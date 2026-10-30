from __future__ import annotations

from pathlib import Path

import pytest

from evident.errors import StageError
from evident.eval.grounding import build_claim_set, dump_claims
from evident.eval.runner import EvalOptions, planned_extraction_calls, run_eval
from evident.models.quota import QuotaGuard
from evident.settings import FreeTierLimits, load_model_config
from tests.fakes import FakeAdapter


def guard(tmp_path: Path, rpd: int) -> QuotaGuard:
    limits = FreeTierLimits(rpm=15, tpm=250_000, rpd=rpd, min_interval_s=0.0, checked="test",
                            source="test")
    return QuotaGuard(limits, tmp_path / "quota.json")


def claims_dir(tmp_path: Path) -> Path:
    claims = build_claim_set()
    for split in ("dev", "test"):
        (tmp_path / f"claims_{split}.jsonl").write_text(
            dump_claims([c for c in claims if c.split == split]), encoding="utf-8")
    return tmp_path


def test_write_results_refuses_dev_split(tmp_path: Path) -> None:
    adapter = FakeAdapter({})
    with pytest.raises(ValueError, match="test split"):
        run_eval(EvalOptions(split="dev", suite="all", judge_prompt="v1", write_results=True),
                 adapter, guard(tmp_path, 500), load_model_config(), claims_dir(tmp_path),
                 tmp_path / "out")
    assert adapter.calls == []


def test_run_eval_stops_on_preflight_failure_without_calls(tmp_path: Path) -> None:
    adapter = FakeAdapter({})
    # rpd 10 leaves 8 after the daily margin; the test split needs 24 extraction calls.
    with pytest.raises(StageError) as err:
        run_eval(EvalOptions(split="test", suite="all", judge_prompt="v1"), adapter,
                 guard(tmp_path, 10), load_model_config(), claims_dir(tmp_path),
                 tmp_path / "out")
    assert err.value.code == "eval_exceeds_quota"
    assert adapter.calls == []
    assert not (tmp_path / "out").exists()


def test_planned_extraction_calls_cover_each_split() -> None:
    assert len(planned_extraction_calls("dev")) == 6
    assert len(planned_extraction_calls("test")) == 24
