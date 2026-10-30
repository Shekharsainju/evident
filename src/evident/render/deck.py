"""Rough interview deck: validated claims as slides, sources in the notes (Task 13)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from evident.contracts.enums import FactStatus, OutputType
from evident.contracts.facts import FactRef, FactVersion
from evident.contracts.plan import Claim, ContentPlan
from evident.contracts.validation import ValidationReport
from evident.render.profile_html import COPY, by_section, renderable_claims

TITLE_LAYOUT = 0
TITLE_ONLY_LAYOUT = 5
MARGIN = Inches(0.5)
TITLE_TOP = Inches(0.4)
TITLE_HEIGHT = Inches(0.9)
TITLE_SIZE = Pt(32)
CLAIM_SIZE = Pt(20)
MARKER_SIZE = Pt(10)
# python-pptx leaves RGBColor untyped.
ACCENT = RGBColor(0x1F, 0x4E, 0x79)  # type: ignore[no-untyped-call]
CLAIM_TOP = Inches(1.5)
CLAIM_HEIGHT = Inches(1.4)
CLAIM_GAP = Inches(0.2)
# Notes labels. The notes check only reads the Sources block, so these never reach it.
TALK_LABEL = "Talk about:"
EVIDENCE_LABEL = "Evidence:"
USER_EVIDENCE_LABEL = "Evidence (written by you):"
USER_WRITTEN_PATHS = {"story", "gap_answer"}


def _style_runs(frame: Any, size: Any, colour: RGBColor | None = None) -> None:
    for paragraph in frame.paragraphs:
        for run in paragraph.runs:
            run.font.size = size
            if colour is not None:
                run.font.color.rgb = colour


def _style_title(slide: Any, width: Any) -> None:
    title = slide.shapes.title
    title.left, title.top = MARGIN, TITLE_TOP
    title.width, title.height = width - 2 * MARGIN, TITLE_HEIGHT
    _style_runs(title.text_frame, TITLE_SIZE, ACCENT)


def _add_marker(slide: Any, width: Any) -> None:
    box = slide.shapes.add_textbox(MARGIN, Inches(7.0), width - 2 * MARGIN, Inches(0.4))
    box.text_frame.text = COPY["marker"]
    _style_runs(box.text_frame, MARKER_SIZE)


def _usable_facts(plan: ContentPlan, facts: Iterable[FactVersion]) -> dict[FactRef, FactVersion]:
    # Only the plan owner's confirmed facts can be quoted, keyed by exact version, so a
    # newer or unconfirmed version can't stand in for the one the claim was validated on.
    return {FactRef(fact_id=f.fact_id, version=f.version): f for f in facts
            if f.owner_id == plan.owner_id and f.status is FactStatus.confirmed}


def _one_line(text: str) -> str:
    # Fact text is untrusted: keeping it on one line stops it from opening a Sources block.
    return " ".join(text.split())


def talking_point(claim: Claim, facts: dict[FactRef, FactVersion]) -> str:
    parts = [f"{TALK_LABEL} {_one_line(claim.text).rstrip('.')}."]
    for ref in claim.evidence:
        f = facts.get(ref)
        if f is None:
            continue
        user_written = f.edited_by_user or f.source.extraction_path in USER_WRITTEN_PATHS
        label = USER_EVIDENCE_LABEL if user_written else EVIDENCE_LABEL
        parts.append(f"{label} {_one_line(f.text)}")
    return " ".join(parts)


def source_lines(claims: list[Claim]) -> list[str]:
    return [f"{c.claim_id}: {ref.fact_id}@{ref.version}, {COPY['source_detail_missing']}"
            for c in claims for ref in c.evidence]


def render_deck(plan: ContentPlan, report: ValidationReport, identity: dict[str, str],
                out: Path, facts: Iterable[FactVersion] = ()) -> Path:
    usable = _usable_facts(plan, facts)
    claims = renderable_claims(plan, report, OutputType.interview_deck)
    body = [c for c in claims if c.parent_claim_id is None]
    narratives = [c for c in claims if c.parent_claim_id is not None]

    deck = Presentation()
    # One paragraph per identity value, so verification can match each one exactly.
    title = deck.slides.add_slide(deck.slide_layouts[TITLE_LAYOUT])
    title.shapes.title.text = "\n".join(identity.values()) or COPY["deck_title"]
    title.placeholders[1].text = COPY["marker"]
    _style_title(title, deck.slide_width)

    for heading, section_claims in by_section(body):
        slide = deck.slides.add_slide(deck.slide_layouts[TITLE_ONLY_LAYOUT])
        slide.shapes.title.text = heading
        _style_title(slide, deck.slide_width)
        # One text box per claim, named by claim ID, so verification can match each box to
        # exactly one validated claim.
        for i, c in enumerate(section_claims):
            top = CLAIM_TOP + i * (CLAIM_HEIGHT + CLAIM_GAP)
            box = slide.shapes.add_textbox(MARGIN, top, deck.slide_width - 2 * MARGIN,
                                           CLAIM_HEIGHT)
            box.name = c.claim_id
            box.text_frame.word_wrap = True
            box.text_frame.text = c.text
            _style_runs(box.text_frame, CLAIM_SIZE)
        _add_marker(slide, deck.slide_width)

        on_slide = {c.claim_id for c in section_claims}
        stories = [n for n in narratives if n.parent_claim_id in on_slide]
        notes = [talking_point(c, usable) for c in section_claims]
        notes += [f"{n.claim_id}: {n.text}" for n in stories] + [COPY["sources_label"]]
        notes += source_lines(section_claims + stories)
        slide.notes_slide.notes_text_frame.text = "\n".join(notes)

    out.parent.mkdir(parents=True, exist_ok=True)
    deck.save(str(out))
    return out
