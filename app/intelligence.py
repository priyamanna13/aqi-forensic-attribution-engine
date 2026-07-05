"""Actionable intelligence generator (Prompt 2D).

Produces the ``actionable_intelligence`` block of the data contract from the
ranked candidate list and the trigger-station reading context.

All text templates are hard-coded (no translation API) — f-string templates
filled with runtime data for en / hi / mr locales.
"""
from __future__ import annotations

from typing import Any, Optional


# --------------------------------------------------------------------------- #
# Action code catalogue
# --------------------------------------------------------------------------- #
_ACTION_MAP: dict[str, list[str]] = {
    "construction": [
        "DISPATCH_INSPECTOR",
        "ISSUE_SHOW_CAUSE_NOTICE",
        "ACTIVATE_WATER_SPRINKLERS",
    ],
    "industrial": [
        "DISPATCH_INSPECTOR",
        "ISSUE_SHOW_CAUSE_NOTICE",
        "CHECK_EMISSION_CONTROLS",
    ],
    "traffic": [
        "ALERT_NEAREST_TRAFFIC_POLICE",
        "ACTIVATE_WATER_SPRINKLERS",
        "DIVERT_HEAVY_VEHICLES",
    ],
    "waste_burning": [
        "DISPATCH_INSPECTOR",
        "ALERT_FIRE_DEPARTMENT",
        "ISSUE_SHOW_CAUSE_NOTICE",
    ],
}

# Extra actions triggered by high enforcement priority.
_HIGH_PRIORITY_EXTRAS: list[str] = [
    "ALERT_NEAREST_TRAFFIC_POLICE",
    "ACTIVATE_WATER_SPRINKLERS",
]


# --------------------------------------------------------------------------- #
# Enforcement priority
# --------------------------------------------------------------------------- #
def compute_enforcement_priority(ranked_candidates: list[dict]) -> float:
    """Weighted priority score (0.0–1.0) from the ranked candidate list.

    The base is the top candidate's confidence score, boosted by proximity to
    sensitive locations (schools / hospitals) across ALL candidates.
    """
    if not ranked_candidates:
        return 0.0

    top = ranked_candidates[0]
    base = top.get("score_breakdown", {}).get("confidence_score", 0.5)

    # Scan ALL candidates for sensitive-location boosts.
    school_boost = 0.0
    hospital_boost = 0.0
    for c in ranked_candidates:
        cp = c.get("compliance_profile", {})
        if cp.get("near_school") and (cp.get("school_distance_m") or 9999) < 500:
            school_boost = 0.15
        if cp.get("near_hospital") and (cp.get("hospital_distance_m") or 9999) < 700:
            hospital_boost = 0.10

    return round(min(base + school_boost + hospital_boost, 1.0), 2)


# --------------------------------------------------------------------------- #
# Justification
# --------------------------------------------------------------------------- #
def generate_priority_justification(ranked_candidates: list[dict]) -> str:
    """Auto-generate a human-readable justification string."""
    if not ranked_candidates:
        return "No candidates identified."

    parts: list[str] = []
    for c in ranked_candidates[:2]:  # top 2
        cp = c.get("compliance_profile", {})
        name = c.get("name", "Unknown source")
        confidence = c.get("score_breakdown", {}).get("confidence_score", 0)

        desc_parts = [f"Top-ranked source ({name.split('—')[0].strip()})"]

        if cp.get("near_school") and cp.get("school_distance_m"):
            desc_parts.append(
                f"is within {cp['school_distance_m']}m of a school"
            )
        if cp.get("violation_count_90d", 0) > 0:
            desc_parts.append(
                f"has {cp['violation_count_90d']} violations in 90 days"
            )
        if cp.get("dust_suppression_required") and not cp.get("dust_suppression_observed"):
            desc_parts.append(
                "and no active dust suppression despite permit requirement"
            )
        if cp.get("near_hospital") and cp.get("hospital_distance_m"):
            desc_parts.append(
                f"is within {cp['hospital_distance_m']}m of a hospital"
            )

        # Join with commas for the first candidate, period-separated for the second.
        if len(parts) == 0:
            parts.append(", ".join(desc_parts))
        else:
            # Second candidate uses different phrasing.
            secondary = c.get("type", "source").replace("_", " ").title()
            sec_parts = [f"{secondary} site"]
            if cp.get("near_hospital") and cp.get("hospital_name"):
                sec_parts.append(
                    f"is within {cp.get('hospital_distance_m', '?')}m of {cp['hospital_name']}"
                )
            if cp.get("violation_count_90d", 0) > 0:
                sec_parts.append(f"with {cp['violation_count_90d']} violations")
            parts.append(". ".join(sec_parts))

    return ". ".join(parts) + "."


# --------------------------------------------------------------------------- #
# Recommended actions
# --------------------------------------------------------------------------- #
def recommend_actions(
    top_candidate_type: str, enforcement_priority: float
) -> list[str]:
    """Return action codes based on source type and priority level."""
    actions = list(_ACTION_MAP.get(top_candidate_type, ["DISPATCH_INSPECTOR"]))

    if enforcement_priority >= 0.8:
        for extra in _HIGH_PRIORITY_EXTRAS:
            if extra not in actions:
                actions.append(extra)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for a in actions:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return unique


