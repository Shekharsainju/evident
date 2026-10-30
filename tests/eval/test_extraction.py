from __future__ import annotations

from typing import Any

from evident.contracts.facts import FactVersion
from evident.eval.extraction import FieldCounts, f1, field_counts, match_facts
from tests.builders import attrs, fact, metric


def gt(fact_id: str, kind: str, text: str, **attributes: Any) -> FactVersion:
    return fact(fact_id, kind=kind, text=text, attributes=attrs(**attributes))


TRUTH = [
    gt("t1", "experience", "Helped customers", title="Customer Service Assistant",
       organisation="Fictional retail store", start="2023-11"),
    gt("t2", "project", "Built a course planner", title="Team Course Planner",
       start="2025-03", end="2025-06", skills=["Python", "Flask"],
       metrics=[metric(metric="latency", direction="absolute", value=2.0, unit="seconds")]),
    gt("t3", "skill", "Java", skills=["Java"]),
]


def test_match_and_counts_on_hand_example() -> None:
    pred = [
        # Same role, organisation spelt in another case, start right, no end on either side.
        gt("p1", "experience", "Answered customer questions",
           title="Customer service assistant", organisation="fictional retail store",
           start="2023-11"),
        # Project: end wrong, one skill missed, one extra skill, metric unit as an alias.
        gt("p2", "project", "Course planner web API", title="Team Course Planner",
           start="2025-03", end="2025-07", skills=["Python", "SQLite"],
           metrics=[metric(metric="latency", direction="absolute", value=2.0, unit="s")]),
    ]
    pairs = match_facts(pred, TRUTH)
    assert [(p and p.fact_id, t and t.fact_id) for p, t in pairs] == [
        ("p1", "t1"), ("p2", "t2"), (None, "t3")]

    c = field_counts(pairs)
    # p1: kind, title, organisation, start all right (4 tp).
    # p2: kind, title, start, Python, metric right (5 tp); end wrong (1 fp + 1 fn);
    #     SQLite extra (1 fp); Flask missed (1 fn).
    # t3 unmatched: kind and the skill Java missed (2 fn).
    assert c == FieldCounts(tp=9, fp=2, fn=4)
    assert f1(c) == 2 * 9 / (2 * 9 + 2 + 4)


def test_unmatched_prediction_counts_fp() -> None:
    pred = [gt("p9", "project", "Unrelated thing", title="Weather Bot", start="2024-01",
               skills=["Rust"])]
    pairs = match_facts(pred, [])
    assert pairs == [(pred[0], None)]
    # kind, title, start and one skill: 4 non-null fields, all false positives.
    assert field_counts(pairs) == FieldCounts(tp=0, fp=4, fn=0)


def test_kind_must_agree_to_match() -> None:
    pred = [gt("p1", "project", "Java", skills=["Java"])]
    pairs = match_facts(pred, [TRUTH[2]])
    assert (pred[0], None) in pairs and (None, TRUTH[2]) in pairs


def test_match_is_one_to_one_best_score_first() -> None:
    truth = [gt("t1", "skill", "Git", skills=["Git"]),
             gt("t2", "skill", "GitHub", skills=["GitHub"])]
    pred = [gt("p1", "skill", "GitHub", skills=["GitHub"]),
            gt("p2", "skill", "Git", skills=["Git"])]
    pairs = {(p and p.fact_id, t and t.fact_id) for p, t in match_facts(pred, truth)}
    assert pairs == {("p1", "t2"), ("p2", "t1")}


def test_f1_of_nothing_is_zero() -> None:
    assert f1(FieldCounts(0, 0, 0)) == 0.0
