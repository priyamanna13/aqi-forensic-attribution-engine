"""Tests for the Source Candidate Ranking Engine (Prompt 2C).

Covers:
  - wind_alignment_score (upwind, perpendicular)
  - chemical_match_score (construction + crustal_dominant)
  - temporal_match_score (during / outside schedule)
  - proximity_score (near / far)
  - compute_confidence bounds
  - rank_candidates ordering and rank field
"""
from __future__ import annotations

import sys
import os

# Ensure the project root is on sys.path so ``app`` is importable.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.scoring import (
    chemical_match_score,
    compliance_penalty,
    compute_confidence,
    proximity_score,
    temporal_match_score,
    wind_alignment_score,
)
from app.ranker import rank_candidates
from app.seed_candidates import get_mock_candidates


# ── Wind alignment ────────────────────────────────────────────────────────

class TestWindAlignment:
    def test_directly_upwind_high_score(self):
        """Source directly upwind (bearing=290, wind=290) → >0.85."""
        score = wind_alignment_score(
            source_bearing=290, wind_direction=290, half_angle=18
        )
        assert score > 0.85, f"Expected >0.85, got {score}"

    def test_perpendicular_low_score(self):
        """Source perpendicular (bearing=200, wind=290, half_angle=18) → <0.3."""
        score = wind_alignment_score(
            source_bearing=200, wind_direction=290, half_angle=18
        )
        assert score < 0.3, f"Expected <0.3, got {score}"


# ── Chemical match ────────────────────────────────────────────────────────

class TestChemicalMatch:
    def test_construction_crustal_dominant(self):
        """construction + crustal_dominant → >0.8."""
        score = chemical_match_score(
            "construction", {"signature_class": "crustal_dominant"}
        )
        assert score > 0.8, f"Expected >0.8, got {score}"


# ── Temporal match ────────────────────────────────────────────────────────

class TestTemporalMatch:
    def test_event_during_schedule(self):
        """08:30 during 07:00–19:00 → 1.0."""
        score = temporal_match_score("08:30", "07:00", "19:00")
        assert score == 1.0, f"Expected 1.0, got {score}"

    def test_event_outside_schedule(self):
        """23:00 outside 07:00–19:00 → 0.3."""
        score = temporal_match_score("23:00", "07:00", "19:00")
        assert score == 0.3, f"Expected 0.3, got {score}"


# ── Proximity ─────────────────────────────────────────────────────────────

class TestProximity:
    def test_near_station(self):
        """1 km with max 5 km → >0.7."""
        score = proximity_score(distance_km=1.0, max_range_km=5.0)
        assert score > 0.7, f"Expected >0.7, got {score}"

    def test_far_from_station(self):
        """4 km with max 5 km → <0.5."""
        score = proximity_score(distance_km=4.0, max_range_km=5.0)
        assert score < 0.5, f"Expected <0.5, got {score}"


# ── Confidence ────────────────────────────────────────────────────────────

class TestConfidence:
    def test_confidence_in_range(self):
        """Confidence score is always between 0.0 and 1.0."""
        for w in (0.0, 0.5, 1.0):
            for c in (0.0, 0.5, 1.0):
                for t in (0.0, 0.5, 1.0):
                    for p in (0.0, 0.5, 1.0):
                        for pen in (0.0, 0.5, 1.0):
                            conf = compute_confidence(w, c, t, p, pen)
                            assert 0.0 <= conf <= 1.0, (
                                f"Out of range: {conf} for "
                                f"w={w}, c={c}, t={t}, p={p}, pen={pen}"
                            )


# ── Ranker integration ────────────────────────────────────────────────────

class TestRankCandidates:
    """Integration test using mock candidates from seed_candidates."""

    STATION_COORDS = (73.8567, 18.5308)
    WIND_DIR = 290
    HALF_ANGLE = 18
    MAX_RANGE_KM = 4.5
    CHEM_FP = {"signature_class": "crustal_dominant"}
    EVENT_TIME = "08:30"

    def _ranked(self) -> list[dict]:
        return rank_candidates(
            candidates=get_mock_candidates(),
            station_coords=self.STATION_COORDS,
            wind_direction=self.WIND_DIR,
            half_angle=self.HALF_ANGLE,
            max_range_km=self.MAX_RANGE_KM,
            chemical_fingerprint=self.CHEM_FP,
            event_time=self.EVENT_TIME,
        )

    def test_sorted_descending_by_confidence(self):
        """Output list is sorted descending by confidence_score."""
        ranked = self._ranked()
        scores = [r["score_breakdown"]["confidence_score"] for r in ranked]
        assert scores == sorted(scores, reverse=True), (
            f"Not sorted descending: {scores}"
        )

    def test_rank_starts_at_one(self):
        """rank field starts at 1 and increments by 1."""
        ranked = self._ranked()
        ranks = [r["rank"] for r in ranked]
        assert ranks == list(range(1, len(ranked) + 1)), (
            f"Unexpected ranks: {ranks}"
        )

    def test_output_has_required_keys(self):
        """Each result dict has all required top-level keys."""
        required = {
            "rank",
            "id",
            "name",
            "type",
            "description",
            "geometry",
            "distance_from_station_km",
            "bearing_from_station_deg",
            "compliance_profile",
            "score_breakdown",
        }
        ranked = self._ranked()
        for entry in ranked:
            assert required.issubset(
                entry.keys()
            ), f"Missing keys: {required - entry.keys()}"

    def test_four_candidates_returned(self):
        """All 4 mock candidates are returned."""
        ranked = self._ranked()
        assert len(ranked) == 4, f"Expected 4, got {len(ranked)}"
