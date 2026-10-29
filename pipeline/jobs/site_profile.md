## Job: site profile (J03)

Profile **one production site**: **{{site_name}}**, {{locality}}, {{country}} (site id `{{site_id}}`), operated by
{{operator_name}}. Search in these languages: {{languages}}.

Find, each with a verbatim quote:
1. **Which of these chain molecules the site makes** (not merely sells): {{chain_molecules}}.
   For each one made here: a claim `field: "exists"`, `value: "true"`, `subject_ref: {"site": "{{site_id}}",
   "molecule": "<mol id>"}`. If the same source states capacity, status or start year, add those claims too.
2. **Coordinates, only if a document states them** (EIA reports, permits, environmental disclosures, company
   pages often print latitude/longitude): a claim `field: "lat_lon"`, `subject_ref: {"site": "{{site_id}}"}`,
   `value` exactly as printed (e.g. `北纬 37°0′52″ 东经 119°7′47″` or `49.4875, 8.4280`). Never compute or look up
   coordinates on a map: if no document prints them, emit `not_found`.
3. **The operator**, if the documents name a different or more precise legal entity than {{operator_name}}: a
   `candidate_company` line and a claim `field: "operator"` on the site with the company's name as `value`.

Already known (don't repeat without a new source): {{known}}.
Emit `not_found` for anything you searched for and couldn't source.
