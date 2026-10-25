from __future__ import annotations

from evident.validation.layer1.checks_scope import (
    check_dates,
    check_deployment,
    check_durations,
    check_entities,
    check_ownership,
    check_skills,
)
from evident.validation.layer1.run import run_layer1
from tests.builders import attrs
from tests.validation.support import claim, confirmed, context, project


def test_since_2023_rejected_when_fact_starts_2025_02() -> None:
    f = project(start="2025-02", end="2025-06")
    (failure,) = check_dates(claim("Building course tools since 2023", f), [f], context(f))
    assert failure.rule == "dates" and failure.phrase == "since 2023"


def test_date_inside_fact_range_passes() -> None:
    f = project(start="2025-02", end="2025-06")
    assert check_dates(claim("In March 2025 built a clash checker", f), [f], context(f)) == []
    assert check_dates(claim("Built a clash checker in 2025", f), [f], context(f)) == []


def test_three_years_python_from_20_months_rejected() -> None:
    f = project(start="2024-01", end="2025-08")  # 20 months
    (failure,) = check_durations(claim("Three years of Python", f), [f], context(f))
    assert failure.rule == "durations" and "20 months" in failure.detail


def test_overlapping_facts_counted_once() -> None:
    a = project("p_a", start="2024-01", end="2025-08")
    b = project("p_b", start="2024-06", end="2025-08")
    ctx = context(a, b)
    assert check_durations(claim("18 months of Python", a, b), [a, b], ctx) == []
    assert check_durations(claim("Two years of Python", a, b), [a, b], ctx)[0].rule == "durations"


def test_ongoing_role_measured_to_as_of() -> None:  # Review Focus 2
    f = project(start="2025-01", end=None)  # to 2026-10: 22 months
    assert check_durations(claim("18 months of Python", f), [f], context(f)) == []
    assert check_durations(claim("Two years of Python", f), [f], context(f))[0].rule == "durations"


def test_duration_uses_only_facts_naming_the_skill() -> None:
    py = project("p_py", start="2025-01", end="2025-06", skills=["Python"])
    java = project("p_java", start="2023-01", end="2024-12", skills=["Java"])
    (failure,) = check_durations(claim("Two years of Python", py, java), [py, java],
                                 context(py, java))
    assert "6 months" in failure.detail


def test_led_on_built_fact_rejected() -> None:
    f = project(ownership="built")
    (failure,) = check_ownership(claim("Led the timetable clash checker", f), [f], context(f))
    assert failure.rule == "ownership" and failure.phrase == "led"
    assert check_ownership(claim("Built the timetable clash checker", f), [f], context(f)) == []


def test_skill_fact_without_ownership_does_not_lower_the_bar() -> None:
    proj = project(ownership="built")
    skill = confirmed("sk_01", kind="skill", text="Python", attributes=attrs(skills=["Python"]))
    assert check_ownership(claim("Built a checker in Python", proj, skill), [proj, skill],
                           context(proj, skill)) == []


def test_production_on_prototype_rejected() -> None:
    f = project(deployment="prototype")
    (failure,) = check_deployment(claim("Shipped a production clash checker", f), [f],
                                  context(f))
    assert failure.rule == "deployment" and failure.phrase in {"production", "shipped"}


def test_kubernetes_without_evidence_rejected() -> None:
    f = project()
    (failure,) = check_skills(claim("Deployed the checker with Kubernetes", f), [f], context(f))
    assert failure.rule == "skills" and failure.phrase == "Kubernetes"


def test_js_alias_matches_javascript() -> None:
    f = project(skills=["JavaScript"])
    assert check_skills(claim("Built the front end in JS", f), [f], context(f)) == []


def test_skill_in_span_text_counts() -> None:
    f = project(skills=[], text="Built a clash checker with SQLite storage")
    assert check_skills(claim("Used SQLite for storage", f), [f], context(f)) == []


def test_senior_engineer_on_graduate_role_rejected() -> None:
    f = confirmed("exp_01", kind="experience", text="Graduate software engineer at a fictional "
                  "technology company", attributes=attrs(title="Graduate Software Engineer",
                                                          organisation="Fictional technology "
                                                                       "company"))
    (failure,) = check_entities(claim("Senior engineer at a technology company", f), [f],
                                context(f))
    assert failure.rule == "entities" and failure.phrase == "senior"


def test_new_organisation_name_rejected() -> None:
    f = project()
    (failure,) = check_entities(claim("Built a clash checker at Acme Robotics", f), [f],
                                context(f))
    assert failure.rule == "entities" and failure.phrase == "Acme Robotics"


def test_known_names_and_skill_lists_pass_entities() -> None:
    f = confirmed("edu_01", kind="education",
                  text="Bachelor of Computing Science, University of Technology Sydney",
                  attributes=attrs(title="Bachelor of Computing Science",
                                   organisation="University of Technology Sydney"))
    c = claim("Bachelor of Computing Science at UTS, using Python and Flask", f)
    assert check_entities(c, [f], context(f)) == []


def test_plain_rephrasing_passes_layer1() -> None:
    f = project()
    result = run_layer1(claim("Developed a timetable clash checker using Python and Flask", f),
                        context(f))
    assert result.passed, result.failures


def test_inflated_claim_collects_every_failure() -> None:
    f = project(ownership="built", deployment="prototype", start="2025-02", end="2025-06")
    result = run_layer1(
        claim("Led a production clash checker with Kubernetes since 2023", f), context(f)
    )
    assert {x.rule for x in result.failures} == {"ownership", "deployment", "skills", "dates"}
