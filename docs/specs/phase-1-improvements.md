# Phase 1 improvements: spec

- **Status:** draft, waiting for owner approval.
- **Date:** 2026-11-03. Branch `improve-grounding`, starting from the A3 submission (tag `v0.1-a3`).
- **Why:** the A3 evaluation (`experiments/a3-slice/RESULTS.md`) passed on false accepts (0/45) and photo F1, but failed on false rejects (13/40, all from the judge) and digital PDF F1 (0.930). It also found Layer 1 gaps that fail closed, and a planner that leaves out skills and coursework. This phase fixes what the evaluation found and measures the fixes on a new held-out test set.
- **Naming:** "phase 1" here means the first phase after the A3 submission. It is not phase 1 ("Contracts and harness") of the design's Build order, and it does not start any Build order phase.
- **Implements:** design sections Grounding and validation, Deterministic check rules, Prompts (content planner), Evidence receipts (vision row), Evaluation harness, Validation plan (experiment 2 in a reduced form), Models and fallbacks (judge).
- **Invariants touched:** `cv-builder-invariants` section 1 (grounding: metrics, entities, judge, receipts), section 2 (contracts: none changed, see 9), section 4 (untrusted content, local data only, logging) and section 5 (evaluation: dev and test splits, bounds, criteria before running). Section 3 (job queue) and RLS are out of scope.
- **Decisions in force:** Decision log 1, 2, 3, 6 and 11; P1, P2, P3, P4 in `docs/decisions-proposed.md`. New entries this phase adds: P6 (judge comparison), P7 (owner decision on metric direction), P8 (lower-is-better metrics, needs approval). P5 is still only a proposal (see 5.3).

Items marked **[my call]** are defaults I chose that you did not decide. Everything else comes from your instructions, the design or the A3 results.

## 1. Goals

In this order (the order is yours):

1. A new held-out test set from five new fictional profiles (06 to 10), with pass criteria committed before any test run.
2. Lower the judge's false rejects by comparing the current judge with a local 8B model and tuning the threshold, on dev data only, with zero false accepts as a hard requirement.
3. The planner always adds one Skills claim and one Coursework claim from confirmed facts (new prompt version).
4. Three Layer 1 fixes: subject codes, the sentence-start entity gap, and metric direction for "cut ... to under N". None may add a false accept.
5. Photo receipts accept OCR word positions where they agree with the model's box.
6. One locked run on profiles 06 to 10, reported side by side with the A3 results.

## 2. Non-goals and anti-goals

- **Non-goals:** real CVs (none are collected this phase), new output types, the job queue, RLS, Docker services, Gotenberg, the web UI, contract changes, extraction prompt changes, and the full experiment 2 (200 + 200 claims).
- **Anti-goals (the phase fails even if the numbers improve):**
  - any false accept on the test set, or any new false accept path in Layer 1;
  - anything tuned, read or rerun on profiles 06 to 10 before the locked run;
  - judge data or CV text leaving the machine: the judge is local only, because later phases use real consented CVs;
  - a receipt box marked verified when OCR did not read the span inside it.

## 3. Data splits for this phase

| Split | Profiles | Use |
|---|---|---|
| Dev | 01 to 05 | Everything that is tuned or chosen: judge model, threshold, Layer 1 fixes, planner prompt, receipt rule |
| Test (locked) | 06 to 10 | One run at the end, nothing tuned on it |

Profiles 02 to 05 were the A3 test split. As you said, they now become dev data, and so do the A3 test claims (`experiments/a3-slice/claims_test.jsonl`). The phase 1 dev claim set is the 40 A3 dev claims plus the 85 A3 test claims: 125 claims (60 supported, 65 unsupported). **[my call]** No new dev claims are generated unless a task needs a case the set lacks (for example lower-is-better metric claims for 6.3). Any added dev claims come from profiles 01 to 05 only, with seed 1, and are hand-checked like the others.

## 4. Item 1: held-out test set (profiles 06 to 10)

### 4.1 The profiles

Five new fictional profiles in the A1 record format (same fields as `data/synthetic/student_profiles.jsonl`), followed by an overlay in the same format as `data/synthetic/a3_enriched/overlay.json`.

