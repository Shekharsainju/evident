"""Content plan: claims that each cite exact fact versions."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from evident.contracts.common import Contract
from evident.contracts.enums import OutputType, Transformation
from evident.contracts.facts import FactRef


class Claim(Contract):
    claim_id: str
    version: int = 1
    text: str
    evidence: list[FactRef]
    section: str
    emphasis: int = Field(ge=1, le=5)
    allowed_transformations: list[Transformation]
    output_types: list[OutputType]
    parent_claim_id: str | None


class ContentPlan(Contract):
    plan_id: str
    owner_id: str
    target_id: str
    claims: list[Claim]
    created_at: datetime
