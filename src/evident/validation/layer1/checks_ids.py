"""Fact ID check: the first Layer 1 rule, run before anything else (design check table, row 1)."""

from __future__ import annotations

from evident.contracts.enums import FactStatus
from evident.contracts.plan import Claim
from evident.contracts.validation import CheckFailure
from evident.validation.layer1.config import Layer1Context

RULE = "fact_ids"


def _ref(fact_id: str, version: int) -> str:
    return f"{fact_id}@{version}"


def check_fact_ids(claim: Claim, ctx: Layer1Context) -> list[CheckFailure]:
    """Every cited fact version must exist, belong to the owner and be confirmed."""
    if not claim.evidence:
        return [CheckFailure(rule=RULE, phrase=claim.text[:80],
                             detail="The claim cites no evidence.")]
    failures: list[CheckFailure] = []
    for ref in claim.evidence:
        label = _ref(ref.fact_id, ref.version)
        fact = ctx.resolve(ref)
        if fact is None:
            failures.append(CheckFailure(rule=RULE, phrase=label,
                                         detail=f"Cites {label}, which does not exist."))
        elif fact.owner_id != ctx.owner_id:
            failures.append(CheckFailure(rule=RULE, phrase=label,
                                         detail=f"Cites {label}, which belongs to another user."))
        elif fact.status is not FactStatus.confirmed:
            failures.append(CheckFailure(
                rule=RULE, phrase=label,
                detail=f"Cites {label}, which is {fact.status.value}, not confirmed."))
    return failures
