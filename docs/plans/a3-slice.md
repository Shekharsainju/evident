# A3 Slice Implementation Plan

> **For agentic workers:** Tasks 2, 12, 14, 16, 17 and 18 (`contracts/`, `validation/`, post-render verification) use superpowers:subagent-driven-development. A fresh implementer and a fresh spec-compliance reviewer check them against `cv-builder-invariants` and this plan. All other tasks, including 3a and 21a, use superpowers:executing-plans (native). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Revised 2026-10-25 (owner request):** model setup replaced (Flash-Lite for Gemini roles, local Qwen3 4B judge, 3.8 Flash spare only), known free-tier limits with 4.5 s spacing, a judge smoke test (Task 3a) and recorded-run demo mode (Task 21a).

**Goal:** A thin end-to-end CV Builder for the 43007 A3 demo, due 2026-10-28. It takes a synthetic CV (photo or PDF) and a job ad (text or screenshot), and produces a validated visual profile PDF and interview deck in which every claim links to its source. It also produces an evaluation with numerator/denominator.

**Architecture:** Typed Pydantic contracts flow through stage functions in `src/evident/`: ingestion, review, coverage, planner, validation, render and post-render. One model adapter interface routes each role to free-tier Gemini 3.5 Flash-Lite or to a local Ollama judge, with a disk cache and a per-model quota guard. A JSON file store sits behind a `Repository` interface so Postgres can replace it later. A FastAPI + Jinja UI runs the stages in background tasks.

**Tech Stack:** Python 3.12, uv, Pydantic v2 (strict), FastAPI, Jinja2, google-genai (`generate_content`), Ollama (local HTTP API via `urllib`), pdfplumber, pypdfium2, pytesseract, rapidfuzz, Pillow, numpy, Playwright (Chromium), python-pptx, scipy, pytest, ruff, mypy.

**Spec:** `docs/specs/a3-slice.md` (approved 2026-10-24, revised 2026-10-25). Decisions P1, P2 and P3 are in `docs/decisions-proposed.md`. Executors read the spec and the `cv-builder-invariants` skill before starting.

## Global Constraints

- Python 3.12; `uv` for everything; commands must run in PowerShell on Windows.
- Pydantic v2 with `strict=True` and `extra="forbid"` on every contract; `schema_version: Literal["2.0"]` on every contract.
- **Models:**
  - Free tier only, no paid usage, never suggest enabling billing.
  - `gemini-3.5-flash-lite` for `extraction_text`, `extraction_vision`, `requirements`, `coverage` and `planner`. Checked against ai.google.dev on 2026-10-25: stable, image input, structured output (P3).
  - `qwen3:4b-instruct-2507-q4_K_M` (digest `0edcdef34593`) via Ollama for `judge` (P1). If Task 3a fails, `judge` moves to `gemini-3.5-flash-lite` and the same-family limitation applies.
  - `gemini-3.8-flash` is a spare. No role maps to it; only `scripts/compare_spare.py` may call it, at the owner's request.
  - IDs come only from `config/models.toml`.
  - google-genai >= 2.3.0, using `client.models.generate_content` with `HttpRetryOptions(attempts=1)` (one request per call). The interactions API was dropped on 2026-10-25: it sent a hidden second request on every 429 or 5xx, and no public option stops it. Ollama through `POST /api/chat` with `urllib`, no new dependency.
  - Transient Gemini errors (5xx, 408, timeouts, connection errors) get at most 3 attempts with 2 s and 4 s backoff, each through the quota guard. A 429 is never retried.
  - Timeouts: text 30 s, vision 45 s, for both providers.
- **Quota (Gemini only):**
  - Every reply is cached on disk, for both providers.
  - Limits: Flash-Lite 15 RPM, 250K TPM, 500 RPD; spare 5 RPM, 250K TPM, 20 RPD.
  - Uncached Flash-Lite calls start at least 4.5 s apart; spare calls at least 13 s apart.
  - Uncached calls go through that model's quota guard, sized to its RPD, which stops before the daily limit with a clear error.
  - A 429 is reported, never retried in a loop.
  - A Gemini model without limits in `config/models.toml` gets no uncached calls at all.
  - Evaluation runs check their Gemini call count against the remaining quota before starting.
- Only synthetic data is sent to Gemini (P3).
- Demo mode (`EVIDENT_DEMO=1`) replays a recorded run; Gemini is cache-only and only the "try an inflated claim" box calls a model live.
- Untrusted content goes inside `<document>`, `<job_ad>` or `<evidence>` tags, after the shared preamble. Models get no tools.
- Never log CV text, contact details or keys. Logs carry IDs, stage, timings, token counts and estimated cost.
- The A1 files in `data/synthetic/*.jsonl` and `data/synthetic/README.md` are never modified.
- Every rendered CV and output carries the marker text `Synthetic profile, A3 testing`.
- Nothing auto-passes: a claim passes only under the outcome table in Task 12.
- **Writing style:** CLAUDE.md rules apply to code comments, docs, UI copy and commit messages:
  - no em dashes or double hyphens as punctuation;
  - conventional prefix and an imperative summary under 72 characters;
  - no emoji;
  - no AI attribution (project `attribution` settings are empty, and no trailer is ever typed by hand).
- Dependencies are limited to spec section 11. Ask before adding anything else.
- Work happens on branch `a3-slice`. Never push. Tell the owner at each milestone marked **Milestone** so they can push.
- Each component task ends with its explainer in `docs/explainers/`. The explainer answers what it does, why it's built this way, how the model is used and its limits, gives one demo-data example, and runs to about a page.

## Review Focus

1. **Numbers that are identifiers, not figures:** subject codes ("43007 Advanced Artificial Intelligence"), versions ("Python 3"). These must not be treated as metrics and rejected. Owned by Task 16.
2. **Ongoing roles** (`end: null`) in date and duration checks. They are measured to the `as_of` date. Owned by Task 18.
3. **Model output that is invalid JSON, or boxes in Gemini's `[ymin, xmin, ymax, xmax]` 0 to 1000 format.** The first gets one retry and then a clear stage error. The second converts correctly to pixel `[x0, y0, x1, y1]`. Owned by Tasks 3 and 7.
4. **User content with HTML characters** (`<`, `&`, quotes). It is escaped when rendered and still passes post-render verification. Owned by Tasks 13 and 14.
5. **Hitting the free-tier limit mid-run, or editing a fact after outputs exist.**
   - Quota: the run stops at a clear "daily quota reached" state with nothing half-written, and resuming later reuses cached replies.
   - Edits: a new fact version is created, and existing outputs keep the versions they used.

   Owned by Tasks 3, 4, 9 and 15.

## Schedule

- **Sunday 2026-10-25:** Tasks 0 to 9, including Task 3a (judge smoke test), which decides the judge before Task 12.
- **Monday 2026-10-26:** Tasks 10 to 15, ending at the **Milestone: rough end-to-end run in the UI**. Then Tasks 16 to 18.
- **Tuesday 2026-10-27:** Tasks 19 to 22, including 21a (evaluation, polish, demo mode, submission pack only).
- **Wednesday morning:** buffer.

If Monday slips, Tasks 16 to 18 come before anything else on Tuesday except Task 19, because the grounding evaluation needs them. If something must go, it is the PDF claim links and the PPTX check.

## File map

```
pyproject.toml, uv.lock, README.md
config/models.toml, config/lexicons.toml, config/aliases.toml, config/template_copy.toml
src/evident/
  settings.py, errors.py
  contracts/common.py, enums.py, facts.py, documents.py, coverage.py, plan.py,
            validation.py, outputs.py, runs.py
  prompts/__init__.py, prompts/<name>/v1.txt   preamble, extraction, requirements, coverage, planner, judge
  models/adapter.py, gemini.py, ollama.py, router.py, cache.py, costs.py, quota.py
  store/repository.py, files.py
  ingestion/drafts.py, vision.py, pdf_text.py
  review/actions.py
  coverage/requirements.py, grading.py
  planning/planner.py
  validation/layer1/config.py, run.py, checks_ids.py, normalise.py, numbers.py,
                    checks_refs.py, checks_scope.py
  validation/judge.py, outcome.py, post_render.py
  render/pdf.py, receipts.py, profile_html.py, deck.py, templates/profile.html.j2
  runs.py
  web/app.py, routes.py, demo.py, templates/*.html, static/app.js
  eval/datasets.py, metrics.py, extraction.py, grounding.py, results.py, budget.py
scripts/build_enriched.py, render_cvs.py, make_photos.py, screenshot_job.py, judge_smoke.py,
        run_eval.py, compare_spare.py, mark_recorded.py, build_examples.py, build_zip.py
data/synthetic/a3_enriched/{overlay.json, profiles.jsonl, README.md, templates/, ground_truth/, rendered/}
experiments/a3-slice/{RESULTS.md, JUDGE_SMOKE.md, judge_smoke_claims.jsonl,
                      claims_dev.jsonl, claims_test.jsonl, claims_review.md}
examples/, docs/explainers/*.md, docs/report-material.md
tests/ mirrors src/evident/, plus tests/fakes.py (FakeAdapter)
```

---

### Task 0: Branch and docs commit

- [ ] **Step 1:** `git switch -c a3-slice`
- [ ] **Step 2:** `git add docs/design.md docs/specs/a3-slice.md docs/plans/a3-slice.md docs/decisions-proposed.md`, then `git status --short`. Expected: only those 4 files staged.
- [ ] **Step 3:** `git commit -m "docs: add design markdown, A3 slice spec, plan and decisions"`

### Task 1: Scaffold, settings and model config

**Files:**
- Create: `pyproject.toml`, `config/models.toml`, `src/evident/{__init__,settings,errors}.py`
- Modify: `.gitignore` (add `var/`, `.cache/`, `dist/`, `*.zip`)
- Test: `tests/test_settings.py`

**Interfaces (Produces):**
- `Settings(BaseSettings)` with fields `gemini_api_key: SecretStr`, `ollama_url: str = "http://127.0.0.1:11434"`, `demo: bool = False` (env `EVIDENT_DEMO`), `data_dir: Path = Path("var")`, `cache_dir: Path = Path(".cache/models")`, `quota_dir: Path = Path(".cache/quota")` (one state file per Gemini model), `as_of: str = "2026-10"`, read from `.env`.
- `LOCAL_OWNER_ID = "local-demo"`.
- `Role` StrEnum: `extraction_text, extraction_vision, requirements, coverage, planner, judge`.
- `Provider` StrEnum: `gemini, ollama`.
- `load_model_config(path: Path = Path("config/models.toml")) -> ModelConfig` with:
  - `roles: dict[Role, RoleConfig(provider: Provider, model: str, timeout_s: int, max_output_tokens: int)]`;
  - `spare: list[str]`, models no role may use (`["gemini-3.8-flash"]`); loading fails if a role maps to one;
  - `prices: dict[str, Price(input_per_mtok: float, output_per_mtok: float, checked: str, source: str)]`, with 0.0 for the local judge;
  - `limits: dict[str, FreeTierLimits(rpm: int, tpm: int, rpd: int, min_interval_s: float, checked: str, source: str)]`, keyed by Gemini model ID;
  - `ollama_digests: dict[str, str]`, the pinned digest per Ollama tag.
