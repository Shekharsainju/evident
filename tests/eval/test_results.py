from __future__ import annotations

from evident.eval.results import TEST_HEADING, replace_section

CRITERIA = "# A3 results\n\n## Pass criteria (stated before running)\n\nF1 >= 0.95.\n"


def test_results_section_appended_after_criteria() -> None:
    out = replace_section(CRITERIA, TEST_HEADING, "numbers")
    assert out.startswith(CRITERIA.rstrip())
    assert out.endswith(f"{TEST_HEADING}\n\nnumbers\n")


def test_results_section_replaced_and_criteria_kept() -> None:
    once = replace_section(CRITERIA, TEST_HEADING, "old numbers")
    twice = replace_section(once, TEST_HEADING, "new numbers")
    assert "old numbers" not in twice and "new numbers" in twice
    assert twice.count(TEST_HEADING) == 1
    assert twice.startswith(CRITERIA.rstrip())
