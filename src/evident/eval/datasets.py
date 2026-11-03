"""Synthetic datasets: the A1 profiles, their fictional A3 enrichment, and ground truth.

Ground truth is for scoring only. Pipeline code must never import it (a test checks this).
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from evident.contracts.facts import (
    FactAttributes,
    FactVersion,
    MetricRecord,
    PdfTextSource,
)

SYNTHETIC = Path("data/synthetic")
A1_PROFILES = SYNTHETIC / "student_profiles.jsonl"
GROUND_TRUTH_OWNER = "ground-truth"
# A fixed time keeps the committed ground truth byte-for-byte reproducible.
GROUND_TRUTH_CONFIRMED_AT = datetime(2026, 10, 25, tzinfo=UTC)


@dataclass(frozen=True)
class Dataset:
    """One folder of fictional profiles, built the same way: source records plus an overlay."""

    name: str
    dir: Path
    source_profiles: Path
    enrichment_note: str
    marker: str

    @property
    def overlay(self) -> Path:
        return self.dir / "overlay.json"

    @property
    def profiles(self) -> Path:
        return self.dir / "profiles.jsonl"

    @property
    def ground_truth_dir(self) -> Path:
        return self.dir / "ground_truth"

    @property
    def rendered_dir(self) -> Path:
        return self.dir / "rendered"


A3_ENRICHED = Dataset(
    name="a3_enriched",
    dir=SYNTHETIC / "a3_enriched",
    source_profiles=A1_PROFILES,
    enrichment_note=(
        "Dates, ownership, deployment, metrics and metric sentences are fictional, added for "
        "A3 testing. See data/synthetic/a3_enriched/overlay.json."
    ),
    marker="Synthetic profile, A3 testing",
)
# Profiles 06 to 10: the phase 1 locked test split (spec 4). The A1 files stay untouched.
HELDOUT_P1 = Dataset(
    name="heldout_p1",
    dir=SYNTHETIC / "heldout_p1",
    source_profiles=SYNTHETIC / "heldout_p1" / "source_profiles.jsonl",
    enrichment_note=(
        "Everything in this profile is fictional, written for phase 1 held-out testing. "
        "See data/synthetic/heldout_p1/overlay.json."
    ),
    marker="Synthetic profile, phase 1 testing",
)
DATASETS = {d.name: d for d in (A3_ENRICHED, HELDOUT_P1)}
_PROFILE_ID = re.compile(r"^student_profile_(\d{2})$")


def dataset_for(document_id: str) -> Dataset:
    match = _PROFILE_ID.match(document_id)
    number = int(match.group(1)) if match else 0
    if 1 <= number <= 5:
        return A3_ENRICHED
    if 6 <= number <= 10:
        return HELDOUT_P1
    raise ValueError(f"no synthetic dataset holds {document_id!r}")


# Older names, kept so existing imports keep working.
ENRICHED_DIR = A3_ENRICHED.dir
OVERLAY = A3_ENRICHED.overlay
ENRICHED_PROFILES = A3_ENRICHED.profiles
GROUND_TRUTH_DIR = A3_ENRICHED.ground_truth_dir
ENRICHMENT_NOTE = A3_ENRICHED.enrichment_note

# SHA-256 of the A1 files with CRLF normalised to LF, recorded 2026-10-25 at commit 52ab483.
A1_HASHES = {
    "jobs.jsonl": "0f9403de41f2de0605bbbf6ef3faa3a81f265b7ec36938aea6c058ada723b461",
    "README.md": "2084d83a2f58951de5059ba7a99e4dea8446ad00d01303ea020ffc9c813a2179",
    "student_introductions.jsonl":
        "5dcaaa8fad02c522f84bbafe851243561ef576e2bc9d79b0d8ac1277a7f3f684",
    "student_profiles.jsonl": "634f21e0b013d14378f0cfaf85c165dd24d292b0b32497f4413f5588c6b4c7d8",
}

_FACTS = TypeAdapter(list[FactVersion])
_ENTRY_FIELDS = ("start", "end", "ownership", "deployment")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def enrich(profile: dict[str, Any], overlay: dict[str, Any],
           note: str = A3_ENRICHED.enrichment_note) -> dict[str, Any]:
    """Return a copy of a source profile with its overlay merged in. The input is not modified."""
    out = copy.deepcopy(profile)
    extra = overlay[out["document_id"]]
    out["education_start"] = extra["education_start"]
    out["expected_graduation_month"] = extra["expected_graduation_month"]
    out["enrichment_note"] = note
    for section, key in (("projects", "title"), ("experience", "role")):
        additions = extra[section]
        for entry in out[section]:
            add = additions.get(entry[key])
            if add is None:
                raise ValueError(f"overlay has no {section} entry for {entry[key]!r}")
            for field in _ENTRY_FIELDS:
                entry[field] = add[field]
            entry["metrics"] = add["metrics"]
            if add.get("add_sentence"):
                entry["description"] = f"{entry['description']} {add['add_sentence']}"
    return out


def build_enriched_profiles(ds: Dataset = A3_ENRICHED) -> list[dict[str, Any]]:
    overlay = json.loads(ds.overlay.read_text(encoding="utf-8"))
    return [enrich(p, overlay, ds.enrichment_note) for p in _read_jsonl(ds.source_profiles)]


def load_enriched_profiles(ds: Dataset = A3_ENRICHED) -> list[dict[str, Any]]:
    return _read_jsonl(ds.profiles)


def _attrs(**fields: Any) -> FactAttributes:
    base: dict[str, Any] = {"ownership": None, "deployment": None, "metrics": [], "start": None,
                            "end": None, "skills": [], "title": None, "organisation": None}
    base.update(fields)
    return FactAttributes.model_validate_json(json.dumps(base))


def _metrics(entry: dict[str, Any], counter: list[int]) -> list[MetricRecord]:
    records = []
    for m in entry["metrics"]:
        counter[0] += 1
        records.append(MetricRecord.model_validate_json(json.dumps(
            {**m, "metric_id": f"m_{counter[0]:02d}", "value": float(m["value"]),
             "baseline": None}
        )))
    return records


def ground_truth_facts(
    profile: dict[str, Any], owner_id: str, document_id: str
) -> list[FactVersion]:
    """The facts a perfect extractor would return for this profile's rendered CV.

    Summary and activities are not career facts under the extraction prompt, so they are left
    out; so are links and contact details.
    """
    rows: list[tuple[str, str, FactAttributes]] = []
    institution = profile["institution"]
    rows.append(("education", f"{profile['degree']}, {institution}", _attrs(
        title=profile["degree"], organisation=institution, start=profile["education_start"])))
    for subject in profile["relevant_current_subjects"] + profile["coursework_highlights"]:
        rows.append(("education", subject, _attrs(title=subject, organisation=institution)))
    counter = [0]
    for e in profile["experience"]:
        attrs = _attrs(title=e["role"], organisation=e["organisation"], start=e["start"],
                       end=e["end"], ownership=e["ownership"], deployment=e["deployment"])
        rows.append(("experience", e["description"],
                     attrs.model_copy(update={"metrics": _metrics(e, counter)})))
    for p in profile["projects"]:
        attrs = _attrs(title=p["title"], start=p["start"], end=p["end"], ownership=p["ownership"],
                       deployment=p["deployment"], skills=p["technologies"])
        rows.append(("project", p["description"],
                     attrs.model_copy(update={"metrics": _metrics(p, counter)})))
    for skill in profile["technical_skills"]:
        rows.append(("skill", skill, _attrs(skills=[skill])))

    facts = []
    for i, (kind, text, attrs) in enumerate(rows, start=1):
        payload = {
            "fact_id": f"{document_id}_gt{i:02d}",
            "version": 1,
            "owner_id": owner_id,
            "status": "confirmed",
            "kind": kind,
            "text": text,
            "attributes": json.loads(attrs.model_dump_json()),
            "source": json.loads(PdfTextSource(
                document_id=document_id, page=1, bbox=(0.0, 0.0, 0.0, 0.0), span_text=text,
                confidence=1.0, span_found=True).model_dump_json()),
            "supersedes": None,
            "edited_by_user": False,
            "confirmed_at": GROUND_TRUTH_CONFIRMED_AT.isoformat(),
        }
        facts.append(FactVersion.model_validate_json(json.dumps(payload)))
    return facts


def ground_truth_path(document_id: str) -> Path:
    return dataset_for(document_id).ground_truth_dir / f"{document_id}.json"


def dump_ground_truth(facts: list[FactVersion]) -> bytes:
    return _FACTS.dump_json(facts, indent=2)


def load_ground_truth(document_id: str) -> list[FactVersion]:
    return _FACTS.validate_json(ground_truth_path(document_id).read_bytes())
