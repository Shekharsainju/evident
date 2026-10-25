"""Digital PDF ingestion: text layer, model splits it into facts, spans located on the page.

The model sees only text. Every span it returns is looked up in the PDF's own text; the
location comes from pdfplumber's character boxes, never from the model (spec 8.1).
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

import pdfplumber
from rapidfuzz import fuzz

from evident.contracts.documents import Document
from evident.contracts.facts import FactVersion, PdfTextSource
from evident.errors import ErrorCategory, StageError
from evident.ingestion.drafts import EXTRACTION_PROMPT_VERSION, ExtractionDraft, draft_to_fact
from evident.models.adapter import ModelAdapter, Part, TextPart
from evident.prompts import load_prompt, render_prompt
from evident.settings import Role
from evident.store.repository import Repository

log = logging.getLogger("evident.ingestion")

SPAN_THRESHOLD = 90.0
SHORT_SPAN_WORDS = 3
NO_BOX = (0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class CharBox:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    # Spaces and line breaks inferred from geometry; they have no box of their own.
    synthetic: bool = False


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    chars: list[CharBox]


@dataclass(frozen=True)
class SpanLocation:
    page: int
    bbox: tuple[float, float, float, float]
    score: float


def _page_chars(raw: list[dict[str, object]]) -> list[CharBox]:
    out: list[CharBox] = []
    prev: CharBox | None = None
    for c in raw:
        box = CharBox(str(c["text"]), float(str(c["x0"])), float(str(c["top"])),
                      float(str(c["x1"])), float(str(c["bottom"])))
        if prev is not None and box.text.strip():
            height = max(1.0, prev.bottom - prev.top)
            new_line = abs(box.top - prev.top) > 0.5 * height
            gap = box.x0 - prev.x1
            if new_line and not prev.text.isspace():
                out.append(CharBox("\n", prev.x1, prev.top, prev.x1, prev.bottom, True))
            elif not new_line and gap > 0.25 * height and not prev.text.isspace():
                out.append(CharBox(" ", prev.x1, prev.top, prev.x1, prev.bottom, True))
        out.append(box)
        prev = box
    return out


def extract_pages(pdf: bytes) -> list[PageText]:
    """Text in content-stream order, which keeps multi-column layouts column by column;
    line order would interleave the columns."""
    pages = []
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for number, page in enumerate(doc.pages, start=1):
            chars = _page_chars(page.chars)
            pages.append(PageText(number, "".join(c.text for c in chars), chars))
    return pages


def _normalised(text: str) -> tuple[str, list[int]]:
    """Lowercase with whitespace runs collapsed, plus a map back to original indices."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            if out and out[-1] == " ":
                continue
            out.append(" ")
        else:
            out.append(ch.lower())
        index.append(i)
    return "".join(out), index


def _union(chars: list[CharBox]) -> tuple[float, float, float, float]:
    real = [c for c in chars if not c.synthetic and c.text.strip()]
    return (min(c.x0 for c in real), min(c.top for c in real),
            max(c.x1 for c in real), max(c.bottom for c in real))


def locate_span(pages: list[PageText], span_text: str,
                threshold: float = SPAN_THRESHOLD) -> SpanLocation | None:
    span, _ = _normalised(span_text.strip())
    if not span.strip():
        return None
    best: SpanLocation | None = None
    for page in pages:
        text, index = _normalised(page.text)
        if not text:
            continue
        if len(span.split()) <= SHORT_SPAN_WORDS:
            # Whole words only, so "Git" can't be placed inside "GitHub".
            m = re.search(rf"(?<!\w){re.escape(span.strip())}(?!\w)", text)
            if m is None:
                continue
            score, start, end = 100.0, m.start(), m.end()
        else:
            align = fuzz.partial_ratio_alignment(span, text)
            if align is None:
                continue
            score, start, end = align.score, align.dest_start, align.dest_end
        if score < threshold or end <= start:
            continue
        chars = page.chars[index[start]:index[end - 1] + 1]
        if not any(not c.synthetic and c.text.strip() for c in chars):
            continue
        if best is None or score > best.score:
            best = SpanLocation(page.page_number, _union(chars), score)
    return best


def request_pdf_draft(pages: list[PageText], adapter: ModelAdapter,
                      prompt_version: str | None = None) -> ExtractionDraft:
    body = "\n\n".join(f"[page {p.page_number}]\n{p.text}" for p in pages)
    prompt = load_prompt("extraction", prompt_version or EXTRACTION_PROMPT_VERSION)
    parts: list[Part] = [TextPart(render_prompt(prompt, content=body))]
    return adapter.generate_json(Role.extraction_text, prompt, parts, ExtractionDraft).value


def ingest_pdf(doc: Document, content: bytes, adapter: ModelAdapter,
               repo: Repository) -> list[FactVersion]:
    pages = extract_pages(content)
    if not any(p.text.strip() for p in pages):
        raise StageError(code="no_text_layer", category=ErrorCategory.input,
                         detail="This PDF has no text layer. Upload a photo or scan instead.")
    draft = request_pdf_draft(pages, adapter)

    facts = []
    for index, item in enumerate(draft.facts, start=1):
        loc = locate_span(pages, item.span_text)
        source = PdfTextSource(
            document_id=doc.document_id,
            page=loc.page if loc else 1,
            bbox=loc.bbox if loc else NO_BOX,
            span_text=item.span_text.strip(),
            confidence=(loc.score / 100.0) if loc else 0.0,
            span_found=loc is not None,
        )
        fact = draft_to_fact(item, index, doc, source)
        if fact is None:
            continue
        repo.put_fact(fact)
        facts.append(fact)
    log.info("pdf ingestion document=%s pages=%d facts=%d spans_found=%d", doc.document_id,
             len(pages), len(facts),
             sum(1 for f in facts if isinstance(f.source, PdfTextSource) and f.source.span_found))
    return facts
