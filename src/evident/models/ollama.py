"""Local entailment judge through Ollama's HTTP API (P1), standard library only.

API facts checked against the local Ollama 0.40.10 server on 2026-10-25:
- `GET /api/tags` lists each tag with its full sha256 `digest`.
- `POST /api/chat` with `stream: false` and `format: <JSON schema>` returns
  `message.content`, `prompt_eval_count` and `eval_count`.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from evident.errors import ErrorCategory, StageError
from evident.models.adapter import (
    ImagePart,
    ModelResult,
    Part,
    RawReply,
    T,
    TextPart,
    complete_json,
)
from evident.models.cache import CachedReply, DiskCache, cache_key
from evident.models.costs import estimate_cost
from evident.prompts import Prompt
from evident.settings import ModelConfig, Role, Settings

log = logging.getLogger("evident.models")

CONTEXT_TOKENS = 4096
KEEP_ALIVE = "30m"
# Loading the weights onto the GPU took 20.5 s on the owner's laptop (2026-10-25). Loading is
# not a judgement, so it gets its own timeout instead of eating the 30 s text-call budget.
LOAD_TIMEOUT_S = 120.0
STATUS_TIMEOUT_S = 5.0


def _unavailable(detail: str) -> StageError:
    return StageError(
        code="judge_unavailable", category=ErrorCategory.provider, detail=detail, retryable=False
    )


class OllamaAdapter:
    def __init__(
        self,
        settings: Settings,
        config: ModelConfig,
        cache: DiskCache,
        use_cache: bool = True,
    ) -> None:
        self.base_url = settings.ollama_url.rstrip("/")
        self.config = config
        self.cache = cache
        self.use_cache = use_cache
        self._verified: set[str] = set()

    def _cache_model_id(self, tag: str) -> str:
        # The tag alone can be re-pulled to different weights; the digest pins them.
        return f"{tag}@{self.config.ollama_digests.get(tag, 'unpinned')}"

    def _request(self, method: str, path: str, body: dict[str, Any] | None,
                 timeout: float) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return payload
        except TimeoutError as exc:
            raise _unavailable(f"Ollama did not reply within {timeout} s.") from exc
        except (urllib.error.URLError, ConnectionError, json.JSONDecodeError) as exc:
            raise _unavailable("Ollama is not reachable or returned a bad response.") from exc

    def _verify_digest(self, tag: str, timeout: float) -> None:
        if tag in self._verified:
            return
        pinned = self.config.ollama_digests.get(tag)
        models = self._request("GET", "/api/tags", None, timeout).get("models", [])
        found = next((m for m in models if m.get("name") == tag), None)
        digest = str(found.get("digest", "")) if found else ""
        if not pinned or not digest.startswith(pinned):
            raise StageError(
                code="judge_model_mismatch",
                category=ErrorCategory.internal,
                detail=f"{tag} is missing or not the pinned version {pinned}.",
            )
        self._verified.add(tag)

    def _ensure_loaded(self, tag: str) -> None:
        running = self._request("GET", "/api/ps", None, STATUS_TIMEOUT_S).get("models", [])
        if any(m.get("name") == tag for m in running):
            return
        self._request(
            "POST", "/api/generate",
            {"model": tag, "keep_alive": KEEP_ALIVE, "options": {"num_ctx": CONTEXT_TOKENS}},
            LOAD_TIMEOUT_S,
        )

    def is_cached(self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]) -> bool:
        tag = self.config.roles[role].model
        key = cache_key(self._cache_model_id(tag), prompt, parts, schema)
        return self.use_cache and self.cache.get(key) is not None

    def generate_json(
        self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]
    ) -> ModelResult[T]:
        rc = self.config.roles[role]
        tag = rc.model
        if any(isinstance(p, ImagePart) for p in parts):
            raise StageError(
                code="image_not_supported",
                category=ErrorCategory.internal,
                detail="The local judge takes text only.",
            )
        key = cache_key(self._cache_model_id(tag), prompt, parts, schema)
        started = time.monotonic()
        if self.use_cache and (hit := self.cache.get(key)) is not None:
            cached = CachedReply.loads(hit)
            return self._result(tag, prompt, schema.model_validate_json(cached.text), True,
                                cached.input_tokens, cached.output_tokens, started)

        self._verify_digest(tag, rc.timeout_s)
        self._ensure_loaded(tag)

        def send(attempt_parts: list[Part]) -> RawReply:
            text = "\n\n".join(p.text for p in attempt_parts if isinstance(p, TextPart))
            body = {
                "model": tag,
                "messages": [{"role": "user", "content": text}],
                "stream": False,
                "format": schema.model_json_schema(),
                "options": {"temperature": 0, "num_ctx": CONTEXT_TOKENS,
                            "num_predict": rc.max_output_tokens},
                "keep_alive": KEEP_ALIVE,
            }
            reply = self._request("POST", "/api/chat", body, rc.timeout_s)
            message = reply.get("message") or {}
            return RawReply(
                str(message.get("content", "")),
                int(reply.get("prompt_eval_count", 0)),
                int(reply.get("eval_count", 0)),
            )

        reply = complete_json(send, parts, schema)
        if self.use_cache:
            self.cache.put(key, CachedReply(reply.text, reply.input_tokens,
                                            reply.output_tokens).dumps())
        result = self._result(tag, prompt, reply.value, False, reply.input_tokens,
                              reply.output_tokens, started)
        log.info(
            "model call role=%s model=%s prompt=%s/%s in=%d out=%d ms=%d cached=%s",
            role.value, tag, prompt.name, prompt.version, result.input_tokens,
            result.output_tokens, result.latency_ms, False,
        )
        return result

    def _result(self, tag: str, prompt: Prompt, value: T, cached: bool, tokens_in: int,
                tokens_out: int, started: float) -> ModelResult[T]:
        return ModelResult(
            value=value,
            model_id=tag,
            prompt=prompt.name,
            prompt_version=prompt.version,
            cached=cached,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            est_cost_usd=estimate_cost(self.config.prices.get(tag), tokens_in, tokens_out),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
