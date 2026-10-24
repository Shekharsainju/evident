"""Fact versions, metric records and the source union."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator

from evident.contracts.common import Contract
from evident.contracts.enums import (
    Deployment,
    FactKind,
    FactStatus,
    MetricDirection,
    Ownership,
)

METRIC_VOCAB = frozenset(
    {
        "latency",
        "accuracy",
        "cost",
        "revenue",
        "users",
        "throughput",
        "time_saved",
        "error_rate",
        "coverage",
        "count",
    }
)

# [x0, y0, x1, y1] in PDF points or image pixels.
BBox = tuple[float, float, float, float]

YearMonth = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class MetricRecord(Contract):
    metric_id: str
    metric: str
    direction: MetricDirection
    value: float
    unit: str
    baseline: float | None
    subject: str
    span_text: str

    @field_validator("metric")
    @classmethod
    def _metric_in_vocab(cls, v: str) -> str:
        # other: metrics are allowed here but always route to user review downstream.
        if v in METRIC_VOCAB or (v.startswith("other:") and len(v) > len("other:")):
            return v
        raise ValueError("metric must be in the controlled vocabulary or start with other:")


class FactAttributes(Contract):
    ownership: Ownership | None
    deployment: Deployment | None
    scale: None = None
    metrics: list[MetricRecord]
    start: YearMonth | None
    end: YearMonth | None
    skills: list[str]
    title: str | None
    organisation: str | None


class PdfTextSource(Contract):
    extraction_path: Literal["pdf_text"] = "pdf_text"
    document_id: str
    page: int
    bbox: BBox
    span_text: str
    confidence: float
    span_found: bool


class OcrSource(Contract):
    extraction_path: Literal["ocr"] = "ocr"
    document_id: str
    page: int
    bbox: BBox
    span_text: str
    confidence: float
    span_found: bool


class VisionSource(Contract):
    extraction_path: Literal["vision"] = "vision"
    document_id: str
    bbox: BBox
    bbox_verified: bool
    span_text: str
    confidence: float


class TranscriptSource(Contract):
    extraction_path: Literal["transcript"] = "transcript"
    document_id: str
    start_ms: int
    end_ms: int
    span_text: str


class StorySource(Contract):
    extraction_path: Literal["story"] = "story"
    story_id: str
    field: str
    char_start: int
    char_end: int
    span_text: str


class GapAnswerSource(Contract):
    extraction_path: Literal["gap_answer"] = "gap_answer"
    question_id: str
    answer_id: str
    char_start: int
    char_end: int
    span_text: str


Source = Annotated[
    PdfTextSource | OcrSource | VisionSource | TranscriptSource | StorySource | GapAnswerSource,
    Field(discriminator="extraction_path"),
]


class FactVersion(Contract):
    fact_id: str
    version: int = Field(ge=1)
    owner_id: str
    status: FactStatus
    kind: FactKind
    text: str
    attributes: FactAttributes
    source: Source
    supersedes: int | None
    edited_by_user: bool
    confirmed_at: datetime | None


class FactRef(Contract):
    fact_id: str
    version: int
