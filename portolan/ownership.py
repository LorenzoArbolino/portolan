"""Ownership over time (methodology, rule 7: a map that contradicts itself is a bug).

An acquisition or divestment recorded in `data/transfers.csv` becomes claims dated on the event:
- `operator`: every listed site gets `operator = buyer`;
- `parent`: the target company gets `parent = buyer` (it keeps operating its sites).

Claims that the transfer makes stale are set aside at build time (never deleted from data): a claim for the
same subject and field naming someone else, whose evidence is undated or published before the event. A web
page read after the sale that still names the seller (common: company pages lag) loses to the dated event;
a source published after the event that still names the seller stays, and shows as contested.

Groups: a company rolls up to its parent while the parent is a single producer company (not an investor and
not a joint venture's several parents). The league counts capacity by group."""

from __future__ import annotations

import datetime as dt

from portolan import ids
from portolan.models import Claim, Company, Event, Evidence, Transfer
from portolan.resolve import Resolved

GRADE_BY_SOURCE = {"A": {"regulator", "permit", "company_primary", "exchange_filing", "trade_measure"}}


def _grade(evs: list[Evidence]) -> str:
    """Best grade of the event's evidence: primary + quote pass → A, other passed quotes → B, else C."""
    best = "C"
    for e in evs:
        if e.quote_check == "pass" and e.source_type in GRADE_BY_SOURCE["A"]:
            return "A"
        if e.quote_check == "pass":
            best = "B"
    return best


def apply_transfers(
    transfers: list[Transfer],
    events: list[Event],
    claims: list[Claim],
    evidence: dict[str, Evidence],
    on: dt.date,
) -> tuple[list[Claim], dict[str, Transfer]]:
    """Derived claims added, stale ones set aside. Returns (claims, event id → transfer applied)."""
    ev_by_id = {e.id: e for e in events}
    applied: dict[str, Transfer] = {}
    derived: list[Claim] = []
    stale: set[str] = set()
    for t in sorted(transfers, key=lambda t: t.date):
        e = ev_by_id.get(t.event_id)
        if e is None or e.date > on:
            continue
        applied[e.id] = t
        evs = [evidence[x] for x in e.evidence_ids if x in evidence]
        targets = [(s, "operator") for s in t.sites] if t.kind == "operator" else [(t.target, "parent")]
        for subject, field in targets:
            derived.append(
                Claim(
                    id=ids.claim_id(subject, field, t.buyer, e.evidence_ids),
                    subject_id=subject,
                    field=field,
                    value=t.buyer,
                    value_norm=t.buyer,
                    as_of=e.date,
                    evidence_ids=e.evidence_ids,
                    extracted_by=f"transfer:{e.id}",
                    confidence=_grade(evs),
                    review_state="accepted",
                    review_note=t.note,
                    flags=["derived from an ownership event"],
                )
            )
            unit_prefix = f"unit:{subject.removeprefix('site:')}:" if subject.startswith("site:") else None
            for c in claims:
                hit = c.subject_id == subject or (unit_prefix and c.subject_id.startswith(unit_prefix))
                if not hit or c.field != field or c.value_norm == t.buyer:
                    continue
                dates = [evidence[x].published_at for x in c.evidence_ids if x in evidence]
                if not any(d is not None and d >= e.date for d in dates):
                    stale.add(c.id)
    kept = [c for c in claims if c.id not in stale]
    return kept + derived, applied


def parents_of(
    company_id: str, resolved: dict[tuple[str, str], Resolved], claims_by_id: dict[str, Claim]
) -> list:
    """The company's current parents: one, or several for a joint venture (contested = several partners)."""
    r = resolved.get((company_id, "parent"))
    if r is None:
        return []
    if r.outcome == "contested":
        return sorted({str(claims_by_id[i].value_norm) for i in r.claim_ids if i in claims_by_id})
    return [str(r.value)]


def groups(companies: list[Company], parents: dict[str, list[str]]) -> dict[str, str]:
    """Company → the group it rolls up to: up the single-parent chain while the parent is a producer."""
    types = {c.id: set(c.type) for c in companies}
    out: dict[str, str] = {}
    for c in companies:
        cur, seen = c.id, {c.id}
        while len(ps := parents.get(cur, [])) == 1 and ps[0] not in seen:
            p = ps[0]
            if "investor" in types.get(p, set()) or (types.get(p) and "producer" not in types[p]):
                break
            cur = p
            seen.add(p)
        out[c.id] = cur
    return out
