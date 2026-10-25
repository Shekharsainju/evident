from __future__ import annotations

from evident.contracts.facts import FactRef
from evident.validation.layer1.checks_ids import check_fact_ids
from evident.validation.layer1.run import run_layer1
from tests.builders import OWNER, fact
from tests.validation.support import claim, confirmed, context, project


def test_confirmed_owned_fact_passes() -> None:
    f = project()
    assert check_fact_ids(claim("Built a timetable clash checker", f), context(f)) == []


def test_claim_without_evidence_fails() -> None:
    (failure,) = check_fact_ids(claim("Built a thing", refs=[]), context())
    assert failure.rule == "fact_ids"
    assert "no evidence" in failure.detail


def test_unknown_ref_fails() -> None:
    f = project()
    c = claim("Built a thing", refs=[FactRef(fact_id="exp_99", version=1)])
    (failure,) = check_fact_ids(c, context(f))
    assert failure.phrase == "exp_99@1"
    assert "does not exist" in failure.detail


def test_superseded_fact_fails() -> None:
    old = fact("exp_03", 1, status="superseded")
    new = confirmed("exp_03", 2, supersedes=1)
    c = claim("Built a thing", refs=[FactRef(fact_id="exp_03", version=1)])
    (failure,) = check_fact_ids(c, context(old, new))
    assert failure.phrase == "exp_03@1"
    assert "superseded" in failure.detail


def test_extracted_fact_fails() -> None:
    f = fact("doc_01_f01", status="extracted")
    (failure,) = check_fact_ids(claim("Built a thing", f), context(f))
    assert "extracted" in failure.detail


def test_other_owner_fact_fails() -> None:
    f = confirmed(owner_id="someone-else")
    (failure,) = check_fact_ids(claim("Built a thing", f), context(f, owner_id=OWNER))
    assert "another user" in failure.detail


def test_run_layer1_stops_after_fact_id_failure() -> None:
    f = fact("doc_01_f01", status="extracted")
    result = run_layer1(claim("Led 3 production deployments with Kubernetes", f), context(f))
    assert not result.passed
    assert [x.rule for x in result.failures] == ["fact_ids"]


def test_run_layer1_passes_plain_rephrasing() -> None:
    f = project()
    result = run_layer1(claim("Developed a clash checker for timetables with Python", f),
                        context(f))
    assert result.passed, result.failures
