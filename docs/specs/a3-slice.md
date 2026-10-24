# A3 slice: spec

- **Status:** approved 2026-10-24. Changes at approval:
  - submission pack (section 12a) and explainers (section 12b) added;
  - free-tier-only models (P3), with the quota rules in section 7.3;
  - demo-first order (section 12).
- **Revised 2026-10-25 (owner request):** model setup replaced. Gemini 3.5 Flash-Lite serves every Gemini role, a local Qwen3 4B judge runs through Ollama (P1 rewritten), Gemini 3.8 Flash is a spare only, free-tier limits are known, and a recorded-run demo mode is added (section 10.1).
- **Date:** 2026-10-24. Demo due Wednesday 2026-10-28.
- **Implements (thin versions of):** design sections Pipeline, Data model, Grounding and validation, Deterministic check rules, Coverage matching, Evidence receipts, Prompts, Evaluation harness, Models and fallbacks, Mapping to the 43007 A3 submission.
- **Invariants touched:** `cv-builder-invariants` sections 1 (grounding), 2 (contracts), 4 (untrusted content, logging) and 5 (evaluation). Section 3 (job queue) and the RLS and roles parts of section 4 are out of scope, as listed below.
- **Decisions in force:** P1 (local open-weights judge, with a same-family fallback if its smoke test fails), P2 (Playwright PDF) and P3 (free-tier Gemini 3.5 Flash-Lite for every Gemini role) in `docs/decisions-proposed.md`.

Items marked **[my call]** are defaults I chose that you have not explicitly decided. Everything else comes from your instructions or the design.

## 1. Intent

A thin, working, end-to-end version of the CV Builder for the 43007 A3 demo. It goes from a CV (digital PDF or phone photo) and a job ad (text or screenshot) to a validated visual profile PDF and interview deck, where every claim links back to its source and an inflated claim is visibly rejected.

The slice is the start of the real system, not a prototype to throw away. It uses the design's contracts and the `src/evident/` layout. Phase 0 resumes after the demo.

## 2. Goals

1. Ingest a CV as a digital PDF (pdfplumber text) or a phone photo (Gemini 3.5 Flash-Lite vision) into versioned facts with typed attributes and a source span.
2. Let the user confirm, edit or reject facts in a review page. Only confirmed facts flow downstream.
3. Grade a job ad's requirements against confirmed facts as strong, partial, weak or gap. Job ads come from `jobs.jsonl` text or, for one ad, a screenshot read by vision.
4. Plan claims, validate them with Layer 1 deterministic checks and a local different-family entailment judge, and route uncertain claims to user review.
5. Render a visual profile (HTML, then PDF via Playwright) and an interview deck (python-pptx), with each claim linked to its source.
6. Run post-render verification on the HTML.
7. Evaluate extraction F1 and claim false accepts, with numerator/denominator and the pass criteria written down before running.
8. Demo it all through a small local web UI.

## 3. Non-goals (until after 2026-10-28)

Postgres job queue, leases and fencing; RLS, database roles and auth; Redis; Gotenberg, PDF/UA and veraPDF; real consented CVs; the upload safety classifier; the prompt-injection suite; visual QA rubric and re-render loop; fairness suite; ATS CV; multi-job tailoring and stale-output alerts.

## 4. Anti-goals (failure even if the demo runs)

- A claim reaches an output without passing Layer 1, Layer 2 and post-render verification, or a claim that is uncertain or fails a check is shown as passed.
- An evaluation number is reported without its denominator, or measured on data that was used for tuning.
- The original A1 files in `data/synthetic/` are modified.
- A synthetic profile is shown outside the classroom without being marked synthetic. The A1 README requires this.
- Code that has to be rewritten rather than extended once Postgres, the queue and auth arrive.

## 5. Constraints

- Python 3.12, uv, Pydantic v2 strict, ruff, mypy strict, pytest, all as in CLAUDE.md. Test first for every invariant.
- Models (P1, P3), free tier only, with no paid usage:
  - `gemini-3.5-flash-lite` for text and vision extraction, job ad requirements (text and screenshot), coverage and planning. Checked against Google's model and pricing pages on 2026-10-25: stable, accepts images, supports structured output.
  - `qwen3:4b-instruct-2507-q4_K_M` (digest `0edcdef34593`) through the local Ollama server as the entailment judge, a different family from Gemini. If its smoke test fails, the judge falls back to `gemini-3.5-flash-lite` (P1).
  - `gemini-3.8-flash` is a spare for comparing quality on a few examples, only through an explicit comparison script. It is never in the default path.
  - Model IDs live in `config/models.toml`. No model name is written from memory.
