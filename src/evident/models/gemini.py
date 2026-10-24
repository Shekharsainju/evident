"""Gemini through google-genai's interactions API, free tier only (P3).

SDK facts checked against google-genai 2.33.0 on 2026-10-25:
- `client.interactions.create(model, input, response_format, response_mime_type,
  generation_config, store, timeout)`; `timeout` is in seconds.
- Image input is a content item `{"type": "image", "data": <base64>, "mime_type": ...}`.
- JSON output: `response_format={"type": "text", "mime_type": "application/json",
  "schema": ...}` plus `response_mime_type="application/json"`.
- Reply text is `interaction.output_text`; usage is `interaction.usage.total_input_tokens`,
  `total_output_tokens` and `total_thought_tokens` (thinking is billed as output).
- HTTP errors carry `status_code`. The SDK retries 408, 409, 429 and 5xx by default, so the
  client is built with `HttpRetryOptions(attempts=0)`.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx
from google import genai
from google.genai import types

from evident.errors import ErrorCategory, StageError
from evident.models.adapter import (
    ModelResult,
    Part,
    RawReply,
    T,
    TextPart,
    complete_json,
)
from evident.models.cache import CachedReply, DiskCache, cache_key
from evident.models.costs import estimate_cost
from evident.models.quota import QuotaGuard, rate_limited_error
from evident.prompts import Prompt
from evident.settings import ModelConfig, Role, Settings

log = logging.getLogger("evident.models")

HTTP_OPTIONS = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=0))


def make_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key, http_options=HTTP_OPTIONS)


def _content(part: Part) -> dict[str, str]:
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text}
    return {
        "type": "image",
        "data": base64.b64encode(part.data).decode("ascii"),
        "mime_type": part.mime_type,
    }


class GeminiAdapter:
    def __init__(
        self,
        settings: Settings,
        config: ModelConfig,
        cache: DiskCache,
        guards: dict[str, QuotaGuard],
        cache_only: bool = False,
        client: Any | None = None,
    ) -> None:
        self.settings = settings
        self.config = config
        self.cache = cache
        self.guards = guards
        self.cache_only = cache_only
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = make_client(self.settings.gemini_api_key.get_secret_value())
        return self._client

    def is_cached(self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]) -> bool:
        model = self.config.roles[role].model
        return self.cache.get(cache_key(model, prompt, parts, schema)) is not None

    def generate_json(
        self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]
    ) -> ModelResult[T]:
        rc = self.config.roles[role]
        model = rc.model
        key = cache_key(model, prompt, parts, schema)
        started = time.monotonic()

        hit = self.cache.get(key)
        if hit is not None:
            cached = CachedReply.loads(hit)
            return self._result(role, prompt, schema.model_validate_json(cached.text), model,
                                True, cached.input_tokens, cached.output_tokens, started)
        if self.cache_only:
            raise StageError(
                code="not_recorded",
                category=ErrorCategory.internal,
                detail="This call is not in the recorded run.",
            )
        guard = self.guards.get(model)
        if guard is None:
            raise StageError(
                code="limits_not_set",
                category=ErrorCategory.internal,
                detail=f"No free-tier limits configured for {model}.",
            )

        def send(attempt_parts: list[Part]) -> RawReply:
            guard.reserve()
            try:
                interaction = self._get_client().interactions.create(
                    model=model,
                    input=[_content(p) for p in attempt_parts],
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": schema.model_json_schema(),
                    },
                    response_mime_type="application/json",
                    generation_config={"max_output_tokens": rc.max_output_tokens,
                                       "temperature": 0.0},
                    store=False,
                    timeout=rc.timeout_s,
                )
            except httpx.TimeoutException as exc:
                raise StageError(
                    code="provider_timeout",
                    category=ErrorCategory.provider,
                    detail=f"{model} did not reply within {rc.timeout_s} s.",
                ) from exc
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status == 429:
                    guard.record_429()
                    raise rate_limited_error() from exc
                if status is not None or isinstance(exc, httpx.HTTPError):
                    raise StageError(
                        code="provider_error",
                        category=ErrorCategory.provider,
                        detail=f"{model} request failed (status {status}).",
                    ) from exc
                raise
            usage = getattr(interaction, "usage", None)
            tokens_in = getattr(usage, "total_input_tokens", None) or 0
            tokens_out = (getattr(usage, "total_output_tokens", None) or 0) + (
                getattr(usage, "total_thought_tokens", None) or 0
            )
            return RawReply(interaction.output_text or "", tokens_in, tokens_out)

        reply = complete_json(send, parts, schema)
        self.cache.put(key, CachedReply(reply.text, reply.input_tokens,
                                        reply.output_tokens).dumps())
        result = self._result(role, prompt, reply.value, model, False, reply.input_tokens,
                              reply.output_tokens, started)
        log.info(
            "model call role=%s model=%s prompt=%s/%s in=%d out=%d est_usd=%.6f ms=%d "
            "cached=%s remaining_today=%d",
            role.value, model, prompt.name, prompt.version, result.input_tokens,
            result.output_tokens, result.est_cost_usd, result.latency_ms, False,
            guard.remaining_today(),
        )
        return result

    def _result(
        self, role: Role, prompt: Prompt, value: T, model: str, cached: bool,
        tokens_in: int, tokens_out: int, started: float,
    ) -> ModelResult[T]:
        return ModelResult(
            value=value,
            model_id=model,
            prompt=prompt.name,
            prompt_version=prompt.version,
            cached=cached,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            est_cost_usd=estimate_cost(self.config.prices.get(model), tokens_in, tokens_out),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
