# Phase 1 held-out test results

Locked test split: synthetic profiles 06 to 10. Every rate is numerator/denominator. This
file holds only the pass criteria so far. Results are added after the one locked run.

## Pass criteria (stated before running)

Committed with the claim set, before any work on the judge comparison, Layer 1 fixes,
planner change or receipt rule, and before any model call on profiles 06 to 10.

| Measure | Criterion | Source |
|---|---|---|
| False accepts on test claims | 0 / all unsupported | Invariant, hard gate |
| False reject rate (supported rejected / supported) | ≤ 10% | Same as A3 and Validation plan 2 |
| Extraction F1, digital PDF | ≥ 0.95 | Validation plan 1 |
| Extraction F1, photos | ≥ 0.90 | Validation plan 1 |
| Planner Skills and Coursework claims | **[my call]** In 5 of 5 profiles the plan contains at least one Skills claim and one Coursework claim; reported with how many of those pass validation | Item 3 |
| Photo receipts verified (facts with a verified box / facts with a span) | **[my call]** ≥ 80%, and 0 wrong boxes among those verified by word positions (every one is checked by hand on a contact sheet) | Validation plan 3's threshold, used on photos |

Reported but with no pass criterion: user review rates, per-category tables, which layer
caught what, judge time per claim (p50, p90, n), Gemini calls and estimated cost.

The pass tests work as in A3: pooled F1 against the threshold, with the bootstrap interval
reported but not deciding; rates with one-sided 95% Clopper-Pearson upper bounds.

### Operational rules (as in A3, fixed before running)

- **Extraction pass test:** the pooled field-level F1 over all test documents of a path
  (digital PDFs, photos, profiles 06 to 10) is compared with the threshold. The bootstrap
  interval (resampling whole profiles) is reported but does not decide pass or fail.
- **Extraction matching:** a predicted fact matches a ground-truth fact only if the kinds
  agree and `token_set_ratio` of their titles (falling back to text) is at least 85;
  one-to-one, best score first. Title and organisation agree at `fuzz.ratio` of 90 or more
  after normalisation; dates, skills and metrics (value, unit family, direction) must be
  equal. A field that is None on both sides isn't counted. See
  `src/evident/eval/extraction.py`.
- **Grounding pass test:** pass needs 0 false accepts on all unsupported test claims and a
  false reject rate (supported claims with outcome `rejected` / supported claims) of 10% or
  less. User review is reported separately and counts as neither.
- **Intervals:** one-sided 95% Clopper-Pearson upper bounds for false accepts and false
  rejects. With 0 false accepts in 86, the upper bound is about 3.4%, so even a pass can't
  show the design's 2% target. The results will say so.
- **Judge model, threshold and planner prompt version:** chosen on dev in Tasks 10 and 11,
  recorded here before the locked run.

### Test set as committed

- **Claim file:** `experiments/p1-heldout/claims_test.jsonl`, built by
  `scripts/build_p1_claims.py` (seed 2, profiles 06 to 10) and hand-checked
  (`claims_review.md`: no relabels, no drops).
- **Counts:** 166 claims: 80 supported and 86 unsupported. Unsupported: 10 each for
  `wrong_number`, `wrong_date`, `inflated_ownership`, `unsupported_skill`, `wrong_entity`,
  `fake_id`, `wrong_aggregate`, `paraphrase_overstatement`; 6 for `inflated_deployment`
  (only 6 projects are not already in production).
- **Distinct texts:** 57 of 80 supported texts and 77 of 86 unsupported texts are distinct.
  The repeats are the same text (degree, subject and skill sentences) cited against different
  profiles' facts, so the effective sample is smaller than n.
- **Known gap:** profile 10's certification and award facts have no claims (the builder
  selects facts by kind and skips these two).
- **Claim file SHA-256:** `3d08a1be410827bde1728e1f61dce8a07022c3c6a37ed06acdfc110f0214f215`,
  over the file content with CRLF normalised to LF (the same convention as `A1_HASHES` in
  `src/evident/eval/datasets.py`).
- **Dataset version:** `data/synthetic/heldout_p1` tree
  `b0d5fea783d914850a633fc3689edae87d720e8d` (`git rev-parse HEAD:data/synthetic/heldout_p1`
  at commit 806f238).
- **Dev data for tuning:** profiles 01 to 05 and the 125 A3 claims. `require_dev` refuses
  any profile from 06 to 10, and the test claims load only with `locked_run=True`.
