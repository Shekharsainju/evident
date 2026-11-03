# Held-out claim set hand check (phase 1, Task 3)

Checked by the builder (Claude), not the owner, on 2026-11-03, before any model call on this
set. Every claim in `claims_test.jsonl` (166) was read against the ground-truth facts it
cites (`data/synthetic/heldout_p1/ground_truth/`) and against its label.

This is the locked test set. After this commit nothing tunes on it, and no dev or tuning
script accepts a profile from 06 to 10 (`require_dev`, `tests/eval/test_splits.py`).

## Result

- **Relabelled:** none.
- **Dropped:** none.
- **Sizes:** 80 supported and 86 unsupported, from profiles 06 to 10, seed 2.
- **Unsupported per category:** 10 each for `wrong_number`, `wrong_date`,
  `inflated_ownership`, `unsupported_skill`, `wrong_entity`, `fake_id`, `wrong_aggregate`
  and `paraphrase_overstatement`; **6** for `inflated_deployment`.
- **Why 6:** a deployment claim is built only from a project that is not already in
  production. The five profiles have 7 projects and one is in production (profile 08's
  Booking Page Speed-up), so 6 are eligible. The builder takes what exists rather than
  inventing projects. The spec allows this (4.3).

## Changes to the generator made during the check

Both were made before any model call, from reading the claims, not from any result. Neither
changes the A3 claim files (a test pins the SHA-256 of the default A3 build).

1. **Singular aggregate:** profiles 06, 08 and 09 have one project, so the supported
   aggregate read "Worked on one projects: X." The template now writes "one project", and
   the wrong-aggregate mutation of it writes "two projects: X" (not "two project"). The
   mutation still cites one fact, so it is still an overcount.
2. **Number word seven:** profile 09 has six subjects, so its wrong-aggregate mutation needs
   "seven". `NUMBER_WORDS` gained 7.

## Certification and award facts (profile 10)

Profile 10's ground truth has facts of kind `certification` and `award`. The claim builder
selects facts by kind (project, experience, education, skill), so these two are **skipped**:
no supported or unsupported claim cites them, and nothing crashed. No new templates were
added. The held-out claims therefore don't test certification or award wording. That is a
coverage gap of this set, stated here and in RESULTS.md.

## What was read

- **Supported (80):** each is a template rephrasing of the cited fact: ownership verb,
  deployment phrase, skills, dates, organisation and metric sentence all match the fact.
  Role claims with an open end say "to the present". One project runs May 2025 to May 2025,
  and the claim says so, which is true if awkward. Degree and subject claims repeat across
  profiles (same university and subjects), expected, since they cite different facts.
- **Unsupported (86):** each differs from its source claim in exactly the way its category
  says, and the changed content is stronger than the evidence.
  - `wrong_number`: counts doubled, percentages plus 10, latency halved (1.5 s to 0.75 s).
  - `wrong_date`: start moved one year earlier.
  - `inflated_ownership`: built to led, contributed role to "Led a team as the".
  - `inflated_deployment`: prototype or concept or internal moved two steps up (never
    beyond production).
  - `unsupported_skill`: a skill from a list of outside skills, checked absent from the
    profile.
  - `wrong_entity`: employer or university replaced by a different fictional one.
  - `fake_id`: faithful text citing `_gt99` or version 2, neither exists.
  - `wrong_aggregate`: count one higher than the cited facts.
  - `paraphrase_overstatement`: faithful text plus a vague boast, or "Is an expert in X".

## Notes for reading the results

- Metric claims copy the evidence span ("Raised test coverage of the service to 70%") and
  the ground truth records direction `absolute`. A Layer 1 rejection of these is a real
  false reject, as in A3.
- Category labels come from construction, so the set is more regular than real planner
  output.
