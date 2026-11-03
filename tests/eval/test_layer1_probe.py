from __future__ import annotations

from evident.eval.layer1_probe import layer1_outcomes, outcome_key, probe_claims
from evident.eval.splits import P1_TEST_PROFILES, load_p1_dev_claims


def test_probe_claims_dev_only() -> None:
    claims = probe_claims(range(3))
    assert claims
    assert not {c.profile_id for c in claims} & set(P1_TEST_PROFILES)


def test_probe_claims_deterministic() -> None:
    assert probe_claims(range(3)) == probe_claims(range(3))


def test_probe_claims_include_dev_claims_deduplicated() -> None:
    claims = probe_claims(range(3))
    keys = [outcome_key(c) for c in claims]
    assert len(keys) == len(set(keys))
    assert set(keys) >= {outcome_key(c) for c in load_p1_dev_claims()}


def test_outcomes_shape() -> None:
    dev = load_p1_dev_claims()
    supported = next(c for c in dev if c.label == "supported")
    wrong = next(c for c in dev if c.category is not None and c.category.value == "wrong_number")
    out = layer1_outcomes([supported, wrong])
    assert out[outcome_key(supported)] == []
    assert "metrics" in out[outcome_key(wrong)]


def test_diff_script_refuses_extra_with_test_profile(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import sys

    import pytest

    from evident.eval.splits import P1_TEST_CLAIMS, LockedSplitError
    from tests.eval.test_splits import _load_script

    module = _load_script("layer1_diff")
    monkeypatch.setattr(sys, "argv", ["diff", "--base", "HEAD", "--extra", str(P1_TEST_CLAIMS)])
    with pytest.raises(LockedSplitError):
        module.main()
