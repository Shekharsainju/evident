# Proposed decisions

Proposals and temporary exceptions to the Decision log in `docs/design.md`. Nothing here changes the design until it is approved and moved into the Decision log.

## P1: Local open-weights judge for the A3 slice (replaces the same-family exception)

- **Status:** approved by the project owner on 2026-10-25. It replaces the earlier P1 (same-family Gemini judge, approved 2026-10-24), which is withdrawn unless the fallback below is triggered.
- **Decision 2 says:** the entailment judge comes from a different model family than the generator. "Models and fallbacks" lists a Claude or open-weights model as the primary judge.
- **What the slice does:** the Layer 2 judge is `qwen3:4b-instruct-2507-q4_K_M` (Qwen family, digest `0edcdef34593`), run locally through Ollama on the owner's RTX 3050 laptop GPU (4 GB VRAM). Gemma models are excluded because they are Google's family. This follows Decision 2, so it is not an exception to it.
- **What is still a limitation:** a 4B quantised model is much smaller than the judges the design has in mind, and its confidence is self-reported and uncalibrated. Every validation report and the evaluation results state both.
- **Gate before use:** a smoke test (plan Task 3a) measures time per judgement and accuracy on 10 obvious claims (5 supported, 5 inflated), with pass criteria written before it runs.
- **Fallback:** if the smoke test fails, the judge role moves to `gemini-3.5-flash-lite` and the same-family limitation from the old P1 applies again: the judge is then the same model as the planner. The mitigations are those of the old P1: a separate judge prompt that sees only the claim and the cited evidence, model-free Layer 1 first, and low confidence or Layer 1/2 disagreement routed to user review. Which way the smoke test went is recorded here and in every report.
- **Smoke test outcome (2026-10-25):** accuracy 10/10 and false accepts 0/5 (pass); median 2.9 s, max 3.6 s (pass); GPU fit 66% (fail, a criterion added by the builder). The owner chose to keep the local judge. Details in `experiments/a3-slice/JUDGE_SMOKE.md`.
- **Ends when:** phase 0 experiment 2 runs, which compares two judge candidates as the design requires.

## P3: Free-tier Gemini 3.5 Flash-Lite for every Gemini role in the A3 slice (temporary exception)

- **Status:** approved by the project owner on 2026-10-24 and revised on 2026-10-25 (Flash-Lite replaces 3.8 Flash; the judge moves to P1).
- **Design says:** Flash-class for vision extraction; Pro-class for planner and coverage grading ("Models and fallbacks").
- **Exception:** one free-tier model, `gemini-3.5-flash-lite`, handles text and vision extraction, job ad requirements (text and screenshots), coverage and planning. No paid usage. The ID, stable status, image input and structured output were checked against Google's model page and pricing page on 2026-10-25.
- **Spare model:** `gemini-3.8-flash` is configured as a spare only. No role uses it by default. It may be called only by an explicit comparison script on a few examples, at the owner's request.
- **Free-tier limits** (Evident project, AI Studio, copied by the owner on 2026-10-25):
  - `gemini-3.5-flash-lite`: 15 RPM, about 250K TPM, 500 RPD;
  - `gemini-3.8-flash`: 5 RPM, about 250K TPM, 20 RPD.
- **Consequences, stated as limitations in every report:**
  - planner and coverage quality may be lower than with a Pro-class model, and lower again than with 3.8 Flash;
  - Google's pricing page says free-tier content is used to improve Google's products, so only synthetic data may be sent (real CVs are already out of scope);
  - free-tier rate limits cap how many evaluation and demo runs fit in a day.
- **Mitigations:** every reply is cached on disk; Flash-Lite calls are spaced at least 4.5 s apart; a local quota guard sized to 500 a day stops before the limit and reports it instead of retrying; coverage grades all requirements in one call; evaluation runs check their call count against the remaining quota before starting. With the judge local, a demo run needs only about 5 to 8 Flash-Lite calls.
- **Ends when:** the slice is submitted, or phase 0 experiment 2 runs.

