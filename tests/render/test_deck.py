from __future__ import annotations

from pathlib import Path

from pptx import Presentation

from evident.render.deck import render_deck
from tests.render.test_profile_html import ID, claim, plan_of, report_of, validation

DECK = "interview_deck"


def notes_text(path: Path) -> str:
    deck = Presentation(str(path))
    return "\n".join(s.notes_slide.notes_text_frame.text for s in deck.slides if s.has_notes_slide)


def body_paragraphs(path: Path) -> list[str]:
    deck = Presentation(str(path))
    # The first slide is the title slide; claims live on the section slides after it.
    return [p.text for s in list(deck.slides)[1:] for shape in s.shapes if shape.has_text_frame
            for p in shape.text_frame.paragraphs]


def test_deck_notes_list_claim_ids_and_sources(tmp_path: Path) -> None:
    kept = claim("c_01", "Built a timetable clash checker in Python", output_type=DECK)
    dropped = claim("c_02", "Shipped the clash checker to production", output_type=DECK,
                    fact_id="doc_01_f02")
    plan = plan_of(kept, dropped)
    report = report_of(validation(kept), validation(dropped, "rejected"))

    notes = notes_text(render_deck(plan, report, ID, tmp_path / "deck.pptx"))

    assert "Sources:" in notes
    assert "c_01: doc_01_f01@1," in notes
    assert "c_02" not in notes and "doc_01_f02" not in notes


def test_deck_body_text_is_verbatim_claims(tmp_path: Path) -> None:
    claims = [
        claim("c_01", 'Built a timetable clash checker (Python, Flask) & "API"', output_type=DECK),
        claim("c_02", "Wrote 40 unit tests for the clash checker", output_type=DECK,
              emphasis=4),
        claim("c_03", "Studied distributed systems", output_type=DECK, section="education"),
    ]
    plan = plan_of(*claims)

    paragraphs = body_paragraphs(render_deck(plan, report_of(*map(validation, claims)), ID,
                                             tmp_path / "deck.pptx"))

    for c in claims:
        assert c.text in paragraphs


def test_narrative_notes_carry_claim_id(tmp_path: Path) -> None:
    body = claim("c_01", "Built a timetable clash checker in Python", output_type=DECK)
    story = claim("c_02", "I wrote the checker after a clash cost a friend a lab slot.",
                  output_type=DECK, parent="c_01")
    plan = plan_of(body, story)

    notes = notes_text(render_deck(plan, report_of(validation(body), validation(story)), ID,
                                   tmp_path / "deck.pptx"))

    assert f"c_02: {story.text}" in notes.splitlines()


def test_each_claim_has_own_text_box_named_by_claim_id(tmp_path: Path) -> None:
    claims = [
        claim("c_01", "Built a timetable clash checker in Python", output_type=DECK),
        claim("c_02", "Wrote 40 unit tests for the clash checker", output_type=DECK),
    ]
    out = render_deck(plan_of(*claims), report_of(*map(validation, claims)), ID,
                      tmp_path / "deck.pptx")

    shapes = [shape for s in Presentation(str(out)).slides for shape in s.shapes]
    named = sorted((shape.name, shape.text_frame.text) for shape in shapes
                   if shape.name in {"c_01", "c_02"})

    assert named == [(c.claim_id, c.text) for c in claims]


def title_paragraphs(path: Path) -> list[str]:
    title = list(Presentation(str(path)).slides)[0]
    return [p.text for p in title.shapes.title.text_frame.paragraphs]


def test_title_slide_shows_name_and_target_role(tmp_path: Path) -> None:
    c = claim("c_01", "Built a timetable clash checker in Python", output_type=DECK)
    identity = {"name": "Alex Example", "target_role": "Graduate AI Engineer"}
    out = render_deck(plan_of(c), report_of(validation(c)), identity, tmp_path / "deck.pptx")

    assert title_paragraphs(out) == ["Alex Example", "Graduate AI Engineer"]


def test_title_slide_without_identity_uses_template_title(tmp_path: Path) -> None:
    c = claim("c_01", "Built a timetable clash checker in Python", output_type=DECK)
    out = render_deck(plan_of(c), report_of(validation(c)), {}, tmp_path / "deck.pptx")

    assert title_paragraphs(out) == ["Interview deck"]
