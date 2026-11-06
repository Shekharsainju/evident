from __future__ import annotations

import pytest

from evident.contracts.facts import FactVersion
from evident.validation.layer1.checks_refs import check_aggregates, check_metrics, check_scale
from evident.validation.layer1.run import run_layer1
from tests.builders import attrs
from tests.validation.support import claim, confirmed, context, metric, project


def latency() -> object:
    return metric(metric_id="m_lat", metric="latency", direction="decrease", value=45.0,
                  unit="percent", span_text="cut latency by 45%")


def accuracy(value: float = 60.0) -> object:
    return metric(metric_id="m_acc", metric="accuracy", direction="increase", value=value,
                  unit="percent", span_text=f"raised accuracy to {value:g}%")


def rules(failures: list[object]) -> list[str]:
    return [f.rule for f in failures]  # type: ignore[attr-defined]


def test_latency_claim_cannot_bind_accuracy_record() -> None:
    f = project(metrics=[accuracy()])
    (failure,) = check_metrics(claim("Cut latency 60%", f), [f], context(f))
    assert failure.rule == "metrics"
    assert "unbound" in failure.detail


def test_round_toward_zero_only() -> None:
    f = project(metrics=[latency()])
    assert check_metrics(claim("Cut latency by 40%", f), [f], context(f)) == []
    assert check_metrics(claim("Cut latency by 45%", f), [f], context(f)) == []
    (failure,) = check_metrics(claim("Cut latency by 50%", f), [f], context(f))
    assert "beyond" in failure.detail and failure.phrase == "50%"


def test_two_matching_records_is_ambiguous() -> None:
    f = project(metrics=[accuracy(60.0), metric(metric_id="m_acc2", metric="accuracy",
                                                   direction="increase", value=70.0,
                                                   unit="percent", span_text="70%")])
    (failure,) = check_metrics(claim("Reached 60% accuracy", f), [f], context(f))
    assert "ambiguous" in failure.detail and "m_acc" in failure.detail


def test_number_only_in_evidence_text_cannot_bind() -> None:
    f = project(text="Built a dashboard that covered 1,200 survey responses", metrics=[])
    (failure,) = check_metrics(claim("Built a dashboard covering 1,200 survey responses", f),
                               [f], context(f))
    assert "unbound" in failure.detail


def test_count_record_binds_a_counted_noun() -> None:
    f = project(metrics=[metric(metric_id="m_cnt", metric="count", direction="absolute",
                                value=1200.0, unit="count",
                                span_text="covered 1,200 survey responses")])
    assert check_metrics(claim("Covered 1,200 survey responses", f), [f], context(f)) == []
    (failure,) = check_metrics(claim("Covered 1,500 survey responses", f), [f], context(f))
    assert "beyond" in failure.detail


def test_direction_word_narrows_binding() -> None:
    f = project(metrics=[latency(), accuracy(45.0)])
    # Both records are 45 percent; "cut" picks the decrease record, so there is no ambiguity.
    assert check_metrics(claim("Cut latency by 40%", f), [f], context(f)) == []


def test_other_metric_needs_review() -> None:
    f = project(metrics=[metric(metric_id="m_o", metric="other:nps", direction="increase",
                                value=12.0, unit="points", span_text="12 points")])
    (failure,) = check_metrics(claim("Lifted NPS by 12 points", f), [f], context(f))
    assert failure.rule == "metrics_other_needs_review"


def test_thousands_of_users_without_users_metric_rejected() -> None:
    f = project(metrics=[latency()])
    (failure,) = check_scale(claim("Serving thousands of users", f), [f], context(f))
    assert failure.rule == "scale" and failure.phrase == "thousands of users"


def test_users_figure_within_record_passes_and_beyond_fails() -> None:
    f = project(metrics=[metric(metric_id="m_u", metric="users", direction="absolute",
                                value=30.0, unit="users",
                                span_text="supported 30 first-year students")])
    assert check_scale(claim("Supported 30 users", f), [f], context(f)) == []
    assert check_scale(claim("Supported hundreds of users", f), [f], context(f))[0].rule == "scale"


