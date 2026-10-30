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

## Test split results

Run started 2026-10-30T21:33:08+00:00 (UTC). One locked run; nothing was tuned on this split.

- Models configured: extraction_text `gemini-3.5-flash-lite`, extraction_vision `gemini-3.5-flash-lite`, requirements `gemini-3.5-flash-lite`, coverage `gemini-3.5-flash-lite`, planner `gemini-3.5-flash-lite`, judge `qwen3:4b-instruct-2507-q4_K_M`
- Ollama digests: {'qwen3:4b-instruct-2507-q4_K_M': '0edcdef34593'}
- Prompt versions: extraction `v2`, judge `v2` (chosen on the dev split, see the Dev tuning log)
- Dataset version: `a3_enriched` tree `b8bcfa4afe49d7783da7df675851986480fb1feb`
- Lexicons version 1, aliases version 1, `as_of` 2026-10
- Cache hits: 0/109 calls; uncached Gemini calls planned at pre-flight: 24

### Extraction F1 (spec 9.1)

Field-level counts; F1 = 2tp / (2tp + fp + fn). Interval: 95% bootstrap resampling whole underlying profiles (10,000 resamples, seed 0).

| Path | tp | fp | fn | Precision | Recall | F1 | 95% interval |
|---|---|---|---|---|---|---|---|
| Digital PDF (pdf_text) | 643 | 41 | 56 | 0.940 | 0.920 | 0.930 | 0.926 to 0.933 (4 profiles) |
| Simulated photo (vision) | 619 | 54 | 80 | 0.920 | 0.886 | 0.902 | 0.876 to 0.928 (4 profiles) |

Per template:

| Path | Template | tp | fp | fn | Precision | Recall | F1 | 95% interval |
|---|---|---|---|---|---|---|---|---|
| Digital PDF (pdf_text) | classic | 215 | 14 | 18 | 0.939 | 0.923 | 0.931 | 0.919 to 0.949 (4 profiles) |
| Digital PDF (pdf_text) | compact | 218 | 12 | 15 | 0.948 | 0.936 | 0.942 | 0.929 to 0.954 (4 profiles) |
| Digital PDF (pdf_text) | sidebar | 210 | 15 | 23 | 0.933 | 0.901 | 0.917 | 0.911 to 0.921 (4 profiles) |
| Simulated photo (vision) | classic | 217 | 15 | 16 | 0.935 | 0.931 | 0.933 | 0.905 to 0.961 (4 profiles) |
| Simulated photo (vision) | compact | 197 | 16 | 36 | 0.925 | 0.845 | 0.883 | 0.850 to 0.903 (4 profiles) |
| Simulated photo (vision) | sidebar | 205 | 23 | 28 | 0.899 | 0.880 | 0.889 | 0.825 to 0.923 (4 profiles) |

### Claim grounding (spec 9.2)

Judge prompt `judge/v2`, threshold 0.80. A claim in user review is not accepted, so it is not a false accept.

- False accept rate (unsupported accepted / all unsupported): 0/45 (0.0%, 95% upper 6.4%)
- False reject rate (supported rejected / all supported): 13/40 (32.5%, 95% upper 46.6%)
- User review, unsupported claims: 4/45 (8.9%, 95% upper 19.2%)
- User review, supported claims: 3/40 (7.5%, 95% upper 18.3%)
- Judge errors: 0 of 85 claims

Per category (unsupported claims):

