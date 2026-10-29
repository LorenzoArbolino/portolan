# Indian environmental clearances (ECs) at scale

**Result: proven for documents companies and state boards publish; the national portal is blocked by
TLS/network issues** (2026-10-26). Triage script: see Recipe. OCR fallback added to `quote_check`
(tesseract, only for pages with no text layer, flagged `ocr`).

## Documents triaged (10 reachable, 4 with scanned pages)

| # | Document | Pages | Text layer | MT/Month table | Chain molecules |
|---|---|---|---|---|---|
| 1 | Privi Speciality Chemicals, EC SEIAA Gujarat 22 Nov 2022 (Jhagadia) | 15 | **scan with OCR layer** (OCR errors: "Existino", "Grouo") | yes | turpentine (215 MT/Month), menthol group, pinane |
| 2 | Privi, EC compliance Jul–Dec 2024 (Jhagadia) | 215 | **pp. 1–4 scanned, no text** (OCRed in this test) | yes | menthol, pinene, turpentine |
| 3 | Privi Unit II, compliance Dec 2023–May 2024 (Mahad) | 116 | text | yes (also MT/A) | pinenes, myrcene, citral |
| 4 | Privi Organics, EIA executive summary, MPCB Apr 2020 (Mahad) | 15 | text | yes (MTPM) | myrcene 400, citral 30, α-pinene 666.66 → 1612.65, β-pinene |
| 5 | Himalaya Terpenes, EIA executive summary, MPCB Feb 2026 (Jamghar, Palghar) | 38 | text | yes (TPA) | dihydromyrcenol 1200 TPA, camphor, terpineol |
| 6 | Atul Ltd, EC 2022 (API intermediates) | 10 | text, **p. 10 scanned** (blank after OCR: a signature page) | yes | none |
| 7 | Anar Chemicals, EC compliance Apr–Sep 2024 | 180 | **pp. 1–2 scanned** (OCRed: cover letter, readable) | yes | none |
| 8 | Grasim Vilayat, EC compliance Oct 2024–Mar 2025 | 72 | text | no | none |
| 9 | Gulbrandsen Chemicals, EC compliance Apr–Sep 2023 | 31 | text | no | none |
| 10 | GACL, EC compliance Oct 2024–Mar 2025 | 48 | text | no | none |

Not reachable: environmentclearance.nic.in (TLS: the server doesn't send its intermediate certificate, so
verification fails; we never disable verification), parivesh.nic.in (connection reset), one Aarti Industries
PDF (404), Galaxy Surfactants (403).

## Findings
- Product-wise capacity per plant is there: 5 of 10 documents carry a product table in MT/Month (or TPA)
  with existing / proposed / total columns, and 3 of them name chain molecules. Company websites post EC
  compliance reports because the EC requires it, so they're a stable source.
- Extraction works: the gold set's 6 Indian items (ECs and EIA summaries) were all answered correctly by
  `claude_code:sonnet` from the layout text (`eval/README.md`).
- `pdftotext -layout` is needed for these tables. Plain reading order separates product names from
  numbers, and a careful agent then refuses (correctly) to pair them.
- OCR (tesseract 5.3) reads scanned prose well (cover letters, EC numbers, dates) but scrambles scanned
  tables: columns interleave and stamps add noise. *Inference:* Scanned tables are "hard documents":
  route them to a vision-capable model with the rendered page image (`pdftoppm -r 300`), as done by hand for
  the Privi EC in this test, and keep `quote_check` on the OCR text with the `ocr` flag (grade C until a
  human or a second extraction agrees).
- Columns mean different things: "Existing", "Proposed", "Total"; group rows ("either or all total not
  to exceed 300") cap several products together. A group cap is not a unit capacity: emit `not_found` for
  the product, or a claim on the group with a note. Negative "proposed" values (e.g. -200) mean a product is
  being dropped.
- *Inference:* The national portal (environmentclearance.nic.in / PARIVESH) would multiply coverage. Fix the TLS
  chain by adding the missing intermediate certificate to a project CA bundle , and test PARIVESH from
  another network.

## Recipe
1. Find documents: search `"<product>" "MT/Month" environmental clearance` + company EC-compliance pages; state
   board EIA summaries (MPCB `public_hearing/exe_summary/…`).
2. Fetch with PortolanBot (`pipeline/fetch.py`), triage: pages, text chars per page (scan if < 40), MT/Month
   present, chain molecules present.
3. Give agents `document.txt` from `extract_text(..., for_agent=True)` (layout text, OCR for pages without text).
4. Scanned tables: render the page and have a vision model read it; record `quote_check` from the OCR text.
5. Claims: `capacity_basis: permitted` for EC totals, `design` for EIA proposals; as_of = EC date.
