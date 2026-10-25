from __future__ import annotations

import html
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches

from evident.validation.post_render import collapse, verify_html, verify_pptx

MARKER = "Synthetic profile, A3 testing"
WHITELIST = {"Profile", "Projects", "Experience", "Contact", "Email:", MARKER}
EXPECTED = {
    "c_01": "Built a timetable clash checker in Python and Flask",
    "c_02": "Profiling cut timetable clash checks to under 2 seconds",
}
IDENTITY = {"name": "Maya Chen", "email": "maya@example.invalid"}


def profile_html(claims: dict[str, str] = EXPECTED, identity: dict[str, str] = IDENTITY,
                 extra: str = "", title: str = "Profile") -> str:
    """The shape Task 13's renderer produces, with autoescape applied by hand."""
    spans = "\n".join(
        f'<li><span data-claim-id="{cid}" data-claim-version="1">{html.escape(text)}</span></li>'
        for cid, text in claims.items()
    )
    return f"""<!doctype html><html><head><title>{title}</title>
<style>body {{ font: 14px sans-serif }} .x::before {{ content: "decorative" }}</style>
<script>console.log("not content");</script></head>
<body>
<h1><span data-identity="name">{html.escape(identity["name"])}</span></h1>
<p>Email: <a href="mailto:x"><span data-identity="email">{html.escape(identity["email"])}
</span></a></p>
<h2>Projects</h2>
<ul>
{spans}
</ul>
{extra}
<footer>{MARKER}</footer>
</body></html>"""


def test_exact_match_passes() -> None:
    result = verify_html(profile_html(), EXPECTED, IDENTITY, WHITELIST)
    assert result.passed, result.problems


def test_whitespace_differences_are_allowed() -> None:
    claims = {"c_01": "Built a timetable\n   clash checker in Python and Flask",
              "c_02": EXPECTED["c_02"]}
    assert verify_html(profile_html(claims), EXPECTED, IDENTITY, WHITELIST).passed


def test_changed_wording_fails() -> None:
    claims = dict(EXPECTED, c_01="Led a timetable clash checker in Python and Flask")
    result = verify_html(profile_html(claims), EXPECTED, IDENTITY, WHITELIST)
    assert not result.passed
    assert result.problems == ["claim c_01: rendered text differs from the validated wording "
                               "(rendered 'Led a timetable clash checker in Python and Flask')"]


def test_truncated_claim_fails() -> None:
    claims = dict(EXPECTED, c_02="Profiling cut timetable clash checks")
    result = verify_html(profile_html(claims), EXPECTED, IDENTITY, WHITELIST)
    assert [p.startswith("claim c_02: rendered text differs") for p in result.problems] == [True]


def test_extra_unwhitelisted_text_fails() -> None:
    extra = "<p>Also fluent in Kubernetes and leadership.</p>"
    result = verify_html(profile_html(extra=extra), EXPECTED, IDENTITY, WHITELIST)
    assert result.problems == ["text 'Also fluent in Kubernetes and leadership.' has no claim "
                               "id and is not template copy"]


def test_missing_expected_claim_fails() -> None:
    claims = {"c_01": EXPECTED["c_01"]}
    result = verify_html(profile_html(claims), EXPECTED, IDENTITY, WHITELIST)
    assert result.problems == ["claim c_02 is missing from the rendered output"]


def test_unknown_claim_id_fails() -> None:
    claims = dict(EXPECTED, c_99="Something the plan never validated")
    result = verify_html(profile_html(claims), EXPECTED, IDENTITY, WHITELIST)
    assert result.problems == ["unknown claim id 'c_99' in the rendered output"]


def test_escaped_entities_compare_decoded() -> None:  # Review Focus 4
    expected = {"c_01": 'Built <script> & "API" tooling'}
    page = profile_html(expected)
    assert "&lt;script&gt;" in page and "<script> &" not in page
    result = verify_html(page, expected, IDENTITY, WHITELIST)
    assert result.passed, result.problems


def test_identity_mismatch_and_unknown_field_fail() -> None:
    page = profile_html(identity={"name": "Someone Else", "email": IDENTITY["email"]})
    result = verify_html(page, EXPECTED, IDENTITY, WHITELIST)
    assert result.problems == ["identity name: rendered 'Someone Else', expected 'Maya Chen'"]
    page = profile_html().replace('data-identity="email"', 'data-identity="phone"')
    assert verify_html(page, EXPECTED, IDENTITY, WHITELIST).problems == [
        "unknown identity field 'phone' in the rendered output"
    ]


