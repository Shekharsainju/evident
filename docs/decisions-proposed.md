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

## P5: Planner prompt v2: feedback inside a data tag, and deck claims asked for

- **Status:** proposed on 2026-10-26, found in the Task 11 review. Approved by the owner on 2026-11-03 and folded into `planner/v2` with the Skills and Coursework instruction (phase 1 spec, section 6).
- **Design says:** every prompt wraps user content in tags marked as data, and the shared preamble tells the model never to follow instructions inside `<document>`, `<job_ad>`, `<transcript>` or `<evidence>` ("Prompts"; Security, "Untrusted input").
- **What the slice does now:** in `src/evident/prompts/planner/v1.txt`, the `{feedback}` placeholder sits before `<evidence>`, outside every data tag. In a second planning round it holds each rejected claim's text, the Layer 1 rule and phrase, and the judge's verdict and offending phrase. Claim text and phrases come from fact text and model output, so they are untrusted, yet they appear where the model reads instructions.
- **What already limits it:** `render_prompt` neutralises data tags inside every field, so the feedback cannot open or close a tag. Each entry is kept on one line, and quotes and bars in quoted values are replaced so an entry cannot pose as extra reasons. Every claim the planner returns still goes through Layers 1 and 2, so an injected claim is rejected or sent to user review, never passed.
- **Proposal:** add `planner/v2.txt` that moves the feedback into its own `<evidence>` block, introduced by a fixed line such as "Earlier claims rejected by validation, with the reasons:". Reusing `<evidence>` means the preamble and `DATA_TAG` stay as they are. The planner moves to `v2`, and the prompt version appears in reports as usual. A test checks that feedback text appears only inside a data tag.
- **Also in v2 (added 2026-10-26):** ask for deck claims. In live run `r_d9b001c86216`, Flash-Lite tagged no claim for `interview_deck`, so the deck had only its title slide. `planner/v1.txt` names both outputs and the deck limits, but never says the deck needs claims, and narratives are optional. v2 would add one instruction: tag each claim with every output it belongs in; the interview deck needs at least one claim per content slide; speaker-note narratives may be added for deck claims. Until then, `build_plan` falls back to tagging the highest-emphasis claims for the deck within its limits (at most 4 slides of 3 claims), and an output with no validated claims is blocked rather than served. Both stay in place after v2 as a safety net.
- **Alternative:** a new `<rejections>` tag. It reads more clearly, but it changes the shared preamble, `DATA_TAG` and every prompt that uses the preamble, so the cached replies for all roles would be invalidated.
- **Cost:** one prompt version bump covers both changes. The planner's cache keys change, so the next run makes one or two new Flash-Lite planner calls, and every cached planner reply from v1 stops being used. It needs a live run to check that the deck is filled without the fallback.
- **Revisit when:** the owner decides. It must land before the recorded demo run (Task 21a), because recording with v1 and switching afterwards would replay stale planner replies.

## P6: Judge model and threshold for phase 1 (pending dev comparison)

- **Status:** pending. Filled in by phase 1 plan Task 10 from the dev comparison in `experiments/p1-judge-dev/RESULTS.md`, then put to the owner.
- **Candidates:** `qwen3:4b-instruct-2507-q4_K_M` (current, P1) and `qwen3:8b-q4_K_M` (digest `500a1f067a9f`, thinking off), both local through Ollama. Both are Qwen family, so the comparison measures size, not family. Both are a different family from Gemini, so Decision 2 holds.
- **Relation to P1:** P1 ends when phase 0 experiment 2 runs. This comparison only partly meets that: two candidates on 125 dev claims, not 200 adversarial and 200 supported.

## P7: Metric direction for "cut ... to under N" (owner decision)

- **Status:** owner decision of 2026-11-03. It reverses the owner decision of 2026-10-31 (A3 RESULTS, "Known limitation: metric direction") to leave the rule unchanged.
- **Change:** when a direction word is followed by "to" and an optional bound word ("under", "below", "less than", "over", "above", "more than") before the number, the number states an end value and may bind to an `absolute` record as well as one with the matching direction. "Cut latency by 2 seconds" still needs a `decrease` record. Phase 1 spec 7.3.
- **Guard:** P8 applies to this path too, so "cut ... to under 1 second" against a 2 second record fails.

## P8: Lower-is-better absolute metrics round away from zero

- **Status:** approved by the owner on 2026-11-03. Moved into the Decision log (row 13) and the Deterministic check rules Metrics row of `docs/design.md`.
- **Found:** while writing the phase 1 spec, a probe on the A3 code showed that with a cited record `latency, absolute, 2 seconds`, Layer 1 passes "Clash checks run in 1 second" and "take 0.5 seconds". The round-toward-zero rule assumes a bigger number is the stronger claim, which is wrong for latency, cost and error rate stated as absolute values.
- **Rule:** for a record with direction `absolute` whose metric is lower-is-better (a list in `config/lexicons.toml`: latency, cost, error_rate), the claimed value may round away from zero, never toward it. Records with direction `decrease` or `increase` store the size of the change, where a bigger number is the stronger claim, so they keep round toward zero.
- **Tests:** "1 second" and "0.5 seconds" against the 2 second record fail; "2 seconds" passes.

## P9: Revert Task 6 (sentence-start entities); keep the gap as a documented limitation

- **Status:** owner decision of 2026-11-07. Recorded in the Decision log (row 14) of `docs/design.md`.
- **What happened:** phase 1 spec 7.2 tried to keep an unknown first word of a sentence in the entity name run, dropping only listed openers. Three review rounds each found a new false-accept path that neither 4478384 nor v0.1-a3 had: a single word left after a dropped opener passed unchecked (49e9317); a digit-led word ("1Password", "1st") passed as a figure, and a leftover word matched lowercase prose (ac3ca43); a leftover of two or more words matched lowercase prose after a bullet, dash or line break (262f0d7, and present since 49e9317). The rules piled up exceptions faster than probes could cover them.
- **Decision:** revert the Layer 1 source to 4478384 with new commits, not by rewriting history. Keep every rejection test and probe. Cases the 4478384 code still accepts become strict xfails, so a later fix shows up as XPASS. Keep the gate tool changes (standing probes, UTF-8 `--report`).
- **Limitation kept:** at a plain sentence start, or after ".", ";" or ":", the first word of a capitalised run is dropped and a single word left is not checked, so "Goldman Sachs backed the planner." passes Layer 1. A run kept whole can match lowercase prose ("The Answer" against "the answer"); this shape was found while writing round 2 probes, not by a review. The Layer 2 judge covers these claims; nothing auto-passes when the judge is unavailable.
- **Future attempt:** start from a stricter design: every capitalised word in the claim must appear in the evidence (after alias mapping). Measure newly failing supported dev claims before adopting it. Supported sentences that must keep passing are in `tests/eval/test_layer1_probe.py` and the `revert_r2_supported` probes.
