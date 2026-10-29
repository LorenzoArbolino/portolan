"""Review decisions: accept or reject claims and close review-queue items.

Only the lines that change are rewritten, so a decision shows up as a small diff in the PR that carries it.
A decision can fix what the reviewer checked against the quote: the unit (re-normalised) or the capacity
basis. Values themselves are never edited here; a wrong value is rejected and re-extracted."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from pipeline.validators.units import normalise_capacity
from portolan.models import Claim

CLAIMS = Path("data/claims.jsonl")
QUEUE = Path("review/queue.jsonl")


def _rewrite(path: Path, change) -> int:
    """Apply `change(dict) -> dict | None` to each JSONL line; None keeps the line byte-for-byte."""
    lines = path.read_text(encoding="utf-8").splitlines()
    n = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        new = change(json.loads(line))
        if new is not None:
            lines[i] = new
            n += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return n


def decide(
    items: list[str],
    accept: bool,
    note: str,
    unit: str | None = None,
    basis: str | None = None,
    flag: str | None = None,
    by: str = "claude",
    claims_path: Path = CLAIMS,
    queue_path: Path = QUEUE,
) -> tuple[int, int]:
    """`items` are review ids (rv:…) or claim ids (clm:…). Returns (claims changed, queue items closed)."""
    queue = [json.loads(x) for x in queue_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    by_rv = {q["id"]: q for q in queue}
    claim_ids = {i for i in items if i.startswith("clm:")}
    for i in items:
        if i.startswith("rv:"):
            if i not in by_rv:
                raise KeyError(i)
            claim_ids |= set(by_rv[i]["claim_ids"])
    today = dt.date.today().isoformat()
    state = "accepted" if accept else "rejected"

    def claim(d: dict) -> str | None:
        if d["id"] not in claim_ids:
            return None
        d["review_state"] = state
        d["review_note"] = f"{state} by {by} on {today}: {note}"
        if unit:
            n = normalise_capacity(d["value"], unit)
            if not n.ok:
                raise ValueError(f"{d['id']}: {n.reason}")
            d["unit_raw"], d["value_norm"] = unit, n.value_tpa
        if basis:
            d["capacity_basis"] = basis
        if flag and flag not in d.setdefault("flags", []):
            d["flags"].append(flag)
        return Claim.model_validate(d).model_dump_json(exclude_none=True)

    def item(d: dict) -> str | None:
        hit = d["id"] in items or bool(claim_ids & set(d.get("claim_ids", [])))
        if not hit or d.get("state") != "open":
            return None
        d.update(state="closed", decision=state, decided_by=by, decided_on=today, decision_note=note)
        return json.dumps(d, ensure_ascii=False, sort_keys=True)

    known = {json.loads(x)["id"] for x in claims_path.read_text(encoding="utf-8").splitlines() if x.strip()}
    if claim_ids - known:
        raise KeyError(", ".join(sorted(claim_ids - known)))
    changed = _rewrite(claims_path, claim)
    closed = _rewrite(queue_path, item)
    return changed, closed