| Category | n | False accepts | User review | Rejected |
|---|---|---|---|---|
| wrong_number | 5 | 0/5 (0.0%, 95% upper 45.1%) | 0/5 (0.0%, 95% upper 45.1%) | 5/5 (100.0%, 95% upper 100.0%) |
| wrong_date | 5 | 0/5 (0.0%, 95% upper 45.1%) | 0/5 (0.0%, 95% upper 45.1%) | 5/5 (100.0%, 95% upper 100.0%) |
| inflated_ownership | 5 | 0/5 (0.0%, 95% upper 45.1%) | 0/5 (0.0%, 95% upper 45.1%) | 5/5 (100.0%, 95% upper 100.0%) |
| inflated_deployment | 5 | 0/5 (0.0%, 95% upper 45.1%) | 1/5 (20.0%, 95% upper 65.7%) | 4/5 (80.0%, 95% upper 99.0%) |
| unsupported_skill | 5 | 0/5 (0.0%, 95% upper 45.1%) | 0/5 (0.0%, 95% upper 45.1%) | 5/5 (100.0%, 95% upper 100.0%) |
| wrong_entity | 5 | 0/5 (0.0%, 95% upper 45.1%) | 2/5 (40.0%, 95% upper 81.1%) | 3/5 (60.0%, 95% upper 92.4%) |
| fake_id | 5 | 0/5 (0.0%, 95% upper 45.1%) | 1/5 (20.0%, 95% upper 65.7%) | 4/5 (80.0%, 95% upper 99.0%) |
| wrong_aggregate | 5 | 0/5 (0.0%, 95% upper 45.1%) | 0/5 (0.0%, 95% upper 45.1%) | 5/5 (100.0%, 95% upper 100.0%) |
| paraphrase_overstatement | 5 | 0/5 (0.0%, 95% upper 45.1%) | 0/5 (0.0%, 95% upper 45.1%) | 5/5 (100.0%, 95% upper 100.0%) |

Which layer flagged each unsupported claim (regardless of final outcome):

- layer1 and judge: 35/45 (77.8%, 95% upper 87.4%)
- layer1 only: 2/45 (4.4%, 95% upper 13.3%)
- judge only: 8/45 (17.8%, 95% upper 29.8%)
- none: 0/45 (0.0%, 95% upper 6.4%)

Which layer flagged each falsely rejected supported claim (13):

- layer1 and judge: 0
- layer1 only: 0
- judge only: 13
- none: 0

### Cost and latency (observations, no criterion)

Estimated cost uses paid list prices from `config/models.toml`; actual cost is zero on the free tier. Latency is for uncached calls only.

| Role | Calls | Cached | Model IDs | Prompt versions | Tokens in/out | Est. cost USD | Uncached latency |
|---|---|---|---|---|---|---|---|
| extraction_text | 12 | 0 | gemini-3.5-flash-lite | v2 | 10542/29902 | 0.0779 | n=12, p50 5.6 s, p90 5.7 s |
| extraction_vision | 12 | 0 | gemini-3.5-flash-lite | v2 | 19488/34197 | 0.0913 | n=12, p50 8.0 s, p90 10.3 s |
| judge | 85 | 0 | qwen3:4b-instruct-2507-q4_K_M | v2 | 31206/5225 | 0.0000 | n=85, p50 3.1 s, p90 4.2 s |

### Pass or fail against the stated criteria

- Extraction F1 on digital PDFs >= 0.95: **Fail**
- Extraction F1 on photos >= 0.9: **Pass**
- Zero false accepts on the test split: **Pass**
- False reject rate <= 10%: **Fail**

A pass on extraction does not establish the phase 0 result: the CVs are synthetic, the photos simulated, and there are only 4 test profiles.

### Limitations

- Pilot results on synthetic data: only 5 underlying profiles, and 4 of them in the extraction test split, so every interval is wide
- Simulated photos (warp, tilt, uneven light, blur, noise, JPEG), easier than real phone photos
- Claims are built from templates and hand-checked by the builder, not the owner; real planner output is more varied
- About 45 unsupported test claims: 0 false accepts gives an upper bound near 6.4%, so even a pass can't show the design's 2% target
- Layer 1 metric direction (known, not fixed by owner decision): a decrease word such as "cut" does not bind to a metric recorded as absolute, so such supported claims are rejected (fails closed)
- Layer 1 entity rule: two names each found whole in the evidence can combine through "and" into a name no fact mentions; see the dev tuning log for the full list
- Small local judge: qwen3:4b-instruct-2507-q4_K_M, 4B quantised, self-reported uncalibrated confidence (P1)
- Free-tier gemini-3.5-flash-lite for extraction, coverage and planning, not a Pro-class model (P3)
