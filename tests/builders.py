"""Builders for valid contract objects in tests. All data is synthetic."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from evident.contracts.documents import Document
from evident.contracts.facts import (
    FactAttributes,
    FactVersion,
    MetricRecord,
    PdfTextSource,
    VisionSource,
)

OWNER = "local-demo"
NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


def attrs(**overrides: Any) -> FactAttributes:
    base: dict[str, Any] = {
        "ownership": None,
        "deployment": None,
        "metrics": [],
        "start": None,
        "end": None,
        "skills": [],
        "title": None,
        "organisation": None,
    }
    base.update(overrides)
    return FactAttributes(**base)


def metric(**overrides: Any) -> MetricRecord:
    base: dict[str, Any] = {
        "metric_id": "m_01",
        "metric": "latency",
        "direction": "decrease",
        "value": 2.0,
        "unit": "seconds",
        "baseline": None,
        "subject": "timetable clash check",
        "span_text": "cut timetable clash checks to under 2 seconds",
    }
    base.update(overrides)
    return MetricRecord(**base)


def pdf_source(document_id: str = "doc_01", **overrides: Any) -> PdfTextSource:
    base: dict[str, Any] = {
        "document_id": document_id,
        "page": 1,
        "bbox": (72.0, 400.0, 540.0, 420.0),
        "span_text": "Built a timetable clash checker (Python, Flask)",
        "confidence": 0.9,
        "span_found": True,
    }
    base.update(overrides)
    return PdfTextSource(**base)


def vision_source(document_id: str = "doc_01", **overrides: Any) -> VisionSource:
    base: dict[str, Any] = {
        "document_id": document_id,
        "bbox": (10.0, 20.0, 300.0, 60.0),
        "bbox_verified": True,
        "span_text": "Built a timetable clash checker (Python, Flask)",
        "confidence": 0.9,
    }
    base.update(overrides)
    return VisionSource(**base)


def fact(fact_id: str = "doc_01_f01", version: int = 1, **overrides: Any) -> FactVersion:
    base: dict[str, Any] = {
        "fact_id": fact_id,
        "version": version,
        "owner_id": OWNER,
        "status": "extracted",
        "kind": "project",
        "text": "Built a timetable clash checker in Python and Flask",
        "attributes": attrs(skills=["Python", "Flask"]),
        "source": pdf_source(),
        "supersedes": None,
        "edited_by_user": False,
        "confirmed_at": None,
    }
    base.update(overrides)
    return FactVersion(**base)


def document(document_id: str = "doc_01", **overrides: Any) -> Document:
    base: dict[str, Any] = {
        "document_id": document_id,
        "owner_id": OWNER,
        "kind": "cv",
        "media_type": "application/pdf",
        "filename": "synthetic_cv.pdf",
        "sha256": "0" * 64,
        "width_px": None,
        "height_px": None,
        "created_at": NOW,
    }
    base.update(overrides)
    return Document(**base)
