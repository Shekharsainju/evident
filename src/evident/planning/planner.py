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
from evident.contracts.validation import ClaimValidation, ValidationReport
from evident.models.adapter import ModelAdapter, Part, TextPart
from evident.prompts import load_prompt, render_prompt
from evident.render.profile_html import by_section
from evident.settings import Role, load_model_config
from evident.validation.judge import evidence_block, limitations
from evident.validation.layer1.config import Layer1Context
from evident.validation.outcome import validate_claim

log = logging.getLogger("evident.planning")

RENDERER_LIMITS = (
    "visual profile: at most 10 claims, each at most 160 characters; deck: at most 4 content "
    "slides, at most 3 claims per slide; speaker-note narratives at most 400 characters"
)
# The deck limits stated in RENDERER_LIMITS, enforced when the deck claims are chosen.
MAX_DECK_SLIDES = 4
MAX_CLAIMS_PER_SLIDE = 3
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


def _choose_deck(claims: list[Claim]) -> list[Claim]:
    """Decide the deck claims here, before validation, so the stored output types are the
    ones validated and the deck renderer draws exactly the deck claims that pass.

    If the planner tagged no claim for the deck, every claim is a candidate (the fallback).
    Candidates are grouped into slides the way the renderer groups them and trimmed to the
    deck limits, highest emphasis first. Narratives follow their parent onto the deck or
    are dropped with it.
    """
    body = [c for c in claims if c.parent_claim_id is None]
    tagged = [c for c in body if OutputType.interview_deck in c.output_types]
    candidates = tagged or body
    chosen = {c.claim_id for _, group in by_section(candidates)[:MAX_DECK_SLIDES]
              for c in group[:MAX_CLAIMS_PER_SLIDE]}
    if not tagged and chosen:
        log.info("planner deck fallback tagged=%d of claims=%d", len(chosen), len(body))
    elif len(chosen) < len(tagged):
        log.info("planner deck trimmed=%d to limits kept=%d", len(tagged) - len(chosen),
                 len(chosen))

    narratives = [c for c in claims if c.parent_claim_id is not None]
    kept_narratives = [n for n in narratives if n.parent_claim_id in chosen]
    if len(kept_narratives) < len(narratives):
        log.info("planner dropped narratives=%d parent not on deck",
                 len(narratives) - len(kept_narratives))
    expanded = {n.parent_claim_id for n in kept_narratives}

    out: list[Claim] = []
    dropped = 0
    for c in claims:
        if c.parent_claim_id is not None:
            if c in kept_narratives:
                # A narrative is already the expansion of its parent, so it may not be
                # expanded again.
                out.append(c.model_copy(update={"allowed_transformations": []}))
            continue
        wanted: set[OutputType] = {t for t in c.output_types
                                   if t is not OutputType.interview_deck}
        if c.claim_id in chosen:
            wanted.add(OutputType.interview_deck)
        if not wanted:
            dropped += 1  # a deck-only claim that didn't make the deck
            continue
        transformations = [Transformation.shorten]
        if c.claim_id in expanded:
            transformations.append(Transformation.expand_narrative)
        out.append(c.model_copy(update={
            "output_types": [t for t in OutputType if t in wanted],
            "allowed_transformations": transformations}))
    if dropped:
        log.info("planner dropped deck-only claims=%d over deck limits", dropped)
    return out


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

    drafted: list[Claim] = []
    for k in usable:
        narrative = k.draft.narrative_for is not None
        drafted.append(Claim(
            claim_id=ids[k.text], text=k.text, evidence=k.refs,
            section=k.draft.section.strip(), emphasis=k.draft.emphasis,
            allowed_transformations=[],  # set in _choose_deck, once narratives are final
            output_types=[OutputType.interview_deck] if narrative else k.output_types,
            parent_claim_id=ids[(k.draft.narrative_for or "").strip()] if narrative else None))

    claims: list[Claim] = []
    for c in _choose_deck(drafted):
        old = prev_by_text.get(c.text)
        if old is not None:
            # Same wording with different evidence or reach is a changed claim, so it is a new
            # version and earlier validation results can't be mistaken for it.
            unchanged = (old.evidence == c.evidence and old.output_types == c.output_types
                         and old.parent_claim_id == c.parent_claim_id
                         and old.allowed_transformations == c.allowed_transformations)
            c = c.model_copy(update={"version": old.version if unchanged else old.version + 1})
        claims.append(c)

    log.info("planner kept claims=%d of drafts=%d", len(claims), len(draft.claims))
    return ContentPlan(plan_id=f"plan_{uuid.uuid4().hex[:12]}", owner_id=owner_id,
                       target_id=target.target_id, claims=claims, created_at=datetime.now(UTC))


def plan_and_validate(
    owner_id: str,
    target: Target,
    facts: list[FactVersion],
    coverage: list[CoverageRow],
    ctx: Layer1Context,
    adapter: ModelAdapter,
    max_rounds: int = 2,
) -> tuple[ContentPlan, ValidationReport]:
    """Plan, validate every claim, and send rejections back to the planner (spec 8.4).

    Each round's plan replaces the previous one. Claims still rejected after the last round
    are listed in `dropped_claim_ids`. They stay in the plan with their results so the claims
    page can show what was rejected and why; `renderable_claims` skips every dropped ID.
    """
    plan: ContentPlan | None = None
    results: list[ClaimValidation] = []
    for round_number in range(1, max_rounds + 1):
        rejected = [v for v in results if v.outcome is ClaimOutcome.rejected]
        if plan is not None and not rejected:
            break
        plan = build_plan(owner_id, target, facts, coverage, adapter,
                          feedback=rejected or None, previous=plan)
        # The same ID and version means the same text, evidence and reach, so the earlier
        # result still holds and the claim is not judged twice.
        earlier = {(v.claim_id, v.claim_version): v for v in results}
        results = [earlier.get((c.claim_id, c.version)) or validate_claim(c, ctx, adapter)
                   for c in plan.claims]
        log.info("plan round=%d claims=%d rejected=%d", round_number, len(plan.claims),
                 sum(v.outcome is ClaimOutcome.rejected for v in results))
    assert plan is not None  # max_rounds >= 1

    dropped = [v.claim_id for v in results if v.outcome is ClaimOutcome.rejected]
    config = load_model_config()
    report = ValidationReport(
        plan_id=plan.plan_id, results=results, dropped_claim_ids=dropped,
        models_by_role={role.value: rc.model for role, rc in config.roles.items()},
        limitations=limitations(config))
    return plan, report
