# Chinese environmental-impact (EIA) documents → 产能

**Result: partially proven** (2026-10-26): 3 company/government environmental documents with
chain-molecule capacities or dates found and quote-checked (target was 5). The route works, and the
documents are richer than expected; finding them is the bottleneck.

| # | Document | Publisher | What it gives | quote_check |
|---|---|---|---|---|
| 1 | 山东新和成药业有限公司 2020 年第二季度环境信息公开 | NHU (cnhu.com), mandated disclosure | Weifang Binhai site: "主要产品：15000 t/a 柠檬醛、5000t/a 芳樟醇、3000t/a 香茅醇、3000t/a 香叶醇…"; exact coordinates (E119°7′47″, N37°0′52″) | pass |
| 2 | 上虞新和成生物化工有限公司 年产7800吨营养品、中间体技术改造及绿色深加工项目 环评公告 | NHU (cnhu.com) | Shangyu: new capacity incl. "3600 吨β-紫罗兰酮" (β-ionone) | pass |
| 3 | 万华化学集团股份有限公司柠檬醛ISPO单元技改项目 环境影响报告书 (full report, 2025) | Yantai Ecology & Environment Bureau | Wanhua citral project: construction start 2022-02, completion and commissioning 2024-09; the 2021 approval (烟环审〔2021〕19号) | pass |
| 4 | 山东新和成精化科技有限公司 年产14000吨营养品及4800吨特种化学品项目 第三次信息公示 | NHU (cnhu.com) | product names **masked** ("2000 吨β-***") | n/a |

A planted wrong number ("25000 t/a 柠檬醛") fails the quote check, as it should.

## Findings
- Chinese companies post their own EIA notices and mandated quarterly environmental disclosures
  (环境信息公开) on their websites; these state **products and annual scale per site** in t/a, with coordinates.
  This filled a gap from the J01 run (NHU makes citral, site unknown): Shandong NHU Pharmaceutical, Weifang,
  15,000 t/a citral (2020).
- Municipal bureaus publish full EIA reports for acceptance notices (受理公示). The Yantai copy of Wanhua's
  report is ~860k characters, but its unit list and material-balance tables are **blank in the published copy**;
  the notice says published reports exclude commercial secrets. Dates and approvals survive; capacities may not.
- Some notices **mask product names** (β-***): never fill them in by inference.
- Pages declared `gb2312` contain GBK-only bytes; `quote_check` now decodes the declared charset first
  (with a tolerance for rare bad bytes) instead of guessing (fixed in this step).
- Personal data appears in these documents (environmental contact person, phone, email). Quotes must be
  cut to the capacity line; `people_leak` blocks names, phones and emails outside company-document quotes.
- *Inference:* Search engines index these PDFs poorly. Better routes: company "环境信息公开" pages
  (one per site, quarterly), municipal 受理公示 lists, and the national 全国排污许可证管理信息平台 (permit
  records list products and capacities; untested).

## Recipe
1. Per producer: company site → 环境信息公开 / 环评公示 → PDFs. Per city: 生态环境局 → 环评受理/审批公示.
2. `extract_text` (charset-aware HTML, layout PDF) → `doc_claims` with `language: zh`.
3. Units: `t/a`, `吨/年`, `万吨/年` (units.yaml); bare `万吨` without a period is refused.
4. Masked names and blank tables → `not_found` with a note, never a guess.
