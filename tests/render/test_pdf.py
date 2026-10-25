from __future__ import annotations

from pathlib import Path

import pdfplumber
from PIL import Image

from evident.render.pdf import html_to_pdf, html_to_png

HTML = """<!doctype html><html><head><meta charset="utf-8"><title>t</title></head>
<body><h1>Synthetic heading</h1><p>Second line &amp; more text</p></body></html>"""


def test_html_to_pdf_text_extractable(tmp_path: Path) -> None:
    out = html_to_pdf(HTML, tmp_path / "x.pdf")
    with pdfplumber.open(out) as pdf:
        text = pdf.pages[0].extract_text() or ""
        width = pdf.pages[0].width
    assert "Synthetic heading" in text and "Second line & more text" in text
    assert abs(width - 595.3) < 1.5  # A4 in points; Chromium rounds to 595.92


def test_html_to_png_full_page_at_width(tmp_path: Path) -> None:
    out = html_to_png(HTML, tmp_path / "x.png", width=800)
    with Image.open(out) as img:
        assert img.width == 800 and img.height > 50
