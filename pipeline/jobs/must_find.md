## Job: must-find (company × molecules)

Portolan's readers are vitamin and aroma-chemical buyers. They will open the map at plants they know, so the
plants of **{{company}}** (also written: {{aliases}}) must be right. Places to look: {{places}}.
Search in these languages: {{languages}}.

For each molecule below, find out, with a verbatim quote each, **whether {{company}} makes it, where (which
site), and its current status and capacity**:

{{targets}}

What is already on the map for this company (do not repeat a fact without a newer or better source):
{{known}}

How to report:
- A plant already on the map: use its unit id, `subject_ref: {"unit": "<unit id>"}`, for `status`,
  `capacity`, `start_year`, `end_year`.
- A plant not yet on the map: one `candidate_company` (or reuse the company by `{"company": "<co id>"}` when
  given above), one `candidate_site` per physical location, an `exists` claim with
  `subject_ref: {"candidate_site": <line>, "molecule": "<mol id>"}`, then `status`/`capacity` on the same
  `subject_ref`.
- Status: prefer the newest dated statement (an annual report's production table, an EIA acceptance, a
  start-up or shutdown notice). "Operating" needs a source that says it runs or produced in a stated year.
- Capacity: nameplate or permitted (environmental clearance), with its unit as printed. Group-level totals
  that don't say which plant are reported against the company (`{"company": ...}`) only if the quote names
  the molecule; never split them across plants.
- A molecule the company doesn't make, or whose site can't be found: emit `not_found` whose `query` starts
  with the molecule id, e.g. `"mol:127-47-9: vitamin A acetate at Wanhua"`, and list every search and URL
  you tried. That is a useful result: it lets the map say "searched, not found".

Where to look first (primary documents beat press; market-report pages are leads only):
- **China:** the company's annual report and prospectus on cninfo.com.cn (主要产品, 产能, 吨/年, 产量);
  environmental impact reports and acceptance notices (环境影响报告书, 环评公示, 竣工环境保护验收) from the
  provincial or city ecology bureau; exchange announcements (公告) on new projects (项目, 投产, 试生产).
- **India:** Parivesh environmental clearances (product tables, MTPM), BSE/NSE annual reports, SEBI
  DRHP/RHP ("installed capacity").
- **EU and Switzerland:** permits (Genehmigung, BImSchG, arrêté préfectoral, ICPE), Industrial Emissions
  Portal, company annual reports and press releases, EU trade-defence regulations.
- **Japan:** EDINET 有価証券報告書 (生産能力), company news releases.

Be thorough before you give up: run at least 8 distinct searches (company name in the local language and in
English, the site's town, the product's local name, "capacity"/"产能"/"生産能力"/"Kapazität"), and open the
company's own investor and press pages, permits, and trade-press articles (CHEManager, ICIS news, Chemical &
Engineering News, Nikkei, Economic Times, 中国化工报, 新浪财经 company announcements). A `not_found` must list
what you tried.

How products are named in filings: synthetic vitamin E (维生素E, VE, VE oil, "50% powder") is sold as
dl-alpha-tocopheryl acetate, so report it under `mol:7695-91-2`; feed and food vitamin A (维生素A, VA, "50万IU",
"vitamin A 1000") is vitamin A acetate, so report it under `mol:127-47-9`. Keep the basis exactly as printed in
`unit_raw` or the quote (e.g. "吨/年（以50%粉计）"); code converts it. A project line in a construction-in-progress
table ("年产 9800 吨维生素 A … 项目") is a `capacity` with `capacity_basis: design` and a `status` of
`under_construction` unless the document says it is finished. Natural vitamin E is not the acetate: skip it.
