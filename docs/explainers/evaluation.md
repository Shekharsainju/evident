# Evaluation harness (A3 slice)

## What it does

`scripts/run_eval.py` measures two things on the synthetic A3 dataset and writes the numbers to `experiments/a3-slice/RESULTS.md`:

- **Extraction F1 (spec 9.1).** Each CV (three templates, as a digital PDF and as a simulated phone photo) goes through the same extraction request the pipeline makes. The drafts become facts through the pipeline's own conversion, and `src/evident/eval/extraction.py` matches them to ground truth and counts fields: kind, title, organisation, start, end, each skill and each metric. Profile 01 is the dev split, profiles 02 to 05 the test split.
- **Claim grounding (spec 9.2).** `src/evident/eval/grounding.py` builds labelled claims from templates: supported claims, and unsupported ones made by one known mutation each (wrong number, wrong date, inflated ownership or deployment, an unsupported skill, a wrong entity, a fake fact ID, a wrong count, an overstated paraphrase). Every claim goes through `validate_claim`, Layer 1 then the judge, and the outcome is counted against its label.

`src/evident/eval/runner.py` runs a split, writes a run record to `experiments/a3-slice/runs/`, and with `--write-results` (test split only) `results.py` rewrites only the "Test split results" section of `RESULTS.md`.

## Why it's built this way

- **Dev and test are separate, and test runs once** (invariants section 5). The judge prompt was chosen on the dev claims with the rule fixed in the plan (fewer false accepts, then fewer inflated claims sent to review, then fewer false rejects). The test split was then run once with nothing changed.
- **Criteria before numbers.** The pass criteria, the claim sets and the hand-check record were committed before any model call. The results writer keeps everything above the test heading as written, so the dev tuning log cannot be rewritten by a run.
- **The pipeline's own code is measured.** Extraction uses the pipeline's request and conversion functions, and grounding uses `validate_claim` with the same outcome table, so the numbers describe the code that ships.
- **A pre-flight before any call.** The runner builds every Gemini request without sending it, checks the cache, and stops if the uncached calls don't fit in today's free-tier quota.
- **Intervals match the data.** Rates use a one-sided 95% Clopper-Pearson upper bound. F1 uses a 95% bootstrap that resamples whole underlying profiles, because the three templates of one profile are not independent.
- **A user review is not an acceptance.** Only a `passed` outcome on an unsupported claim is a false accept.

## How the model is used

- Extraction: `gemini-3.5-flash-lite`, prompt `extraction/v2`, 24 calls for the test split (12 PDF, 12 photo).
- Judge: `qwen3:4b-instruct-2507-q4_K_M` (digest `0edcdef34593`) through Ollama, prompt `judge/v2`, threshold 0.80, one call per claim, no quota.
- Replies are cached on disk, so a dev re-run after a code change costs nothing for unchanged requests. Run records hold counts, IDs, versions and timings only, never CV text.

## Limits

- Five synthetic profiles, four in the extraction test split, so every interval is wide. The photos are simulated and easier than real phone photos.
- Claims come from templates and were hand-checked by the builder, not the owner. Real planner output is more varied.
- 45 unsupported test claims: 0 false accepts gives an upper bound of 6.4%, which cannot show the design's 2% target.
- The judge, not Layer 1, causes the false rejects on test. A 4B local judge with self-reported confidence is the weakest part of the slice.

## Example

The locked test run (2026-10-31), from `RESULTS.md`:

| Criterion | Result | Verdict |
|---|---|---|
| Extraction F1, digital PDF, at least 0.95 | 0.930 (tp 643, fp 41, fn 56), interval 0.926 to 0.933 | Fail |
| Extraction F1, photo, at least 0.90 | 0.902 (tp 619, fp 54, fn 80), interval 0.876 to 0.928 | Pass |
| Zero false accepts | 0/45, upper bound 6.4% | Pass |
| False reject rate at most 10% | 13/40 (32.5%), upper bound 46.6% | Fail |

All 13 false rejects were rejected by the judge alone: all 6 subject claims, 2 of 3 four-subject aggregates, 2 of 3 role claims, 2 of 6 project scope claims and 1 of 6 project date claims.
