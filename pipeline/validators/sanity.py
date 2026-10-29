"""`sanity` validator: values a real plant can have. Failures go to review, never silently fixed.

- capacity within the chain pack's bounds (`sanity.capacity_tpa`);
- years 1900–2035;
- status transitions that can happen: a `closed` unit doesn't start operating again without a
  `restarted` event; `cancelled` only follows `planned` or `under_construction`."""

from __future__ import annotations

import datetime as dt

YEAR_MIN, YEAR_MAX = 1900, 2035

# Allowed moves between consecutive dated status claims. Same status → same status is always fine.
ALLOWED: dict[str, set[str]] = {
    "planned": {"under_construction", "commissioning", "operating", "cancelled"},
    "under_construction": {"commissioning", "operating", "cancelled", "idle"},
    "commissioning": {"operating", "idle", "closing", "closed"},
    "operating": {"idle", "closing", "closed"},
    "idle": {"operating", "closing", "closed"},
    "closing": {"closed", "operating"},  # a closure can be reversed before it happens
    "closed": set(),
    "cancelled": {"planned"},  # a project can be revived
    "unknown": {
        "planned",
        "under_construction",
        "commissioning",
        "operating",
        "idle",
        "closing",
        "closed",
        "cancelled",
    },
}


def capacity_problem(value_tpa: float, lo: float, hi: float) -> str | None:
    if not lo <= value_tpa <= hi:
        return f"sanity: {value_tpa:g} t/a outside {lo:g}–{hi:g}"
    return None


def year_problem(year: int | None, raw: object) -> str | None:
    if year is None or not YEAR_MIN <= year <= YEAR_MAX:
        return f"sanity: year {raw!r} not in {YEAR_MIN}–{YEAR_MAX}"
    return None


def transition_problems(history: list[tuple[dt.date, str]]) -> list[str]:
    """`history`: (as_of, status) for one unit. Returns one message per impossible move."""
    out = []
    seq = sorted(history)
    for (d0, s0), (d1, s1) in zip(seq, seq[1:], strict=False):
        if s0 == s1 or s0 not in ALLOWED:
            continue
        if s1 not in ALLOWED[s0]:
            out.append(f"sanity: status {s0} ({d0}) → {s1} ({d1}) is not a possible transition")
    return out
