"""Mock pollution-source candidates for the Pune AOI.

Provides ``get_mock_candidates()`` → list[dict] (no DB required) and a CLI
that inserts the same records into the database via the ``PollutionSource``
ORM model.
"""
from __future__ import annotations

import json
import uuid


# ---------------------------------------------------------------------------
# Mock candidate data (exact values from the data-contract sample)
# ---------------------------------------------------------------------------

_CANDIDATES: list[dict] = [
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "hinjewadi-phase3-construction")),
        "name": "Hinjewadi Phase-III Construction Cluster",
        "type": "construction",
        "description": (
            "Large-scale residential and commercial construction activity in "
            "Hinjewadi Phase III.  Multiple active sites with earth-moving, "
            "concrete batching, and demolition generating fugitive dust."
        ),
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [73.8215, 18.5487],
                    [73.8241, 18.5487],
                    [73.8241, 18.5512],
                    [73.8215, 18.5512],
                    [73.8215, 18.5487],
                ]
            ],
        },
        "permit_id": "PMC/CONST/2026/04781",
        "schedule_start": "07:00",
        "schedule_end": "19:00",
        "near_school": True,
        "school_name": "Vibgyor High School, Balewadi",
        "school_distance_m": 380,
        "near_hospital": False,
        "hospital_name": None,
        "hospital_distance_m": None,
        "dust_suppression_required": True,
        "dust_suppression_observed": False,
        "last_inspection_date": "2026-05-18",
        "violation_count_90d": 3,
    },
    {
        "id": str(
            uuid.uuid5(uuid.NAMESPACE_DNS, "pcmc-industrial-zone-unit14-acc")
        ),
        "name": "Pimpri-Chinchwad Industrial Zone \u2014 Unit 14 (ACC Cement Silo)",
        "type": "industrial",
        "description": (
            "ACC Cement bulk silo and bagging plant in PCMC industrial zone.  "
            "Cement dust emissions from loading/unloading, conveyor transfer "
            "points, and silo venting."
        ),
        "geometry": {
            "type": "Point",
            "coordinates": [73.8193, 18.5548],
        },
        "permit_id": "MPCB/IND/PUN/2024/11923",
        "schedule_start": "06:00",
        "schedule_end": "22:00",
        "near_school": False,
        "school_name": None,
        "school_distance_m": None,
        "near_hospital": True,
        "hospital_name": "Aditya Birla Memorial Hospital",
        "hospital_distance_m": 620,
        "dust_suppression_required": True,
        "dust_suppression_observed": True,
        "last_inspection_date": "2026-06-10",
        "violation_count_90d": 1,
    },
    {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "mumbai-pune-expressway-wakad")),
        "name": "Mumbai\u2013Pune Expressway Entry Corridor (Wakad Toll Plaza)",
        "type": "traffic",
        "description": (
            "High-traffic corridor at the Wakad toll-plaza entry to the "
            "Mumbai\u2013Pune Expressway.  Heavy diesel truck traffic, "
            "stop-and-go congestion, and brake/tyre wear emissions."
        ),
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [73.8168, 18.5491],
                [73.8201, 18.5463],
                [73.8239, 18.5435],
                [73.8274, 18.5411],
            ],
        },
        "permit_id": None,
        "schedule_start": "00:00",
        "schedule_end": "23:59",
        "near_school": True,
        "school_name": "Delhi Public School, Wakad",
        "school_distance_m": 510,
        "near_hospital": False,
        "hospital_name": None,
        "hospital_distance_m": None,
        "dust_suppression_required": False,
        "dust_suppression_observed": False,
        "last_inspection_date": None,
        "violation_count_90d": 0,
    },
    {
        "id": str(
            uuid.uuid5(uuid.NAMESPACE_DNS, "mula-mutha-riverbank-waste-burning")
        ),
        "name": "Mula-Mutha Riverbank Open Waste Burning Site",
        "type": "waste_burning",
        "description": (
            "Unregulated open-air waste burning along the Mula-Mutha riverbank.  "
            "Mixed municipal solid waste, plastics, and agricultural residue "
            "combustion producing PM2.5, CO, and VOCs."
        ),
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [73.8302, 18.5395],
                    [73.8328, 18.5395],
                    [73.8328, 18.5418],
                    [73.8302, 18.5418],
                    [73.8302, 18.5395],
                ]
            ],
        },
        "permit_id": None,
        "schedule_start": None,
        "schedule_end": None,
        "near_school": False,
        "school_name": None,
        "school_distance_m": None,
        "near_hospital": True,
        "hospital_name": "Sahyadri Super Speciality Hospital",
        "hospital_distance_m": 440,
        "dust_suppression_required": False,
        "dust_suppression_observed": False,
        "last_inspection_date": None,
        "violation_count_90d": 7,
    },
]


def get_mock_candidates() -> list[dict]:
    """Return the four mock pollution-source candidates as plain dicts.

    Each dict contains all ``PollutionSource`` fields plus a ``geometry``
    key with the parsed GeoJSON dict (ready for the ranker).
    """
    # Return deep copies to prevent mutation of the module-level data.
    import copy

    return copy.deepcopy(_CANDIDATES)


# ---------------------------------------------------------------------------
# CLI: seed the database
# ---------------------------------------------------------------------------

def _seed_db() -> None:
    """Insert mock candidates into the database."""
    from .candidate_models import PollutionSource
    from .db import get_session

    session = get_session()
    for cand in _CANDIDATES:
        source = PollutionSource(
            name=cand["name"],
            type=cand["type"],
            description=cand["description"],
            geom=json.dumps(cand["geometry"]),
            permit_id=cand["permit_id"],
            schedule_start=cand["schedule_start"],
            schedule_end=cand["schedule_end"],
            near_school=cand["near_school"],
            school_name=cand["school_name"],
            school_distance_m=cand["school_distance_m"],
            near_hospital=cand["near_hospital"],
            hospital_name=cand["hospital_name"],
            hospital_distance_m=cand["hospital_distance_m"],
            dust_suppression_required=cand["dust_suppression_required"],
            dust_suppression_observed=cand["dust_suppression_observed"],
            last_inspection_date=cand["last_inspection_date"],
            violation_count_90d=cand["violation_count_90d"],
        )
        session.add(source)
    session.commit()
    print(f"Seeded {len(_CANDIDATES)} pollution-source candidates.")
    session.close()


if __name__ == "__main__":
    _seed_db()
