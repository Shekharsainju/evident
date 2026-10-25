"""Rough interview deck: validated claims as slides, sources in the notes (Task 13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.util import Inches, Pt

from evident.contracts.enums import OutputType
from evident.contracts.plan import Claim, ContentPlan
from evident.contracts.validation import ValidationReport
from evident.render.profile_html import COPY, by_section, renderable_claims

TITLE_LAYOUT = 0
TITLE_ONLY_LAYOUT = 5
CLAIM_TOP = Inches(1.5)
CLAIM_HEIGHT = Inches(1.4)
CLAIM_GAP = Inches(0.2)


def _add_marker(slide: Any, width: Any) -> None:
    box = slide.shapes.add_textbox(Inches(0.5), Inches(7.0), width - Inches(1.0), Inches(0.4))
    box.text_frame.text = COPY["marker"]
    box.text_frame.paragraphs[0].runs[0].font.size = Pt(10)


def source_lines(claims: list[Claim]) -> list[str]:
    return [f"{c.claim_id}: {ref.fact_id}@{ref.version}, {COPY['source_detail_missing']}"
            for c in claims for ref in c.evidence]


def render_deck(plan: ContentPlan, report: ValidationReport, identity: dict[str, str],
                out: Path) -> Path:
    claims = renderable_claims(plan, report, OutputType.interview_deck)
    body = [c for c in claims if c.parent_claim_id is None]
    narratives = [c for c in claims if c.parent_claim_id is not None]

    deck = Presentation()
    # Only template copy on the title slide: Task 14's verify_pptx takes no identity, so a
    # name here would fail verification on a correct deck.
    title = deck.slides.add_slide(deck.slide_layouts[TITLE_LAYOUT])
    title.shapes.title.text = COPY["deck_title"]
    title.placeholders[1].text = COPY["marker"]

    for heading, section_claims in by_section(body):
        slide = deck.slides.add_slide(deck.slide_layouts[TITLE_ONLY_LAYOUT])
        slide.shapes.title.text = heading
        # One text box per claim, named by claim ID, so verification can match each box to
        # exactly one validated claim.
        for i, c in enumerate(section_claims):
            top = CLAIM_TOP + i * (CLAIM_HEIGHT + CLAIM_GAP)
            box = slide.shapes.add_textbox(Inches(0.5), top, deck.slide_width - Inches(1.0),
                                           CLAIM_HEIGHT)
            box.name = c.claim_id
            box.text_frame.word_wrap = True
            box.text_frame.text = c.text
        _add_marker(slide, deck.slide_width)

        on_slide = {c.claim_id for c in section_claims}
        stories = [n for n in narratives if n.parent_claim_id in on_slide]
        notes = [f"{n.claim_id}: {n.text}" for n in stories] + [COPY["sources_label"]]
        notes += source_lines(section_claims + stories)
        slide.notes_slide.notes_text_frame.text = "\n".join(notes)

    out.parent.mkdir(parents=True, exist_ok=True)
    deck.save(str(out))
    return out
