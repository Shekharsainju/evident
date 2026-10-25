"""Evaluation pre-flight against the free-tier daily quota (spec 7.3; P3).

An evaluation run counts the uncached calls it would make before making any of them, so it
never stops halfway through a split because the daily quota ran out.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from evident.errors import ErrorCategory, StageError
from evident.models.adapter import ModelAdapter, Part
from evident.models.quota import QuotaGuard
from evident.prompts import Prompt
from evident.settings import Role


@dataclass(frozen=True)
class PlannedCall:
    role: Role
    prompt: Prompt
    parts: list[Part]
    schema: type[BaseModel]


def preflight(calls: list[PlannedCall], adapter: ModelAdapter, quota: QuotaGuard) -> int:
    """Returns how many of `calls` are not cached, or refuses if that exceeds today's quota.

    One guard covers one Gemini model, so pass only the calls that model will serve. The
    local judge has no quota and its calls don't belong here.
    """
    needed = sum(1 for c in calls if not adapter.is_cached(c.role, c.prompt, c.parts, c.schema))
    left = quota.remaining_today()
    if needed > left:
        raise StageError(code="eval_exceeds_quota", category=ErrorCategory.provider,
                         retryable=False,
                         detail=f"Needs {needed} uncached calls, {left} left today.")
    return needed
