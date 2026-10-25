"""Gemini through google-genai's generate_content, free tier only (P3).

SDK facts checked against google-genai 2.33.0 on 2026-10-25:
- `client.models.generate_content(model, contents, config)`. Images go in as
  `types.Part.from_bytes`; `GenerateContentConfig.response_json_schema` with
  `response_mime_type="application/json"` constrains the reply; `http_options.timeout` is in
  milliseconds.
- Reply text is `response.text`; usage is `usage_metadata.prompt_token_count`,
  `candidates_token_count` and `thoughts_token_count` (thinking is billed as output).
- HTTP errors are `errors.ClientError` (4xx) and `errors.ServerError` (5xx), with `.code`.
- The SDK retries by default. `HttpRetryOptions(attempts=1)` means one total attempt for
  generate_content; a local fake server confirms one request per 429 (tests/models/
  test_gemini_sdk.py). The interactions API was dropped because no public option stops its
  hidden retry.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from google import genai
from google.genai import errors, types

from evident.errors import ErrorCategory, StageError
from evident.models.adapter import ModelResult, Part, RawReply, T, TextPart, complete_json
from evident.models.cache import CachedReply, DiskCache, cache_key
from evident.models.costs import estimate_cost
from evident.models.quota import QuotaGuard, rate_limited_error
from evident.prompts import Prompt
from evident.settings import ModelConfig, Role, Settings

log = logging.getLogger("evident.models")

HTTP_OPTIONS = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
# Bounded retry for transient provider errors (invariants section 3: max 3 attempts).
# Model calls in the slice are idempotent: same inputs, cached reply, no side effects.
MAX_ATTEMPTS = 3
BACKOFF_S = (2.0, 4.0)


def make_client(api_key: str, base_url: str | None = None) -> genai.Client:
    options = HTTP_OPTIONS
    if base_url is not None:
        options = HTTP_OPTIONS.model_copy(update={"base_url": base_url})
    return genai.Client(api_key=api_key, http_options=options)


def _content(part: Part) -> types.Part:
    if isinstance(part, TextPart):
        return types.Part.from_text(text=part.text)
    return types.Part.from_bytes(data=part.data, mime_type=part.mime_type)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, errors.ServerError):
        return True
    if isinstance(exc, errors.ClientError):
        return exc.code == 408
    return isinstance(exc, httpx.TimeoutException | httpx.TransportError)


class GeminiAdapter:
    def __init__(
        self,
        settings: Settings,
        config: ModelConfig,
        cache: DiskCache,
        guards: dict[str, QuotaGuard],
        cache_only: bool = False,
        client: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.config = config
        self.cache = cache
        self.guards = guards
        self.cache_only = cache_only
        self._client = client
        self._sleep = sleep

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
            return self._result(prompt, schema.model_validate_json(cached.text), model, True,
                                cached.input_tokens, cached.output_tokens, started)
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
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
            max_output_tokens=rc.max_output_tokens,
            temperature=0.0,
            http_options=types.HttpOptions(timeout=rc.timeout_s * 1000),
        )

        def call_once(contents: list[types.Part]) -> Any:
            # Every request Google sees passes the guard first, retries included.
            guard.reserve()
            return self._get_client().models.generate_content(
                model=model, contents=contents, config=config
            )

        def send(attempt_parts: list[Part]) -> RawReply:
            contents = [_content(p) for p in attempt_parts]
            for attempt in range(MAX_ATTEMPTS):
                try:
                    response = call_once(contents)
                    break
                except Exception as exc:
                    if isinstance(exc, errors.APIError) and exc.code == 429:
                        guard.record_429()
                        raise rate_limited_error() from exc
                    if not isinstance(exc, errors.APIError | httpx.HTTPError):
                        raise
                    if not _is_transient(exc) or attempt == MAX_ATTEMPTS - 1:
                        code = exc.code if isinstance(exc, errors.APIError) else None
                        raise StageError(
                            code="provider_error",
                            category=ErrorCategory.provider,
                            detail=f"{model} request failed (status {code}, "
                            f"attempt {attempt + 1} of {MAX_ATTEMPTS}).",
                        ) from exc
                    self._sleep(BACKOFF_S[attempt])
            usage = getattr(response, "usage_metadata", None)
            tokens_in = getattr(usage, "prompt_token_count", None) or 0
            tokens_out = (getattr(usage, "candidates_token_count", None) or 0) + (
                getattr(usage, "thoughts_token_count", None) or 0
            )
            return RawReply(response.text or "", tokens_in, tokens_out)

        reply = complete_json(send, parts, schema)
        self.cache.put(key, CachedReply(reply.text, reply.input_tokens,
                                        reply.output_tokens).dumps())
        result = self._result(prompt, reply.value, model, False, reply.input_tokens,
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
        self, prompt: Prompt, value: T, model: str, cached: bool,
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
