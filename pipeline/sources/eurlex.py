"""EU trade-defence regulations (source E10, docs/spikes/E10.md): CELEX → Measure + Union-industry rows.

EUR-Lex's HTML pages sit behind a JavaScript bot check; the Publications Office CELLAR endpoint serves the
same act as XHTML to plain HTTP clients (robots.txt allows it). EU legal acts are reusable under Commission
Decision 2011/833/EU with attribution."""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from pipeline.fetch import USER_AGENT
from pipeline.validators.quote_check import extract_text
from portolan.ids import company_id, measure_id
from portolan.models import CompanyRate, Measure

CELLAR = "https://publications.europa.eu/resource/celex/{celex}"
_PCT = r"(\d{1,3}(?:,\d+)?)\s*%"


def fetch_celex(celex: str, client: httpx.Client | None = None) -> str:
    c = client or httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60)
    r = c.get(
        CELLAR.format(celex=celex), headers={"Accept": "application/xhtml+xml", "Accept-Language": "eng"}
    )
    r.raise_for_status()
    return re.sub(r"[ \t]+", " ", extract_text(r.content, r.headers.get("content-type", "")))


def _num(s: str) -> float:
    return float(s.replace(" ", "").replace(",", "."))


def parse_measure(text: str, celex: str, url: str | None = None) -> Measure:
    """Article 1 of a definitive AD/CVD regulation → Measure (rates, company rates, CN codes, origin)."""
    art1 = text[text.rfind("\nArticle 1\n") :] if "\nArticle 1\n" in text else text[text.rfind("Article 1") :]
    art1 = art1[: art1.find("Article 2")] if "Article 2" in art1 else art1
    cn = sorted(
        {re.sub(r"\s", "", c) for c in re.findall(r"CN codes?\s+((?:ex\s*)?\d{4}\s?\d{2}\s?\d{2})", art1)}
    )
    title = re.search(r"(REGULATION \(EU\) (\d{4})/(\d+))", text)
    year, num = (title.group(2), title.group(3)) if title else (celex[1:5], celex[6:].lstrip("0"))
    instrument = "cvd" if "countervailing" in art1.lower() else "ad"
    origin = []
    if "People’s Republic of China" in art1 or "People's Republic of China" in art1:
        origin.append("CHN")
    for m in re.finditer(
        r"originating in (India|the United States of America|Indonesia|Malaysia|Brazil)", art1
    ):
        origin.append(
            {
                "India": "IND",
                "the United States of America": "USA",
                "Indonesia": "IDN",
                "Malaysia": "MYS",
                "Brazil": "BRA",
            }[m.group(1)]
        )
    rates: list[CompanyRate] = []
    rows = re.findall(rf"\|\s*([^|\n]+?)\s*\|\s*{_PCT}\s*\|", art1)
    for name, pct in rows:
        if not re.search(r"all other|other cooperating", name, re.IGNORECASE):
            rates.append(CompanyRate(company_id=company_id(name), rate=_num(pct)))
    all_rates = [_num(p) for _, p in rows] or [_num(p) for p in re.findall(rf"shall be {_PCT}", art1)]
    product = re.search(r"imports of (.+?),? (?:currently )?falling under", art1)
    return Measure(
        id=measure_id("eu", f"{year}-{num}"),
        jurisdiction="EU",
        instrument=instrument,
        product_desc=product.group(1).strip() if product else "",
        cn_codes=cn,
        origin_iso3=sorted(set(origin)),
        rate_min=min(all_rates) if all_rates else None,
        rate_max=max(all_rates) if all_rates else None,
        company_rates=rates,
        legal_ref=f"Commission Implementing Regulation (EU) {year}/{num}",
        url=url or CELLAR.format(celex=celex),
    )


@dataclass
class IndustryRow:
    indicator: str  # e.g. "Production capacity (tonnes)"
    values: list[str]  # one per period, as printed: "[3 900 – 4 500 ]", "98 %", "12 345"


def union_industry_rows(text: str) -> list[IndustryRow]:
    """Rows of the Union-industry injury tables (production, capacity, utilisation). Values are kept as
    printed: with one or two Union producers they are confidentiality ranges, not numbers."""
    out = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.match(
            r"(Production capacity|Capacity utilisation|Production volume|"
            r"Total Union production)",
            cells[0],
        ):
            out.append(IndustryRow(cells[0], [c for c in cells[1:] if c]))
    return out