- The Ollama judge is called over its local HTTP API with the standard library, so it adds no Python dependency.
- Only synthetic data is ever sent to Gemini, because free-tier content is used to improve Google's products (P3). The local judge sends nothing off the machine.
- Untrusted content (CV text, OCR and vision output, job ads) goes inside `<document>`, `<job_ad>` or `<evidence>` tags, using the design's shared system preamble. Models get no tools.
- Never log CV text, contact details or keys. Logs record IDs, stage, timing, token counts and cost only.
- Windows dev machine; commands must work in PowerShell.

## 6. Data

### 6.1 Enriched copy (decided by you)

- New folder `data/synthetic/a3_enriched/`, committed. The A1 files are never modified. A test checks that the SHA-256 of each A1 file is unchanged.
- **[my call]** How it's built: a hand-written overlay file, `a3_enriched/overlay.json`, keyed by `document_id`. A script, `scripts/build_enriched.py`, merges it with `student_profiles.jsonl` to produce `a3_enriched/profiles.jsonl`. The overlay is the only place fictional additions live, so they're easy to audit.
- Fields added, all fictional:
  - `start` and `end` (YYYY-MM, or `end: null` for ongoing) on every project and experience entry, realistic for a third-year student (2023 to 2026).
  - `ownership` (contributed, built, led) and `deployment` (concept, prototype, internal, production) on projects and experience, chosen to match the existing wording ("Built ..." becomes built; "Contributed to ..." becomes contributed).
  - 1 to 3 `metrics` per profile, as metric records (metric, direction, value, unit, subject, span_text). Each metric's `span_text` is also added to the matching description so it appears on the rendered CV. Figures stay modest and plausible, with a single value each, for example "cut timetable clash checks to under 2 seconds" (settled at plan approval: before-and-after pairs are left out to keep number binding simple).
- `a3_enriched/README.md` lists every added field, says plainly that all of it is fictional and was added for A3 testing, and points to the overlay file.

### 6.2 Rendered CVs and photos

- **[my call]** Three Jinja CV templates: a single-column classic, a two-column modern one with a sidebar, and a compact dense one. They differ in layout, section order and typography so extraction isn't tested on one layout. Rendered to PDF with Playwright. That gives 5 profiles × 3 templates = 15 digital CVs.
- Every rendered CV carries a visible "Synthetic profile, A3 testing" footer.
- **[my call]** Phone photos are simulated from page 1 of each PDF: perspective warp, slight rotation, uneven lighting, mild blur and noise, JPEG compression, at fixed seeds. That gives 15 photos. They're labelled as simulated in the evaluation, since they're easier than real phone photos. You can drop in a few real phone photos of printed CVs; the pipeline treats them the same way.
- Generated CVs and photos go in `data/synthetic/a3_enriched/rendered/` and are committed, so the evaluation is reproducible.

### 6.3 Ground truth

- **[my call]** A deterministic converter turns each enriched profile into its expected facts (the same contracts the pipeline produces). Ground truth lives in `a3_enriched/ground_truth/` and is never passed to the pipeline. A test checks that no pipeline module imports it.

### 6.4 Job ads

- The 9 ads in `jobs.jsonl` are used as text.
- **[my call]** For the screenshot path, one ad (`graduate_ai_engineer`) is rendered as a plain job-board-style page and captured as a PNG with Playwright. Vision reads it into requirements under the untrusted-content rules.

## 7. Architecture

