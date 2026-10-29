"""Offline basemap for the app (used when the vector tiles can't load): Natural Earth 1:110m land and land
borders, public domain, coordinates rounded to 0.01°. Run from the repo root:
`uv run python app/scripts/make_basemap.py` → app/public/basemap.json"""

import json
from pathlib import Path

from pipeline.fetch import Fetcher

BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
LAYERS = {"land": "ne_110m_land.geojson", "borders": "ne_110m_admin_0_boundary_lines_land.geojson"}


def _round(c):
    return [_round(x) for x in c] if isinstance(c[0], list) else [round(c[0], 2), round(c[1], 2)]


def main() -> None:
    f, out = Fetcher(), {}
    for name, file in LAYERS.items():
        got = f.get(BASE + file)
        assert got.ok, got.reason
        feats = json.loads(got.content)["features"]
        out[name] = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": x["geometry"]["type"],
                        "coordinates": _round(x["geometry"]["coordinates"]),
                    },
                }
                for x in feats
            ],
        }
    path = Path("app/public/basemap.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
