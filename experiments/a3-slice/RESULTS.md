# A3 slice evaluation results (Task 20)

Pilot results on synthetic data. Every rate is numerator/denominator.

## Pass criteria (stated before running)

Written and committed before any dev or test model call for this evaluation. Spec 9.1 and
9.2 are copied word for word below, followed by the operational rules the code applies.

#### 9.1 Extraction F1

- **Data:** 15 digital CVs and 15 simulated photos, all from **only 5 underlying profiles** (stated in the results, as you asked).
- **[my call] Split:** profile 01 (3 CVs and 3 photos) is the dev split, used for prompt fixes. Profiles 02 to 05 (12 CVs and 12 photos) are the test split, run once for the reported numbers.
- **[my call] Scoring:**
  - Predicted facts are matched to ground-truth facts within the same CV by kind plus fuzzy title or organisation match, one-to-one.
  - Field-level precision, recall and F1 over: kind, title/role, organisation, start, end, skills (each skill counts as one field), and metrics (value, unit and direction as one field).
  - Reported per extraction path (pdf_text, vision) and per template.
- **Intervals:** 95% bootstrap resampling whole underlying profiles. With 4 test profiles the interval is wide, and the results say so.
- **Pass criteria (from validation experiment 1, stated before running):** F1 ≥ 0.95 on digital PDFs and ≥ 0.90 on photos. A pass here doesn't establish the phase 0 result: the CVs are synthetic, the photos are simulated and there are only 4 test profiles.

#### 9.2 Claim grounding (false accepts)

- **[my call] Claim set:** built from enriched ground-truth facts, labelled by construction:
  - **Unsupported:** mutations of supported claims across the design's adversarial categories: wrong number, wrong date, inflated ownership, inflated deployment, unsupported skill, wrong entity, fake fact ID, wrong aggregate, and paraphrased overstatement with no concrete change (left to the judge).
  - **Supported:** faithful rephrasings.
  - Mutations come from templates, so labels are reliable. I'll hand-check every claim and record any I relabel or drop.
- **[my call] Sizes and split:**
  - Test split: about 45 unsupported (5 per category) and 40 supported claims from profiles 03 to 05.
  - Dev split: about 20 unsupported and 20 supported from profiles 01 and 02, used for the judge threshold and prompt fixes.
- **Metrics:**
  - False accept rate = unsupported claims accepted ÷ all unsupported claims.
  - False reject rate = supported claims rejected ÷ all supported claims.
  - User-review rate is reported separately for each group. A review is not an acceptance, so it doesn't count as a false accept.
  - All three are reported overall and per category, with one-sided 95% Clopper-Pearson upper bounds, and broken down by which layer caught each claim.
- **Pass criteria (stated before running):** zero false accepts on the test split, and false reject rate ≤ 10%. With about 45 unsupported claims, 0 errors gives an upper bound near 6.4%, so even a pass can't show the design's 2% target. The results will say so.
- The results name the judge model actually used and state its limits (P1). If the fallback is in use, they state the same-family limitation.
- **[my call] Spare comparison (optional, only if you ask):** `gemini-3.8-flash` re-runs a few dev examples (at most 15 calls, under its 20 a day) so its output can be compared with Flash-Lite's. It is reported separately, as an observation, and never feeds a reported rate.

### Operational rules (fixed before running)

- **Extraction pass test:** the pooled field-level F1 over all test documents of a path
  (12 digital PDFs, 12 photos from profiles 02 to 05) is compared with the threshold. The
  bootstrap interval is reported but does not decide pass or fail.
- **Extraction matching:** a predicted fact matches a ground-truth fact only if the kinds
  agree and `token_set_ratio` of their titles (falling back to text) is at least 85;
  one-to-one, best score first. Title and organisation agree at `fuzz.ratio` of 90 or more
  after normalisation; dates, skills and metrics (value, unit family, direction) must be
  equal. A field that is None on both sides isn't counted. See `src/evident/eval/extraction.py`.
- **Extraction prompt:** `extraction/v2`, already chosen on the dev split (profile 01) by
  `scripts/tune_extraction_dev.py`. It is not changed in this task.
- **Grounding pass test:** pass needs 0 false accepts on the 45 unsupported test claims and
  a false reject rate (supported claims with outcome `rejected` / 40) of 10% or less. User
  review is reported separately and counts as neither.
- **Judge prompt choice (dev split only):** `judge/v1` and `judge/v2` are run as two
  separate dev runs. The winner has fewer false accepts; on a tie, fewer unsupported claims
  routed to user review instead of rejected; on a further tie, fewer false rejects. If all
  three tie, `v1` stays (no change without evidence).
- **Judge threshold:** stays at 0.8. It is not tuned in this task.
- **Claim set:** `claims_dev.jsonl` and `claims_test.jsonl`, built by
  `scripts/build_claim_sets.py` (seed 0) and hand-checked (`claims_review.md`), committed
  before any test-split call.
- **Dataset version at the time of writing:** `a3_enriched` tree
  `b8bcfa4afe49d7783da7df675851986480fb1feb`.
