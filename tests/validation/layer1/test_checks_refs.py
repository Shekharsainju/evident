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
