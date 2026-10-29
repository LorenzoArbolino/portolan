"""Estimate step (methodology, rules 1 and 5): fill a gap only with a value we can defend.

Runs at build time on the merged data, so estimates always reflect the current sourced values and are never
stored as if they were findings. Each estimate carries its method, its input claims (whose evidence it cites),
a low–high range and a confidence. It only fills a field that has no sourced value; it never overrides one.
Where no method qualifies, the field stays unknown: unknown beats invented.

Methods, tried in order for each unit (molecule-agnostic):
- `capacity_from_output`: a sourced output figure, shown as a capacity range output … output ÷ 0.6 (point
  value output ÷ 0.8). It rescales one sourced number rather than imputing from peers. Never for by-products
  (the molecule's `byproduct: true`, e.g. turpentine from kraft pulp mills): their output tracks the main
  product, so they show the output ("made in <year>") and no capacity.
- `capacity_from_world_residual`: a grade A/B world capacity no older than 5 years, minus the known units,
  shared equally over the units with no capacity, each share capped at the largest sourced unit of the
  molecule. Only when the molecule's must-find items are all resolved (otherwise the residual belongs to
  producers we haven't found) and when the method passes its backtest for the molecule.
- `capacity_from_peers`: lower quartile of the sourced capacities for the same molecule, only where the
  leave-one-out backtest passes for that molecule (see `backtest`).

Status is never estimated. A unit with no status claim gets `last_seen` (the newest date of its sourced
evidence), which the app shows as "status unconfirmed (last seen <date>)"."""

from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from portolan import ids
from portolan.models import Claim, Estimate, Unit
from portolan.resolve import resolve

UTILISATION, UTIL_LOW = 0.8, 0.6
DORMANT = {"closed", "cancelled", "closing", "planned"}
WORLD_MAX_AGE_YEARS = 5
# Backtest gate (rule 2): enough sourced values, and most held-out estimates within a factor of 2.
BACKTEST_MIN_N = 5
BACKTEST_MIN_HIT = 0.7
BACKTEST_BAND = (0.5, 2.0)
PEER_METHODS = ("capacity_from_peers", "capacity_from_world_residual")


def _claim(
    subject: str, field: str, value, inputs: list[Claim], method: str, low, high, confidence: str, on: dt.date
) -> Claim:
    evidence = sorted({e for c in inputs for e in c.evidence_ids})[:20]
    est = Estimate(
        method=method,
        inputs=sorted({c.id for c in inputs})[:50],
        low=None if low is None else round(low, 1),
        high=None if high is None else round(high, 1),
        confidence=confidence,
    )
    return Claim(
        id=ids.claim_id(subject, field, f"{value}|{method}", evidence),
        subject_id=subject,
        field=field,
        value=value,
        value_norm=value,
        unit_raw="t/a" if field == "capacity" else None,
        capacity_basis="estimated" if field == "capacity" else None,
        as_of=on,
        evidence_ids=evidence,
        extracted_by=f"estimate:{method}",
        confidence="D",
        review_state="accepted",
        review_note=f"estimate ({method}, confidence {confidence})",
        estimate=est,
    )


BASIS_UNSTATED = "product basis not stated"  # flag set by the collector; such figures aren't comparable


def _comparable(r, by_id: dict[str, Claim]) -> bool:
    """A resolved capacity usable as a number: not resting on a figure whose product basis is unknown."""
    return not any(BASIS_UNSTATED in by_id[i].flags for i in r.claim_ids if i in by_id)


# ---------------------------------------------------------------- the methods as pure functions


def peers_value(known: list[float]) -> float | None:
    """Lower quartile of the peers (big plants get reported; the unreported ones skew small)."""
    if len(known) < 3:
        return None
    return statistics.quantiles(known, n=4)[0]


def residual_share(world: float, known: list[float], n_missing: int) -> float | None:
    """World capacity minus the known units, shared over the missing ones, capped at the largest known
    unit."""
    if n_missing < 1 or not known:
        return None
    share = (world - sum(known)) / n_missing
    return min(share, max(known)) if share > 0 else None


# ---------------------------------------------------------------- backtest (rule 2)


