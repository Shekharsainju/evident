# Phase 1 improvements: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix what the A3 evaluation exposed (judge false rejects, Layer 1 gaps, planner coverage of skills and coursework, photo receipts), and measure the fixes in one locked run on new held-out profiles 06 to 10.

**Architecture:** Profiles 06 to 10 get their own dataset folder, and the dataset code picks a folder by profile ID, so existing callers don't change. The dev and test split constants for this phase live in one module, with a guard that refuses test profiles outside the locked run. Layer 1 fixes are small rule changes in `validation/layer1/`, each checked against the previous code by a diff script. The judge comparison stores raw verdicts once and sweeps thresholds offline.

**Tech Stack:** Python 3.12, Pydantic v2 (strict), pytest, ruff, mypy (strict), pdfplumber, pytesseract, rapidfuzz, Ollama (local judge), Gemini 3.5 Flash-Lite (free tier, synthetic data only), Playwright (render).

**Spec:** `docs/specs/phase-1-improvements.md` (approved 2026-11-03). Read it with this plan. Section numbers below ("spec 7.3") refer to it.

## Global Constraints

- Work on branch `improve-grounding`. Never push, force, reset --hard or rewrite history. Commits use a conventional prefix, an imperative summary under 72 characters, no emoji, and no AI attribution.
- Writing style (CLAUDE.md): no em dashes or double hyphens as punctuation; none of the banned words; comments explain why.
- Contracts in `src/evident/contracts/` do not change. If a task needs a change, stop and ask.
- No new Python dependencies. Pulling `qwen3:8b-q4_K_M` through Ollama is allowed (Task 9).
- The judge runs locally only. No hosted judge.
- Only synthetic data is sent to Gemini. Never log CV text, contact details or keys.
- Profiles 06 to 10 are the locked test split. After Task 3 commits their claim set, nothing reads, runs or tunes on them until Task 15. Dev is profiles 01 to 05, including every A3 claim (125 claims).
- Fail closed. No task may add a false accept. A claim the new code passes that the old code rejected is checked by hand, and an unsupported one blocks the task.
- Tasks touching `validation/`, `contracts/`, receipts (`ingestion/vision.py`) or post-render verification get a fresh spec-compliance reviewer that checks against `cv-builder-invariants` as well as this plan.
- Model IDs come only from `config/models.toml`. Judge timeout stays 30 s, `max_output_tokens` 512.
- Every RESULTS file reports numerator/denominator, one-sided 95% Clopper-Pearson upper bounds for proportions, model IDs, digests, prompt versions and dataset version.
- Commands (PowerShell): `uv run pytest`, `uv run ruff check . ; uv run mypy .`

## Review Focus

1. **Cold start of a partly offloaded 8B model.** The first call loads 5.2 GB, part of it into system RAM, and may pass the 30 s timeout. Expected: a warm-up call before timing that is recorded but not counted, and any timeout counts as a judge error (user review), never a pass. Test in Task 10.
2. **Units that differ from the record** ("under 2,000 ms" or "2s" against a "2 seconds" record). Expected: either a correct binding or a fail-closed reject, never a pass beyond the record. Test in Task 7.
3. **The same span appears twice on a photo** ("Python" in the skills list and in a project line). Expected: the word-position path sees two matches and keeps the whole-image fallback. Test in Task 12.
4. **A sentence-start name after a bullet, semicolon or line break** ("• Goldman Sachs backed ...", "...; Goldman Sachs backed ..."). Expected: treated like the start of a sentence, so the opener rule applies. Test in Task 6. Task 6 was reverted (P9): after a bullet or line break the name is rejected; after a semicolon or colon it is a documented limitation, kept as a strict xfail.
5. **A profile with no confirmed coursework or skill facts.** Expected: the planner prompt doesn't ask for a section it can't support, and the run record counts the missing claim without inventing one. Test in Task 11.

---

### Task 0: Record the decisions

**Files:**
- Modify: `docs/decisions-proposed.md` (P5 status; add P7, P8; reserve P6)
- Modify: `docs/design.md:378` (Metrics row) and the Decision log (add row 13 for P8)
- Modify (local only, gitignored): `.claude/skills/cv-builder-invariants/SKILL.md`, metrics bullet, edited through `anthropic-skills:skill-creator`

- [ ] **Step 1:** In `docs/decisions-proposed.md`:
  - P5 status: "approved by the owner on 2026-11-03, folded into `planner/v2` with the Skills and Coursework instruction (phase 1 spec 6)".
  - Add **P7:** owner decision of 2026-11-03 reversing the 2026-10-31 decision on metric direction (spec 7.3).
  - Add **P8:** approved 2026-11-03. Rule text from spec 7.3, including the `absolute`-only scope, the probe that found the gap, and that it moves to the Decision log.
  - Add a heading for **P6**, "Judge model and threshold (pending dev comparison, Task 10)".
- [ ] **Step 2:** Change the Metrics row text in `docs/design.md` from "The claimed value may round toward zero, never away." to "The claimed value may round toward zero, never away; for a lower-is-better metric recorded as an absolute value, it may round away from zero, never toward it." Add Decision log row 13 for P8:
  - Decision: lower-is-better absolute metrics round away from zero.
  - Alternatives: one rounding direction for all metrics.
  - Why: a smaller latency, cost or error rate is a stronger claim.
  - Revisit when: never; correctness requirement.
  Regenerating `design.pdf` and `design.docx` is out of scope, and the commit message says so.
- [ ] **Step 3:** Use `anthropic-skills:skill-creator` to make the same wording change in the `cv-builder-invariants` metrics bullet. The file is local, so there is nothing to commit for it.
- [ ] **Step 4:** Commit: `git add docs/decisions-proposed.md docs/design.md` then `git commit -m "docs: record P5, P7 and P8 owner decisions"`.

