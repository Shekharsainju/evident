# Post-render verification

## What it does

Post-render verification is Layer 3 of the release gate (design: Grounding and validation; spec 8.7). After a renderer has produced the visual profile HTML or the interview deck, it checks that what ended up in the file is exactly what was validated. The code is `src/evident/validation/post_render.py`.

- `verify_html(html, expected, identity, whitelist)` parses the page with the standard library's `html.parser`. Every element with `data-claim-id` must contain that claim's validated wording, every `data-identity` element must contain the identity value it was given, and every other text node, plus the `<title>`, must be template copy from the whitelist. The only difference it forgives is whitespace. Script and style content is ignored.
- `verify_pptx(path, expected, whitelist)` is the lighter deck check the spec calls for: every paragraph of body text on every slide must be a validated claim or template copy, and every claim ID in the `Sources:` block of the speaker notes must exist in the validated plan.

Both return a `PostRenderResult(passed, problems)`. A failed result blocks that output's files (plan Task 15).

## Why it's built this way

- **It checks the file, not the plan.** Layers 1 and 2 decide which claims may be rendered. This layer catches what happens after that decision: a template that truncates, a renderer that rewrites, a stray line of copy that nobody validated. Those are the failure modes the design lists for Layer 3.
- **Exact match after whitespace collapse only.** Case, punctuation and wording all count. A rendered claim is compared to `expected[claim_id]` after both are collapsed to single spaces, so a template line break is fine and a dropped word is not.
- **Entities compare decoded** (Review Focus 4). `html.parser` is run with `convert_charrefs=True`, so `&lt;script&gt; &amp; &quot;API&quot;` on the page compares equal to the validated `<script> & "API"`. Autoescaping in the renderer and verification here therefore agree, and user content with HTML characters neither breaks the page nor fails the check.
- **Text nodes, not elements.** Template copy is matched per text node, which is what a template actually emits: `Email:` is one node, the identity value next to it is another. Punctuation-only nodes (a separator, a bullet) carry no words and are allowed, so decorative markup does not need whitelisting.
- **Nesting is handled by depth, not by tag name.** A claim rendered as `Built a <b>timetable</b> checker` is one span; the collector joins its text until the matching close tag. Void elements (`<br>`, `<img>`) never change the depth, so a renderer that adds a line break inside a span cannot confuse the match.
- **Unknown IDs fail, not just changed text.** A claim ID on the page that is not in `expected` means the renderer put something in that the plan never validated. A claim in `expected` that is not on the page means the output silently lost content. Both are reported.
- **The deck check is deliberately lighter** (spec 8.7, builder's call). PPTX has no per-span attributes, so the check works at paragraph level and on the `Sources:` lines in the notes, which Task 13 writes as `claim_id: fact_id@version, page or image, span_text`.
- **Problems are sentences with the rendered text quoted**, so the outputs page can show what was found without the reader opening the file.

## How the model is used

No model. The check is deterministic and runs in milliseconds, which is what makes it safe to rerun after every re-render.

## Limits

- **It verifies the HTML, and the PDF only through it.** The PDF is produced from the same HTML by Playwright, so the HTML check covers the text, but a PDF-specific loss (a page break cutting a span) is not detected. Extracting text from the PDF is a follow-up.
- **The deck check cannot tell a claim from its shortened form.** If a renderer shortens a claim for a slide, the shortened text must itself be a validated derived claim in `expected`, as the design requires. The check does not know which claim a slide paragraph came from.
- **Narrative speaker notes are not checked word for word.** Only the claim IDs in the `Sources:` block are checked. The narrative above it is a derived claim that passed Layers 1 and 2 before rendering, which is where its wording is held.
- **The end-to-end test uses a stand-in template.** `test_render_profile_output_passes_verification` renders with a Jinja template that follows the Task 13 contract (`data-claim-id`, `data-claim-version`, `data-identity`, autoescape on), because the renderer did not exist when this was written. When `src/evident/render/profile_html.py` lands, the test should call `render_profile` instead.
- **Whitelist entries are exact.** `Email` and `Email:` are different entries. The template copy file (Task 13's `config/template_copy.toml`) has to list labels as they are rendered.

## Example

Validated claims:

```
c_01: Built a timetable clash checker in Python and Flask
c_02: Profiling cut timetable clash checks to under 2 seconds
```

A page that renders `c_01` as "Led a timetable clash checker in Python and Flask", drops `c_02`, and adds an unvalidated line fails with:

```
claim c_01: rendered text differs from the validated wording (rendered 'Led a timetable clash checker in Python and Flask')
claim c_02 is missing from the rendered output
text 'Also fluent in Kubernetes and leadership.' has no claim id and is not template copy
```

The same page with the validated wording, both claims, and only whitelisted copy passes, including when a claim contains `<`, `&` or quotes and the template escapes them.
