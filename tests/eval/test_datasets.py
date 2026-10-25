from __future__ import annotations

import hashlib
import re
from pathlib import Path

from evident.contracts.enums import ExtractionPath, FactKind, FactStatus
from evident.contracts.facts import FactVersion
from evident.eval.datasets import (
    A1_HASHES,
    A1_PROFILES,
    ground_truth_facts,
    load_enriched_profiles,
    load_ground_truth,
)

YEAR_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def test_a1_files_unchanged() -> None:
    for name, digest in A1_HASHES.items():
        data = Path("data/synthetic", name).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == digest, name


def test_enriched_keeps_every_a1_profile_and_marks_it_fictional() -> None:
    profiles = load_enriched_profiles()
    assert [p["document_id"] for p in profiles] == [
        f"student_profile_0{i}" for i in range(1, 6)
    ]
    assert all("fictional" in p["enrichment_note"] for p in profiles)


def test_every_metric_span_appears_in_its_description() -> None:
    count = 0
    for p in load_enriched_profiles():
        for entry in p["projects"] + p["experience"]:
            for m in entry["metrics"]:
                assert m["span_text"] in entry["description"], (p["document_id"], m)
                count += 1
    assert count >= 5
    for p in load_enriched_profiles():
        n = sum(len(e["metrics"]) for e in p["projects"] + p["experience"])
        assert 1 <= n <= 3, p["document_id"]


def test_every_project_and_experience_has_dates_ownership_deployment() -> None:
    ongoing = 0
    for p in load_enriched_profiles():
        for entry in p["projects"] + p["experience"]:
            assert YEAR_MONTH.match(entry["start"])
            assert "2023-02" <= entry["start"] <= "2026-10"
            if entry["end"] is None:
                ongoing += 1
            else:
                assert YEAR_MONTH.match(entry["end"])
                assert entry["start"] <= entry["end"] <= "2026-10"
            assert entry["ownership"] in {"contributed", "built", "led"}
            assert "deployment" in entry
        for project in p["projects"]:
            assert project["deployment"] in {"concept", "prototype", "internal", "production"}
        assert YEAR_MONTH.match(p["expected_graduation_month"])
    assert ongoing >= 1


def test_ground_truth_facts_validate_and_cover_each_section() -> None:
    for p in load_enriched_profiles():
        facts = ground_truth_facts(p, owner_id="gt", document_id=p["document_id"])
        kinds = [f.kind for f in facts]
        assert kinds.count(FactKind.project) == len(p["projects"])
        assert kinds.count(FactKind.experience) == len(p["experience"])
        n_courses = len(p["coursework_highlights"]) + len(p["relevant_current_subjects"])
        assert kinds.count(FactKind.education) == 1 + n_courses
        assert kinds.count(FactKind.skill) == len(p["technical_skills"])
        for f in facts:
            assert FactVersion.model_validate_json(f.model_dump_json()) == f
            assert f.status is FactStatus.confirmed and f.version == 1
            assert f.source.extraction_path == ExtractionPath.pdf_text.value
        assert len({f.fact_id for f in facts}) == len(facts)


def test_project_ground_truth_carries_enrichment() -> None:
    p = next(p for p in load_enriched_profiles() if p["document_id"] == "student_profile_01")
    facts = ground_truth_facts(p, owner_id="gt", document_id="student_profile_01")
    planner = next(f for f in facts if f.attributes.title == "Team Course Planner")
    assert planner.attributes.ownership is not None
    assert planner.attributes.ownership.value == "contributed"
    assert (planner.attributes.start, planner.attributes.end) == ("2025-03", "2025-06")
    assert [m.value for m in planner.attributes.metrics] == [2.0]
    assert "Flask" in planner.attributes.skills


def test_summary_and_activities_are_not_ground_truth() -> None:
    for p in load_enriched_profiles():
        texts = [f.text for f in ground_truth_facts(p, "gt", p["document_id"])]
        assert p["summary"] not in texts
        assert not any(a in texts for a in p["activities"])


def test_committed_ground_truth_matches_converter() -> None:
    for p in load_enriched_profiles():
        assert load_ground_truth(p["document_id"]) == ground_truth_facts(
            p, owner_id="ground-truth", document_id=p["document_id"]
        )


def test_a1_profiles_list_matches_hash_list() -> None:
    assert A1_PROFILES.name in A1_HASHES


def test_pipeline_does_not_import_ground_truth() -> None:
    root = Path("src/evident")
    for path in root.rglob("*.py"):
        if path.is_relative_to(root / "eval"):
            continue
        assert "ground_truth" not in path.read_text(encoding="utf-8"), path
