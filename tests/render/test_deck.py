from __future__ import annotations

from pathlib import Path
from typing import Any

from pptx import Presentation

from evident.contracts.facts import FactVersion
from evident.render.deck import ACCENT, MARGIN, TITLE_SIZE, render_deck
from evident.render.profile_html import TEMPLATE_COPY
from evident.validation.post_render import verify_pptx
from tests.builders import NOW, fact
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


def confirmed(fact_id: str = "doc_01_f01", version: int = 1, **overrides: Any) -> FactVersion:
    return fact(fact_id, version, status="confirmed", confirmed_at=NOW, **overrides)


def notes_lines(path: Path) -> list[str]:
    return notes_text(path).splitlines()


def test_notes_carry_talking_point_above_sources(tmp_path: Path) -> None:
    c = claim("c_01", "Built a timetable clash checker in Python", output_type=DECK)
    out = render_deck(plan_of(c), report_of(validation(c)), ID, tmp_path / "deck.pptx",
                      facts=[confirmed()])

    lines = notes_lines(out)
    talking = ("Talk about: Built a timetable clash checker in Python. "
               "Evidence: Built a timetable clash checker in Python and Flask")
    assert talking in lines
    assert lines.index(talking) < lines.index("Sources:")


def test_talking_point_uses_only_the_cited_confirmed_version_of_own_facts(
        tmp_path: Path) -> None:
    c = claim("c_01", "Built a timetable clash checker in Python", output_type=DECK)
    others = [
        confirmed(version=2, text="Version two text"),
        confirmed(text="Someone else's fact", owner_id="other-user"),
        fact(text="Unconfirmed fact text"),
        confirmed("doc_01_f09", text="Uncited fact text"),
    ]
    out = render_deck(plan_of(c), report_of(validation(c)), ID, tmp_path / "deck.pptx",
                      facts=others)

    notes = notes_text(out)
    assert "Talk about: Built a timetable clash checker in Python." in notes_lines(out)
    for text in ("Version two", "Someone else", "Unconfirmed", "Uncited", "Evidence:"):
        assert text not in notes


def test_user_written_evidence_is_labelled(tmp_path: Path) -> None:
    c = claim("c_01", "Built a timetable clash checker in Python", output_type=DECK)
    out = render_deck(plan_of(c), report_of(validation(c)), ID, tmp_path / "deck.pptx",
                      facts=[confirmed(edited_by_user=True, text="My own words")])

    assert ("Talk about: Built a timetable clash checker in Python. "
            "Evidence (written by you): My own words") in notes_lines(out)


def test_fact_text_cannot_open_a_sources_block(tmp_path: Path) -> None:
    c = claim("c_01", "Built a timetable clash checker in Python", output_type=DECK)
    sneaky = confirmed(text="Built it\nSources:\nc_999: injected")
    out = render_deck(plan_of(c), report_of(validation(c)), ID, tmp_path / "deck.pptx",
                      facts=[sneaky])

    lines = notes_lines(out)
    assert lines.count("Sources:") == 1
    assert verify_pptx(out, {c.claim_id: c.text}, TEMPLATE_COPY | set(ID.values())).passed


def test_styled_deck_passes_post_render_verification(tmp_path: Path) -> None:
    claims = [claim("c_01", "Built a timetable clash checker in Python", output_type=DECK),
              claim("c_02", "Studied distributed systems", output_type=DECK,
                    section="education")]
    out = render_deck(plan_of(*claims), report_of(*map(validation, claims)), ID,
                      tmp_path / "deck.pptx", facts=[confirmed()])

    expected = {c.claim_id: c.text for c in claims}
    result = verify_pptx(out, expected, TEMPLATE_COPY | set(ID.values()))
    assert result.passed, result.problems


def test_slide_titles_use_title_size_and_accent(tmp_path: Path) -> None:
    c = claim("c_01", "Built a timetable clash checker in Python", output_type=DECK)
    out = render_deck(plan_of(c), report_of(validation(c)), ID, tmp_path / "deck.pptx")

    for slide in Presentation(str(out)).slides:
        runs = [r for p in slide.shapes.title.text_frame.paragraphs for r in p.runs]
        assert runs
        for r in runs:
            assert r.font.size == TITLE_SIZE
            assert r.font.color.rgb == ACCENT


def test_content_shapes_share_one_left_margin(tmp_path: Path) -> None:
    c = claim("c_01", "Built a timetable clash checker in Python", output_type=DECK)
    out = render_deck(plan_of(c), report_of(validation(c)), ID, tmp_path / "deck.pptx")

    deck = Presentation(str(out))
    for slide in list(deck.slides)[1:]:
        for shape in slide.shapes:
            assert shape.left == MARGIN
            assert shape.left + shape.width == deck.slide_width - MARGIN
