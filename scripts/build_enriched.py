"""Merge a fictional overlay into its source profiles and write ground truth.

Usage: uv run python scripts/build_enriched.py [--dataset a3_enriched|heldout_p1]
The source profiles are only read, never written.
"""

from __future__ import annotations

import argparse
import json

from evident.eval.datasets import (
    DATASETS,
    GROUND_TRUTH_OWNER,
    build_enriched_profiles,
    dump_ground_truth,
    ground_truth_facts,
    ground_truth_path,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="a3_enriched")
    ds = DATASETS[parser.parse_args().dataset]
    profiles = build_enriched_profiles(ds)
    ds.profiles.parent.mkdir(parents=True, exist_ok=True)
    ds.profiles.write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in profiles), encoding="utf-8"
    )
    ds.ground_truth_dir.mkdir(parents=True, exist_ok=True)
    for p in profiles:
        facts = ground_truth_facts(p, owner_id=GROUND_TRUTH_OWNER, document_id=p["document_id"])
        ground_truth_path(p["document_id"]).write_bytes(dump_ground_truth(facts))
        print(f"{p['document_id']}: {len(facts)} ground-truth facts")


if __name__ == "__main__":
    main()
