"""Split guard tests.

Contract for later scripts: any tuning or comparison script must refuse a profile from 06
to 10 by raising LockedSplitError (via require_dev). The xfail tests below are switched on
by the task that adds each script, and they accept nothing else, so an argparse exit on an
unknown option can't pass for a guard.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

from evident.eval.grounding import load_claims
from evident.eval.splits import (
    P1_DEV_PROFILES,
    P1_TEST_CLAIMS,
    P1_TEST_PROFILES,
    LockedSplitError,
    load_p1_dev_claims,
    load_p1_test_claims,
    require_dev,
)

ROOT = Path(__file__).resolve().parents[2]


def test_profile_split_is_disjoint_and_complete() -> None:
    assert tuple(f"student_profile_{n:02d}" for n in range(1, 6)) == P1_DEV_PROFILES
    assert tuple(f"student_profile_{n:02d}" for n in range(6, 11)) == P1_TEST_PROFILES


def test_p1_dev_has_125_claims() -> None:
    claims = load_p1_dev_claims()
    assert len(claims) == 125
    assert Counter(c.label for c in claims) == {"supported": 60, "unsupported": 65}
    assert {c.profile_id for c in claims} <= set(P1_DEV_PROFILES)


def test_require_dev_refuses_test_profiles() -> None:
    with pytest.raises(LockedSplitError):
        require_dev(["student_profile_01", "student_profile_07"])
    require_dev(["student_profile_01", "student_profile_05"])


def test_test_claims_need_locked_flag() -> None:
    with pytest.raises(LockedSplitError):
        load_p1_test_claims(locked_run=False)


def test_test_claims_file_is_test_profiles_only() -> None:
    # Reads the file directly: ordinary unit tests never pass locked_run=True.
    assert (ROOT / P1_TEST_CLAIMS).exists()
    claims = load_claims(ROOT / P1_TEST_CLAIMS)
    assert {c.profile_id for c in claims} <= set(P1_TEST_PROFILES)
    assert {c.split for c in claims} == {"test"}


def _load_script(name: str):  # type: ignore[no-untyped-def]
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_tuning_scripts_refuse_test_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script("tune_extraction_dev")
    monkeypatch.setattr(sys, "argv", ["tune", "--profile", "student_profile_07"])
    with pytest.raises(SystemExit, match="Dev tuning uses student_profile_01 only."):
        module.main()


@pytest.mark.xfail(strict=True, reason="scripts/layer1_diff.py arrives in Task 4")
def test_layer1_diff_script_refuses_test_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script("layer1_diff")
    monkeypatch.setattr(sys, "argv", ["diff", "--profile", "student_profile_07"])
    with pytest.raises(LockedSplitError):
        module.main()


@pytest.mark.xfail(strict=True, reason="scripts/compare_judges.py arrives in Task 10")
def test_compare_judges_script_refuses_test_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script("compare_judges")
    monkeypatch.setattr(sys, "argv", ["compare", "--profile", "student_profile_07"])
    with pytest.raises(LockedSplitError):
        module.main()
