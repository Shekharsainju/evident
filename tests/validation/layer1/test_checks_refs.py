from __future__ import annotations

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


# Task 7 (P8, Decision log 13): a lower-is-better metric recorded as an absolute value may
# round away from zero, never toward it. Fix round 1: such a record binds only a number with
# a unit in its family, in a claim that names the metric; a lower bound above the record
# fails; a saving word means a change, which an absolute record cannot back.


def _clash_latency() -> object:
    return metric(metric_id="m_clash", metric="latency", direction="absolute", value=2.0,
                  unit="seconds", span_text="cut timetable clash checks to under 2 seconds")


def _hosting_cost() -> object:
    return metric(metric_id="m_cost", metric="cost", direction="absolute", value=400.0,
                  unit="usd", span_text="kept hosting cost to $400 a month")


def _error_rate() -> object:
    return metric(metric_id="m_err", metric="error_rate", direction="absolute", value=5.0,
                  unit="percent", span_text="an error rate of 5%")


def _unbound(text: str, rec: object) -> bool:
    f = project(metrics=[rec])
    failures = check_metrics(claim(text, f), [f], context(f))
    return any(x.rule == "metrics" and "unbound" in x.detail for x in failures)


def test_lower_is_better_old_false_accepts_now_fail() -> None:
    f = project(metrics=[_clash_latency()])
    for text in ("Clash check latency is 1 second", "Clash check latency is 0.5 seconds"):
        failures = check_metrics(claim(text, f), [f], context(f))
        assert len(failures) == 1, (text, failures)
        assert failures[0].rule == "metrics" and "beyond" in failures[0].detail, text


def test_lower_is_better_equal_or_higher_passes() -> None:
    f = project(metrics=[_clash_latency()])
    for text in ("Clash check latency is 2 seconds", "Clash check latency is about 3 seconds",
                 "Clash check latency is under 2 seconds", "Clash check latency is 2s"):
        assert check_metrics(claim(text, f), [f], context(f)) == [], text


def test_decrease_record_still_rounds_toward_zero() -> None:
    f = project(metrics=[latency()])
    assert check_metrics(claim("Cut latency by 40%", f), [f], context(f)) == []
    assert check_metrics(claim("Cut latency by 50%", f), [f], context(f)) != []


def test_units_that_differ_fail_closed() -> None:
    # Whole Layer 1, not only check_metrics: "2,000" reads as the year 2000, so the dates
    # rule is what rejects "under 2,000 ms".
    f = project(metrics=[_clash_latency()])
    for text in ("Clash checks run in under 2,000 ms", "Clash checks run in 1500 ms",
                 "Clash checks run in 1s", "Clash checks run in 0.5s",
                 "Clash check latency is under 2,000 ms", "Clash check latency is 1500 ms"):
        assert not run_layer1(claim(text, f), context(f)).passed, text


def test_lower_is_better_unitless_number_is_unbound() -> None:
    rec = _clash_latency()
    for text in ("Clash check latency is now 500.",
                 "Clash check latency stays low across 40.",
                 "Clash check latency is 800 on average",
                 "Ran clash checks on 300 of the plans with low latency"):
        assert _unbound(text, rec), text
    assert _unbound("Fixed errors in 50 of the modules", _error_rate())
    assert _unbound("Kept hosting cost to 900 of budget", _hosting_cost())


def test_lower_is_better_number_without_the_metric_keyword_is_unbound() -> None:
    rec = _clash_latency()
    for text in ("Clash checks run in 1 second", "Clash checks run in 2 seconds",
                 "Clash checks take 3 seconds", "Clash checks finish in 2s"):
        assert _unbound(text, rec), text
    assert _unbound("Hosting came to $400 a month", _hosting_cost())


def test_unitless_number_beside_a_lower_is_better_record_does_not_bind_elsewhere() -> None:
    # Dropping the latency record must not leave a count record to bind the stray number.
    count = metric(metric_id="m_n", metric="count", direction="absolute", value=500.0,
                   unit="count", span_text="500 plans")
    f = project(metrics=[_clash_latency(), count])
    failures = check_metrics(claim("Clash checks finished in 500", f), [f], context(f))
    assert [x.rule for x in failures] == ["metrics"], failures


def test_lower_bound_above_a_lower_is_better_record_fails() -> None:
    f = project(metrics=[_clash_latency()])
    for text in ("Clash check latency is at least 3 seconds",
                 "Clash check latency is over 3 seconds",
                 "Clash check latency is 3+ seconds"):
        failures = check_metrics(claim(text, f), [f], context(f))
        assert [x.rule for x in failures] == ["metrics"], text
    for text in ("Clash check latency is at least 2 seconds",
                 "Clash check latency is over 1 second"):
        assert check_metrics(claim(text, f), [f], context(f)) == [], text


def test_saving_needs_a_decrease_record() -> None:
    for text in ("Saved $500 in hosting cost", "Saved $300 in hosting costs",
                 "Hosting cost savings of $500"):
        assert _unbound(text, _hosting_cost()), text
    assert _unbound("Saved 1 second of clash check latency", _clash_latency())
    f = project(metrics=[_hosting_cost()])
    for text in ("Kept hosting cost at $400 a month", "Hosting cost was about $450 a month"):
        assert check_metrics(claim(text, f), [f], context(f)) == [], text


def test_lower_is_better_error_rate_rounds_away_from_zero() -> None:
    f = project(metrics=[_error_rate()])
    (failure,) = check_metrics(claim("Kept the error rate at 3%", f), [f], context(f))
    assert "beyond" in failure.detail
    assert check_metrics(claim("Kept the error rate at 5%", f), [f], context(f)) == []


def test_higher_is_better_absolute_record_still_rounds_toward_zero() -> None:
    rec = metric(metric_id="m_acc_abs", metric="accuracy", direction="absolute", value=84.0,
                 unit="percent", span_text="84% accuracy")
    f = project(metrics=[rec])
    assert check_metrics(claim("Reached 80% accuracy", f), [f], context(f)) == []
    assert check_metrics(claim("Reached 90% accuracy", f), [f], context(f)) != []
    assert check_metrics(claim("Reached 80% on the test set", f), [f], context(f)) == []
