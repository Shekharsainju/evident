"""Coverage grading and its gate (design: Coverage matching; spec 8.3; invariants section 1).

Every non-boilerplate requirement is graded in one call against all confirmed facts. The
reply is untrusted: it is checked against the confirmed facts before anything is stored.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from evident.contracts.coverage import CoverageRow, Requirement
from evident.contracts.enums import CoverageGrade, FactStatus, RequirementCategory
from evident.contracts.facts import FactRef, FactVersion
from evident.errors import ErrorCategory, StageError
from evident.models.adapter import ModelAdapter, Part, TextPart
from evident.prompts import load_prompt, render_prompt
from evident.settings import Role

log = logging.getLogger("evident.coverage")

NOT_GRADED = "not graded by model"


class DraftRow(BaseModel):
    requirement_id: str
    grade: str
    evidence: list[str] = []
    rationale: str = ""


class GradingDraft(BaseModel):
    rows: list[DraftRow]


def _gate_error(detail: str) -> StageError:
    return StageError(code="coverage_gate", category=ErrorCategory.validation, detail=detail)


def _one_line(value: str) -> str:
    # A fact or requirement must stay on one line, or its text could pose as another entry.
    return " ".join(value.split())


def _dates(fact: FactVersion) -> str:
    a = fact.attributes
    if a.start and a.end:
        return f"{a.start} to {a.end}"
    if a.start:
        return f"{a.start} to present"
    return a.end or ""


def _evidence_line(fact: FactVersion) -> str:
    skills = ", ".join(fact.attributes.skills)
    return (f"{fact.fact_id}@{fact.version}: {_one_line(fact.text)} | {_one_line(skills)} | "
            f"{_dates(fact)}")


def _parse_ref(value: str) -> FactRef:
    fact_id, sep, version = value.strip().rpartition("@")
    if not sep or not fact_id or not version.isdigit() or int(version) < 1:
        raise _gate_error("The grader returned a malformed evidence reference.")
    return FactRef(fact_id=fact_id, version=int(version))


def _grade(value: str) -> CoverageGrade | None:
    try:
        return CoverageGrade(value.strip().lower())
    except ValueError:
        return None


def grade_requirements(
    reqs: list[Requirement], facts: list[FactVersion], adapter: ModelAdapter
) -> list[CoverageRow]:
    gradable = [r for r in reqs if r.category is not RequirementCategory.boilerplate]
    if not gradable:
        return []
    # Checked again here so no caller can send an unconfirmed fact to the grader.
    confirmed = [f for f in facts if f.status is FactStatus.confirmed]
    prompt = load_prompt("coverage")
    parts: list[Part] = [TextPart(render_prompt(
        prompt,
        requirements="\n".join(
            f"{r.requirement_id}: {_one_line(r.text)} ({r.category.value})" for r in gradable),
        candidate_facts="\n".join(_evidence_line(f) for f in confirmed),
    ))]
    draft = adapter.generate_json(Role.coverage, prompt, parts, GradingDraft).value

    by_id = {r.requirement_id: r for r in gradable}
    returned: dict[str, DraftRow] = {}
    for item in draft.rows:
        if item.requirement_id not in by_id:
            raise _gate_error("The grader returned a row for an unknown requirement.")
        if item.requirement_id in returned:
            raise _gate_error("The grader returned two rows for one requirement.")
        returned[item.requirement_id] = item

    rows: list[CoverageRow] = []
    for r in gradable:
        drafted = returned.get(r.requirement_id)
        grade = _grade(drafted.grade) if drafted is not None else None
        if drafted is None or grade is None:
            rows.append(CoverageRow(requirement_id=r.requirement_id, text=r.text,
                                    category=r.category, grade=CoverageGrade.gap,
                                    evidence=[], rationale=NOT_GRADED))
            continue
        refs: list[FactRef] = []
        for raw in drafted.evidence:
            ref = _parse_ref(raw)
            if ref not in refs:
                refs.append(ref)
        rows.append(CoverageRow(requirement_id=r.requirement_id, text=r.text,
                                category=r.category, grade=grade, evidence=refs,
                                rationale=drafted.rationale.strip()))
    log.info("coverage graded requirements=%d facts=%d", len(rows), len(confirmed))
    return rows


def check_coverage_gate(rows: list[CoverageRow], facts: list[FactVersion]) -> None:
    confirmed = {(f.fact_id, f.version) for f in facts if f.status is FactStatus.confirmed}
    problems: list[str] = []
    for row in rows:
        if row.grade is CoverageGrade.gap and row.evidence:
            problems.append(f"{row.requirement_id}: a gap must not cite evidence")
        if row.grade is not CoverageGrade.gap and not row.evidence:
            problems.append(f"{row.requirement_id}: a {row.grade.value} grade needs evidence")
        for ref in row.evidence:
            if (ref.fact_id, ref.version) not in confirmed:
                problems.append(
                    f"{row.requirement_id}: {ref.fact_id}@{ref.version} is not a confirmed fact")
    if problems:
        raise _gate_error("; ".join(problems))
