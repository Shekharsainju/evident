"""What the extraction model returns, and its conversion into extracted fact versions.

The draft schemas are deliberately loose: the model's output is untrusted, so the strict
contracts are applied here, field by field, and anything that doesn't fit is dropped
rather than guessed.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, ValidationError

from evident.contracts.documents import Document
from evident.contracts.enums import Deployment, FactKind, FactStatus, MetricDirection, Ownership
from evident.contracts.facts import (
    METRIC_VOCAB,
    FactAttributes,
    FactVersion,
    MetricRecord,
    Source,
)

log = logging.getLogger("evident.ingestion")

YEAR_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
BOX_SCALE = 1000.0
# Chosen on the dev split (profile 01) on 2026-10-25: v2 found 48/48 facts, v1 29/48.
EXTRACTION_PROMPT_VERSION = "v2"


class DraftMetric(BaseModel):
    metric: str
    direction: str
    value: float
    unit: str
    subject: str = ""
    span_text: str = ""


class DraftAttributes(BaseModel):
    ownership: str | None = None
    deployment: str | None = None
    start: str | None = None
    end: str | None = None
    title: str | None = None
    organisation: str | None = None
    skills: list[str] = []
    metrics: list[DraftMetric] = []


class ExtractedFactDraft(BaseModel):
    kind: str
    text: str
    span_text: str
    box_2d: list[int] | None = None
    attributes: DraftAttributes = DraftAttributes()


class ExtractionDraft(BaseModel):
    facts: list[ExtractedFactDraft]
    unreadable_regions: list[str] = []


def box_2d_to_pixels(
    box_2d: list[int], width: int, height: int
) -> tuple[float, float, float, float]:
    """Gemini boxes are [ymin, xmin, ymax, xmax] on a 0 to 1000 scale; ours are
    [x0, y0, x1, y1] in pixels."""
    if len(box_2d) != 4:
        raise ValueError("box_2d needs 4 numbers")
    ymin, xmin, ymax, xmax = (max(0.0, min(BOX_SCALE, float(v))) for v in box_2d)
    if xmax <= xmin or ymax <= ymin:
        raise ValueError("box_2d is empty or inverted")
    return (
        xmin / BOX_SCALE * width,
        ymin / BOX_SCALE * height,
        xmax / BOX_SCALE * width,
        ymax / BOX_SCALE * height,
    )


def _enum[E: (Ownership, Deployment, MetricDirection)](
    cls: type[E], value: str | None
) -> E | None:
    if value is None:
        return None
    try:
        return cls(value.strip().lower())
    except ValueError:
        return None


def _year_month(value: str | None) -> str | None:
    return value if value is not None and YEAR_MONTH.match(value.strip()) else None


def _metric_name(name: str) -> str:
    clean = name.strip().lower()
    if clean in METRIC_VOCAB:
        return clean
    if clean.startswith("other:"):
        clean = clean[len("other:"):]
    slug = re.sub(r"[^a-z0-9]+", "_", clean).strip("_") or "unnamed"
    return f"other:{slug}"


def _metrics(drafts: list[DraftMetric]) -> list[MetricRecord]:
    records: list[MetricRecord] = []
    for m in drafts:
        direction = _enum(MetricDirection, m.direction)
        if direction is None:
            continue
        records.append(MetricRecord(
            metric_id=f"m_{len(records) + 1:02d}",
            metric=_metric_name(m.metric),
            direction=direction,
            value=float(m.value),
            unit=m.unit.strip(),
            baseline=None,
            subject=m.subject.strip(),
            span_text=m.span_text.strip(),
        ))
    return records


def draft_to_fact(
    draft: ExtractedFactDraft, index: int, doc: Document, source: Source
) -> FactVersion | None:
    """Turn one model draft into an extracted fact, or None if it can't be a fact."""
    try:
        kind = FactKind(draft.kind.strip().lower())
    except ValueError:
        log.info("extraction draft %d skipped: unknown kind", index)
        return None
    if not draft.span_text.strip() or not draft.text.strip():
        log.info("extraction draft %d skipped: empty text or span", index)
        return None
    a = draft.attributes
    try:
        attributes = FactAttributes(
            ownership=_enum(Ownership, a.ownership),
            deployment=_enum(Deployment, a.deployment),
            metrics=_metrics(a.metrics),
            start=_year_month(a.start),
            end=_year_month(a.end),
            skills=[s.strip() for s in a.skills if s.strip()],
            title=(a.title or "").strip() or None,
            organisation=(a.organisation or "").strip() or None,
        )
        return FactVersion(
            fact_id=f"{doc.document_id}_f{index:02d}",
            version=1,
            owner_id=doc.owner_id,
            status=FactStatus.extracted,
            kind=kind,
            text=draft.text.strip(),
            attributes=attributes,
            source=source,
            supersedes=None,
            edited_by_user=False,
            confirmed_at=None,
        )
    except ValidationError:
        log.info("extraction draft %d skipped: failed contract validation", index)
        return None
