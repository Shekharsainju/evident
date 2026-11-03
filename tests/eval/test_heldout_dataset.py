"""Profiles 06 to 10: the phase 1 locked test split (spec 4). Checks shape, never content use."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evident.contracts.enums import FactKind
from evident.eval.assets import TEMPLATES, cv_pdf_path, cv_photo_path, render_cv_html
from evident.eval.datasets import (
    A1_PROFILES,
    HELDOUT_P1,
    load_enriched_profiles,
    load_ground_truth,
)

IDS = [f"student_profile_{n:02d}" for n in range(6, 11)]
# Every employer and issuer in the held-out profiles is invented: a real company in a synthetic CV
# would read as a claim about that company (spec 4.1). The institution is the A1 cohort setting.
COHORT_INSTITUTION = {"University of Technology Sydney"}


def profiles() -> dict[str, dict[str, Any]]:
    return {p["document_id"]: p for p in load_enriched_profiles(HELDOUT_P1)}


def months(ym: str) -> int:
    year, mm = ym.split("-")
    return int(year) * 12 + int(mm)


def test_five_profiles_ids_06_to_10() -> None:
    assert [p["document_id"] for p in load_enriched_profiles(HELDOUT_P1)] == IDS


def test_same_fields_as_a1() -> None:
    a1_keys = set(json.loads(A1_PROFILES.read_text(encoding="utf-8").splitlines()[0]))
    for line in HELDOUT_P1.source_profiles.read_text(encoding="utf-8").splitlines():
        assert set(json.loads(line)) == a1_keys


def test_marked_synthetic() -> None:
    for p in profiles().values():
        assert p["profile_type"] == "synthetic_plausible"
        assert "fictional" in str(p["enrichment_note"]).lower()
    readme = (HELDOUT_P1.dir / "README.md").read_text(encoding="utf-8")
    assert "Everything here is fictional" in readme
    assert "must stay marked as synthetic" in readme


def test_heldout_cv_carries_heldout_marker() -> None:
    html = render_cv_html(profiles()["student_profile_06"], "classic")
    assert HELDOUT_P1.marker in html
    assert "A3 testing" not in html


def test_every_skill_has_evidence() -> None:
    for p in profiles().values():
        evidenced = {e["skill"] for e in p["skill_evidence"]}
        assert set(p["technical_skills"]) <= evidenced, p["document_id"]


def test_metric_span_in_description_and_count() -> None:
    for p in profiles().values():
        entries = p["projects"] + p["experience"]
        for e in entries:
            for m in e["metrics"]:
                assert m["span_text"] in e["description"], (p["document_id"], m)
        assert 1 <= sum(len(e["metrics"]) for e in entries) <= 3, p["document_id"]


def test_shapes() -> None:
    ps = profiles()
    # 06 career changer: a non-software job that ended at least 12 months before study began.
    p06 = ps["student_profile_06"]
    start06 = months(str(p06["education_start"]))
    assert any(e["end"] and start06 - months(e["end"]) >= 12 and e["deployment"] is None
               for e in p06["experience"])
    # 07 gap year: a dated gap-year entry inside the 13 months before study began.
    p07 = ps["student_profile_07"]
    start07 = months(str(p07["education_start"]))
    gap = [e for e in p07["experience"] if "gap year" in e["type"].lower()]
    assert len(gap) == 1
    assert start07 - 13 <= months(gap[0]["start"]) and months(gap[0]["end"]) < start07
    # 08 more work experience: three or more roles, two of them overlapping.
    exp08 = ps["student_profile_08"]["experience"]
    assert len(exp08) >= 3
    spans = [(months(e["start"]), months(e["end"] or "2026-10")) for e in exp08]
    assert any(a[0] <= b[1] and b[0] <= a[1] for i, a in enumerate(spans) for b in spans[i + 1:])
    # 09 mostly skills: a long skill list and one project.
    p09 = ps["student_profile_09"]
    assert len(p09["technical_skills"]) >= 12 and len(p09["projects"]) == 1
    # 10: the two fact kinds profiles 01 to 05 never use.
    kinds = {f.kind for f in load_ground_truth("student_profile_10")}
    assert {FactKind.certification, FactKind.award} <= kinds


def test_no_real_organisations() -> None:
    for doc_id in IDS:
        for f in load_ground_truth(doc_id):
            org = f.attributes.organisation
            if org is not None:
                assert "Fictional" in org or org in COHORT_INSTITUTION, (doc_id, org)


def test_assets_exist() -> None:
    for doc_id in IDS:
        for template in TEMPLATES:
            assert Path(cv_pdf_path(doc_id, template)).is_file()
            assert Path(cv_photo_path(doc_id, template)).is_file()
