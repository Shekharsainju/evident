# Demo UI

## What it does

A small FastAPI and Jinja app (`src/evident/web/`) that runs the whole slice on localhost: pick a CV and a job ad, review the facts, then grade, plan, validate and render. The pages are start, run status, facts, coverage, claims (with a live "try an inflated claim" box), outputs and receipts. `RunService` in `src/evident/runs.py` runs the stages in a background task; the run page refreshes every 2 seconds.

## How to run the demo

In PowerShell, from the repository root:

1. `ollama list` shows `qwen3:4b-instruct-2507-q4_K_M` (ID `0edcdef34593`). If Ollama isn't running, start `ollama serve` in another window.
2. `.env` has `GEMINI_API_KEY`. Demo mode is off: `Remove-Item Env:EVIDENT_DEMO -ErrorAction SilentlyContinue`.
3. **Warm up the judge.** The first judge call after Ollama starts took about 48 s in the first live run. Run one claim through the Live box, or one full run, a few minutes before presenting.
4. `uv run uvicorn evident.web.app:main --factory --port 8000`, then open http://127.0.0.1:8000.
5. Choose `student_profile_01_classic_photo` and the job screenshot, then start. Profile 01 is the dev split.
6. On the facts page:
   - click "Confirm all other facts";
   - confirm each highlighted fact;
   - click "Continue".
7. Show Coverage, Claims (type an inflated claim in the Live box and tick its fact) and Outputs.

## Why it's built this way

- **No queue** (spec 7.2). Stages run in order in a background task and write a status record. Continue marks the run pending before the task starts, and a per-run lock stops double clicks from starting two pipelines.
- **Clean resumes.** A quota stop writes nothing for that stage. A run that already has a plan and report renders again without re-planning, so approvals survive. Changing a fact sends the run back to review, so Continue grades again, and fact changes are refused while a run is busy.
- **Only verified files are served.** The file route serves only names listed in the output, after checking ownership, that post-render verification passed, and that the output isn't superseded by a newer render. An output with no validated claims is blocked with a reason, not served empty.
- **Outputs show no identity.** No name or contact details, until a source for a display name is decided.

## How the model is used

The UI calls no model itself. Each run uses Flash-Lite for extraction, requirements, coverage and planning, and the local judge for each claim. The Live box runs Layer 1 and the judge on the typed claim only.

## Live runs (profile 01 photo, job screenshot, 2026-10-26)

| Run | Flash-Lite calls | Judge calls | Result |
|---|---|---|---|
| `r_661b1eefc7c6` | 5: extraction, requirements, coverage, planner ×2 | 11 (6, then 5) | Both outputs passed; deck had 2 claims |
| `r_d9b001c86216` | 3: coverage, planner ×2 (extraction and requirements from cache) | 9 (6, then 3) | Profile passed with 3 claims; **deck had only its title slide** |
| `r_f83cb650cf5b` | 3 (extraction and requirements from cache) | 12 (7, then 5) | Both passed; profile 5 claims, deck 4 |

- **Timings in `r_661b1eefc7c6`.** Vision extraction took about 9 s. After Continue: requirements 3 s, coverage 4 s, then the first verdict about 48 s after the planner reply (Ollama loading the model). Later verdicts took about 0.6 s each, and the whole second round about 6 s. With a warm judge, `r_f83cb650cf5b` went from coverage to a stored plan in about 16 s.
- **The empty deck.** In `r_d9b001c86216` the planner tagged no claim for the deck. `render_deck` drew only the title slide, and `verify_pptx` passed it because there was nothing to fail. The fix: `build_plan` now chooses the deck claims itself (see `planner.md`), and an output with no validated claims is blocked. `r_f83cb650cf5b` was the first run after the fix.
- Quota: these runs and one other used 13 of the 500 Flash-Lite calls for that quota day (Pacific date 2026-10-25).

## Limits

- One local owner and no auth; localhost only.
- A run left "running" by a server restart can't be resumed from the UI.
- The profile HTML downloads instead of opening in the browser.
- Recorded-run demo mode (Task 21a) isn't built yet, so every demo run calls the models.
