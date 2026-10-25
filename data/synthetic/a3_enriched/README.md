# A3 enriched profiles (fictional)

This folder holds a copy of the five A1 synthetic profiles with fictional fields added for the 43007 A3 slice. **Everything added here is fictional and exists only for A3 testing.** Like the A1 data, it must stay marked as synthetic whenever it is shown outside the classroom.

The A1 files in `data/synthetic/` are never modified. `tests/eval/test_datasets.py` checks their SHA-256 hashes.

## Files

- `overlay.json`: the hand-written additions, keyed by `document_id`. It is the only place the fictional values live, so they can be audited in one file.
- `profiles.jsonl`: the A1 profiles merged with the overlay by `scripts/build_enriched.py`. It is generated: edit the overlay and rebuild instead.
- `ground_truth/<document_id>.json`: the facts a perfect extractor would return for each profile. They are used only to score extraction and are never passed to the pipeline. A test checks that no pipeline module refers to ground truth.

Rebuild with `uv run python scripts/build_enriched.py`.

## Fields added

On each profile:

- `education_start`: 2024-02 for every profile (third year in 2026).
- `expected_graduation_month`: 2026-11 for every profile.
- `enrichment_note`: says the additions are fictional and points here.

On every project and experience entry:

- `start` and `end` (YYYY-MM). `end` is `null` for ongoing roles, which are profile 01's retail role, profile 04's IT support role and profile 05's cadetship.
- `ownership` (contributed, built or led), matched to the existing wording. Where an entry says both "built" and "contributed" (team projects), it uses `contributed`, the more cautious reading.
- `deployment` (concept, prototype, internal or production). It is `null` for roles that build no software (retail, peer volunteering, IT support).
- `metrics`: 0 to 2 single-figure metric records per entry, and 1 to 3 per profile.

## Metric sentences added to descriptions

Each metric's `span_text` appears word for word in its entry's description, so it shows on the rendered CV.

| Profile | Entry | Sentence added |
|---|---|---|
| 01 | Team Course Planner | Profiling cut timetable clash checks to under 2 seconds. |
| 01 | AI Coursework Prototype | Tested it on 20 sample student questions. |
| 02 | Coursework Retrieval Assistant | Evaluated it on 25 test queries. |
| 02 | Text Classification Study | The best setting reached 84% accuracy on the held-out test set. |
| 03 | Student Services Dashboard | The dashboard covered 1,200 survey responses. |
| 03 | Peer Learning Volunteer | Supported 30 first-year students across the semester. |
| 04 | Reliable Course Service | The new tests raised test coverage to 80%. |
| 04 | IT Support Assistant | Logged 40 support requests in the first month. |
| 05 | Software Development Cadet | Added 25 automated tests to the backend. |

## What ground truth contains

For each profile:

- one education fact for the degree;
- one education fact per current subject and coursework highlight;
- one fact per experience entry;
- one fact per project;
- one skill fact per technical skill.

The summary, activities, links and contact details are not career facts under the extraction prompt, so they are left out.
