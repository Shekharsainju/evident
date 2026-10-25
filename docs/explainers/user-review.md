# User review

## What it does

After ingestion, the user sees every extracted fact beside a crop of the document it came from, and decides on each:

- **Confirm:** the fact may now be used downstream.
- **Reject:** the fact is never used.
- **Edit:** creates a new version of the fact. The new version is marked as edited by the user, and has to be confirmed in turn.

A "Confirm all other facts" button confirms the low-impact facts in one step. Only confirmed facts flow on to coverage, planning and claims. The code is in `src/evident/review/actions.py`, the pages in `src/evident/web/`, and the crops in `src/evident/render/receipts.py`.

## Why it's built this way

- **The user is the authority on their own facts** (design: Pipeline 3; invariants section 1). A claim may cite only confirmed fact versions that belong to the current user, so nothing the model extracted reaches an output until a person has looked at it.
- **High-impact facts need their own confirm** (spec 8.2). `is_high_impact` is true when a fact:
  - has dates or metrics;
  - is education or a certification;
  - claims ownership above "contributed" or deployment above "concept";
  - or has an uncertain source location (a PDF span that wasn't found, or a photo box that failed the OCR check).

  These are the details that change what a claim may later say, so the bulk button skips them.
- **A fact whose supporting text wasn't found can't be confirmed as it stands.** The user has to edit it, which marks it as their own wording, or reject it.
- **Edits never change a fact in place** (design: Data model; invariants section 1):
  - the new version records `supersedes`, and the old version becomes `superseded`;
  - outputs keep the exact fact versions they used, so an edit makes them stale rather than silently changing them;
  - the new version is written before the old one is superseded, so a failure between the two steps still leaves the newest version in charge.
- **Every page and crop is scoped to the owner.** A crop URL for another owner's fact returns the same 404 as an unknown ID, so IDs can't be probed. User text is escaped in every page (Jinja autoescape). Uploads are typed from their bytes, never from the file name, and capped at 10 MB.

## How the model is used

None. Review is model-free. The run service starts ingestion in a background task:

- a quota error during ingestion leaves the run in a visible `quota_exhausted` state, with nothing half-written;
- resuming later reuses the cached reply.

## Limits

- **There is no auth.** Every request acts as the single local owner, and the app runs on localhost only (spec 3).
- **Photos lean on per-fact confirms.** Most photo boxes fall back to "approximate location", so most photo facts need their own confirm. On profile 01's classic photo, all 16 facts needed a check.
- **Crops don't mark the exact span.** A crop includes a margin for context, so it shows the region around a fact without outlining it. Outlining belongs with the receipt work (Task 21).
- **Metric values can't be edited in the form yet.** A wrong metric has to be rejected instead.

## Example

Starting a run from `student_profile_01_classic_photo` with the Graduate AI Engineer ad, checked in headless Chromium on 2026-10-25 (the reply came from cache, with no model call):

- the run reached review with 16 facts, each shown with its crop;
- confirming one fact turned its badge to "confirmed" and left the rest waiting.
