# evident

evident is a multimodal CV builder that only says what your evidence proves. It reads a CV (as a PDF or a phone photo) and a job ad (as text or a screenshot), lets you confirm the facts it found, then writes a tailored profile and interview deck in which every claim is checked against its source before it can appear.

Built for UTS 43007 Advanced Artificial Intelligence, Assessment 3, as an extension of our Assessment 1 CV Builder.

## Why

AI CV tools often inflate: "contributed to a project" becomes "led a team", and numbers appear that were never in the original. evident takes the opposite approach. Every claim must cite confirmed facts, pass two independent checks, and link back to the part of the document it came from.

## How it works

1. **Ingestion.** PDFs are read from their text layer. Photos and screenshots are read by a vision model (Gemini 3.5 Flash-Lite), which returns each fact with the image region it came from. Tesseract OCR confirms each region before it is used as a receipt; if it cannot, the receipt shows the whole image, marked approximate.
2. **Review.** You confirm, edit or reject each fact beside its source. Facts with dates, metrics, qualifications, higher ownership or deployment levels, or an approximate location must be confirmed one by one.
3. **Coverage.** The job ad is split into requirements, and each is graded strong, partial, weak or gap against your confirmed facts.
4. **Planning.** The model proposes claims for the target job. Each claim must cite the exact fact versions it relies on.
5. **Validation.** Every claim passes two checks:
   - **Layer 1:** deterministic rules for fact IDs, numbers, dates, durations, ownership, deployment, named entities, skills and counts.
   - **Judge:** a separate local model (Qwen3 4B through Ollama) decides whether the evidence supports the wording.

   If both pass, the claim is used. If either rejects it with confidence, it is blocked. If they disagree, or the judge is unsure, you decide.
6. **Rendering.** Validated claims become a one-page profile (HTML and PDF) and an interview deck (PPTX) with talking points in the speaker notes.
7. **Post-render check.** The exported files are checked again: every claim must match its validated wording, and no untraced text may appear.

The web app also has a **"Try an inflated claim"** box: type any claim, tick the facts it cites, and see both checks decide, with reasons.

## Results

On a locked test of synthetic profiles 02 to 05, with pass criteria set before running:

| Measure | Result |
| --- | --- |
| Inflated claims accepted | 0 of 45 |
| True claims rejected | 13 of 40 |
| Extraction F1, digital PDFs | 0.930 |
| Extraction F1, simulated photos | 0.902 |

Full method and numbers: `experiments/a3-slice/RESULTS.md`.

## Tech stack

- Python 3.12, FastAPI, Jinja, Pydantic v2
- Gemini 3.5 Flash-Lite (free tier) for vision, coverage and planning
- Qwen3 4B through Ollama for the judge, running locally
- pdfplumber and Tesseract OCR for text and box checks
- Playwright for HTML to PDF, python-pptx for decks
- uv, pytest, ruff and mypy

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Tesseract OCR, available on your PATH
- Ollama, with the judge model:
  ```
  ollama pull qwen3:4b-instruct-2507-q4_K_M
  ```
- A free Gemini API key from Google AI Studio (no billing needed)

The judge runs on a GPU with 4 GB of memory, or on the CPU if there is none (slower).

## Setup

1. Clone the repository and switch to the project folder.
2. Copy `.env.example` to `.env` and set your key:
   ```
   GEMINI_API_KEY=your-key-here
   ```
3. Install dependencies and the browser used for PDF export:
   ```
   uv sync --locked
   uv run playwright install chromium
   ```
4. Run the tests:
   ```
   uv run pytest
   ```

## Run

1. Make sure Ollama is running.
2. Start the app:
   ```
   uv run uvicorn evident.web.app:main --factory --port 8000
   ```
3. Open http://localhost:8000.
4. Choose a synthetic CV (for example `student_profile_01_classic_photo`) and a job ad, and click **Start**.
5. Confirm the extracted facts, then click **Continue: grade, plan, validate and render**.
6. Review any claims sent to you, then open the outputs.

The free tier allows 15 Gemini requests a minute and 500 a day. evident spaces its calls, caches every reply on disk, and refuses a run that would exceed the daily limit. A rate-limit error is never retried.

## Evaluation

The evaluation harness is `scripts/run_eval.py`. It measures extraction F1 against ground truth and claim grounding on development and test splits, and writes `experiments/a3-slice/RESULTS.md`. See `docs/explainers/evaluation.md` for how to run it and how the splits work.

## Project layout

```
src/evident/
  contracts/      Pydantic data contracts (facts, plans, validation)
  ingestion/      PDF text, vision and OCR box checks
  coverage/       requirement extraction and grading
  planning/       claim planner
  validation/     Layer 1 rules, judge, outcome table, post-render checks
  render/         profile and deck renderers, templates
  models/         Gemini and Ollama adapters, quota guard, cache
  eval/           evaluation datasets and metrics
  web/            web app routes
  prompts/        versioned model prompts
config/           model settings, lexicons, aliases, template text
data/synthetic/   A1 dataset and fictional enrichment overlay
examples/         sample profile and deck from a full run
experiments/      evaluation results
docs/             design, spec, plan, decisions and explainers
tests/            test suite
```

## Data and privacy

All profiles and job ads are synthetic, from the Assessment 1 dataset. Fictional dates and figures are added in a separate overlay; the original A1 files are unchanged. Every output is marked as synthetic. Google may use free-tier requests to improve its products, so do not upload real personal data.

## Limitations

- Results come from 5 synthetic profiles and simulated phone photos.
- The small local judge rejects too many true claims.
- Some entity checks still have gaps, for example two names joined by "and".
- Profiles and decks are short, because only validated claims are shown.
- This is a working slice of a larger design; the full design adds a database job queue, per-user isolation and sign-in.

## Documentation

- `docs/design.md`: full product design
- `docs/specs/a3-slice.md` and `docs/plans/a3-slice.md`: what was built and how
- `docs/explainers/`: one plain-English explainer per component
- `docs/decisions-proposed.md`: decisions and exceptions for this build

## Team
| Member | Contribution |
Shekhar Sainju | System design, repository setup, data contracts, model layer, PDF and photo ingestion, fact review, evaluation, integration |

| Tuan Hung Hoang | Content planner, UI wiring, evaluation metrics, explainers |

| Bofang Yang | Validation (Layer 1 checks, judge, outcome table), post-render verification |

| [White] | Coverage grading, profile and deck renderers |


