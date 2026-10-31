# Renderers and receipts

## What is rendered

The visual profile and interview deck render only claims whose exact versions passed both
validation layers, or which were explicitly approved after a user-review outcome. A claim
also needs current, confirmed evidence; changing or rejecting a fact removes dependent
claims from the next render. The post-render verifier then checks that every rendered claim
still has its claim ID and exact approved wording. All other visible text is fixed template
copy.

The profile uses an A4-safe resume layout: a clear identity block, ordered sections, and
readable claim lists. It is responsive in a browser and removes browser-only framing when
printed. The deck shares the restrained high-contrast palette but contains no extra factual
copy.

## Evidence receipts

Each rendered profile claim remains marked with `data-claim-id` and `data-claim-version`.
Selecting it in the HTML profile opens a receipt popover. The popover fetches a partial
receipt containing the claim, its cited fact versions, and source crops. The full receipt
page remains available as a normal link.

PDF rendering substitutes absolute receipt URLs for the claim links, because Chromium only
keeps absolute links as PDF annotations. The PDF therefore preserves a clickable link for
each rendered claim. Receipt lookup checks the plan, report, current fact versions, and
renderability, so it does not reveal receipts for rejected, stale, or unrenderable claims.

## Editing a claim

Only a claim awaiting user review can be edited in the slice UI. Editing creates the next
claim version with the same evidence references, runs Layer 1 and the independent judge
again, replaces the old version only after that validation succeeds, and re-renders the
outputs. Earlier output files are marked stale and are no longer served. An edit therefore
never turns unsupported wording into an approved claim merely by changing the displayed
text.
