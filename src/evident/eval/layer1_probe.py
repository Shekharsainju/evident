"""Probe corpus and outcome map for the Layer 1 before and after diff (Phase 1, Task 4).

Dev profiles only: the corpus calls require_dev, so tuning can't reach the locked test split.
"""

from __future__ import annotations

import random

from evident.eval.grounding import (
    DEFAULT_AS_OF,
    LabelledClaim,
    _claim,
    _instances,
    _mutations,
    layer1_context,
)
from evident.eval.splits import P1_DEV_PROFILES, load_p1_dev_claims, require_dev
from evident.validation.layer1.run import run_layer1


def outcome_key(c: LabelledClaim) -> str:
    refs = ",".join(f"{r.fact_id}@{r.version}" for r in c.claim.evidence)
    return f"{c.claim.text}|{refs}"


def probe_claims(seed_range: range = range(50)) -> list[LabelledClaim]:
    require_dev(P1_DEV_PROFILES)
    out: list[LabelledClaim] = list(load_p1_dev_claims())
    for profile in P1_DEV_PROFILES:
        instances = _instances(profile)
        for i in instances:
            out.append(LabelledClaim(
                claim=_claim("probe", i.text, i.refs, i.section), label="supported",
                category=None, profile_id=profile, split="dev", template=i.template))
        for seed in seed_range:
            for m in _mutations(instances, random.Random(seed)):
                out.append(LabelledClaim(
                    claim=_claim("probe", m.text, m.refs, m.base.section), label="unsupported",
                    category=m.category, profile_id=profile, split="dev",
                    template=m.base.template, mutated_from=m.base.key,
                    base_text=m.base.text, base_evidence=list(m.base.refs)))
    seen: set[str] = set()
    unique: list[LabelledClaim] = []
    for c in out:
        key = outcome_key(c)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def layer1_outcomes(claims: list[LabelledClaim]) -> dict[str, list[str]]:
    contexts: dict[str, object] = {}
    result: dict[str, list[str]] = {}
    for c in claims:
        if c.profile_id not in contexts:
            contexts[c.profile_id] = layer1_context(c.profile_id, DEFAULT_AS_OF)
        res = run_layer1(c.claim, contexts[c.profile_id])  # type: ignore[arg-type]
        result[outcome_key(c)] = sorted({f.rule for f in res.failures})
    return result