def test_three_projects_citing_one_project_rejected() -> None:
    f = project()
    (failure,) = check_aggregates(claim("Delivered three projects", f), [f], context(f))
    assert failure.rule == "aggregates" and "1 project fact" in failure.detail


def test_three_projects_citing_three_projects_passes() -> None:
    fs = [project(f"p_{i}") for i in range(3)]
    assert check_aggregates(claim("Delivered three projects", *fs), fs, context(*fs)) == []
    assert check_aggregates(claim("Delivered over two projects", *fs), fs, context(*fs)) == []


def test_subject_code_claim_passes_metric_check() -> None:  # Review Focus 1, end to end
    f = confirmed("edu_01", kind="education",
                  text="43007 Advanced Artificial Intelligence",
                  attributes=attrs(start="2026-07", end=None,
                                   title="43007 Advanced Artificial Intelligence",
                                   organisation="University of Technology Sydney"))
    result = run_layer1(claim("Completed 43007 Advanced Artificial Intelligence", f),
                        context(f))
    assert result.passed, result.failures


# Task 7 (P8) was reverted after two review rounds: with no upper limit on a lower-is-better
# record, each fix left a way for a stray number to pass (P10). The layer 1 code is back to
# 2010eec, where every metric rounds toward zero. Rejections that code makes are plain tests;
# rejections it does not make are strict xfails naming the limitation (the judge covers them).

_P8_LIMITATION = pytest.mark.xfail(
    strict=True,
    reason="Task 7 reverted (P10): a lower-is-better absolute record still rounds toward "
           "zero, and a time unit glued to its number is not read. Documented limitation; "
           "the judge covers it.")


def _clash_latency() -> object:
    return metric(metric_id="m_clash", metric="latency", direction="absolute", value=2.0,
                  unit="seconds", span_text="cut timetable clash checks to under 2 seconds")


def _hosting_cost() -> object:
    return metric(metric_id="m_cost", metric="cost", direction="absolute", value=400.0,
                  unit="usd", span_text="kept hosting cost to $400 a month")


def _error_rate() -> object:
    return metric(metric_id="m_err", metric="error_rate", direction="absolute", value=5.0,
                  unit="percent", span_text="an error rate of 5%")


def _rejects(text: str, rec: object) -> bool:
    f = project(metrics=[rec])
    return not run_layer1(claim(text, f), context(f)).passed


@_P8_LIMITATION
def test_lower_is_better_value_below_the_record_fails() -> None:
    for text in ("Clash check latency is 1 second", "Clash check latency is 0.5 seconds",
                 "Clash checks run in 1 second"):
        assert _rejects(text, _clash_latency()), text
    assert _rejects("Kept the error rate at 3%", _error_rate())


def test_lower_is_better_equal_value_passes() -> None:
    f = project(metrics=[_clash_latency()])
    for text in ("Clash check latency is 2 seconds", "Clash check latency is under 2 seconds",
                 "Clash check latency is 2s", "Clash check latency is at least 2 seconds",
                 "Clash check latency is over 1 second"):
        assert check_metrics(claim(text, f), [f], context(f)) == [], text
    g = project(metrics=[_error_rate()])
    assert check_metrics(claim("Kept the error rate at 5%", g), [g], context(g)) == []
    h = project(metrics=[_hosting_cost()])
    assert check_metrics(claim("Kept hosting cost at $400 a month", h), [h], context(h)) == []


def test_decrease_record_still_rounds_toward_zero() -> None:
    f = project(metrics=[latency()])
    assert check_metrics(claim("Cut latency by 40%", f), [f], context(f)) == []
    assert check_metrics(claim("Cut latency by 50%", f), [f], context(f)) != []


def test_units_that_differ_fail_closed() -> None:
    # "2,000" reads as the year 2000, so the dates rule is what rejects "under 2,000 ms".
    for text in ("Clash checks run in under 2,000 ms", "Clash checks run in 1500 ms",
                 "Clash check latency is under 2,000 ms", "Clash check latency is 1500 ms"):
        assert _rejects(text, _clash_latency()), text


