# Phase 1 Layer 1 fixes: gate results

Spec: `docs/specs/phase-1-improvements.md` section 7. Plan: Tasks 4 to 8 (Task 5 runs after Task 8).

## Pass criterion (stated before running)

For each fix, `scripts/layer1_diff.py --base <commit before the fix> --extra probes/task-<n>.jsonl` exits 0: no unsupported claim that the old code rejected passes under the new code. Every claim the new code passes and the old code rejected is listed and checked by hand. A fresh reviewer approves the fix against `cv-builder-invariants`.

## Deviation from spec 7 step 5 (owner approved 2026-11-06)

Spec 7 step 5 asks for a comparison on the 125 dev claims plus about 10,000 generated claims. The generator yields 946 distinct claims over dev profiles 01 to 05 and seeds 0 to 49. More seeds only add duplicates, because each template allows few distinct mutations. The shortfall is accepted for this phase. To make up for it, each fix adds at least 40 probes aimed at the rule it changes, at least half of them unsupported, in `probes/task-<n>.jsonl`. These are dev data only.

What this costs: the generated set covers the A3 template shapes and little else, so a false-accept path in a claim shape the templates and the targeted probes both miss would not show up in the gate. The fresh reviewer is asked to hunt for such paths, and each one found becomes a regression test.

## Gates

Counts are claims whose Layer 1 outcome changed between the base and the fix. K: unsupported, newly passing (must be 0). S: supported, newly passing. F: supported, newly failing. U: unsupported, newly failing.

| Task | Fix | Base | Fix commit | Probes (targeted, of them unsupported) | K | S | F | U | Gate output |
|---|---|---|---|---|---|---|---|---|---|
| 6 | sentence-start entities (7.2) | 4478384 | fix round 1 (see git log) | 2291 (1350, 940) | 0 | 303 | 0 | 172 | `task-6-diff.txt` |
| 6 | same, against the A3 code | v0.1-a3 | fix round 1 (see git log) | 2291 (1350, 940) | 0 | 303 | 0 | 172 | `task-6-diff-vs-a3.txt` |

Task 6 is pending review; this row is final only once the review approves.

Task 6 S = 303: all supported probes with a full name in the evidence (Our, My, Her, A before the name, or a verb opener after a bullet, dash or line break), which the old code rejected. Checked by hand. Against 49e9317 the counts are K 0, S 0, F 0, U 490 (`task-6-diff-vs-49e9317.txt`). Standing probes: every `probes/*.jsonl` is loaded by every gate run.