| Profile | Shape (yours) | Detail **[my call]** |
|---|---|---|
| 06 | Career changer | Several years in a non-tech job (for example a pharmacy assistant), then came to computing; the earlier role is real experience with no software deployment |
| 07 | Gap year | A gap year between school and university, or mid-degree, with dates that show it; one short volunteering entry inside the gap |
| 08 | More work experience | Two or three roles (part-time developer, internship, casual job) with overlapping dates, so duration checks see overlaps |
| 09 | Mostly skills, few projects | A long skills list, one small project, coursework carrying most of the skill evidence |
| 10 | Your list has four shapes for five profiles, so I chose this one | Holds a certification and an award, the two fact kinds profiles 01 to 05 don't use |

Every profile:

- is marked `profile_type: synthetic_plausible` and carries the same synthetic notice as 01 to 05; names, organisations, links and contact details are invented, and no real employer is named **[my call]**: invented organisation names only, since a real company in a synthetic CV reads as a claim about that company;
- has the same field structure, a `skill_evidence` entry for every skill, 1 to 3 metric records with `span_text` added word for word to the description, and dates, ownership and deployment as in the A3 overlay;
- varies phrasing naturally. **[my call]** The profiles are written and committed before any Layer 1 or planner work starts, so they are not shaped around the fixes. They include whatever metric wording reads naturally, including lower-is-better metrics if the story calls for one.

### 4.2 Where the files go **[my call]**

The A1 files are locked by SHA-256 in `tests/eval/test_datasets.py`, so profiles 06 to 10 never touch them. New folder `data/synthetic/heldout_p1/`:

- `source_profiles.jsonl`: the five A1-format records (hand-written);
- `overlay.json`, `profiles.jsonl` (generated), `ground_truth/`, `rendered/` (3 templates as PDF, 3 simulated photos per profile, same seeds and settings as `scripts/make_photos.py`), `README.md` with the synthetic notice;
- templates are reused from `data/synthetic/a3_enriched/templates/`, not copied.

`scripts/build_enriched.py`, `render_cvs.py` and `make_photos.py` get a dataset argument (default stays `a3_enriched`), so A3 outputs rebuild byte for byte. A test checks that.

### 4.3 Test claim set **[my call: sizes]**

Built by the same `build_claim_set` code with a new seed (2), from profiles 06 to 10 only:

- 90 unsupported (10 per category, the same 9 categories as A3) and 80 supported.
- With 0 false accepts in 90, the one-sided 95% upper bound is about 3.3% (A3: 6.4% from 45). It still can't show the design's 2% target, and the results will say so.
- If a profile can't produce enough mutations of a category, the builder takes what exists and records the real counts before the run.
- Every claim is hand-checked by the builder (`claims_review.md`), and relabels or drops are recorded.
- After the hand-check, the claim files are committed and no one opens or runs anything on them until the locked run. A test checks that no dev or tuning script accepts a 06 to 10 profile ID.

### 4.4 Pass criteria (committed before any test run)

Written into `experiments/p1-heldout/RESULTS.md` and committed as part of item 1, before any work on items 2 to 5. Proposed values:

| Measure | Criterion | Source |
|---|---|---|
| False accepts on test claims | 0 / all unsupported | Invariant, hard gate |
| False reject rate (supported rejected / supported) | ≤ 10% | Same as A3 and Validation plan 2 |
| Extraction F1, digital PDF | ≥ 0.95 | Validation plan 1 |
| Extraction F1, photos | ≥ 0.90 | Validation plan 1 |
| Planner Skills and Coursework claims | **[my call]** In 5 of 5 profiles the plan contains at least one Skills claim and one Coursework claim; reported with how many of those pass validation | Item 3 |
| Photo receipts verified (facts with a verified box / facts with a span) | **[my call]** ≥ 80%, and 0 wrong boxes among those verified by word positions (every one is checked by hand on a contact sheet) | Validation plan 3's threshold, used on photos |

Reported but with no pass criterion: user review rates, per-category tables, which layer caught what, judge time per claim (p50, p90, n), Gemini calls and estimated cost.

