from __future__ import annotations

import json
from pathlib import Path

import pytest

from evident.contracts.enums import ClaimOutcome, Verdict
from evident.contracts.facts import FactRef
from evident.contracts.validation import JudgeVerdict
from evident.errors import ErrorCategory, StageError
from evident.models.adapter import TextPart
from evident.settings import Role, load_model_config
from evident.validation import JUDGE_THRESHOLD, decide, limitations, run_judge, validate_claim
from tests.builders import fact
from tests.fakes import FakeAdapter
from tests.validation.support import claim, confirmed, context, judge_reply, project


def verdict(kind: str = "supported", confidence: float = 0.95) -> JudgeVerdict:
    return JudgeVerdict(verdict=Verdict(kind), offending_phrase=None, corrected_phrasing=None,
                        confidence=confidence)


# Outcome table, one test per row


def test_pass_and_confident_supported_passes() -> None:
    assert decide(True, verdict("supported", 0.9), JUDGE_THRESHOLD) is ClaimOutcome.passed


@pytest.mark.parametrize("kind", ["overstated", "unsupported"])
def test_pass_and_confident_negative_rejects(kind: str) -> None:
    assert decide(True, verdict(kind, 0.9), JUDGE_THRESHOLD) is ClaimOutcome.rejected


@pytest.mark.parametrize("judge", [verdict("supported", 0.5), verdict("unsupported", 0.5), None])
def test_pass_and_unsure_or_error_goes_to_review(judge: JudgeVerdict | None) -> None:
    assert decide(True, judge, JUDGE_THRESHOLD) is ClaimOutcome.user_review


@pytest.mark.parametrize("judge", [verdict("overstated", 0.9), verdict("unsupported", 0.9),
                                   verdict("supported", 0.5), None])
def test_fail_and_anything_but_confident_support_rejects(judge: JudgeVerdict | None) -> None:
    assert decide(False, judge, JUDGE_THRESHOLD) is ClaimOutcome.rejected


def test_fail_and_confident_supported_is_disagreement() -> None:
    assert decide(False, verdict("supported", 0.9), JUDGE_THRESHOLD) is ClaimOutcome.user_review


def test_threshold_is_inclusive() -> None:
    assert decide(True, verdict("supported", 0.8), 0.8) is ClaimOutcome.passed
    assert decide(True, verdict("supported", 0.79), 0.8) is ClaimOutcome.user_review


# validate_claim end to end with a fake judge


def test_supported_claim_passes_end_to_end() -> None:
    f = project()
    adapter = FakeAdapter({Role.judge: [judge_reply()]})
    v = validate_claim(claim("Built a timetable clash checker in Python", f), context(f), adapter)
    assert v.outcome is ClaimOutcome.passed
    assert v.layer1.passed and v.judge_model == "fake-judge" and v.judge_error is None
    assert v.reasons == ["judge: supported (confidence 0.95)"]


def test_superseded_fact_rejected() -> None:
    old = fact("exp_03", 1, status="superseded")
    new = confirmed("exp_03", 2, supersedes=1)
    c = claim("Built a clash checker", refs=[FactRef(fact_id="exp_03", version=1)])
    adapter = FakeAdapter({Role.judge: [judge_reply("unsupported", 0.9)]})
    v = validate_claim(c, context(old, new), adapter)
    assert v.outcome is ClaimOutcome.rejected
    assert v.reasons[0].startswith("fact_ids: Cites exp_03@1, which is superseded")
    # The superseded fact is not shown to the judge.
    text = "\n".join(p.text for p in adapter.calls[0].parts if isinstance(p, TextPart))
    assert "exp_03@1" not in text


def test_other_owner_fact_rejected() -> None:
    f = confirmed(owner_id="someone-else")
    adapter = FakeAdapter({Role.judge: [judge_reply("unsupported", 0.9)]})
    v = validate_claim(claim("Built a clash checker", f), context(f), adapter)
    assert v.outcome is ClaimOutcome.rejected
    assert "another user" in v.reasons[0]


def test_claim_without_evidence_rejected() -> None:
    adapter = FakeAdapter({Role.judge: [judge_reply("unsupported", 0.9)]})
    v = validate_claim(claim("Built a clash checker", refs=[]), context(), adapter)
    assert v.outcome is ClaimOutcome.rejected
    assert "(no cited facts)" in adapter.calls[0].parts[0].text  # type: ignore[union-attr]


