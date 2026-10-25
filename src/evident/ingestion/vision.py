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
from PIL import Image
from rapidfuzz import fuzz

from evident.contracts.documents import Document
from evident.contracts.facts import FactVersion, VisionSource
from evident.errors import ErrorCategory, StageError
from evident.ingestion.drafts import ExtractionDraft, box_2d_to_pixels, draft_to_fact
from evident.models.adapter import ImagePart, ModelAdapter, Part, TextPart
from evident.prompts import load_prompt, render_prompt
from evident.settings import Role
from evident.store.repository import Repository

log = logging.getLogger("evident.ingestion")

WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
CROP_MARGIN = 0.04
VERIFY_THRESHOLD = 80.0
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


def ocr_match_score(image: bytes, bbox: tuple[float, float, float, float],
                    span_text: str) -> float:
    pytesseract.pytesseract.tesseract_cmd = _tesseract()
    with Image.open(io.BytesIO(image)) as img:
        w, h = img.size
        mx, my = CROP_MARGIN * w, CROP_MARGIN * h
        x0, y0, x1, y1 = bbox
        crop = img.convert("L").crop((
            int(max(0, x0 - mx)), int(max(0, y0 - my)),
            int(min(w, x1 + mx)), int(min(h, y1 + my)),
        ))
        text = pytesseract.image_to_string(crop)
    span, found = _normalise(span_text), _normalise(text)
    if not span or not found:
        return 0.0
    return float(fuzz.partial_ratio(span, found))


def verify_bbox(image: bytes, bbox: tuple[float, float, float, float], span_text: str,
                threshold: float = VERIFY_THRESHOLD) -> bool:
    return ocr_match_score(image, bbox, span_text) >= threshold


def ingest_photo(doc: Document, content: bytes, adapter: ModelAdapter,
                 repo: Repository) -> list[FactVersion]:
    with Image.open(io.BytesIO(content)) as img:
        width, height = img.size
    whole = (0.0, 0.0, float(width), float(height))
    prompt = load_prompt("extraction")
    parts: list[Part] = [
        ImagePart(data=content, mime_type=doc.media_type),
        TextPart(render_prompt(prompt, content=IMAGE_PLACEHOLDER)),
    ]
    draft = adapter.generate_json(Role.extraction_vision, prompt, parts, ExtractionDraft).value

    facts = []
    for index, item in enumerate(draft.facts, start=1):
        bbox, verified, score = whole, False, 0.0
        if item.box_2d is not None:
            try:
                candidate = box_2d_to_pixels(item.box_2d, width, height)
            except ValueError:
                log.info("extraction draft %d: unusable box", index)
            else:
                score = ocr_match_score(content, candidate, item.span_text)
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
