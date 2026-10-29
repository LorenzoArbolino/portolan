"""Merges: when two IDs turn out to be the same thing, `data/merges.csv` records `from_id → to_id`.
IDs are never rewritten in the data; the build applies the merges, so the decision stays visible and
reversible.
A merged site's units follow it: `unit:<from-site>:<mol>` becomes `unit:<to-site>:<mol>`."""

from __future__ import annotations

from portolan.models import Claim, Event, Merge, Site, Unit


def id_map(merges: list[Merge], units: list[Unit]) -> dict[str, str]:
    m = {x.from_id: x.to_id for x in merges}

    def final(i: str) -> str:
        seen = set()
        while i in m and i not in seen:
            seen.add(i)
            i = m[i]
        return i

    out = {k: final(k) for k in m}
    for u in units:
        if u.site_id in out:
            to_site = out[u.site_id].removeprefix("site:")
            out[u.id] = f"unit:{to_site}:{u.id.split(':', 2)[2]}"
    return out


def apply(
    ids: dict[str, str], units: list[Unit], sites: list[Site], claims: list[Claim], events: list[Event]
):
    if not ids:
        return units, sites, claims, events
    new_units = {}
    for u in units:
        nu = u.model_copy(update={"id": ids.get(u.id, u.id), "site_id": ids.get(u.site_id, u.site_id)})
        new_units.setdefault(nu.id, nu)
    sites = [s for s in sites if s.id not in ids]
    claims = [
        c.model_copy(
            update={
                "subject_id": ids.get(c.subject_id, c.subject_id),
                "value_norm": ids.get(c.value_norm, c.value_norm)
                if isinstance(c.value_norm, str)
                else c.value_norm,
            }
        )
        for c in claims
    ]
    # Events: a merged event folds into its target (one real-world event, several sources).
    by_id = {e.id: e.model_copy(update={"subjects": [ids.get(s, s) for s in e.subjects]}) for e in events}
    for e in list(by_id.values()):
        to = ids.get(e.id)
        if to and to in by_id and to != e.id:
            t = by_id[to]
            by_id[to] = t.model_copy(
                update={
                    "subjects": list(dict.fromkeys(t.subjects + e.subjects)),
                    "evidence_ids": sorted(set(t.evidence_ids) | set(e.evidence_ids)),
                }
            )
            del by_id[e.id]
    return list(new_units.values()), sites, claims, list(by_id.values())
