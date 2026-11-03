"""Write the phase 1 locked test claim set (spec 4.3): profiles 06 to 10, seed 2.

Run once, then hand-check (claims_review.md). Prints counts only.

Usage: uv run python scripts/build_p1_claims.py
"""

from __future__ import annotations

from collections import Counter

from evident.eval.grounding import SplitSpec, build_claim_set, dump_claims
from evident.eval.splits import P1_TEST_CLAIMS, P1_TEST_PROFILES


def main() -> None:
    claims = build_claim_set(seed=2, splits=[SplitSpec("test", P1_TEST_PROFILES, 80, 10)])
    P1_TEST_CLAIMS.parent.mkdir(parents=True, exist_ok=True)
    P1_TEST_CLAIMS.write_text(dump_claims(claims), encoding="utf-8")
    print(f"{P1_TEST_CLAIMS}: {len(claims)} claims")
    print(dict(Counter(c.label for c in claims)))
    for category, n in sorted(Counter(str(c.category) for c in claims if c.category).items()):
        print(f"  {category}: {n}")


if __name__ == "__main__":
    main()
