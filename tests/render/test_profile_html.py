from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pdfplumber
import pytest

from evident.contracts.enums import ClaimOutcome, OutputType, Verdict
from evident.contracts.facts import FactRef
from evident.contracts.plan import Claim, ContentPlan
from evident.contracts.validation import (
    ClaimValidation,
    JudgeVerdict,
    Layer1Result,
    ValidationReport,
)
from evident.errors import StageError
from evident.render.profile_html import (
    heading,
    render_profile,
    render_profile_pdf,
    renderable_claims,
)
from tests.builders import NOW, OWNER

MARKER = "Synthetic profile, A3 testing"
ID = {"name": "Alex Example"}


def claim(claim_id: str, text: str, version: int = 1, output_type: str = "visual_profile",
          fact_id: str = "doc_01_f01", section: str = "projects", emphasis: int = 3,
          parent: str | None = None) -> Claim:
    return Claim(claim_id=claim_id, version=version, text=text,
                 evidence=[FactRef(fact_id=fact_id, version=1)], section=section,
                 emphasis=emphasis, allowed_transformations=[],
                 output_types=[OutputType(output_type)], parent_claim_id=parent)


def validation(c: Claim, outcome: str = "passed", approved: bool = False) -> ClaimValidation:
    verdict = {"passed": "supported", "rejected": "unsupported", "user_review": "supported"}
    confidence = 0.4 if outcome == "user_review" else 0.95
    return ClaimValidation(
        claim_id=c.claim_id, claim_version=c.version, outcome=ClaimOutcome(outcome),
        layer1=Layer1Result(passed=outcome != "rejected", failures=[]),
        judge=JudgeVerdict(verdict=Verdict(verdict[outcome]), offending_phrase=None,
                           corrected_phrasing=None, confidence=confidence),
        judge_model="test-judge", judge_error=None, reasons=[], approved_by_user=approved)


def plan_of(*claims: Claim) -> ContentPlan:
    return ContentPlan(plan_id="plan_01", owner_id=OWNER, target_id="tgt_01",
                       claims=list(claims), created_at=NOW)


def report_of(*results: ClaimValidation, dropped: tuple[str, ...] = (),
              plan_id: str = "plan_01") -> ValidationReport:
    return ValidationReport(plan_id=plan_id, results=list(results),
                            dropped_claim_ids=list(dropped), models_by_role={}, limitations=[])


def plan_with(text: str) -> ContentPlan:
    return plan_of(claim("c_01", text))


REPORT = report_of(validation(claim("c_01", "")))


