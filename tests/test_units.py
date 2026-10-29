import pytest

from pipeline.validators.units import downgrade, load_units, normalise_capacity, parse_number


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("48,000", "t/a", 48_000),
        ("48", "kt/a", 48_000),
        ("48", "ktpa", 48_000),
        ("4.8", "万吨/年", 48_000),
        ("4.8", "万吨 / 年", 48_000),
        ("400", "MT/Month", 4_800),
        ("400", "MT / Month", 4_800),
        ("1,20,000", "TPA", 120_000),
        ("30", "tonnes per year", 30),
        ("12", "kilotonnes per annum", 12_000),
        ("5", "thousand tonnes per year", 5_000),
        ("1.2", "Mt/a", 1_200_000),
        ("1.2", "MMTPA", 1_200_000),
        ("3000", "吨/年", 3_000),
        ("20", "千吨/年", 20_000),
        ("10", "million lbs/yr", 4_535.9237),
        ("48 000", "t/a", 48_000),
        ("48,000", "ton-per-year", 48_000),
        (48000, "t/a", 48_000),
    ],
)
def test_conversions(value, unit, expected):
    r = normalise_capacity(value, unit)
    assert r.ok, r.reason
    assert r.value_tpa == pytest.approx(expected)
    assert not r.estimated


@pytest.mark.parametrize(
    ("value", "unit", "expected", "assumption"),
    [
        ("100", "TPD", 33_000, "330 operating days per year"),
        ("2", "t/h", 16_000, "8000 operating hours per year"),
        ("500", "kg/h", 4_000, "8000 operating hours per year"),
    ],
)
def test_assumed_factors_are_flagged(value, unit, expected, assumption):
    r = normalise_capacity(value, unit)
    assert r.ok and r.value_tpa == pytest.approx(expected)
    assert r.estimated and r.assumption == assumption
    assert r.flags == [f"assumed: {assumption}"]


@pytest.mark.parametrize(
    ("value", "unit"),
    [
        ("5", "MTPA"),  # million or metric?
        ("5", "MT"),  # no period
        ("3", "万吨"),  # stock, not a rate
        ("40-50", "kt/a"),  # range
        ("48.000", "t/a"),  # thousands or decimal, no language
        ("big", "t/a"),
        ("5", "barrels/day"),  # unknown unit
        ("5", None),
    ],
)
def test_refuses_to_guess(value, unit):
    r = normalise_capacity(value, unit)
    assert not r.ok and r.value_tpa is None and r.reason


def test_language_resolves_separator():
    assert parse_number("48.000", "de") == (48_000, None)
    assert parse_number("4,8", "de") == (4.8, None)
    assert parse_number("48,000", "de")[0] is None  # 3 decimals after a comma: ambiguous even in German
    assert normalise_capacity("48.000", "Jahrestonnen", language="de").value_tpa == 48_000


def test_downgrade():
    assert downgrade("A") == "B"
    assert downgrade("D") == "D"
    assert downgrade("B", 2) == "D"


def test_units_yaml_has_no_conflicting_aliases():
    by_alias, _ = load_units()
    assert by_alias  # load_units raises on conflicts


def test_product_basis_converts_vitamin_formulations():
    from pipeline.validators.units import product_basis

    ve, va = "mol:7695-91-2", "mol:127-47-9"
    assert product_basis(ve, "吨/年", "VE(50%粉)产能60000吨/年")[0] == 0.5
    assert product_basis(va, None, "公司维生素A折50万IU计年产能为8000吨")[0] == 0.172
    assert product_basis(ve, "t/a", "vitamin E acetate capacity of 25,000 t") is None  # pure basis: untouched
    assert product_basis("mol:5392-40-5", None, "50% powder") is None  # only the listed molecules


def test_unit_with_a_basis_note():
    from pipeline.validators.units import normalise_capacity

    n = normalise_capacity("40000", "吨/年 (VE 50%粉)", "zh")
    assert n.ok and n.value_tpa == 40000
