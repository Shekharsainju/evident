"""Test double for ModelAdapter: replays queued JSON replies (or raises queued
exceptions) per role."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from evident.models.adapter import ModelResult, Part, T
from evident.prompts import Prompt
from evident.settings import Role


@dataclass(frozen=True)
class RecordedCall:
    role: Role
    prompt: Prompt
    parts: list[Part]


class FakeAdapter:
    def __init__(self, responses: Mapping[Role, Sequence[str | Exception]]) -> None:
        self.responses = {role: list(replies) for role, replies in responses.items()}
        self.calls: list[RecordedCall] = []

    def is_cached(self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]) -> bool:
        return False

    def generate_json(
        self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]
    ) -> ModelResult[T]:
        self.calls.append(RecordedCall(role, prompt, list(parts)))
        queue = self.responses.get(role)
        if not queue:
            raise AssertionError(f"FakeAdapter has no reply queued for role {role.value}")
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ModelResult(
            value=schema.model_validate_json(reply),
            model_id=f"fake-{role.value}",
            prompt=prompt.name,
            prompt_version=prompt.version,
            cached=False,
            input_tokens=0,
            output_tokens=0,
            est_cost_usd=0.0,
            latency_ms=0,
        )
