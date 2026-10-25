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
- **Boxes are checked, not believed** (design: Evidence receipts; spec 8.1). The model returns `box_2d` as `[ymin, xmin, ymax, xmax]` on a 0 to 1000 scale. `box_2d_to_pixels` converts it to `[x0, y0, x1, y1]` in pixels and clamps it to the image.
- **How the check works.** Tesseract reads exactly that region, upscaled 2x with a blank white border so a tight crop reads well. The text it finds is matched against the claimed `span_text`:
  - spans of 3 words or fewer must appear as whole words, so "Git" can't match "GitHub";
  - longer spans use a fuzzy match.

  A box is kept only if the score is 80 or more. The stored box is exactly the region that was checked.
- **Failing boxes fall back.** Otherwise the source falls back to the whole image with `bbox_verified: false`, so a receipt never points at the wrong spot.
- **Why no padding.** The check used to widen the crop by 4% of the image. Dev tuning on 2026-10-25 showed that this let a box pointing at a *neighbouring* line pass:

  | Check | Wrong-box pairs accepted |
  |---|---|
  | 4% image margin (old) | 56/720 |
  | Exact region, as now | 2/720 |

  The exact region is the fail-closed choice.
- **Confidence is the OCR match score divided by 100**, not a number the model reports about itself.

## How the model is used

- **Calls:** one call per image, on role `extraction_vision` (`gemini-3.5-flash-lite`, 45 s timeout), with prompt `extraction/v2`. v2 requires one fact per role, project, qualification, course subject and listed skill; v1 let the model merge them. The reply is constrained to the `ExtractionDraft` JSON schema and validated against it.
- **Invalid JSON:** gets one retry with the validation error included, then the stage fails.
- **Caching:** replies are cached on disk, so re-running the same photo costs no quota.

## Limits

- **Granularity, after dev tuning on profile 01's three photos (2026-10-25):**

  | Prompt | Ground-truth facts found | Precision |
  |---|---|---|
  | `extraction/v1` | 29/48 | 29/29 |
  | `extraction/v2` | 48/48 | 48/49 |

  This is one development profile only, so it doesn't show how the prompt does on other CVs.
- **Few boxes verify on photos.** With v2, 11 of 49 boxes verify. Flash-Lite places boxes about half a line too high, and short skill boxes drift sideways. Padding would raise the number only by accepting boxes that point at other text, so the rest fall back to the whole image, marked approximate.
- **Possible improvement:** locate each span using full-page OCR word boxes, and accept a location only when it agrees with the model's box.
- **Simulated photos.** The test photos are simulated from rendered PDFs, which is easier than real phone photos.
- **One image only.** Multi-page photo sets aren't handled; each image is one document.

## Example

Profile 01's classic photo, `data/synthetic/a3_enriched/rendered/student_profile_01_classic_photo.jpg` (synthetic), with `extraction/v2`:

- 16 facts: the degree, 4 subjects, 1 role, 2 projects and 8 skills, one fact each;
- 6 of the 16 boxes verified.
