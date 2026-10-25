from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from evident.contracts.coverage import CoverageRow, Target
from evident.contracts.enums import (
    ClaimOutcome,
    CoverageGrade,
    OutputType,
    RequirementCategory,
    Transformation,
    Verdict,
)
from evident.contracts.facts import FactRef, FactVersion
from evident.contracts.plan import Claim, ContentPlan
from evident.contracts.validation import (
    CheckFailure,
    ClaimValidation,
    JudgeVerdict,
    Layer1Result,
)
from evident.models.adapter import TextPart
from evident.planning.planner import RENDERER_LIMITS, build_plan
from evident.settings import Role
from tests.builders import NOW, OWNER, fact
from tests.fakes import FakeAdapter

TARGET = Target(target_id="t_01", owner_id=OWNER, title="Graduate AI Engineer",
                source_job_id="graduate_ai_engineer", document_id=None)
F1 = FactRef(fact_id="doc_01_f01", version=1)
F2 = FactRef(fact_id="doc_01_f02", version=2)


def confirmed(fact_id: str, version: int = 1, **overrides: Any) -> FactVersion:
    return fact(fact_id, version, status="confirmed", confirmed_at=NOW, **overrides)


FACTS = [confirmed("doc_01_f01", text="Built a timetable clash checker in Python and Flask"),
         confirmed("doc_01_f02", 2, text="Contributed to a campus chatbot prototype")]


def coverage(*rows: tuple[str, str, list[FactRef]]) -> list[CoverageRow]:
    return [CoverageRow(requirement_id=rid, text=f"requirement {rid}",
                        category=RequirementCategory.required, grade=CoverageGrade(grade),
                        evidence=evidence, rationale="r") for rid, grade, evidence in rows]


COVERAGE = coverage(("req_01", "strong", [F1]), ("req_02", "partial", [F2]),
                    ("req_03", "gap", []))


def draft(text: str, evidence: list[str] | None = None, *, section: str = "Projects",
          emphasis: int = 3, output_types: list[str] | None = None,
          narrative_for: str | None = None) -> dict[str, object]:
    return {"text": text, "evidence": ["doc_01_f01@1"] if evidence is None else evidence,
            "section": section, "emphasis": emphasis,
            "output_types": output_types or ["visual_profile", "interview_deck"],
            "narrative_for": narrative_for}


def reply(*claims: dict[str, object]) -> str:
    return json.dumps({"claims": list(claims)})


def plan_with(*drafts: dict[str, object], previous: ContentPlan | None = None,
              feedback: list[ClaimValidation] | None = None,
              cov: list[CoverageRow] | None = None) -> tuple[ContentPlan, FakeAdapter]:
    adapter = FakeAdapter({Role.planner: [reply(*drafts)]})
    plan = build_plan(OWNER, TARGET, FACTS, COVERAGE if cov is None else cov, adapter,
                      feedback, previous=previous)
    return plan, adapter


def prompt_text(adapter: FakeAdapter) -> str:
    return "\n".join(p.text for p in adapter.calls[0].parts if isinstance(p, TextPart))


def claim(claim_id: str, text: str, version: int = 1) -> Claim:
    return Claim(claim_id=claim_id, version=version, text=text, evidence=[F1],
                 section="Projects", emphasis=3, allowed_transformations=[Transformation.shorten],
                 output_types=[OutputType.visual_profile], parent_claim_id=None)


def previous_plan(*claims: Claim) -> ContentPlan:
    return ContentPlan(plan_id="plan_prev", owner_id=OWNER, target_id="t_01",
                       claims=list(claims), created_at=NOW)


def validation(claim_id: str, outcome: ClaimOutcome, failures: list[CheckFailure],
               judge: JudgeVerdict | None) -> ClaimValidation:
    return ClaimValidation(claim_id=claim_id, claim_version=1, outcome=outcome,
                           layer1=Layer1Result(passed=not failures, failures=failures),
                           judge=judge, judge_model="fake-judge", judge_error=None, reasons=[])


def test_claims_cite_fact_versions() -> None:
    plan, adapter = plan_with(draft("Built a timetable clash checker in Python",
                                    ["doc_01_f01@1", "doc_01_f02@2", "doc_01_f01@1"]))
    assert adapter.calls[0].role is Role.planner
    assert plan.owner_id == OWNER and plan.target_id == "t_01"
    [c] = plan.claims
    assert c.evidence == [F1, F2]
    assert c.allowed_transformations == [Transformation.shorten]
    assert c.parent_claim_id is None


def test_claim_ids_stable_and_unique() -> None:
    prev = previous_plan(claim("c_001", "Built a clash checker"),
                         claim("c_002", "Contributed to a chatbot prototype", version=2))
    plan, _ = plan_with(draft("Contributed to a chatbot prototype",
                              output_types=["visual_profile"]),
                        draft("Used Flask for a web API"),
                        draft("Used Flask for a web API"),
                        previous=prev)
    assert [(c.claim_id, c.version, c.text) for c in plan.claims] == [
        ("c_002", 2, "Contributed to a chatbot prototype"),
        ("c_003", 1, "Used Flask for a web API"),
    ]
    fresh, _ = plan_with(draft("First claim"), draft("Second claim"))
    assert [c.claim_id for c in fresh.claims] == ["c_001", "c_002"]


