from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from evident.errors import ErrorCategory, StageError
from evident.models.quota import QuotaGuard
from evident.settings import FreeTierLimits


def limits(rpm: int = 100, rpd: int = 10, min_interval_s: float = 0.0) -> FreeTierLimits:
    return FreeTierLimits(
        rpm=rpm, tpm=10**6, rpd=rpd, min_interval_s=min_interval_s, checked="x", source="y"
    )


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


NOON = datetime(2026, 10, 25, 12, tzinfo=UTC)


def fixed() -> datetime:
    return NOON


def test_limits_not_set_refuses(tmp_path: Path) -> None:
    for lim in (None, limits(rpm=0), limits(rpd=0)):
        g = QuotaGuard(lim, tmp_path / "q.json", clock=fixed, sleep=lambda s: None)
        with pytest.raises(StageError) as e:
            g.reserve()
        assert e.value.code == "limits_not_set"
        assert e.value.category is ErrorCategory.internal


def test_daily_quota_stops_with_margin(tmp_path: Path) -> None:
    g = QuotaGuard(limits(rpd=10), tmp_path / "q.json", clock=fixed, sleep=lambda s: None)
    for _ in range(8):
        g.reserve()
    with pytest.raises(StageError) as e:
        g.reserve()
    assert e.value.code == "daily_quota" and not e.value.retryable
    assert e.value.category is ErrorCategory.provider
    assert "8/10" in e.value.detail


def test_flash_lite_guard_stops_at_498_of_500(tmp_path: Path) -> None:
    g = QuotaGuard(
        limits(rpm=10**6, rpd=500), tmp_path / "q.json", clock=fixed, sleep=lambda s: None
    )
    for _ in range(498):
        g.reserve()
    assert g.remaining_today() == 0
    with pytest.raises(StageError):
        g.reserve()


def test_day_rolls_over_at_utc_minus_8(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 10, 26, 7, 59, tzinfo=UTC))
    g = QuotaGuard(limits(rpd=3), tmp_path / "q.json", clock=clock, sleep=lambda s: None)
    g.reserve()
    assert g.remaining_today() == 0
    clock.now = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)
    assert g.remaining_today() == 1
    g.reserve()


def test_rpm_pacing_sleeps_instead_of_failing(tmp_path: Path) -> None:
    clock = Clock(NOON)
    waits: list[float] = []

    def sleep(s: float) -> None:
        waits.append(s)
        clock.now += timedelta(seconds=s)

    g = QuotaGuard(limits(rpm=2, rpd=100), tmp_path / "q.json", clock=clock, sleep=sleep)
    g.reserve()
    clock.now += timedelta(seconds=10)
    g.reserve()
    g.reserve()  # third call within the minute waits until the first is 60 s old
    assert waits == [pytest.approx(50.0)]


def test_min_interval_spaces_calls_4_5_s(tmp_path: Path) -> None:
    clock = Clock(NOON)
    waits: list[float] = []

    def sleep(s: float) -> None:
        waits.append(s)
        clock.now += timedelta(seconds=s)

    g = QuotaGuard(
        limits(rpm=15, rpd=500, min_interval_s=4.5), tmp_path / "q.json", clock=clock, sleep=sleep
    )
    g.reserve()
    clock.now += timedelta(seconds=1)
    g.reserve()
    assert waits == [pytest.approx(3.5)]


def test_state_survives_restart(tmp_path: Path) -> None:
    clock = Clock(NOON)
    waits: list[float] = []
    lim = limits(rpd=10, min_interval_s=4.5)
    QuotaGuard(lim, tmp_path / "q.json", clock=clock, sleep=lambda s: None).reserve()
    clock.now += timedelta(seconds=2)
    g2 = QuotaGuard(lim, tmp_path / "q.json", clock=clock, sleep=waits.append)
    assert g2.remaining_today() == 7
    g2.reserve()
    assert waits == [pytest.approx(2.5)]


def test_record_429_blocks_calls_for_a_minute(tmp_path: Path) -> None:
    clock = Clock(NOON)
    g = QuotaGuard(limits(), tmp_path / "q.json", clock=clock, sleep=lambda s: None)
    g.record_429()
    with pytest.raises(StageError) as e:
        g.reserve()
    assert e.value.code == "rate_limited"
    clock.now += timedelta(seconds=61)
    g.reserve()
