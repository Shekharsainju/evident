"""Local free-tier guard: spaces calls and stops before the daily limit (spec 7.3)."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from evident.errors import ErrorCategory, StageError
from evident.settings import FreeTierLimits

# Google resets daily quota at midnight Pacific. A fixed UTC-8 day ends at or after that
# reset all year, so the guard never assumes quota is back early.
PACIFIC_STANDARD = timezone(timedelta(hours=-8))
DAILY_MARGIN = 2
RATE_LIMIT_BLOCK_S = 60.0
WINDOW_S = 60.0


def utc_now() -> datetime:
    return datetime.now(UTC)


class QuotaGuard:
    def __init__(
        self,
        limits: FreeTierLimits | None,
        state_path: Path,
        clock: Callable[[], datetime] = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limits = limits
        self.state_path = state_path
        self.clock = clock
        self.sleep = sleep
        # Background stages share one guard; holding the lock while pacing serialises calls.
        self._lock = threading.Lock()

    def _day(self, now: datetime) -> str:
        return now.astimezone(PACIFIC_STANDARD).date().isoformat()

    def _load(self) -> dict[str, object]:
        if self.state_path.exists():
            data: dict[str, object] = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data
        return {}

    def _save(self, state: dict[str, object]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def _count_today(self, state: dict[str, object], now: datetime) -> int:
        if state.get("day") != self._day(now):
            return 0
        count = state.get("count", 0)
        return count if isinstance(count, int) else 0

    def _usable(self) -> FreeTierLimits:
        lim = self.limits
        if lim is None or lim.rpm <= 0 or lim.rpd <= 0:
            raise StageError(
                code="limits_not_set",
                category=ErrorCategory.internal,
                detail="Free-tier limits are missing in config/models.toml; no uncached calls.",
            )
        return lim

    def remaining_today(self) -> int:
        lim = self._usable()
        with self._lock:
            used = self._count_today(self._load(), self.clock())
        return max(0, lim.rpd - DAILY_MARGIN - used)

    def reserve(self) -> None:
        lim = self._usable()
        with self._lock:
            state = self._load()
            now = self.clock()
            ts = now.timestamp()
            last_429 = state.get("last_429")
            if isinstance(last_429, float | int) and ts - last_429 < RATE_LIMIT_BLOCK_S:
                raise rate_limited_error()
            used = self._count_today(state, now)
            if used >= lim.rpd - DAILY_MARGIN:
                raise StageError(
                    code="daily_quota",
                    category=ErrorCategory.provider,
                    detail=(
                        f"Free-tier daily quota reached ({used}/{lim.rpd}). "
                        "Resets at midnight Pacific."
                    ),
                    retryable=False,
                )
            raw_recent = state.get("recent", [])
            recent = [float(t) for t in raw_recent if isinstance(t, float | int)] if isinstance(
                raw_recent, list
            ) else []
            recent = [t for t in recent if ts - t < WINDOW_S]
            wait = 0.0
            last = state.get("last_start")
            if isinstance(last, float | int):
                wait = max(wait, float(last) + lim.min_interval_s - ts)
            if len(recent) >= lim.rpm:
                wait = max(wait, recent[-lim.rpm] + WINDOW_S - ts)
            if wait > 0:
                self.sleep(wait)
                ts = max(self.clock().timestamp(), ts + wait)
            recent = [t for t in recent if ts - t < WINDOW_S] + [ts]
            self._save(
                {"day": self._day(now), "count": used + 1, "last_start": ts, "recent": recent,
                 "last_429": last_429}
            )

    def record_429(self) -> None:
        with self._lock:
            state = self._load()
            state["last_429"] = self.clock().timestamp()
            self._save(state)


def rate_limited_error() -> StageError:
    return StageError(
        code="rate_limited",
        category=ErrorCategory.provider,
        detail="Gemini returned 429 (rate or daily limit). Not retried; try again later.",
        retryable=False,
    )
