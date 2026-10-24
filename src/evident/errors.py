"""Error categories from the design: they decide whether a stage may be retried."""

from __future__ import annotations

from enum import StrEnum


class ErrorCategory(StrEnum):
    validation = "validation"
    input = "input"
    provider = "provider"
    internal = "internal"


class StageError(Exception):
    def __init__(
        self, code: str, category: ErrorCategory, detail: str = "", retryable: bool = False
    ) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.category = category
        self.detail = detail
        self.retryable = retryable
