# Indian prospectuses (DRHP / RHP) → installed-capacity tables

**Result: proven** (2026-10-26). 3 RHPs fetched from SEBI's own document store; all 3 carry
installed-capacity tables certified by an independent chartered engineer. Granularity varies a lot.

| RHP | Pages | Table (page) | Granularity | Example row |
|---|---|---|---|---|
| Gem Aromatics Ltd, RHP Aug 2025 ([SEBI](https://www.sebi.gov.in/filings/public-issues/aug-2025/gem-aromatics-limited-rhp_96063.html)) | ~400 | "Installed capacity and capacity utilization" (p. 236) | **facility × product category × fiscal year**: installed, actual production, utilisation | Budaun, "Mint and mint derivatives": FY2025 installed 2,800.00 t, actual 2,226.43 t, 79.52 % |
| Anupam Rasayan India Ltd, RHP Mar 2021 ([SEBI](https://www.sebi.gov.in/filings/public-issues/mar-2021/anupam-rasayan-india-limited-rhp_49435.html)) | 348 | per facility (p. 144) | **facility × year** (multi-purpose plants, no product split) | Sachin Unit-1: FY2020 installed 4,542 MT, production 3,691 MT, 81.27 % |
| Clean Science and Technology Ltd, RHP Jul 2021 ([SEBI](https://www.sebi.gov.in/filings/public-issues/jul-2021/clean-science-and-technology-ltd-_50870.html)) | 331 | aggregate (p. 126) + facility detail | **company total** in the summary: 29,900 MTPA, 71.94 % (FY2021) | — |

## Findings
- SEBI filing pages (`sebi.gov.in/filings/public-issues/...html`) link the full PDF in
  `sebi.gov.in/sebi_data/attachdocs/...pdf`; robots.txt allows both. SEBI's search endpoint (`/sebiweb/ajax/...`)
  answered HTTP 530 to PortolanBot, so documents are found by web search, then fetched from SEBI.
- Capacities are certified ("As certified by Anjaria Enviro Tech Private Limited … certificate dated
  August 4, 2025"): strong `company_primary` / `exchange_filing` evidence, grade A when the quote checks.
- Rows are **product categories** ("Mint and mint derivatives") or **whole multi-purpose facilities**,
  not molecules. *Inference:* They map to a unit only when the category is one molecule; otherwise they're
  site-level context (capacity of a multi-product plant), stored as a site claim with the category in a note.
  Never split a category total across molecules (that would be inventing a number).
- Each table gives installed capacity **and** actual production **and** utilisation, by year: three
  claims per row (`nameplate`, `production`, and a derived utilisation that we don't store).
- `pdftotext -layout` keeps the table rows intact (multi-line headers aside); a 400-page PDF is ~3 MB of
  text, so the planner should hand agents only the "Installed capacity" pages (page finder: pages with
  "installed capacity" + "utili[sz]ation" + an MT/MTPA number).

## Recipe
1. Web search `"<company>" RHP site:sebi.gov.in` → filing page → `attachdocs` PDF.
2. Page finder (above) → extract those pages with layout → `doc_claims` / J06 `filing_extract` on that text.
3. Claims: installed capacity → `capacity`, basis `nameplate`, as_of = fiscal year end; actual production →
   `capacity` with basis `production`; subject = unit if the category is one chain molecule, else site.
