"""Tests for the NAAQS + CPCB NAQI math in app.standards.

These are the highest-value tests: every downstream number depends on this being
exactly right, so they're pinned to the data contract sample values.
"""
from __future__ import annotations

import pytest

from app.standards import (
    AVERAGING_PERIODS,
    NAAQS_LIMITS,
    POLLUTANTS,
    aqi_category,
    canonical_unit,
    compute_aqi,
    exceedance_factor,
    sub_index,
)

# The data contract sample's concentrations + expected exceedance factors.
SAMPLE_CONC = {
    "pm25": 148.6,
    "pm10": 387.2,
    "no2": 72.4,
    "so2": 54.8,
    "co": 3.2,
    "o3": 42.1,
}
SAMPLE_EXCEEDANCE = {
    "pm25": 2.48,
    "pm10": 3.87,
    "no2": 0.91,
    "so2": 0.69,
    "co": 0.80,
    "o3": 0.42,
}


class TestExceedanceFactor:
    def test_matches_sample_for_all_pollutants(self):
        for p in POLLUTANTS:
            got = exceedance_factor(p, SAMPLE_CONC[p])
            assert got == SAMPLE_EXCEEDANCE[p], (
                f"{p}: {got} != {SAMPLE_EXCEEDANCE[p]}"
            )

    def test_round_half_up_not_bankers(self):
        # 54.8/80 = 0.685 -> 0.69 (ROUND_HALF_UP), not 0.68 (banker's).
        assert exceedance_factor("so2", 54.8) == 0.69
        # 2.5 / 1 unit-style: 0.125 -> 0.13? no limit of 1; use pm25: 7.5/60=0.125
        assert exceedance_factor("pm25", 7.5) == 0.13  # 0.125 half-up -> 0.13

    def test_none_for_unknown(self):
        assert exceedance_factor("nox", 10) is None

    def test_none_for_bad_concentration(self):
        assert exceedance_factor("pm10", None) is None
        assert exceedance_factor("pm10", -5) == -0.05  # ratio still defined; sign kept


class TestNaaqsUnits:
    def test_co_is_mg_per_m3(self):
        assert canonical_unit("co") == "mg/m³"

    def test_others_are_ug_per_m3(self):
        for p in ("pm25", "pm10", "no2", "so2", "o3"):
            assert canonical_unit(p) == "µg/m³"

    def test_averaging_periods_present(self):
        for p in POLLUTANTS:
            assert AVERAGING_PERIODS[p] in ("24hr", "8hr")
        assert AVERAGING_PERIODS["co"] == "8hr"
        assert AVERAGING_PERIODS["pm10"] == "24hr"


class TestSubIndex:
    def test_pm10_anchors(self):
        assert sub_index("pm10", 0) == 0
        assert sub_index("pm10", 50) == 50
        assert sub_index("pm10", 100) == 100
        # AQI 310 sits in band 301-400 (conc 351-430).
        assert sub_index("pm10", 358) == 310

    def test_supports_extreme_values_above_500(self):
        # Extreme event: PM10 well above the standard; AQI must be > 500.
        assert sub_index("pm10", 600) > 500
        assert sub_index("pm25", 500) > 500


class TestComputeAqi:
    def test_dominant_is_max_subindex(self):
        r = compute_aqi(SAMPLE_CONC)
        assert r.total_aqi == max(r.sub_indices.values())
        # With strict CPCB math, PM10=387 -> AQI 346 (NOT the sample's 310;
        # the sample is internally inconsistent — see README note).
        assert r.dominant_pollutant == "pm10"
        assert r.category == "Very Poor"

    def test_target_scenario_aqi_310(self):
        # The seed/mock anchors PM10 so the *computed* AQI is exactly 310.
        conc = {
            "pm25": 125.0, "pm10": 358.0, "no2": 72.0,
            "so2": 55.0, "co": 3.2, "o3": 42.0,
        }
        r = compute_aqi(conc)
        assert r.total_aqi == 310
        assert r.dominant_pollutant == "pm10"
        assert r.category == "Very Poor"

    def test_insufficient_data_without_pm(self):
        r = compute_aqi({"no2": 40, "so2": 40, "co": 1.0})
        assert r.total_aqi is None  # no PM species

    def test_insufficient_data_too_few(self):
        r = compute_aqi({"pm10": 100})
        assert r.total_aqi is None  # only 1 pollutant

    def test_extreme_aqi_above_500(self):
        r = compute_aqi({"pm25": 500, "pm10": 600, "no2": 300, "so2": 800, "co": 20, "o3": 300})
        assert r.total_aqi is not None
        assert r.total_aqi > 500


class TestCategory:
    @pytest.mark.parametrize("aqi,cat", [
        (50, "Good"), (100, "Satisfactory"), (200, "Moderate"),
        (300, "Poor"), (400, "Very Poor"), (401, "Severe"), (310, "Very Poor"),
    ])
    def test_boundaries(self, aqi, cat):
        assert aqi_category(aqi) == cat
