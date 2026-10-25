from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from evident.render.pdf import html_to_pdf
from evident.render.receipts import PDF_SCALE, crop_source
from tests.builders import document, pdf_source, vision_source


@pytest.fixture(scope="module")
def pdf_bytes(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    html = "<!doctype html><html><body><p style='font:20pt Arial'>Synthetic line</p></body></html>"
    return html_to_pdf(html, tmp_path_factory.mktemp("pdf") / "r.pdf").read_bytes()


def size(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as img:
        assert img.format == "PNG"
        return img.size


def test_crop_source_pdf_returns_png(pdf_bytes: bytes) -> None:
    src = pdf_source(bbox=(50.0, 50.0, 250.0, 80.0))
    w, h = size(crop_source(document(), pdf_bytes, src))
    # 200 x 30 pt box plus a 12 pt margin each side, rendered at PDF_SCALE
    assert w == pytest.approx((200 + 24) * PDF_SCALE, abs=3)
    assert h == pytest.approx((30 + 24) * PDF_SCALE, abs=3)


def test_unfound_pdf_span_shows_whole_page(pdf_bytes: bytes) -> None:
    src = pdf_source(bbox=(0.0, 0.0, 0.0, 0.0), span_found=False)
    w, h = size(crop_source(document(), pdf_bytes, src))
    assert w == pytest.approx(595.3 * PDF_SCALE, abs=4) and h > w


def png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_crop_source_image_uses_pixel_box_with_margin(tmp_path: Path) -> None:
    doc = document(media_type="image/png", width_px=1000, height_px=2000)
    src = vision_source(bbox=(100.0, 200.0, 300.0, 260.0))
    w, h = size(crop_source(doc, png(1000, 2000), src))
    assert (w, h) == (200 + 2 * 40, 60 + 2 * 80)  # 4% of width and height


def test_unverified_image_box_shows_whole_image() -> None:
    doc = document(media_type="image/png", width_px=400, height_px=600)
    src = vision_source(bbox=(0.0, 0.0, 400.0, 600.0), bbox_verified=False)
    assert size(crop_source(doc, png(400, 600), src)) == (400, 600)
