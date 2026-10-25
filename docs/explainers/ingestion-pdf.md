# Ingestion: digital PDFs

## What it does

It turns a CV that has a text layer into extracted facts, each pinned to the exact words on the page that support it. `ingest_pdf` in `src/evident/ingestion/pdf_text.py`:

1. Reads the text and every character's box with pdfplumber.
2. Asks the model to split the text into atomic facts.
3. Finds each fact's `span_text` in the PDF's own text, and stores the union of those characters' boxes as the source location.

Facts are stored as version 1 with status `extracted`, and the user reviews them before use.

## Why it's built this way

- **Location comes from the PDF, not the model** (design: Pipeline 1, Evidence receipts; spec 8.1). The model sees text only. Every span it returns is looked up in the text layer, and the box is built from pdfplumber's character boxes. A span that can't be found is kept, but flagged `span_found: false` with an empty box, and it can't be confirmed until the user edits or rejects it.
- **Text is read in content-stream order.** Chromium writes the PDF in document order, so a sidebar or two-column layout is read column by column. Reading by line position instead interleaves the columns, mixing a skills list into a project description. Spaces and line breaks are inferred from character positions, and they carry no box of their own.
- **Matching is strict:**
  - Spans longer than 3 words use a fuzzy alignment and need a score of 90 or more.
  - Spans of 3 words or fewer must match whole words, so a "Git" skill is never placed inside "GitHub".
  - If a short span appears more than once, the first occurrence is used. Every occurrence has the same words, so the receipt still shows the right text.
- **Shared rules with the photo path.** The PDF text goes inside `<document>` tags after the shared preamble, and the model's drafts go through the same field-by-field contract checks (`drafts.py`) as photo ingestion.
- **An empty text layer is an input error.** It returns a message asking for a photo or scan instead, rather than an empty result.

## How the model is used

- **Calls:** one call per document, on role `extraction_text` (`gemini-3.5-flash-lite`, 30 s timeout), with prompt `extraction/v2`, chosen on the dev split. Page markers `[page N]` separate the pages.
- **Validation:** the reply is validated against the `ExtractionDraft` schema. Invalid JSON gets one retry with the error, then the stage fails.
- **Caching:** replies are cached on disk.

## Limits

- **One development profile only.** On profile 01's three PDFs (2026-10-25), `extraction/v2` found 48/48 ground-truth facts at 48/48 precision, and all 48 spans were located. A drawing of the boxes on the sidebar PDF showed each one on its own text. That's one profile, and the test profiles haven't been run.
- **Tagged reading order isn't used.** A PDF made by another tool may write text in a different order; content-stream order is right for Chromium output, but not guaranteed elsewhere.
- **Scanned PDFs with no text layer** are refused here and should go through the photo path.
- **No reading-order fallback.** If the content stream is scrambled, a long span may fail the 90 threshold and be flagged for the user.

## Example

`data/synthetic/a3_enriched/rendered/student_profile_01_sidebar.pdf` (synthetic):

- 16 facts: the degree, 4 subjects, 1 role, 2 projects and 8 skills;
- each skill boxed on its own line in the sidebar;
- each project boxed from its title down to its technology line.
