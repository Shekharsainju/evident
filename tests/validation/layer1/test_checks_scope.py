from __future__ import annotations

import pytest

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
from tests.validation.support import claim, confirmed, context, metric, project


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


# Written dates are not names (A3 dev false rejects); the date rule still covers them.


def test_written_dates_are_not_names() -> None:
    f = project(start="2024-02", end="2025-06")
    for text in ("Worked on the Team Course Planner project from Mar 2025 to Jun 2025.",
                 "Building the Team Course Planner since February 2024",
                 "Since February 2024, built the Team Course Planner",
                 "From Mar 2025 to Jun 2025 worked on the Team Course Planner",
                 "Started the Team Course Planner in Feb 2024."):
        assert check_entities(claim(text, f), [f], context(f)) == [], text


def test_date_outside_fact_range_still_rejected_by_date_rule() -> None:
    f = project(start="2025-02", end="2025-06")
    result = run_layer1(claim("Worked on the Team Course Planner project from Mar 2024 to "
                              "Jun 2025.", f), context(f))
    assert {x.rule for x in result.failures} == {"dates"}


def test_unknown_name_next_to_a_date_still_rejected() -> None:
    f = project()
    for text in ("Built a clash checker at Acme Robotics in Mar 2025",
                 "Built a clash checker for Acme Robotics Mar 2025"):
        (failure,) = check_entities(claim(text, f), [f], context(f))
        assert failure.phrase == "Acme Robotics", text


def test_month_word_inside_a_name_still_checked() -> None:
    f = project()
    (failure,) = check_entities(claim("Built a clash checker at March Networks", f), [f],
                                context(f))
    assert failure.phrase == "March Networks"


# Name runs split on "and": each part is its own name.


def test_names_joined_by_and_checked_separately() -> None:
    a = project("p_a", title="Coursework Retrieval Assistant")
    b = project("p_b", title="Text Classification Study")
    c = claim("Worked on two projects: Coursework Retrieval Assistant and Text Classification "
              "Study.", a, b)
    assert check_entities(c, [a, b], context(a, b)) == []


def test_unknown_name_joined_by_and_still_rejected() -> None:
    f = project()
    (failure,) = check_entities(claim("Worked on two projects: Team Course Planner and Acme "
                                      "Robotics Platform.", f), [f], context(f))
    assert failure.phrase == "Acme Robotics Platform."


def test_unknown_single_word_in_and_list_still_rejected() -> None:
    # "Go" is not a skill alias, so the skill check can't see it; the name check must.
    f = project()
    c = claim("Built the clash checker as a prototype, using Python and Go.", f)
    (failure,) = check_entities(c, [f], context(f))
    assert failure.phrase == "Go."
    assert not run_layer1(c, context(f)).passed


def test_verb_before_an_and_list_is_not_part_of_the_name() -> None:
    a = project("p_a", title="Team Course Planner")
    b = project("p_b", title="Text Classification Study")
    c = claim("Built Team Course Planner and Text Classification Study", a, b)
    assert check_entities(c, [a, b], context(a, b)) == []
    # "Planner" alone is not a whole name in the evidence ("Team Course Planner").
    failures = check_entities(claim("Built Planner and Tracker", a, b), [a, b], context(a, b))
    assert {x.phrase for x in failures} == {"Planner", "Tracker"}


# Reviewer counterexamples: a removed date or an "and" split must not let a name through.


def test_single_word_name_beside_a_date_still_rejected() -> None:
    f = project()
    (failure,) = check_entities(claim("Interned at Google Mar 2025.", f), [f], context(f))
    assert failure.phrase == "Google"
    failures = check_entities(claim("Worked at Acme Fall 2025 and Initech.", f), [f], context(f))
    assert {x.phrase for x in failures} == {"Acme", "Initech."}


def test_and_parts_must_match_a_name_not_a_prose_word() -> None:
    marks = project(text="Achieved top marks in Python and Flask, supervised by Dr Spencer")
    failures = check_entities(claim("Worked at Marks and Spencer.", marks), [marks],
                              context(marks))
    assert {x.phrase for x in failures} == {"Marks", "Spencer."}  # "Dr Spencer" is the name
    dept = project(text="Studied at the Department of Science, with a focus on technology")
    (failure,) = check_entities(claim("Worked at the Department of Science and Technology.",
                                      dept), [dept], context(dept))
    assert failure.phrase == "Technology."


def test_listed_word_found_only_in_prose_still_rejected() -> None:
    f = project(text="Built a clash checker in Python and Flask ready to go live")
    (failure,) = check_entities(claim("Built the clash checker using Python and Go.", f), [f],
                                context(f))
    assert failure.phrase == "Go."


