## Job: ownership chain (J07)

Find who owns **{{company_name}}** (company id `{{company_id}}`, {{hq_country}}), up to the ultimate parent,
with dates. Search in these languages: {{languages}}.

For each link: a `candidate_company` line for the parent and a claim `field: "parent"`, `subject_ref:
{"company": "{{company_id}}"}` (or `{"candidate_company": <line>}` for a higher link), `value` = the parent's
name as written, `as_of` = the date the source states, and `valid_from` / `valid_to` when the source gives
them. If the source gives a percentage, add a claim `field: "share_pct"` with the number. Prefer annual
reports, exchange filings and company registers to press. A listed company with no parent: `not_found`
with the note "no parent: listed / independent" and the source you checked.