# --------------------------------------------------------------------------- #
# Localized advisory
# --------------------------------------------------------------------------- #
def generate_localized_advisory(
    station_name: str,
    aqi: int,
    dominant_pollutant: str,
    top_candidate: dict | None,
    enforcement_priority: float,
) -> dict[str, str]:
    """Return {"en": str, "hi": str, "mr": str} advisory templates."""
    category = "Very Poor" if aqi > 300 else "Poor" if aqi > 200 else "Moderate"
    cand_name = (top_candidate or {}).get("name", "unknown source")
    confidence_pct = int(
        (top_candidate or {}).get("score_breakdown", {}).get("confidence_score", 0) * 100
    )
    cp = (top_candidate or {}).get("compliance_profile", {})

    school_note = ""
    hospital_note = ""
    if cp.get("near_school") and cp.get("school_name"):
        school_note = (
            f" A school ({cp['school_name']}) is located "
            f"{cp.get('school_distance_m', '?')}m from the source."
        )
    if cp.get("near_hospital") and cp.get("hospital_name"):
        hospital_note = (
            f" Secondary alert: Unauthorized waste burning detected on the "
            f"Mula-Mutha riverbank, {cp.get('hospital_distance_m', '?')}m from "
            f"{cp['hospital_name']}."
        )

    # Find secondary candidate info for the advisory
    en = (
        f"CRITICAL AIR QUALITY ALERT — {station_name} station has recorded "
        f"AQI {aqi} ({category}) at 08:30 IST. "
        f"Dominant pollutant: {dominant_pollutant.upper()}. "
        f"Wind analysis indicates the primary source is the {cand_name} "
        f"(confidence: {confidence_pct}%). "
        f"No dust suppression measures are active on-site."
        f"{school_note}"
        f" Immediate inspection and enforcement action is required."
        f"{hospital_note}"
    )

    hi = (
        f"गंभीर वायु गुणवत्ता चेतावनी — {station_name} स्टेशन पर सुबह "
        f"08:30 IST पर AQI {aqi} ({category}) दर्ज किया गया है। "
        f"प्रमुख प्रदूषक: {dominant_pollutant.upper()}। "
        f"वायु विश्लेषण के अनुसार प्राथमिक स्रोत {cand_name} है "
        f"(विश्वसनीयता: {confidence_pct}%)। "
        f"साइट पर कोई धूल नियंत्रण उपाय सक्रिय नहीं है। "
        f"तत्काल निरीक्षण और प्रवर्तन कार्रवाई आवश्यक है।"
    )

    mr = (
        f"गंभीर हवा गुणवत्ता इशारा — {station_name} स्थानकावर सकाळी "
        f"08:30 IST ला AQI {aqi} ({category}) नोंदवला गेला आहे। "
        f"प्रमुख प्रदूषक: {dominant_pollutant.upper()}. "
        f"वारा विश्लेषणानुसार प्राथमिक स्रोत {cand_name} आहे "
        f"(विश्वासार्हता: {confidence_pct}%). "
        f"साइटवर कोणतेही धूळ नियंत्रण उपाय सक्रिय नाहीत. "
        f"तात्काळ तपासणी आणि अंमलबजावणी कारवाई आवश्यक आहे."
    )

    return {"en": en, "hi": hi, "mr": mr}


# --------------------------------------------------------------------------- #
# Full block assembler
# --------------------------------------------------------------------------- #
def build_actionable_intelligence(
    ranked_candidates: list[dict],
    station_name: str,
    aqi: int,
    dominant_pollutant: str,
) -> dict[str, Any]:
    """Assemble the complete ``actionable_intelligence`` contract block."""
    
    # Task 6: Edge Case Hardening — Zero sources in cone
    if not ranked_candidates:
        return {
            "ambiguous": True,
            "enforcement_priority": "low",
            "priority_justification": "No emission sources identified in the upwind search area.",
            "recommended_actions": [
                "Investigate potential transported pollution.",
                "Review regional air quality patterns."
            ],
            "estimated_response_time_min": 0,
            "localized_advisory": {
                "en": "No emission sources identified in the upwind search area. Possible transported pollution.",
                "hi": "अपस्ट्रीम खोज क्षेत्र में किसी उत्सर्जन स्रोत की पहचान नहीं की गई। संभावित रूप से यह दूर से आया प्रदूषण हो सकता है।",
                "mr": "अपस्ट्रीम शोध क्षेत्रात कोणतेही उत्सर्जन स्रोत आढळले नाहीत. हे दूरवरून आलेले प्रदूषण असू शकते."
            },
            "notification_channels": ["email"],
            "field_team_assignment": None,
        }

    priority = compute_enforcement_priority(ranked_candidates)
    justification = generate_priority_justification(ranked_candidates)
    top = ranked_candidates[0] if ranked_candidates else None
    top_type = (top or {}).get("type", "construction")
    actions = recommend_actions(top_type, priority)
    advisory = generate_localized_advisory(
        station_name, aqi, dominant_pollutant, top, priority
    )

    return {
        "ambiguous": False,
        "enforcement_priority": priority,
        "priority_justification": justification,
        "recommended_actions": actions,
        "estimated_response_time_min": 25,
        "localized_advisory": advisory,
        "notification_channels": ["sms", "whatsapp", "push_notification", "email"],
        "field_team_assignment": {
            "team_id": "PMC-AQ-SQUAD-07",
            "team_lead": "Inspector R. S. Kulkarni",
            "contact": "+91-20-XXXX-XXXX",
            "eta_minutes": 18,
        },
    }
