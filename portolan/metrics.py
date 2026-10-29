"""Derived metrics, computed at build from resolved values and never stored as
claims. Every metric carries the claim IDs it used, so a headline number is as traceable as a single claim.

Counted capacity: units whose resolved status is operating, commissioning, idle or closing and whose
capacity is resolved (not contested-without-value, not production). Units with unknown capacity or status
are counted separately, never estimated."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from portolan.chain import ChainPack
from portolan.models import Claim, Site, Unit
from portolan.resolve import Resolved, resolve

ACTIVE = {"operating", "commissioning", "idle", "closing"}


@dataclass
class Metric:
    value: object
    claim_ids: list[str] = field(default_factory=list)
    note: str | None = None


@dataclass
class MoleculeMetrics:
    molecule_id: str
    on: str
    world_capacity_tpa: Metric
    units_counted: int
    units_unknown_capacity: list[str]
    units_unknown_status: list[str]
    share_by_site: dict[str, float]
    share_by_company: dict[str, float]
    share_by_country: dict[str, float]
    hhi_company: Metric
    hhi_country: Metric
    route_mix: Metric
    pinch_point_score: Metric
    gap_estimate_tpa: None = None  # gap probes; shown separately, never added to world capacity

    def to_dict(self) -> dict:
        return asdict(self)


def _hhi(shares: dict[str, float]) -> float:
    return round(sum((100 * s) ** 2 for s in shares.values()), 1)


def _shares(cap: dict[str, float]) -> dict[str, float]:
    total = sum(cap.values())
    return {k: round(v / total, 4) for k, v in sorted(cap.items(), key=lambda kv: -kv[1])} if total else {}


def main_route_inputs(pack: ChainPack) -> dict[str, set[str]]:
    """Product → inputs of its main route. Main route = the first route listed for the product in the pack
    (until route_mix data says otherwise)."""
    out: dict[str, set[str]] = {}
    for r in pack.routes:
        out.setdefault(r.product, set(r.inputs))
    return out


def downstream_dependants(pack: ChainPack, molecule_id: str) -> list[str]:
    """Molecules whose main route depends on `molecule_id`, directly or through other dependants."""
    main = main_route_inputs(pack)
    found: set[str] = set()
    frontier = {molecule_id}
    while frontier:
        nxt = {p for p, ins in main.items() if ins & frontier and p not in found and p != molecule_id}
        found |= nxt
        frontier = nxt
    return sorted(found)


def molecule_metrics(
    pack: ChainPack,
    molecule_id: str,
    units: list[Unit],
    sites: dict[str, Site],
    claims: list[Claim],
    on: dt.date | None = None,
    resolved: dict[tuple[str, str], Resolved] | None = None,
) -> MoleculeMetrics:
    on = on or dt.date.today()
    res = resolved if resolved is not None else resolve(claims, on=on)
    mol_units = [u for u in units if u.molecule_id == molecule_id]
    cap: dict[str, float] = {}
    used: dict[str, list[str]] = {}
    unknown_cap, unknown_status = [], []
    for u in mol_units:
        st = res.get((u.id, "status"))
        if st is None:
            unknown_status.append(u.id)
            continue
        if st.value not in ACTIVE:
            continue
        c = res.get((u.id, "capacity"))
        if c is None or not isinstance(c.value, int | float) or c.outcome == "contested":
            unknown_cap.append(u.id)
            continue
        cap[u.id] = float(c.value)
        used[u.id] = st.claim_ids + c.claim_ids

    def owner(u_id: str) -> tuple[str, list[str]]:
        site_id = next(u.site_id for u in mol_units if u.id == u_id)
        r = res.get((u_id, "operator")) or res.get((site_id, "operator"))
        return (str(r.value), r.claim_ids) if r else ("unknown", [])

    by_site: dict[str, float] = defaultdict(float)
    by_company: dict[str, float] = defaultdict(float)
    by_country: dict[str, float] = defaultdict(float)
    by_route: dict[str, float] = defaultdict(float)
    for u_id, v in cap.items():
        u = next(x for x in mol_units if x.id == u_id)
        by_site[u.site_id] += v
        co, co_ids = owner(u_id)
        used[u_id] = used[u_id] + co_ids
        by_company[co] += v
        by_country[sites[u.site_id].country if u.site_id in sites else "unknown"] += v
        rr = res.get((u_id, "route"))
        route = str(rr.value) if rr else (u.route_id or "unknown")
        if rr:
            used[u_id] = used[u_id] + rr.claim_ids
        by_route[route] += v
    all_ids = sorted({i for ids_ in used.values() for i in ids_})
    site_shares = _shares(dict(by_site))
    deps = downstream_dependants(pack, molecule_id)
    top_share = max(site_shares.values(), default=0.0)
    return MoleculeMetrics(
        molecule_id=molecule_id,
        on=on.isoformat(),
        world_capacity_tpa=Metric(
            round(sum(cap.values()), 1),
            all_ids,
            f"{len(cap)} units with known capacity; {len(unknown_cap)} unknown",
        ),
        units_counted=len(cap),
        units_unknown_capacity=sorted(unknown_cap),
        units_unknown_status=sorted(unknown_status),
        share_by_site=site_shares,
        share_by_company=_shares(dict(by_company)),
        share_by_country=_shares(dict(by_country)),
        hhi_company=Metric(_hhi(_shares(dict(by_company))), all_ids),
        hhi_country=Metric(_hhi(_shares(dict(by_country))), all_ids),
        route_mix=Metric(_shares(dict(by_route)), all_ids),
        pinch_point_score=Metric(
            round(top_share * len(deps), 3),
            all_ids,
            f"top site share {top_share:.0%} × {len(deps)} dependants: {', '.join(deps)}",
        ),
    )
