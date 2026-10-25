# Planner

## What it does

The planner turns confirmed facts and the coverage matrix into claims for the two outputs, the visual profile and the interview deck. Each claim cites exact fact versions and has a section, an emphasis (1 to 5), the outputs it belongs in and the transformations a renderer may apply. The code is in `src/evident/planning/planner.py`.

1. `build_plan` makes one planner call and turns the reply into a `ContentPlan`. Drafts that can't become a valid claim are dropped here.
2. `plan_and_validate` validates every claim (Layer 1, then the judge), sends rejected claims back to the planner once, and returns the plan with its `ValidationReport`. `RunService.run_plan_and_validate` stores both only once both exist.

## Why it's built this way

- **The reply is untrusted** (invariants sections 1 and 2). A draft is dropped if it has empty text, an emphasis outside 1 to 5, an unknown output type, a malformed `fact_id@version`, or a duplicate text. Logs record only the draft index and the reason, never claim text. Every kept claim still goes through Layers 1 and 2, so nothing here can pass a claim.
- **The gap rule.** A claim is kept only if at least one fact it cites backs a requirement graded strong, partial or weak. The coverage gate stops gap rows from citing evidence, so this is how "never write a claim for a gap" is enforced. Its effect on real runs is still being checked.
- **Feedback rounds** (spec 8.4). Rejected claims go back to the planner with their text, the Layer 1 rule and phrase, and the judge's verdict and phrase, under "Rejected claims and reasons". At most 2 rounds run in total. Round 2's plan replaces round 1's. Claims still rejected after the last round are listed in `dropped_claim_ids` and stay in the stored plan, so the claims page can show what was rejected and why. Renderers and receipts skip them.
- **Stable claim IDs.** IDs are `c_001`, `c_002`, ... A draft whose text exactly matches a claim in the previous round keeps its ID. New texts get the next free number. If the matching claim's evidence, outputs or transformations changed, it keeps the ID but gets a new version, so an earlier validation result can't be mistaken for it. An unchanged claim (same ID and version) reuses its earlier result and isn't judged again.
- **Narratives.** A speaker-note narrative names its parent by repeating the parent's exact text. It goes only on the deck, may not be expanded again, and is dropped if its parent is missing or not on the deck.
- **The deck is chosen here, before validation.** Flash-Lite often tags no claim for the deck. If it tags none, every claim becomes a deck candidate (the fallback). Candidates are grouped into slides the way `render_deck` groups them and cut to at most 4 slides of 3 claims, highest emphasis first. So the stored output types are the ones that were validated, and the deck draws exactly the deck claims that pass. When the fallback or the cut applies, the log gives counts only.

## How the model is used

- Role `planner` (`gemini-3.5-flash-lite`), prompt `planner/v1`. One call per round, so one or two per run.
- Confirmed facts go inside `<evidence>` (text, source span, dates, ownership, deployment, skills, metrics) and the coverage matrix inside `<job_ad>`. The renderer limits are stated in the prompt.

## Limits

- **Feedback sits outside a data tag.** In `planner/v1` the rejected-claims block comes before `<evidence>`, in instruction position. Quotes and bars are neutralised, and Layers 1 and 2 still check everything. **P5** in `docs/decisions-proposed.md` proposes a planner v2 that moves the feedback into a data tag and asks for deck claims. It is pending the owner's decision, changes cache keys, and must land before the demo recording.
- **Round 2 rewords freely.** The planner often rewrites every claim, so all of them are judged again.
- **The deck is chosen before validation.** If every chosen deck claim is then rejected, the deck is blocked even when other claims passed.
- **Narratives are rare.** No live run so far has produced one.

## Example

In run `r_f83cb650cf5b` (profile 01 photo, Graduate AI Engineer screenshot), the final plan had 5 claims: `c_008` and `c_009` (Education), `c_010` and `c_011` (Projects), and `c_012` (Skills). The planner tagged the first four for the deck itself, so the fallback didn't fire. If it had, `c_012` would have been on the deck too. `c_008` went to user review and was approved; the rest passed. The profile showed all 5 claims and the deck 4, and both passed post-render verification.