### Task 1: Dataset paths by profile

**Files:**
- Modify: `src/evident/eval/datasets.py`, `src/evident/eval/assets.py`
- Modify: `scripts/build_enriched.py`, `scripts/render_cvs.py`, `scripts/make_photos.py` (add `--dataset {a3_enriched,heldout_p1}`, default `a3_enriched`)
- Test: `tests/eval/test_datasets.py`, `tests/scripts/test_cv_assets.py`

**Interfaces:**
- Produces (in `datasets.py`):
  - `@dataclass(frozen=True) class Dataset: name: str; dir: Path; source_profiles: Path; overlay: Path; profiles: Path; ground_truth_dir: Path; rendered_dir: Path`
  - `A3_ENRICHED: Dataset` (source `data/synthetic/student_profiles.jsonl`) and `HELDOUT_P1: Dataset` (dir `data/synthetic/heldout_p1`, source `heldout_p1/source_profiles.jsonl`)
  - `dataset_for(document_id: str) -> Dataset`: 01 to 05 give `A3_ENRICHED`, 06 to 10 give `HELDOUT_P1`, anything else raises `ValueError`
  - `build_enriched_profiles(ds: Dataset = A3_ENRICHED)`, `load_enriched_profiles(ds: Dataset = A3_ENRICHED)`
  - `ground_truth_path(document_id)` and `load_ground_truth(document_id)` go through `dataset_for`
  - `ENRICHMENT_NOTE` becomes per dataset (`Dataset.enrichment_note: str`). The heldout note points at `heldout_p1/overlay.json`.
- Produces (in `assets.py`): `cv_pdf_path(document_id, template)` and `cv_photo_path(document_id, template)` go through `dataset_for(...).rendered_dir`. Templates stay in `a3_enriched/templates/`.
- Old module constants (`ENRICHED_PROFILES`, `GROUND_TRUTH_DIR` and so on) stay as aliases of `A3_ENRICHED` fields, so existing imports keep working.

- [ ] **Step 1: Write the failing tests:**
  - `test_dataset_for_routes_profiles`: `dataset_for("student_profile_03") is A3_ENRICHED`, `dataset_for("student_profile_08") is HELDOUT_P1`, `pytest.raises(ValueError)` for `"student_profile_11"`.
  - `test_a3_rebuild_is_byte_identical`: for each of profiles 01 to 05, `dump_ground_truth(ground_truth_facts(p, ...)) == ground_truth_path(id).read_bytes()`, and `build_enriched_profiles()` serialised as the script writes it equals `profiles.jsonl`.
  - `test_photo_seed_for_heldout`: the seed function `photo_seed(document_id, template) -> int` gives `100 * n + j`, where n is the profile number (1 to 10) and j the template index. So profile 01 keeps 100 to 102, and profile 06 gets 600 to 602.
- [ ] **Step 2:** Run `uv run pytest tests/eval/test_datasets.py tests/scripts/test_cv_assets.py -v`. Expected: FAIL (names not defined).
- [ ] **Step 3:** Implement the interfaces above, and `photo_seed` in `assets.py`. `make_photos.py` uses `photo_seed` instead of the enumerate index. Profile n's seed equals what the old enumerate gave for 01 to 05, so A3 photos don't change.
- [ ] **Step 4:** Run the full suite: `uv run pytest`, then `uv run ruff check . ; uv run mypy .`. Then `uv run python scripts/build_enriched.py` and `git status --short data/`. Expected: tests pass, and no file under `data/synthetic/a3_enriched` changes.
- [ ] **Step 5:** Commit: `refactor: route dataset paths by profile id`.

### Task 2: Profiles 06 to 10 and their assets

**Files:**
- Create: `data/synthetic/heldout_p1/source_profiles.jsonl`, `overlay.json`, `README.md`
- Generated (commit): `heldout_p1/profiles.jsonl`, `ground_truth/student_profile_0{6..9}.json`, `ground_truth/student_profile_10.json`, `rendered/*.pdf`, `rendered/*_photo.jpg`
- Test: `tests/eval/test_heldout_dataset.py`

**Interfaces:**
- Consumes: Task 1's `HELDOUT_P1`, `dataset_for`, script `--dataset heldout_p1`.

- [ ] **Step 1: Write the failing tests** in `tests/eval/test_heldout_dataset.py`:
  - `test_five_profiles_ids_06_to_10`: `[p["document_id"] for p in load_enriched_profiles(HELDOUT_P1)] == ["student_profile_06", ..., "student_profile_10"]`.
  - `test_same_fields_as_a1`: each source record has exactly the key set of an A1 record.
  - `test_marked_synthetic`: every record has `profile_type == "synthetic_plausible"`, and the README contains the same synthetic notice wording as `a3_enriched/README.md`.
  - `test_every_skill_has_evidence`: each `technical_skills` item has a `skill_evidence` entry.
  - `test_metric_span_in_description`: every overlay metric's `span_text` appears verbatim in its entry's enriched description.
  - `test_metric_count_per_profile`: 1 to 3 metric records per profile.
  - `test_shapes`:
    - 06 has an experience entry ending at least 12 months before `education_start`, with `deployment` null;
    - 07 has a gap of at least 9 months with no education or experience between two dated entries;
    - 08 has at least 3 experience entries and at least one overlapping pair;
    - 09 has at least 12 skills and exactly 1 project;
    - 10 has at least one `certification` fact and one `award` fact in ground truth.
  - `test_no_real_organisations`: every organisation name contains "Fictional" or comes from a fixed list of invented names in the test file.
  - `test_assets_exist`: 3 PDFs and 3 photos per profile.
