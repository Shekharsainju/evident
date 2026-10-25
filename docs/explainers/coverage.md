# Coverage

## What it does

Coverage compares a target job ad with the user's confirmed facts and grades each requirement as strong, partial, weak or gap, citing the fact versions behind each grade. The code is in `src/evident/coverage/`, and `RunService.run_coverage` in `src/evident/runs.py` runs it for a run.

1. `extract_requirements` splits the job ad (pasted text, or a screenshot sent as an image) into requirements. Each gets an ID (`req_01`, `req_02`, ...) and a category: required, preferred, responsibility or boilerplate.
2. `grade_requirements` grades every requirement that is not boilerplate, in one model call, against all confirmed facts.
3. `check_coverage_gate` checks the result. The matrix is stored only if the gate passes.

## Why it's built this way

- **Only confirmed facts count** (design: Pipeline 4; invariants section 1). A grade may cite only a confirmed fact version. The caller passes confirmed facts, and `grade_requirements` filters again, so an extracted, rejected or superseded fact can't reach the grader even by mistake.
- **Evidence is cited as `fact_id@version`.** Each fact goes to the grader as one line, `fact_id@version: text | skills | dates`. The version matters because an edit creates a new version, and a grade must point at the exact one it used.
- **One call for all requirements** (spec 8.3; P3). A profile has 10 to 25 confirmed facts, so the grader sees all of them and no retrieval step is needed. One call per ad saves free-tier quota.
- **Boilerplate is not graded.** Perks and team culture lines are not requirements a candidate can meet or miss, so they get no row.
- **The model's reply is untrusted.** It is parsed through a loose draft schema and then checked:
  - a requirement with no returned row becomes a gap, with the rationale "not graded by model", so the miss is cautious and visible;
  - an unrecognised grade is treated the same way;
  - a row for an unknown requirement, two rows for one requirement, or a malformed evidence reference fails the stage with `coverage_gate`.
- **The gate fails closed** (invariants section 1). It rejects a graded row with no evidence, a gap row that cites evidence, and any citation that is not a confirmed fact at that exact version. A failed gate writes nothing and the run stops in a `failed` state. It is a validation error, so it is never retried automatically.
- **Untrusted text stays inside tags.** The ad goes in `<job_ad>` and the facts in `<evidence>`. Each fact and requirement is flattened to a single line, so a fact that contains a line break can't pose as another entry. Tag-like text inside user content is neutralised by `render_prompt`.
- **The run waits for review.** While any high-impact fact is still `extracted`, `run_coverage` leaves the run in `waiting_for_user` with "Confirm or reject the highlighted facts first." and makes no model call.
- **Quota stops are clean.** A quota error sets `quota_exhausted` at the coverage stage and writes nothing. Pressing continue later reuses the cached replies.

## How the model is used

- **Requirements:** role `requirements` (`gemini-3.5-flash-lite`), prompt `requirements/v1`. One call per job ad, with an image part first when the ad is a screenshot.
- **Grading:** role `coverage` (`gemini-3.5-flash-lite`), prompt `coverage/v1`. One call per ad.
- **Cost:** two uncached calls per target. Invalid JSON gets one retry through the adapter, then the stage fails.
- The prompts ask the model to cite "fact_ids". The code relies on the `fact_id@version` form shown in the evidence lines and rejects anything it can't parse.

## Limits

- **Grades are the model's judgement.** The gate checks that citations are real and consistent. It does not check that a "strong" grade is deserved. The labelled coverage set in the evaluation phase is where agreement with human grades gets measured.
- **No retrieval.** If a profile grows far beyond 25 facts, all facts in one prompt will stop fitting well.
- **A single bad row stops the whole matrix.** An inconsistent row fails the stage instead of being repaired, so the user sees a clear error. Retrying costs another call.
- **Free-text parsing is strict about references only.** Requirement text is trimmed and flattened but not otherwise checked against the ad, so a model that rewords a requirement is not caught.
- **Unrecognised categories are dropped.** A requirement the model labels with an unknown category is skipped. If every item is skipped, the stage fails with `no_requirements`.
- **No live check has been run for this explainer.** The tests use a fake adapter. The live run on the job screenshot (plan Task 10, step 5) still has to be done by hand.

## Example

The Graduate AI Engineer ad (`data/synthetic/jobs.jsonl`) lists "Python with NumPy, Pandas, scikit-learn, and PyTorch". Profile 01 has the confirmed project fact `student_profile_01_gt07` (a small web API with a Python service layer, Flask and SQLite).

The grader is shown the requirement and the fact as:

```
req_03: Python with NumPy, Pandas, scikit-learn, and PyTorch (required)
student_profile_01_gt07@1: Built a small web API that stores course information ... | Python, Flask, SQLite, REST APIs, pytest, Git | 2025-03 to 2025-06
```

A row that cites `student_profile_01_gt07@1` as partial evidence passes the gate. The same row citing `student_profile_01_gt07@2` fails with `coverage_gate`, because version 2 is not a confirmed fact. A `gap` row that still lists that fact also fails. This example is illustrative: it shows what the gate accepts and rejects, not a recorded model reply.