```
src/evident/
  contracts/   facts, metrics, sources, coverage, plan, validation, outputs, documents
  ingestion/   pdf_text.py, vision.py, facts.py (span matching, fact assembly)
  coverage/    requirements.py, grading.py
  planning/    planner.py
  validation/  layer1/ (normalise, lexicons, one module per check), judge.py, post_render.py, pipeline.py
  models/      adapter.py (interface), gemini.py, cache.py, costs.py
  render/      templates/, profile_html.py, pdf.py, deck.py, receipts.py
  store/       repository.py (interface), files.py (JSON file store)
  web/         app.py, routes/, templates/
  eval/        extraction.py, grounding.py, metrics.py (Clopper-Pearson, bootstrap), datasets.py
scripts/       build_enriched.py, render_cvs.py, make_photos.py, screenshot_job.py, run_eval.py
experiments/a3-slice/RESULTS.md
config/        models.toml, lexicons.toml, aliases.toml
```

`coverage/` and `planning/` are not in the CLAUDE.md layout. The design's pipeline has those stages, so I've added them as packages. **[my call]**

### 7.1 Contracts

- Taken from the design's Data model: FactVersion, MetricRecord, the five source variants (only `pdf_text` and `vision` used in the slice), CoverageRow, ContentPlanClaim, plus Document, Requirement, ValidationResult, Output and Lineage. Pydantic v2 strict, explicit enums from the invariants, `schema_version` on every contract.
- **[my call]** `schema_version = "2.0"`, matching the design's example. Once you approve this spec, the contracts are frozen under the CLAUDE.md rule.
- All model JSON is validated against the contract before use. Invalid JSON gets one retry with the validation error included in the prompt, then the stage fails with an `internal` error; it never passes partial output.

### 7.2 Storage and execution

- **[my call]** A JSON file store under `var/` (gitignored), behind a `Repository` interface whose methods match what the Postgres version will need (get or put fact versions, never update in place; outputs record fact versions and claim IDs). Postgres plugs in behind the same interface later.
- **[my call]** No queue. Each pipeline run executes stages in order in a FastAPI background task and writes a stage status record that the UI polls. A stage's output is written only after its gate passes. Stage functions take and return contracts, so they move onto queue workers later unchanged.
- Fact edits create a new version (`supersedes`); outputs keep the fact versions they used.

### 7.3 Model adapter

- One `ModelAdapter` interface with `generate_json(role, prompt_version, parts, schema)`. Two implementations sit behind it: Gemini (google-genai) and Ollama (local HTTP API, standard library only). A router picks the implementation from each role's `provider` in `config/models.toml`.
- Timeouts from the invariants: text 30 s, vision 45 s. They apply to the local judge too. Max output tokens set per role.
- **[my call]** The Ollama adapter checks at startup that the configured tag resolves to the pinned digest. A mismatch or a stopped Ollama server is a judge error, which routes claims to user review (nothing auto-passes).
- **[my call]** A disk cache keyed by the hash of (model ID, prompt version, inputs), for both providers. It makes the demo work if the network is slow, makes the evaluation reproducible and feeds the recorded-run demo (section 10.1). Results always record whether a call came from cache.
- **[my call]** Every call logs token counts and an estimated cost at the model's paid list price (in `config/models.toml`, with the date checked). The actual cost is zero on the free tier. The local judge has an estimated API cost of zero; electricity isn't counted. The estimate gives a cost-per-output figure for the report and is reused by phase 0 experiment 4.
- **Free-tier quota (decided by you):**
  - **Limits** (AI Studio, Evident project, copied by the owner on 2026-10-25), in `config/models.toml`:
    - `gemini-3.5-flash-lite`: 15 RPM, about 250K TPM, 500 RPD;
    - `gemini-3.8-flash` (spare): 5 RPM, about 250K TPM, 20 RPD.

    A Gemini model with no limits in the config is refused for uncached calls (fail closed).
  - **Spacing.** Uncached Flash-Lite calls start at least 4.5 s apart (15 RPM allows 4 s). **[my call]** Spare calls start at least 13 s apart (5 RPM allows 12 s). This is pacing, not retrying.
  - **Quota guard.** One guard per Gemini model counts uncached calls per Pacific day, sized to that model's RPD (500 for Flash-Lite, 20 for the spare). Daily quota resets at midnight Pacific time per Google's docs. **[my call]** The guard uses UTC-8 all year, so its reset lands at or after Google's and it never assumes quota is back early. The local judge has no quota guard.
  - **[my call] TPM** isn't tracked. At 4.5 s spacing, at most about 13 calls start per minute, so a call would need an average of about 19K tokens to reach 250K. The largest call (coverage, or vision on one page image) is far below that. Token counts are logged, so this can be checked.
  - **Stopping.** It stops with a clear "daily quota reached" error before the RPD limit. A 429 from Google is reported the same way and never retried in a loop.
  - **Caching.** Every reply is cached on disk. Cache hits don't count against quota.
  - **Evaluation pre-flight.** Each evaluation run first counts the uncached Gemini calls it would need. If that exceeds the remaining daily quota, it stops before making any call and says how many calls are needed and how many are left.
  - **[my call] Keeping calls down:**
    - coverage grades all requirements of a job ad in one call (section 8.3);
    - planner limits are tightened (at most 10 profile claims and 4 deck slides), which keeps judge calls per run near 15 to 20.

    With the judge local, a demo run needs about 5 to 8 uncached Flash-Lite calls (ingestion, requirements, coverage, one or two planner rounds). The full evaluation needs 30 Flash-Lite calls for extraction (6 dev, 24 test) and about 125 local judge calls (40 dev, 85 test). It fits in one quota day. If the judge falls back to Flash-Lite (P1), those 125 calls count against quota too, which still fits under 500.