- `ErrorCategory` StrEnum `validation, input, provider, internal`, and `StageError(Exception)` with `code: str, category: ErrorCategory, detail: str, retryable: bool`. Both live in `errors.py` and are re-exported from `contracts/enums.py` in Task 2.

- [ ] **Step 1:** Write `pyproject.toml`:
  - package `evident`, src layout, `requires-python = ">=3.12,<3.13"`;
  - dependencies from spec section 11, with `google-genai>=2.3.0`;
  - ruff with line length 100, `select = ["E","F","I","B","UP","SIM"]`;
  - mypy `strict = true`, with `ignore_missing_imports` for `pdfplumber`, `pypdfium2`, `pytesseract` and `pptx`;
  - pytest `testpaths = ["tests"]`, marker `live`, and `addopts = "-m 'not live'"`.
- [ ] **Step 2:** `uv sync ; uv run playwright install chromium`. Expected: both exit 0.
- [ ] **Step 3:** Write `config/models.toml`:
  - `extraction_text`, `extraction_vision`, `requirements`, `coverage` and `planner` use provider `gemini`, model `gemini-3.5-flash-lite`; `judge` uses provider `ollama`, model `qwen3:4b-instruct-2507-q4_K_M` (switched to Flash-Lite only if Task 3a fails). Timeouts 30 s, 45 s for `extraction_vision`;
  - `spare = ["gemini-3.8-flash"]`;
  - `[prices."gemini-3.5-flash-lite"]` is `input_per_mtok = 0.30`, `output_per_mtok = 2.50`; `[prices."gemini-3.8-flash"]` is `0.75` and `3.75` (through 2026-12-31); both `checked = "2026-10-25"` with the pricing URL. These are paid list prices, used for cost estimates only. The Ollama model's price is 0.0;
  - `[limits."gemini-3.5-flash-lite"]` is `rpm = 15, tpm = 250000, rpd = 500, min_interval_s = 4.5`; `[limits."gemini-3.8-flash"]` is `rpm = 5, tpm = 250000, rpd = 20, min_interval_s = 13.0`; both `checked = "2026-10-25"`, `source = "AI Studio rate-limit page, Evident project, copied by owner"`;
  - `[ollama_digests]` maps the judge tag to `0edcdef34593`.

  These IDs and prices were checked against the models and pricing pages on 2026-10-25.
- [ ] **Step 4: Failing tests:**

```python
GEMINI_ROLES = set(Role) - {Role.judge}

def test_gemini_roles_use_flash_lite():
    cfg = load_model_config()
    assert set(cfg.roles) == set(Role)
    assert {cfg.roles[r].model for r in GEMINI_ROLES} == {"gemini-3.5-flash-lite"}
    assert {cfg.roles[r].provider for r in GEMINI_ROLES} == {Provider.gemini}
    for role, rc in cfg.roles.items():
        assert rc.timeout_s == (45 if role is Role.extraction_vision else 30)

def test_judge_is_local_and_not_gemini_family():
    rc = load_model_config().roles[Role.judge]
    assert rc.provider is Provider.ollama
    assert not rc.model.startswith(("gemini", "gemma"))

def test_spare_model_never_mapped_to_a_role(tmp_path):
    cfg = load_model_config()
    assert "gemini-3.8-flash" in cfg.spare
    assert all(rc.model not in cfg.spare for rc in cfg.roles.values())
    bad = tmp_path / "models.toml"   # copy with planner -> gemini-3.8-flash
    ...
    with pytest.raises(ValueError):
        load_model_config(bad)

def test_flash_lite_limits_and_spacing():
    lim = load_model_config().limits["gemini-3.5-flash-lite"]
    assert (lim.rpm, lim.rpd) == (15, 500) and lim.min_interval_s >= 4.5

def test_settings_reads_key_without_exposing_it(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-a-key")
    assert "test-not-a-key" not in repr(Settings())
```

- [ ] **Step 5:** `uv run pytest tests/test_settings.py -v`. Expected: FAIL (ImportError).
- [ ] **Step 6:** Implement with `tomllib`.
- [ ] **Step 7:** `uv run pytest ; uv run ruff check . ; uv run mypy .`. Expected: 5 passed, both linters clean.
- [ ] **Step 8:** Commit `chore: scaffold project, settings and free-tier model config`.

### Task 2: Contracts [subagent-driven]