def test_judge_error_never_passes() -> None:
    f = project()
    quota = StageError(code="daily_quota", category=ErrorCategory.provider,
                       detail="Needs 1 call, 0 left today.")
    adapter = FakeAdapter({Role.judge: [quota]})
    v = validate_claim(claim("Built a timetable clash checker", f), context(f), adapter)
    assert v.outcome is ClaimOutcome.user_review
    assert v.judge is None and v.judge_model is None
    assert v.judge_error == "daily_quota: Needs 1 call, 0 left today."
    assert v.reasons == ["judge error: daily_quota: Needs 1 call, 0 left today."]


def test_judge_unavailable_routes_to_user_review() -> None:  # Ollama down
    f = project()
    down = StageError(code="judge_unavailable", category=ErrorCategory.provider,
                      detail="Ollama is not reachable or returned a bad response.")
    adapter = FakeAdapter({Role.judge: [down]})
    v = validate_claim(claim("Built a timetable clash checker", f), context(f), adapter)
    assert v.outcome is ClaimOutcome.user_review
    assert v.judge_error is not None and v.judge_error.startswith("judge_unavailable")


def test_layer1_failure_with_confident_support_is_user_review() -> None:
    f = project(ownership="built")
    adapter = FakeAdapter({Role.judge: [judge_reply("supported", 0.9)]})
    v = validate_claim(claim("Led the timetable clash checker", f), context(f), adapter)
    assert v.outcome is ClaimOutcome.user_review
    assert v.reasons[0].startswith("ownership:")


def test_judge_prompt_contains_only_cited_facts() -> None:
    cited = project("p_cited", text="Built a timetable clash checker")
    other = project("p_other", text="Built a secret unrelated dashboard")
    adapter = FakeAdapter({Role.judge: [judge_reply()]})
    c = claim("Built a clash checker", cited)
    assert other.fact_id not in {r.fact_id for r in c.evidence}
    _, _, error = run_judge(c, [cited], adapter)
    assert error is None
    text = "\n".join(p.text for p in adapter.calls[0].parts if isinstance(p, TextPart))
    assert "p_cited@1" in text and "timetable clash checker" in text
    assert "p_other" not in text and "secret" not in text
    assert "<evidence>" in text and "Claim: Built a clash checker" in text
    assert adapter.calls[0].role is Role.judge


def test_judge_evidence_lists_dates_ownership_and_metrics() -> None:
    from tests.builders import metric

    f = project(start="2025-01", end=None, metrics=[metric()])
    adapter = FakeAdapter({Role.judge: [judge_reply()]})
    run_judge(claim("Built a checker", f), [f], adapter)
    text = adapter.calls[0].parts[0].text  # type: ignore[union-attr]
    assert "dates: 2025-01 to present" in text
    assert "ownership: built; deployment: prototype" in text
    assert "metric m_01: latency decrease 2 seconds" in text


def test_report_limitations_match_judge_provider(tmp_path: Path) -> None:
    local = limitations(load_model_config())
    assert local[0].startswith("Small local judge: qwen3:4b-instruct-2507-q4_K_M")
    assert "uncalibrated" in local[0] and local[1].startswith("Free-tier gemini-3.5-flash-lite")

    fallback = Path("config/models.toml").read_text(encoding="utf-8").replace(
        '[roles.judge]\nprovider = "ollama"\nmodel = "qwen3:4b-instruct-2507-q4_K_M"',
        '[roles.judge]\nprovider = "gemini"\nmodel = "gemini-3.5-flash-lite"',
    )
    assert fallback != Path("config/models.toml").read_text(encoding="utf-8")
    path = tmp_path / "models.toml"
    path.write_text(fallback, encoding="utf-8")
    same_family = limitations(load_model_config(path))
    assert same_family[0] == "Same-family judge: gemini-3.5-flash-lite is also the planner " \
                             "(P1 fallback)"
    assert same_family[1] == local[1]


def test_validation_round_trips_as_json() -> None:
    f = project()
    adapter = FakeAdapter({Role.judge: [judge_reply("overstated", 0.9, "production")]})
    v = validate_claim(claim("Shipped a production clash checker", f), context(f), adapter)
    assert v.outcome is ClaimOutcome.rejected
    data = json.loads(v.model_dump_json())
    assert data["judge"]["offending_phrase"] == "production"
    assert any(r.startswith("deployment:") for r in data["reasons"])
