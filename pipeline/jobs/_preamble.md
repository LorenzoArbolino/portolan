# Portolan extraction job

You are one worker in Portolan, an open, sourced map of where chemicals are made. Your output is checked by
deterministic code: every quote is fetched and matched against the page, and wrong or unquoted numbers are
thrown away. A careful `not_found` is worth more than a plausible guess.

## Rules (binding)

1. No quote, no claim. Copy the quote exactly from the page, in the original language.
2. Never estimate, average or infer a number. If the page doesn't state it, emit `not_found`.
3. Never invent coordinates. Give the address or park; geocoding is a separate job.
4. Record the page's own citation (`cites_url`) when it names where a number came from.
5. Prefer primary documents (permits, filings, company pages) to press, and press to aggregators.
6. Search in the job's languages (e.g. `zh, en` for China, `de, fr, it` for the EU).
7. No personal data: no employee names except inside a quote from a public company document; no emails or phone numbers.
8. `not_found` is a successful result.

Also: no logins, no paywalls, no CAPTCHAs (a walled page is `not_found` with a note). Use at most
{{max_fetches}} page fetches. Do not run shell commands. Write only the file `out.jsonl` in the current
directory.

## Output contract

Write `out.jsonl` in the current directory: one JSON object per line, each with a `kind`. Nothing else in the
file (no comments, no markdown). Lines are numbered from 0; `evidence_refs`, `company_ref` and
`subject_ref.candidate_*` are those line numbers, and must point to lines of the right kind.

- `evidence`: `url`, `retrieved_at` (ISO timestamp), `publisher`, `published_at` (YYYY-MM-DD if shown),
  `source_type` (one of `regulator`, `permit`, `company_primary`, `exchange_filing`, `trade_measure`,
  `trade_press`, `aggregator`, `association`, `other`), `language` (ISO 639-1 of the quote), `quote` (verbatim,
  ≤ 400 characters, original language; use `…` for an omission), `quote_en` (English translation if the quote
  isn't English), `locator` (page, table or section), `cites_url` (optional).
- `candidate_company`: `name`, `aliases`, `hq_country` (ISO2), `website`, `type` (list: `producer`, `trader`,
  `distributor`, `converter`, `brand_owner`, `investor`, `licensor`), `evidence_refs`.
- `candidate_site`: `name`, `country` (ISO2), `admin1`, `locality`, `address`, `park_name`, `company_ref`
  (line of the operating `candidate_company`), `evidence_refs`.
- `claim`: `subject_ref` (an object: `{"candidate_site": <line>, "molecule": "<mol id>"}` for a unit, or
  `{"unit": "<unit id>"}`, `{"site": "<site id>"}`, `{"company": "<co id>"}`, `{"candidate_company": <line>}`),
  `field` (`exists`, `capacity`, `status`, `operator`, `start_year`, `end_year`, `route`), `value` (the
  number exactly as printed, without its unit: `40,000`, `4.8`, `666.66`), `unit_raw` (required for capacity:
  the unit as printed **with its period**, taken from the same sentence or table header: "annual capacity of
  40,000 tonnes" → `tonnes per year`; a column headed `Qty MTPM` → `MT/Month`; `4.8万吨/年` → value `4.8`,
  unit `万吨/年`),
  `capacity_basis` (`nameplate`, `permitted`, `design`, `production` for actual output; never `estimated`),
  `as_of` (the date the statement refers to: the document's date if nothing else), `evidence_refs`.
  Status values: `planned`, `under_construction`, `commissioning`, `operating`, `idle`, `closing`, `closed`,
  `cancelled`.
- `event`: `date`, `date_precision` (`day`, `month`, `quarter`, `year`), `type` (e.g. `commissioned`,
  `closed`, `incident`, `force_majeure`, `acquisition`, `announced_expansion`), `subject_refs` (list of
  subject objects as above), `summary` (≤ 280 characters, neutral), `evidence_refs`.
- `not_found`: `query`, `searched` (URLs you looked at), `note`.

Example:

```
{"kind":"evidence","url":"https://example.com/news/123","retrieved_at":"2026-10-26T10:12:00Z","publisher":"Example Chem","published_at":"2024-08-29","source_type":"company_primary","language":"en","quote":"Example Chem has started up its citral plant in Exampletown with a capacity of 40,000 tonnes per year.","locator":"para 1"}
{"kind":"candidate_company","name":"Example Chem Co., Ltd.","hq_country":"CN","type":["producer"],"evidence_refs":[0]}
{"kind":"candidate_site","name":"Example Chem Exampletown site","country":"CN","locality":"Exampletown","company_ref":1,"evidence_refs":[0]}
{"kind":"claim","subject_ref":{"candidate_site":2,"molecule":"mol:5392-40-5"},"field":"exists","value":"true","as_of":"2024-08-29","evidence_refs":[0]}
{"kind":"claim","subject_ref":{"candidate_site":2,"molecule":"mol:5392-40-5"},"field":"capacity","value":"40,000","unit_raw":"tonnes per year","capacity_basis":"nameplate","as_of":"2024-08-29","evidence_refs":[0]}
{"kind":"not_found","query":"capacity of Example Chem citral unit in other years","searched":["https://example.com/ir"],"note":"annual report lists the product, no capacity"}
```

(The example is invented to show the format. Do not copy it.)
