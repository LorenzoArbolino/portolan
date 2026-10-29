"""`geo` validator: a point must lie in the country the site claims, and the precision must fit.

Offline check against Natural Earth 1:50m bounding boxes, one box per polygon part (`country_boxes.json`,
public domain), with a margin for coastal plants. Coarse by design: it catches swapped lat/lon, wrong signs
and wrong countries, not a point 5 km off."""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

BOXES = Path(__file__).with_name("country_boxes.json")
MARGIN_DEG = 0.25


@cache
def _boxes() -> dict[str, list[list[float]]]:
    return json.loads(BOXES.read_text(encoding="utf-8"))["boxes"]


def in_country(lat: float, lon: float, iso2: str, margin: float = MARGIN_DEG) -> bool | None:
    """True/False, or None when the country isn't in the table."""
    boxes = _boxes().get(iso2.upper())
    if not boxes:
        return None
    return any(
        x0 - margin <= lon <= x1 + margin and y0 - margin <= lat <= y1 + margin for x0, y0, x1, y1 in boxes
    )


_DMS = re.compile(
    r"(\d+(?:\.\d+)?)\s*°\s*(?:(\d+(?:\.\d+)?)\s*[′'’])?\s*(?:(\d+(?:\.\d+)?)\s*[″\"”])?\s*([NSEW])",
    re.IGNORECASE,
)
_HEMI_ZH = {"北纬": "N", "南纬": "S", "东经": "E", "西经": "W"}


def parse_lat_lon(text: str) -> tuple[float, float] | None:
    """Parse '37°0′52″N 119°7′47″E', '18°06.397’N … 73°29.321’E' (decimal minutes),
    '北纬 37°0′52″ 东经 119°7′47″' or '49.48, 8.44'. None if unsure."""
    t = text.strip()
    for zh, h in _HEMI_ZH.items():
        t = re.sub(zh + r"\s*([\d.°′'″\" ]+)", lambda m, h=h: m.group(1).strip() + h, t)
    parts = _DMS.findall(t)
    if len(parts) == 2:
        vals = {}
        for deg, mins, secs, hemi in parts:
            v = float(deg) + float(mins or 0) / 60 + float(secs or 0) / 3600
            hemi = hemi.upper()
            vals["lat" if hemi in "NS" else "lon"] = -v if hemi in "SW" else v
        if set(vals) == {"lat", "lon"}:
            return round(vals["lat"], 6), round(vals["lon"], 6)
        return None
    m = re.fullmatch(r"\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*", t)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def check(lat: float, lon: float, iso2: str, precision: str) -> list[str]:
    problems = []
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return [f"geo: {lat},{lon} is not a coordinate"]
    inside = in_country(lat, lon, iso2)
    if inside is False:
        swapped = in_country(lon, lat, iso2) if -90 <= lon <= 90 else False
        problems.append(f"geo: {lat},{lon} is outside {iso2}" + (" (lat/lon swapped?)" if swapped else ""))
    if precision == "country":
        problems.append("geo: a point with precision 'country' would be invented; drop the point")
    return problems
