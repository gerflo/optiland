from __future__ import annotations

from pathlib import Path

import math
import pytest
import yaml

from optiland.materials import Material
from optiland.materials.winlens_glassplus import find_glassplus_record


def _glassplus_path() -> Path:
    return Path.cwd().parent / "WinLens Library 2002" / "WinLens3DBasic" / "stglassplus.dat"


def _reference_coefficients(name: str, reference: str) -> tuple[str, str]:
    material = Material(name, reference=reference)
    with Path(material.filename).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    data = payload["DATA"][0]
    return data["type"], data["coefficients"]


def _numbers_from_coefficient_string(text: str) -> list[float]:
    return [float(token) for token in str(text).split()]


def _formula_3_nd_vd(coefficients: list[float]) -> tuple[float, float]:
    def n_value(wavelength: float) -> float:
        n_squared = coefficients[0]
        exponents = [2.0, -2.0, -4.0, -6.0, -8.0]
        for coefficient, exponent in zip(coefficients[1:], exponents):
            n_squared += coefficient * (wavelength**exponent)
        return math.sqrt(n_squared)

    n_d = n_value(0.5875618)
    n_f = n_value(0.4861327)
    n_c = n_value(0.6562725)
    v_d = (n_d - 1.0) / (n_f - n_c)
    return n_d, v_d


def test_find_glassplus_record_decodes_schott_formula_2_coefficients() -> None:
    record = find_glassplus_record(_glassplus_path(), "N-BAF10", "Schott")

    assert record is not None
    assert record.reference == "Schott"
    assert record.formula_type == "formula 2"

    formula_type, coefficient_string = _reference_coefficients("N-BAF10", "Schott")
    assert record.formula_type == formula_type
    assert _numbers_from_coefficient_string(record.coefficient_string()) == pytest.approx(
        _numbers_from_coefficient_string(coefficient_string),
    )


def test_find_glassplus_record_decodes_ohara_formula_2_coefficients() -> None:
    record = find_glassplus_record(_glassplus_path(), "S-BAH10", "Ohara")

    assert record is not None
    assert record.reference == "Ohara"
    assert record.formula_type == "formula 2"

    formula_type, coefficient_string = _reference_coefficients("S-BAH10", "Ohara")
    assert record.formula_type == formula_type
    assert _numbers_from_coefficient_string(record.coefficient_string()) == pytest.approx(
        _numbers_from_coefficient_string(coefficient_string),
    )


def test_find_glassplus_record_decodes_hoya_formula_3_coefficients() -> None:
    record = find_glassplus_record(_glassplus_path(), "BAC4", "Hoya")

    assert record is not None
    assert record.reference == "Hoya"
    assert record.formula_type == "formula 3"

    formula_type, coefficient_string = _reference_coefficients("BAC4", "Hoya")
    assert record.formula_type == formula_type
    assert _numbers_from_coefficient_string(record.coefficient_string()) == pytest.approx(
        _numbers_from_coefficient_string(coefficient_string),
    )


def test_find_glassplus_record_decodes_hikari_formula_3_coefficients() -> None:
    record = find_glassplus_record(_glassplus_path(), "BAF11", "Hikari")

    assert record is not None
    assert record.reference == "Hikari"
    assert record.formula_type == "formula 3"

    formula_type, coefficient_string = _reference_coefficients("BAF11", "Hikari")
    assert record.formula_type == formula_type
    assert _numbers_from_coefficient_string(record.coefficient_string()) == pytest.approx(
        _numbers_from_coefficient_string(coefficient_string),
    )


def test_find_glassplus_record_decodes_sumita_formula_3_coefficients() -> None:
    record = find_glassplus_record(_glassplus_path(), "K-BK7", "Sumita")

    assert record is not None
    assert record.reference == "Sumita"
    assert record.formula_type == "formula 3"

    formula_type, coefficient_string = _reference_coefficients("K-BK7", "SUMITA")
    assert record.formula_type == formula_type
    assert _numbers_from_coefficient_string(record.coefficient_string()) == pytest.approx(
        _numbers_from_coefficient_string(coefficient_string),
        abs=1.5e-4,
    )


def test_find_glassplus_record_corning_code_matches_nd_vd_pattern() -> None:
    record = find_glassplus_record(_glassplus_path(), "BCDB64-61", "Corning")

    assert record is not None
    assert record.reference == "Corning"
    assert record.formula_type == "formula 3"

    n_d, v_d = _formula_3_nd_vd(record.coefficients)
    assert n_d == pytest.approx(1.564, abs=0.002)
    assert v_d == pytest.approx(61.0, abs=0.5)


def test_find_glassplus_record_pilkington_code_matches_nd_vd_pattern() -> None:
    record = find_glassplus_record(_glassplus_path(), "BF606439", "Pilkington")

    assert record is not None
    assert record.reference == "Pilkington"
    assert record.formula_type == "formula 3"

    n_d, v_d = _formula_3_nd_vd(record.coefficients)
    assert n_d == pytest.approx(1.606, abs=0.002)
    assert v_d == pytest.approx(43.9, abs=0.5)


def test_find_glassplus_record_chengdu_code_matches_nd_vd_pattern() -> None:
    record = find_glassplus_record(_glassplus_path(), "D-K59", "Chengdu")

    assert record is not None
    assert record.reference == "Chengdu"
    assert record.formula_type == "formula 3"

    n_d, v_d = _formula_3_nd_vd(record.coefficients)
    assert n_d == pytest.approx(1.518, abs=0.002)
    assert v_d == pytest.approx(63.5, abs=0.5)
