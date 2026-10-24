"""Job targets, their requirements and the graded coverage matrix."""

from __future__ import annotations

from evident.contracts.common import Contract
from evident.contracts.enums import CoverageGrade, RequirementCategory
from evident.contracts.facts import FactRef


class Target(Contract):
    target_id: str
    owner_id: str
    title: str
    source_job_id: str | None
    document_id: str | None


class Requirement(Contract):
    requirement_id: str
    text: str
    category: RequirementCategory


class CoverageRow(Contract):
    requirement_id: str
    text: str
    category: RequirementCategory
    grade: CoverageGrade
    evidence: list[FactRef]
    rationale: str
