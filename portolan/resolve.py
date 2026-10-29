"""Resolution rules: claims → the value displayed for each (subject, field).

1. Discard `rejected` and `superseded` claims (and claims dated after the requested date).
2. Take the claims with the latest `as_of`; among those, the highest grade.
3. If two or more survivors disagree beyond tolerance (capacity ±10%, any other field: different value), the
   field is **contested**: the range and every source are kept.
4. Capacity: `capacity_basis` ranks nameplate > design > permitted > estimated; `production` is never capacity
   (it resolves separately, as the pseudo-field `production`).
5. D-grade claims (estimates) are resolved only when `include_estimates=True`; the public default leaves
   them out, so the app can show them behind its "show estimates" toggle.

Ties left after these rules: accepted beats validated beats proposed. Pure functions, no I/O."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from portolan.models import Claim

GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}
BASIS_RANK = {"nameplate": 0, "design": 1, "permitted": 2, "estimated": 3, None: 4}
STATE_RANK = {"accepted": 0, "validated": 1, "proposed": 2}
CAPACITY_TOLERANCE = 0.10

Outcome = Literal["resolved", "contested"]


@dataclass
class Resolved:
    subject_id: str
    field: str
    outcome: Outcome
    value: object  # the displayed value (for contested: the value of the top-ranked claim)
    as_of: dt.date
    grade: str
    claim_ids: list[str]  # the claims the displayed value rests on
    source_claim_ids: list[str] = field(default_factory=list)  # every live claim for this field
    range: tuple[float, float] | None = None
    basis: str | None = None
    review_state: str | None = None


def _key(c: Claim) -> str:
    return "production" if c.field == "capacity" and c.capacity_basis == "production" else c.field


def _value(c: Claim) -> object:
    return c.value_norm if c.value_norm is not None else c.value


def _agree(field_name: str, a: object, b: object) -> bool:
    if field_name in ("capacity", "production") and isinstance(a, int | float) and isinstance(b, int | float):
        hi = max(abs(a), abs(b))
        return hi == 0 or abs(a - b) / hi <= CAPACITY_TOLERANCE
    return a == b


def resolve_field(subject_id: str, field_name: str, claims: list[Claim]) -> Resolved | None:
    live = [c for c in claims if c.review_state not in ("rejected", "superseded")]
    if field_name in ("capacity", "production"):
        live = [c for c in live if isinstance(_value(c), int | float)]  # unparsed capacity never displays
    if not live:
        return None
    latest = max(c.as_of for c in live)
    top = [c for c in live if c.as_of == latest]
    best_grade = min(GRADE_RANK[c.confidence] for c in top)
    top = [c for c in top if GRADE_RANK[c.confidence] == best_grade]
    if field_name == "capacity":
        best_basis = min(BASIS_RANK.get(c.capacity_basis, 4) for c in top)
        top = [c for c in top if BASIS_RANK.get(c.capacity_basis, 4) == best_basis]
    top.sort(key=lambda c: (STATE_RANK.get(c.review_state, 3), c.id))
    head = top[0]
    disagree = [c for c in top if not _agree(field_name, _value(c), _value(head))]
    numeric = [v for v in (_value(c) for c in top) if isinstance(v, int | float)]
    contested = bool(disagree)
    return Resolved(
        subject_id=subject_id,
        field=field_name,
        outcome="contested" if contested else "resolved",
        value=_value(head),
        as_of=latest,
        grade=head.confidence,
        claim_ids=sorted(c.id for c in top)
        if contested
        else sorted(c.id for c in top if _agree(field_name, _value(c), _value(head))),
        source_claim_ids=sorted(c.id for c in live),
        range=(min(numeric), max(numeric)) if contested and numeric else None,
        basis=head.capacity_basis,
        review_state=head.review_state,
    )


def resolve(
    claims: Iterable[Claim], on: dt.date | None = None, include_estimates: bool = False
) -> dict[tuple[str, str], Resolved]:
    """Resolve every (subject, field). `on` replays history: only claims with as_of ≤ on count."""
    groups: dict[tuple[str, str], list[Claim]] = defaultdict(list)
    for c in claims:
        if on is not None and c.as_of > on:
            continue
        # D is shown only behind the estimates toggle, and only real estimates (with an `estimate` record);
        # a claim graded D because its quote failed never displays.
        if c.confidence == "D" and not (include_estimates and c.estimate is not None):
            continue
        groups[(c.subject_id, _key(c))].append(c)
    out: dict[tuple[str, str], Resolved] = {}
    for (subject, fname), cs in sorted(groups.items()):
        if any(c.confidence != "D" for c in cs):  # an estimate only fills a gap, never overrides a source
            cs = [c for c in cs if c.confidence != "D"]
        r = resolve_field(subject, fname, cs)
        if r is not None:
            out[(subject, fname)] = r
    return out
