"""Ownership over time: a recorded sale moves the operator from its date; stale claims step aside; groups."""

import datetime as dt

from portolan.merges import apply as apply_merges
from portolan.models import Claim, Company, Event, Evidence, Merge, Transfer
from portolan.ownership import apply_transfers, groups
from portolan.resolve import resolve

SITE = "site:us-jacksonville-02"


def ev(i: int, published: str | None, source_type: str = "company_primary") -> Evidence:
    return Evidence(
        id=f"src:{i:012x}",
        url=f"https://example.com/{i}",
        retrieved_at="2026-10-28T00:00:00Z",
        published_at=published,
        source_type=source_type,
        language="en",
        quote="q",
        quote_check="pass",
    )


def op_claim(i: int, value: str, as_of: str, evidence: str, subject: str = SITE) -> Claim:
    return Claim(
        id=f"clm:{i:012x}",
        subject_id=subject,
        field="operator",
        value=value,
        value_norm=value,
        as_of=as_of,
        evidence_ids=[evidence],
        extracted_by="test",
        confidence="A",
        review_state="accepted",
    )


SALE = Event(
    id="ev:2026-09-01:sale",
    date="2026-09-01",
    type="divestment",
    subjects=["co:seller"],
    summary="Seller sells the site to Buyer",
    evidence_ids=["src:000000000009"],
)
EVIDENCE = {e.id: e for e in [ev(1, None), ev(2, "2026-04-20"), ev(3, "2026-10-01"), ev(9, "2026-09-01")]}


def test_divestment_moves_the_operator_and_sets_stale_claims_aside():
    claims = [
        op_claim(1, "co:seller", "2026-10-28", "src:000000000001"),  # undated web page read after the sale
        op_claim(2, "co:seller", "2026-04-20", "src:000000000002"),  # register from before the sale
    ]
    t = Transfer(event_id=SALE.id, kind="operator", seller="co:seller", buyer="co:buyer", sites=[SITE],
                 decided_by="test", date="2026-10-28")  # fmt: skip
    on = dt.date(2026, 10, 28)
    out, applied = apply_transfers([t], [SALE], claims, EVIDENCE, on)
    assert SALE.id in applied
    r = resolve(out, on=on)[(SITE, "operator")]
    assert r.value == "co:buyer" and r.as_of == dt.date(2026, 9, 1) and r.grade == "A"
    # before the sale, history still shows the seller
    before = apply_transfers([t], [SALE], claims, EVIDENCE, dt.date(2026, 8, 1))[0]
    assert resolve(before, on=dt.date(2026, 8, 1))[(SITE, "operator")].value == "co:seller"
    # a source published after the sale that still names the seller is kept: the map shows the conflict
    late = claims + [op_claim(3, "co:seller", "2026-10-01", "src:000000000003")]
    r = resolve(apply_transfers([t], [SALE], late, EVIDENCE, on)[0], on=on)[(SITE, "operator")]
    assert r.value == "co:seller"  # newer as_of wins; the audit flags it as a sold-asset contradiction


def test_parent_transfer_and_groups():
    target = "co:linax"
    t = Transfer(event_id=SALE.id, kind="parent", buyer="co:santa-clara", target=target, sites=[],
                 decided_by="test", date="2026-10-28")  # fmt: skip
    out, _ = apply_transfers([t], [SALE], [], EVIDENCE, dt.date(2026, 10, 28))
    assert out[0].subject_id == target and out[0].field == "parent" and out[0].value_norm == "co:santa-clara"
    cos = [
        Company(id="co:shandong", name="Shandong NHU", type=["producer"]),
        Company(id="co:nhu", name="Zhejiang NHU", type=["producer"]),
        Company(id="co:wanhua", name="Wanhua", type=["producer"]),
        Company(id="co:guofeng", name="Yantai Guofeng", type=["investor"]),
        Company(id="co:jv", name="BASF PETRONAS", type=["producer"]),
    ]
    parents = {"co:shandong": ["co:nhu"], "co:wanhua": ["co:guofeng"], "co:jv": ["co:basf", "co:petronas"]}
    g = groups(cos, parents)
    assert g["co:shandong"] == "co:nhu"  # subsidiary rolls up
    assert g["co:wanhua"] == "co:wanhua"  # an investor is not a group
    assert g["co:jv"] == "co:jv"  # a joint venture stays itself


def test_event_merge_folds_sources():
    a = SALE.model_copy(update={"id": "ev:2026-09-01:a", "subjects": ["unit:us-jacksonville-02:linalool"]})
    b = SALE.model_copy(update={"id": "ev:2026-09-03:b", "evidence_ids": ["src:000000000003"]})
    m = Merge(from_id=b.id, to_id=a.id, reason="same event", decided_by="test", date="2026-10-28")
    *_, events = apply_merges({m.from_id: m.to_id}, [], [], [], [a, b])
    assert [e.id for e in events] == [a.id]
    assert events[0].evidence_ids == ["src:000000000003", "src:000000000009"]
    assert events[0].subjects == ["unit:us-jacksonville-02:linalool", "co:seller"]