## 8. Pipeline stages

### 8.1 Ingestion (design: Pipeline 1, Evidence receipts)

- **Digital PDF:** pdfplumber extracts text and character boxes. Flash-Lite (text, extraction prompt from the design) splits the text into atomic facts with `span_text`. Each `span_text` is fuzzy-matched to the page text, and the matched characters' boxes are unioned into the bbox. A fact whose span can't be matched (match score below a threshold, **[my call]** 90) is kept but flagged "span not found" and can't be confirmed until edited or rejected. Gate: every fact has a span.
- **Photo:** Flash-Lite vision returns facts with a bbox. The bbox is verified by Tesseract OCR on the crop, fuzzy-matched to `span_text`. Unverified boxes fall back to the whole image, marked approximate (`bbox_verified: false`).
- Fact kinds: experience, project, education, certification, skill, award, per the design's extraction prompt.

### 8.2 User review (design: Pipeline 3)

- The review page shows each fact beside a crop of its source.
- Confirm, edit (creates a new version) or reject.
- **[my call]** A "confirm all low-impact facts" button covers the rest. Facts with dates, metrics, qualifications or ownership/deployment above "contributed"/"concept" always need a per-fact confirm, as the design requires for high-impact fields.

### 8.3 Coverage (design: Pipeline 4, Coverage matching, coverage grading prompt)

- Flash-Lite splits the job ad (text, or the screenshot by vision) into requirements with a category (required, preferred, responsibility, boilerplate). Boilerplate isn't graded.
- **[my call]** No embeddings or retrieval: a profile has about 10 to 25 confirmed facts, so the grader sees all of them. All requirements of one ad are graded in a single call to save free-tier quota (P3), with one row returned per requirement ID. Retrieval and per-requirement calls come in later with the real coverage stage.
- Gate: every graded requirement has a grade and cited fact versions, or an explicit gap. Cited fact IDs not in the confirmed list fail the gate.

### 8.4 Planner (design: Pipeline 5, content planner prompt)

- Flash-Lite builds claims for the two output types, each citing fact IDs and versions, with a section, an emphasis level and allowed transformations. No claims for gaps.
- Deck speaker-note narratives are derived claims and go through Layers 1 and 2 like any other claim.
- Rejected claims go back to the planner once with the rejection reason. **[my call]** At most 2 rounds; after that, the claim is dropped and the drop is listed in the validation report.

### 8.5 Claim validation (design: Grounding and validation, Deterministic check rules)

- **Layer 1**, model-free, one module per check, each with failing tests written first: fact IDs (exist, belong to the profile, confirmed), metrics (one binding, same metric, direction and unit, rounding toward zero only, ambiguous binding rejects), durations, dates, ownership, deployment, scale, skills (with aliases), aggregates, entities. Normalisation as in the design. Lexicons and aliases live in versioned config files.
- **Layer 2:** the local Qwen3 4B judge (P1) using the design's entailment prompt, returning `supported | overstated | unsupported`, the offending phrase, a corrected phrasing and a confidence. Ollama's JSON-schema output constrains the reply, and it is still validated against the contract. Every report names the judge model and states its limits: small, quantised, self-reported uncalibrated confidence, or the same-family limitation if the fallback is in use.
- **Outcome rules (table settled at plan approval):**

