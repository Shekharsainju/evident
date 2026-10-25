"""Photo and scan ingestion: vision extraction, then OCR checks each box (spec 8.1).

The image is untrusted: it goes to the model inside the document block, and nothing the
model returns is trusted until the box has been checked against the pixels with OCR.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps
from rapidfuzz import fuzz

from evident.contracts.documents import Document
from evident.contracts.facts import FactVersion, VisionSource
from evident.errors import ErrorCategory, StageError
from evident.ingestion.drafts import (
    EXTRACTION_PROMPT_VERSION,
    ExtractionDraft,
    box_2d_to_pixels,
    draft_to_fact,
)
from evident.models.adapter import ImagePart, ModelAdapter, Part, TextPart
from evident.prompts import load_prompt, render_prompt
from evident.settings import Role
from evident.store.repository import Repository

log = logging.getLogger("evident.ingestion")

WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
VERIFY_THRESHOLD = 80.0
OCR_UPSCALE = 2
OCR_WHITE_BORDER = 12
SHORT_SPAN_WORDS = 3
IMAGE_PLACEHOLDER = "The document is the attached image."



def _tesseract() -> str:
    found = shutil.which("tesseract")
    if found:
        return found
    if WINDOWS_TESSERACT.exists():
        return str(WINDOWS_TESSERACT)
    raise StageError(code="ocr_unavailable", category=ErrorCategory.internal,
                     detail="Tesseract is not installed or not on PATH.")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%.]", " ", text.lower())).strip()


def _ocr_text(image: bytes, region: tuple[float, float, float, float]) -> str:
    pytesseract.pytesseract.tesseract_cmd = _tesseract()
    with Image.open(io.BytesIO(image)) as img:
        x0, y0, x1, y1 = region
        crop = img.convert("L").crop((int(x0), int(y0), int(x1), int(y1)))
    # Blank border and upscaling help Tesseract read a tight crop without widening the region
    # into neighbouring lines; widening it let wrong boxes pass (dev tuning, 2026-10-25).
    crop = crop.resize((max(1, crop.width * OCR_UPSCALE), max(1, crop.height * OCR_UPSCALE)),
                       Image.Resampling.LANCZOS)
    crop = ImageOps.expand(crop, border=OCR_WHITE_BORDER * OCR_UPSCALE, fill=255)
    return str(pytesseract.image_to_string(crop))


def span_score(span_text: str, ocr_text: str) -> float:
    """0 to 100. Short spans must appear as whole words, or "Git" would match "GitHub"."""
    span, found = _normalise(span_text), _normalise(ocr_text)
    if not span or not found:
        return 0.0
    if len(span.split()) <= SHORT_SPAN_WORDS:
        return 100.0 if re.search(rf"(?<!\w){re.escape(span)}(?!\w)", found) else 0.0
    return float(fuzz.partial_ratio(span, found))


def ocr_region_score(image: bytes, region: tuple[float, float, float, float],
                     span_text: str) -> float:
    """How well the OCR text of exactly this region matches span_text (0 to 100)."""
    return span_score(span_text, _ocr_text(image, region))


def verify_bbox(image: bytes, bbox: tuple[float, float, float, float], span_text: str,
                threshold: float = VERIFY_THRESHOLD) -> bool:
    return ocr_region_score(image, bbox, span_text) >= threshold


def request_photo_draft(content: bytes, media_type: str, adapter: ModelAdapter,
                        prompt_version: str | None = None) -> ExtractionDraft:
    prompt = load_prompt("extraction", prompt_version or EXTRACTION_PROMPT_VERSION)
    parts: list[Part] = [
        ImagePart(data=content, mime_type=media_type),
        TextPart(render_prompt(prompt, content=IMAGE_PLACEHOLDER)),
    ]
    return adapter.generate_json(Role.extraction_vision, prompt, parts, ExtractionDraft).value


def ingest_photo(doc: Document, content: bytes, adapter: ModelAdapter,
                 repo: Repository) -> list[FactVersion]:
    with Image.open(io.BytesIO(content)) as img:
        width, height = img.size
    whole = (0.0, 0.0, float(width), float(height))
    draft = request_photo_draft(content, doc.media_type, adapter)

    facts = []
    for index, item in enumerate(draft.facts, start=1):
        bbox, verified, score = whole, False, 0.0
        if item.box_2d is not None:
            try:
                candidate = box_2d_to_pixels(item.box_2d, width, height)
            except ValueError:
                log.info("extraction draft %d: unusable box", index)
            else:
                score = ocr_region_score(content, candidate, item.span_text)
                if score >= VERIFY_THRESHOLD:
                    bbox, verified = candidate, True
        source = VisionSource(
            document_id=doc.document_id,
            bbox=bbox,
            bbox_verified=verified,
            span_text=item.span_text.strip(),
            confidence=score / 100.0,
        )
        fact = draft_to_fact(item, index, doc, source)
        if fact is None:
            continue
        repo.put_fact(fact)
        facts.append(fact)
    log.info("photo ingestion document=%s facts=%d verified_boxes=%d unreadable_regions=%d",
             doc.document_id, len(facts), sum(f.source.bbox_verified for f in facts
                                              if isinstance(f.source, VisionSource)),
             len(draft.unreadable_regions))
    return facts
