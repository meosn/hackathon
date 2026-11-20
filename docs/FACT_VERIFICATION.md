# Which claims reach the listener

Each substantive transcript line maps to one claim and at least one source article. A claim has an exact excerpt, half-open Unicode character offsets, a source URL and a stored article. The offsets address the normalized, visible article text returned by `GET /api/v1/articles/{id}`. They do not refer to byte positions in original HTML. For a synthetic record, inspect the stored article in the application; its reserved example-domain URL identifies the fictional source.

## Evidence gate

The extractor selects complete, short assertion sentences containing a recognized reporting or action verb. It skips questions, coordinated propositions, instructions, advice signals and unsupported fragments. This favors coverage that can be verified reproducibly. The current vocabulary covers selected English, German and Dutch constructions. Long or compound factual sentences may be omitted.

1. Resolve the supplied claim ID in the database. The default publishing path accepts only a supported claim.
2. Compare the proposed narration with the fact using an ordered token sequence. A small, explicit equivalence vocabulary allows expressions such as “increased” and “rose” or “4 percent” and “4%”. The gate preserves digits, signs, decimal marks, units, dates, direction, actors, order and negation. Other paraphrases may be refused even when a human editor would accept them.
3. Resolve every supplied article ID to a citation for that same fact. For each citation, require an original URL, valid offsets, and an exact match between the stored excerpt and the current normalized text slice.
4. Recheck the narrated words against that excerpt. One good citation cannot compensate for an unrelated article in the same citation list.
5. The briefing worker repeats checks around synthesis. Fixed introductions, transitions, closings and conflict notices belong to an allowlist. Citation-bearing lines are verified again if the model changes any words.

For example, “Revenue rose by 4%.” can cite “Revenue increased by 4 percent.” Changing 4 to 40, changing percent to percentage points, or exchanging the reporting and acquiring organizations fails closed.

## Interpreting verification

| Outcome | Meaning |
| --- | --- |
| supported | The source text supports the statement as worded. A single report is sufficient for source alignment. |
| conflicting | Different publishers supply incompatible numerical values for the same matched claim context. |
| insufficient_evidence | The submitted assertion lacks a sufficient source or matching span and is ineligible for publication. |
| rejected | The proposed wording fails a gate, such as a numerical, attribution or unit mismatch. |

The data model and API vocabulary support all four outcomes. The extractive importer persists supported and conflicting facts. Ineligible candidate outputs are rejected before insertion or block briefing generation. A supported claim can describe what a publisher reported. This label alone does not establish real-world truth, source independence or validation by an official release.

## Disagreements

A comparison signature retains the entire normalized sentence except for one identified numeric measure. The metric, reporting context, units, time references and language stay in the signature. Numerically equivalent spellings share a value. Distinct values from distinct publishers create a disagreement group; each member becomes conflicting. Both source excerpts remain available. Conflicting values are omitted from ordinary factual narration. The story detail and source-comparison API retain both accounts.

In the bundled synthetic Sunvale story, two inputs say the same pilot has “40 megawatts” and “42 megawatts”. Each is shown with its publisher and exact excerpt. The system makes no estimate of the correct capacity. Cross-language, multi-number and substantially reworded disagreements can remain undetected by this conservative rule. Official releases can be imported under their actual publisher with their real URL for inspection.

## Repeatable checks

```bash
cd backend
python -m pytest -q tests/test_news_verification.py tests/test_news_pipeline.py
```

The tests cover actor reversal, negation, percentages, currency, dates, units, missing or unrelated citations, corrupted offsets, acceptable paraphrases, numerical disagreements, multilingual clustering, exact and near duplicates, story corrections and pagination.
