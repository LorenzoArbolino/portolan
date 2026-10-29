## Job: market overview (J15)

Build the producer league table for **{{molecule_name}}** (CAS {{cas}}, id `{{molecule_id}}`): who makes it,
how much each can make, and the world total. Search in: {{languages}}. Names: {{search_names}}.

Producers already known (with what we have; confirm, update or add to them):
{{known}}

What to emit, each with a verbatim quote:
- **World figures:** `field: "world_capacity"` (and `"world_demand"` if stated) with `subject_ref:
  {"molecule": "{{molecule_id}}"}`, `unit_raw` as printed, `as_of` the source's date.
- **Each producer** you find stated: a `candidate_company`; a `candidate_site` if the source names the plant's
  town; then `capacity` (with `unit_raw`, `capacity_basis`), `status` and `start_year` as stated, with
  `subject_ref: {"candidate_site": <line>, "molecule": "{{molecule_id}}"}`, or `{"candidate_company": <line>,
  "molecule": "{{molecule_id}}"}` when no plant is named.
- A market share stated as a percentage is not a capacity; skip it unless the source also gives tonnes.

Best sources: free summaries of market reports (they often list producers with capacities), trade press
(ICIS, Chemical Week, C&EN, 化工网, 中国化工报, 化学工業日報), company annual reports and investor slides,
Chinese industry analyses (智研咨询, 华经产业研究院, 百川盈孚, 卓创 summaries), IPO prospectuses.
