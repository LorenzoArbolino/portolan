import datetime as dt

from portolan.models import Claim
from portolan.resolve import resolve

U = "unit:cn-exampletown-01:citral"
_n = iter(range(10_000))


def C(
    field="capacity",
    value=48000,
    as_of="2024-08-29",
    grade="B",
    state="accepted",
    basis="nameplate",
    subject=U,
):
    i = next(_n)
    return Claim(
        id=f"clm:{i:012x}",
        subject_id=subject,
        field=field,
        value=str(value),
        value_norm=value,
        capacity_basis=basis if field == "capacity" else None,
        as_of=as_of,
        evidence_ids=["src:000000000001"],
        extracted_by="test",
        confidence=grade,
        review_state=state,
    )


def one(claims, **kw):
    out = resolve(claims, **kw)
    return out


def test_latest_as_of_wins_over_grade():
    old_a = C(value=40000, as_of="2020-01-01", grade="A")
    new_b = C(value=48000, as_of="2024-08-29", grade="B")
    r = one([old_a, new_b])[(U, "capacity")]
    assert r.value == 48000 and r.outcome == "resolved" and r.claim_ids == [new_b.id]
    assert set(r.source_claim_ids) == {old_a.id, new_b.id}


def test_higher_grade_wins_on_same_date():
    a, c = C(value=48000, grade="A"), C(value=30000, grade="C")
    r = one([a, c])[(U, "capacity")]
    assert r.value == 48000 and r.outcome == "resolved" and r.grade == "A"


def test_tie_within_tolerance_is_resolved_with_both_sources():
    a, b = C(value=48000), C(value=46000)  # 4% apart
    r = one([a, b])[(U, "capacity")]
    assert r.outcome == "resolved" and sorted(r.claim_ids) == sorted([a.id, b.id])


def test_contested_beyond_tolerance_keeps_range():
    a, b = C(value=48000), C(value=40000)  # 17% apart, same date and grade
    r = one([a, b])[(U, "capacity")]
    assert r.outcome == "contested" and r.range == (40000, 48000)
    assert sorted(r.claim_ids) == sorted([a.id, b.id])


def test_contested_status():
    r = one([C("status", "operating"), C("status", "idle")])[(U, "status")]
    assert r.outcome == "contested"


def test_superseded_and_rejected_are_ignored():
    sup = C(value=40000, as_of="2025-01-01", state="superseded")
    rej = C(value=10, as_of="2025-06-01", state="rejected")
    ok = C(value=48000)
    r = one([sup, rej, ok])[(U, "capacity")]
    assert r.value == 48000 and r.claim_ids == [ok.id] and r.source_claim_ids == [ok.id]


def test_production_is_never_capacity():
    prod = C(value=30000, as_of="2025-12-31", basis="production")
    cap = C(value=48000)
    out = one([prod, cap])
    assert out[(U, "capacity")].value == 48000
    assert out[(U, "production")].value == 30000


def test_basis_ranking():
    permitted = C(value=60000, basis="permitted")
    nameplate = C(value=48000, basis="nameplate")
    assert one([permitted, nameplate])[(U, "capacity")].value == 48000


def test_estimates_fill_gaps_only_behind_toggle():
    from portolan.models import Estimate

    def est(**kw):
        c = C(value=50000, as_of="2026-06-01", grade="D", basis="estimated", **kw)
        return c.model_copy(update={"estimate": Estimate(method="m", inputs=[c.id], confidence="low")})

    sourced = C(value=48000)
    assert one([est(), sourced], include_estimates=True)[(U, "capacity")].value == 48000  # never overrides
    assert (U, "capacity") not in one([est()])
    assert one([est()], include_estimates=True)[(U, "capacity")].value == 50000
    failed_quote = C(value=50000, grade="D")  # D without an estimate record never displays
    assert (U, "capacity") not in one([failed_quote], include_estimates=True)


def test_replay_history_with_on_date():
    old = C("status", "operating", as_of="2016-01-01")
    fire = C("status", "idle", as_of="2017-10-31")
    assert one([old, fire], on=dt.date(2017, 6, 1))[(U, "status")].value == "operating"
    assert one([old, fire], on=dt.date(2018, 1, 1))[(U, "status")].value == "idle"


def test_unparsed_capacity_never_displays():
    bad = Claim(
        id="clm:0000000000ff",
        subject_id=U,
        field="capacity",
        value="40-50",
        unit_raw="kt/a",
        as_of="2024-01-01",
        evidence_ids=["src:000000000001"],
        extracted_by="t",
        confidence="B",
    )
    assert (U, "capacity") not in one([bad])


def test_accepted_beats_validated_on_tie():
    v = C(value=48000, state="validated")
    a = C(value=48500, state="accepted")
    assert one([v, a])[(U, "capacity")].review_state == "accepted"
