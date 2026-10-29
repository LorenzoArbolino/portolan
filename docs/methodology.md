# Methodology

How Portolan turns public documents into the values on the map, and the rules that keep those values honest.

## Pipeline

```
 chain pack ──► plan ──► research jobs ──► collect ──────────► data/ ──► build ──► map
 (molecules,     │       (LLM agents       (deterministic       │        (resolve,
  routes,        │        search and        validators:         │         metrics,
  regions,       │        read; propose     schema, units,      │         bundle)
  seed sources)  │        claims with       quote_check,        │
                 │        quotes)           geo, dedupe,        ▼
                 │                          sanity, licence,  review queue
                 └── must-find checklist     people_leak)      (uncertain items)
```

1. **Plan.** A chain pack (`chains/*.yaml`) lists the molecules, their production routes, the regions to cover and
   the source types to try. The planner turns it into jobs: find producers, profile a site, read a filing, read
   an environmental permit, trace ownership, and so on.
2. **Research.** Agents search the web and read documents, then write *proposals*: evidence (URL, publisher, date,
   verbatim quote) and the claims it supports. They never write canonical data, and `not_found` is a valid
   answer. Agent CLIs and models are configured in one file (`pipeline/models.yaml`).
3. **Collect.** Deterministic validators check every proposal. The quote must appear in the document (fuzzy token
   match ≥ 0.92, with numbers matching exactly), units must normalise to tonnes per year, coordinates must fall
   in the stated country, and statuses must follow possible transitions. A licence check blocks domains whose
   terms forbid redistribution, and a personal-data scan runs too. Validated proposals are written to `data/`;
   anything uncertain goes to a review queue for a human decision.
4. **Build.** Claims are resolved into the value shown for each field (rules below). Metrics are computed from
   resolved values and record the claims they used. The result is a DuckDB database and a JSON bundle per chain
   for the web map.

## Rules

1. **No quote, no number.** A capacity, status, date or owner needs a verbatim quote from a reachable URL. The one
   exception is a marked estimate (grade D). It comes from a dedicated estimate step, states its method, its
   sourced inputs and a low–high range, never overrides a sourced value, and is shown only when the reader
   turns estimates on.
2. **Agents propose; code decides.** Only the collector and the resolver write canonical data.
3. **No personal data.** No employee names (except inside a quote from a public company document), emails or
   phone numbers. `portolan leak-check` runs on every build.
4. **Cite, don't copy.** The repository stores URLs, short quotes (≤ 400 characters) and archive links, never
   copies of source documents.
5. **No estimate method without a backtest.** A method is enabled for a molecule only if a leave-one-out test on
   that molecule's sourced values passes: n ≥ 5, with at least 70% of held-out estimates within 0.5–2× of the
   true value. Results are in [`eval/estimates.md`](../eval/estimates.md).
6. **Never sum across molecules.** Totals and shares are per molecule. Adding capacities along a chain counts the
   same carbon several times.
7. **A contradiction is a bug.** Acquisitions move plants to the buyer from the deal date. Duplicate events are
   merged. Exports above known capacity are flagged. `portolan audit` lists every case.
8. **Effort follows importance.** Each chain carries a weighted must-find checklist of the producers a buyer
   would expect to see. Breadth (new molecules, new chains) waits until the checklist is resolved.
9. **Be a good crawler.** Respect robots.txt, identify as `PortolanBot`, rate-limit per domain. No logins, no
   paywall circumvention, no CAPTCHAs.

## Grades

| Grade | Rule |
|---|---|
| **A** | Primary source (regulator, permit, company document, exchange filing, legal act) and the quote check passes |
| **B** | Named trade press or industry association with a passing quote check, or two independent C sources that agree |
| **C** | A single aggregator page, or a primary source whose quote can't be checked automatically (e.g. a scanned table) |
| **D** | Estimate (see rule 1). Hidden unless estimates are on |

Two sources count as independent only if neither cites the other.

## Resolution

For each subject and field:

1. Drop rejected and superseded claims.
2. Take the claims with the latest `as_of` date. Among those, take the highest grade.
3. If claims at the top grade disagree beyond tolerance (capacity ±10%, or a different status), the field is
   **contested**. The map shows the range and every source.
4. Capacity bases rank `nameplate > design > permitted > estimated`. Reported production is shown as output,
   never as capacity.
5. A capacity stated on a product basis (e.g. vitamin E as 50% feed powder) is converted to the molecule with a
   visible flag. A figure whose basis is not stated is shown as "(basis?)" and kept out of totals and shares.

## Display

- The map opens on sourced values. Unknown capacity is drawn as a hollow ring, and a unit with no current status
  shows "status unconfirmed (last seen <date>)".
- Shares, and "X leads", are shown only when at least two thirds of a molecule's existing plants publish a
  capacity.
- Trade: a customs code shared by several molecules is shown once, under all their names. Codes that cover a
  wider family are left out and named in a footnote.
- Locations: published coordinates where a permit or register gives them, otherwise the town centre.

## Model evaluation

Extraction models are scored before use on a hand-checked gold set of 30 items, including traps where the right
answer is `not_found` and items in Chinese, German and Japanese. Scoring is done by code, with no LLM judge.
Only models that pass (precision ≥ 0.95 and honesty on traps ≥ 0.9) have their claims auto-accepted. Everything
else goes to review. See [`eval/README.md`](../eval/README.md).

## Known limits

- Plant-level capacity is published for about a third of units. Many producers, especially in China and India,
  don't disclose it per plant, and several Chinese filing portals block automated access.
- Status for some Chinese and Indian units rests on documents more than two years old. Their age is shown on the
  map.
- Customs codes rarely isolate a single specialty molecule. Trade is shown only where one does.

Source-specific findings are in [`docs/sources/`](sources/).
