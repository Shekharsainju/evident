from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from evident.contracts.enums import ClaimOutcome
from evident.eval.datasets import load_ground_truth
from evident.eval.grounding import (
    Category,
    LabelledClaim,
    build_claim_set,
    dump_claims,
    load_claims,
    run_grounding,
)
from evident.settings import Role
from tests.fakes import FakeAdapter


def by_split(claims: list[LabelledClaim], split: str) -> list[LabelledClaim]:
    return [c for c in claims if c.split == split]


def test_claim_set_sizes_and_split_by_profile() -> None:
    claims = build_claim_set()
    dev, test = by_split(claims, "dev"), by_split(claims, "test")
    assert Counter(c.label for c in dev) == {"supported": 20, "unsupported": 20}
    assert Counter(c.label for c in test) == {"supported": 40, "unsupported": 45}
    assert Counter(c.category for c in test if c.label == "unsupported") == {
        cat: 5 for cat in Category}
    assert {c.category for c in dev if c.label == "unsupported"} == set(Category)
    assert {c.profile_id for c in dev} == {"student_profile_01", "student_profile_02"}
    assert {c.profile_id for c in test} == {
        "student_profile_03", "student_profile_04", "student_profile_05"}
    assert all((c.label == "supported") == (c.category is None) for c in claims)
    assert len({c.claim.claim_id for c in claims}) == len(claims)
    assert len({(c.profile_id, c.claim.text) for c in claims if c.label == "supported"}) == 60


def test_claim_set_is_deterministic() -> None:
    assert build_claim_set(0) == build_claim_set(0)


def test_mutations_change_claim() -> None:
    for c in build_claim_set():
        if c.label == "supported":
            continue
        assert c.mutated_from is not None
        assert (c.claim.text, c.claim.evidence) != (c.base_text, c.base_evidence)


def test_claims_cite_only_their_own_profile() -> None:
    for c in build_claim_set():
        ids = {f.fact_id for f in load_ground_truth(c.profile_id)}
        for ref in c.claim.evidence:
            if c.category is Category.fake_id:
                continue
            assert ref.fact_id in ids and ref.version == 1


def test_fake_id_cites_something_that_does_not_exist() -> None:
    for c in build_claim_set():
        if c.category is not Category.fake_id:
            continue
        known = {(f.fact_id, f.version) for f in load_ground_truth(c.profile_id)}
        assert any((r.fact_id, r.version) not in known for r in c.claim.evidence)


def test_claims_round_trip_through_jsonl(tmp_path: Path) -> None:
    claims = build_claim_set()
    path = tmp_path / "claims.jsonl"
    path.write_text(dump_claims(claims), encoding="utf-8")
    assert load_claims(path) == claims
    assert all(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())


def judge(verdict: str, confidence: float) -> str:
    return json.dumps({"verdict": verdict, "offending_phrase": None,
                       "corrected_phrasing": None, "confidence": confidence})


def two_claims() -> list[LabelledClaim]:
    claims = by_split(build_claim_set(), "dev")
    good = next(c for c in claims if c.label == "supported" and c.claim.text.startswith("Skills"))
    bad = next(c for c in claims if c.category is Category.paraphrase_overstatement)
    return [good, bad]


def test_review_counts_as_not_accepted() -> None:
    claims = two_claims()
    # Both judged with low confidence: both go to user review.
    adapter = FakeAdapter({Role.judge: [judge("supported", 0.3), judge("supported", 0.3)]})
    results = run_grounding(claims, adapter, threshold=0.8, judge_prompt_version="v1")
    assert [o.outcome for o in results.outcomes] == [ClaimOutcome.user_review] * 2
    assert (results.false_accepts.k, results.false_accepts.n) == (0, 1)
    assert (results.false_rejects.k, results.false_rejects.n) == (0, 1)
    assert (results.review_unsupported.k, results.review_supported.k) == (1, 1)


def test_confident_support_of_an_unsupported_claim_is_a_false_accept() -> None:
    claims = two_claims()
    adapter = FakeAdapter({Role.judge: [judge("supported", 0.95), judge("supported", 0.95)]})
    results = run_grounding(claims, adapter, threshold=0.8, judge_prompt_version="v1")
    assert results.outcomes[1].outcome is ClaimOutcome.passed
    assert (results.false_accepts.k, results.false_accepts.n) == (1, 1)
    per = results.per_category[Category.paraphrase_overstatement]
    assert (per.false_accepts.k, per.false_accepts.n) == (1, 1)
    assert results.caught_by["none"] == 1


def test_judge_error_is_never_an_accept() -> None:
    from evident.errors import ErrorCategory, StageError

    error = StageError(code="ollama_down", category=ErrorCategory.provider)
    adapter = FakeAdapter({Role.judge: [error, error]})
    results = run_grounding(two_claims(), adapter, threshold=0.8, judge_prompt_version="v1")
    assert results.false_accepts.k == 0
    assert all(o.outcome is not ClaimOutcome.passed for o in results.outcomes)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_run_grounding_uses_the_requested_prompt(version: str) -> None:
    adapter = FakeAdapter({Role.judge: [judge("supported", 0.9), judge("overstated", 0.9)]})
    run_grounding(two_claims(), adapter, threshold=0.8, judge_prompt_version=version)
    assert {c.prompt.version for c in adapter.calls} == {version}


def test_role_claims_use_the_right_article() -> None:
    texts = [c.claim.text for c in build_claim_set()]
    assert not any(" a IT " in t for t in texts)
    assert any("Worked as an IT Support Assistant" in t for t in texts)
