# Judge and outcome table

## What it does

Layer 2 asks a model whether the cited evidence proves the claim. `run_judge` in `src/evident/validation/judge.py` builds the prompt, calls the `judge` role through the model adapter and returns a `JudgeVerdict`: `supported`, `overstated` or `unsupported`, the offending phrase, a corrected phrasing and a confidence from 0 to 1. `validate_claim` in `outcome.py` runs Layer 1, then the judge, then combines the two with the outcome table and returns a `ClaimValidation` with the outcome, both layers' results and a list of plain-language reasons.

The outcome table (spec 8.5, settled at plan approval):

| Layer 1 | Judge | Outcome |
|---|---|---|
| pass | supported, confidence at or above 0.8 | passed |
| pass | overstated or unsupported, confidence at or above 0.8 | rejected |
| pass | any verdict below 0.8, or a judge error | user review |
| fail | overstated, unsupported, below 0.8, or a judge error | rejected |
| fail | supported, confidence at or above 0.8 | user review (the layers disagree) |

Nothing auto-passes: a claim passes only in the first row.

## Why it's built this way

- **A different model family** (design Decision 2, P1). The planner is Gemini, so the judge is Qwen, run locally through Ollama. Correlated errors between a generator and a judge of the same family are the reason the design insists on this. If the smoke test had failed, the role would have moved to Gemini and `limitations` would say so in every report.
- **The judge sees only the cited facts.** `evidence_block` lists each cited fact as `fact_id@version`, its text, source span, dates, ownership, deployment, skills and metric records, inside an `<evidence>` tag after the shared preamble. Facts that are not cited never reach the prompt, and a cited fact that is superseded, rejected or another user's is left out too, so it cannot argue for the claim. The judge therefore answers "does this evidence prove this claim", not "is this claim true of the person".
- **The judge always runs, even after a Layer 1 failure.** A rejection then carries both reasons, and the disagreement row exists: if Layer 1 fails but the judge is confidently supportive, the claim goes to the user instead of being silently dropped. A quota or connection error is recorded as `judge_error` and the claim goes to user review (or stays rejected), never passed (invariants section 1: nothing auto-passes when the judge is unavailable).
- **Constrained output, then validated again.** Ollama is given the `JudgeVerdict` JSON schema as its `format`, and the reply is still parsed through the strict Pydantic contract, with one retry on invalid JSON. Model output is untrusted until it has passed the contract.
- **Threshold 0.8, inclusive.** `JUDGE_THRESHOLD` lives in `judge.py` and is tuned only on the dev split (spec 9). The confidence is the model's own number and is not calibrated, which is one of the two limitation lines.
- **`limitations` is derived from `config/models.toml`**, not typed by hand, so the report line names the judge that was actually used: the small local Qwen line when the provider is Ollama, the same-family line if the fallback is in place, plus the free-tier Flash-Lite line (P3) in both cases.
- **Reasons are sentences.** Each Layer 1 failure becomes `rule: detail`, and the judge line gives the verdict, the confidence, the offending phrase and whether it fell below the threshold. The claims page shows these as they are.

## How the model is used

- **Role:** `judge`, `qwen3:4b-instruct-2507-q4_K_M` (digest `0edcdef34593`) through the local Ollama HTTP API, temperature 0, 4096-token context, 512 output tokens, 30 s timeout. Prompt `judge/v1`.
- **Cost:** one local call per claim, zero quota. Replies are cached on disk by model digest, prompt and parts, so re-validating an unchanged claim is free.
- **Latency on a MacBook (Apple silicon), measured 2026-10-25:** 1.8 to 2.4 s per judgement warm, 6.9 s for the first call that loads the model.
- **Logging:** only the claim ID and the error code are logged on failure. Claim text never goes to the log.

## Limits

- **A 4B quantised model is a small judge.** The design has larger judges in mind for phase 0. The live smoke run got the clear cases right (see the example) but its confidence is a self-reported number: it gave 0.999 to supported claims and 0.0 to an obviously inflated one, which is not a calibrated probability.
- **"Judge error" covers several things**: Ollama not running, a wrong model digest, a timeout, or (on the Gemini fallback) a quota stop. The code and detail are in `judge_error`; all of them route to user review rather than passing.
- **The judge can be stricter than the facts warrant.** In the smoke run it marked "Completed 43007 Advanced Artificial Intelligence" as overstated because the fact lists the subject as current (no end date). That is a correct reading of the evidence, but a planner that writes "Studying ..." would pass; the wording matters.
- **One judgement per claim, no self-consistency sampling.** Repeated calls at temperature 0 return the same answer, so the threshold is the only lever against a confidently wrong verdict. The disagreement row and user review are the safety net.
- **The evidence block is plain text.** A fact whose text contains something that looks like an instruction is still inside `<evidence>` tags and the preamble tells the model to ignore it, but a small model may follow it anyway. Layer 1 and post-render verification are the guarantees that do not depend on the judge behaving.

## Example

Live run, 2026-10-25, against the local judge, cited fact as in `layer1-checks.md`:

| Claim | Layer 1 | Judge | Outcome |
|---|---|---|---|
| Built a timetable clash checker in Python and Flask | pass | supported 0.999 | passed |
| Profiling cut timetable clash checks to under 2 seconds | pass | supported 0.999 | passed |
| Cut timetable clash checks to under 1 second | pass | overstated 0.80, phrase "under 1 second" | rejected |
| Led a production timetable system serving thousands of users | fail (scale, ownership, deployment) | overstated 0.00 | rejected |
| Architected the university's timetable platform in Python | fail (ownership) | overstated 0.10 | rejected |

The reasons stored for the fourth claim:

```
scale: 'thousands of users' has no users or throughput metric record.
ownership: 'led' is rank 3; the cited facts allow rank 2.
deployment: 'production' is rank 4; the cited facts allow rank 2.
judge: overstated (confidence 0.00), phrase: Led a production timetable system serving thousands of users, below the 0.80 threshold
```

With the judge switched off (Ollama stopped), the first claim becomes `user_review` with the reason `judge error: judge_unavailable: Ollama is not reachable or returned a bad response.` It does not pass.
