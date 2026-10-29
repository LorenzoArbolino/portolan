## Job: unit claims (J04)

Find sourced facts about **one production unit**: {{molecule_name}} (CAS {{cas}}, id `{{molecule_id}}`) made at
**{{site_name}}**, {{locality}}, {{country}} (unit id `{{unit_id}}`), operated by {{operator_name}}.
Search in these languages: {{languages}}.

Look for, with a verbatim quote each:
- `capacity` (with `unit_raw` and `capacity_basis`; several values over time are welcome, each with its own
  `as_of`);
- `status` (operating, idle, closed, under construction…) and when;
- `start_year` and, if closed, `end_year`;
- `route` (the process or feedstock, e.g. "from isoprenol", "from pinene"), only if stated.

Use `subject_ref: {"unit": "{{unit_id}}"}` for every claim. Emit `not_found` for each field you searched for
and couldn't source. Known so far (do not repeat without a new source): {{known}}.

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
