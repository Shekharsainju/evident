"""Write the labelled claim sets for Task 20 (spec 9.2). Deterministic: seed 0.

Usage: uv run python scripts/build_claim_sets.py
"""

from __future__ import annotations

from pathlib import Path

from evident.eval.grounding import build_claim_set, dump_claims

EXPERIMENT = Path("experiments/a3-slice")


def main() -> None:
    claims = build_claim_set(seed=0)
    for split in ("dev", "test"):
        path = EXPERIMENT / f"claims_{split}.jsonl"
        chosen = [c for c in claims if c.split == split]
        path.write_text(dump_claims(chosen), encoding="utf-8")
        print(f"{path}: {len(chosen)} claims")


if __name__ == "__main__":
    main()
