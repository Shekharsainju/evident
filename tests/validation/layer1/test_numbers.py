from __future__ import annotations

import pytest

from evident.validation.layer1.numbers import (
    NumberKind,
    duration_months,
    find_numbers,
    parse_date_range,
)
from tests.validation.support import LEX


def kinds(text: str, evidence: list[str] | None = None) -> list[NumberKind]:
    return [m.kind for m in find_numbers(text, evidence or [], LEX)]


@pytest.mark.parametrize(
    "text,value,unit,comp",
    [
        ("cut latency by forty percent", 40, "percent", "eq"),
        ("over 40% faster", 40, "percent", "ge"),
        ("40+ users", 40, "users", "ge"),
        ("1,200 requests", 1200, "requests", "eq"),
        ("2k users", 2000, "users", "eq"),
        ("more than two hundred students", 200, "students", "ge"),
        ("1.5m visitors", 1_500_000, "visitors", "eq"),
    ],
)
def test_metric_numbers(text: str, value: float, unit: str, comp: str) -> None:
    (m,) = find_numbers(text, [], LEX)
    assert (m.kind, m.value, m.unit, m.comparator) == (NumberKind.metric, value, unit, comp)


def test_subject_code_is_identifier_not_metric() -> None:  # Review Focus 1
    ms = find_numbers("Completed 43007 Advanced Artificial Intelligence",
                      ["43007 Advanced Artificial Intelligence"], LEX)
    assert [m.kind for m in ms] == [NumberKind.identifier]


def test_version_number_is_identifier() -> None:
    assert kinds("Wrote services in Python 3", ["Python 3"]) == [NumberKind.identifier]


def test_figure_quoted_from_mid_sentence_is_not_an_identifier() -> None:
    evidence = ["Built a dashboard that covered 1,200 survey responses"]
    assert kinds("Covered 1,200 survey responses", evidence) == [NumberKind.metric]


def test_identifier_not_in_evidence_is_metric() -> None:
    assert kinds("Wrote services in Python 3", ["Python service layer"]) == [NumberKind.metric]


def test_year_is_date() -> None:
    assert kinds("Interned since 2023") == [NumberKind.date]


def test_month_year_and_season_year_are_dates() -> None:
    ms = find_numbers("From March 2024 to Summer 2025", [], LEX)
    assert [m.kind for m in ms] == [NumberKind.date, NumberKind.date]
    assert parse_date_range("from march", 2024) == ("2024-03", "2024-03")
    assert parse_date_range("to summer", 2025) == ("2024-12", "2025-02")
    assert parse_date_range("since", 2023) == ("2023-01", "2023-12")


def test_three_years_is_duration() -> None:
    (m,) = find_numbers("three years of Python", [], LEX)
    assert m.kind is NumberKind.duration
    assert duration_months(m) == 36


def test_twenty_months_and_weeks_are_durations() -> None:
    ms = find_numbers("20 months of support and 6 weeks of training", [], LEX)
    assert [m.kind for m in ms] == [NumberKind.duration, NumberKind.duration]
    assert duration_months(ms[0]) == 20
    assert duration_months(ms[1]) == pytest.approx(1.38, abs=0.01)


def test_three_projects_is_aggregate() -> None:
    (m,) = find_numbers("Delivered three projects", [], LEX)
    assert (m.kind, m.value, m.unit) == (NumberKind.aggregate, 3, "projects")


def test_percent_is_never_a_year_or_identifier() -> None:
    assert kinds("reached 2024% growth", ["2024% growth"]) == [NumberKind.metric]


def test_span_offsets_point_into_normalised_text() -> None:
    from evident.validation.layer1.normalise import normalise_text

    text = "Cut latency by 40% and served 1,200 users"
    norm = normalise_text(text)
    for m in find_numbers(text, [], LEX):
        assert norm[m.start:m.end] == m.span


# Task 7 (Review Focus 2): a time unit glued to its number ("1s", "200ms") is still a metric
# number. Without this, "Clash checks run in 1s" had no number for the metric rule to check.


@pytest.mark.parametrize("text,value,unit", [
    ("Clash checks run in 1s", 1.0, "s"),
    ("Clash checks run in 0.5s", 0.5, "s"),
    ("Clash checks run in 200ms", 200.0, "ms"),
    ("Clash checks run in 2secs", 2.0, "secs"),
])
def test_time_unit_glued_to_a_number_is_a_metric(text: str, value: float, unit: str) -> None:
    (m,) = find_numbers(text, [], LEX)
    assert (m.kind, m.value, m.unit) == (NumberKind.metric, value, unit)


def test_decade_is_not_read_as_a_glued_time_unit() -> None:
    assert find_numbers("Worked on retro games from the 1990s", [], LEX) == []
