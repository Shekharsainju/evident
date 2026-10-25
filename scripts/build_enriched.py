"""Merge the fictional A3 overlay into the A1 profiles and write ground truth.

Usage: uv run python scripts/build_enriched.py
The A1 files are only read, never written.
"""

from __future__ import annotations

import json

from evident.eval.datasets import (
    ENRICHED_PROFILES,
    GROUND_TRUTH_DIR,
    GROUND_TRUTH_OWNER,
    build_enriched_profiles,
    dump_ground_truth,
    ground_truth_facts,
    ground_truth_path,
)


def main() -> None:
    profiles = build_enriched_profiles()
    ENRICHED_PROFILES.parent.mkdir(parents=True, exist_ok=True)
    ENRICHED_PROFILES.write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in profiles), encoding="utf-8"
    )
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    for p in profiles:
        facts = ground_truth_facts(p, owner_id=GROUND_TRUTH_OWNER, document_id=p["document_id"])
        ground_truth_path(p["document_id"]).write_bytes(dump_ground_truth(facts))
        print(f"{p['document_id']}: {len(facts)} ground-truth facts")


if __name__ == "__main__":
    main()
