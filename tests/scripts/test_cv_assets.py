"""Checks on the committed rendered CVs, photos and job screenshot (built by scripts/)."""

from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import pdfplumber
import pytest
from PIL import Image

from evident.eval.assets import (
    JOB_SCREENSHOT,
    MARKER,
    TEMPLATES,
    cv_pdf_path,
    cv_photo_path,
    pdf_page_png,
    render_cv_html,
    simulate_photo,
)
from evident.eval.datasets import load_enriched_profiles, load_ground_truth

PROFILES = load_enriched_profiles()


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        # Content-stream order keeps each column together; line order interleaves columns.
        return squash(" ".join(page.extract_text(use_text_flow=True) or "" for page in pdf.pages))


def test_all_15_cvs_exist_and_carry_marker() -> None:
    for p in PROFILES:
        for template in TEMPLATES:
            path = cv_pdf_path(p["document_id"], template)
            assert path.exists(), path
            assert MARKER in pdf_text(path), path


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_ground_truth_title_appears_in_pdf_text(template: str) -> None:
    for p in PROFILES:
        text = pdf_text(cv_pdf_path(p["document_id"], template))
        for fact in load_ground_truth(p["document_id"]):
            if fact.attributes.title:
                assert squash(fact.attributes.title) in text, (template, fact.attributes.title)


def test_metric_sentences_rendered() -> None:
    for p in PROFILES:
        text = pdf_text(cv_pdf_path(p["document_id"], "classic"))
        for entry in p["projects"] + p["experience"]:
            for m in entry["metrics"]:
                assert squash(m["span_text"]) in text


def test_templates_differ_in_layout() -> None:
    p = PROFILES[0]
    htmls = {t: render_cv_html(p, t) for t in TEMPLATES}
    assert len(set(htmls.values())) == len(TEMPLATES)


def test_cv_html_escapes_user_text() -> None:
    p = {**PROFILES[0], "name": "A <b>bold</b> & name"}
    html = render_cv_html(p, "classic")
    assert "<b>bold</b>" not in html and "&lt;b&gt;" in html


def test_all_15_photos_exist() -> None:
    for p in PROFILES:
        for template in TEMPLATES:
            assert cv_photo_path(p["document_id"], template).exists()
    assert JOB_SCREENSHOT.exists()


def page_png() -> bytes:
    return pdf_page_png(cv_pdf_path(PROFILES[0]["document_id"], "classic").read_bytes())


def test_simulate_photo_deterministic_per_seed() -> None:
    png = page_png()
    assert simulate_photo(png, seed=7) == simulate_photo(png, seed=7)
    assert simulate_photo(png, seed=7) != simulate_photo(png, seed=8)


def test_photo_differs_from_source() -> None:
    png = page_png()
    source = Image.open(io.BytesIO(png)).convert("L")
    photo = Image.open(io.BytesIO(simulate_photo(png, seed=1))).convert("L").resize(source.size)
    diff = np.abs(np.asarray(source, dtype=float) - np.asarray(photo, dtype=float)).mean()
    assert diff > 10
