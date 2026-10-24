"""Closed vocabularies from the design data model."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from evident.errors import ErrorCategory

__all__ = [
    "ClaimOutcome",
    "CoverageGrade",
    "Deployment",
    "DocumentKind",
    "ErrorCategory",
    "ExtractionPath",
    "FactKind",
    "FactStatus",
    "MetricDirection",
    "OutputType",
    "Ownership",
    "RequirementCategory",
    "RunStage",
    "RunState",
    "Transformation",
    "Verdict",
]


class ContractEnum(StrEnum):
    """Accepts a plain string value even under strict mode.

    Strict mode otherwise demands enum instances for Python input, which would force every
    caller and fixture to import enums just to build a dict. Invalid values still fail.
    """

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: type[Any], handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        def coerce(value: Any) -> Any:
            if isinstance(value, str) and not isinstance(value, cls):
                return cls(value)
            return value

        return core_schema.no_info_before_validator_function(coerce, handler(source))


class FactStatus(ContractEnum):
    extracted = "extracted"
    confirmed = "confirmed"
    rejected = "rejected"
    superseded = "superseded"


class ExtractionPath(ContractEnum):
    pdf_text = "pdf_text"
    ocr = "ocr"
    vision = "vision"
    transcript = "transcript"
    story = "story"
    gap_answer = "gap_answer"


class Ownership(ContractEnum):
    contributed = "contributed"
    built = "built"
    led = "led"


class Deployment(ContractEnum):
    concept = "concept"
    prototype = "prototype"
    internal = "internal"
    production = "production"


class MetricDirection(ContractEnum):
    increase = "increase"
    decrease = "decrease"
    absolute = "absolute"


class CoverageGrade(ContractEnum):
    strong = "strong"
    partial = "partial"
    weak = "weak"
    gap = "gap"


class RequirementCategory(ContractEnum):
    required = "required"
    preferred = "preferred"
    responsibility = "responsibility"
    boilerplate = "boilerplate"


class FactKind(ContractEnum):
    experience = "experience"
    project = "project"
    education = "education"
    certification = "certification"
    skill = "skill"
    award = "award"


class Verdict(ContractEnum):
    supported = "supported"
    overstated = "overstated"
    unsupported = "unsupported"


class ClaimOutcome(ContractEnum):
    passed = "passed"
    rejected = "rejected"
    user_review = "user_review"


class OutputType(ContractEnum):
    visual_profile = "visual_profile"
    interview_deck = "interview_deck"


class Transformation(ContractEnum):
    shorten = "shorten"
    expand_narrative = "expand_narrative"


class DocumentKind(ContractEnum):
    cv = "cv"
    job_ad = "job_ad"


class RunStage(ContractEnum):
    ingest = "ingest"
    review = "review"
    coverage = "coverage"
    plan = "plan"
    validate = "validate"
    render = "render"
    verify = "verify"
    done = "done"


class RunState(ContractEnum):
    pending = "pending"
    running = "running"
    waiting_for_user = "waiting_for_user"
    quota_exhausted = "quota_exhausted"
    failed = "failed"
    done = "done"