class ClaimSpans(HTMLParser):
    """Collects the text inside each data-claim-id span as (id, version, text)."""

    def __init__(self) -> None:
        super().__init__()
        self.spans: list[tuple[str | None, str | None, str]] = []
        self._open: list[int | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "span" and "data-claim-id" in a:
            self.spans.append((a["data-claim-id"], a.get("data-claim-version"), ""))
            self._open.append(len(self.spans) - 1)
        elif tag == "span":
            self._open.append(None)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._open:
            self._open.pop()

    def handle_data(self, data: str) -> None:
        for i in self._open:
            if i is not None:
                cid, ver, text = self.spans[i]
                self.spans[i] = (cid, ver, text + data)


def claim_spans(html: str) -> list[tuple[str | None, str | None, str]]:
    parser = ClaimSpans()
    parser.feed(html)
    return parser.spans


def test_rejected_and_unapproved_review_claims_not_rendered() -> None:
    passed = claim("c_01", "Built a timetable clash checker in Python")
    approved = claim("c_02", "Wrote the Flask API for the clash checker")
    unapproved = claim("c_03", "Led a team of five on the clash checker")
    rejected = claim("c_04", "Shipped the clash checker to production")
    plan = plan_of(passed, approved, unapproved, rejected)
    report = report_of(validation(passed), validation(approved, "user_review", approved=True),
                       validation(unapproved, "user_review"), validation(rejected, "rejected"))

    kept = renderable_claims(plan, report, OutputType.visual_profile)
    html = render_profile(plan, report, ID, "")

    assert [c.claim_id for c in kept] == ["c_01", "c_02"]
    assert passed.text in html and approved.text in html
    assert unapproved.text not in html and rejected.text not in html


def test_every_rendered_claim_has_id_and_version() -> None:
    first = claim("c_01", "Built a timetable clash checker in Python")
    second = claim("c_02", "Wrote the Flask API for the clash checker", version=2)
    plan = plan_of(first, second)
    html = render_profile(plan, report_of(validation(first), validation(second)), ID, "")

    spans = claim_spans(html)

    assert sorted((cid, ver) for cid, ver, _ in spans) == [("c_01", "1"), ("c_02", "2")]
    assert {cid: text.strip() for cid, _, text in spans} == {
        "c_01": first.text, "c_02": second.text}


def test_html_special_chars_escaped() -> None:  # Review Focus 4
    html = render_profile(plan_with('Built <script> & "API"'), REPORT, ID, "")
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_pdf_contains_claim_text_and_marker(tmp_path: Path) -> None:
    text = "Built a timetable clash checker in Python"
    html = render_profile(plan_with(text), REPORT, ID, "")

    out = render_profile_pdf(html, tmp_path / "profile.pdf")
    with pdfplumber.open(out) as pdf:
        pdf_text = " ".join(" ".join((p.extract_text() or "") for p in pdf.pages).split())

    assert text in pdf_text and MARKER in pdf_text


def test_pdf_has_link_annotation_per_claim(tmp_path: Path) -> None:
    first = claim("c_01", "Built a timetable clash checker in Python")
    second = claim("c_02", "Wrote the Flask API for the clash checker")
    html = render_profile(plan_of(first, second), report_of(validation(first), validation(second)),
                          ID, "/receipts")
    links = {
        "c_01": "https://evident.test/receipts/c_01?plan_id=plan_01",
        "c_02": "https://evident.test/receipts/c_02?plan_id=plan_01",
    }
    out = render_profile_pdf(html, tmp_path / "profile.pdf", links)

    with pdfplumber.open(out) as pdf:
        uris = {annot["uri"] for page in pdf.pages for annot in page.annots or []}

    assert uris == set(links.values())


def test_styled_profile_still_passes_post_render() -> None:
    from evident.render.profile_html import TEMPLATE_COPY
    from evident.validation.post_render import verify_html

    c = claim("c_01", "Built a timetable clash checker in Python")
    html = render_profile(plan_of(c), report_of(validation(c)), ID, "/receipts")
    result = verify_html(html, {c.claim_id: c.text}, ID, TEMPLATE_COPY)

    assert result.passed, result.problems


# Fail-closed rules in renderable_claims


def kept_ids(plan: ContentPlan, report: ValidationReport) -> list[str]:
    return [c.claim_id for c in renderable_claims(plan, report, OutputType.visual_profile)]


def test_unvalidated_new_version_beside_validated_one_not_rendered() -> None:
    old = claim("c_01", "Built a timetable clash checker in Python")
    new = claim("c_01", "Built and shipped a timetable clash checker", version=2)
    assert kept_ids(plan_of(old, new), report_of(validation(old))) == []


def test_duplicate_claim_ids_in_plan_fail_closed() -> None:
    first = claim("c_01", "Built a timetable clash checker in Python")
    twin = claim("c_01", "Led the timetable clash checker project")
    assert kept_ids(plan_of(first, twin), report_of(validation(first))) == []


def test_validation_for_another_version_not_rendered() -> None:
    validated = claim("c_01", "Built a timetable clash checker in Python")
    edited = claim("c_01", "Built a timetable clash checker in Python", version=2)
    assert kept_ids(plan_of(edited), report_of(validation(validated))) == []


def test_dropped_claim_not_rendered() -> None:
    c = claim("c_01", "Built a timetable clash checker in Python")
    assert kept_ids(plan_of(c), report_of(validation(c), dropped=("c_01",))) == []


def test_report_for_another_plan_raises() -> None:
    c = claim("c_01", "Built a timetable clash checker in Python")
    with pytest.raises(StageError):
        renderable_claims(plan_of(c), report_of(validation(c), plan_id="plan_02"),
                          OutputType.visual_profile)


def test_derived_claim_with_rejected_parent_not_rendered() -> None:
    parent = claim("c_01", "Built a timetable clash checker in Python")
    child = claim("c_02", "Built a clash checker", parent="c_01")
    report = report_of(validation(parent, "rejected"), validation(child))
    assert kept_ids(plan_of(parent, child), report) == []


@pytest.mark.parametrize("first", ["passed", "rejected"])
def test_conflicting_records_for_one_version_not_rendered(first: str) -> None:
    c = claim("c_01", "Built a timetable clash checker in Python")
    second = "rejected" if first == "passed" else "passed"
    report = report_of(validation(c, first), validation(c, second))
    assert kept_ids(plan_of(c), report) == []


def test_claim_for_another_output_type_not_rendered() -> None:
    c = claim("c_01", "Built a timetable clash checker in Python", output_type="interview_deck")
    assert kept_ids(plan_of(c), report_of(validation(c))) == []


def test_section_heading_ignores_case() -> None:
    assert heading("Projects") == heading("PROJECTS") == heading("projects") == "Projects"
