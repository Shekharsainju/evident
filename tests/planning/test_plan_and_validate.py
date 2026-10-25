from __future__ import annotations

import json

from evident.contracts.coverage import CoverageRow, Target
from evident.contracts.enums import ClaimOutcome, CoverageGrade, RequirementCategory
from evident.contracts.facts import FactRef
from evident.models.adapter import TextPart
from evident.planning.planner import plan_and_validate
from evident.settings import Role, load_model_config
from evident.validation.judge import limitations
from tests.fakes import FakeAdapter
from tests.validation.support import OWNER, context, judge_reply, project

FACT = project()
REF = FactRef(fact_id=FACT.fact_id, version=FACT.version)
TARGET = Target(target_id="t_01", owner_id=OWNER, title="Graduate AI Engineer",
                source_job_id="graduate_ai_engineer", document_id=None)
COVERAGE = [CoverageRow(requirement_id="req_01", text="Python",
                        category=RequirementCategory.required, grade=CoverageGrade.strong,
                        evidence=[REF], rationale="r")]
GOOD = "Built a timetable clash checker in Python"
INFLATED = "Led a production deployment of the timetable clash checker"
FIXED = "Built a prototype timetable clash checker"


def plan_reply(*texts: str) -> str:
    return json.dumps({"claims": [
        {"text": t, "evidence": [f"{FACT.fact_id}@1"], "section": "Projects", "emphasis": 3,
         "output_types": ["visual_profile", "interview_deck"], "narrative_for": None}
        for t in texts]})


def planner_prompts(adapter: FakeAdapter) -> list[str]:
    return ["\n".join(p.text for p in c.parts if isinstance(p, TextPart))
            for c in adapter.calls if c.role is Role.planner]


def test_rejected_claim_resubmitted_with_reason() -> None:
    adapter = FakeAdapter({
        Role.planner: [plan_reply(GOOD, INFLATED), plan_reply(GOOD, FIXED)],
        Role.judge: [judge_reply(), judge_reply("overstated", 0.9, "production"), judge_reply()],
    })
    plan, report = plan_and_validate(OWNER, TARGET, [FACT], COVERAGE, context(FACT), adapter)
    first, second = planner_prompts(adapter)
    assert "Rejected claims and reasons" not in first
    assert "Rejected claims and reasons" in second and INFLATED in second
    assert "ownership" in second and '"production"' in second
    assert [c.text for c in plan.claims] == [GOOD, FIXED]
    # GOOD kept its ID and version, so its first-round result was reused, not judged again.
    assert plan.claims[0].claim_id == "c_001" and plan.claims[1].claim_id == "c_003"
    assert [c.role for c in adapter.calls].count(Role.judge) == 3
    assert report.plan_id == plan.plan_id and report.dropped_claim_ids == []
    assert {(v.claim_id, v.outcome) for v in report.results} == {
        ("c_001", ClaimOutcome.passed), ("c_003", ClaimOutcome.passed)}


def test_drop_after_two_rounds() -> None:
    adapter = FakeAdapter({
        Role.planner: [plan_reply(GOOD, INFLATED), plan_reply(GOOD, INFLATED)],
        Role.judge: [judge_reply(), judge_reply("overstated", 0.9, "production")],
    })
    plan, report = plan_and_validate(OWNER, TARGET, [FACT], COVERAGE, context(FACT), adapter)
    assert [c.role for c in adapter.calls].count(Role.planner) == 2
    # Kept in the stored plan so the claims page can show its wording; renderers skip it.
    assert [c.text for c in plan.claims] == [GOOD, INFLATED]
    assert report.dropped_claim_ids == ["c_002"]
    dropped = [v for v in report.results if v.claim_id == "c_002"]
    assert [v.outcome for v in dropped] == [ClaimOutcome.rejected]


def test_no_second_round_without_rejections_and_review_is_not_rejection() -> None:
    adapter = FakeAdapter({
        Role.planner: [plan_reply(GOOD, FIXED)],
        Role.judge: [judge_reply(), judge_reply(confidence=0.5)],
    })
    plan, report = plan_and_validate(OWNER, TARGET, [FACT], COVERAGE, context(FACT), adapter)
    assert len(planner_prompts(adapter)) == 1
    assert [v.outcome for v in report.results] == [ClaimOutcome.passed, ClaimOutcome.user_review]
    assert len(plan.claims) == 2 and report.dropped_claim_ids == []


def test_report_names_models_and_limitations() -> None:
    adapter = FakeAdapter({Role.planner: [plan_reply(GOOD)], Role.judge: [judge_reply()]})
    _, report = plan_and_validate(OWNER, TARGET, [FACT], COVERAGE, context(FACT), adapter)
    config = load_model_config()
    assert report.models_by_role == {r.value: rc.model for r, rc in config.roles.items()}
    assert report.limitations == limitations(config)