The pass tests work as in A3: pooled F1 against the threshold, with the bootstrap interval reported but not deciding; rates with one-sided 95% Clopper-Pearson upper bounds.

## 5. Item 2: judge comparison (dev only)

### 5.1 Candidates

- **Current:** `qwen3:4b-instruct-2507-q4_K_M`, digest `0edcdef34593`.
- **Candidate (yours: local 8B through Ollama, layers on the CPU if needed):** `qwen3:8b-q4_K_M`, digest `500a1f067a9f`, 5.2 GB, from the Ollama library tags page checked on 2026-11-03.
  - **[my call] Why this one:** it is the only current 8B instruct tag I could verify in the Ollama library with a known lineage. Newer 9B models are listed (for example `nimble-v3`, `bonsai-2`), but their base family and licence aren't stated clearly. They could be Gemma-based, which Decision 2 rules out.
  - **Limitation:** same family as the current judge (Qwen). The comparison measures model size, not family. Both are different-family from Gemini, so Decision 2 holds either way.
  - Qwen3 8B is a hybrid thinking model. It runs with thinking switched off (Ollama `think: false`), so replies stay short and inside the 512-token judge budget. If the adapter can't switch thinking off, the builder stops and reports back.
- **Fit check (first step of item 2, before any dev run):** pull the tag, confirm the local digest matches `500a1f067a9f`, run one judgement, and record from `ollama ps` the GPU/CPU split and the time. Pin the digest in `config/models.toml` under `[ollama_digests]`.
- **Timeout:** the judge call keeps the 30 s text timeout (invariants). A candidate whose p90 time per claim on dev is over 20 s is not eligible **[my call: margin]**. A timed-out call is a judge error, so the claim goes to user review, never passes.

### 5.2 What is compared and how the winner is chosen (written before running)

Both models use prompt `judge/v2` unchanged **[my call]**. A new judge prompt isn't in scope; if dev results point to one, I'll propose it. Each model judges all 125 dev claims once, and the raw verdicts and confidences are stored. Thresholds are then applied offline from 0.50 to 0.95 in steps of 0.05, so no model reruns are needed per threshold.

Selection, in order **[my call]**:

1. **Eligible:** 0 false accepts on all 65 dev unsupported claims at that threshold, 0 judge errors other than timeouts, and p90 time under 20 s.
2. Among eligible (model, threshold) pairs: the fewest false rejects.
3. With supported claims sent to user review capped at 15% (9 of 60). Without the cap, raising the threshold would turn rejects into reviews and look like a fix.
4. Ties: fewer unsupported claims routed to review instead of rejected, then lower p50 time, then the current model and threshold 0.80 (no change without evidence).

Reported in `experiments/p1-judge-dev/RESULTS.md`: for each model, false accepts, false rejects, reviews (both groups), judge errors, time per claim (p50, p90, n, GPU/CPU split), each with numerator/denominator, plus the full threshold table.

If no pair is eligible, nothing changes: the judge and 0.80 stay, and the results say so plainly. If the 8B wins, `roles.judge` moves to it, and P1 is superseded by P6.

### 5.3 Decision entry

P6 in `docs/decisions-proposed.md` records the comparison, the winner and the evidence, for your approval. It also notes that P1's "Ends when: phase 0 experiment 2 runs" is only partly met: this is two candidates on 125 dev claims, not 200 + 200.

## 6. Item 3: planner Skills and Coursework claims

- New prompt `src/evident/prompts/planner/v2.txt`, a copy of v1 plus one instruction: always include at least one claim in a `Skills` section citing confirmed skill facts, and at least one in a `Coursework` section citing confirmed education facts for subjects or coursework, unless no such confirmed facts exist. In that case the section is left out and nothing is invented. `PROMPT_VERSION` moves to `v2`.
- **[my call] P5 conflict:** P5 also proposes a `planner/v2` (feedback inside a data tag, deck claims). P5 isn't approved, so this phase takes `v2` for Skills and Coursework only. If you approve P5 later, it becomes `v3`. Option: approve P5 now and I'll fold it into v2 (one cache invalidation instead of two). Tell me at approval.
- These claims go through Layers 1 and 2 like any other. No deterministic fallback writes a skills claim: the claim text always comes from the planner and is validated. **[my call]** `build_plan` logs a warning, and the run record notes when a profile has confirmed skill or coursework facts but the plan has no claim for one, so the locked run can count it.
- Dev check: planner runs on profiles 01 to 05 with one job ad each (about 5 to 10 Flash-Lite calls, cached), plus a unit test with a fake adapter showing the instruction is in the rendered prompt and that a plan with no skill facts doesn't demand one.

