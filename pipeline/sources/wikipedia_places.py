"""Approximate site placement (town level) when no document prints the plant's coordinates.

Online geocoders refuse crawlers (Nominatim /search, Photon, Overpass, GeoNames and Wikidata APIs all disallow
them in robots.txt); Wikipedia article pages are allowed and print each town's coordinates in a `geo` span.
The result is a `locality`-precision point, written to `data/site_locations.csv` with its source URL, never a
claim about the plant itself, and drawn on the map as an approximate marker. Coordinates are facts; the source
is credited in ATTRIBUTION.md.

Fallback when Wikipedia has no page or refuses the request (since 2026-10-27 it answers our bot with "Please
respect our robot policy"; we do not work around that): Natural Earth 1:10m populated places, public domain,
fetched once from the project's GitHub mirror."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

from pipeline.fetch import Fetcher
from portolan.models import Site

COUNTRY_NAMES = {
    "CN": ["China"],
    "IN": ["India"],
    "DE": ["Germany"],
    "FR": ["France"],
    "CH": ["Switzerland"],
    "IT": ["Italy"],
    "ES": ["Spain"],
    "NL": ["Netherlands"],
    "BE": ["Belgium"],
    "FI": ["Finland"],
    "SE": ["Sweden"],
    "US": ["United States", "U.S."],
    "JP": ["Japan"],
    "MY": ["Malaysia"],
    "BR": ["Brazil"],
    "ID": ["Indonesia"],
    "GB": ["United Kingdom", "England", "Scotland"],
    "KR": ["Korea"],
    "SG": ["Singapore"],
    "AT": ["Austria"],
    "PL": ["Poland"],
    "MX": ["Mexico"],
    "PT": ["Portugal"],
    "TR": ["Turkey"],
}
GEO = re.compile(r'<span class="geo">\s*(-?\d+(?:\.\d+)?)\s*;\s*(-?\d+(?:\.\d+)?)\s*</span>')
COLUMNS = ["site_id", "lat", "lon", "geo_precision", "source_url", "note"]


def locate(site: Site, fetcher: Fetcher) -> dict | None:
    names = [site.locality]
    if site.admin1:
        names.append(f"{site.locality}, {site.admin1}")
    for name in names:
        url = "https://en.wikipedia.org/wiki/" + quote(name.replace(" ", "_"))
        got = fetcher.get(url)
        if not got.ok:
            continue
        html = got.content.decode("utf-8", errors="replace")
        if "may refer to" in html[:20000]:  # disambiguation page
            continue
        if not any(c in html for c in COUNTRY_NAMES.get(site.country, [site.country])):
            continue
        m = GEO.search(html)
        if m:
            return {
                "site_id": site.id,
                "lat": float(m.group(1)),
                "lon": float(m.group(2)),
                "geo_precision": "locality",
                "source_url": url,
                "note": f"town centre of {site.locality} (Wikipedia), not the plant",
            }
    return None


NE_PLACES = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
    "ne_10m_populated_places_simple.geojson"
)


def ne_places(fetcher: Fetcher) -> list[dict]:
    got = fetcher.get(NE_PLACES)
    if not got.ok:
        return []
    return [f["properties"] for f in json.loads(got.content)["features"]]


def locate_ne(site: Site, places: list[dict]) -> dict | None:
    """Match each comma-separated part of the locality (most specific first) to a Natural Earth place."""
    for part in (p.strip() for p in (site.locality or "").split(",")):
        hits = [
            p
            for p in places
            if p.get("iso_a2") == site.country
            and part.lower() in (str(p.get("name", "")).lower(), str(p.get("nameascii", "")).lower())
        ]
        if site.admin1 and len(hits) > 1:
            hits = [p for p in hits if str(p.get("adm1name", "")).lower() == site.admin1.lower()] or hits
        if len(hits) == 1:
            p = hits[0]
            return {
                "site_id": site.id,
                "lat": round(float(p["latitude"]), 5),
                "lon": round(float(p["longitude"]), 5),
                "geo_precision": "locality",
                "source_url": NE_PLACES,
                "note": f"town centre of {p['name']} (Natural Earth populated places), not the plant",
            }
    return None


US_STATES = {
    "AL": "Alabama", "AR": "Arkansas", "CA": "California", "FL": "Florida", "GA": "Georgia",
    "LA": "Louisiana", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "NC": "North Carolina", "NJ": "New Jersey",
    "OH": "Ohio", "SC": "South Carolina", "TX": "Texas", "VA": "Virginia", "WA": "Washington",
    "WI": "Wisconsin", "OR": "Oregon", "ME": "Maine", "KY": "Kentucky", "TN": "Tennessee", "IN": "Indiana",
    "PA": "Pennsylvania", "NY": "New York", "IL": "Illinois", "MD": "Maryland", "WV": "West Virginia",
}  # fmt: skip


def locate_region(site: Site, places: list[dict]) -> dict | None:
    """Last resort, for the map only: the largest town of the site's province/state, else of its country.
    Marked approximate (`geo_precision` admin1 or country), with a small fixed offset so plants don't
    stack."""
    admin1 = US_STATES.get(site.admin1 or "", site.admin1 or "").lower()
    in_country = [p for p in places if p.get("iso_a2") == site.country]
    pool = [p for p in in_country if admin1 and str(p.get("adm1name", "")).lower() == admin1]
    precision = "admin1" if pool else "country"
    pool = pool or in_country
    if not pool:
        return None
    p = max(pool, key=lambda x: float(x.get("pop_max") or 0))
    h = int(hashlib.sha1(site.id.encode()).hexdigest()[:8], 16)  # stable jitter, ±0.15° / ±0.4°
    spread = 0.15 if precision == "admin1" else 0.4
    dx, dy = ((h % 1000) / 1000 - 0.5) * 2 * spread, (((h // 1000) % 1000) / 1000 - 0.5) * 2 * spread
    return {
        "site_id": site.id,
        "lat": round(float(p["latitude"]) + dy, 4),
        "lon": round(float(p["longitude"]) + dx, 4),
        "geo_precision": precision,
        "source_url": NE_PLACES,
        "note": f"approximate: near {p['name']}, the largest town of the "
        + ("province or state" if precision == "admin1" else "country"),
    }


def read_locations(path: Path = Path("data/site_locations.csv")) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["site_id"]: r for r in csv.DictReader(f)}


def write_locations(rows: dict[str, dict], path: Path = Path("data/site_locations.csv")) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        for k in sorted(rows):
            w.writerow({c: rows[k][c] for c in COLUMNS})
