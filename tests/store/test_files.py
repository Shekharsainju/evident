from __future__ import annotations

from pathlib import Path

import pytest

from evident.contracts.coverage import CoverageRow, Target
from evident.contracts.enums import (
    ClaimOutcome,
    CoverageGrade,
    FactStatus,
    OutputType,
    RequirementCategory,
    RunStage,
    RunState,
)
from evident.contracts.facts import FactRef
from evident.contracts.outputs import Output, PostRenderResult
from evident.contracts.plan import Claim, ContentPlan
from evident.contracts.runs import RunStatus
from evident.contracts.validation import ClaimValidation, Layer1Result, ValidationReport
from evident.errors import StageError
from evident.store.files import FileRepository
from tests.builders import NOW, OWNER, document, fact

OTHER = "someone-else"


@pytest.fixture
def repo(tmp_path: Path) -> FileRepository:
    return FileRepository(tmp_path / "var")


def target() -> Target:
    return Target(target_id="t_01", owner_id=OWNER, title="Graduate AI engineer",
                  source_job_id="graduate_ai_engineer", document_id=None)


def plan() -> ContentPlan:
    claim = Claim(claim_id="c_001", text="Built a Flask timetable checker",
                  evidence=[FactRef(fact_id="doc_01_f01", version=1)], section="Projects",
                  emphasis=3, allowed_transformations=[], output_types=[OutputType.visual_profile],
                  parent_claim_id=None)
    return ContentPlan(plan_id="p_01", owner_id=OWNER, target_id="t_01", claims=[claim],
                       created_at=NOW)


def report() -> ValidationReport:
    result = ClaimValidation(claim_id="c_001", claim_version=1, outcome=ClaimOutcome.passed,
                             layer1=Layer1Result(passed=True, failures=[]), judge=None,
                             judge_model=None, judge_error=None, reasons=[])
    return ValidationReport(plan_id="p_01", results=[result], dropped_claim_ids=[],
                            models_by_role={}, limitations=[])


def output() -> Output:
    return Output(output_id="o_01", owner_id=OWNER, plan_id="p_01",
                  output_type=OutputType.visual_profile, claim_ids=["c_001"],
                  fact_refs=[FactRef(fact_id="doc_01_f01", version=1)],
                  files={"html": "profile.html"},
                  post_render=PostRenderResult(passed=True, problems=[]))


def run() -> RunStatus:
    return RunStatus(run_id="r_01", owner_id=OWNER, stage=RunStage.ingest, state=RunState.running,
                     message="", error=None, document_id="doc_01", target_id=None,
                     plan_id=None, output_ids=[])


def row() -> CoverageRow:
    return CoverageRow(requirement_id="req_01", text="Python",
                       category=RequirementCategory.required,
                       grade=CoverageGrade.strong,
                       evidence=[FactRef(fact_id="doc_01_f01", version=1)],
                       rationale="Python project shown.")


def test_document_round_trip(repo: FileRepository) -> None:
    repo.put_document(document(), b"%PDF-1.7 synthetic")
    assert repo.get_document(OWNER, "doc_01") == document()
    assert repo.get_document_bytes(OWNER, "doc_01") == b"%PDF-1.7 synthetic"


def test_fact_round_trip(repo: FileRepository) -> None:
    repo.put_fact(fact())
    assert repo.get_fact(OWNER, FactRef(fact_id="doc_01_f01", version=1)) == fact()


def test_other_records_round_trip(repo: FileRepository) -> None:
    repo.put_target(target())
    repo.put_coverage(OWNER, "t_01", [row()])
    repo.put_plan(plan())
    repo.put_report(OWNER, report())
    repo.put_output(output())
    repo.put_run(run())
    assert repo.get_target(OWNER, "t_01") == target()
    assert repo.get_coverage(OWNER, "t_01") == [row()]
    assert repo.get_plan(OWNER, "p_01") == plan()
    assert repo.get_report(OWNER, "p_01") == report()
    assert repo.get_output(OWNER, "o_01") == output()
    assert repo.get_run(OWNER, "r_01") == run()


