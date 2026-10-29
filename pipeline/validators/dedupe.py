"""`dedupe` validator: sites that may be the same plant → proposed merge (review queue).

Signals: a shared registry ID (decisive), or the same country with similar names (rapidfuzz token-set ≥ 85)
and, when both have coordinates, less than 2 km apart. Merges are never applied here: a reviewer
adjudicates and a merge is recorded in `data/merges.csv`."""

from __future__ import annotations

import math
from dataclasses import dataclass

from rapidfuzz import fuzz

from portolan.models import Site

NAME_SIMILARITY = 85
MAX_KM = 2.0


@dataclass
class Candidate:
    a: str
    b: str
    reason: str


def _bare(name: str) -> str:
    return name.lower().replace("(plant location not public)", "").strip()


def same_locality(a: str, b: str) -> bool:
    """'Ludwigshafen' = 'Ludwigshafen am Rhein' = 'ludwigshafen-am-rhein'; 'Mahad' ≠ 'Mahadevapura'."""
    from portolan.ids import slugify

    x, y = slugify(a), slugify(b)
    return x == y or x.startswith(y + "-") or y.startswith(x + "-")


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def candidates(sites: list[Site], new_ids: set[str] | None = None) -> list[Candidate]:
    """Pairs to review. With `new_ids`, only pairs involving at least one new site."""
    out: list[Candidate] = []
    for i, a in enumerate(sites):
        for b in sites[i + 1 :]:
            if new_ids is not None and a.id not in new_ids and b.id not in new_ids:
                continue
            shared = {k for k, v in a.registry_ids.items() if b.registry_ids.get(k) == v}
            if shared:
                out.append(Candidate(a.id, b.id, f"shared registry id: {', '.join(sorted(shared))}"))
                continue
            if a.country != b.country:
                continue
            sim = fuzz.token_set_ratio(_bare(a.name), _bare(b.name))
            if sim < NAME_SIMILARITY:
                continue
            if None not in (a.lat, a.lon, b.lat, b.lon):
                d = km(a.lat, a.lon, b.lat, b.lon)
                if d < MAX_KM:
                    out.append(Candidate(a.id, b.id, f"names {sim:.0f}% similar, {d:.1f} km apart"))
            elif same_locality(a.locality, b.locality):
                out.append(Candidate(a.id, b.id, f"names {sim:.0f}% similar, same locality, no coordinates"))
    return out
