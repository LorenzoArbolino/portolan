"""Estimate step: fills gaps only, says how, and never overrides a sourced value."""

import datetime as dt
import itertools

from portolan.estimate import backtest, estimate, last_seen
from portolan.models import Claim, Unit

ON = dt.date(2026, 10, 28)
_n = itertools.count()
MOL = "mol:5392-40-5"


def unit(i: int, mol: str = MOL) -> Unit:
    return Unit(id=f"unit:cn-town{i}-01:citral", site_id=f"site:cn-town{i}-01", molecule_id=mol)


def C(subject, field, value, grade="A", as_of="2025-01-01", basis=None):
    i = next(_n)
    return Claim(
        id=f"clm:{i:012x}",
        subject_id=subject,
        field=field,
        value=str(value),
        value_norm=value,
        capacity_basis=basis or ("nameplate" if field == "capacity" else None),
        as_of=as_of,
        evidence_ids=[f"src:{i:012x}"],
        extracted_by="test",
        confidence=grade,
        review_state="accepted",
    )


def by(out, subject, field):
    return next((c for c in out if c.subject_id == subject and c.field == field), None)


def test_capacity_from_output_and_never_over_a_source():
    us = [unit(1), unit(2)]
    claims = [C(us[0].id, "capacity", 8000, basis="production"), C(us[1].id, "capacity", 48000)]
    out = estimate(us, claims, ON)
    e = by(out, us[0].id, "capacity")
    assert e.value == 10000 and e.estimate.method == "capacity_from_output" and e.confidence == "D"
    assert (e.estimate.low, e.estimate.high) == (8000, round(8000 / 0.6, 1))
    assert by(out, us[1].id, "capacity") is None  # sourced: left alone


def test_byproduct_gets_no_capacity_estimate():
    us = [unit(1)]
    claims = [C(us[0].id, "capacity", 8000, basis="production")]
    assert estimate(us, claims, ON, byproducts={MOL}) == []


def test_peers_only_where_the_backtest_passes():
    us = [unit(i) for i in range(6)]
    claims = [C(us[i].id, "capacity", v) for i, v in enumerate([10000, 11000, 12000, 13000, 14000])]
    tests = backtest(us, claims, ON)
    assert tests[(MOL, "capacity_from_peers")].passed  # tight values: held-out estimates within 2×
    e = by(estimate(us, claims, ON), us[5].id, "capacity")
    assert e.estimate.method == "capacity_from_peers" and e.estimate.confidence == "low"
    assert e.estimate.low == 10000 and e.estimate.high == 12000
    # the citral case: spread too wide, method disabled, the field stays unknown
    spread = [C(us[i].id, "capacity", v) for i, v in enumerate([360, 8000, 15000, 40000, 48000])]
    assert not backtest(us, spread, ON)[(MOL, "capacity_from_peers")].passed
    assert by(estimate(us, spread, ON), us[5].id, "capacity") is None
    # too few values: never enabled
    assert not backtest(us, claims[:4], ON)[(MOL, "capacity_from_peers")].passed


def test_world_residual_gates_and_cap():
    us = [unit(i) for i in range(4)]
    base = [C(us[0].id, "capacity", 20000)]
    on = {(MOL, "capacity_from_world_residual")}
    world = C(MOL, "world_capacity", 100000, grade="A", as_of="2024-01-01")
    e = by(estimate(us, base + [world], ON, enabled=on), us[1].id, "capacity")
    # residual 80 kt over 3 missing units = 26.7 kt each, capped at the largest sourced unit (20 kt)
    assert e.estimate.method == "capacity_from_world_residual" and e.value == 20000
    weak = C(MOL, "world_capacity", 100000, grade="C", as_of="2024-01-01")
    old = C(MOL, "world_capacity", 100000, grade="A", as_of="2003-01-01")
    for w in (weak, old):
        assert by(estimate(us, base + [w], ON, enabled=on), us[1].id, "capacity") is None
    assert by(estimate(us, base + [world], ON, enabled=set()), us[1].id, "capacity") is None  # backtest
    assert (
        by(estimate(us, base + [world], ON, enabled=on, resolved_molecules=set()), us[1].id, "capacity")
        is None
    )
    # no sourced unit to cap against (the isophytol case): unknown
    assert by(estimate(us, [world], ON, enabled=on), us[1].id, "capacity") is None


def test_status_is_never_estimated_only_last_seen():
    us = [unit(1), unit(2), unit(3)]
    claims = [
        C(us[0].id, "exists", "true", as_of="2025-06-01"),
        C(us[1].id, "capacity", 5000, as_of="2015-06-01"),
        C(us[2].id, "status", "closed", as_of="2020-01-01"),
    ]
    out = estimate(us, claims, ON)
    assert all(c.field != "status" for c in out)
    seen = last_seen(us, claims, {claims[1].evidence_ids[0]: dt.date(2014, 3, 1)})
    assert seen[us[0].id]["last_seen"] == "2025-06-01"
    assert seen[us[1].id]["last_seen"] == "2014-03-01"  # evidence publication date beats as_of
    assert us[2].id not in seen  # has a sourced status


def test_basis_unknown_figures_stay_out_of_backtest_and_peers():
    us = [unit(i) for i in range(7)]
    claims = [C(us[i].id, "capacity", v) for i, v in enumerate([10000, 11000, 12000, 13000, 14000])]
    odd = C(us[5].id, "capacity", 90000).model_copy(update={"flags": ["product basis not stated"]})
    t = backtest(us, claims + [odd], ON)[(MOL, "capacity_from_peers")]
    assert t.n == 5 and us[5].id not in {r[0] for r in t.rows}
    out = estimate(us, claims + [odd], ON)
    assert by(out, us[5].id, "capacity") is None  # it has a figure: never estimated over
    assert by(out, us[6].id, "capacity").estimate.high == 12000  # peers ignore the basis-unknown 90,000
