# Held-out profiles 06 to 10 (fictional)

This folder holds five new synthetic profiles written for phase 1 of the CV Builder (spec `docs/specs/phase-1-improvements.md`, section 4). **Everything here is fictional and exists only for testing.** Like the A1 and A3 data, it must stay marked as synthetic whenever it is shown outside the classroom.

These profiles are the **locked test split** for phase 1. Nothing is tuned on them. After their claim set is committed, nothing reads or runs on them until the locked run.

## Files

- `source_profiles.jsonl`: five hand-written records in the A1 format (the same fields as `data/synthetic/student_profiles.jsonl`). Names, organisations, links and contact details are invented. Every employer and issuer name starts with "Fictional".
- `overlay.json`: dates, ownership, deployment, metric records and metric sentences, in the A3 overlay format. Profile 10 also has `certifications` and `awards`, which the A1 format has no field for.
- `profiles.jsonl`, `ground_truth/`, `rendered/`: generated. Rebuild with:
  - `uv run python scripts/build_enriched.py --dataset heldout_p1`
  - `uv run python scripts/render_cvs.py --dataset heldout_p1`
  - `uv run python scripts/make_photos.py --dataset heldout_p1`

The CV templates are shared with `data/synthetic/a3_enriched/templates/`. Photo seeds are 100 times the profile number plus the template index (600 to 1002).

## The five profiles

| Profile | Shape |
|---|---|
| 06 | Career changer: six years as a pharmacy assistant before studying |
| 07 | Gap year between school and university, with gap-year volunteering |
| 08 | More work experience: a part-time developer role, an internship and a casual job, overlapping |
| 09 | Mostly skills from coursework, one small project, no work experience |
| 10 | Holds a certification and an award |

Ground truth follows the A3 rules (one fact per degree, subject, role, project and skill), plus one fact per certification and award.
