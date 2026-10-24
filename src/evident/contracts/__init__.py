"""Frozen contracts. Changing one needs owner approval and a schema_version bump."""

from __future__ import annotations

from evident.contracts.common import Contract
from evident.contracts.coverage import CoverageRow, Requirement, Target
from evident.contracts.documents import Document
from evident.contracts.facts import (
    FactAttributes,
    FactRef,
    FactVersion,
    GapAnswerSource,
    MetricRecord,
    OcrSource,
    PdfTextSource,
    StorySource,
    TranscriptSource,
    VisionSource,
)
from evident.contracts.outputs import Output, PostRenderResult
from evident.contracts.plan import Claim, ContentPlan
from evident.contracts.runs import RunStatus
from evident.contracts.validation import (
    CheckFailure,
    ClaimValidation,
    JudgeVerdict,
    Layer1Result,
    ValidationReport,
)

ALL_CONTRACTS: tuple[type[Contract], ...] = (
    MetricRecord,
    FactAttributes,
    PdfTextSource,
    OcrSource,
    VisionSource,
    TranscriptSource,
    StorySource,
    GapAnswerSource,
    FactVersion,
    FactRef,
    Document,
    Target,
    Requirement,
    CoverageRow,
    Claim,
    ContentPlan,
    CheckFailure,
    Layer1Result,
    JudgeVerdict,
    ClaimValidation,
    ValidationReport,
    PostRenderResult,
    Output,
    RunStatus,
)

__all__ = ["ALL_CONTRACTS", "Contract"]