| Layer 1 | Judge | Outcome |
|---|---|---|
| pass | supported, confidence ≥ threshold | passed |
| pass | overstated or unsupported, confidence ≥ threshold | rejected |
| pass | any verdict below threshold, or judge error | user review |
| fail | overstated or unsupported, below threshold, or judge error | rejected |
| fail | supported, confidence ≥ threshold | user review (disagreement) |

  Nothing auto-passes.
- **[my call]** Confidence threshold starts at 0.8 and may be tuned only on the dev split (section 9). It is uncalibrated and reported as such.
- The UI shows claims in user review with both layers' reasons. The user can approve, edit (revalidated) or drop each one.

### 8.6 Renderers (design: Pipeline 7, Evidence receipts)

- **Visual profile:** Jinja HTML with user content escaped. Each claim is wrapped in an element with `data-claim-id`; clicking it opens a receipt popover with the claim, the fact version and the source crop from `/documents/{id}/source`. Converted to PDF with Playwright (P2). The PDF has a link annotation per claim to its receipt page in the local app. **[my call]** I'm including those links because "every claim linked to its source" covers the PDF too. If they're fiddly with Playwright's PDF output, I'll drop them and say so.
- **Interview deck:** python-pptx from a fixed template. Speaker notes list each slide's claim IDs, plus the source text and location for each.
- Both carry a "Synthetic profile" marker.
- Renderers never add factual text. Template copy (headings, labels) comes from a whitelist file.

### 8.7 Post-render verification (design: Grounding and validation, Layer 3)

- On the HTML: every element with `data-claim-id` must exactly match that claim's validated wording for this output (after whitespace normalisation only). Every other text node must be in the template whitelist. Any extra text, missing claim, unknown claim ID or changed wording fails.
- Failure blocks export of that output. The check reruns after any re-render.
- **[my call]** The PPTX gets a lighter check: every claim ID in the speaker notes exists in the validated plan, and every slide's body text appears in the validated claims or the whitelist. You asked only for HTML; I'm adding this because it's cheap. If time runs short it's the first thing I drop, and I'll say so.

## 9. Evaluation (design: Evaluation harness, Measurement rules)

Results go to `experiments/a3-slice/RESULTS.md`. Every rate is reported as numerator/denominator, along with model IDs, prompt versions, the dataset version (git hash of `a3_enriched/`), pass criteria stated before running, and pass or fail. These are pilot results on synthetic data and are labelled that way.

### 9.1 Extraction F1

- **Data:** 15 digital CVs and 15 simulated photos, all from **only 5 underlying profiles** (stated in the results, as you asked).
- **[my call] Split:** profile 01 (3 CVs and 3 photos) is the dev split, used for prompt fixes. Profiles 02 to 05 (12 CVs and 12 photos) are the test split, run once for the reported numbers.
- **[my call] Scoring:**
  - Predicted facts are matched to ground-truth facts within the same CV by kind plus fuzzy title or organisation match, one-to-one.
  - Field-level precision, recall and F1 over: kind, title/role, organisation, start, end, skills (each skill counts as one field), and metrics (value, unit and direction as one field).
  - Reported per extraction path (pdf_text, vision) and per template.
- **Intervals:** 95% bootstrap resampling whole underlying profiles. With 4 test profiles the interval is wide, and the results say so.
- **Pass criteria (from validation experiment 1, stated before running):** F1 ≥ 0.95 on digital PDFs and ≥ 0.90 on photos. A pass here doesn't establish the phase 0 result: the CVs are synthetic, the photos are simulated and there are only 4 test profiles.

### 9.2 Claim grounding (false accepts)

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

### 9.3 Cost and latency (by-product, no pass criterion)

Mean cost per output pair and p50/p90 stage latency over the demo runs, with n. These are reported as observations only.

## 10. Demo UI (decided: FastAPI + Jinja)

Plain server-rendered pages, no JavaScript framework. A little vanilla JS for the receipt popover and status polling.