def test_verb_trimmed_from_a_two_word_list_item() -> None:
    f = project()
    failures = check_entities(claim("Built Acme and Initech.", f), [f], context(f))
    assert {x.phrase for x in failures} == {"Acme", "Initech."}
    # A word outside the verb lexicons stays in the name, which still fails.
    failures = check_entities(claim("Joined Acme and Initech.", f), [f], context(f))
    assert {x.phrase for x in failures} == {"Joined Acme", "Initech."}


def test_strict_part_must_equal_a_whole_evidence_name() -> None:
    cases = [
        ("Worked at Johnson and Johnson.", project(text="Worked with Dr Johnson in Python")),
        ("Worked at Johnson and Johnson.", project(organisation="Johnson Controls")),
        ("Worked at Amazon Mar 2025.", project(text="Deployed on Amazon Web Services")),
    ]
    for text, f in cases:
        assert check_entities(claim(text, f), [f], context(f)) != [], text
        assert not run_layer1(claim(text, f), context(f)).passed, text


def test_word_opening_an_evidence_sentence_is_not_a_name() -> None:
    cases = [
        ("Worked at Ernst and Young.", "Ernst reviewed it. Young users liked it"),
        ("Worked at Marks and Spencer.", "Marks were top. Supervised by Spencer"),
        ("Worked at Department of Science and Technology.",
         "Member of the Department of Science. Joined the Technology Society"),
        ("Worked at Built Mar 2025.", "Built a timetable clash checker in Python and Flask"),
    ]
    for text, evidence in cases:
        f = project(text=evidence)
        assert check_entities(claim(text, f), [f], context(f)) != [], text


def test_sentence_opening_evidence_run_is_only_a_whole_name() -> None:
    cases = [
        ("Worked at Johnson and Johnson.", "Dr Johnson supervised the clash checker in Python"),
        ("Interned at Johnson Mar 2025.", "Dr Johnson supervised the clash checker in Python"),
        ("Interned at Spencer Mar 2025.", "Built a clash checker. Professor Spencer marked it"),
        ("Interned at Sachs Mar 2025.", "Goldman Sachs sponsored the clash checker"),
        ("Worked at Web Services and Team Course Planner.", "Amazon Web Services hosted it"),
        ("Worked at Marks and Spencer.", "Mr Marks reviewed it. Professor Spencer marked it"),
    ]
    for text, evidence in cases:
        f = project(text=evidence)
        assert not run_layer1(claim(text, f), context(f)).passed, text


def test_date_preposition_in_the_name_slot_is_a_name() -> None:
    f = project()
    for text in ("Interned at After Mar 2025.", "Interned at Between Mar 2025."):
        assert not run_layer1(claim(text, f), context(f)).passed, text


def test_only_a_known_verb_is_trimmed_from_a_strict_part() -> None:
    cases = [
        ("Goldman Sachs and Acme backed the planner.",
         project(text="Reviewed by Sachs, then Acme hired me")),
        ("Goldman Sachs Mar 2025 backed the planner.",
         project(text="Reviewed by Sachs while building the planner")),
        ("Goldman Sachs Mar 2025 backed the planner.", project(organisation="Sachs")),
    ]
    for text, f in cases:
        assert not run_layer1(claim(text, f), context(f)).passed, text


def test_lexicon_words_that_are_not_verbs_stay_in_the_name() -> None:
    prod = {"deployment": "production"}
    cases = [
        ("Internal Revenue Service Mar 2025 audited the planner.",
         project(text="Built the planner, checked by Revenue Service staff", **prod)),
        ("Live Nation Mar 2025 used the planner.",
         project(text="Built the planner, shown to Nation staff", **prod)),
        ("Pilot Corp Mar 2025 used the planner.", project(organisation="Corp", **prod)),
        ("Internal Revenue Service and Acme Robotics audited the planner.",
         project(text="Built the planner, checked by Revenue Service staff. Hosted by Acme "
                      "Robotics", **prod)),
    ]
    for text, f in cases:
        assert not run_layer1(claim(text, f), context(f)).passed, text


def test_skill_alias_beside_a_date_must_be_a_cited_name() -> None:
    f = project(text="Joined March Networks as a developer")
    assert not run_layer1(claim("Interned at Networks Mar 2025.", f), context(f)).passed


def test_name_after_a_joiner_in_evidence_is_a_name() -> None:
    f = project(text="Interned at Acme on the planner", start="2025-02", end="2025-06")
    assert check_entities(claim("Interned at Acme Mar 2025.", f), [f], context(f)) == []


