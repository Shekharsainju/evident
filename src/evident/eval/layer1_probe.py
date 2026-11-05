"""Probe corpus and outcome map for the Layer 1 before and after diff (Phase 1, Task 4).

Dev profiles only: the corpus calls require_dev, so tuning can't reach the locked test split.
"""

from __future__ import annotations

import random
from typing import Any

from evident.eval.grounding import (
    DEFAULT_AS_OF,
    LabelledClaim,
    _claim,
    _instances,
    _mutations,
    layer1_context,
)
from evident.eval.splits import P1_DEV_PROFILES, load_p1_dev_claims, require_dev
from evident.validation.layer1.config import Layer1Context
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
    return dedupe_fail_closed(out)


def dedupe_fail_closed(claims: list[LabelledClaim]) -> list[LabelledClaim]:
    """One claim per outcome key. If labels disagree, keep the unsupported one, so a
    colliding probe can never be scored as supported and hide a false accept."""
    kept: dict[str, LabelledClaim] = {}
    for c in claims:
        key = outcome_key(c)
        prior = kept.get(key)
        if prior is None or (prior.label == "supported" and c.label == "unsupported"):
            kept[key] = c
    return list(kept.values())


def classify(
    claims: list[LabelledClaim], old: list[list[str]], new: dict[str, list[str]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Compare failing rules per claim. K: unsupported newly passes (the gate), S: supported
    newly passes, F: supported newly fails, U: unsupported newly fails."""
    changed: list[dict[str, Any]] = []
    counts = {"K": 0, "S": 0, "F": 0, "U": 0}
    for c, old_rules in zip(claims, old, strict=True):
        new_rules = new[outcome_key(c)]
        if bool(old_rules) == bool(new_rules):
            continue
        newly_passing = not new_rules
        letter = {(True, "unsupported"): "K", (True, "supported"): "S",
                  (False, "supported"): "F", (False, "unsupported"): "U"}[(newly_passing, c.label)]
        counts[letter] += 1
        changed.append({"label": c.label, "old": old_rules, "new": new_rules,
                        "text": c.claim.text, "evidence": outcome_key(c).split("|")[-1]})
    return changed, counts


def layer1_outcomes(claims: list[LabelledClaim]) -> dict[str, list[str]]:
    contexts: dict[str, Layer1Context] = {}
    result: dict[str, list[str]] = {}
    for c in claims:
        if c.profile_id not in contexts:
            contexts[c.profile_id] = layer1_context(c.profile_id, DEFAULT_AS_OF)
        res = run_layer1(c.claim, contexts[c.profile_id])
        result[outcome_key(c)] = sorted({f.rule for f in res.failures})
    return result