1. **Start:** pick a synthetic profile CV (PDF or photo) or upload one, and pick a job ad (from the list, or the screenshot).
2. **Review facts:** each fact beside its source crop; confirm, edit or reject.
3. **Coverage:** the requirement table with grades and cited facts.
4. **Claims:** passed, rejected (with rule and phrase) and user-review claims. **[my call]** A "try an inflated claim" box lets you type a claim live and see it rejected, which covers the design's "validator rejecting an inflated claim" demo item.
5. **Outputs:** the profile HTML with clickable receipts, PDF and PPTX downloads, and the validation report (models used per role, judge limitations, post-render result).

Runs only on localhost. No auth, as auth is out of scope.

### 10.1 Recorded-run demo mode (decided by you, 2026-10-25)

- Before the presentation, you run the full pipeline once in the UI, so every model reply is in the disk cache and every stage's records are in the store. A script then marks that run as recorded.
- **[my call]** Marking writes a small manifest, `var/demo/recorded.json` (run ID, recorded date, model ID per role). It isn't a contract, so the frozen contracts don't change. The run's facts, coverage, plan, report and outputs stay in the store as they were.
- In demo mode (`EVIDENT_DEMO=1`), the UI opens on the recorded run and shows each stage instantly from stored records. Nothing in the pipeline reruns. Every page carries a visible banner: "Recorded run from <date>. Replayed from stored results; no models are called on this page."
- **[my call]** In demo mode, every role except the judge is cache-only. An uncached call for those roles fails with a clear "not in the recording" error instead of using quota. This protects the demo from accidental live calls.
- Only the "try an inflated claim" box calls models live: Layer 1 plus the judge on the claim you type. It is labelled "Live". With the local judge this uses no Gemini quota. If the judge has fallen back to Flash-Lite (P1), the box's judge call is the one allowed live Gemini call path in demo mode, through the normal quota guard.

## 11. Dependencies to approve

Approving this spec approves these. Nothing else gets added without asking. The local judge adds no Python dependency: it uses the Ollama server already installed, the pulled model `qwen3:4b-instruct-2507-q4_K_M` and the standard library's `urllib`.

- **Runtime:**
  - fastapi, uvicorn, jinja2, python-multipart (UI)
  - pydantic, pydantic-settings (contracts and config; keys come from `.env`)
  - google-genai (Gemini)
  - pdfplumber (text and boxes; brings pypdfium2 for page crops)
  - pytesseract (bbox verification; Tesseract is already installed)
  - rapidfuzz (span matching)
  - pillow, numpy (photo simulation and crops)
  - playwright, plus its Chromium download (PDF, screenshots)
  - python-pptx (deck)
  - scipy (Clopper-Pearson via the beta distribution)
- **Dev:** pytest, ruff, mypy.

## 12. Order of work and stretch stages

### Core, in order (demo first, decided by you)

1. **Sunday:**
   - scaffold, contracts, model adapter with quota guard, file store;
   - the local judge smoke test (speed and 10 obvious claims), which decides the judge before any task depends on it;
   - enriched data, rendered CVs, photos and job screenshot;
   - photo ingestion, then PDF ingestion;
   - the fact review UI.
2. **Monday, first half (rough end-to-end run):**
   - coverage;
   - planner;
   - claim validation core (fact ID check, judge, outcome rules);
   - rough renderers;
   - post-render verification;
   - the UI flow from photo upload to profile PDF and deck.

   It can look rough. **Milestone:** a full run in the UI by the end of Monday.
3. **Monday, second half:** the rest of Layer 1 (number classification, metrics, scale, aggregates, dates, durations, ownership, deployment, skills, entities).
4. **Tuesday, evaluation, polish and the submission pack only:**
   - evaluation metrics and runs;
   - polish (receipt popover, PDF claim links, PPTX check, styling);
   - recorded-run demo mode (section 10.1);
   - the submission pack (section 12a).

Wednesday morning is buffer. If Monday slips, the remaining Layer 1 checks take priority over everything on Tuesday except the evaluation, since the grounding evaluation depends on them. If anything has to go, the PDF claim links and PPTX check go first.

Each component's explainer (section 12b) is written as part of that component's step, not saved for the end.

### 12a. Submission pack (Tuesday; decided by you)

