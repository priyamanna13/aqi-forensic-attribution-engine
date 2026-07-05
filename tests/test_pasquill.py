"""Tests for app.pasquill — stability classification & cardinal directions."""
from __future__ import annotations

import pytest

from app.pasquill import classify_stability, degrees_to_cardinal


class TestClassifyStability:
    """Core Pasquill-Gifford table scenarios."""

    def test_strong_sun_low_wind_gives_A(self):
        """Strong insolation + calm wind → extremely unstable (A)."""
        result = classify_stability(5, 0, True, 60)
        assert result["pasquill_class"] == "A"

    def test_overcast_moderate_wind_gives_D(self):
        """Overcast + moderate wind → neutral (D)."""
        result = classify_stability(25, 8, True)
        assert result["pasquill_class"] == "D"

    def test_nighttime_calm_gives_F(self):
        """Clear calm night → moderately stable (F)."""
        result = classify_stability(3, 0, False)
        assert result["pasquill_class"] == "F"

    def test_contract_scenario_gives_D_with_coefficients(self):
        """Contract scenario: 14.5 km/h, 3 oktas, daytime, 30° sun → D."""
        result = classify_stability(14.5, 3, True, 30)
        assert result["pasquill_class"] == "D"
        assert result["dispersion_coefficient"]["sigma_y"] == pytest.approx(0.22)
        assert result["dispersion_coefficient"]["sigma_z"] == pytest.approx(0.08)


class TestDegreesToCardinal:
    """16-point compass rose conversion."""

    @pytest.mark.parametrize(
        "deg, expected",
        [
            (0, "N"),
            (90, "E"),
            (180, "S"),
            (270, "W"),
            (290, "WNW"),
        ],
    )
    def test_cardinal_directions(self, deg: int, expected: str):
        assert degrees_to_cardinal(deg) == expected


class TestDispersionCoefficients:
    """Dispersion coefficients are positive floats for all classes A-F."""

    @pytest.mark.parametrize("cls", ["A", "B", "C", "D", "E", "F"])
    def test_positive_coefficients(self, cls: str):
        from app.pasquill import dispersion_coefficients

        coeffs = dispersion_coefficients(cls)
        assert isinstance(coeffs["sigma_y"], float)
        assert isinstance(coeffs["sigma_z"], float)
        assert coeffs["sigma_y"] > 0
        assert coeffs["sigma_z"] > 0