- [ ] **Step 2:** Run `uv run pytest tests/eval/test_heldout_dataset.py -v`. Expected: FAIL (files missing).
- [ ] **Step 3:** Write the five source records and the overlay by hand (spec 4.1). Ground truth must cover certification and award facts for profile 10.
  - If `ground_truth_facts` doesn't yet emit those kinds, extend it in `datasets.py`, with a test that A3 ground truth stays byte-identical (Task 1's test covers this).
  - Then run, in order: `uv run python scripts/build_enriched.py --dataset heldout_p1`, `uv run python scripts/render_cvs.py --dataset heldout_p1`, `uv run python scripts/make_photos.py --dataset heldout_p1`.
- [ ] **Step 4:** Run `uv run pytest`. Expected: PASS. Open one PDF and one photo per profile and check it renders on one page and reads correctly. Note the result in the commit body.
- [ ] **Step 5:** Commit: `feat: add held-out synthetic profiles 06 to 10`.

### Task 3: Locked test claim set, split guard and pass criteria

**Files:**
- Create: `src/evident/eval/splits.py`
- Modify: `src/evident/eval/grounding.py` (profile tuple and counts become parameters of `build_claim_set`)
- Create: `scripts/build_p1_claims.py`, `experiments/p1-heldout/claims_test.jsonl`, `experiments/p1-heldout/claims_review.md`, `experiments/p1-heldout/RESULTS.md` (criteria only)
- Test: `tests/eval/test_splits.py`, `tests/eval/test_grounding.py`

**Interfaces:**
- Produces (in `splits.py`):
  - `P1_DEV_PROFILES: tuple[str, ...]` (01 to 05) and `P1_TEST_PROFILES` (06 to 10)
  - `P1_DEV_CLAIM_FILES = (Path("experiments/a3-slice/claims_dev.jsonl"), Path("experiments/a3-slice/claims_test.jsonl"))`
  - `P1_TEST_CLAIMS = Path("experiments/p1-heldout/claims_test.jsonl")`
  - `load_p1_dev_claims() -> list[LabelledClaim]`
  - `require_dev(profile_ids: Iterable[str]) -> None`: raises `LockedSplitError(ValueError)` if any ID is in `P1_TEST_PROFILES`
  - `load_p1_test_claims(*, locked_run: bool) -> list[LabelledClaim]`: raises `LockedSplitError` unless `locked_run` is true
- Produces (in `grounding.py`): `build_claim_set(seed: int = 0, splits: Sequence[SplitSpec] | None = None) -> list[LabelledClaim]`, with `@dataclass(frozen=True) class SplitSpec: split: Split; profiles: tuple[str, ...]; n_supported: int; per_category: dict[Category, int] | int`. `None` keeps the A3 behaviour.

- [ ] **Step 1: Write the failing tests:**
  - `test_a3_claim_set_unchanged`: before changing `grounding.py`, compute the SHA-256 of `dump_claims(build_claim_set(seed=0))` on the current code and hard-code it. The test asserts the refactored default call gives the same hash.
  - `test_p1_dev_has_125_claims`: `len(load_p1_dev_claims()) == 125`, 60 supported and 65 unsupported, no profile ID from 06 to 10.
  - `test_require_dev_refuses_test_profiles`: `pytest.raises(LockedSplitError)` for `["student_profile_01", "student_profile_07"]`.
  - `test_test_claims_need_locked_flag`: `pytest.raises(LockedSplitError)` for `load_p1_test_claims(locked_run=False)`.
  - `test_tuning_scripts_refuse_test_profiles`: import `scripts/tune_extraction_dev.py`, the Task 4 diff script and the Task 10 comparison script, and check that each calls `require_dev`. Since those scripts don't exist yet, this test is added here as `xfail(strict=True)` per missing script and turned on by Tasks 4 and 10.
