"""Coverage notes (`data/coverage.csv`): for each country with a trade or production
signal, what Portolan knows. Gaps are data: a country that exports a chain code to the EU but has no unit is a
lead for J11 gap probes. Notes are generated from facts only (flows and resolved claims)."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import duckdb

from portolan.chain import ChainPack
from portolan.resolve import resolve
from portolan.store import Store

ISO3_TO_2 = {
    "CHN": "CN",
    "IND": "IN",
    "USA": "US",
    "JPN": "JP",
    "MYS": "MY",
    "BRA": "BR",
    "IDN": "ID",
    "CHE": "CH",
    "GBR": "GB",
    "KOR": "KR",
    "SGP": "SG",
    "TUR": "TR",
    "MEX": "MX",
    "ZAF": "ZA",
    "VNM": "VN",
    "THA": "TH",
    "ISR": "IL",
    "RUS": "RU",
    "CAN": "CA",
    "ARG": "AR",
    "TWN": "TW",
    "NOR": "NO",
    "AUS": "AU",
}
COLUMNS = [
    "chain_id",
    "country",
    "molecule_id",
    "units_known",
    "units_with_status",
    "units_with_capacity",
    "eu_imports_t_latest",
    "eu_imports_year",
    "hs6",
    "note",
]


def eu_imports(flows_dir: Path, hs6: str) -> dict[str, tuple[str, float]]:
    """Partner ISO3 → (latest year, tonnes) of EU27 imports for one HS6 code."""
    p = flows_dir / f"{hs6}.parquet"
    if not p.exists():
        return {}
    q = (
        f"SELECT partner_iso3, period, sum(qty_kg)/1000 FROM '{p}' "
        f"WHERE flow='import' AND qty_kg IS NOT NULL GROUP BY 1,2"
    )
    out: dict[str, tuple[str, float]] = {}
    for partner, period, t in duckdb.sql(q).fetchall():
        if partner not in out or period > out[partner][0]:
            out[partner] = (period, round(t, 1))
    return out


def coverage(
    pack: ChainPack,
    store: Store,
    flows_dir: Path = Path("data/flows"),
    min_t: float = 10.0,
    on: dt.date | None = None,
) -> list[dict]:
    units = store.load("units")
    sites = {s.id: s for s in store.load("sites")}
    res = resolve(store.load("claims"), on=on)
    rows = []
    for m in pack.molecules:
        if m.tier == "base" or m.role == "context":
            continue
        signals: dict[str, tuple[str, float, str]] = {}
        for hs6 in m.hs6:
            for p3, (year, t) in eu_imports(flows_dir, hs6).items():
                if t >= min_t and p3 in ISO3_TO_2:
                    c2 = ISO3_TO_2[p3]
                    if c2 not in signals or t > signals[c2][1]:
                        signals[c2] = (year, t, hs6)
        mol_units = [u for u in units if u.molecule_id == m.id and u.site_id in sites]
        countries = sorted(set(signals) | {sites[u.site_id].country for u in mol_units})
        for c in countries:
            cu = [u for u in mol_units if sites[u.site_id].country == c]
            with_status = sum((u.id, "status") in res for u in cu)
            with_cap = sum((u.id, "capacity") in res for u in cu)
            year, t, hs6 = signals.get(c, ("", 0.0, ""))
            if not cu:
                note = f"gap: EU imported {t:g} t of HS {hs6} from {c} in {year}, no unit known (J11 lead)"
            elif with_status < len(cu):
                note = f"{len(cu) - with_status} of {len(cu)} known units lack a status claim"
            else:
                note = "all known units have a status claim"
            rows.append(
                {
                    "chain_id": pack.id,
                    "country": c,
                    "molecule_id": m.id,
                    "units_known": len(cu),
                    "units_with_status": with_status,
                    "units_with_capacity": with_cap,
                    "eu_imports_t_latest": t if t else "",
                    "eu_imports_year": year,
                    "hs6": hs6,
                    "note": note,
                }
            )
    return rows


def write_coverage(rows: list[dict], path: Path = Path("data/coverage.csv")) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path