## P2: Playwright instead of Gotenberg for HTML to PDF in the A3 slice (temporary exception)

- **Status:** approved by the project owner on 2026-10-24 as a temporary exception for the A3 slice only.
- **Design says:** Gotenberg (headless Chrome) converts HTML to PDF; Playwright print-to-PDF is the listed fallback ("Models and fallbacks").
- **Exception:** the slice uses the fallback, Playwright print-to-PDF, as its only converter. No PDF/UA or veraPDF check runs on these PDFs.
- **Why:** Gotenberg needs Docker Compose services, which are out of scope before 2026-10-28. Playwright is already needed for screenshots and HTML checks.
- **Ends when:** the Docker Compose services are set up after the slice, or phase 4 ("First outputs") starts, whichever comes first.

## P4: Deck speaker notes cite fact versions without source text or location in the A3 slice (temporary exception)

- **Status:** approved by the project owner on 2026-10-25 as a temporary exception for the A3 slice only.
- **Spec and plan say:** speaker notes list each slide's claim IDs, plus the source text and location for each (spec, deck output). Plan Task 13 gives the line format `claim_id: fact_id@version, page or image, span_text`.
- **Why it cannot be met as planned:** the planned `render_deck(plan, report, identity, out)` receives no fact versions, so it has no page, image or span text to print. This is a gap in the plan, found in the Task 13 review.
- **Exception:** `render_deck` keeps the planned signature. Each `Sources:` line reads `claim_id: fact_id@version, page and span in the receipt`, where the trailing text is fixed template copy from `config/template_copy.toml`.
- **Consequences:** the notes alone do not show the source text or where in the document it came from; the fact ID and version are the only link back.
- **Ends when:** the deck renderer is next changed after the slice, or phase 4 ("First outputs") starts, whichever comes first. The fix then is to pass the cited fact versions into `render_deck`.

## P5: Planner feedback on rejected claims goes inside a data tag (proposal)

- **Status:** proposed on 2026-10-26, found in the Task 11 review. Not approved; the prompt is unchanged until the owner decides.
- **Design says:** every prompt wraps user content in tags marked as data, and the shared preamble tells the model never to follow instructions inside `<document>`, `<job_ad>`, `<transcript>` or `<evidence>` ("Prompts"; Security, "Untrusted input").
- **What the slice does now:** in `src/evident/prompts/planner/v1.txt`, the `{feedback}` placeholder sits before `<evidence>`, outside every data tag. In a second planning round it holds each rejected claim's text, the Layer 1 rule and phrase, and the judge's verdict and offending phrase. Claim text and phrases come from fact text and model output, so they are untrusted, yet they appear where the model reads instructions.
- **What already limits it:** `render_prompt` neutralises data tags inside every field, so the feedback cannot open or close a tag. Each entry is kept on one line, and quotes and bars in quoted values are replaced so an entry cannot pose as extra reasons. Every claim the planner returns still goes through Layers 1 and 2, so an injected claim is rejected or sent to user review, never passed.
- **Proposal:** add `planner/v2.txt` that moves the feedback into its own `<evidence>` block, introduced by a fixed line such as "Earlier claims rejected by validation, with the reasons:". Reusing `<evidence>` means the preamble and `DATA_TAG` stay as they are. The planner moves to `v2`, and the prompt version appears in reports as usual. A test checks that feedback text appears only inside a data tag.
- **Alternative:** a new `<rejections>` tag. It reads more clearly, but it changes the shared preamble, `DATA_TAG` and every prompt that uses the preamble, so the cached replies for all roles would be invalidated.
- **Cost:** the planner's cache keys change, so the next demo run makes one or two new Flash-Lite planner calls.
- **Revisit when:** the owner decides, or before the recorded demo run (Task 21a), whichever comes first.
