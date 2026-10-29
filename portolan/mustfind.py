"""Must-find checklist (methodology, rule 8): per item and molecule, is the producer on the map with a sourced
status? Computed from resolved data at build time, so the checklist can't drift from the map.

A molecule of an item is
- `found` when a unit of that molecule, operated by one of the item's companies (or a company in their
  group), at one of its sites if listed, has a sourced (A–C) status; its capacity is then sourced or shown as
  unknown;
- `unfound` when the chain pack records what was searched without result;
- `open` otherwise (no unit, or a unit whose status is unconfirmed)."""

from __future__ import annotations

from portolan.chain import ChainPack
from portolan.models import Unit
from portolan.resolve import Resolved


def status(
    pack: ChainPack,
    units: list[Unit],
    resolved: dict[tuple[str, str], Resolved],
    group: dict[str, str],
) -> list[dict]:
    def operator(u: Unit) -> str | None:
        r = resolved.get((u.id, "operator")) or resolved.get((u.site_id, "operator"))
        return str(r.value) if r else None

    out = []
    for mf in pack.must_find:
        wanted = set(mf.company_ids) | {group.get(c, c) for c in mf.company_ids}
        per: dict[str, dict] = {}
        for mol in mf.molecules:
            mine = [
                u
                for u in units
                if u.molecule_id == mol
                and (not mf.sites or u.site_id in mf.sites)
                and (op := operator(u)) is not None
                and (op in wanted or group.get(op, op) in wanted)
            ]
            with_status = [u for u in mine if (r := resolved.get((u.id, "status"))) and r.grade != "D"]
            if with_status:
                u = with_status[0]
                cap = resolved.get((u.id, "capacity"))
                per[mol] = {
                    "state": "found",
                    "units": [x.id for x in with_status],
                    "capacity": "sourced" if cap is not None and cap.grade != "D" else "unknown",
                }
            elif mol in mf.unfound:
                per[mol] = {"state": "unfound", "searched": mf.unfound[mol]}
            else:
                per[mol] = {
                    "state": "open",
                    "detail": "unit on the map, status unconfirmed" if mine else "no unit on the map",
                    "units": [x.id for x in mine],
                }
        states = {d["state"] for d in per.values()}
        out.append(
            {
                "id": mf.id,
                "label": mf.label,
                "weight": mf.weight,
                "state": "open" if "open" in states else ("found" if states == {"found"} else "resolved"),
                "molecules": per,
            }
        )
    return out


def resolved_molecules(pack: ChainPack, items: list[dict]) -> set[str]:
    """Molecules with no open must-find item (the world-residual estimate needs this)."""
    open_ = {m for it in items for m, d in it["molecules"].items() if d["state"] == "open"}
    return {m.id for m in pack.molecules} - open_
