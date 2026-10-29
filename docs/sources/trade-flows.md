# Trade flows for the chain's HS6 / CN8 codes, 2015–2025

**Result: proven** (2026-10-26). Two keyless routes work. Recipes: `pipeline/sources/comtrade.py`
(G1, HS6, world) and the Comext query below (E9, CN8, EU).

## G1 UN Comtrade (HS6 × reporter × year, partner = World)
- The public **preview** API needs no key: `comtradeapi.un.org/public/v1/preview/C/A/HS?period=…&cmdCode=…
  &flowCode=X|M&partnerCode=0`. Limits: **one period per call** (multi-year → HTTP 400), rows capped (~500), and
  bursts get HTTP 429. Reporter ISO3 comes from `files/v1/app/reference/Reporters.json` (the preview returns
  only M49 codes). No robots.txt (404).
- Example, HS 291219 exports 2024: China 81,797 t, Germany 73,630 t, USA 40,469 t (2015: Germany 103,051 t).
- Full pull of the 15 chain HS6 codes × 11 years × 2 flows = 330 calls: 9 of 15 codes done in ~2.5 h in one sitting
  (429 backoffs dominate); the rest is a background job, not a blocker. Budget a scheduled task for J09.
- Redistribution terms of raw Comtrade rows are not yet checked: rows stay in `cache/flows/`
  (gitignored); only derived aggregates will be published.

## E9 Eurostat Comext (CN8, EU reporters)
- `ec.europa.eu/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409` answers JSON-stat with no
  key, **many years and partners per call** (`time=2015&time=2016…`), ~2–10 s per call. Reporter `EU27_2020`
  gives the EU total; the response also contains aggregates (EU, EA…), so never sum across all reporters.
- EU27 imports (t, from `QUANTITY_IN_100KG` / 10):

| CN8 | Content | from CN 2015 → 2019 → 2023 → 2025 | from IN 2015 → 2025 |
|---|---|---|---|
| 2912 19 00 | other acyclic aldehydes (incl. citral) | 546 → 1,532 → 2,614 → 3,693 | 1,072 → 1,715 |
| 2905 22 00 | acyclic terpene alcohols (geraniol, linalool, …) | 1,476 → 1,355 → 1,154 → 3,917 | 1,928 → 3,101 |
| 2914 23 00 | ionones and methylionones | 369 → 518 → 593 → 1,070 | 44 → 60 |

- *Inference:* The 2023→2025 jump in Chinese terpene alcohols and aldehydes fits new Chinese capacity (Wanhua's
  citral plant started up in 2024) but the codes mix several molecules: a signal for J11 gap probes, never a
  capacity.
- Licence: Eurostat data reusable with attribution (Commission Decision 2011/833/EU) [inference: re-verify for
  Comext].

## Recipe
- World: `pipeline.sources.comtrade.pull_to_cache(hs6_codes, years)` → `to_flows(rows, reporter_iso3())` →
  `portolan.models.Flow` (reporter, partner WLD, hs6, period, kg, USD). Budget ~1.5 s/call plus 429 backoff.
- EU: one Comext call per CN8 × flow with all years and partners; store as `Flow` with `source: eurostat_comext`.
- Codes map to molecules through the chain pack's `hs6`/`cn8` lists; one code often covers many molecules.