## 7. Item 4: Layer 1 fixes

Each fix follows the same steps:

1. Reproduce the failing case as a test.
2. Write the false-accept regression tests the reviewer asks for.
3. Make the fix.
4. Fresh reviewer (spec compliance against `cv-builder-invariants`), with as many review rounds as it takes to get an approval.
5. Compare the new rule with the old one on the 125 dev claims plus about 10,000 generated claims, as for the entity fix in A3. Any claim the new code passes and the old code rejected is listed and checked by hand. Any unsupported one blocks the fix.

### 7.1 Subject codes read as numbers

- A3 tests pass for "Enrolled in 43007 Advanced Artificial Intelligence", so the gap is in other forms. The first step is to find the failing forms in the A3 run records and planner outputs on dev (for example "Advanced Artificial Intelligence (43007)", "subject 43007", or a code in the middle of an evidence sentence). If none can be reproduced, the builder reports back before changing anything.
- **[my call] Direction of the fix:** a number counts as an identifier only if it appears as a whole token in the title of a cited education fact, and the claim puts it next to at least two words of that same title, in either order, with brackets allowed. A figure from free description text ("covered 1,200 responses") still has to bind to a metric record.

### 7.2 Sentence-start entity gap ("Goldman Sachs backed the planner.")

- Today any first word of a sentence is dropped from name runs, so a two-word name at the start of a sentence loses its first word and passes.
- **[my call] Fix:** the first word is dropped only if it is in a lexicon of common sentence openers (ownership verbs, action verbs, determiners, pronouns) in `config/`. Otherwise it stays in the name run and must appear in the evidence.
- Expected cost: more fail-closed rejects for supported claims that open with an unlisted capitalised word. They are counted on dev and reported.
- The A3 known limitations ("Marks and Spencer", "Led Zeppelin") are not in scope. They stay listed.

### 7.3 Metric direction: "cut ... to under 2 seconds"

