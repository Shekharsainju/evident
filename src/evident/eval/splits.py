"""Phase 1 data splits (spec 3). Profiles 01 to 05 are dev; 06 to 10 are the locked test.

Tuning code calls require_dev on any profile it touches. The test claims load only for the
one locked run, so nothing can be tuned on them by accident.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from evident.eval.grounding import LabelledClaim, load_claims

P1_DEV_PROFILES: tuple[str, ...] = tuple(f"student_profile_{n:02d}" for n in range(1, 6))
P1_TEST_PROFILES: tuple[str, ...] = tuple(f"student_profile_{n:02d}" for n in range(6, 11))
P1_DEV_CLAIM_FILES = (Path("experiments/a3-slice/claims_dev.jsonl"),
                      Path("experiments/a3-slice/claims_test.jsonl"))
P1_TEST_CLAIMS = Path("experiments/p1-heldout/claims_test.jsonl")


class LockedSplitError(ValueError):
    """Raised when dev or tuning code reaches for the locked test split."""


def load_p1_dev_claims() -> list[LabelledClaim]:
    return [c for path in P1_DEV_CLAIM_FILES for c in load_claims(path)]


def require_dev(profile_ids: Iterable[str]) -> None:
    locked = sorted(set(profile_ids) & set(P1_TEST_PROFILES))
    if locked:
        raise LockedSplitError(f"locked test profiles are not allowed here: {', '.join(locked)}")


def load_p1_test_claims(*, locked_run: bool) -> list[LabelledClaim]:
    if not locked_run:
        raise LockedSplitError("the test claims load only for the locked run")
    return load_claims(P1_TEST_CLAIMS)
