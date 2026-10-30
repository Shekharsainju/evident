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

## Dev tuning log

Dev split only: extraction on profile 01 (3 PDFs, 3 photos), grounding on the 40 dev
claims (profiles 01 and 02). Run records: `runs/dev_all_judge-v1.json` and
`runs/dev_grounding_judge-v2_before-entity-fix.json` (the v1 run also covered extraction, `--suite all`;
the v2 run was grounding only, since extraction doesn't depend on the judge). Models: `gemini-3.5-flash-lite` (extraction),
`qwen3:4b-instruct-2507-q4_K_M` digest `0edcdef34593` via Ollama (judge). Dataset
`a3_enriched` tree `b8bcfa4afe49d7783da7df675851986480fb1feb`, judge threshold 0.80,
`as_of` 2026-10.

### Extraction (observation, no change)

`extraction/v2`, all 6 replies from the cache of the earlier dev tuning.

| Path | tp | fp | fn | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| Digital PDF (pdf_text) | 153 | 15 | 18 | 0.911 | 0.895 | 0.903 |
| Simulated photo (vision) | 153 | 13 | 18 | 0.922 | 0.895 | 0.908 |

Dev PDF F1 is below the 0.95 test criterion. The extraction prompt is not changed in this
task (owner instruction: choose the judge prompt on dev, then one locked test run).

### Judge prompt: v1 against v2 (2026-10-31)

| Measure | judge/v1 | judge/v2 |
|---|---|---|
| False accepts (unsupported passed / unsupported) | 0/20 | 0/20 |
| Unsupported routed to user review / unsupported | 3/20 | 1/20 |
| False rejects (supported rejected / supported) | 7/20 | 9/20 |
| Supported in user review / supported | 7/20 | 5/20 |
| Judge errors | 0/40 | 0/40 |

**Choice: `judge/v2`.** False accepts tie at 0. On the second rule v2 routes fewer
unsupported claims to review instead of rejecting them (1 against 3: v2 rejects all three
paraphrase overstatements, v1 sent two to review). The third rule (false rejects, where v1
is better, 7 against 9) is not reached. `PROMPT_VERSION` in `src/evident/validation/judge.py`
is now `v2`.

### Finding: Layer 1 false rejects on faithful claims (not changed here)

Of the 20 supported dev claims, 10 fail Layer 1, and the cause is in Layer 1, not the
claims:

1. **Written dates read as names (7 claims).** The entity check treats "Mar 2025",
   "Feb 2024" and similar as names that no cited fact mentions. Every supported claim with
   a written month fails (project dates, role dates, degree start).
2. **Name runs across "and" (2 claims).** "Retrieval Assistant and Text Classification
   Study" is read as one name, so both two-project aggregate claims fail.
3. **Metric direction (1 claim).** "Cut timetable clash checks to under 2 seconds" doesn't
   bind: the ground-truth metric is `absolute`, and "cut" is a decrease word.

These all fail closed: none can cause a false accept. Step 7 allows changes only to the
extraction prompt, the judge prompt and the threshold, so Layer 1 was not changed as part of
the tuning.

### Owner decision: fix issues 1 and 2, keep issue 3 (2026-10-31)

The owner asked for issues 1 and 2 to be fixed as a separate task, test first with a fresh
reviewer, and issue 3 to stay as it is. Commit `76fb242` changes only the entity rule:

- Written dates the date rule reads (a month or season directly before a year, with an
  optional leading day: "Mar 2025", "3 June 2025") are cut out of name runs. "June 3, 2025"
  is not cut, because the date rule would check only its year.
- Name runs are split on "and", and each part must equal a whole name in the evidence
  (title, organisation, skill, or a capitalised run in the fact text). A word in plain
  prose, a fragment of a longer name, or a lone word opening a sentence, line or bullet does
  not count.

Eight fresh reviews; the first seven each found a false accept path, now each a regression
test. The eighth approved after comparing about 10,000 generated claims against the previous
code. The judge prompt, threshold, claim sets and labels did not change.

Known limitations of the entity rule after the fix (all from reviews, not from test data):

- Two names that each appear whole in the evidence can be joined with "and" into a name no
  fact mentions ("Marks" and "Spencer" make "Marks and Spencer" pass).
- A name whose first word is an ownership verb ("Led Zeppelin") can lose that word at the
  start of a sentence.
- Older, not from this change: at the start of a sentence any first word is dropped, so
  "Goldman Sachs backed the planner." passes with no evidence (a single word is skipped).
- Fail-closed rejects: "Joined May 2024 ..." (rejected on "Joined"), "June 3, 2025" style
  dates, and an evidence name followed by a date.

### Known limitation: metric direction (issue 3, not fixed)

"Cut timetable clash checks to under 2 seconds" is rejected because the ground-truth metric
has direction `absolute` while "cut" reads as a decrease, so the number doesn't bind. The
owner decided to leave the metric direction rule unchanged. It fails closed: claims like
this are rejected, never passed. Expect it in test-split false rejects for metric claims
whose ground truth is absolute.

### Dev re-run after the entity fix (2026-10-31)

Run record `runs/dev_grounding_judge-v2.json`, `judge/v2`, threshold 0.80, same 40 dev
claims, same models and digest as above.

| Measure | v2 before fix | v2 after fix |
|---|---|---|
| False accepts (unsupported passed / unsupported) | 0/20 | 0/20 |
| Unsupported routed to user review / unsupported | 1/20 | 1/20 |
| False rejects (supported rejected / supported) | 9/20 | 9/20 |
| Supported in user review / supported | 5/20 | 1/20 |
| Supported passed / supported | 6/20 | 10/20 |
| Judge errors | 0/40 | 0/40 |

False accepts stay at 0/20, so the owner's condition for the locked test run is met. Every
unsupported claim is still caught: 15 by both layers, 4 by the judge only, 1 by Layer 1
only. The fix moved four supported claims from user review to passed. The false rejects did
not fall, because the judge also rejects most of the same claims: 8 of the 9 are now
rejected by the judge alone (three written project or role dates, one subject claim, a
two-project aggregate, both four-subject aggregates, a project scope claim) and 1 by both layers (the
metric claim of issue 3). Nothing was tuned in response; the dev false reject rate (45%) is
well above the 10% test criterion, so a test fail on that criterion is expected.
