# Ingestion: photos and scans (vision)

## What it does

It turns a photo or scan of a CV into extracted facts, each with a source location on the image. `ingest_photo` in `src/evident/ingestion/vision.py`:

1. Sends the image to the vision model with the extraction prompt.
2. Converts the model's boxes to pixels.
3. Checks each box with OCR.
4. Stores each fact as version 1 with status `extracted`.

Nothing is confirmed here. The user reviews every fact before it can be used (see `user-review.md`).

## Why it's built this way

- **The image is untrusted** (design: Security, privacy and data lifecycle; invariants section 4). The image goes to the model alongside the shared preamble. The prompt text says the document is the attached image and keeps it inside `<document>` tags. The model gets no tools.
- **The model's output is untrusted too.** It comes back in loose draft schemas (`src/evident/ingestion/drafts.py`). Each field is then checked against the strict contracts, and anything that doesn't fit is dropped rather than guessed:
  - an unknown ownership or deployment value becomes empty;
  - a date that isn't `YYYY-MM` becomes empty;
  - a metric name outside the vocabulary becomes `other:<name>`, which always goes to user review;
  - a metric with an invalid direction is dropped;
  - a draft with an unknown kind is skipped.
- **Boxes are checked, not believed** (design: Evidence receipts; spec 8.1). The model returns `box_2d` as `[ymin, xmin, ymax, xmax]` on a 0 to 1000 scale. `box_2d_to_pixels` converts it to `[x0, y0, x1, y1]` in pixels and clamps it to the image. Tesseract then reads the crop (with a 4% margin) and fuzzy-matches it against the claimed `span_text`. A box is kept only if the match score is 80 or more. Otherwise the source falls back to the whole image with `bbox_verified: false`, so a receipt never points at the wrong spot.
- **Confidence is the OCR match score divided by 100**, not a number the model reports about itself.

## How the model is used

- **Calls:** one call per image, on role `extraction_vision` (`gemini-3.5-flash-lite`, 45 s timeout), with prompt `extraction/v1`. The reply is constrained to the `ExtractionDraft` JSON schema and validated against it.
- **Invalid JSON:** gets one retry with the validation error included, then the stage fails.
- **Caching:** replies are cached on disk, so re-running the same photo costs no quota.

## Limits

- **Granularity.** On the first live run (profile 01, classic template, 2026-10-25), the model returned 5 facts where the ground truth has 16:
  - it put all 8 skills into one skill fact;
  - it didn't split the coursework into separate facts.

  Prompt changes are made only on the development split in Task 20.
- **OCR on photos is noisy.** In the same run, 2 of 5 boxes verified. The others pointed at the right region but scored 62 to 77 against the threshold of 80, so they fell back to the whole image. The threshold is a starting value; it is not tuned.
- **Simulated photos.** The test photos are simulated from rendered PDFs, which is easier than real phone photos.
- **One image only.** Multi-page photo sets aren't handled; each image is one document.

## Example

`data/synthetic/a3_enriched/rendered/student_profile_01_classic_photo.jpg` (synthetic) produced:

- facts: 1 education, 1 experience, 2 projects and 1 skill fact listing 8 skills;
- 4 facts with dates and 2 with metrics;
- two verified boxes: the skills line scored 100, and the first project scored 94.
