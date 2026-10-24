"""Results of the claim validation layers."""

from __future__ import annotations

from pydantic import Field

from evident.contracts.common import Contract
from evident.contracts.enums import ClaimOutcome, Verdict


class CheckFailure(Contract):
    rule: str
    phrase: str
    detail: str


class Layer1Result(Contract):
    passed: bool
    failures: list[CheckFailure]


class JudgeVerdict(Contract):
    verdict: Verdict
    offending_phrase: str | None
    corrected_phrasing: str | None
    confidence: float = Field(ge=0, le=1)


class ClaimValidation(Contract):
    claim_id: str
    claim_version: int
    outcome: ClaimOutcome
    layer1: Layer1Result
    judge: JudgeVerdict | None
    judge_model: str | None
    judge_error: str | None
    reasons: list[str]
    approved_by_user: bool = False


class ValidationReport(Contract):
    plan_id: str
    results: list[ClaimValidation]
    dropped_claim_ids: list[str]
    models_by_role: dict[str, str]
    limitations: list[str]