**Files:**
- Create: `src/evident/contracts/{__init__,common,enums,facts,documents,coverage,plan,validation,outputs,runs}.py`, `docs/explainers/contracts.md`
- Test: `tests/contracts/test_contracts.py`, `tests/contracts/fixtures/*.json` (the design's Data model examples, plus the added fields)

**Interfaces (Produces; every later task uses these names):**
- `common.Contract(BaseModel)`: `ConfigDict(strict=True, extra="forbid", frozen=True)`, with field `schema_version: Literal["2.0"] = "2.0"`.
- `enums`, all StrEnum, with the exact values from the invariants skill:
  - `FactStatus`, `ExtractionPath`, `Ownership`, `Deployment`, `MetricDirection`, `CoverageGrade`, `RequirementCategory`;
  - `FactKind`: `experience, project, education, certification, skill, award`;
  - `Verdict`: `supported, overstated, unsupported`;
  - `ClaimOutcome`: `passed, rejected, user_review`;
  - `OutputType`: `visual_profile, interview_deck`;
  - `Transformation`: `shorten, expand_narrative`;
  - `DocumentKind`: `cv, job_ad`;
  - `RunStage`: `ingest, review, coverage, plan, validate, render, verify, done`;
  - `RunState`: `pending, running, waiting_for_user, quota_exhausted, failed, done`;
  - plus the re-exported `ErrorCategory`.
- `facts`:
  - `METRIC_VOCAB = {"latency", "accuracy", "cost", "revenue", "users", "throughput", "time_saved", "error_rate", "coverage", "count"}`.
  - `MetricRecord(metric_id, metric: str, direction, value: float, unit: str, baseline: float | None, subject: str, span_text: str)`. `metric` must be in `METRIC_VOCAB` or start with `other:`.
  - `FactAttributes(ownership: Ownership | None, deployment: Deployment | None, scale: None = None, metrics: list[MetricRecord], start: str | None, end: str | None, skills: list[str], title: str | None, organisation: str | None)`. `start` and `end` match `^\d{4}-(0[1-9]|1[0-2])$`. `title` and `organisation` are additions to the design example, needed by the entity check and extraction scoring.
  - The five source variants, discriminated on `extraction_path`:
    - `PdfTextSource(document_id, page: int, bbox, span_text, confidence: float, span_found: bool)`, with literal `pdf_text`; `OcrSource` is the same with `ocr`;
    - `VisionSource(document_id, bbox, bbox_verified: bool, span_text, confidence)`;
    - `TranscriptSource(document_id, start_ms, end_ms, span_text)`;
    - `StorySource(story_id, field, char_start, char_end, span_text)`;
    - `GapAnswerSource(question_id, answer_id, char_start, char_end, span_text)`.

    `Source = Annotated[Union[...], Field(discriminator="extraction_path")]`. Each `bbox` is `tuple[float, float, float, float]` as `[x0, y0, x1, y1]` in PDF points or image pixels.
  - `FactVersion(fact_id, version: int >= 1, owner_id, status, kind, text, attributes, source: Source, supersedes: int | None, edited_by_user: bool, confirmed_at: datetime | None)`.
  - `FactRef(fact_id, version)`.
- `documents.Document(document_id, owner_id, kind, media_type: Literal["application/pdf", "image/png", "image/jpeg"], filename, sha256, width_px: int | None, height_px: int | None, created_at)`.
- `coverage`:
  - `Target(target_id, owner_id, title, source_job_id: str | None, document_id: str | None)`;
  - `Requirement(requirement_id, text, category)`;
  - `CoverageRow(requirement_id, text, category, grade, evidence: list[FactRef], rationale)`.
- `plan`:
  - `Claim(claim_id, version: int = 1, text, evidence: list[FactRef], section: str, emphasis: int (1..5), allowed_transformations: list[Transformation], output_types: list[OutputType], parent_claim_id: str | None)`;
  - `ContentPlan(plan_id, owner_id, target_id, claims: list[Claim], created_at)`.
- `validation`:
  - `CheckFailure(rule: str, phrase: str, detail: str)`;
  - `Layer1Result(passed: bool, failures: list[CheckFailure])`;
  - `JudgeVerdict(verdict, offending_phrase: str | None, corrected_phrasing: str | None, confidence: float (0..1))`;
  - `ClaimValidation(claim_id, claim_version, outcome, layer1, judge: JudgeVerdict | None, judge_model: str | None, judge_error: str | None, reasons: list[str], approved_by_user: bool = False)`;
  - `ValidationReport(plan_id, results: list[ClaimValidation], dropped_claim_ids: list[str], models_by_role: dict[str, str], limitations: list[str])`.
- `outputs`:
  - `PostRenderResult(passed: bool, problems: list[str])`;
  - `Output(output_id, owner_id, plan_id, output_type, claim_ids: list[str], fact_refs: list[FactRef], files: dict[str, str], post_render: PostRenderResult | None)`.
- `runs.RunStatus(run_id, owner_id, stage, state, message, error: str | None, document_id, target_id: str | None, plan_id: str | None, output_ids: list[str])`.
- `contracts.ALL_CONTRACTS: tuple[type[Contract], ...]`.

- [ ] **Step 1: Failing tests:**

```python
def test_design_fact_example_round_trips():
    fact = FactVersion.model_validate_json((FIXTURES / "fact_version.json").read_text())
    assert FactVersion.model_validate_json(fact.model_dump_json()) == fact

def test_strict_rejects_coercion():
    with pytest.raises(ValidationError):
        FactRef.model_validate({"fact_id": "exp_03", "version": "2"})

def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        FactRef.model_validate({"fact_id": "x", "version": 1, "extra": 1})

def test_metric_vocab_and_other_prefix():
    MetricRecord.model_validate({**METRIC, "metric": "other:clash_checks"})
    with pytest.raises(ValidationError):
        MetricRecord.model_validate({**METRIC, "metric": "vibes"})

def test_source_discriminates_on_extraction_path():
    f = FactVersion.model_validate_json((FIXTURES / "fact_vision.json").read_text())
    assert isinstance(f.source, VisionSource)

def test_every_contract_has_schema_version():
    for model in ALL_CONTRACTS:
        assert model.model_fields["schema_version"].default == "2.0"

@pytest.mark.parametrize("bad", ["2026-13", "26-05", "2026-5"])
def test_year_month_format(bad):
    with pytest.raises(ValidationError):
        FactAttributes.model_validate({**ATTRS, "start": bad})
```

- [ ] **Step 2:** `uv run pytest tests/contracts -v`. Expected: FAIL (ImportError).
- [ ] **Step 3:** Implement the contracts as listed.
- [ ] **Step 4:** `uv run pytest tests/contracts -v ; uv run mypy .`. Expected: all pass.
- [ ] **Step 5:** Write `docs/explainers/contracts.md`.
- [ ] **Step 6:** Commit `feat: add versioned strict contracts from the design data model`. From here on, contracts are frozen: any change needs owner approval and a `schema_version` bump.

### Task 3: Prompts, model adapter, cache, quota guard

**Files:**
- Create: `src/evident/prompts/__init__.py`, `src/evident/prompts/{preamble,extraction,requirements,coverage,planner,judge}/v1.txt`
- Create: `src/evident/models/{__init__,adapter,cache,costs,quota,gemini,ollama,router}.py`, `tests/fakes.py`
- Test: `tests/models/test_adapter.py`, `tests/models/test_quota.py`, `tests/models/test_ollama.py`, `tests/models/test_router.py`, `tests/models/test_gemini_live.py` and `tests/models/test_ollama_live.py` (marked `live`)

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `Prompt(name, version, text)`; `load_prompt(name: str, version: str = "v1") -> Prompt`; `render_prompt(prompt: Prompt, **fields: str) -> str`, which prepends the preamble.
  - `TextPart(text: str)`, `ImagePart(data: bytes, mime_type: str)`, `Part = TextPart | ImagePart`.
  - `ModelResult[T](value: T, model_id, prompt: str, prompt_version: str, cached: bool, input_tokens: int, output_tokens: int, est_cost_usd: float, latency_ms: int)`.
  - `class ModelAdapter(Protocol)` with two methods:
    - `generate_json(self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]) -> ModelResult[T]`;
    - `is_cached(self, role, prompt, parts, schema) -> bool`, used by the evaluation pre-flight.
  - `DiskCache(root: Path)` with `get(key) -> str | None` and `put(key, value) -> None`. `cache_key(model_id, prompt, parts, schema) -> str` is the sha256 of the model ID, prompt name and version, schema name, and each part's text or bytes hash.
  - `estimate_cost(price: Price, input_tokens: int, output_tokens: int) -> float`.
  - `QuotaGuard(limits: FreeTierLimits, state_path: Path, clock: Callable[[], datetime] = utc_now, sleep: Callable[[float], None] = time.sleep)` with:
    - `reserve() -> None`, called before every uncached call;
    - `remaining_today() -> int`;
    - `record_429() -> None`.

    Behaviour:
    - one guard per Gemini model, with state at `settings.quota_dir / f"{model_id}.json"`;
    - the day key is the UTC-8 date;
    - `rpd` is reached when the count is `>= rpd - 2` (a margin of 2, so Flash-Lite stops at 498 and the spare at 18), at which point it raises `StageError(code="daily_quota", category=provider, retryable=False, detail="Free-tier daily quota reached (n/rpd). Resets at midnight Pacific.")`;
    - missing limits or any limit of 0 raises `StageError(code="limits_not_set", category=internal)`;
    - spacing: each reservation sleeps until at least `min_interval_s` (4.5 s for Flash-Lite) has passed since the previous reservation's start, and also until fewer than `rpm` calls fall in the last 60 s; this is pacing, not retrying;
    - state is written atomically after each reservation, including the last call time, so spacing holds across restarts.
  - `GeminiAdapter(settings, config, cache, guards: dict[str, QuotaGuard], cache_only: bool = False)`. A 429 or resource-exhausted response calls `record_429()` and raises `StageError(code="rate_limited", category=provider, retryable=False)`. It is never retried. With `cache_only=True` (demo mode), a cache miss raises `StageError(code="not_recorded", category=internal, detail="This call is not in the recorded run.")` before any network call.
  - `OllamaAdapter(settings, config, cache)` for role `judge`:
    - `POST {ollama_url}/api/chat` with `stream: false`, `format` set to `schema.model_json_schema()`, `options: {"temperature": 0, "num_ctx": 4096}`, `keep_alive: "30m"`, the preamble as the system message and the rendered prompt as the user message;
    - timeout from the role config (30 s);
    - on first use, `POST /api/show` must report the pinned digest (`ollama_digests`) for the tag; a mismatch raises `StageError(code="judge_model_mismatch", category=internal)`;
    - connection refused, timeout or HTTP error raises `StageError(code="judge_unavailable", category=provider, retryable=False)`, which the outcome table turns into user review;
    - invalid JSON gets the same one retry as Gemini;
    - token counts come from `prompt_eval_count` and `eval_count`; estimated cost is 0.0;
    - image parts are refused with `StageError(category=internal)`, since the judge is text only.
  - `RoutingAdapter(config, gemini, ollama)` implements `ModelAdapter` and sends each role to the adapter named by its `provider`. It refuses any spare model.
  - `build_adapter(settings, config) -> RoutingAdapter` wires everything. With `settings.demo`, every role except `judge` is cache-only, so the live claim box still works whichever provider the judge uses.
  - `tests/fakes.FakeAdapter(responses: dict[Role, list[str]])` returns queued JSON strings in order, records calls, and `is_cached` returns False.

- [ ] **Step 1:** Write the prompt files.
  - `preamble`, `extraction`, `coverage`, `planner` and `judge` copy the design's Prompts section text exactly, with `{placeholders}`.
  - The extraction prompt asks for `box_2d` as `[ymin, xmin, ymax, xmax]` normalised to 0 to 1000, plus `title` and `organisation` attributes.
  - Coverage is changed to grade a list: "For each requirement below, return requirement_id, grade, evidence fact_ids and rationale", with the requirements as `id: text (category)` lines inside `<job_ad>`.
  - Planner `renderer_limits` reads "visual profile: at most 10 claims, each at most 160 characters; deck: at most 4 content slides, at most 3 claims per slide; speaker-note narratives at most 400 characters".
  - New `requirements/v1.txt`: "Split the job ad into individual requirements. For each, return text (verbatim or minimally trimmed) and category: required | preferred | responsibility | boilerplate. Do not add requirements that are not in the ad." The ad goes in `<job_ad>{content}</job_ad>`.
- [ ] **Step 2: Failing tests:**

```python
def test_invalid_json_retried_once_with_error_then_stage_error(): ...   # stub client returns "not json" twice
def test_valid_json_after_one_retry_returns_value(): ...
def test_cache_hit_skips_client_and_quota(tmp_path): ...
def test_prompt_version_change_misses_cache(tmp_path): ...             # Review Focus 5
def test_429_raises_rate_limited_without_retry(): ...                   # stub called exactly once
def test_untrusted_text_is_wrapped_in_tags():
    assert "<document>evil</document>" in render_prompt(load_prompt("extraction"), content="evil")
# test_quota.py
def test_limits_not_set_refuses(): ...
def test_daily_quota_stops_with_margin(tmp_path):
    g = QuotaGuard(FreeTierLimits(rpm=100, tpm=10**6, rpd=10, checked="x", source="y"), tmp_path / "q.json", clock=fixed)
    for _ in range(8): g.reserve()
    with pytest.raises(StageError) as e: g.reserve()
    assert e.value.code == "daily_quota" and not e.value.retryable
def test_day_rolls_over_at_utc_minus_8(tmp_path): ...                   # 07:59 UTC same day, 08:00 UTC new day
def test_rpm_pacing_sleeps_instead_of_failing(tmp_path): ...           # fake sleep records the wait
def test_min_interval_spaces_calls_4_5_s(tmp_path): ...                # two reserves 1 s apart: second sleeps 3.5 s
def test_flash_lite_guard_stops_at_498_of_500(tmp_path): ...
def test_state_survives_restart(tmp_path): ...                         # count and last call time
# test_ollama.py (stub HTTP server on localhost)
def test_judge_request_uses_schema_format_and_temperature_0(): ...
def test_digest_mismatch_refuses(): ...
def test_server_down_raises_judge_unavailable_without_retry(): ...
def test_image_part_refused(): ...
# test_router.py
def test_roles_route_by_provider(): ...
def test_cache_only_miss_raises_not_recorded_without_network(): ...
def test_demo_mode_leaves_judge_role_live(): ...
def test_cache_only_hit_returns_cached_value(): ...
```

- [ ] **Step 3:** `uv run pytest tests/models -v`. Expected: FAIL.
- [ ] **Step 4:** Implement.
  - `GeminiAdapter.generate_json` calls `client.interactions.create(model=..., input=[...], response_format={"type": "text", "mime_type": "application/json", "schema": schema.model_json_schema()})` and validates with `schema.model_validate_json(interaction.output_text)`.
  - Check https://ai.google.dev/api/interactions-api and the installed SDK for:
    - the inline image field;
    - the system instruction and max output tokens in `generation_config`;
    - the token usage attribute names;
    - the timeout option;
    - how a 429 surfaces.

    Note the field names you found in a comment, with the date.
  - Log only role, model, prompt version, tokens, estimated cost, latency, cache hit and remaining quota.
- [ ] **Step 5:** `uv run pytest tests/models -v`. Expected: PASS.
- [ ] **Step 6:** Live smoke test: `uv run pytest -m live tests/models`. It makes 1 Flash-Lite call with a small synthetic image part (confirms image input end to end) and 1 local judge call. Expected: PASS, Flash-Lite `remaining_today()` drops by 1, and the judge digest check passes.
- [ ] **Step 7:** Commit `feat: add model adapters with cache and free-tier quota guard`.

### Task 3a: Local judge smoke test

Decides the judge before any task depends on it (spec 7.3, P1). Native execution.

**Files:**
- Create: `experiments/a3-slice/judge_smoke_claims.jsonl`, `scripts/judge_smoke.py`
- Generated: `experiments/a3-slice/JUDGE_SMOKE.md`

- [ ] **Step 1:** Write 10 obvious claims by hand, each with a short synthetic evidence block in the same shape the judge will see (text, span_text, dates, ownership, deployment, metrics):
  - 5 supported (faithful rephrasings);
  - 5 inflated, one each: "led" on a contributed fact, "production" on a prototype, a larger number than the metric, a skill not in the evidence, and a plainly overstated paraphrase.
- [ ] **Step 2:** Write the pass criteria into `JUDGE_SMOKE.md` and commit them before any judge call:
  - **Accuracy:** at least 9 of 10 verdicts correct, where an inflated claim is correct only as `overstated` or `unsupported`, **and** 0 of 5 inflated claims judged `supported` with confidence ≥ 0.8 (that would be a false accept under the outcome table).
  - **Speed:** warm median ≤ 8 s per judgement and warm maximum ≤ 20 s, measured after one discarded warm-up call. The 20 s cap keeps a judgement inside the 30 s text timeout with margin. At 8 s, the 15 to 20 judgements in a demo run take under 3 minutes.
  - **Fit:** the model runs fully on the GPU (`ollama ps` shows 100% GPU).
  - Fail on any criterion means the fallback: `judge` moves to `gemini-3.5-flash-lite`.
- [ ] **Step 3:** `scripts/judge_smoke.py` runs the 10 claims through `OllamaAdapter` with the real judge prompt, bypassing the cache so each timing is real. It records each verdict, confidence and latency, and the cold-start time of the warm-up call. No claim or evidence text is logged, only claim index, label, verdict, confidence and timing.
- [ ] **Step 4:** Run it: `uv run python scripts/judge_smoke.py`. Write the results into `JUDGE_SMOKE.md`: k/10 correct, false accepts k/5, median and max latency with n, GPU share, Ollama version, model tag and digest, prompt version, and pass or fail.
- [ ] **Step 5:** Depending on the outcome:
  - **Pass:** keep `judge` on Ollama. Update P1 "Smoke test outcome" to "passed" with the date and figures.
  - **Fail:** set `judge` to provider `gemini`, model `gemini-3.5-flash-lite` in `config/models.toml`, update the Task 1 judge test to match, set P1 to "fallback in force" with the reason, and note in Task 12 that `LIMITATIONS` uses the same-family wording.
- [ ] **Step 6:** Tell the owner which way it went, with the figures.
- [ ] **Step 7:** Commit `test: add local judge smoke test and record outcome`.

### Task 4: File repository

**Files:** Create `src/evident/store/{__init__,repository,files}.py`. Test: `tests/store/test_files.py`.

**Interfaces (Produces):**
- `Repository` Protocol and `FileRepository(root: Path)` implementing:
  - `put_document(doc: Document, content: bytes)`, `get_document(owner_id, document_id) -> Document | None`, `get_document_bytes(owner_id, document_id) -> bytes`.
  - `put_fact(fact)`, which raises `StageError(code="version_exists", category=internal)` if `(fact_id, version)` already exists.
  - `set_fact_status(owner_id, fact_id, version, status, confirmed_at) -> FactVersion`. Only `extracted -> confirmed | rejected | superseded` and `confirmed -> superseded` are allowed; anything else raises.
  - `get_fact(owner_id, ref: FactRef) -> FactVersion | None`.
  - `current_facts(owner_id, document_id: str | None = None) -> list[FactVersion]`, returning the highest non-superseded version per fact_id.
  - `put_target`/`get_target`, `put_coverage(target_id, rows)`/`get_coverage`, `put_plan`/`get_plan`, `put_report`/`get_report(plan_id)`, `put_output`/`get_output`, `put_run`/`get_run`.

  Every getter takes `owner_id` and returns None for another owner's record.

- [ ] **Step 1: Failing tests:** round trip for each record type, plus:
  - `test_other_owner_gets_none`;
  - `test_put_fact_never_overwrites_existing_version`;
  - `test_status_transitions_enforced`;
  - `test_current_facts_skips_superseded`;
  - `test_output_keeps_fact_versions_after_new_fact_version`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement with one JSON file per record, at `root/<owner_id>/<type>/<id>[_v<version>].json`. Write to a temp file and `os.replace` it into place.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: add owner-scoped JSON file repository`.

### Task 5: Enriched synthetic data and ground truth

**Files:**
- Create: `data/synthetic/a3_enriched/{overlay.json,README.md}`, `scripts/build_enriched.py`, `src/evident/eval/{__init__,datasets}.py`
- Generated (committed): `a3_enriched/profiles.jsonl`, `a3_enriched/ground_truth/<document_id>.json`
- Test: `tests/eval/test_datasets.py`

**Interfaces (Produces):**
- `load_enriched_profiles() -> list[dict]`.
- `ground_truth_facts(profile: dict, owner_id: str, document_id: str) -> list[FactVersion]`. All are confirmed and version 1, with a `PdfTextSource` of `bbox=(0, 0, 0, 0)`, `span_found=True` and `page=1`.
- `A1_HASHES: dict[str, str]`, the SHA-256 of the 4 A1 files, computed now and pasted in.

- [ ] **Step 1:** Write `overlay.json` by hand, keyed by `document_id`. For each profile:
  - add `start` and `end` (YYYY-MM between 2023-02 and 2026-10, with at least one `end: null` across the set), `ownership` and `deployment` on every project and experience entry, matching existing wording;
  - add `expected_graduation_month`;
  - add 1 to 3 single-figure metric records, with units from `percent, count, seconds, hours, users`. Each comes with the sentence that inserts its `span_text` into the matching description.
- [ ] **Step 2: Failing tests:**

```python
def test_a1_files_unchanged():
    for name, digest in A1_HASHES.items():
        assert sha256(Path("data/synthetic", name).read_bytes()).hexdigest() == digest
def test_every_metric_span_appears_in_its_description(): ...
def test_every_project_and_experience_has_dates_ownership_deployment(): ...
def test_ground_truth_facts_validate_and_cover_each_section(): ...  # experience, project, education incl. coursework, one skill fact per technical_skill
def test_summary_and_activities_are_not_ground_truth(): ...
def test_pipeline_does_not_import_ground_truth(): ...               # no "ground_truth" in src/evident outside eval/
```

- [ ] **Step 3:** Run. Expected: FAIL.
- [ ] **Step 4:** Implement `build_enriched.py` and `datasets.py`, then run `uv run python scripts/build_enriched.py`.
- [ ] **Step 5:** Write `a3_enriched/README.md`. Cover every added field and which descriptions gained metric sentences. State that everything added is fictional, for A3 testing, and must stay marked synthetic. Point to `overlay.json`.
- [ ] **Step 6:** Run tests. Expected: PASS.
- [ ] **Step 7:** Commit `feat: add labelled fictional enrichment of A1 profiles`.

### Task 6: CV templates, rendered CVs, simulated photos, job screenshot

**Files:**
- Create: `src/evident/render/{__init__,pdf}.py`, `data/synthetic/a3_enriched/templates/{classic,sidebar,compact}.html.j2`, `scripts/{render_cvs,make_photos,screenshot_job}.py`
- Generated (committed): `a3_enriched/rendered/<document_id>_<template>.pdf`, `..._<template>_photo.jpg`, `rendered/job_graduate_ai_engineer.png`
- Test: `tests/render/test_pdf.py`, `tests/scripts/test_cv_assets.py`

**Interfaces (Produces):**
- `html_to_pdf(html: str, out: Path) -> Path` (A4, print backgrounds).
- `html_to_png(html: str, out: Path, width: int = 1200) -> Path` (full page).
- `simulate_photo(page_png: bytes, seed: int) -> bytes` (JPEG).

- [ ] **Step 1: Failing tests:**
  - `test_html_to_pdf_text_extractable`;
  - `test_all_15_cvs_exist_and_carry_marker`;
  - `test_every_ground_truth_title_appears_in_pdf_text`;
  - `test_simulate_photo_deterministic_per_seed`;
  - `test_photo_differs_from_source`: mean absolute pixel difference > 10.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement the templates.
  - Layouts: classic (single column), sidebar (skills and education on the left) and compact (dense two-column).
  - Each renders name, degree and institution, education with coursework, experience, projects (dates and metric sentences) and skills, with the marker footer. No summary or activities.
- [ ] **Step 4:** Implement `simulate_photo`: perspective warp of up to 4% corner shift, rotation ±3°, a lighting gradient, Gaussian blur radius 0.8 to 1.5, noise σ 4, JPEG quality 70. All parameters are drawn from `random.Random(seed)`.
- [ ] **Step 5:** `screenshot_job.py` renders `graduate_ai_engineer` in a plain job-board layout and saves the PNG.
- [ ] **Step 6:** Run the three scripts, then the tests. Expected: PASS. Look at two photos and one PDF to check they're legible.
- [ ] **Step 7:** Commit `feat: render synthetic CVs in three templates with simulated photos`.

### Task 7: Photo ingestion (vision)

**Files:**
- Create: `src/evident/ingestion/{__init__,drafts,vision}.py`, `docs/explainers/ingestion-vision.md`
- Test: `tests/ingestion/test_drafts.py`, `tests/ingestion/test_vision.py`

**Interfaces (Produces):**
- Model-facing schemas, not contracts:
  - `DraftMetric(metric: str, direction: str, value: float, unit: str, subject: str, span_text: str)`;
  - `DraftAttributes(ownership, deployment, start, end, title, organisation: str | None; skills: list[str]; metrics: list[DraftMetric])`;
  - `ExtractedFactDraft(kind: str, text: str, span_text: str, box_2d: list[int] | None, attributes: DraftAttributes)`;
  - `ExtractionDraft(facts: list[ExtractedFactDraft], unreadable_regions: list[str])`.
- `draft_to_fact(draft, index: int, doc: Document, source: Source) -> FactVersion`:
  - `fact_id = f"{doc.document_id}_f{index:02d}"`, version 1, status extracted;
  - an invalid enum value or date format becomes None;
  - an unknown metric name becomes `other:<name>`;
  - a draft with an unknown kind is skipped, and the skip is logged by index only.
- `box_2d_to_pixels(box_2d: list[int], width: int, height: int) -> tuple[float, float, float, float]`. Gemini order is `[ymin, xmin, ymax, xmax]` on 0 to 1000. The result is clamped to the image.
- `verify_bbox(image: bytes, bbox, span_text: str, threshold: float = 80.0) -> bool`, which crops with a 4% margin, runs `pytesseract.image_to_string`, and compares normalised text with `fuzz.partial_ratio`.
- `ingest_photo(doc: Document, content: bytes, adapter: ModelAdapter, repo: Repository) -> list[FactVersion]`, using role `extraction_vision`. A box that is missing or fails verification falls back to `(0, 0, width, height)` with `bbox_verified=False`.

- [ ] **Step 1: Failing tests:**

```python
def test_box_2d_order_and_scale():                              # Review Focus 3
    assert box_2d_to_pixels([100, 200, 300, 400], width=1000, height=2000) == (200.0, 200.0, 400.0, 600.0)
def test_box_2d_clamped_to_image(): ...
def test_invalid_enum_in_draft_becomes_none_not_crash(): ...
def test_unknown_metric_becomes_other_prefix(): ...
def test_verify_bbox_true_on_rendered_text_crop(): ...           # PNG from html_to_png with known text
def test_unverified_box_falls_back_to_whole_image(): ...
def test_image_sent_as_image_part_with_document_tags(): ...
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Set `pytesseract.pytesseract.tesseract_cmd` from `shutil.which("tesseract")`, falling back to `C:\Program Files\Tesseract-OCR\tesseract.exe`. If Tesseract is missing, raise `StageError(code="ocr_unavailable", category=internal)`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Live check on one photo (1 call): print the counts of facts and of verified boxes only.
- [ ] **Step 6:** Write the explainer, then commit `feat: add photo ingestion with OCR-verified boxes`.

### Task 8: PDF ingestion

**Files:** Create `src/evident/ingestion/pdf_text.py`, `docs/explainers/ingestion-pdf.md`. Test: `tests/ingestion/test_pdf_text.py`.

**Interfaces (Produces):**
- `CharBox(text, x0, top, x1, bottom)` and `PageText(page_number: int, text: str, chars: list[CharBox])`.
- `extract_pages(pdf: bytes) -> list[PageText]`. `text` is the concatenation of `chars` in order.
- `SpanLocation(page, bbox, score)`; `locate_span(pages, span_text, threshold: float = 90.0) -> SpanLocation | None`, using `fuzz.partial_ratio_alignment` per page, the best score, and the union of the matched chars' boxes.
- `ingest_pdf(doc, content, adapter, repo) -> list[FactVersion]`, using role `extraction_text` and `draft_to_fact` from Task 7. A span that isn't found keeps the fact, with `span_found=False` and `bbox=(0, 0, 0, 0)`. An empty text layer raises `StageError(category=input)`.

- [ ] **Step 1: Failing tests:**
  - `test_locate_span_returns_union_box_on_correct_page`: a 2-page PDF from `html_to_pdf`;
  - `test_locate_span_below_threshold_returns_none`;
  - `test_ingest_pdf_stores_extracted_facts_with_spans`: the FakeAdapter returns 2 drafts, one span present and one absent;
  - `test_ingest_pdf_sends_text_inside_document_tags`;
  - `test_empty_text_layer_raises_input_error`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Live check on one CV (1 call): fact count and `span_found` share. Expected: more than 10 facts, and at least 90% with span found.
- [ ] **Step 6:** Write the explainer, then commit `feat: add PDF text ingestion with span boxes`.

### Task 9: Review actions, source crops, review UI

**Files:**
- Create: `src/evident/review/{__init__,actions}.py`, `src/evident/render/receipts.py`, `src/evident/runs.py` (start and ingest only)
- Create: `src/evident/web/{__init__,app,routes}.py`, `web/templates/{base,start,run,facts}.html`, `web/static/app.js`
- Create: `docs/explainers/user-review.md`
- Test: `tests/review/test_actions.py`, `tests/render/test_receipts.py`, `tests/web/test_review_routes.py`

**Interfaces (Produces):**
- `is_high_impact(fact) -> bool`. True if the fact has dates, metrics, kind education or certification, ownership above contributed, deployment above concept, or `span_found` / `bbox_verified` False.
- `confirm(repo, owner_id, ref, now) -> FactVersion`. This raises `StageError(code="span_not_found", category=validation)` for an unedited pdf fact with `span_found=False`.
- `confirm_low_impact(repo, owner_id, document_id, now) -> int`.
- `reject(repo, owner_id, ref) -> FactVersion`.
- `FactEdit`, a dataclass of optional text and attribute fields; `edit(repo, owner_id, ref, changes: FactEdit, now) -> FactVersion`. The new version has `supersedes = old.version`, `edited_by_user=True` and status extracted, and the old version becomes superseded.
- `crop_source(doc, content, source) -> bytes`, a PNG. PDF pages are rendered with pypdfium2 at scale 2 and cropped to the bbox with a 12 pt margin. Images are cropped in pixels with a 4% margin.
- `RunService(repo, adapter, settings)` with `start(owner_id, cv_path: Path | None, upload: tuple[str, bytes] | None, job_id: str | None, use_job_screenshot: bool) -> RunStatus` and `run_ingest(run_id) -> None`.
  - Routing is by media type: PDF goes to `ingest_pdf`, PNG or JPEG to `ingest_photo`.
  - On success the run moves to `review` / `waiting_for_user`.
  - A `StageError` with code `daily_quota` or `rate_limited` sets state `quota_exhausted` and shows its detail.
- `create_app(settings, repo, adapter) -> FastAPI`; `main() -> FastAPI` builds the real dependencies.
- Routes:
  - `GET /`;
  - `POST /runs`, which redirects to `/runs/{run_id}`;
  - `GET /runs/{run_id}` (meta refresh 2 s while running);
  - `GET /runs/{run_id}/facts`;
  - `POST /facts/{fact_id}/v/{version}/{confirm|reject|edit}`;
  - `POST /runs/{run_id}/facts/confirm-low-impact`;
  - `GET /documents/{document_id}/source?fact_id=&version=` returns a PNG, or 404 for another owner or an unknown ID.

- [ ] **Step 1: Failing tests:**
  - `test_confirm_low_impact_skips_high_impact`;
  - `test_cannot_confirm_unmatched_span_until_edited`;
  - `test_edit_creates_new_version_and_supersedes_old`;
  - `test_crop_source_pdf_returns_png`;
  - `test_source_route_404_for_other_owner`;
  - `test_facts_page_lists_fact_with_crop_link`;
  - `test_quota_error_sets_quota_exhausted_state` (Review Focus 5).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement with Jinja autoescape on. Run with `uv run uvicorn evident.web.app:main --factory --port 8000`.
- [ ] **Step 4:** Run tests. Expected: PASS.
- [ ] **Step 5:** Manual check: upload a photo, see facts and crops, confirm some.
- [ ] **Step 6:** Write the explainer, then commit `feat: add fact review actions, source crops and review pages`.

### Task 10: Coverage

**Files:** Create `src/evident/coverage/{__init__,requirements,grading}.py`, `docs/explainers/coverage.md`. Modify `runs.py` (add `run_coverage`). Test: `tests/coverage/test_coverage.py`.

**Interfaces (Produces):**
- `extract_requirements(adapter, *, text: str | None = None, image: bytes | None = None) -> list[Requirement]`. Exactly one of text or image is given; IDs are `req_01...`; the role is `requirements`.
- `GradingDraft(rows: list[DraftRow(requirement_id, grade, evidence: list[str] (as "fact_id@version"), rationale)])`.
- `grade_requirements(reqs, facts, adapter) -> list[CoverageRow]`. All non-boilerplate requirements are graded in one call (role `coverage`). Facts go inside `<evidence>` as `fact_id@version: text | skills | dates`. A requirement with no returned row becomes `gap` with rationale "not graded by model", which is cautious and visible.
- `check_coverage_gate(rows, facts) -> None` raises `StageError(code="coverage_gate", category=validation)` if:
  - a non-gap row has no evidence;
  - a gap row has evidence;
  - a ref isn't in the confirmed facts;
  - a returned requirement ID is unknown.
- `RunService.run_coverage(run_id) -> None` uses only confirmed facts. While any high-impact fact is still `extracted`, it stays `waiting_for_user` with the message "Confirm or reject the highlighted facts first."

- [ ] **Step 1: Failing tests:**
  - `test_boilerplate_not_graded`;
  - `test_single_call_grades_all_requirements`;
  - `test_missing_row_becomes_gap`;
  - `test_gate_rejects_citation_of_unconfirmed_fact`;
  - `test_gate_rejects_gap_with_evidence`;
  - `test_only_confirmed_facts_reach_grader`;
  - `test_screenshot_path_sends_image_part`;
  - `test_run_waits_while_high_impact_fact_unconfirmed`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Live check, requirements from the screenshot (1 call): count and categories.
- [ ] **Step 6:** Write the explainer, then commit `feat: add requirement extraction and single-call coverage grading`.

### Task 11: Planner

**Files:** Create `src/evident/planning/{__init__,planner}.py`. Test: `tests/planning/test_planner.py`.

**Interfaces (Produces):**
- `PlanDraft(claims: list[DraftClaim(text, evidence: list[str], section, emphasis: int, output_types: list[str], narrative_for: str | None)])`.
- `build_plan(owner_id, target, facts, coverage, adapter, feedback: list[ClaimValidation] | None = None) -> ContentPlan`:
  - role `planner`;
  - claim IDs are `c_001...`, stable across feedback rounds for the same text;
  - `narrative_for` becomes `parent_claim_id` with output type `interview_deck`;
  - a claim whose evidence cites only facts behind gap rows is dropped before validation;
  - on feedback, the prompt lists each rejected claim's text, rule and phrase under "Rejected claims and reasons".

- [ ] **Step 1: Failing tests:**
  - `test_claims_cite_fact_versions`;
  - `test_claim_ids_stable_and_unique`;
  - `test_narrative_claims_have_parent_and_deck_output_type`;
  - `test_feedback_text_contains_rule_and_phrase`;
  - `test_claim_for_gap_only_evidence_dropped`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: add content planner`. The planner explainer is written in Task 15, once the feedback loop exists.

### Task 12: Claim validation core [subagent-driven]

**Files:**
- Create: `config/lexicons.toml`, `config/aliases.toml`
- Create: `src/evident/validation/{__init__,judge,outcome}.py`, `src/evident/validation/layer1/{__init__,config,run,checks_ids}.py`
- Create: `docs/explainers/judge.md`
- Test: `tests/validation/test_outcome.py`, `tests/validation/layer1/test_checks_ids.py`

**Interfaces (Produces):**
- `Lexicons`, loaded by `load_lexicons(path=Path("config/lexicons.toml"))`, with:
  - `ownership: dict[str, int]` and `deployment: dict[str, int]`, ranks exactly as in the design's Lexicons table;
  - `metric_keywords: dict[str, str]`;
  - `direction_words: dict[str, MetricDirection]`;
  - `scale_nouns: set[str]`;
  - `aggregate_nouns: dict[str, FactKind]`;
  - `seniority_words: set[str]`;
  - `credential_words: set[str]`.
- `Aliases`, loaded by `load_aliases()`, with `skills: dict[str, str]` (alias to canonical, canonical maps to itself) and `entities: dict[str, str]`. Start `skills` with every enriched-profile skill plus about 150 common tools.
- `Layer1Context(owner_id: str, resolve: Callable[[FactRef], FactVersion | None], lex: Lexicons, aliases: Aliases, as_of: str)`.
- `Check = Callable[[Claim, list[FactVersion], Layer1Context], list[CheckFailure]]`, and `CHECKS: list[Check]` in `run.py`, empty here. Tasks 16 to 18 append to it.
- `check_fact_ids(claim, ctx) -> list[CheckFailure]` fails if the claim has no evidence, a ref doesn't resolve, the owner differs, or the status isn't confirmed.
- `run_layer1(claim, ctx) -> Layer1Result` runs `check_fact_ids` first. If that fails it stops; otherwise it resolves the facts and runs every check in `CHECKS`.
- `run_judge(claim, facts, adapter) -> tuple[JudgeVerdict | None, str | None, str | None]`, returning (verdict, model_id, error). It uses role `judge`, and the evidence holds only the cited facts: text, span_text, dates, ownership, deployment and metrics.
- `JUDGE_THRESHOLD = 0.8`. Tune it only on the dev split.
- `validate_claim(claim, ctx, adapter, threshold: float = JUDGE_THRESHOLD) -> ClaimValidation`. The judge always runs. A quota error from the judge is recorded as a judge error and sets no outcome beyond the table.
- `limitations(config) -> list[str]` goes into every `ValidationReport.limitations`. It is derived from the judge's provider in `config/models.toml`, so the report always matches the model actually used:
  - judge on Ollama: "Small local judge: qwen3:4b-instruct-2507-q4_K_M, 4B quantised, self-reported uncalibrated confidence (P1)";
  - judge on Gemini (fallback): "Same-family judge: gemini-3.5-flash-lite is also the planner (P1 fallback)";
  - always: "Free-tier gemini-3.5-flash-lite for extraction, coverage and planning, not a Pro-class model (P3)".
- **Outcome table (spec 8.5):**

| Layer 1 | Judge | Outcome |
|---|---|---|
| pass | supported, confidence ≥ threshold | passed |
| pass | overstated or unsupported, confidence ≥ threshold | rejected |
| pass | any verdict below threshold, or judge error | user_review |
| fail | overstated or unsupported, below threshold, or judge error | rejected |
| fail | supported, confidence ≥ threshold | user_review |

- [ ] **Step 1: Failing tests:**
  - one test per table row;
  - `test_superseded_fact_rejected` ("cites exp_03 v1, which is superseded");
  - `test_other_owner_fact_rejected`;
  - `test_claim_without_evidence_rejected`;
  - `test_judge_error_never_passes`;
  - `test_judge_prompt_contains_only_cited_facts`;
  - `test_judge_unavailable_routes_to_user_review` (Ollama down);
  - `test_report_limitations_match_judge_provider` (both the Ollama and the fallback config).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. The lexicon and alias files are complete now, although only the loaders are used until Task 16.
- [ ] **Step 4:** Run, then `uv run mypy .`. Expected: PASS.
- [ ] **Step 5:** Write `docs/explainers/judge.md`, then commit `feat: add claim validation core with judge and fail-closed outcome`.

### Task 13: Rough renderers

**Files:**
- Create: `config/template_copy.toml`, `src/evident/render/{profile_html,deck}.py`, `src/evident/render/templates/profile.html.j2`
- Test: `tests/render/test_profile_html.py`, `tests/render/test_deck.py`

**Interfaces (Produces):**
- `TEMPLATE_COPY: set[str]`, loaded from `template_copy.toml`: headings, labels and the marker text.
- `renderable_claims(plan, report, output_type) -> list[Claim]` returns claims with outcome passed, or user_review with `approved_by_user`, for that output type.
- `render_profile(plan, report, identity: dict[str, str], receipt_base: str) -> str`. Each claim goes in `<span data-claim-id="{id}" data-claim-version="{v}">`, and identity fields in `<span data-identity="{key}">`. Autoescape is on. The styling is minimal until Task 21.
- `render_profile_pdf(html: str, out: Path) -> Path` uses `html_to_pdf`.
- `render_deck(plan, report, identity, out: Path) -> Path`:
  - a title slide;
  - one slide per section, ordered by emphasis;
  - each slide's body is its claims, verbatim;
  - notes hold the narrative claims, then `Sources:` lines as `claim_id: fact_id@version, page or image, span_text`;
  - the marker on every slide.

- [ ] **Step 1: Failing tests:**

```python
def test_rejected_and_unapproved_review_claims_not_rendered(): ...
def test_every_rendered_claim_has_id_and_version(): ...
def test_html_special_chars_escaped():                          # Review Focus 4
    html = render_profile(plan_with('Built <script> & "API"'), REPORT, ID, "")
    assert "<script>" not in html and "&lt;script&gt;" in html
def test_pdf_contains_claim_text_and_marker(tmp_path): ...
def test_deck_notes_list_claim_ids_and_sources(tmp_path): ...
def test_deck_body_text_is_verbatim_claims(tmp_path): ...
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: add rough visual profile and deck renderers`.

### Task 14: Post-render verification [subagent-driven]

**Files:** Create `src/evident/validation/post_render.py`, `docs/explainers/post-render.md`. Test: `tests/validation/test_post_render.py`.

**Interfaces (Produces):**
- `verify_html(html: str, expected: dict[str, str], identity: dict[str, str], whitelist: set[str]) -> PostRenderResult`, using stdlib `html.parser`:
  - text in a `data-claim-id` element equals the expected wording after whitespace collapse, with entities decoded;
  - text in `data-identity` elements equals the identity value;
  - every other non-empty text node, and `<title>`, is in the whitelist;
  - a missing expected claim or an unknown claim ID fails;
  - `<script>` and `<style>` content is ignored.
- `verify_pptx(path: Path, expected: dict[str, str], whitelist: set[str]) -> PostRenderResult`. Every body text frame must be an expected claim or whitelist text, and every claim ID in the notes must be in `expected`. This is droppable, per spec 8.7.

- [ ] **Step 1: Failing tests:**
  - `test_exact_match_passes`;
  - `test_changed_wording_fails`;
  - `test_truncated_claim_fails`;
  - `test_extra_unwhitelisted_text_fails`;
  - `test_missing_expected_claim_fails`;
  - `test_unknown_claim_id_fails`;
  - `test_escaped_entities_compare_decoded` (Review Focus 4);
  - `test_render_profile_output_passes_verification`, end to end with Task 13;
  - `test_pptx_extra_body_text_fails`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Write the explainer, then commit `feat: add post-render verification for HTML and PPTX`.

### Task 15: End-to-end run in the UI

**Files:**
- Modify: `planning/planner.py` (add `plan_and_validate`), `runs.py`, `web/routes.py`
- Create: `web/templates/{coverage,claims,outputs,receipt}.html`, `docs/explainers/planner.md`, `docs/explainers/demo-ui.md`
- Test: `tests/planning/test_plan_and_validate.py`, `tests/web/test_flow.py`

**Interfaces (Produces):**
- `plan_and_validate(owner_id, target, facts, coverage, ctx, adapter, max_rounds: int = 2) -> tuple[ContentPlan, ValidationReport]`. Rejected claims go back with their reasons, for at most 2 rounds in total. Claims still rejected after that are removed, and their IDs go in `dropped_claim_ids`.
- `RunService` methods:
  - `run_plan_and_validate(run_id)`;
  - `run_render(run_id)`, which renders both outputs, runs `verify_html` and `verify_pptx`, and stores `Output` with `post_render`. A failed verification blocks that output's files.
  - `continue_after_review(run_id)`, which runs coverage, then plan and validate, then render, in a background task.

  On a quota error, each stage leaves the run in `quota_exhausted` at the current stage, writing nothing for that stage. Pressing continue later resumes from that stage and reuses cached replies.
- Routes:
  - `POST /runs/{run_id}/continue`;
  - `GET /runs/{run_id}/coverage`;
  - `GET /runs/{run_id}/claims`;
  - `POST /runs/{run_id}/claims/try` (form: `text`, one or more `fact_ref` as `fact_id@version`). It runs `validate_claim` and shows the result inline, without adding the claim to the plan.
  - `POST /claims/{claim_id}/review` (form: `action=approve|drop`). Approve sets `approved_by_user` and re-renders. Edit is added in Task 21 if time allows.
  - `GET /runs/{run_id}/outputs`, showing the files, post-render result and the report's models and limitations;
  - `GET /outputs/{output_id}/files/{name}`, which returns 404 when the output is blocked;
  - `GET /receipts/{claim_id}?plan_id=`, a plain page with the claim, the fact version and the crop.

- [ ] **Step 1: Failing tests:**
  - `test_rejected_claim_resubmitted_with_reason`;
  - `test_drop_after_two_rounds`;
  - `test_quota_mid_run_resumes_from_stage`: a FakeAdapter raises `daily_quota` on the planner, then succeeds after continue;
  - `test_full_flow_with_fake_adapter`: photo upload, then confirm-low-impact, then confirm each high-impact fact, then continue. Assert:
    - 2 outputs with `post_render.passed`;
    - the claims page shows a rejected claim with rule and phrase;
    - `/claims/try` with "Led a production deployment" on a built prototype fact shows `rejected`;
    - a blocked output's file route returns 404.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Live run in the browser: photo CV plus the screenshot job, end to end. About 5 to 8 Flash-Lite calls and 15 to 20 local judge calls. Record the call counts per model, cache hits and time from the report.
- [ ] **Step 6:** Write `planner.md` and `demo-ui.md`, then commit `feat: wire end-to-end run from photo to validated outputs`.
- [ ] **Milestone: rough end-to-end run in the UI.** Tell the owner it's a good time to push.

### Task 16: Layer 1 normalisation and number classification [subagent-driven]

**Files:** Create `src/evident/validation/layer1/{normalise,numbers}.py`. Test: `tests/validation/layer1/test_normalise.py`, `tests/validation/layer1/test_numbers.py`.

**Interfaces (Produces):**
- `normalise_text(s: str) -> str`: NFKC, lowercase, unify Unicode dashes and quotes, strip punctuation except `.`, `%` and `$` inside numbers, collapse whitespace.
- `NumberKind` StrEnum: `metric, date, duration, aggregate, identifier`.
- `NumberMention(value: float, unit: str | None, comparator: Literal["eq", "ge"], kind: NumberKind, span: str, start: int, end: int)`.
- `find_numbers(claim_text: str, evidence_texts: list[str], lex: Lexicons) -> list[NumberMention]`:
  - number words become digits; `k`/`m` suffixes are expanded; separators are removed;
  - "over 40", "40+" and "more than 40" become `ge`.

  Classification order:
  1. A year 1990 to 2039, or month-year or season-year: `date`.
  2. A number followed by month(s), year(s) or week(s): `duration`.
  3. A number followed by an aggregate noun: `aggregate`.
  4. A number in a token sequence found verbatim in evidence text, next to an alphabetic token: `identifier`.
  5. Anything else: `metric`.

- [ ] **Step 1: Failing tests:**

```python
@pytest.mark.parametrize("text,value,unit,comp", [
    ("cut latency by forty percent", 40, "percent", "eq"),
    ("over 40% faster", 40, "percent", "ge"),
    ("40+ users", 40, "users", "ge"),
    ("1,200 requests", 1200, "requests", "eq"),
    ("2k users", 2000, "users", "eq"),
])
def test_metric_numbers(text, value, unit, comp): ...
def test_subject_code_is_identifier_not_metric():               # Review Focus 1
    ms = find_numbers("Completed 43007 Advanced Artificial Intelligence",
                      ["43007 Advanced Artificial Intelligence"], LEX)
    assert [m.kind for m in ms] == [NumberKind.identifier]
def test_version_number_is_identifier(): ...
def test_identifier_not_in_evidence_is_metric(): ...
def test_year_is_date(): ...
def test_three_years_is_duration(): ...
def test_three_projects_is_aggregate(): ...
def test_normalise_unifies_en_dash_and_case():
    assert normalise_text("Built \u2013 FastAPI") == normalise_text("built - fastapi")
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: add layer 1 normalisation and number classification`.

### Task 17: Layer 1 metric, scale and aggregate checks [subagent-driven]

**Files:** Create `src/evident/validation/layer1/checks_refs.py`. Modify `layer1/run.py` (register checks). Test: `tests/validation/layer1/test_checks_refs.py`.

**Interfaces (Produces):** `check_metrics`, `check_scale` and `check_aggregates`, each a `Check` registered in `CHECKS`. The `rule` is the function name minus `check_`. Rules as in spec 8.5 and the design's check table:
- **Metrics:** for each `metric` mention, candidates are cited metric records with the same unit, further narrowed by any metric keyword or direction word in the claim. Exactly one must remain, otherwise the claim fails as `ambiguous` or `unbound`. The value must satisfy `abs(claim) <= abs(record)`, same sign. An `other:` metric fails as `metrics_other_needs_review`.
- **Scale:** a scale noun with a number or quantity word needs a bound metric with metric `users` or `throughput`.
- **Aggregates:** the count equals the number of cited facts of the noun's kind.

- [ ] **Step 1: Failing tests:**
  - `test_latency_claim_cannot_bind_accuracy_record`;
  - `test_round_toward_zero_only`: 40% vs a 45% record passes, 50% fails;
  - `test_two_matching_records_is_ambiguous`;
  - `test_number_only_in_evidence_text_cannot_bind`;
  - `test_other_metric_needs_review`;
  - `test_thousands_of_users_without_users_metric_rejected`;
  - `test_three_projects_citing_one_project_rejected`;
  - `test_three_projects_citing_three_projects_passes`;
  - `test_subject_code_claim_passes_metric_check` (Review Focus 1, end to end).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: add layer 1 metric, scale and aggregate checks`.

### Task 18: Layer 1 scope checks [subagent-driven]

**Files:** Create `src/evident/validation/layer1/checks_scope.py`, `docs/explainers/layer1-checks.md`. Modify `layer1/run.py`. Test: `tests/validation/layer1/test_checks_scope.py`.

**Interfaces (Produces):** `check_dates`, `check_durations`, `check_ownership`, `check_deployment`, `check_skills` and `check_entities`, all registered in `CHECKS`.
- **Dates:** each claimed date falls inside at least one cited fact's `[start, end or as_of]`.
- **Durations:** months are the union of cited facts' ranges that list the skill (via aliases) or role title, with overlaps counted once and `end=None` measured to `as_of`. A claim in years must have `years * 12 <= months`.
- **Ownership / deployment:** the claim's highest lexicon rank must be `<=` the minimum rank among cited facts, where None counts as rank 1.
- **Skills:** each canonical skill in the claim appears in a cited fact's `skills` or `span_text` after alias mapping.
- **Entities:** seniority and credential words, and capitalised multi-word names that aren't skills, must appear in cited evidence text, `title` or `organisation` after alias mapping.

- [ ] **Step 1: Failing tests:**
  - `test_since_2023_rejected_when_fact_starts_2025_02`;
  - `test_three_years_python_from_20_months_rejected`;
  - `test_overlapping_facts_counted_once`;
  - `test_ongoing_role_measured_to_as_of` (Review Focus 2);
  - `test_led_on_built_fact_rejected`;
  - `test_production_on_prototype_rejected`;
  - `test_kubernetes_without_evidence_rejected`;
  - `test_js_alias_matches_javascript`;
  - `test_senior_engineer_on_graduate_role_rejected`;
  - `test_new_organisation_name_rejected`;
  - `test_plain_rephrasing_passes_layer1`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the whole suite, `uv run pytest ; uv run mypy .`. Expected: PASS. Rerun the Task 15 live flow from cache plus the new uncached judge calls, and confirm outputs still pass post-render.
- [ ] **Step 5:** Write `docs/explainers/layer1-checks.md`, then commit `feat: add layer 1 scope checks`.
- [ ] **Milestone: Layer 1 complete.** Tell the owner it's a good time to push.

### Task 19: Evaluation metrics and budget

**Files:** Create `src/evident/eval/{metrics,budget}.py`. Test: `tests/eval/test_metrics.py`, `tests/eval/test_budget.py`.

**Interfaces (Produces):**
- `clopper_pearson_upper(k: int, n: int, confidence: float = 0.95) -> float`, which is `scipy.stats.beta.ppf(confidence, k + 1, n - k)` when `k < n`, else 1.0, and raises ValueError for `n == 0`.
- `bootstrap_ci(clusters: Sequence[T], statistic: Callable[[Sequence[T]], float], n_resamples: int = 10_000, seed: int = 0, level: float = 0.95) -> tuple[float, float]`, resampling whole clusters.
- `Rate(k: int, n: int)` with `.value` and `.upper`, formatting as `"k/n (x.x%, 95% upper y.y%)"`.
- `PlannedCall(role, prompt, parts, schema)`.
- `preflight(calls: list[PlannedCall], adapter: ModelAdapter, quota: QuotaGuard) -> int` returns the number of uncached calls. It raises `StageError(code="eval_exceeds_quota", category=provider, retryable=False, detail=f"Needs {n} uncached calls, {m} left today.")` if `n > quota.remaining_today()`, before any call is made.

- [ ] **Step 1: Failing tests:**

```python
@pytest.mark.parametrize("k,n,expected", [(0, 45, 0.0644), (0, 100, 0.0295), (0, 1000, 0.00299)])
def test_clopper_pearson_zero_errors(k, n, expected):
    assert clopper_pearson_upper(k, n) == pytest.approx(expected, abs=5e-4)
def test_cp_rejects_empty(): ...
def test_bootstrap_deterministic_and_brackets_mean(): ...
def test_rate_format():
    assert str(Rate(0, 45)) == "0/45 (0.0%, 95% upper 6.4%)"
def test_preflight_counts_only_uncached(): ...
def test_preflight_refuses_before_any_call_when_over_quota(): ...
```

- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit `feat: add evaluation metrics and quota pre-flight`.

### Task 20: Extraction and grounding evaluation, RESULTS.md

**Files:**
- Create: `src/evident/eval/{extraction,grounding,results}.py`, `scripts/run_eval.py`, `docs/explainers/evaluation.md`
- Generated: `experiments/a3-slice/{claims_dev,claims_test}.jsonl`, `claims_review.md`, `RESULTS.md`
- Test: `tests/eval/test_extraction.py`, `tests/eval/test_grounding.py`

**Interfaces (Produces):**
- `match_facts(pred, truth) -> list[tuple[FactVersion | None, FactVersion | None]]`. Pairs are matched greedily one-to-one by `fuzz.token_set_ratio` of title (falling back to text), at 85 or above.
- `FieldCounts(tp, fp, fn)` and `field_counts(pairs) -> FieldCounts`. Fields are kind, title, organisation, start, end, each skill and each metric (value, unit and direction together). A field that is None on both sides isn't counted. An unmatched prediction counts its non-null fields as false positives; an unmatched truth fact counts them as false negatives.
- `f1(c) -> float`.
- `Category` StrEnum with 9 values: `wrong_number, wrong_date, inflated_ownership, inflated_deployment, unsupported_skill, wrong_entity, fake_id, wrong_aggregate, paraphrase_overstatement`.
- `LabelledClaim(claim, label: Literal["supported", "unsupported"], category: Category | None, profile_id, split: Literal["dev", "test"])`.
- `build_claim_set(seed: int = 0) -> list[LabelledClaim]`. Supported claims are template rephrasings of ground-truth facts; each unsupported claim is one mutation per category. Dev covers profiles 01 and 02 (20 unsupported, 20 supported). Test covers 03 to 05 (5 per category, so 45 unsupported, and 40 supported).
- `run_grounding(claims, adapter, threshold) -> GroundingResults`, with false accept, false reject and review rates overall, per category, and per catching layer.
- `run_eval.py --split dev|test --suite extraction|grounding|all [--write-results]`:
  - `--write-results` refuses unless `--split test`;
  - it always runs `preflight` first;
  - it records the model ID, prompt versions, the dataset version (`git rev-parse HEAD:data/synthetic/a3_enriched`), the cache-hit share and the date.

- [ ] **Step 1: Failing tests:**
  - `test_match_and_counts_on_hand_example`;
  - `test_unmatched_prediction_counts_fp`;
  - `test_claim_set_sizes_and_split_by_profile`;
  - `test_mutations_change_claim`;
  - `test_review_counts_as_not_accepted`;
  - `test_write_results_refuses_dev_split`;
  - `test_run_eval_stops_on_preflight_failure_without_calls`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Generate the claim sets. Hand-check every claim and record relabels and drops in `claims_review.md`. Commit them before any test-split model call.
- [ ] **Step 6:** Write the `RESULTS.md` section "Pass criteria (stated before running)", copying spec 9.1 and 9.2 word for word, and commit it.
- [ ] **Step 7:** Dev run, `uv run python scripts/run_eval.py --split dev --suite all`: 6 uncached Flash-Lite calls and about 40 local judge calls. Only the extraction prompt (`v2`), the judge prompt (`v2`) and `JUDGE_THRESHOLD` may change, and each change goes in the "Dev tuning log" with its dev numbers.
  - **Judge prompt v1 vs v2 (owner decision 2026-10-25):** `judge/v2` changes only the confidence line to "Return confidence: how sure you are that your verdict is correct, from 0 (guessing) to 1 (certain). It is not the probability that the claim is supported." Run the dev claims once with `judge/v1` and once with `judge/v2`, as two separate runs (`--judge-prompt v1|v2`), each with its own false accept, false reject and review rates.
  - The winner is chosen on the dev split only: fewer false accepts first, then fewer inflated claims routed to review instead of rejected, then fewer false rejects. Set it as the judge prompt version in code before Step 8, and log the choice and reason.
  - The smoke-test claims (Task 3a) are not used for this choice.
- [ ] **Step 8:** Test run, `uv run python scripts/run_eval.py --split test --suite all --write-results`: 24 uncached Flash-Lite calls and about 85 local judge calls (all 109 against quota if the judge fell back).
  - If the pre-flight refuses, tell the owner the counts and stop. Don't retry. It resumes after the quota resets, from the cache.
  - `RESULTS.md` gets:
    - extraction P/R/F1 per path and per template, with tp/fp/fn and bootstrap intervals over 4 profiles;
    - grounding rates as `Rate` strings, overall, per category and per catching layer;
    - cost-estimate and latency observations;
    - pass or fail against each criterion;
    - the spec 13 limitations, including "only 5 underlying profiles", "simulated photos" and the judge limitation from `limitations(config)`;
    - which judge prompt version (`v1` or `v2`) the reported numbers use, with a pointer to the dev tuning log entry that chose it.
  - A fail is reported as a fail.
- [ ] **Step 9 (optional, only if the owner asks):** `uv run python scripts/compare_spare.py --n 5`. It re-runs up to 5 dev extraction examples and up to 10 dev planner or coverage calls on `gemini-3.8-flash` (at most 15 calls, through the spare's own guard of 20 a day), and writes a side-by-side "Spare comparison (observation only)" section in `RESULTS.md`. Dev data only; it never feeds a reported rate.
- [ ] **Step 10:** Write the explainer, then commit `docs: add A3 slice evaluation results`.
- [ ] **Milestone: evaluation done.** Tell the owner it's a good time to push.

### Task 21: Polish

**Files:**
- Modify: `render/templates/profile.html.j2`, `render/profile_html.py`, `web/templates/*`, `web/static/app.js`, `web/routes.py`
- Create: `docs/explainers/renderers-and-receipts.md`
- Test: `tests/render/test_profile_html.py` (extend), `tests/web/test_flow.py` (extend)

**Interfaces:**
- `render_profile_pdf(html, out, claim_links: dict[str, str]) -> Path` wraps each claim span in `<a href="{receipt_base}/receipts/{claim_id}">`, which Chromium keeps as PDF link annotations. This is droppable.
- `app.js` adds a receipt popover on `[data-claim-id]` clicks, fetching `/receipts/{id}?partial=1`.
- `POST /claims/{claim_id}/review` with `action=edit` and `text` makes a new claim version, revalidates it, re-renders, and notes stale outputs in the run message.
- Styling for the profile, deck theme and UI pages. The verification whitelist is updated for any new template copy.

- [ ] **Step 1: Failing tests:**
  - `test_pdf_has_link_annotation_per_claim`;
  - `test_receipt_partial_returns_fragment`;
  - `test_edit_review_claim_revalidates_and_rerenders`;
  - `test_styled_profile_still_passes_post_render`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS. Then a live run from cache.
- [ ] **Step 5:** Write the explainer, then commit `feat: polish outputs, receipts and demo pages`.

### Task 21a: Recorded-run demo mode

Spec 10.1. Native execution.

**Files:**
- Create: `src/evident/web/demo.py`, `scripts/mark_recorded.py`, `web/templates/_recorded_banner.html`
- Modify: `web/app.py`, `web/routes.py`, `web/templates/base.html`, `docs/explainers/demo-ui.md`
- Test: `tests/web/test_demo.py`

**Interfaces (Produces):**
- `RecordedRun(run_id: str, owner_id: str, recorded_at: str, models_by_role: dict[str, str])`, a plain dataclass, not a contract, stored at `var/demo/recorded.json`.
- `mark_recorded(repo, run_id, config, out=Path("var/demo/recorded.json")) -> RecordedRun`. It refuses unless the run is `done` and both outputs passed post-render.
- `load_recorded(path) -> RecordedRun | None`.
- With `settings.demo` true:
  - `GET /` redirects to the recorded run;
  - every page renders the banner "Recorded run from {recorded_at}. Replayed from stored results; no models are called on this page.";
  - `POST /runs`, `/continue`, fact edits and claim review actions return 403 with "Disabled in demo mode", so the recording can't change;
  - only `POST /runs/{run_id}/claims/try` calls a model, and its result panel is labelled "Live";
  - every role except `judge` is cache-only (Task 3).
- If demo mode is on but no recording exists, the app refuses to start with a clear message.

- [ ] **Step 1: Failing tests:**
  - `test_mark_recorded_refuses_unfinished_run`;
  - `test_demo_pages_show_recorded_banner`;
  - `test_demo_mode_blocks_mutating_routes`;
  - `test_demo_pages_make_no_model_calls` (FakeAdapter records zero calls while rendering every stage page);
  - `test_try_box_calls_judge_live_and_is_labelled_live`;
  - `test_demo_without_recording_refuses_to_start`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Before recording, check that the judge prompt version in code is the one Task 20 chose. A new prompt version changes cache keys, so recording with the wrong version would replay the wrong verdicts. Owner step, after the final prompts are settled: run the full pipeline once in the UI, then `uv run python scripts/mark_recorded.py --run-id <id>`. Then start with `$env:EVIDENT_DEMO = "1"; uv run uvicorn evident.web.app:main --factory --port 8000` and click through every stage. Expected: every page loads instantly with the banner, and the quota files show no new Flash-Lite calls.
- [ ] **Step 6:** Update `docs/explainers/demo-ui.md`, then commit `feat: add recorded-run demo mode with live claim box`.

### Task 22: Submission pack

**Files:**
- Create: `scripts/build_examples.py`, `scripts/build_zip.py`, `README.md`, `docs/report-material.md`
- Generated (committed): `examples/`
- Test: `tests/scripts/test_build_zip.py`, `tests/scripts/test_build_examples.py`

**Interfaces (Produces):**
- `build_examples(out: Path = Path("examples"), profile: str = "student_profile_03", template: str = "sidebar", job: str = "screenshot") -> None` writes:
  - `input_cv_photo.jpg` and `job_ad_screenshot.png`;
  - `facts.json`;
  - `coverage.json` and `coverage.md`;
  - `profile.pdf`, `profile.html` and `deck.pptx`;
  - `validation_report.json`;
  - `inflated_claim_rejected.md`;
  - `RESULTS.md`;
  - `README.md`, saying what each file is, that everything is synthetic, and that facts were confirmed automatically for repeatability.

  It reuses the cache, so a rebuild after the Task 15 run costs few calls.
- `build_zip(group_id: str, out_dir: Path = Path("dist")) -> Path`. It writes `A3_Code_<group_id>.zip` from `git ls-files` plus `examples/`, minus the spec 12a exclusions, then scans it.
- `scan_zip(path: Path, env_path: Path = Path(".env")) -> list[tuple[str, str]]` returns (file, pattern name) pairs only, never matched text. The patterns are those in spec 12a, plus the in-memory `.env` values. On any hit the zip is deleted and the script exits 1.

- [ ] **Step 1: Failing tests:**
  - `test_zip_excludes_sensitive_paths`;
  - `test_planted_fake_key_detected_and_zip_deleted`;
  - `test_env_value_detected_without_printing`;
  - `test_clean_zip_passes`;
  - `test_examples_folder_complete` (FakeAdapter).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** `uv run python scripts/build_examples.py`, then inspect each file.
- [ ] **Step 6:** Write `README.md` with these PowerShell steps, then follow it in a fresh clone (`git clone . $env:TEMP\evident-check`) and fix whatever doesn't work as written:
  1. Prerequisites (Python 3.12, uv, Tesseract, Git, Ollama), with `winget` commands.
  2. `uv sync`.
  3. `uv run playwright install chromium`.
  4. `Copy-Item .env.example .env` and set `GEMINI_API_KEY` (a free AI Studio key).
  5. `ollama pull qwen3:4b-instruct-2507-q4_K_M`, and check `[limits]` against the reader's own AI Studio rate-limit page, since limits differ per project.
  6. `uv run pytest`.
  7. `uv run uvicorn evident.web.app:main --factory --port 8000`.
  8. `uv run python scripts/run_eval.py --split test --suite all`.
  8a. Demo mode: `$env:EVIDENT_DEMO = "1"` before starting the UI, after marking a recorded run.
  9. `uv run python scripts/build_examples.py`.
  10. `uv run python scripts/build_zip.py --group-id <GroupID>`.
- [ ] **Step 7:** Write `docs/report-material.md`, covering:
  - the architecture as text, plus Mermaid source;
  - the multimodal parts;
  - every prompt with its name and version;
  - 6 to 8 snippets with `file:line`: metric binding, the outcome table, post-render comparison, the box conversion, the quota guard, Clopper-Pearson and the zip scan;
  - the `RESULTS.md` tables;
  - the model per role;
  - the spec 13 limitations.

  Run the writing-style check over it and all explainers.
- [ ] **Step 8:** `uv run python scripts/build_zip.py --group-id TEST`. Expected: exit 0. List the contents and confirm no excluded path is present.
- [ ] **Step 9:** Commit `docs: add submission pack, README and report material`.
- [ ] **Milestone: A3 slice complete.** Tell the owner it's a good time to push.

---

## Stretch stages

Optional, in this order. Each starts only after the previous one is finished, tested and committed, and after the owner says go. Each gets detailed tasks appended in the format above before it starts.

- **S1. Interview rehearsal (audio):**
  - questions from required requirements graded strong or partial;
  - answer upload (`.webm`, `.wav` or `.m4a`);
  - transcription with word timestamps through a new role `transcription` on a free-tier model checked against the docs;
  - feedback via the design's rehearsal prompt, with statements checked by Layer 1 and the judge;
  - no voice, accent, emotion or confidence comments;
  - explainer.
- **S2. LinkedIn kit:**
  - headline, About and experience from the same validated plan;
  - new `OutputType.linkedin_kit`, which needs owner approval and a schema_version bump;
  - `verify_html`;
  - explainer.
- **S3. Portfolio site:**
  - a static local-only site from the validated plan, with whole-source crops in receipts; never published, since redacted crops (Decision 10) aren't built;
  - `OutputType.portfolio_site`, which needs the same approval and bump;
  - explainer.