def test_other_owner_gets_none(repo: FileRepository) -> None:
    repo.put_document(document(), b"x")
    repo.put_fact(fact())
    repo.put_target(target())
    repo.put_coverage(OWNER, "t_01", [row()])
    repo.put_plan(plan())
    repo.put_report(OWNER, report())
    repo.put_output(output())
    repo.put_run(run())
    assert repo.get_document(OTHER, "doc_01") is None
    with pytest.raises(StageError):
        repo.get_document_bytes(OTHER, "doc_01")
    assert repo.get_fact(OTHER, FactRef(fact_id="doc_01_f01", version=1)) is None
    assert repo.current_facts(OTHER) == []
    assert repo.get_target(OTHER, "t_01") is None
    assert repo.get_coverage(OTHER, "t_01") is None
    assert repo.get_plan(OTHER, "p_01") is None
    assert repo.get_report(OTHER, "p_01") is None
    assert repo.get_output(OTHER, "o_01") is None
    assert repo.get_run(OTHER, "r_01") is None


def test_unsafe_ids_rejected(repo: FileRepository) -> None:
    with pytest.raises(StageError):
        repo.get_run(OWNER, "../../etc/passwd")
    with pytest.raises(StageError):
        repo.get_plan("..", "p_01")


def test_put_fact_never_overwrites_existing_version(repo: FileRepository) -> None:
    repo.put_fact(fact())
    with pytest.raises(StageError) as e:
        repo.put_fact(fact(text="Something else"))
    assert e.value.code == "version_exists"
    assert repo.get_fact(OWNER, FactRef(fact_id="doc_01_f01", version=1)) == fact()


def test_put_document_never_overwrites(repo: FileRepository) -> None:
    repo.put_document(document(), b"one")
    with pytest.raises(StageError):
        repo.put_document(document(), b"two")
    assert repo.get_document_bytes(OWNER, "doc_01") == b"one"


@pytest.mark.parametrize(
    "start,new,allowed",
    [
        ("extracted", "confirmed", True),
        ("extracted", "rejected", True),
        ("extracted", "superseded", True),
        ("confirmed", "superseded", True),
        ("confirmed", "rejected", False),
        ("rejected", "confirmed", False),
        ("superseded", "confirmed", False),
        ("confirmed", "extracted", False),
    ],
)
def test_status_transitions_enforced(
    repo: FileRepository, start: str, new: str, allowed: bool
) -> None:
    repo.put_fact(fact(status=start))
    ref = FactRef(fact_id="doc_01_f01", version=1)
    if allowed:
        updated = repo.set_fact_status(OWNER, ref, FactStatus(new), NOW)
        assert updated.status == FactStatus(new)
        assert repo.get_fact(OWNER, ref) == updated
    else:
        with pytest.raises(StageError):
            repo.set_fact_status(OWNER, ref, FactStatus(new), NOW)
        assert repo.get_fact(OWNER, ref) == fact(status=start)


def test_confirm_sets_confirmed_at_only_on_confirm(repo: FileRepository) -> None:
    repo.put_fact(fact())
    ref = FactRef(fact_id="doc_01_f01", version=1)
    assert repo.set_fact_status(OWNER, ref, FactStatus.confirmed, NOW).confirmed_at == NOW


def test_current_facts_skips_superseded(repo: FileRepository) -> None:
    repo.put_fact(fact())
    repo.set_fact_status(OWNER, FactRef(fact_id="doc_01_f01", version=1),
                         FactStatus.superseded, NOW)
    repo.put_fact(fact(version=2, supersedes=1, edited_by_user=True, text="Edited"))
    repo.put_fact(fact("doc_01_f02", text="Second fact"))
    repo.put_fact(fact("doc_02_f01", source=fact().source.model_copy(
        update={"document_id": "doc_02"})))
    current = repo.current_facts(OWNER, "doc_01")
    assert {(f.fact_id, f.version) for f in current} == {("doc_01_f01", 2), ("doc_01_f02", 1)}
    assert len(repo.current_facts(OWNER)) == 3


def test_output_keeps_fact_versions_after_new_fact_version(repo: FileRepository) -> None:
    repo.put_fact(fact(status="confirmed"))
    repo.put_output(output())
    repo.set_fact_status(OWNER, FactRef(fact_id="doc_01_f01", version=1),
                         FactStatus.superseded, NOW)
    repo.put_fact(fact(version=2, supersedes=1, edited_by_user=True))
    stored = repo.get_output(OWNER, "o_01")
    assert stored is not None
    assert stored.fact_refs == [FactRef(fact_id="doc_01_f01", version=1)]
    assert repo.get_fact(OWNER, stored.fact_refs[0]) is not None
