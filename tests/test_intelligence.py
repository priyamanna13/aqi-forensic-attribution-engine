"""Tests for the actionable intelligence generator (Prompt 2D)."""
from __future__ import annotations

import pytest

from app.intelligence import (
    build_actionable_intelligence,
    compute_enforcement_priority,
    generate_localized_advisory,
    generate_priority_justification,
    recommend_actions,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def mock_ranked():
    """Minimal ranked candidates matching the data-contract shape."""
    return [
        {
            "rank": 1,
            "name": "Hinjewadi Phase-III Construction Cluster",
            "type": "construction",
            "description": "Large-scale construction...",
            "score_breakdown": {
                "wind_alignment_score": 0.92,
                "chemical_match_score": 0.88,
                "temporal_match_score": 0.95,
                "proximity_score": 0.78,
                "compliance_penalty": 0.15,
                "confidence_score": 0.91,
            },
            "compliance_profile": {
                "permit_id": "PMC/CONST/2026/04781",
                "schedule_start": "07:00",
                "schedule_end": "19:00",
                "operating_at_event_time": True,
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
        },
        {
            "rank": 2,
            "name": "Mula-Mutha Riverbank Open Waste Burning Site",
            "type": "waste_burning",
            "description": "Unauthorized waste burning...",
            "score_breakdown": {
                "confidence_score": 0.62,
            },
            "compliance_profile": {
                "near_school": False,
                "school_distance_m": None,
                "near_hospital": True,
                "hospital_name": "Sahyadri Super Speciality Hospital",
                "hospital_distance_m": 440,
                "dust_suppression_required": False,
                "dust_suppression_observed": False,
                "violation_count_90d": 7,
            },
        },
    ]


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
class TestEnforcementPriority:
    def test_priority_between_0_and_1(self, mock_ranked):
        p = compute_enforcement_priority(mock_ranked)
        assert 0.0 <= p <= 1.0

    def test_near_school_boosts_above_0_8(self, mock_ranked):
        p = compute_enforcement_priority(mock_ranked)
        assert p > 0.8, f"Expected priority > 0.8 with near-school candidate, got {p}"

    def test_empty_candidates_returns_zero(self):
        assert compute_enforcement_priority([]) == 0.0


class TestRecommendActions:
    def test_actions_is_nonempty_list(self):
        actions = recommend_actions("construction", 0.94)
        assert isinstance(actions, list)
        assert len(actions) > 0

    def test_actions_are_strings(self):
        actions = recommend_actions("construction", 0.94)
        assert all(isinstance(a, str) for a in actions)


class TestLocalizedAdvisory:
    def test_advisory_has_three_languages(self, mock_ranked):
        adv = generate_localized_advisory(
            "Shivajinagar", 310, "pm10", mock_ranked[0], 0.94
        )
        assert "en" in adv
        assert "hi" in adv
        assert "mr" in adv

    def test_advisory_strings_nonempty(self, mock_ranked):
        adv = generate_localized_advisory(
            "Shivajinagar", 310, "pm10", mock_ranked[0], 0.94
        )
        for lang in ("en", "hi", "mr"):
            assert len(adv[lang]) > 0, f"Advisory for {lang} is empty"


class TestJustification:
    def test_mentions_top_candidate_name(self, mock_ranked):
        text = generate_priority_justification(mock_ranked)
        # Should mention some part of the top candidate name.
        assert "Hinjewadi" in text or "Construction" in text or "construction" in text


class TestBuildActionableIntelligence:
    def test_full_block_keys(self, mock_ranked):
        block = build_actionable_intelligence(
            mock_ranked, "Shivajinagar", 310, "pm10"
        )
        expected_keys = {
            "enforcement_priority",
            "priority_justification",
            "recommended_actions",
            "estimated_response_time_min",
            "localized_advisory",
            "notification_channels",
            "field_team_assignment",
        }
        assert expected_keys <= set(block.keys())

    def test_field_team_has_required_keys(self, mock_ranked):
        block = build_actionable_intelligence(
            mock_ranked, "Shivajinagar", 310, "pm10"
        )
        ft = block["field_team_assignment"]
        assert "team_id" in ft
        assert "team_lead" in ft
        assert "contact" in ft
        assert "eta_minutes" in ft