@dataclass
class Backtest:
    molecule_id: str
    method: str
    n: int
    hits: int
    rows: list[tuple[str, float, float | None]]  # (unit, true value, held-out estimate)

    @property
    def hit_rate(self) -> float:
        tested = [r for r in self.rows if r[2] is not None]
        return self.hits / len(tested) if tested else 0.0

    @property
    def passed(self) -> bool:
        tested = [r for r in self.rows if r[2] is not None]
        return self.n >= BACKTEST_MIN_N and bool(tested) and self.hit_rate >= BACKTEST_MIN_HIT


def _within(est: float | None, true: float) -> bool:
    return est is not None and true > 0 and BACKTEST_BAND[0] <= est / true <= BACKTEST_BAND[1]


def leave_one_out(
    molecule_id: str, method: str, values: dict[str, float], fn: Callable[[list[float]], float | None]
) -> Backtest:
    rows = []
    for uid, true in sorted(values.items()):
        rest = [v for k, v in values.items() if k != uid]
        rows.append((uid, true, fn(rest)))
    return Backtest(molecule_id, method, len(values), sum(_within(e, t) for _, t, e in rows), rows)


def backtest(units: list[Unit], claims: list[Claim], on: dt.date) -> dict[tuple[str, str], Backtest]:
    """Leave-one-out per molecule and imputing method, on the sourced (A–C) capacities as resolved today.
    World residual: each sourced unit in turn is treated as the only missing one."""
    live = [c for c in claims if c.review_state not in ("rejected", "superseded") and c.confidence != "D"]
    res = resolve(live, on=on)
    by_id = {c.id: c for c in live}
    by_mol: dict[str, dict[str, float]] = defaultdict(dict)
    for u in units:
        r = res.get((u.id, "capacity"))
        if (
            r is not None
            and isinstance(r.value, int | float)
            and r.value > 0
            and r.outcome == "resolved"
            and _comparable(r, by_id)
        ):
            by_mol[u.molecule_id][u.id] = float(r.value)
    out: dict[tuple[str, str], Backtest] = {}
    for mol in sorted({u.molecule_id for u in units}):
        vals = by_mol.get(mol, {})
        out[(mol, "capacity_from_peers")] = leave_one_out(mol, "capacity_from_peers", vals, peers_value)
        w = res.get((mol, "world_capacity"))
        if w is not None and isinstance(w.value, int | float):
            world = float(w.value)
            out[(mol, "capacity_from_world_residual")] = leave_one_out(
                mol,
                "capacity_from_world_residual",
                vals,
                lambda rest, world=world: residual_share(world, rest, 1),
            )
    return out


def backtest_markdown(results: dict[tuple[str, str], Backtest], names: dict[str, str], on: dt.date) -> str:
    lo, hi = BACKTEST_BAND
    L = [
        "# Estimate backtest",
        "",
        f"Built {on.isoformat()} by `uv run portolan backtest`. Leave-one-out on the sourced (grade A–C) "
        "capacities of each molecule: hide one value, estimate it from the others, compare. A method is "
        f"enabled for a molecule only if n ≥ {BACKTEST_MIN_N} sourced values **and** at least "
        f"{BACKTEST_MIN_HIT:.0%} of the held-out estimates fall within {lo:g}–{hi:g}× of the true value. "
        "Otherwise the field stays unknown.",
        "",
        "`capacity_from_output` is not an imputation (it rescales the unit's own sourced output) and is "
        "shown as a range; no unit has both a sourced output and a sourced capacity yet, so it cannot be "
        "backtested. "
        "It never applies to by-products.",
        "",
        "| Molecule | Method | n | Within 2× | Result |",
        "|---|---|---:|---:|---|",
    ]
    for (mol, method), b in sorted(results.items(), key=lambda kv: (names.get(kv[0][0], ""), kv[0][1])):
        tested = [r for r in b.rows if r[2] is not None]
        L.append(
            f"| {names.get(mol, mol)} | {method} | {b.n} | {b.hits}/{len(tested)} | "
            f"{'**enabled**' if b.passed else 'disabled'} |"
        )
    L += ["", "## Held-out values", ""]
    for (mol, method), b in sorted(results.items(), key=lambda kv: (names.get(kv[0][0], ""), kv[0][1])):
        if not b.rows:
            continue
        L += [f"**{names.get(mol, mol)} · {method}**", ""]
        L += [
            f"- {uid}: true {t:,.0f} t/a, estimate "
            + (f"{e:,.0f} t/a ({e / t:.2f}×)" if e is not None else "none (too few peers)")
            for uid, t, e in b.rows
        ]
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- the estimate step


