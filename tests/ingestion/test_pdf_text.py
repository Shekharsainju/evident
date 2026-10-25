from __future__ import annotations

import json
from pathlib import Path

import pytest

from evident.contracts.facts import FactRef, PdfTextSource
from evident.errors import ErrorCategory, StageError
from evident.ingestion.pdf_text import extract_pages, ingest_pdf, locate_span
from evident.models.adapter import TextPart
from evident.render.pdf import html_to_pdf
from evident.settings import Role
from evident.store.files import FileRepository
from tests.builders import document
from tests.fakes import FakeAdapter

TWO_PAGES = """<!doctype html><html><body style="font:14pt Arial">
<p>Page one heading</p><p>Skills: GitHub, Jupyter Notebook</p>
<div style="page-break-before:always"></div>
<p>Built a timetable clash checker in Python and Flask for the society.</p>
<p>Git</p>
</body></html>"""


@pytest.fixture(scope="module")
def pdf_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    return html_to_pdf(TWO_PAGES, tmp_path_factory.mktemp("pdf") / "two.pdf").read_bytes()


def test_extract_pages_text_matches_chars(pdf_bytes: bytes) -> None:
    pages = extract_pages(pdf_bytes)
    assert [p.page_number for p in pages] == [1, 2]
    for page in pages:
        assert page.text == "".join(c.text for c in page.chars)
    assert "Built a timetable clash checker" in pages[1].text


def test_locate_span_returns_union_box_on_correct_page(pdf_bytes: bytes) -> None:
    pages = extract_pages(pdf_bytes)
    loc = locate_span(pages, "Built a timetable clash checker in Python and Flask")
    assert loc is not None and loc.page == 2 and loc.score >= 90
    x0, top, x1, bottom = loc.bbox
    assert x1 > x0 > 0 and bottom > top > 0
    real = [c for c in pages[1].chars if not c.synthetic and c.text.strip()]
    first = next(c for c in real if c.text == "B")
    assert x0 == pytest.approx(first.x0) and top == pytest.approx(first.top, abs=0.5)


def test_locate_span_below_threshold_returns_none(pdf_bytes: bytes) -> None:
    assert locate_span(extract_pages(pdf_bytes), "Led a production Kubernetes migration") is None


def test_short_span_matches_whole_word_only(pdf_bytes: bytes) -> None:
    loc = locate_span(extract_pages(pdf_bytes), "Git")
    assert loc is not None and loc.page == 2  # not inside "GitHub" on page 1


def drafts_reply() -> str:
    def fact(span: str) -> dict[str, object]:
        return {"kind": "project", "text": span, "span_text": span, "box_2d": None,
                "attributes": {"ownership": "built", "skills": ["Python", "Flask"]}}

    return json.dumps({"facts": [
        fact("Built a timetable clash checker in Python and Flask"),
        fact("Designed a quantum compiler for satellites"),
    ], "unreadable_regions": []})


def test_ingest_pdf_stores_extracted_facts_with_spans(tmp_path: Path, pdf_bytes: bytes) -> None:
    repo = FileRepository(tmp_path)
    doc = document()
    adapter = FakeAdapter({Role.extraction_text: [drafts_reply()]})
    found, missing = ingest_pdf(doc, pdf_bytes, adapter, repo)
    for fact in (found, missing):
        assert repo.get_fact(doc.owner_id, FactRef(fact_id=fact.fact_id, version=1)) == fact
    assert isinstance(found.source, PdfTextSource) and found.source.span_found
    assert found.source.page == 2 and found.source.bbox != (0.0, 0.0, 0.0, 0.0)
    assert isinstance(missing.source, PdfTextSource) and not missing.source.span_found
    assert missing.source.bbox == (0.0, 0.0, 0.0, 0.0)


def test_ingest_pdf_sends_text_inside_document_tags(tmp_path: Path, pdf_bytes: bytes) -> None:
    adapter = FakeAdapter({Role.extraction_text: [drafts_reply()]})
    ingest_pdf(document(), pdf_bytes, adapter, FileRepository(tmp_path))
    [call] = adapter.calls
    assert call.role is Role.extraction_text
    assert call.prompt.name == "extraction" and call.prompt.version == "v2"
    [part] = call.parts
    assert isinstance(part, TextPart)
    body = part.text.split("<document>", 2)[-1]
    assert "Built a timetable clash checker" in body and body.rstrip().endswith("</document>")


def test_empty_text_layer_raises_input_error(tmp_path: Path) -> None:
    blank = html_to_pdf("<!doctype html><html><body></body></html>", tmp_path / "blank.pdf")
    with pytest.raises(StageError) as e:
        ingest_pdf(document(), blank.read_bytes(), FakeAdapter({}), FileRepository(tmp_path))
    assert e.value.category is ErrorCategory.input
