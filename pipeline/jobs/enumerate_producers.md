## Job: enumerate producers (J01)

Find **every company and site that produces {{molecule_name}}** (CAS {{cas}}, id `{{molecule_id}}`) in
**{{region_name}}**. Search in these languages: {{languages}}.

Names to search for: {{search_names}}.

- For each producer site you find: one `evidence`, one `candidate_company`, one `candidate_site`, and one
  `claim` with `field: "exists"`, `value: "true"` and `subject_ref: {"candidate_site": <line>, "molecule":
  "{{molecule_id}}"}`. The quote must show that **this site (or this company in this region) makes this
  molecule**, not merely sells or distributes it.
- If the same source also states capacity, status or start year for that site and molecule, add those claims
  (same `subject_ref`). Don't search further for them; a separate job does that.
- If a source shows that a company makes the molecule but you can't find where, emit the
  `candidate_company` and an `exists` claim with `subject_ref: {"candidate_company": <line>, "molecule":
  "{{molecule_id}}"}`, plus a `not_found` for the site. Don't guess the site.
- Traders, distributors and catalogue sellers are not producers. Skip them unless a quote shows production.
- One site per physical location. If a company makes the molecule at two places, that's two sites.
- If you can't find any producer in the region, or a lead below can't be confirmed, emit `not_found` with the
  searches you ran.

Leads to verify or drop (unconfirmed; they need their own evidence):
{{leads}}

Where to look (most producers are found in documents, not on product pages):
- **Company filings:** annual reports and prospectuses. China: cninfo.com.cn 年度报告 / 招股说明书 (产能, 吨/年).
  India: BSE/NSE annual reports, SEBI DRHP/RHP ("installed capacity", MTPA/MTPM). Japan: EDINET
  有価証券報告書 (生産能力). Korea: DART. Brazil: CVM filings. Investor presentations count too.
- **Environmental permits:** China EIA notices (环境影响报告书, 环评公示, 验收报告: they list products,
  tonnage and often coordinates). India Parivesh environmental clearances (product tables in MTPM). EU
  Industrial Emissions Portal and national permits (Germany: Genehmigung, BImSchG). US EPA CDR and TRI.
- **Local and regional press, in the local language:** municipal or provincial news on 开工 / 投产 / 签约, Indian
  business dailies and state industrial-development corporations (MIDC, GIDC), Brazilian regional papers,
  Japanese 日経 / 化学工業日報 summaries.
- **Government and trade bodies:** investment-promotion announcements, EU trade-defence regulations (they
  name the producers investigated), industry-association member lists, award or safety-incident reports.