def test_word_opening_an_evidence_line_or_bullet_is_not_a_name() -> None:
    for evidence in ("Built the planner\nYoung users liked it",
                     "Built the planner\n• Young users liked it",
                     "Built the planner\n - Young users liked it",
                     "Built the planner (Young users liked it)"):
        f = project(text=evidence)
        c = claim("Interned at Young Mar 2025.", f)
        assert not run_layer1(c, context(f)).passed, evidence


def test_date_the_date_rule_cannot_read_is_not_cut_out() -> None:
    # "December 2, 2025" reads as all of 2025 to the date rule, so the month is unchecked;
    # the entity rule must not cut it out and let it pass.
    f = project(text="Cut timetable clash checks to under 2 seconds at Acme Robotics",
                metrics=[metric()])
    for text in ("Cut timetable clash checks to under 2 seconds at Acme Robotics December 2, "
                 "2025.",
                 "Cut timetable clash checks to under 2 seconds at Acme Robotics Dec 2 2025."):
        assert not run_layer1(claim(text, f), context(f)).passed, text


# Task 6 (spec 7.2) was reverted after three review rounds: each fix opened a new false-accept
# path. The layer 1 code is back to 4478384. These tests keep every rejection the review
# rounds asked for. Cases the 4478384 code already rejects are plain tests. Cases it accepts
# are the documented sentence-start limitation (the Layer 2 judge covers it) and are strict
# xfails, so a future fix that closes them shows up as XPASS.

_LIMITATION = pytest.mark.xfail(
    strict=True,
    reason="Task 6 reverted: a name at a plain sentence start, or after '.', ';' or ':', loses its "
           "first word and a single word is not checked. Documented limitation; the judge "
           "covers it.")
_DASHES = ("-", "–", "—", "*")
_STARTS = ("• ", "- ", "Built it\n")
_DIGIT_LED = ("1Password", "1st", "2nd", "3D", "5G", "10x", "23andMe", "3Com", "8x8",
              "99designs", "2U")


def _entities_rejects(text: str, f) -> bool:  # type: ignore[no-untyped-def]
    return any(x.rule == "entities" for x in check_entities(claim(text, f), [f], context(f)))


def test_unknown_name_after_a_bullet_or_line_break_rejected() -> None:
    f = project()
    for text in ("• Goldman Sachs backed the planner",
                 "Built it\nGoldman Sachs backed it.",
                 "Built it\n• Goldman Sachs backed it."):
        failures = check_entities(claim(text, f), [f], context(f))
        assert [x.rule for x in failures] == ["entities"], text


@_LIMITATION
def test_unknown_sentence_start_name_rejected() -> None:
    f = project()
    for text in ("Goldman Sachs backed the planner.",
                 "Built it; Goldman Sachs backed the planner.",
                 "Built it.\nGoldman Sachs backed it."):
        failures = check_entities(claim(text, f), [f], context(f))
        assert [x.rule for x in failures] == ["entities"], text


def test_name_after_a_bullet_with_one_evidence_word_rejected() -> None:
    f = project(text="Built the planner, checked by Sachs staff")
    assert not run_layer1(claim("• Goldman Sachs backed the planner", f), context(f)).passed


@_LIMITATION
def test_sentence_start_name_with_one_evidence_word_still_rejected() -> None:
    f = project(text="Built the planner, checked by Sachs staff")
    for text in ("Goldman Sachs backed the planner.",
                 "Built it; Goldman Sachs backed the planner."):
        assert not run_layer1(claim(text, f), context(f)).passed, text


def test_sentence_start_name_in_evidence_passes() -> None:
    f = project(text="Built it for the Fictional Robotics Society showcase")
    for text in ("Built the Team Course Planner with Python.",
                 "Led the Fictional Robotics Society showcase.",
                 "• Fictional Robotics Society showcase used it",
                 "Built it; Fictional Robotics Society used it.",
                 "The Team Course Planner cut clash checks to under 2 seconds."):
        assert check_entities(claim(text, f), [f], context(f)) == [], text


def test_name_word_opener_after_a_marker_before_an_unknown_word_is_rejected() -> None:
    f = project()
    cases = ["• The Guardian featured the planner.",
             "Built the planner\nThe Guardian featured it.",
             "Built the planner - The Guardian featured it.",
             "Built the planner — The Guardian featured it.",
             "Built the planner – The Guardian featured it.",
             "Built the planner * The Economist covered it.",
             "• Her Majesty praised the planner.",
             "Built the planner\nWe Mentor backed it.",
             "Built it – Our Goldman backed it.",
             "Built it\nIt Goldman backed it.",
             "Built it\nA Goldman backed it."]
    for text in cases:
        assert _entities_rejects(text, f), text


