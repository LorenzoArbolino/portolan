"""Eurostat Comext (source E9, J09 `trade_pull`, docs/spikes/G1-E9.md): EU27 imports and exports by partner
for the chain's HS6 codes → `data/flows/<hs6>.parquet` (Flow rows). Eurostat data is reusable with attribution
(Commission Decision 2011/833/EU), recorded in ATTRIBUTION.md. Comtrade rows are not published (terms not
checked). The EU is stored as reporter `EUU` (Comtrade's code for the EU; not an ISO 3166 code)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import httpx

from pipeline.fetch import USER_AGENT
from portolan.models import Flow

API = "https://ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409"
REPORTERS = "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json"
FLOWS = {"1": "import", "2": "export"}


def iso2_to_iso3(client: httpx.Client) -> dict[str, str]:
    res = client.get(REPORTERS).json()["results"]
    out = {
        x["reporterCodeIsoAlpha2"]: x["reporterCodeIsoAlpha3"]
        for x in res
        if x.get("reporterCodeIsoAlpha2") and x.get("reporterCodeIsoAlpha3") and not x.get("isGroup")
    }
    out["GB"] = "GBR"
    return out


def pull_hs6(hs6: str, years: list[int], client: httpx.Client, iso3: dict[str, str]) -> list[Flow]:
    rows: list[Flow] = []
    for flow_code, flow in FLOWS.items():
        params = [
            ("format", "JSON"),
            ("lang", "en"),
            ("freq", "A"),
            ("reporter", "EU27_2020"),
            ("product", hs6),
            ("flow", flow_code),
            ("indicators", "QUANTITY_IN_100KG"),
            ("indicators", "VALUE_IN_EUROS"),
        ]
        params += [("time", str(y)) for y in years]
        d = client.get(API, params=params).json()
        if "dimension" not in d:
            continue
        dims = d["id"]
        sizes = d["size"]
        index = {k: {v: i for i, v in d["dimension"][k]["category"]["index"].items()} for k in dims}
        values = d.get("value", {})
        acc: dict[tuple[str, str], dict] = {}
        for k, v in values.items():
            k = int(k)
            pos = {}
            for dim, size in zip(reversed(dims), reversed(sizes), strict=True):
                pos[dim] = index[dim][k % size]
                k //= size
            key = (pos["partner"], pos["time"])
            acc.setdefault(key, {})[pos["indicators"]] = v
        for (partner, period), ind in acc.items():
            p3 = iso3.get(partner)
            if not p3:  # aggregates (EXT_EU27_2020, …) and codes without ISO3 are skipped, never summed
                continue
            rows.append(
                Flow(
                    reporter_iso3="EUU",
                    partner_iso3=p3,
                    flow=flow,
                    hs6=hs6,
                    period=period,
                    qty_kg=ind.get("QUANTITY_IN_100KG", 0) * 100 if "QUANTITY_IN_100KG" in ind else None,
                    value_eur=ind.get("VALUE_IN_EUROS"),
                    source="eurostat_comext_DS-045409",
                )
            )
    return rows


def write_parquet(rows: list[Flow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE f (reporter_iso3 VARCHAR, partner_iso3 VARCHAR, flow VARCHAR, hs6 VARCHAR, "
        "period VARCHAR, qty_kg DOUBLE, value_usd DOUBLE, value_eur DOUBLE, source VARCHAR)"
    )
    con.executemany(
        "INSERT INTO f VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            [
                r.reporter_iso3,
                r.partner_iso3,
                r.flow,
                r.hs6,
                r.period,
                r.qty_kg,
                r.value_usd,
                r.value_eur,
                r.source,
            ]
            for r in rows
        ],
    )
    con.execute(f"COPY (SELECT * FROM f ORDER BY flow, partner_iso3, period) TO '{path}' (FORMAT PARQUET)")


def trade_pull(hs6_codes: list[str], years: list[int], out_dir: Path = Path("data/flows")) -> dict[str, int]:
    client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=180, follow_redirects=True)
    iso3 = iso2_to_iso3(client)
    counts = {}
    for hs6 in hs6_codes:
        rows = pull_hs6(hs6, years, client, iso3)
        write_parquet(rows, out_dir / f"{hs6}.parquet")
        counts[hs6] = len(rows)
    return counts
