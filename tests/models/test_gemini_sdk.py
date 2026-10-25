"""The real google-genai SDK against a local fake server: counts what actually goes on the wire.

Found 2026-10-25: with the interactions API, HttpRetryOptions(attempts=0) still sent 2
requests per 429, because the SDK rewrites attempts 0 -> 1 and one layer reads it as a retry
count. These tests pin the request count end to end, not just the config value.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from evident.errors import StageError
from evident.models.adapter import TextPart
from evident.models.cache import DiskCache
from evident.models.gemini import GeminiAdapter, make_client
from evident.models.quota import QuotaGuard
from evident.prompts import Prompt
from evident.settings import FreeTierLimits, Role, Settings, load_model_config

MODEL = "gemini-3.5-flash-lite"
OK_BODY = (  # a minimal generateContent reply
    b'{"candidates": [{"content": {"role": "model",'
    b' "parts": [{"text": "{\\"answer\\": \\"ok\\"}"}]}}],'
    b' "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3}}'
)


class Echo(BaseModel):
    answer: str


@pytest.fixture
def server() -> Iterator[tuple[list[int], list[str], str]]:
    statuses: list[int] = []  # queued replies; when empty, keep answering with the last one
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            # Read the body: closing with unread data resets the socket on Windows.
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            hits.append(self.path)
            status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
            body = OK_BODY if status == 200 else (
                b'{"error": {"code": %d, "message": "stub", "status": "STUB"}}' % status
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield statuses, hits, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def adapter_for(tmp_path: Path, url: str) -> tuple[GeminiAdapter, QuotaGuard]:
    limits = FreeTierLimits(rpm=1000, tpm=10**6, rpd=500, min_interval_s=0.0, checked="t",
                            source="t")
    guard = QuotaGuard(limits, tmp_path / "q.json",
                       clock=lambda: datetime(2026, 10, 25, 12, tzinfo=UTC), sleep=lambda s: None)
    adapter = GeminiAdapter(
        Settings(_env_file=None, gemini_api_key=SecretStr("test-not-a-key")),
        load_model_config(),
        DiskCache(tmp_path / "cache"),
        {MODEL: guard},
        client=make_client("test-not-a-key", base_url=url),
        sleep=lambda s: None,
    )
    return adapter, guard


PROMPT = Prompt("sdk_test", "v1", "x")
PARTS = [TextPart("hello")]


def test_429_sends_exactly_one_request(tmp_path: Path, server: Any) -> None:
    statuses, hits, url = server
    statuses.append(429)
    adapter, guard = adapter_for(tmp_path, url)
    with pytest.raises(StageError) as e:
        adapter.generate_json(Role.requirements, PROMPT, list(PARTS), Echo)
    assert e.value.code == "rate_limited"
    assert len(hits) == 1
    assert guard.remaining_today() == 500 - 2 - 1


def test_503_sends_three_requests_all_counted(tmp_path: Path, server: Any) -> None:
    statuses, hits, url = server
    statuses.append(503)
    adapter, guard = adapter_for(tmp_path, url)
    with pytest.raises(StageError) as e:
        adapter.generate_json(Role.requirements, PROMPT, list(PARTS), Echo)
    assert e.value.code == "provider_error"
    assert len(hits) == 3
    assert guard.remaining_today() == 500 - 2 - 3


def test_503_then_ok_succeeds_on_second_request(tmp_path: Path, server: Any) -> None:
    statuses, hits, url = server
    statuses.extend([503, 200])
    adapter, _ = adapter_for(tmp_path, url)
    result = adapter.generate_json(Role.requirements, PROMPT, list(PARTS), Echo)
    assert result.value.answer == "ok"
    assert len(hits) == 2
