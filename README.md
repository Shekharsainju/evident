# Evident: evidence-grounded CV Builder (A3 slice)

Evident takes a CV (PDF or photo) and a job ad (text or screenshot), and produces a visual
profile PDF and an interview deck in which every claim links to the fact that supports it.
Claims pass through rule checks and a separate judge model, and each output is verified again
after rendering.

**All data in this repository is synthetic.** The CVs, job ads and people are fictional.
Results are pilot results on 5 underlying profiles: see
`experiments/a3-slice/RESULTS.md`.

## Setup on Windows

Run every command in PowerShell from the repository root.

### 1. Install the prerequisites

Python 3.12 is installed by `uv` in step 2 if it is missing.

```powershell
winget install --id astral-sh.uv -e
winget install --id Git.Git -e
winget install --id UB-Mannheim.TesseractOCR -e
winget install --id Ollama.Ollama -e
```

Open a new PowerShell window afterwards so the new commands are on `PATH`. The Tesseract
installer does not add itself to `PATH`, so add it for this window (use the same folder if
you start a new one):

```powershell
$env:Path += ";C:\Program Files\Tesseract-OCR"
```

### 2. Install the Python dependencies

```powershell
uv sync
```

### 3. Install the browser used for PDF rendering

```powershell
uv run playwright install chromium
```

### 4. Create your settings file

```powershell
Copy-Item .env.example .env
```

Open `.env` and set `GEMINI_API_KEY` to a free key from Google AI Studio. Never commit
`.env`. The free tier is all this project uses: do not enable billing.

### 5. Pull the local judge model and check your limits

```powershell
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

Compare the `[limits]` sections in `config/models.toml` with your own AI Studio rate-limit
page, because limits differ per project. Lower the values if yours are lower.

### 6. Run the tests

```powershell
uv run pytest
```

No test calls a model unless you add `-m live`.

### 7. Start the UI

```powershell
uv run uvicorn evident.web.app:main --factory --port 8000
```

Open <http://127.0.0.1:8000>.

### 8. Run the evaluation

```powershell
uv run python scripts/run_eval.py --split test --suite all
```

This checks your remaining free-tier quota first and makes no call if the run won't fit
today. The first run uses 24 Flash-Lite calls and about 85 local judge calls. Adding
`--write-results` rewrites the results section of `RESULTS.md`.

### 8a. Demo mode

**Not available yet.** Demo mode needs the recorded-run feature (plan Task 21a), which is not
built, so with `EVIDENT_DEMO=1` nothing replays a recording and uncached Gemini calls stop
with an error. When Task 21a lands, the steps are:

```powershell
uv run python scripts/mark_recorded.py --run-id <run id>
$env:EVIDENT_DEMO = "1"
uv run uvicorn evident.web.app:main --factory --port 8000
```

### 9. Rebuild the examples

```powershell
uv run python scripts/build_examples.py
```

This runs the whole pipeline on `student_profile_03` and needs steps 4 and 5. It writes
`examples/` only if the run finishes, both outputs pass post-render verification and the
inflated claim is rejected; otherwise it stops and leaves `examples/` unchanged. The
extraction and job ad replies come from the cache after the first run, but coverage, planning
and judging are called again each time, because their prompts contain new fact IDs.

### 10. Build the submission zip

```powershell
uv run python scripts/build_zip.py --group-id <GroupID>
```

This writes `dist/A3_Code_<GroupID>.zip` from `git ls-files` plus `examples/`, without local
settings, caches or run state. It then scans every file for key-like strings. On any hit it
deletes the zip, names the file and pattern, and exits 1. It also stops if any of the 12
`examples/` files is missing, so run step 9 first. Commit first as well: uncommitted new files
are not included.

To test the zip without a full `examples/` folder, add `--allow-incomplete-examples`. Never
submit a zip built that way.

## Layout

| Path | What it holds |
|---|---|
| `src/evident/` | The pipeline: ingestion, review, coverage, planning, validation, rendering, UI |
| `config/` | Model roles and limits, lexicons, aliases, template copy |
| `data/synthetic/` | The synthetic profiles, job ads, rendered CVs and ground truth |
| `experiments/a3-slice/` | Claim sets, run records and `RESULTS.md` |
| `examples/` | One complete run |
| `docs/` | Design, spec, plan, component explainers and report material |
