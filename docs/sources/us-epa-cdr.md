# EPA Chemical Data Reporting (CDR) — are site-level fields public?

**Result: proven, with limits** (2026-10-26). Source: 2024 CDR public CSV (reporting year 2023),
`https://www.epa.gov/system/files/other-files/2026-04/2024-cdr-public-csv-data.zip` (14 MB zip, 4 CSVs + dictionary).

## Findings
- The public file has **one record per site × chemical** with site name, address, latitude/longitude, parent
  company, activity (`Manufacture` / `Import` / `Both`) and **production volumes in lb**: `2023 DOMESTIC PV`,
  `2023 IMPORT PV`, `2023 PV`, `2022 PV`, … unless claimed as CBI (then the cell reads `CBI`).
- An older EPA page says the 2016 release "withheld … all site-specific production volumes"; EPA later
  re-released 2016 data with them, and the 2020 and 2024 public files carry the fields. The 03-sources note
  "public site fields unconfirmed" is now answered: they exist, filled where not CBI.
- These are **production volumes (actual output)**, not capacity: they enter as `capacity_basis: production`
  and never display as capacity (01 §6 rule 4). They also tell producers (`Manufacture`) from importers.
- Coordinates come with the record: a geocoding source for US sites (J14).
- Licence: US federal government work, public domain [inference: confirm the dataset page carries no extra terms].

## Chain coverage (2024 CDR, chain CAS numbers)

| molecule | site records | manufacture or both | of which 2023 domestic PV public | PV CBI | activity CBI |
|---|---|---|---|---|---|
| L-menthol | 11 | 1 | 0 | 1 | 1 |
| alpha-pinene | 34 | 2 | 1 | 1 | 0 |
| beta-ionone | 6 | 0 | 0 | 0 | 1 |
| beta-pinene | 38 | 2 | 1 | 1 | 0 |
| citral | 48 | 0 | 0 | 0 | 2 |
| dihydromyrcenol | 51 | 2 | 1 | 1 | 1 |
| geraniol | 41 | 3 | 1 | 2 | 1 |
| isoprenol | 2 | 0 | 0 | 0 | 0 |
| linalool | 54 | 3 | 1 | 2 | 1 |
| menthol (racemic) | 2 | 1 | 0 | 1 | 0 |
| myrcene | 4 | 2 | 1 | 1 | 0 |
| turpentine | 47 | 41 | 40 | 1 | 1 |
| vitamin E acetate | 2 | 0 | 0 | 0 | 0 |


- **Turpentine** is the standout: 40 kraft mills publish 2023 crude sulphate turpentine output (e.g. Packaging
  Corp of America, Counce TN, 10,000,000 lb ≈ 4,536 t; International Paper, Bogalusa LA, 6,000,000 lb). That is
  the US feedstock map for the pine branch of the chain.
- **Pine chemicals**: IFF, Jacksonville FL publishes alpha-pinene 15,246,111 lb (≈ 6,915 t), myrcene 10,715,764
  lb, beta-pinene 5,852,424 lb, geraniol 274,590 lb for 2023.
- **Citral, β-ionone, vitamin E acetate, isoprenol**: no US manufacture reported in public form (import-only or
  CBI). *Inference:* Consistent with no US citral production.

## Recipe
1. Download the CSV zip into `cache/` (never committed: it's bulk third-party data; we publish derived claims).
2. Filter `CHEMICAL ID` on the chain's CAS numbers; keep `ACTIVITY in (Manufacture, Both)`.
3. Emit per site: `candidate_site` (name, city, state, lat/lon with `geo_precision: exact` from the record),
   `claim` `exists` and, where public, a `capacity` claim with `capacity_basis: production`, `unit_raw: lb/a`,
   `as_of: 2023-12-31`. Evidence: the dataset URL + the row as the quote (`<company> | <city> | <CAS> | <PV>`),
   `quote_check: manual` (a CSV row, checked by the script itself), source_type `regulator`.
4. Build as a script job (⚙, like J09), not an agent.
