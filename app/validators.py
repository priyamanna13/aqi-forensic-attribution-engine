"""Input validation for raw CPCB CAAQMS readings.

CPCB's real-time feed is messy: offline sensors report ``-999``, ``0`` or null;
units are sometimes inconsistent (CO occasionally arrives in µg/m³); and
transient garbage values appear. This module normalises and screens each
pollutant before it can reach the database, and produces a structured
``ValidationReport`` so the pipeline can log *why* a reading was rejected.

Design
------
* Validation runs identically on live and mock streams (one code path).
* Sentinel/missing values are **flagged**, never silently coerced to 0.
* A reading is *valid* (persistable) when it has enough pollutants to compute an
  AQI (>= 3 incl. a PM species) after cleaning. Partial data is fine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .standards import POLLUTANTS, MG_PER_M3_POLLUTANTS, canonical_unit

#: Values CPCB uses to denote "no data" / offline sensor. Tunable via env.
MISSING_SENTINELS: frozenset = frozenset({-999, -9999, None})

#: Zero is treated as missing for pollutant concentrations (a real PM2.5 of
#: exactly 0.0 µg/m³ is not physically meaningful in ambient air). This mirrors
#: the prompt's requirement to flag/ reject ``0`` rather than pass it through.
TREAT_ZERO_AS_MISSING: bool = True

#: Sanity upper bounds per pollutant (canonical units) to catch transient
#: garbage values that pass the basic checks. Generous, not restrictive.
_PLAUSIBLE_MAX: dict[str, float] = {
    "pm25": 1000.0,
    "pm10": 2000.0,
    "no2": 1000.0,
    "so2": 2000.0,
    "co": 60.0,
    "o3": 1000.0,
}


@dataclass
class FieldIssue:
    pollutant: str
    code: str  # "missing" | "negative" | "implausible" | "unit_converted"
    message: str
    raw: Any = None


@dataclass
class ValidationReport:
    """Outcome of validating one raw reading."""

    is_valid: bool = False
    errors: list[FieldIssue] = field(default_factory=list)
    warnings: list[FieldIssue] = field(default_factory=list)
    #: cleaned, canonical-unit concentrations ready for AQI computation / persist.
    clean: dict[str, float] = field(default_factory=dict)
    #: pollutants dropped during validation (for diagnostics).
    dropped: list[str] = field(default_factory=list)

    def to_log(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "n_clean": len(self.clean),
            "errors": [e.__dict__ for e in self.errors],
            "warnings": [w.__dict__ for w in self.warnings],
            "dropped": self.dropped,
        }


def _to_float(v: Any) -> Optional[float]:
    """Coerce CPCB-ish JSON values to float, returning None if not numeric."""
    if v is None:
        return None
    if isinstance(v, bool):  # guard: bools are ints in Python
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() in {"na", "n/a", "null", "none", "-"}:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


class ReadingValidator:
    """Validate + normalise one raw reading into canonical-unit concentrations.

    Parameters
    ----------
    co_input_unit:
        Unit the upstream feed reports CO in. Defaults to ``"mg/m3"`` (CPCB's
        standard); set to ``"ug/m3"`` if a particular feed sends CO in µg/m³ so
        it is divided by 1000 on the way in.
    """

    def __init__(
        self,
        co_input_unit: str = "mg/m3",
        missing_sentinels: frozenset = MISSING_SENTINELS,
        treat_zero_as_missing: bool = TREAT_ZERO_AS_MISSING,
    ) -> None:
        self.co_input_unit = co_input_unit.lower().replace("³", "3")
        self.missing_sentinels = missing_sentinels
        self.treat_zero_as_missing = treat_zero_as_missing

    # ------------------------------------------------------------------ #
    def validate(self, raw: dict[str, Any]) -> ValidationReport:
        """Validate a raw reading dict keyed by pollutant name."""
        report = ValidationReport()

        for pollutant in POLLUTANTS:
            if pollutant not in raw:
                continue
            value = self._validate_field(pollutant, raw[pollutant], report)
            if value is not None:
                report.clean[pollutant] = value
            else:
                report.dropped.append(pollutant)

        # A reading is persistable iff it can yield an AQI: enough pollutants
        # and at least one PM species. (Final AQI computation lives in standards.)
        has_pm = any(p in report.clean for p in ("pm25", "pm10"))
        report.is_valid = len(report.clean) >= 3 and has_pm
        if not report.is_valid and not report.errors:
            report.warnings.append(
                FieldIssue(
                    pollutant="-",
                    code="insufficient_data",
                    message=(
                        f"Only {len(report.clean)} valid pollutant(s); need >=3 "
                        "including a PM species to compute AQI."
                    ),
                )
            )
        return report

    # ------------------------------------------------------------------ #
    def _validate_field(
        self, pollutant: str, raw_value: Any, report: ValidationReport
    ) -> Optional[float]:
        # 1. Missing / sentinel -> flag, drop.
        if raw_value in self.missing_sentinels or raw_value is None:
            report.warnings.append(
                FieldIssue(
                    pollutant,
                    "missing",
                    f"{pollutant}: missing/sentinel value {raw_value!r}; dropped.",
                    raw_value,
                )
            )
            return None

        numeric = _to_float(raw_value)
        if numeric is None:
            report.warnings.append(
                FieldIssue(
                    pollutant,
                    "missing",
                    f"{pollutant}: non-numeric value {raw_value!r}; dropped.",
                    raw_value,
                )
            )
            return None

        # 2. Zero as missing (ambient pollutants are never exactly 0).
        if numeric == 0.0 and self.treat_zero_as_missing:
            report.warnings.append(
                FieldIssue(
                    pollutant,
                    "missing",
                    f"{pollutant}: zero treated as missing; dropped.",
                    raw_value,
                )
            )
            return None

        # 3. Negative -> error (impossible concentration).
        if numeric < 0:
            report.errors.append(
                FieldIssue(
                    pollutant,
                    "negative",
                    f"{pollutant}: negative concentration {numeric}; dropped.",
                    raw_value,
                )
            )
            return None

        # 4. Unit normalisation (CO only): convert to canonical mg/m³ *before*
        #    plausibility checks, so a feed reporting CO in µg/m³ isn't rejected.
        if pollutant == "co" and self.co_input_unit == "ug/m3":
            numeric = numeric / 1000.0
            report.warnings.append(
                FieldIssue(
                    pollutant,
                    "unit_converted",
                    f"{pollutant}: converted µg/m³ -> mg/m³.",
                    raw_value,
                )
            )

        # 5. Plausibility ceiling -> error, drop.
        ceiling = _PLAUSIBLE_MAX.get(pollutant)
        if ceiling is not None and numeric > ceiling:
            report.errors.append(
                FieldIssue(
                    pollutant,
                    "implausible",
                    f"{pollutant}: {numeric} {canonical_unit(pollutant)} exceeds "
                    f"plausible ceiling {ceiling}; dropped.",
                    raw_value,
                )
            )
            return None

        return round(numeric, 3)