@_LIMITATION
def test_name_word_opener_at_a_plain_start_before_an_unknown_word_is_rejected() -> None:
    assert _entities_rejects("The Guardian featured the planner.", project())


def test_each_start_marker_rejects_an_opener_before_an_unknown_word() -> None:
    f = project()
    for dash in _DASHES:
        for opener in ("The", "Our", "Her", "We", "It", "A"):
            assert _entities_rejects(f"Built it {dash} {opener} Goldman backed it.", f), \
                (dash, opener)
    for opener in ("The", "Our", "Her", "We", "It", "A"):
        assert _entities_rejects(f"Built it\n{opener} Goldman backed it.", f), opener
        assert _entities_rejects(f"• {opener} Goldman backed it.", f), opener


def test_deployment_noun_opener_is_part_of_the_name() -> None:
    prod = project(deployment="production")
    for text in ("• Live Nation used the planner.", "Built the planner\nLive Nation used it.",
                 "Built it\nPilot Flying backed it.", "Built it\nShipped Sachs tools."):
        assert _entities_rejects(text, prod), text
    concept = project(deployment="concept")
    assert _entities_rejects("• Concept Ventures funded the planner.", concept)


def test_ownership_opener_before_an_unknown_word_is_rejected_on_a_led_fact() -> None:
    led = project(ownership="led")
    for text in ("• Led Zeppelin used it.", "Built it\nLed Zeppelin used it."):
        assert not run_layer1(claim(text, led), context(led)).passed, text


def test_name_word_opener_at_a_plain_start_or_after_a_colon_passes() -> None:
    f = project()
    for text in ("The Planner cut clash checks.", "Built the Team Course Planner.",
                 "Team Course Planner: Reached 84 on it.",
                 "Team Course Planner: Reached 84% on it.",
                 "Team Course Planner: Covered 1,200 on it.",
                 "Team Course Planner: Reached 2.5 on it."):
        assert check_entities(claim(text, f), [f], context(f)) == [], text


def test_digit_led_word_after_an_opener_must_be_in_the_evidence() -> None:
    f = project()
    for start in _STARTS:
        for word in _DIGIT_LED:
            text = f"{start}The {word} team used the Team Course Planner."
            assert not run_layer1(claim(text, f), context(f)).passed, text


def test_digit_led_word_in_a_capitalised_evidence_name_is_supported() -> None:
    f = project(text="Built a planner the 1Password team used, in Python and Flask")
    assert check_entities(claim("• The 1Password team used the planner.", f), [f],
                          context(f)) == []


def test_word_after_an_opener_and_a_marker_must_not_match_only_lowercase_evidence() -> None:
    f = project()  # text: "Built a timetable clash checker in Python and Flask"
    for start in _STARTS:
        for text in (f"{start}The Timetable featured the planner.",
                     f"{start}The Checker won praise.",
                     f"{start}Our Clash team used it."):
            assert _entities_rejects(text, f), text


@_LIMITATION
def test_word_after_an_opener_at_a_plain_start_must_not_match_only_lowercase_evidence() -> None:
    f = project()
    for text in ("The Timetable featured the planner.", "The Checker won praise.",
                 "Our Clash team used it."):
        assert _entities_rejects(text, f), text


def test_word_after_an_opener_at_an_evidence_sentence_start_is_not_a_name() -> None:
    # "Timetable" opens the evidence sentence, so its capital letter says nothing.
    f = project(text="Timetable clash checks ran in Python and Flask")
    assert _entities_rejects("• The Timetable featured the planner.", f)


@pytest.mark.xfail(strict=True, reason="Task 6 reverted: a run kept whole ('The Answer') "
                   "matches lowercase prose in the evidence at any start. Documented "
                   "limitation; the judge covers it.")
def test_opener_led_run_must_not_match_lowercase_prose_as_a_whole() -> None:
    # "the answer" is prose in the evidence; with the opener kept, "The Answer" matches it.
    f = project(text="Built a planner and noted where the answer was uncertain, in Python")
    for start in ("", *_STARTS):
        assert _entities_rejects(f"{start}The Answer featured the planner.", f), start


def test_opener_led_run_with_a_capitalised_evidence_name_is_supported() -> None:
    f = project(text="Built a planner that was featured in The Guardian, in Python")
    for start in ("", *_STARTS):
        text = f"{start}The Guardian featured the planner."
        assert check_entities(claim(text, f), [f], context(f)) == [], text
