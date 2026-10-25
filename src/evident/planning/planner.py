"""Content planner (design: Pipeline 5, content planner prompt; spec 8.4; invariants section 1).

The planner drafts claims that cite exact fact versions. Its reply is untrusted: drafts that
cannot be turned into a valid claim are dropped here, and every kept claim still goes through
Layers 1 and 2 before anything renders it.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from evident.contracts.coverage import CoverageRow, Target
from evident.contracts.enums import (
    ClaimOutcome,
    CoverageGrade,
    FactStatus,
    OutputType,
    Transformation,
    Verdict,
)
from evident.contracts.facts import FactRef, FactVersion
from evident.contracts.plan import Claim, ContentPlan
from evident.contracts.validation import ClaimValidation
from evident.models.adapter import ModelAdapter, Part, TextPart
from evident.prompts import load_prompt, render_prompt
from evident.settings import Role
from evident.validation.judge import evidence_block

log = logging.getLogger("evident.planning")

RENDERER_LIMITS = (
    "visual profile: at most 10 claims, each at most 160 characters; deck: at most 4 content "
    "slides, at most 3 claims per slide; speaker-note narratives at most 400 characters"
)
FEEDBACK_HEADING = "Rejected claims and reasons"
CLAIM_ID = re.compile(r"^c_(\d+)$")


class DraftClaim(BaseModel):
    text: str
    evidence: list[str] = Field(description='Cited facts, each as "fact_id@version".')
    section: str
    emphasis: int = Field(description="1 (low) to 5 (high).")
    output_types: list[str] = Field(description="visual_profile and/or interview_deck.")
    narrative_for: str | None = Field(
        default=None,
        description="For a speaker-note narrative: the exact text of the claim it expands. "
                    "Null for every other claim.")


class PlanDraft(BaseModel):
    claims: list[DraftClaim]


@dataclass
class _Kept:
    index: int
    text: str
    refs: list[FactRef]
    draft: DraftClaim
    output_types: list[OutputType]


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _parse_ref(value: str) -> FactRef | None:
    fact_id, sep, version = value.strip().rpartition("@")
    if not sep or not fact_id or not version.isdigit() or int(version) < 1:
        return None
    return FactRef(fact_id=fact_id, version=int(version))


def _coverage_matrix(rows: list[CoverageRow]) -> str:
    lines = []
    for r in rows:
        refs = ", ".join(f"{e.fact_id}@{e.version}" for e in r.evidence) or "none"
        lines.append(f"{r.requirement_id} ({r.category.value}, {r.grade.value}): "
                     f"{_one_line(r.text)} | evidence: {refs} | {_one_line(r.rationale)}")
    return "\n".join(lines)


def _quoted(value: str) -> str:
    # Claim text and phrases derive from untrusted content; a stray quote or bar could pose
    # as an extra reason on the same feedback line.
    return _one_line(value).replace('"', "'").replace("|", "/")


def _feedback(feedback: list[ClaimValidation], previous: ContentPlan | None) -> str:
    texts = {c.claim_id: c.text for c in previous.claims} if previous else {}
    lines: list[str] = []
    for v in feedback:
        if v.outcome is not ClaimOutcome.rejected:
            continue
        reasons = [f'rule {f.rule}: "{_quoted(f.phrase)}"' for f in v.layer1.failures]
        if v.judge is not None and v.judge.verdict is not Verdict.supported:
            phrase = _quoted(v.judge.offending_phrase or "")
            reasons.append(f'judge {v.judge.verdict.value}: "{phrase}"')
        if v.judge_error:
            reasons.append("judge error")
        text = _quoted(texts.get(v.claim_id, "(text not available)"))
        lines.append(f'- {v.claim_id}: "{text}" | ' + " | ".join(reasons or ["rejected"]))
    if not lines:
        return ""
    return f"\n{FEEDBACK_HEADING}:\n" + "\n".join(lines) + "\n"


def _check_draft(d: DraftClaim, supported: set[FactRef]) -> tuple[_Kept | None, str]:
    text = d.text.strip()
    if not text:
        return None, "empty text"
    if not 1 <= d.emphasis <= 5:
        return None, "emphasis out of range"
    types: list[OutputType] = []
    for raw in d.output_types:
        try:
            t = OutputType(raw.strip())
        except ValueError:
            return None, "unknown output type"
        if t not in types:
            types.append(t)
    if not types:
        return None, "no output type"
    refs: list[FactRef] = []
    for raw in d.evidence:
        ref = _parse_ref(raw)
        if ref is None:
            return None, "malformed evidence reference"
        if ref not in refs:
            refs.append(ref)
    # Never write a claim for a gap: at least one cited fact must back a graded requirement.
    if not any(r in supported for r in refs):
        return None, "evidence backs no graded requirement"
    return _Kept(index=-1, text=text, refs=refs, draft=d, output_types=types), ""


def build_plan(
    owner_id: str,
    target: Target,
    facts: list[FactVersion],
    coverage: list[CoverageRow],
    adapter: ModelAdapter,
    feedback: list[ClaimValidation] | None = None,
    previous: ContentPlan | None = None,
) -> ContentPlan:
    confirmed = [f for f in facts if f.status is FactStatus.confirmed]
    prompt = load_prompt("planner")
    parts: list[Part] = [TextPart(render_prompt(
        prompt,
        output_types="visual_profile, interview_deck",
        renderer_limits=RENDERER_LIMITS,
        feedback=_feedback(feedback or [], previous),
        confirmed_facts=evidence_block(confirmed),
        coverage_matrix=_coverage_matrix(coverage),
    ))]
    draft = adapter.generate_json(Role.planner, prompt, parts, PlanDraft).value

    supported = {ref for r in coverage if r.grade is not CoverageGrade.gap for ref in r.evidence}
    kept: list[_Kept] = []
    seen: set[str] = set()
    for i, d in enumerate(draft.claims):
        item, reason = _check_draft(d, supported)
        if item is not None and item.text in seen:
            item, reason = None, "duplicate text"
        if item is None:
            log.info("planner dropped draft=%d reason=%s", i, reason)
            continue
        item.index = i
        seen.add(item.text)
        kept.append(item)

    parents = {k.text for k in kept if k.draft.narrative_for is None}
    usable: list[_Kept] = []
    for k in kept:
        target_text = k.draft.narrative_for
        if target_text is not None and target_text.strip() not in parents:
            log.info("planner dropped draft=%d reason=narrative parent not found", k.index)
            continue
        usable.append(k)
    expanded = {k.draft.narrative_for.strip() for k in usable if k.draft.narrative_for}

    prev_by_text = {c.text: c for c in previous.claims} if previous else {}
    numbers = [int(m.group(1)) for c in (previous.claims if previous else [])
               if (m := CLAIM_ID.match(c.claim_id))]
    next_number = max(numbers, default=0) + 1
    ids: dict[str, str] = {}
    for k in usable:
        if k.text in prev_by_text:
            ids[k.text] = prev_by_text[k.text].claim_id
        else:
            ids[k.text] = f"c_{next_number:03d}"
            next_number += 1

    claims: list[Claim] = []
    for k in usable:
        claim_id = ids[k.text]
        if k.draft.narrative_for is not None:
            # A narrative is already the expansion of its parent, so it may not be expanded again.
            parent_id: str | None = ids[k.draft.narrative_for.strip()]
            transformations: list[Transformation] = []
            output_types = [OutputType.interview_deck]
        else:
            parent_id = None
            transformations = [Transformation.shorten]
            if k.text in expanded:
                transformations.append(Transformation.expand_narrative)
            output_types = k.output_types
        version = 1
        old = prev_by_text.get(k.text)
        if old is not None:
            # Same wording with different evidence or reach is a changed claim, so it is a new
            # version and earlier validation results can't be mistaken for it.
            unchanged = (old.evidence == k.refs and old.output_types == output_types
                         and old.parent_claim_id == parent_id
                         and old.allowed_transformations == transformations)
            version = old.version if unchanged else old.version + 1
        claims.append(Claim(claim_id=claim_id, version=version, text=k.text, evidence=k.refs,
                            section=k.draft.section.strip(), emphasis=k.draft.emphasis,
                            allowed_transformations=transformations, output_types=output_types,
                            parent_claim_id=parent_id))

    log.info("planner kept claims=%d of drafts=%d", len(claims), len(draft.claims))
    return ContentPlan(plan_id=f"plan_{uuid.uuid4().hex[:12]}", owner_id=owner_id,
                       target_id=target.target_id, claims=claims, created_at=datetime.now(UTC))
