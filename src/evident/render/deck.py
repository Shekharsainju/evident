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
CONTENT_LAYOUT = 1


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
    title = deck.slides.add_slide(deck.slide_layouts[TITLE_LAYOUT])
    title.shapes.title.text = identity.get("name", "")
    title.placeholders[1].text = COPY["marker"]

    for heading, section_claims in by_section(body):
        slide = deck.slides.add_slide(deck.slide_layouts[CONTENT_LAYOUT])
        slide.shapes.title.text = heading
        frame = slide.placeholders[1].text_frame
        frame.text = section_claims[0].text
        for c in section_claims[1:]:
            frame.add_paragraph().text = c.text
        _add_marker(slide, deck.slide_width)

        on_slide = {c.claim_id for c in section_claims}
        stories = [n for n in narratives if n.parent_claim_id in on_slide]
        notes = [n.text for n in stories] + [COPY["sources_label"]]
        notes += source_lines(section_claims + stories)
        slide.notes_slide.notes_text_frame.text = "\n".join(notes)

    out.parent.mkdir(parents=True, exist_ok=True)
    deck.save(str(out))
    return out
