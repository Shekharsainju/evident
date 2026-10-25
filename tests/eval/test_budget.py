from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from evident.errors import ErrorCategory, StageError
from evident.eval.budget import PlannedCall, preflight
from evident.models.adapter import Part, T, TextPart
from evident.models.quota import QuotaGuard
from evident.prompts import Prompt
from evident.settings import FreeTierLimits, Role
from tests.fakes import FakeAdapter

PROMPT = Prompt(name="extraction", version="v1", text="x")


class Reply(BaseModel):
    ok: bool


class CachingFake(FakeAdapter):
    """Reports a call as cached when its text part is in `cached`."""

    def __init__(self, cached: set[str]) -> None:
        super().__init__({})
        self.cached = cached
        self.cache_checks = 0

    def is_cached(self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]) -> bool:
        self.cache_checks += 1
        return any(isinstance(p, TextPart) and p.text in self.cached for p in parts)


def guard(tmp_path: Path, rpd: int) -> QuotaGuard:
    limits = FreeTierLimits(rpm=15, tpm=250_000, rpd=rpd, min_interval_s=4.5,
                            checked="t", source="t")
    return QuotaGuard(limits, tmp_path / "quota.json",
                      clock=lambda: datetime(2026, 10, 27, 12, tzinfo=UTC),
                      sleep=lambda s: None)


def calls(*texts: str) -> list[PlannedCall]:
    return [PlannedCall(Role.extraction_text, PROMPT, [TextPart(t)], Reply) for t in texts]


def test_preflight_counts_only_uncached(tmp_path: Path) -> None:
    adapter = CachingFake(cached={"cv_01", "cv_03"})
    needed = preflight(calls("cv_01", "cv_02", "cv_03", "cv_04"), adapter, guard(tmp_path, 500))
    assert needed == 2
    assert adapter.cache_checks == 4 and adapter.calls == []


def test_preflight_refuses_before_any_call_when_over_quota(tmp_path: Path) -> None:
    quota = guard(tmp_path, rpd=5)  # 3 left after the guard's safety margin
    left = quota.remaining_today()
    adapter = CachingFake(cached=set())
    with pytest.raises(StageError) as exc:
        preflight(calls("a", "b", "c", "d"), adapter, quota)
    err = exc.value
    assert err.code == "eval_exceeds_quota" and err.category is ErrorCategory.provider
    assert not err.retryable
    assert err.detail == f"Needs 4 uncached calls, {left} left today."
    assert adapter.calls == [] and quota.remaining_today() == left


def test_preflight_allows_exactly_the_remaining_quota(tmp_path: Path) -> None:
    quota = guard(tmp_path, rpd=5)
    left = quota.remaining_today()
    texts = [f"cv_{i}" for i in range(left)]
    assert preflight(calls(*texts), CachingFake(cached=set()), quota) == left
