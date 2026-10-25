"""Runs the Layer 1 checks in order and collects every failure (plan Task 12)."""

from __future__ import annotations

from collections.abc import Callable

from evident.contracts.facts import FactVersion
from evident.contracts.plan import Claim
from evident.contracts.validation import CheckFailure, Layer1Result
from evident.validation.layer1 import checks_refs, checks_scope
from evident.validation.layer1.checks_ids import check_fact_ids
from evident.validation.layer1.config import Layer1Context

Check = Callable[[Claim, list[FactVersion], Layer1Context], list[CheckFailure]]

# Order matters only for reading the report: every check runs and every failure is kept.
CHECKS: list[Check] = [
    checks_refs.check_metrics,
    checks_refs.check_scale,
    checks_refs.check_aggregates,
    checks_scope.check_dates,
    checks_scope.check_durations,
    checks_scope.check_ownership,
    checks_scope.check_deployment,
    checks_scope.check_skills,
    checks_scope.check_entities,
]


def resolve_facts(claim: Claim, ctx: Layer1Context) -> list[FactVersion]:
    facts: list[FactVersion] = []
    for ref in claim.evidence:
        fact = ctx.resolve(ref)
        if fact is not None:
            facts.append(fact)
    return facts


def run_layer1(claim: Claim, ctx: Layer1Context) -> Layer1Result:
    """Fact IDs first. If they fail, nothing else can be checked against the evidence."""
    failures = check_fact_ids(claim, ctx)
    if failures:
        return Layer1Result(passed=False, failures=failures)
    facts = resolve_facts(claim, ctx)
    for check in CHECKS:
        failures.extend(check(claim, facts, ctx))
    return Layer1Result(passed=not failures, failures=failures)