- [ ] **Step 2:** Run `uv run pytest tests/eval/test_splits.py tests/eval/test_grounding.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. `scripts/build_p1_claims.py` calls `build_claim_set(seed=2, splits=[SplitSpec("test", P1_TEST_PROFILES, 80, 10)])` and writes `P1_TEST_CLAIMS`. If a category has fewer than 10 mutations available, take what exists and print the real counts.
- [ ] **Step 4:** Hand-check every claim and write `claims_review.md` in the A3 format, with relabels and drops. Record the final counts.
- [ ] **Step 5:** Write `experiments/p1-heldout/RESULTS.md`, with only the "Pass criteria (stated before running)" section:
  - the table from spec 4.4, word for word;
  - the operational rules from A3 (pooled F1, matching rules, Clopper-Pearson);
  - final claim counts, dataset version (`git rev-parse HEAD:data/synthetic/heldout_p1`) and the claim file's SHA-256;
  - "Judge model, threshold and planner prompt version: chosen on dev in Tasks 10 and 11, recorded here before the locked run."
- [ ] **Step 6:** Run `uv run pytest`, ruff and mypy. Expected: PASS.
- [ ] **Step 7:** Commit: `test: lock phase 1 held-out claim set and pass criteria`. **Milestone: tell the owner it is a good time to push.**

### Task 4: Layer 1 diff tool

**Files:**
- Create: `src/evident/eval/layer1_probe.py`, `scripts/layer1_diff.py`
- Test: `tests/eval/test_layer1_probe.py`

**Interfaces:**
- Produces:
  - `probe_claims(seed_range: range = range(50)) -> list[LabelledClaim]`: every supported instance and every mutation from `_instances` and `_mutations` over `P1_DEV_PROFILES`, across the seeds, plus the 125 dev claims. Deduplicated on (text, evidence). It calls `require_dev`. It may be fewer or more than 10,000 claims; the count is printed.
  - `layer1_outcomes(claims: list[LabelledClaim]) -> dict[str, list[str]]`: key `claim text|refs`, value the sorted failing rule names.
  - Script `scripts/layer1_diff.py --base <git-ref> [--extra probes.jsonl]`:
    1. creates a temporary `git worktree` at `<git-ref>` in the scratch folder;
    2. runs `layer1_outcomes` there with `uv run`, then here;
    3. prints every claim whose pass or fail changed, with its label;
    4. removes the worktree;
    5. exits with code 1 if any unsupported claim newly passes.
- [ ] **Step 1: Failing tests:**
  - `test_probe_claims_dev_only`: no `profile_id` in `P1_TEST_PROFILES`.
  - `test_probe_claims_deterministic`: the same list on two calls.
  - `test_outcomes_shape`: a known supported dev claim maps to `[]`, and a known wrong-number dev claim maps to a list containing `"metrics"`.
- [ ] **Step 2:** Run and see FAIL. **Step 3:** Implement. **Step 4:** Run `uv run python scripts/layer1_diff.py --base HEAD`. Expected: "0 changed". Turn on the matching `xfail` from Task 3.
- [ ] **Step 5:** Commit: `test: add layer 1 before and after diff tool`.

Tasks 5 to 8 each end with the same gate, called **"Layer 1 gate"** below:
- run `uv run python scripts/layer1_diff.py --base <commit before the task> --extra <task probes>`. Expected: exit 0, and every newly passing claim is listed in the commit body as checked by hand;
- a fresh reviewer (spec compliance against `cv-builder-invariants` and the task), with review rounds until it approves. Each false-accept path a reviewer finds becomes a regression test before the fix.

**Deviation from spec 7 step 5 (owner approved 2026-11-06):** the generated probe set is 946 distinct claims plus the 125 dev claims, not about 10,000. More seeds only add duplicates, because the templates allow few distinct mutations. To make up for it, each Layer 1 task commits at least 40 probes aimed at its own rule, at least half of them unsupported, to `experiments/p1-layer1/probes/task-<n>.jsonl` (dev profiles only), and passes them as `--extra`. The gate output goes to `experiments/p1-layer1/task-<n>-diff.txt`. `experiments/p1-layer1/RESULTS.md` records the deviation and each gate's counts.

**Order change (owner, 2026-11-06):** Task 5 runs after Task 8 and before the Task 8 milestone. The step 1 search found no failing claim phrase in the dev run records, but the owner saw the failure in the live demo. The cause is the extracted fact wording "Studied 43007 Advanced Artificial Intelligence.", where the code is not the first evidence token, so `_is_identifier` reads it as an unbound number. The ground truth wording "43007 Advanced Artificial Intelligence" passes. Task 5 starts from a failing unit test against the extracted wording.

### Task 5: Subject codes (spec 7.1)

**Files:** Modify `src/evident/validation/layer1/numbers.py` (`_is_identifier`). Test `tests/validation/layer1/test_numbers.py`.

**Interfaces:** `_is_identifier(norm_claim, number_text, start, end, evidence, titles: list[str]) -> bool`. `titles` holds the normalised titles of the cited education facts, passed from `find_numbers` (new keyword argument `titles: list[str] = []`, filled by `check_metrics` from cited facts with kind `education`).

- [ ] **Step 1: Reproduce.** Search `experiments/a3-slice/runs/*.json`, `var/` run records and the planner's cached dev replies for Layer 1 failures whose phrase is a 4 to 6 digit number. Write each real failing form as a test that expects no metric failure. If nothing reproduces, stop and report to the owner before changing code.
- [ ] **Step 2: Add these tests:**
  - Expected to pass: "Advanced Artificial Intelligence (43007)" and "subject 43007 Advanced Artificial Intelligence", citing the 43007 education fact.
  - Expected to fail with `metrics` (unbound):
    - "covered 1200 survey responses" citing a fact whose description has "1,200 survey responses" but no metric record;
    - "43007 responses" citing the 43007 fact;
    - "43008 Advanced Artificial Intelligence" citing the 43007 fact;
    - the code next to only one title word ("43007 Advanced").
- [ ] **Step 3:** Run, and see the "pass" tests fail. **Step 4:** Implement the rule from spec 7.1:
  - the number is a whole token of a cited education title;
  - at least two of that title's other words are adjacent to it in the claim, before or after, in title order, with brackets and the words "subject" or "unit" allowed in between.
- [ ] **Step 5:** Run the full suite. Then the **Layer 1 gate**. Commit: `fix: accept subject codes next to their cited title`.

### Task 6: Sentence-start entities (spec 7.2)

> **Status: reverted on 2026-11-07 (owner decision, P9).** Three review rounds (49e9317, ac3ca43, 262f0d7) each found a new false-accept path: an opener dropped after a bullet, dash or line break left a single unchecked word; a digit-led word passed as a figure; a leftover word matched lowercase prose (a whole run matching prose, "The Answer", was found while writing round 2 probes); a leftover of two or more words matched lowercase prose. The Layer 1 source (`checks_scope.py`, `config.py`, `config/lexicons.toml`) is back to its 4478384 version through a new commit. History is not rewritten. Every test and probe that asserts a rejection is kept. Cases the 4478384 code accepts are strict xfails that name the limitation. The gate tool changes (standing probes, `--report` in UTF-8) stay. The sentence-start entity gap stays a documented limitation, covered by the Layer 2 judge. A future attempt starts from a stricter design: every capitalised word in the claim must appear in the evidence. Gate after the revert: 0 changed claims against v0.1-a3 and 4478384 (`experiments/p1-layer1/RESULTS.md`). The steps below are kept as the record of what was tried.

**Files:** Modify `src/evident/validation/layer1/checks_scope.py` (`_name_runs`, `check_entities`) and `config/lexicons.toml` (new `sentence_openers` list, `version = "2"`). Modify `layer1/config.py` (`Lexicons.sentence_openers: frozenset[str]`). Test `tests/validation/layer1/test_checks_scope.py`.

- [ ] **Step 1: Failing tests:**
  - Rejected with `entities`:
    - "Goldman Sachs backed the planner.";
    - "• Goldman Sachs backed the planner";
    - "Built it; Goldman Sachs backed the planner.";
    - "Built it.\nGoldman Sachs backed it."
  - Still pass:
    - "Built the Team Course Planner with Python." citing that project;
    - "Led the Fictional Robotics Society showcase." where the name is in the evidence;
    - "The Team Course Planner cut clash checks to under 2 seconds." (the opener "The" is dropped).
  - The existing A3 entity tests stay green.
- [ ] **Step 2:** Run and see FAIL. **Step 3:** Implement:
  - the first word of a sentence, bullet or clause after a semicolon is dropped only if it is in `sentence_openers`;
  - the list holds every `ownership` and `deployment` lexicon key, these action verbs ("Developed", "Designed", "Wrote", "Created", "Tested", "Completed", "Enrolled", "Studied", "Volunteered", "Supported", "Worked", "Joined", "Evaluated", "Analysed", "Analyzed", "Added", "Logged", "Profiled", "Used"), determiners and pronouns ("The", "A", "An", "This", "That", "These", "Our", "My", "Her", "His", "Their", "It", "She", "He", "They", "I", "We").
  - Each opener added during dev is listed in the commit body with the dev claim that needed it.
- [ ] **Step 4:** Run the full suite, and count supported dev claims that now fail Layer 1 against before (from the diff output). Write the count in the commit body.
- [ ] **Step 5:** **Layer 1 gate.** Commit: `fix: keep unknown sentence openers in entity name runs`.

### Task 7: Lower-is-better metrics round away from zero (P8)

**Files:** Modify `src/evident/validation/layer1/checks_refs.py` (`_within`) and `config/lexicons.toml` (new `lower_is_better = ["latency", "cost", "error_rate"]`, `version = "3"`: Task 6 used "2" and was reverted to "1", so "2" is not reused). Modify `layer1/config.py`. Test `tests/validation/layer1/test_checks_refs.py`.

**Interfaces:** `_within(mention: NumberMention, record: MetricRecord, lower_is_better: frozenset[str]) -> bool`.

- [ ] **Step 1: Failing tests**, with the record `metric="latency", direction="absolute", value=2.0, unit="seconds"`:
  - `test_lower_is_better_old_false_accepts_now_fail`: "Clash checks run in 1 second" and "Clash checks take 0.5 seconds" each give one `metrics` failure with "beyond" in the detail (the owner asked for these two cases).
  - `test_lower_is_better_equal_or_higher_passes`: "Clash checks run in 2 seconds" and "in about 3 seconds" pass.
  - `test_decrease_record_still_rounds_toward_zero`: the existing `test_round_toward_zero_only` stays unchanged and green.
  - `test_units_that_differ_fail_closed` (Review Focus 2): "under 2,000 ms" and "1500 ms" against the 2 seconds record never pass. "2s" either binds and passes or fails; assert only that "1s" and "0.5s" fail.
  - The same pair for `error_rate` (absolute, percent): 5% recorded, a claim of 3% fails and 5% passes.
- [ ] **Step 2:** Run and see FAIL. **Step 3:** Implement: for an `absolute` record whose metric is in `lower_is_better`, pass only if the claim keeps the sign and `abs(mention.value) >= abs(record.value)`. Every other case is unchanged.
- [ ] **Step 4:** Full suite. **Layer 1 gate** (here a newly *failing* supported claim is expected and listed; a newly passing one must not exist). Commit: `fix: round lower-is-better absolute metrics away from zero`.

### Task 8: Direction word with "to" states an end value (spec 7.3, P7)

**Files:** Modify `src/evident/validation/layer1/checks_refs.py` (`_candidates`). Test `tests/validation/layer1/test_checks_refs.py`.

**Interfaces:** `_end_value_phrase(norm: str, mention: NumberMention, lex: Lexicons) -> bool`: true when the words before the number, inside the window, are a direction word, then optional words, then "to", then optionally one of "under", "below", "less than", "over", "above", "more than", and then the number.

- [ ] **Step 1: Failing tests:**
  - Passes: "Cut timetable clash checks to under 2 seconds" citing the profile 01 record (`latency, absolute, 2 seconds`). This is the A3 issue 3 claim.
  - Fail with `metrics`:
    - "Cut timetable clash checks to under 1 second" (beyond, by Task 7);
    - "Cut timetable clash checks by 2 seconds" (no `decrease` record: unbound);
    - "Raised test coverage to 90%" citing profile 04's `coverage absolute 80%` (beyond).
  - Passes: "Raised test coverage to 80%" citing that record.
  - Ambiguous (`metrics`, "ambiguous"): a fact with both a `decrease` 2 seconds latency record and an `absolute` 2 seconds latency record, with the claim "cut ... to 2 seconds".
- [ ] **Step 2:** Run and see FAIL. **Step 3:** Implement: when `_end_value_phrase` is true, the direction filter keeps records whose direction is the word's direction *or* `absolute`.
- [ ] **Step 4:** Full suite. **Layer 1 gate.** The A3 RESULTS file is not edited. Task 10 records this fix in `experiments/p1-judge-dev/RESULTS.md`. Commit: `fix: bind direction words with an end value to absolute metrics`. **Milestone: tell the owner it is a good time to push.**

### Task 9: Local 8B judge candidate

**Files:** Modify `config/models.toml` (add `[roles.judge_candidate]` and the digest), `src/evident/settings.py` (`Role.judge_candidate`), `src/evident/models/ollama.py` (`think` option). Test `tests/models/test_ollama.py`, `tests/test_settings.py`.

**Interfaces:**
- `RoleConfig.think: bool | None = None`, read from an optional `think` key in models.toml. The Ollama body sends `"think": rc.think` only when it is not None.
- `[roles.judge_candidate]`: provider `ollama`, model `qwen3:8b-q4_K_M`, `timeout_s = 30`, `max_output_tokens = 512`, `think = false`. `[ollama_digests]` gets `"qwen3:8b-q4_K_M" = "500a1f067a9f"`, and a price entry of 0, matching qwen3:4b.
- `validate_claim(..., judge_role: Role = Role.judge)`, so the comparison can send the judge call to the candidate role without changing the default path.

- [ ] **Step 1: Failing tests:**
  - `test_think_false_sent_when_configured` (fake HTTP, assert `body["think"] is False`);
  - `test_think_absent_by_default`;
  - `test_judge_candidate_role_loads`;
  - `test_digest_mismatch_refused` for the new tag (reuse the existing digest test helper).
- [ ] **Step 2:** Run and see FAIL. **Step 3:** Implement.
- [ ] **Step 4: Fit check (manual, recorded):**
  - `ollama pull qwen3:8b-q4_K_M`, then `ollama list`. Expected: ID `500a1f067a9f`. If it differs, stop and ask.
  - Run one judgement on a dev claim through `validate_claim(..., judge_role=Role.judge_candidate)`, then `ollama ps`. Record the load time, the call time and the CPU/GPU split.
  - If the call needs over 30 s once warm, stop and report: the candidate is not eligible.
- [ ] **Step 5:** Full suite, ruff, mypy. Commit: `feat: add local qwen3 8b judge candidate`.

### Task 10: Judge comparison on dev (spec 5)

**Files:** Create `src/evident/eval/judge_compare.py`, `scripts/compare_judges.py`, `experiments/p1-judge-dev/RESULTS.md`, `experiments/p1-judge-dev/runs/*.json`. Modify `src/evident/validation/judge.py` (`JUDGE_THRESHOLD` only if a new one is chosen), `config/models.toml` (`roles.judge` only if the candidate wins), `docs/decisions-proposed.md` (P6). Test `tests/eval/test_judge_compare.py`.

**Interfaces:**
- `@dataclass(frozen=True) class Judged: claim_id: str; label: Literal["supported", "unsupported"]; layer1_passed: bool; verdict: Verdict | None; confidence: float | None; error: str | None; ms: int`
- `judge_all(claims, adapter, role: Role, warmup: LabelledClaim) -> list[Judged]`: one warm-up call first. Its time and result are kept in the run record under `warmup` and are not counted.
- `sweep(judged: list[Judged], thresholds: Sequence[float]) -> list[SweepRow]`: uses `outcome.decide`, with no model calls. `SweepRow` has `threshold`, `false_accepts`, `false_rejects`, `review_supported`, `review_unsupported`, `errors`, each a `Rate`.
- `choose(rows_by_model: dict[str, list[SweepRow]], p90_ms: dict[str, float]) -> Choice | None`: applies spec 5.2 rules 1 to 4 exactly. Supported review ≤ 9/60 and p90 ≤ 20,000 ms. `None` means no change.

- [ ] **Step 1: Failing tests:**
  - `test_sweep_counts_with_decide`: hand-built `Judged` lists give known counts at 0.5 and 0.9.
  - `test_choose_requires_zero_false_accepts`.
  - `test_choose_review_cap_blocks_gaming`: a threshold that moves every reject to review is not chosen.
  - `test_choose_tie_falls_back_to_current`: equal rows keep `qwen3:4b-instruct-2507-q4_K_M` at 0.80.
  - `test_timeout_counts_as_error_not_pass` (Review Focus 1): a `Judged` with `error="timeout"` gives `user_review`, and is counted in `errors`.
  - `test_slow_p90_ineligible`.
  - `test_compare_script_calls_require_dev` (turns on the Task 3 `xfail`).
- [ ] **Step 2:** Run and see FAIL. **Step 3:** Implement. The script:
  1. loads `load_p1_dev_claims()` and calls `require_dev`;
  2. runs `judge_all` for `Role.judge` and `Role.judge_candidate` (cached replies allowed for the 4B, since its cache keys hold the digest);
  3. writes `runs/dev_<model>.json` with every `Judged`, then sweeps 0.50 to 0.95 in steps of 0.05;
  4. prints the choice.
- [ ] **Step 4:** Run `uv run python scripts/compare_judges.py`. Write `experiments/p1-judge-dev/RESULTS.md`:
  - selection rules (copied from spec 5.2, stated as fixed before the run);
  - for each model: rates with numerator/denominator, p50, p90 and n of time, GPU/CPU split;
  - the full threshold table and the choice;
  - the Layer 1 fix summary from Tasks 5 to 8;
  - limitations (same family, small dev set, uncalibrated confidence).
- [ ] **Step 5:** Apply the choice:
  - if it's the 8B, set `roles.judge` to it (with `think = false`);
  - if it's a new threshold, set `JUDGE_THRESHOLD` (comment: "chosen on phase 1 dev, see experiments/p1-judge-dev/RESULTS.md");
  - fill in P6.
  - If no pair is eligible, change nothing and say so in RESULTS and P6.
- [ ] **Step 6:** Full suite, ruff, mypy. Fresh reviewer (validation territory). Commit: `feat: choose judge model and threshold on phase 1 dev`. **Milestone: tell the owner it is a good time to push.**

### Task 11: Planner prompt v2 (spec 6, P5)

**Files:** Create `src/evident/prompts/planner/v2.txt`. Modify `src/evident/planning/planner.py` (`PLANNER_PROMPT_VERSION = "v2"`, `load_prompt("planner", PLANNER_PROMPT_VERSION)`, feedback rendering, coverage warning). Test `tests/planning/test_planner.py`.

**Interfaces:**
- `PLANNER_PROMPT_VERSION: str = "v2"` in `planner.py`. Reports read it the way they read the judge version.
- `missing_sections(plan: ContentPlan, facts: list[FactVersion]) -> list[str]`: returns `"Skills"` if a confirmed skill fact exists and no plan claim has section `Skills` (case-insensitive), and `"Coursework"` in the same way for confirmed education facts other than the degree. The degree fact is the one whose title starts with "Bachelor", "Master" or "Diploma"; the rest are subjects. `build_plan` logs `"plan missing sections=%s"` (names only, no text), and the run record stores the list.

- [ ] **Step 1: Failing tests:**
  - `test_v2_prompt_asks_for_skills_and_coursework`: the rendered prompt contains the fixed instruction lines from v2.
  - `test_feedback_only_inside_evidence_tag` (P5): in a second planning round, every feedback entry's text lies between the `<evidence>` and `</evidence>` that follow the fixed line "Earlier claims rejected by validation, with the reasons:", and nowhere else.
  - `test_deck_instruction_present` (P5).
  - `test_missing_sections_detects_absent_skills`.
  - `test_no_coursework_facts_no_demand` (Review Focus 5): with no subject facts, `missing_sections` doesn't list "Coursework". With no confirmed skill facts, the rendered prompt has a line saying "no confirmed skill facts: leave the Skills section out", and the fake adapter's plan without a Skills claim gives `[]`.
  - `test_planner_uses_v2`: the prompt version in the model call is `v2`.
  - The existing planner tests stay green, including `test_feedback_phrase_cannot_fake_extra_reasons`.
- [ ] **Step 2:** Run and see FAIL. **Step 3:** Write `v2.txt` as a copy of `v1.txt` with three changes:
  - the feedback moves into its own `<evidence>` block, after the fixed line;
  - one instruction: "Always include at least one claim with section Skills that cites confirmed skill facts, and at least one claim with section Coursework that cites confirmed subject or coursework education facts. If no such confirmed facts exist, leave that section out. Never write a claim the cited facts do not support.";
  - the P5 deck instruction from `docs/decisions-proposed.md`, word for word.
  Then implement the code changes.
- [ ] **Step 4: Dev check (live, Flash-Lite):** for profiles 01 to 05 (`require_dev`), with job ads from `jobs.jsonl` in order, run `plan_and_validate`. Expect about 10 to 20 Flash-Lite calls, checked against the quota guard first. Record per profile:
  - whether a Skills and a Coursework claim exist;
  - their outcomes;
  - whether the deck was filled without the fallback.
  Results go in a "Planner v2 (dev)" section of `experiments/p1-judge-dev/RESULTS.md`.
- [ ] **Step 5:** Full suite, ruff, mypy. Fresh reviewer (prompts and untrusted content). Commit: `feat: planner v2 adds skills and coursework claims`.

### Task 12: Photo receipts from OCR word positions (spec 8)

**Files:** Modify `src/evident/ingestion/vision.py`. Test `tests/ingestion/test_vision.py`.

**Interfaces:**
- `ocr_words(image: bytes) -> list[OcrWord]`, where `OcrWord` is `@dataclass(frozen=True)` with `text: str` and `box: tuple[float, float, float, float]`. It uses `pytesseract.image_to_data` on the whole image, upscaled by `OCR_UPSCALE` with boxes mapped back to original pixels, and is called once per photo.
- `word_matches(words: list[OcrWord], span_text: str) -> list[tuple[float, tuple[float, float, float, float]]]`: (score, union box) for each non-overlapping window of words scoring ≥ `VERIFY_THRESHOLD` with `span_score`.
- `agrees(ocr_box, model_box, margin_px: float, min_inside: float) -> bool`: the share of the OCR box's area inside the model box, enlarged by `margin_px`, is at least `min_inside`.
- `WORD_BOX_MARGIN_PX = 12.0` and `WORD_BOX_MIN_INSIDE = 0.5` as starting values. Task 13 tunes them on dev, and `ingest_photo` reads them.
- `ingest_photo` order: the crop check first (unchanged). If it fails and a model box exists, word matches; accept only if exactly one match exists and it `agrees`. The stored `bbox` is the OCR union box, with `bbox_verified=True` and `confidence=score/100`. A log line `"box verified by=%s"` with `crop` or `words` (no text).

- [ ] **Step 1: Failing tests** (rendered fixtures like the existing `page_png` and `list_png`):
  - `test_word_positions_verify_when_crop_fails`: a model box slightly offset so the crop check fails, but the span's words lie mostly inside it. Expect verified, with the stored box equal to the OCR union.
  - `test_word_positions_reject_far_box`: a model box on a different line. Not verified, whole image.
  - `test_repeated_span_falls_back` (Review Focus 3): "Python" appears twice. Not verified.
  - `test_short_span_whole_word_in_words_path`: "Git" doesn't match "GitHub".
  - `test_crop_path_unchanged`: the existing verified-box tests stay green, with the box exactly the checked region.
  - `test_no_model_box_no_word_path`: a missing `box_2d` still falls back to the whole image, so word positions alone never place a receipt.
- [ ] **Step 2:** Run and see FAIL. **Step 3:** Implement.
- [ ] **Step 4:** Full suite, ruff, mypy. Fresh reviewer (receipts). Commit: `feat: verify photo receipt boxes from OCR word positions`.

### Task 13: Receipt dev check and A3 re-analysis

**Files:** Create `scripts/receipts_dev.py`, `experiments/p1-judge-dev/receipts_contact_sheet.html` (synthetic data only, so it is committed). Modify `experiments/p1-judge-dev/RESULTS.md`. Test `tests/scripts/test_receipts_dev.py`.

**Interfaces:** `receipt_stats(profile_ids: Sequence[str], use_word_path: bool) -> ReceiptStats` (`verified_crop`, `verified_words`, `facts_with_span`, `items`), using only cached extraction replies. It refuses an uncached call (`CacheOnlyAdapter`, as in demo mode) and calls `require_dev` unless invoked by the locked run.

- [ ] **Step 1: Failing tests:** `test_cache_only_refuses_live_call`, `test_require_dev_called`, `test_stats_on_fixture` (with a fake adapter and a rendered fixture).
- [ ] **Step 2:** Run and see FAIL. **Step 3:** Implement.
- [ ] **Step 4:** Run on all 15 dev photos:
  - with `use_word_path=False`: the A3 re-analysis, labelled as such;
  - with `use_word_path=True`: write a contact sheet of every word-path box (crop with margin, span text under it) and check each by hand.
  - Tune `WORD_BOX_MARGIN_PX` and `WORD_BOX_MIN_INSIDE` on these 15 photos only, choosing the setting with 0 wrong boxes and the most verified. Record the grid and the choice.
  - Any wrong box at the chosen setting blocks the task.
- [ ] **Step 5:** Commit: `test: measure photo receipt verification on dev`. **Milestone: tell the owner it is a good time to push.**

### Task 14: Locked-run runner for phase 1

**Files:** Modify `src/evident/eval/runner.py` (`EXTRACTION_PROFILES["p1_test"]`, `EvalOptions.phase`, planner and receipt suites), `src/evident/eval/results.py` (side-by-side table), `scripts/run_eval.py` (`--phase p1`, `--locked-run`). Test `tests/eval/test_runner.py`, `tests/eval/test_results.py`.

**Interfaces:**
- `EvalOptions.phase: Literal["a3", "p1"] = "a3"`. With `p1` and split `test`:
  - extraction runs on `P1_TEST_PROFILES`;
  - grounding loads `load_p1_test_claims(locked_run=True)`;
  - a `planner` suite runs `plan_and_validate` per profile with job ads from `jobs.jsonl` in order;
  - a `receipts` suite runs `receipt_stats(P1_TEST_PROFILES, True)` after extraction, reading that run's own vision replies.
- `--locked-run` is required for `--phase p1 --split test` and refused otherwise. The run refuses to start unless:
  - `git status --porcelain` is empty;
  - the SHA-256 of `P1_TEST_CLAIMS` matches the one written in `experiments/p1-heldout/RESULTS.md`;
  - the RESULTS file's criteria section already names the judge model, threshold and planner version.
- `side_by_side(a3_summary: dict, p1_summary: dict) -> str`: a markdown table with rows for every measure both have, columns "A3 test (profiles 02 to 05 / 03 to 05)" and "Phase 1 test (06 to 10)", each cell `k/n (rate, 95% upper)` or the F1 and interval.

- [ ] **Step 1: Failing tests:**
  - `test_locked_run_flag_required`;
  - `test_refuses_dirty_tree` (monkeypatched git);
  - `test_refuses_claim_hash_mismatch`;
  - `test_refuses_missing_choices_in_results`;
  - `test_p1_dev_runs_use_dev_profiles_only`;
  - `test_side_by_side_rows`, with fixed summaries giving the exact table text for one rate row and one F1 row;
  - `test_planner_suite_counts_missing_sections`.
- [ ] **Step 2:** Run and see FAIL. **Step 3:** Implement. **Step 4:** Dry run on dev: `uv run python scripts/run_eval.py --phase p1 --split dev --suite all`. Expected: completes, writes a dev run record, and the quota pre-flight shows the planned call count. Turn on any remaining `xfail` from Task 3.
- [ ] **Step 5:** Full suite, ruff, mypy. Fresh reviewer (evaluation harness, split guard). Commit: `feat: add phase 1 locked run and side by side report`.

### Task 15: Locked run

**Files:** Modify `experiments/p1-heldout/RESULTS.md`. Create `experiments/p1-heldout/runs/test_all.json`.

- [ ] **Step 1:** Fill in the criteria section's model choices: the judge model and digest, the threshold and the planner version from Tasks 10 and 11. Commit: `docs: record phase 1 model choices before the locked run`.
- [ ] **Step 2:** Pre-flight: `ollama list` digests match `config/models.toml`; the Gemini quota for the day covers the planned calls (printed by the runner); the tree is clean.
- [ ] **Step 3:** Run `uv run python scripts/run_eval.py --phase p1 --split test --suite all --locked-run --write-results` once.
- [ ] **Step 4:** Check that RESULTS.md has:
  - every criterion with pass or fail, and every rate with numerator/denominator and its bound;
  - the side-by-side table with A3;
  - model IDs, digests, prompt versions, dataset version, lexicon version, cache hits, calls and estimated cost, and judge time p50, p90 and n;
  - limitations (spec 10.4, same-family judge, synthetic data, the 2% target not shown).
  Hand-write a short "What changed" paragraph that states fails plainly. Nothing is rerun or tuned after this run, whatever the result.
- [ ] **Step 5:** Commit: `docs: report phase 1 locked run on profiles 06 to 10`. **Milestone: tell the owner it is a good time to push, and that the plan is finished.** Then follow `superpowers:finishing-a-development-branch` (merge locally or leave the branch; never push).
