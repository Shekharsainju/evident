"""The outcome table (spec 8.5): how Layer 1 and the judge combine. Nothing auto-passes."""

from __future__ import annotations

from evident.contracts.enums import ClaimOutcome, FactStatus, Verdict
from evident.contracts.plan import Claim
from evident.contracts.validation import ClaimValidation, JudgeVerdict
from evident.models.adapter import ModelAdapter
from evident.validation.judge import JUDGE_THRESHOLD, run_judge
from evident.validation.judge import PROMPT_VERSION as JUDGE_PROMPT_VERSION
from evident.validation.layer1.config import Layer1Context
from evident.validation.layer1.run import resolve_facts, run_layer1


def decide(layer1_passed: bool, judge: JudgeVerdict | None, threshold: float) -> ClaimOutcome:
    """One row of the outcome table. A missing verdict is a judge error."""
    confident = judge is not None and judge.confidence >= threshold
    supported = judge is not None and judge.verdict is Verdict.supported
    if layer1_passed:
        if not confident:
            return ClaimOutcome.user_review
        return ClaimOutcome.passed if supported else ClaimOutcome.rejected
    if confident and supported:
        return ClaimOutcome.user_review  # the layers disagree
    return ClaimOutcome.rejected


def _reasons(validation_layer1_failures: list[str], judge: JudgeVerdict | None,
             error: str | None, threshold: float) -> list[str]:
    reasons = list(validation_layer1_failures)
    if error is not None:
        reasons.append(f"judge error: {error}")
    elif judge is not None:
        line = f"judge: {judge.verdict.value} (confidence {judge.confidence:.2f})"
        if judge.verdict is not Verdict.supported and judge.offending_phrase:
            line += f", phrase: {judge.offending_phrase}"
        if judge.confidence < threshold:
            line += f", below the {threshold:.2f} threshold"
        reasons.append(line)
    return reasons


def validate_claim(
    claim: Claim, ctx: Layer1Context, adapter: ModelAdapter, threshold: float = JUDGE_THRESHOLD,
    judge_prompt_version: str = JUDGE_PROMPT_VERSION,
) -> ClaimValidation:
    """Layer 1, then the judge (always), then the outcome table."""
    layer1 = run_layer1(claim, ctx)
    # The judge sees only cited facts that are confirmed and the owner's; a superseded or
    # foreign fact is not evidence, so it must not be able to argue for the claim.
    facts = [f for f in resolve_facts(claim, ctx)
             if f.status is FactStatus.confirmed and f.owner_id == ctx.owner_id]
    verdict, model_id, error = run_judge(claim, facts, adapter, judge_prompt_version)
    outcome = decide(layer1.passed, verdict, threshold)
    failures = [f"{f.rule}: {f.detail}" for f in layer1.failures]
    return ClaimValidation(
        claim_id=claim.claim_id,
        claim_version=claim.version,
        outcome=outcome,
        layer1=layer1,
        judge=verdict,
        judge_model=model_id,
        judge_error=error,
        reasons=_reasons(failures, verdict, error, threshold),
    )