@_P8_LIMITATION
def test_glued_time_unit_below_the_record_fails() -> None:
    for text in ("Clash checks run in 1s", "Clash checks run in 0.5s"):
        assert _rejects(text, _clash_latency()), text


def test_unitless_number_against_a_lower_is_better_record_fails() -> None:
    for text in ("Clash check latency is now 500.", "Clash check latency stays low across 40.",
                 "Clash check latency is 800 on average",
                 "Ran clash checks on 300 of the plans with low latency"):
        assert _rejects(text, _clash_latency()), text
    assert _rejects("Fixed errors in 50 of the modules", _error_rate())
    assert _rejects("Kept hosting cost to 900 of budget", _hosting_cost())


def test_value_above_a_lower_is_better_record_fails() -> None:
    for text in ("Clash checks take 3 seconds", "Clash check latency is at least 3 seconds",
                 "Clash check latency is over 3 seconds", "Clash check latency is 3+ seconds"):
        assert _rejects(text, _clash_latency()), text


def test_unitless_number_beside_a_lower_is_better_record_does_not_bind_elsewhere() -> None:
    count = metric(metric_id="m_n", metric="count", direction="absolute", value=500.0,
                   unit="count", span_text="500 plans")
    f = project(metrics=[_clash_latency(), count])
    failures = check_metrics(claim("Clash checks finished in 500", f), [f], context(f))
    assert [x.rule for x in failures] == ["metrics"], failures


def test_saving_above_an_absolute_cost_record_fails() -> None:
    for text in ("Saved $500 in hosting cost", "Hosting cost savings of $500"):
        assert _rejects(text, _hosting_cost()), text


@_P8_LIMITATION
def test_saving_needs_a_decrease_record() -> None:
    assert _rejects("Saved $300 in hosting costs", _hosting_cost())
    assert _rejects("Saved 1 second of clash check latency", _clash_latency())


def test_higher_is_better_absolute_record_still_rounds_toward_zero() -> None:
    rec = metric(metric_id="m_acc_abs", metric="accuracy", direction="absolute", value=84.0,
                 unit="percent", span_text="84% accuracy")
    f = project(metrics=[rec])
    assert check_metrics(claim("Reached 80% accuracy", f), [f], context(f)) == []
    assert check_metrics(claim("Reached 90% accuracy", f), [f], context(f)) != []
    assert check_metrics(claim("Reached 80% on the test set", f), [f], context(f)) == []


# Task 5 (spec 7.1): the live claim that Layer 1 rejected. With the subject fact cited as the
# extractor writes it (title and span lead with the code), the code is an identifier. Cited
# without that fact, the code is in no cited evidence and the rejection is right.


def _subject_43007() -> FactVersion:
    return confirmed("d_f02", text="Studied 43007 Advanced Artificial Intelligence.",
                     kind="education", attributes=attrs(title="43007 Advanced Artificial "
                                                              "Intelligence"))


def _degree() -> FactVersion:
    return confirmed("d_f01", text="Bachelor of Computing Science, University of Technology "
                     "Sydney", kind="education",
                     attributes=attrs(title="Bachelor of Computing Science",
                                      organisation="University of Technology Sydney",
                                      start="2024-02", end="2026-11"))


_LIVE_43007 = ("Studied 43007 Advanced Artificial Intelligence as part of a Bachelor of "
               "Computing Science.")


def test_live_subject_code_claim_passes_with_the_subject_fact_cited() -> None:
    facts = [_degree(), _subject_43007()]
    assert run_layer1(claim(_LIVE_43007, *facts), context(*facts)).passed


def test_live_subject_code_claim_citing_only_the_degree_is_rejected() -> None:
    deg = _degree()
    failures = check_metrics(claim(_LIVE_43007, deg), [deg], context(deg))
    assert [(x.rule, x.phrase) for x in failures] == [("metrics", "43007")]