def estimate(
    units: list[Unit],
    claims: list[Claim],
    on: dt.date | None = None,
    byproducts: Iterable[str] = (),
    resolved_molecules: Iterable[str] | None = None,
    enabled: set[tuple[str, str]] | None = None,
) -> list[Claim]:
    """Grade-D capacity estimates for units with no sourced capacity.

    `byproducts`: molecules never given a capacity estimate. `resolved_molecules`: molecules whose must-find
    items are all resolved (None = no checklist, treated as resolved). `enabled`: (molecule, method)
    pairs that passed the backtest; None runs the backtest here."""
    on = on or dt.date.today()
    byproducts = set(byproducts)
    live = [c for c in claims if c.review_state not in ("rejected", "superseded")]
    by_id = {c.id: c for c in live}
    sourced = resolve(live, on=on)
    if enabled is None:
        enabled = {k for k, b in backtest(units, live, on).items() if b.passed}
    out: list[Claim] = []

    def got(subject: str, field: str):
        return sourced.get((subject, field))

    def inputs(r) -> list[Claim]:
        return [by_id[i] for i in r.claim_ids if i in by_id]

    by_mol: dict[str, list[Unit]] = defaultdict(list)
    for u in units:
        by_mol[u.molecule_id].append(u)

    for mol, us in by_mol.items():
        if mol in byproducts:
            continue
        caps = {u.id: r for u in us if (r := got(u.id, "capacity")) is not None}
        missing: list[Unit] = []
        for u in us:
            if u.id in caps:
                continue
            if (st := got(u.id, "status")) is not None and st.value in DORMANT:
                continue
            prod = got(u.id, "production")
            if prod is not None and isinstance(prod.value, int | float) and prod.value > 0:
                v = prod.value
                out.append(
                    _claim(
                        u.id,
                        "capacity",
                        round(v / UTILISATION),
                        inputs(prod),
                        "capacity_from_output",
                        v,
                        v / UTIL_LOW,
                        "medium",
                        on,
                    )  # fmt: skip
                )
            else:
                missing.append(u)
        usable = {k: r for k, r in caps.items() if _comparable(r, by_id)}
        known = [float(r.value) for r in usable.values() if isinstance(r.value, int | float) and r.value > 0]
        cap_inputs = [c for r in usable.values() for c in inputs(r)]
        world = got(mol, "world_capacity")
        world_ok = (
            world is not None
            and world.grade in ("A", "B")
            and isinstance(world.value, int | float)
            and (on - world.as_of).days <= WORLD_MAX_AGE_YEARS * 365.25
            and (resolved_molecules is None or mol in resolved_molecules)
            and (mol, "capacity_from_world_residual") in enabled
            and len(usable) == len(caps)  # a basis-unknown unit can't be subtracted from the world figure
        )
        share = residual_share(float(world.value), known, len(missing)) if world_ok else None
        peer = peers_value(known) if (mol, "capacity_from_peers") in enabled else None
        for u in missing:
            if share is not None:
                out.append(_claim(u.id, "capacity", round(share), inputs(world) + cap_inputs,
                                  "capacity_from_world_residual", share * 0.5, min(share * 1.5, max(known)),
                                  "low", on))  # fmt: skip
            elif peer is not None:
                out.append(_claim(u.id, "capacity", round(peer), cap_inputs, "capacity_from_peers",
                                  min(known), statistics.median(known), "low", on))  # fmt: skip
    return out


def last_seen(units: list[Unit], claims: list[Claim], evidence_dates: dict[str, dt.date]) -> dict[str, dict]:
    """Units with no sourced status: the newest date we saw them in a source (evidence publication date, else
    the claim's as_of). The app shows "status unconfirmed (last seen <date>)" instead of inventing one."""
    live = [c for c in claims if c.review_state not in ("rejected", "superseded") and c.confidence != "D"]
    has_status = {c.subject_id for c in live if c.field in ("status", "end_year")}
    out: dict[str, dict] = {}
    for u in units:
        if u.id in has_status:
            continue
        mine = [c for c in live if c.subject_id == u.id]
        if not mine:
            continue
        dated = [
            (min([evidence_dates[e] for e in c.evidence_ids if e in evidence_dates] or [c.as_of]), c)
            for c in mine
        ]
        when, c = max(dated, key=lambda x: x[0])
        out[u.id] = {"last_seen": when.isoformat(), "claim_ids": [c.id]}
    return out