- **`examples/`:** one complete run, committed:
  - input CV photo;
  - extracted facts (JSON);
  - coverage matrix (JSON and a readable HTML or Markdown table);
  - validated profile PDF;
  - deck (PPTX);
  - validation report;
  - an inflated claim being rejected (the claim, the rule or judge verdict, the offending phrase);
  - a copy of the evaluation results.

  **[my call]** Generated by `scripts/build_examples.py` from a fixed profile and job ad, so it can be regenerated after any fix.
- **`README.md`:** exact Windows setup and run steps in PowerShell, covering:
  - installing uv, Tesseract and the Playwright browser;
  - `uv sync`;
  - creating `.env` from `.env.example`;
  - starting the UI, running the tests, running the evaluation and rebuilding the examples.

  It states that all data is synthetic.
- **`scripts/build_zip.py`:** builds the code zip from `git ls-files` plus the generated `examples/`, so gitignored files are never picked up. It also excludes by explicit rule `.env`, `.claude/`, `CLAUDE.md`, `data/private/`, `var/`, caches (`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, the model cache) and `.venv/`. It then scans every file in the zip for key-like strings: Google API key pattern `AIza[0-9A-Za-z_-]{35}`, generic `sk-` style keys, private key headers, `*_API_KEY=` with a non-empty value, and the actual value of each key in the local `.env`, compared in memory and never printed. Any hit deletes the zip and exits non-zero, naming the file and pattern but not the matched text. A test covers both a clean zip and one with a planted fake key. **[my call]** The zip is named `A3_Code_<GroupID>.zip` with the group ID passed as an argument, matching the submission file names in the design.
- **`docs/report-material.md`:** raw material for the report, not the report:
  - the architecture (text plus a diagram source);
  - the multimodal parts (PDF text, vision on photos and job ad screenshots, rendered outputs);
  - the exact prompts with their versions;
  - key code snippets to quote, with file and line references;
  - evaluation tables with numerator/denominator and intervals;
  - limitations (section 13);
  - which model handled each role.

### 12b. Component explainers (decided by you)

- One short Markdown file per component in `docs/explainers/`: contracts, ingestion (PDF), ingestion (vision), user review, coverage, planner, Layer 1 checks, judge, renderers and receipts, post-render verification, evaluation, demo UI, plus one per stretch stage if built.
- Each answers four questions in plain English:
  - what it does;
  - why it's built this way (citing the design section or decision);
  - how the model is used, or that it uses none;
  - its limits.

  Each also gives one example from the demo data, and is about a page long.
- Each component's step in the plan isn't done until its explainer exists and matches the code as built.

### Stretch stages

Optional; each starts only after the previous one is finished and tested.

- **S1. Interview rehearsal (audio):** questions from the coverage matrix, upload or record an answer, Flash-Lite transcription (audio input to be checked in Google's docs first) with timestamps, requirement coverage feedback using the design's rehearsal prompt. No comments on voice, accent, emotion or confidence.
- **S2. LinkedIn kit:** headline, About and experience entries from the same validated plan, with the same validation and post-render text check.
- **S3. Portfolio site:** static HTML site from the validated plan, with receipts using whole-source crops. Redacted crops are deferred, so it is shown locally only and never published.

Given four days, I expect the core plus perhaps S1. I'll tell you as soon as the core slips.

## 13. Limitations to state in the A3 report

- Small local judge: a 4B quantised Qwen3 model with self-reported, uncalibrated confidence (P1). If the smoke test forced the fallback, instead: same-family judge, the same Flash-Lite model as the planner.
- Free-tier Flash-Lite for planner and coverage instead of a Pro-class model; free-tier rate limits cap run counts (P3).
- The demo replays a recorded run; only the inflated-claim box runs live.
- Playwright PDF with no PDF/UA check (P2).
- Synthetic data from 5 profiles, with fictional enrichment.
- Simulated photos.
- Small samples, so even passes only bound the false accept rate near 6%.
- Uncalibrated judge threshold.
- No queue, auth, RLS or safety classifier.
- Prompt-injection resistance not evaluated.

## 14. Left to the builder

- Template visual design.
- Exact fuzzy-match scoring.
- Photo distortion parameters.
- Module internals.
- Test fixtures.
- Exact UI layout.

All of these stay within the contracts and invariants above.
