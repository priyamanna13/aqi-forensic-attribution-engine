"""Tests for app.validators: CPCB edge-case handling."""
from __future__ import annotations

from app.validators import ReadingValidator


def _good():
    return {"pm25": 148.6, "pm10": 387.2, "no2": 72.4, "so2": 54.8, "co": 3.2, "o3": 42.1}


class TestSentinels:
    def test_minus_999_flagged_not_passed(self):
        r = ReadingValidator().validate({**_good(), "pm25": -999})
        assert not r.is_valid or "pm25" not in r.clean
        assert "pm25" in r.dropped
        # The sentinel must never reach clean as a real integer.
        assert r.clean.get("pm25") != -999

    def test_null_flagged(self):
        r = ReadingValidator().validate({**_good(), "pm25": None})
        assert "pm25" not in r.clean

    def test_zero_treated_as_missing(self):
        r = ReadingValidator().validate({**_good(), "pm25": 0})
        assert "pm25" not in r.clean
        assert any(w.pollutant == "pm25" and w.code == "missing" for w in r.warnings)

    def test_string_na_flagged(self):
        r = ReadingValidator().validate({**_good(), "pm25": "NA"})
        assert "pm25" not in r.clean


class TestUnitNormalization:
    def test_co_ugm3_converted_to_mgm3(self):
        v = ReadingValidator(co_input_unit="ug/m3")
        r = v.validate({**_good(), "co": 3200})  # 3200 µg/m³ -> 3.2 mg/m³
        assert r.clean["co"] == 3.2
        assert any(w.code == "unit_converted" for w in r.warnings)

    def test_co_default_mgm3_not_converted(self):
        v = ReadingValidator()  # default mg/m3
        r = v.validate({**_good(), "co": 3.2})
        assert r.clean["co"] == 3.2
        assert not any(w.code == "unit_converted" for w in r.warnings)


class TestRejection:
    def test_negative_dropped_as_error(self):
        r = ReadingValidator().validate({**_good(), "pm25": -5})
        assert "pm25" not in r.clean
        assert any(e.code == "negative" for e in r.errors)

    def test_implausible_dropped_as_error(self):
        r = ReadingValidator().validate({**_good(), "pm25": 5000})
        assert "pm25" not in r.clean
        assert any(e.code == "implausible" for e in r.errors)

    def test_partial_data_valid_when_aqi_computable(self):
        # Drop 2 pollutants; still 4 incl. PM10 -> valid.
        raw = {"pm10": 100, "no2": 40, "so2": 40, "co": 1.0}
        r = ReadingValidator().validate(raw)
        assert r.is_valid

    def test_invalid_when_no_pm(self):
        raw = {"no2": 40, "so2": 40, "co": 1.0}
        r = ReadingValidator().validate(raw)
        assert not r.is_valid

    def test_report_to_log_shape(self):
        r = ReadingValidator().validate(_good())
        log = r.to_log()
        assert {"is_valid", "n_clean", "errors", "warnings", "dropped"} <= set(log)


class TestCoercion:
    def test_numeric_string_parsed(self):
        r = ReadingValidator().validate({**_good(), "pm25": "150.5"})
        assert r.clean["pm25"] == 150.5

    def test_garbage_string_dropped(self):
        r = ReadingValidator().validate({**_good(), "pm25": "abc"})
        assert "pm25" not in r.clean
