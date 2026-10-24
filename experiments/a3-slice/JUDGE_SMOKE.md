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
