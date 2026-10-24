"""The one interface every model call goes through (design: Models and fallbacks)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from evident.errors import ErrorCategory, StageError
from evident.prompts import Prompt
from evident.settings import Role

T = TypeVar("T", bound=BaseModel)

# Pydantic errors quote the bad input; cap it so a long reply doesn't double the retry prompt.
MAX_ERROR_CHARS = 2000
RETRY_NOTE = (
    "Your previous reply was not valid JSON for the schema. Error:\n{error}\n"
    "Reply again with JSON only, matching the schema."
)


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    data: bytes
    mime_type: str


Part = TextPart | ImagePart


@dataclass(frozen=True)
class ModelResult[T: BaseModel]:
    value: T
    model_id: str
    prompt: str
    prompt_version: str
    cached: bool
    input_tokens: int
    output_tokens: int
    est_cost_usd: float
    latency_ms: int


class ModelAdapter(Protocol):
    def generate_json(
        self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]
    ) -> ModelResult[T]: ...

    def is_cached(self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]) -> bool:
        ...


@dataclass(frozen=True)
class RawReply:
    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class JsonReply[T: BaseModel]:
    value: T
    text: str
    input_tokens: int
    output_tokens: int


def complete_json[T: BaseModel](
    send: Callable[[list[Part]], RawReply], parts: list[Part], schema: type[T]
) -> JsonReply[T]:
    """Ask once, retry once with the validation error, then fail the stage."""
    attempt_parts = list(parts)
    tokens_in = tokens_out = 0
    for attempt in range(2):
        reply = send(attempt_parts)
        tokens_in += reply.input_tokens
        tokens_out += reply.output_tokens
        try:
            value = schema.model_validate_json(reply.text)
        except ValidationError as exc:
            if attempt == 1:
                break
            note = RETRY_NOTE.format(error=str(exc)[:MAX_ERROR_CHARS])
            attempt_parts = [*parts, TextPart(note)]
            continue
        return JsonReply(value=value, text=reply.text, input_tokens=tokens_in,
                         output_tokens=tokens_out)
    raise StageError(
        code="invalid_model_json",
        category=ErrorCategory.internal,
        detail=f"Model reply did not match {schema.__name__} after one retry.",
    )
