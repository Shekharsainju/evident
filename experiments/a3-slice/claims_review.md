# Claim set hand check (Task 20, Step 5)

Checked by the builder (Claude), not the owner, on 2026-10-31, before any model call for
this evaluation. Every claim in `claims_dev.jsonl` (40) and `claims_test.jsonl` (85) was
read against the ground-truth facts it cites.

## Result

- **Relabelled:** none.
- **Dropped:** none.
- **Sizes:** dev 20 supported and 20 unsupported (profiles 01 and 02; two per category,
  three for `fake_id` and `paraphrase_overstatement`); test 40 supported and 45 unsupported,
  5 per category (profiles 03 to 05).

## Changes to the generator made during the check

Both were made before any model call, from reading the claims, not from any result.

1. **Article:** role claims read "Worked as a IT Support Assistant". The template now picks
   "a" or "an" ("an IT Support Assistant").
2. **Spread of mutations:** in the first draft every test `paraphrase_overstatement` and
   `fake_id` claim came from a skill claim, so each category tested one sentence shape. The
   unsupported picks now rotate across the templates a mutation came from, as the
   supported picks already did. The categories now draw on project, role, degree, metric,
   aggregate and skill claims where each applies.

## Notes for reading the results

- **Supported claims that quote metric wording.** Metric claims copy the evidence span,
  for example "Cut timetable clash checks to under 2 seconds" and "Raised test coverage to
  80%". The ground truth records these metrics with direction `absolute`, while "cut" and
  "raised" are direction words in the Layer 1 lexicon. If Layer 1 rejects them, that is a
  real false reject of a faithful claim, and it is reported as one.
- **`fake_id`** claims keep faithful text but cite a fact ID that doesn't exist (`_gt99`)
  or a version that doesn't exist (`@2`). They are unsupported because the cited evidence
  doesn't exist.
- **`wrong_date`** claims move a start date one year earlier, which claims a longer span
  than the evidence.
- **`wrong_number`** claims double counts, add 10 points to percentages and halve
  latencies, so each changed number is a stronger claim than the evidence, never a weaker
  one it would still imply.
- **Identical text across profiles** (for example the same degree at the same university
  for profiles 01 and 02) is expected: the claims cite different facts.
- **Category labels come from construction.** The claim set is template-built, so it is
  more regular than real planner output.