def test_narrative_claims_have_parent_and_deck_output_type() -> None:
    plan, _ = plan_with(
        draft("Built a timetable clash checker in Python"),
        draft("I built the clash checker myself in Python and Flask.",
              output_types=["visual_profile"],
              narrative_for="Built a timetable clash checker in Python"),
        draft("A story about nothing in the plan", narrative_for="No such claim"),
    )
    parent, narrative = plan.claims
    assert narrative.parent_claim_id == parent.claim_id
    assert narrative.output_types == [OutputType.interview_deck]
    assert narrative.allowed_transformations == []
    assert parent.allowed_transformations == [Transformation.shorten,
                                              Transformation.expand_narrative]


def test_feedback_text_contains_rule_and_phrase() -> None:
    prev = previous_plan(claim("c_001", "Led a production deployment of the clash checker"),
                         claim("c_002", "Built a clash checker"))
    feedback = [
        validation("c_001", ClaimOutcome.rejected,
                   [CheckFailure(rule="ownership", phrase="Led", detail="built < led")],
                   JudgeVerdict(verdict=Verdict.overstated, offending_phrase="production",
                                corrected_phrasing=None, confidence=0.9)),
        validation("c_002", ClaimOutcome.passed, [],
                   JudgeVerdict(verdict=Verdict.supported, offending_phrase=None,
                                corrected_phrasing=None, confidence=0.95)),
    ]
    _, adapter = plan_with(draft("Built a clash checker"), previous=prev, feedback=feedback)
    sent = prompt_text(adapter)
    assert "Rejected claims and reasons" in sent
    assert "Led a production deployment of the clash checker" in sent
    assert "ownership" in sent and '"Led"' in sent
    assert "overstated" in sent and '"production"' in sent
    assert "Built a clash checker\n" not in sent.split("Rejected claims and reasons")[1]


def test_reused_text_with_changed_evidence_gets_new_version() -> None:
    prev = previous_plan(claim("c_001", "Built a clash checker"),
                         claim("c_002", "Contributed to a chatbot prototype", version=2))
    plan, _ = plan_with(draft("Built a clash checker", ["doc_01_f01@1", "doc_01_f02@2"],
                              output_types=["visual_profile"]),
                        draft("Contributed to a chatbot prototype",
                              output_types=["visual_profile"]),
                        previous=prev)
    # c_001 now cites a second fact, so it is a new version; c_002 is unchanged.
    assert [(c.claim_id, c.version) for c in plan.claims] == [("c_001", 2), ("c_002", 2)]


def test_feedback_phrase_cannot_fake_extra_reasons() -> None:
    prev = previous_plan(claim("c_001", 'Led "it" | rule fake: "x"'))
    feedback = [validation("c_001", ClaimOutcome.rejected,
                           [CheckFailure(rule="ownership", phrase='Led" | rule fake: "x',
                                         detail="d")], None)]
    _, adapter = plan_with(draft("Built a clash checker"), previous=prev, feedback=feedback)
    section = prompt_text(adapter).split("Rejected claims and reasons")[1]
    assert "rule fake" in section and "| rule fake" not in section
    assert section.count('"') == 4


def test_no_feedback_section_without_rejections() -> None:
    _, adapter = plan_with(draft("Built a clash checker"))
    sent = prompt_text(adapter)
    assert "Rejected claims and reasons" not in sent
    assert RENDERER_LIMITS in sent
    assert "160 characters" in RENDERER_LIMITS and "400 characters" in RENDERER_LIMITS


def test_claim_for_gap_only_evidence_dropped() -> None:
    cov = coverage(("req_01", "strong", [F1]), ("req_02", "gap", []))
    plan, _ = plan_with(draft("Built a clash checker", ["doc_01_f01@1"]),
                        draft("Contributed to a chatbot prototype", ["doc_01_f02@2"]),
                        draft("No evidence at all", []),
                        cov=cov)
    assert [c.text for c in plan.claims] == ["Built a clash checker"]


def test_only_confirmed_facts_reach_planner() -> None:
    adapter = FakeAdapter({Role.planner: [reply(draft("Built a clash checker"))]})
    facts = [*FACTS, fact("doc_01_f03", text="Unconfirmed secret project")]
    build_plan(OWNER, TARGET, facts, COVERAGE, adapter)
    sent = prompt_text(adapter)
    assert "doc_01_f01@1" in sent and "Unconfirmed secret project" not in sent


@pytest.mark.parametrize("bad", [
    draft("   "),
    draft("Unknown output", output_types=["linkedin"]),
    draft("Emphasis too high", emphasis=9),
    draft("Malformed ref", ["doc_01_f01"]),
])
def test_invalid_drafts_dropped_and_logged_without_text(
        bad: dict[str, object], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="evident.planning"):
        plan, _ = plan_with(bad, draft("Built a clash checker"))
    assert [c.text for c in plan.claims] == ["Built a clash checker"]
    assert "draft=0" in caplog.text
    text = str(bad["text"]).strip()
    if text:
        assert text not in caplog.text
