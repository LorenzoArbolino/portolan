# EU trade-defence regulations → measures + Union-industry tables

**Result: proven** (2026-10-26). Recipe: `pipeline/sources/eurlex.py`, tests `tests/test_eurlex.py`.

| Regulation | Measure parsed | Union-industry table |
|---|---|---|
| (EU) 2025/1151, vanillin, CN ex 2912 41 00, origin CN | AD 131,1 % (single rate) | capacity `[3 900 – 4 500]` → `[4 300 – 4 900]` t, utilisation 98 % → 35 % (ranges) |
| (EU) 2026/913, adipic acid, CN 2917 12 00, origin CN | AD 29,1 % (Chongqing Huafon), 42,3 % (Tangshan Zhonghao), 31,5 % (other cooperating), 42,3 % (all others) | in the provisional act |
| (EU) 2025/2287 (provisional, adipic acid) | n/a | capacity 847 552 → 742 145 t, utilisation 82 % → 60 % (4 periods) |

## Findings
- EUR-Lex HTML (`eur-lex.europa.eu/legal-content/...`) returned an empty 200 body to PortolanBot. *Inference:* It's a JavaScript bot check. The Publications Office **CELLAR** endpoint serves the same act as XHTML: `https://publications.europa.eu/resource/celex/<CELEX>` with `Accept: application/xhtml+xml`, `Accept-Language: eng`. Its robots.txt allows it.
- With a single Union producer (vanillin: Syensqo had 98 % of Union production), the Commission publishes **ranges** "for reasons of confidentiality"; with several producers (adipic acid) it publishes the real totals. Ranges are never turned into a number (no quote, no number): they stay as printed. The units validator already refuses them. A `range` value type for aggregate claims is not built yet.
- Article 1 carries a clean `| company | rate % | TARIC code |` table in the CELLAR text, so company rates parse deterministically. `company_id` is derived from the name; matching to existing companies goes through the resolver and merges.
- Decimal commas (`29,1 %`) and space thousands separators (`847 552`) need the separator rules already in `units.parse_number`.
- Gap: the product description regex misses the vanillin wording; fine for now (`legal_ref` + CN codes identify the measure).

## Recipe
```python
from pipeline.sources.eurlex import fetch_celex, parse_measure, union_industry_rows

text = fetch_celex("32026R0913")
measure = parse_measure(text, "32026R0913")  # → portolan.models.Measure
rows = union_industry_rows(fetch_celex("32025R2287"))  # capacity / production / utilisation as printed
```
Licence: EU legal acts are reusable under Commission Decision 2011/833/EU with attribution (re-verify per dataset, 03 §7).
