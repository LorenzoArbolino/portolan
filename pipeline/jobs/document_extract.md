## Job: extract claims from one long document (J05 permit / J06 filing)

The document is **{{doc_title}}** ({{doc_kind}}), {{url}}, published by {{publisher}}. Its text has been saved
as `document.txt` in your working directory: read that file (PDF text; tables may be laid out in columns;
for very long documents only the pages that mention the chain's products or capacity are included). Cite
the URL above as the evidence `url` and copy quotes exactly from `document.txt`.

Report every **plant-level** fact the document states for these molecules: {{chain_molecules}}.
- Sites: `candidate_company` + `candidate_site` (address, park, registry or permit numbers as printed).
- Per site × molecule: `exists`, `capacity` (with `unit_raw` exactly as the column or sentence gives it, and
  `capacity_basis`: `permitted` for permit/clearance quantities, `nameplate` for installed capacity in a
  filing, `production` for actual output, `design` for a proposal), `status`, `start_year`.
- Tables with several columns (existing / proposed / total; or several years): one claim per value you
  report, each with its own `as_of` (the document date, or the fiscal year end it refers to) and a quote that
  contains the row label and the number.
- Product groups ("either or all total not to exceed …", "mint and mint derivatives"): a group total is **not**
  a molecule's capacity. Emit `not_found` for the molecule with a note, never split the total.
- Masked or blanked values (`***`, empty tables): `not_found`, never a guess.
Use only this document; don't search the web.

How products are named in filings: synthetic vitamin E (维生素E, VE, VE oil, "50% powder") is sold as
dl-alpha-tocopheryl acetate, so report it under `mol:7695-91-2`; feed and food vitamin A (维生素A, VA, "50万IU",
"vitamin A 1000") is vitamin A acetate, so report it under `mol:127-47-9`. Keep the basis exactly as printed in
`unit_raw` or the quote (e.g. "吨/年（以50%粉计）"); code converts it. A project line in a construction-in-progress
table ("年产 9800 吨维生素 A … 项目") is a `capacity` with `capacity_basis: design` and a `status` of
`under_construction` unless the document says it is finished. Natural vitamin E is not the acetate: skip it.