- **Owner decision (yours, 2026-11-03):** this reverses the 2026-10-31 decision to leave issue 3 as it was. Recorded as P7 (approved).
- **[my call] Fix:** when a direction word is followed by "to" and an optional bound word ("under", "below", "less than", "over", "above") before the number, the number states an end value. It may then bind to an `absolute` record as well as one with the matching direction. "Cut latency by 2 seconds" (with "by") still needs a `decrease` record.
- **Found while writing this spec (confirmed with a probe on the current code):** the round-toward-zero rule assumes bigger is better. With a cited record `latency, absolute, 2 seconds`, Layer 1 passes "Clash checks run in 1 second" and "take 0.5 seconds". That is an existing Layer 1 false-accept path for lower-is-better metrics. The judge may still catch these, but Layer 1 alone doesn't. The 7.3 fix would widen it ("cut to under 1 second" would pass), so:
  - **[my call]** Until you decide, the new 7.3 path binds lower-is-better metrics (latency, error rate, cost and the like, listed in the lexicon) only when the claimed value equals the record's. That meets both readings of the rule.
  - **P8 (needs your approval, it changes an invariant's wording):** for lower-is-better metrics, a claimed value may round away from zero, never toward it. Applied everywhere, it closes the existing path. It is test-first with a fresh reviewer like the other fixes. If you don't approve P8, the existing gap stays open and is listed as a limitation in every report.

## 8. Item 5: photo receipts from OCR word positions

Today a model box is verified only if Tesseract, run on that exact crop, reads the span. Otherwise the receipt falls back to the whole image, marked approximate.

**[my call] New rule**, tried only when the crop check fails:

1. Run Tesseract once per photo on the whole image (`image_to_data`, word boxes), with the same preprocessing as the crop path.
2. Find the span in the OCR word sequence with the same scoring as `span_score`. Short spans must match as whole words.
3. Take the union of the matched words' boxes as the OCR region.
4. Accept it only if:
   - exactly one OCR match scores at or above `VERIFY_THRESHOLD`; two or more is ambiguous, so it falls back;
   - at least 50% of the OCR region's area lies inside the model's box, enlarged by a small margin. Both values are tuned on dev photos (profiles 01 to 05) only.
5. The stored box is the OCR region, with `bbox_verified = true`, since OCR read the span there. `confidence` is the match score.

No contract change: `VisionSource` keeps its fields. The run record logs which method verified each box (crop or word positions). If the builder finds a contract field is needed, they stop and ask.

Dev check: verified-box rate before and after on all 15 dev photos, from cached extraction replies (no new Gemini calls). Every newly accepted box is rendered as a crop on one contact sheet and checked by hand. Any wrong box blocks the rule. A fresh reviewer is used, since this is receipt and post-render territory.

The A3 verified-box rate was not reported. It is recomputed from the cached A3 replies under the old code, labelled as a re-analysis.

## 9. What does not change

- Contracts (`src/evident/contracts/`): no change, no `schema_version` bump. If any task needs one, it stops and asks.
- Extraction prompt `v2`, the coverage and requirements prompts, and the Gemini model roles (P3).
- No new Python dependencies **[my call]**: `pytesseract`, `rapidfuzz` and the Ollama adapter are already in use. Pulling `qwen3:8b-q4_K_M` is a model download, not a package. If one is needed, I'll ask.

## 10. Locked run and comparison

1. Prerequisites: items 1 to 5 merged on the branch, every test green, and the dev results files written.
2. One run on profiles 06 to 10:
   - extraction (15 PDFs, 15 photos);
   - grounding on the 170 test claims with the chosen judge and threshold;
   - the planner on each profile with one job ad;
   - photo receipt verification.
   - About 45 to 60 Flash-Lite calls, under the 500 a day cap, checked at pre-flight.
3. `experiments/p1-heldout/RESULTS.md` gets:
   - the results against the criteria committed in 4.4;
   - a side-by-side table: A3 test (profiles 02 to 05 or 03 to 05) against phase 1 test (06 to 10), for every measure both runs have;
   - model IDs, digests, prompt versions, dataset version (git tree hash of `heldout_p1`), lexicon version, and limitations.
4. The two runs use different profiles, so the comparison isn't paired: a difference may come from the profiles as well as the fixes. Profile 06 to 10 variety (career changer, gap year and so on) may make them harder. The results say this.
5. A failed criterion is reported as a fail. Nothing is rerun or tuned on 06 to 10 afterwards.

## 11. Repo housekeeping

- `CLAUDE.md` "Current phase" now describes this phase (done in the same commit as this spec).
- Results files: `experiments/p1-judge-dev/RESULTS.md` (item 2 and the dev parts of 3 to 5) and `experiments/p1-heldout/RESULTS.md` (criteria first, locked run last).
- Milestones where I'll tell you to push:
  - test set and criteria committed;
  - judge comparison done;
  - Layer 1 fixes done;
  - planner and receipts done;
  - locked run reported.

## 12. Order of work

1. Item 1: profiles, rendering, ground truth, claim set, hand-check, pass criteria. Commit.
2. Item 2: fit check, dev comparison, threshold choice, P6.
3. Item 4: Layer 1 fixes (7.1, 7.2, 7.3, and P8 if you approve it). These run before the planner, so planner dev checks use the fixed Layer 1.
4. Item 3: planner v2.
5. Item 5: photo receipts.
6. Recompute the judge selection offline from the stored dev verdicts with the fixed Layer 1, since outcomes combine both layers. The judge's verdicts don't depend on Layer 1, so no model reruns. Report both versions. If the choice changes, P6 is updated.
7. Locked run.

Item 4 runs before item 3, unlike your list. The planner's dev check counts how many of its claims pass validation, and that count should come from the fixed Layer 1. The work itself doesn't change. Tell me if you want your order kept.
