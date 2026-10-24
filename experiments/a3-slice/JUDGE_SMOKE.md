# Local judge smoke test (plan Task 3a)

Decides whether the local Ollama judge (P1) is fast and accurate enough to use before any task depends on it. This is a go/no-go check on 10 obvious, hand-written claims, not an evaluation. The grounding evaluation is in `RESULTS.md`.

## Set-up

- **Judge:** `qwen3:4b-instruct-2507-q4_K_M` via Ollama, digest `0edcdef34593`. Temperature 0, `num_ctx` 4096, JSON schema = the `JudgeVerdict` contract.
- **Prompt:** `judge/v1` with the shared preamble `preamble/v1`.
- **Claims:** `experiments/a3-slice/judge_smoke_claims.jsonl`.
  - 5 supported (faithful rephrasings).
  - 5 inflated, one each: ownership, deployment, number, skill, paraphrased overstatement.
  - All names and organisations are fictional.
- **Machine:** owner's laptop, RTX 3050 Ti Laptop GPU with 4 GB VRAM.

## Pass criteria (stated before running, 2026-10-25)

1. **Accuracy:**
   - at least 9 of 10 verdicts correct, where an inflated claim counts as correct only as `overstated` or `unsupported`; **and**
   - 0 of 5 inflated claims judged `supported` with confidence of 0.8 or more (that would be a false accept under the outcome table).
2. **Speed:** after one discarded warm-up call, median of 8 s or less per judgement, and maximum of 20 s or less. The 20 s cap keeps a judgement inside the 30 s text timeout with margin.
3. **Fit:** the model runs fully on the GPU (Ollama reports 100% of the loaded model in VRAM).

If any criterion fails, the judge falls back to `gemini-3.5-flash-lite` and P1's same-family limitation applies.

## Results

Run on 2026-10-25 with `uv run python scripts/judge_smoke.py`. Ollama 0.40.10; the model was unloaded first, cache bypassed.

| # | Label | Kind | Verdict | Confidence | Seconds | Correct |
|---|---|---|---|---|---|---|
| 1 | supported | faithful | supported | 1.00 | 2.8 | yes |
| 2 | supported | faithful | supported | 1.00 | 2.8 | yes |
| 3 | supported | faithful | supported | 0.95 | 3.4 | yes |
| 4 | supported | faithful | supported | 1.00 | 2.9 | yes |
| 5 | supported | faithful | supported | 1.00 | 2.8 | yes |
| 6 | inflated | ownership | overstated | 0.60 | 2.9 | yes |
| 7 | inflated | deployment | overstated | 0.10 | 3.5 | yes |
| 8 | inflated | number | overstated | 0.80 | 2.8 | yes |
| 9 | inflated | skill | overstated | 0.60 | 3.1 | yes |
| 10 | inflated | paraphrase | overstated | 0.15 | 3.6 | yes |

- Warm-up call, including the cold load, took 10.5 s and is discarded.
- **Accuracy:**
  - 10/10 correct;
  - false accepts 0/5 (no inflated claim judged supported at any confidence).

  **Pass.**
- **Speed:** median 2.9 s, maximum 3.6 s (n = 10, warm). **Pass.**
- **Fit:** Ollama reports 66% of the loaded model in VRAM and 34% in system memory, at `num_ctx` 4096 with a loaded size of 3.5 GB. **Fail.**

**Outcome against the criteria as stated: fail (criterion 3 only).** The owner decides whether to keep the local judge (P1).

### Observation for Task 12 (not a criterion)

On the inflated claims the confidence values (0.10 to 0.80) look like the probability that the claim is supported, not confidence in the verdict. Under the outcome table, an `overstated` verdict below 0.8 goes to user review, not rejection. That is safe, since nothing passes, but most inflated claims would land in review rather than being rejected. The judge prompt's "Return a confidence from 0 to 1" is ambiguous, so a v2 wording ("your confidence that the verdict is correct") should be tested on the dev split.
