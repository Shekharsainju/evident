"""Source crops for receipts: the part of the original document a fact came from."""

from __future__ import annotations

import io

import pypdfium2 as pdfium
from PIL import Image

from evident.contracts.documents import Document
from evident.contracts.facts import OcrSource, PdfTextSource, Source, VisionSource
from evident.errors import ErrorCategory, StageError

PDF_SCALE = 2.0
PDF_MARGIN_PT = 12.0
IMAGE_MARGIN = 0.04
NO_BOX = (0.0, 0.0, 0.0, 0.0)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _ints(box: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    return (round(box[0]), round(box[1]), round(box[2]), round(box[3]))


def crop_source(doc: Document, content: bytes, source: Source) -> bytes:
    if isinstance(source, PdfTextSource | OcrSource):
        pdf = pdfium.PdfDocument(content)
        try:
            page = pdf[source.page - 1]
            img = page.render(scale=PDF_SCALE).to_pil()
        finally:
            pdf.close()
        if tuple(source.bbox) == NO_BOX:
            return _png(img)  # span not found: show the whole page, never a guessed spot
        x0, y0, x1, y1 = source.bbox
        m = PDF_MARGIN_PT
        box = (max(0.0, x0 - m) * PDF_SCALE, max(0.0, y0 - m) * PDF_SCALE,
               min(img.width, (x1 + m) * PDF_SCALE), min(img.height, (y1 + m) * PDF_SCALE))
        return _png(img.crop(_ints(box)))
    if isinstance(source, VisionSource):
        with Image.open(io.BytesIO(content)) as opened:
            img = opened.convert("RGB")
        if not source.bbox_verified:
            return _png(img)
        x0, y0, x1, y1 = source.bbox
        mx, my = IMAGE_MARGIN * img.width, IMAGE_MARGIN * img.height
        box = (max(0.0, x0 - mx), max(0.0, y0 - my), min(img.width, x1 + mx),
               min(img.height, y1 + my))
        return _png(img.crop(_ints(box)))
    raise StageError(code="no_crop", category=ErrorCategory.internal,
                     detail=f"No visual source for {source.extraction_path}.")