def test_script_style_and_title_handling() -> None:
    # Script and style content is ignored; the title must be template copy.
    assert verify_html(profile_html(), EXPECTED, IDENTITY, WHITELIST).passed
    result = verify_html(profile_html(title="Maya's amazing CV"), EXPECTED, IDENTITY, WHITELIST)
    assert result.problems == ["title \"Maya's amazing CV\" is not template copy"]


def test_nested_markup_inside_a_claim_is_joined() -> None:
    page = profile_html().replace(
        f'data-claim-version="1">{html.escape(EXPECTED["c_01"])}',
        'data-claim-version="1">Built a <b>timetable</b> clash checker in <i>Python</i> and Flask',
    )
    assert verify_html(page, EXPECTED, IDENTITY, WHITELIST).passed


def test_punctuation_only_nodes_are_allowed() -> None:
    page = profile_html(extra="<p>·</p><span> | </span>")
    assert verify_html(page, EXPECTED, IDENTITY, WHITELIST).passed


def test_render_profile_output_passes_verification() -> None:
    """End to end with the renderer. Until Task 13 lands, a Jinja template with autoescape
    stands in for render_profile; swap the import when src/evident/render/profile_html.py
    exists."""
    from jinja2 import Environment

    env = Environment(autoescape=True)
    template = env.from_string(
        "<html><head><title>Profile</title></head><body>"
        "<h1><span data-identity=\"name\">{{ identity.name }}</span></h1>"
        "<h2>Projects</h2><ul>{% for c in claims %}"
        "<li><span data-claim-id=\"{{ c.id }}\" data-claim-version=\"{{ c.version }}\">"
        "{{ c.text }}</span></li>{% endfor %}</ul>"
        "<footer>{{ marker }}</footer></body></html>"
    )
    expected = dict(EXPECTED, c_03='Tested it on 20 sample questions with <input> & "edge" cases')
    page = template.render(
        identity=IDENTITY,
        claims=[{"id": k, "version": 1, "text": v} for k, v in expected.items()],
        marker=MARKER,
    )
    assert "&#34;edge&#34;" in page or "&quot;edge&quot;" in page
    result = verify_html(page, expected, {"name": IDENTITY["name"]}, WHITELIST)
    assert result.passed, result.problems


# PPTX


def deck(path: Path, bodies: list[list[str]], notes: list[str]) -> Path:
    prs = Presentation()
    layout = prs.slide_layouts[6]  # blank
    for body, note in zip(bodies, notes, strict=True):
        slide = prs.slides.add_slide(layout)
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(4))
        frame = box.text_frame
        frame.text = body[0]
        for line in body[1:]:
            frame.add_paragraph().text = line
        marker = slide.shapes.add_textbox(Inches(1), Inches(6), Inches(8), Inches(0.5))
        marker.text_frame.text = MARKER
        slide.notes_slide.notes_text_frame.text = note
    prs.save(str(path))
    return path


def test_pptx_clean_deck_passes(tmp_path: Path) -> None:
    path = deck(tmp_path / "deck.pptx",
                [["Projects"], [EXPECTED["c_01"], EXPECTED["c_02"]]],
                ["", "Sources:\nc_01: doc_01_f01@1, page 1, Built a timetable clash checker\n"
                     "c_02: doc_01_f01@1, page 1, cut timetable clash checks"])
    result = verify_pptx(path, EXPECTED, WHITELIST)
    assert result.passed, result.problems


def test_pptx_extra_body_text_fails(tmp_path: Path) -> None:
    path = deck(tmp_path / "deck.pptx",
                [["Projects"], [EXPECTED["c_01"], "Also led a team of twelve"]],
                ["", "Sources:\nc_01: doc_01_f01@1, page 1, span"])
    result = verify_pptx(path, EXPECTED, WHITELIST)
    assert result.problems == ["slide 2: body text 'Also led a team of twelve' is neither a "
                               "validated claim nor template copy"]


def test_pptx_unknown_claim_id_in_notes_fails(tmp_path: Path) -> None:
    path = deck(tmp_path / "deck.pptx", [[EXPECTED["c_01"]]],
                ["Narrative line that is not a source.\nSources:\nc_77: doc_01_f01@1, page 1, x"])
    result = verify_pptx(path, EXPECTED, WHITELIST)
    assert result.problems == ["slide 1: notes cite unknown claim id 'c_77'"]


def test_collapse_only_touches_whitespace() -> None:
    assert collapse("  a \n b\t c ") == "a b c"
    assert collapse("A, b.") == "A, b."
