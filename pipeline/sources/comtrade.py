"""UN Comtrade (source G1, J09 `trade_pull`, docs/spikes/G1-E9.md): HS6 × reporter × year flows via the
keyless public preview API (no account; partner = World keeps each call well under the preview's row cap).

Raw rows go to the gitignored cache until Comtrade's redistribution terms are checked; only derived
aggregates are publishable. HS6 codes group several molecules (291219 is "other acyclic aldehydes", not
citral alone), so flows are a signal for gap probes, never a capacity."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from pipeline.fetch import USER_AGENT
from portolan.models import Flow

PREVIEW = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
REPORTERS = "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json"


def reporter_iso3(client: httpx.Client | None = None) -> dict[int, str]:
    """M49 reporter code → ISO3 (the preview API returns only the numeric code). Groups are skipped."""
    c = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60)
    res = c.get(REPORTERS).json()["results"]
    return {
        x["reporterCode"]: x["reporterCodeIsoAlpha3"]
        for x in res
        if not x.get("isGroup") and x.get("reporterCodeIsoAlpha3")
    }


def pull(
    hs6: str, years: list[int], flow: str = "X", client: httpx.Client | None = None, delay_s: float = 1.5
) -> list[dict]:
    c = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60)
    rows: list[dict] = []
    for y in years:
        for attempt in range(3):
            r = c.get(
                PREVIEW, params={"period": str(y), "partnerCode": "0", "cmdCode": hs6, "flowCode": flow}
            )
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
            rows += r.json().get("data") or []
            break
        time.sleep(delay_s)
    return rows


def to_flows(rows: list[dict], iso3: dict[int, str]) -> list[Flow]:
    out = []
    for x in rows:
        iso = x.get("reporterISO") or iso3.get(x.get("reporterCode"))
        if not iso or len(iso) != 3 or not iso.isalpha():
            continue
        out.append(
            Flow(
                reporter_iso3=iso,
                partner_iso3="WLD",
                flow="export" if x.get("flowCode") == "X" else "import",
                hs6=str(x["cmdCode"]),
                period=str(x["period"]),
                qty_kg=x.get("netWgt"),
                value_usd=x.get("primaryValue"),
                source="un_comtrade_preview",
            )
        )
    return out


def pull_to_cache(
    hs6_codes: list[str], years: list[int], cache: Path = Path("cache/flows")
) -> dict[str, int]:
    cache.mkdir(parents=True, exist_ok=True)
    counts = {}
    for hs6 in hs6_codes:
        rows = pull(hs6, years, "X") + pull(hs6, years, "M")
        (cache / f"{hs6}.json").write_text(json.dumps(rows), encoding="utf-8")
        counts[hs6] = len(rows)
    return counts
