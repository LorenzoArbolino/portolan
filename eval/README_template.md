# Gold set: measuring the agents

We don't trust extraction agents; we score them. `gold.jsonl` holds hand-checked
items: one document, one unit, one field, and the right answer, or `not_found` when the honest answer is
that the document doesn't say (traps: a company total, an increment, a feed rate, a crane's lifting capacity).
Every gold quote is verified against its source by `quote_check` (`uv run python eval/run_gold.py check`).

**Gold v0:** 30 items: 7 easy, 12 hard (scanned Indian EC with OCR, EIA tables in MT/Month, German thousands
separators, Chinese pronoun resolution), 11 traps; 8 non-English (zh, de, ja).

## Scores (job type `doc_claims`: one document → claims)

| agent:model | job | items | precision | recall | not_found honesty | quote pass | ok easy·hard·trap | date |
|---|---|---|---|---|---|---|---|---|
{{rows}}

- **precision**: claims on the asked field that match the gold value (capacity ±1% after unit normalisation;
  status after vocabulary normalisation). Any claim on a trap counts as wrong.
- **recall**: answerable items with at least one matching claim.
- **not_found honesty**: traps with no claim on the asked field.
- **quote pass**: cited quotes found in the document by `quote_check` (≥ 0.92 similarity, numbers exact).
- Threshold to use a candidate for a job type: precision ≥ 0.95 and not_found honesty ≥ 0.9.

## Read these scores with care

- Five items were adjudicated after a pilot run (g13, g15, g21, g24, g25), where the pilot showed the gold had
  missed a correct answer or was ambiguous about the molecule name. Each change is written in the item's `note`.
  This makes the scores of the pilot model somewhat optimistic.
- The gold set was drafted with the help of a model from the same family as the candidates scored here, so they
  may share blind spots. Every item was checked against its source document, and every quote is verified by code.
- 30 items is small: one miss moves precision or recall by 3–5 points.
- Pipeline fixes found by the gold run (layout text for PDF tables, partial dates such as `2026-02`, the
  unit-period rule in the job preamble) apply to every job, not only to the gold set.

Re-run: `uv run python eval/run_gold.py run --agent claude_code:sonnet`, then `… report`. Scored by code, no
LLM judge. Documents are fetched by PortolanBot and kept only in the local cache (never committed).
