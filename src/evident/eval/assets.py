"""Synthetic test assets: CVs rendered from enriched profiles, simulated phone photos and a
job ad screenshot (spec 6.2 and 6.4). All of it is marked synthetic."""

from __future__ import annotations

import io
import random
from pathlib import Path
from typing import Any

import numpy as np
import pypdfium2 as pdfium
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageFilter

from evident.eval.datasets import A3_ENRICHED, ENRICHED_DIR, dataset_for

MARKER = A3_ENRICHED.marker
JOB_MARKER = "Synthetic job ad, A3 testing"
TEMPLATES = ("classic", "sidebar", "compact")
TEMPLATE_DIR = ENRICHED_DIR / "templates"
RENDERED_DIR = ENRICHED_DIR / "rendered"
SCREENSHOT_JOB_ID = "graduate_ai_engineer"
JOB_SCREENSHOT = RENDERED_DIR / f"job_{SCREENSHOT_JOB_ID}.png"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(enabled_extensions=("j2", "html"), default=True),
)


def cv_pdf_path(document_id: str, template: str) -> Path:
    return dataset_for(document_id).rendered_dir / f"{document_id}_{template}.pdf"


def cv_photo_path(document_id: str, template: str) -> Path:
    return dataset_for(document_id).rendered_dir / f"{document_id}_{template}_photo.jpg"


def photo_seed(document_id: str, template: str) -> int:
    """Profile n, template j gets 100 * n + j: the seeds profiles 01 to 05 always had."""
    return 100 * int(document_id.rsplit("_", 1)[1]) + TEMPLATES.index(template)


def month(value: str) -> str:
    year, mm = value.split("-")
    return f"{MONTHS[int(mm) - 1]} {year}"


def date_range(start: str, end: str | None) -> str:
    return f"{month(start)} to {month(end) if end else 'present'}"


def cv_context(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": profile["name"],
        "degree": profile["degree"],
        "institution": profile["institution"],
        "education_dates": (
            f"{month(profile['education_start'])} to present "
            f"(expected {month(profile['expected_graduation_month'])})"
        ),
        "subjects": profile["relevant_current_subjects"] + profile["coursework_highlights"],
        "experience": [
            {**e, "dates": date_range(e["start"], e["end"])} for e in profile["experience"]
        ],
        "projects": [
            {**p, "dates": date_range(p["start"], p["end"])} for p in profile["projects"]
        ],
        "skills": profile["technical_skills"],
        "marker": dataset_for(profile["document_id"]).marker,
    }


def render_cv_html(profile: dict[str, Any], template: str) -> str:
    return _env.get_template(f"{template}.html.j2").render(cv=cv_context(profile))


def pdf_page_png(pdf: bytes, page: int = 0, scale: float = 2.0) -> bytes:
    doc = pdfium.PdfDocument(pdf)
    try:
        image = doc[page].render(scale=scale).to_pil()
    finally:
        doc.close()
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _perspective_coeffs(
    dst: list[tuple[float, float]], src: list[tuple[float, float]]
) -> list[float]:
    # Solve for the 8 coefficients that map each output corner back to its source corner.
    rows = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    a = np.array(rows, dtype=float)
    b = np.array([c for pair in src for c in pair], dtype=float)
    return [float(c) for c in np.linalg.solve(a, b)]


def simulate_photo(page_png: bytes, seed: int) -> bytes:
    """A rough phone photo of a printed page: warp, tilt, uneven light, blur, noise, JPEG.

    These are easier than real phone photos, and results say so.
    """
    rnd = random.Random(seed)
    rng = np.random.default_rng(seed)
    img = Image.open(io.BytesIO(page_png)).convert("RGB")
    w, h = img.size
    table = (96, 90, 84)

    def jitter(x: float, y: float) -> tuple[float, float]:
        return (x + rnd.uniform(-0.04, 0.04) * w, y + rnd.uniform(-0.04, 0.04) * h)

    corners = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
    moved = [jitter(x, y) for x, y in corners]
    img = img.transform((w, h), Image.Transform.PERSPECTIVE,
                        _perspective_coeffs(moved, corners), Image.Resampling.BICUBIC,
                        fillcolor=table)
    img = img.rotate(rnd.uniform(-3.0, 3.0), Image.Resampling.BICUBIC, expand=False,
                     fillcolor=table)

    arr = np.asarray(img, dtype=np.float64)
    angle = rnd.uniform(0, 2 * np.pi)
    yy, xx = np.mgrid[0:h, 0:w]
    ramp = (np.cos(angle) * xx / w + np.sin(angle) * yy / h)
    ramp = (ramp - ramp.min()) / (ramp.max() - ramp.min() + 1e-9)
    arr = arr * (0.72 + 0.33 * ramp)[..., None]
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(radius=rnd.uniform(0.8, 1.5)))

    arr = np.asarray(img, dtype=np.float64) + rng.normal(0, 4, size=(h, w, 3))
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def render_job_html(job: dict[str, Any]) -> str:
    return _env.get_template("job_board.html.j2").render(job=job, marker=JOB_MARKER)
