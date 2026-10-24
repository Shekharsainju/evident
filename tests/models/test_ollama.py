from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from evident.errors import ErrorCategory, StageError
from evident.models.adapter import ImagePart, Part, TextPart
from evident.models.cache import DiskCache
from evident.models.ollama import OllamaAdapter
from evident.prompts import load_prompt, render_prompt
from evident.settings import Role, Settings, load_model_config

TAG = "qwen3:4b-instruct-2507-q4_K_M"
PINNED = "0edcdef34593"


class Verdict(BaseModel):
    verdict: str


class Stub:
    def __init__(self) -> None:
        self.digest = PINNED + "eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0"
        self.replies: list[str] = []
        self.chat_bodies: list[dict[str, Any]] = []
        self.resident = True
        self.paths: list[str] = []


@pytest.fixture
def stub() -> Iterator[tuple[Stub, str]]:
    state = Stub()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            state.paths.append(self.path)
            if self.path == "/api/ps":
                self._send({"models": [{"name": TAG}] if state.resident else []})
                return
            assert self.path == "/api/tags"
            self._send({"models": [{"name": TAG, "digest": state.digest}]})

        def do_POST(self) -> None:
            state.paths.append(self.path)
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            if self.path == "/api/generate":
                state.resident = True
                self._send({"done": True})
                return
            assert self.path == "/api/chat"
            state.chat_bodies.append(body)
            content = state.replies.pop(0)
            self._send(
                {"message": {"role": "assistant", "content": content},
                 "prompt_eval_count": 300, "eval_count": 40}
            )

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def make(tmp_path: Path, url: str, use_cache: bool = True) -> OllamaAdapter:
    settings = Settings(_env_file=None, gemini_api_key=SecretStr("x"), ollama_url=url)
    return OllamaAdapter(
        settings, load_model_config(), DiskCache(tmp_path / "cache"), use_cache=use_cache
    )


PROMPT = load_prompt("judge")
TEXT = render_prompt(PROMPT, cited_facts_with_spans="e", claim_text="c")
PARTS: list[Part] = [TextPart(TEXT)]


def test_judge_request_uses_schema_format_and_temperature_0(
    tmp_path: Path, stub: tuple[Stub, str]
) -> None:
    state, url = stub
    state.replies = ['{"verdict": "supported"}']
    result = make(tmp_path, url).generate_json(Role.judge, PROMPT, PARTS, Verdict)
    assert result.value.verdict == "supported"
    assert result.model_id == TAG
    assert (result.input_tokens, result.output_tokens, result.est_cost_usd) == (300, 40, 0.0)
    body = state.chat_bodies[0]
    assert body["model"] == TAG
    assert body["stream"] is False
    assert body["format"] == Verdict.model_json_schema()
    assert body["options"]["temperature"] == 0
    assert body["messages"][-1]["content"] == TEXT


def test_cached_reply_skips_server(tmp_path: Path, stub: tuple[Stub, str]) -> None:
    state, url = stub
    state.replies = ['{"verdict": "supported"}']
    adapter = make(tmp_path, url)
    adapter.generate_json(Role.judge, PROMPT, PARTS, Verdict)
    assert adapter.generate_json(Role.judge, PROMPT, PARTS, Verdict).cached
    assert len(state.chat_bodies) == 1


def test_use_cache_false_always_calls_server(tmp_path: Path, stub: tuple[Stub, str]) -> None:
    state, url = stub
    state.replies = ['{"verdict": "a"}', '{"verdict": "b"}']
    adapter = make(tmp_path, url, use_cache=False)
    adapter.generate_json(Role.judge, PROMPT, PARTS, Verdict)
    assert adapter.generate_json(Role.judge, PROMPT, PARTS, Verdict).value.verdict == "b"


def test_digest_mismatch_refuses(tmp_path: Path, stub: tuple[Stub, str]) -> None:
    state, url = stub
    state.digest = "ffffffffffff" + "0" * 52
    state.replies = ['{"verdict": "supported"}']
    with pytest.raises(StageError) as e:
        make(tmp_path, url).generate_json(Role.judge, PROMPT, PARTS, Verdict)
    assert e.value.code == "judge_model_mismatch"
    assert state.chat_bodies == []


def test_server_down_raises_judge_unavailable_without_retry(tmp_path: Path) -> None:
    with pytest.raises(StageError) as e:
        make(tmp_path, "http://127.0.0.1:9").generate_json(Role.judge, PROMPT, PARTS, Verdict)
    assert e.value.code == "judge_unavailable"
    assert e.value.category is ErrorCategory.provider and not e.value.retryable


def test_invalid_json_retried_once(tmp_path: Path, stub: tuple[Stub, str]) -> None:
    state, url = stub
    state.replies = ["nope", '{"verdict": "overstated"}']
    result = make(tmp_path, url).generate_json(Role.judge, PROMPT, PARTS, Verdict)
    assert result.value.verdict == "overstated"
    assert len(state.chat_bodies) == 2


def test_model_loaded_before_judging_when_not_resident(
    tmp_path: Path, stub: tuple[Stub, str]
) -> None:
    # Loading takes about 20 s on the owner's GPU; it must not eat the 30 s judgement timeout.
    state, url = stub
    state.resident = False
    state.replies = ['{"verdict": "supported"}']
    make(tmp_path, url).generate_json(Role.judge, PROMPT, PARTS, Verdict)
    assert state.paths.index("/api/generate") < state.paths.index("/api/chat")


def test_no_load_request_when_model_resident(tmp_path: Path, stub: tuple[Stub, str]) -> None:
    state, url = stub
    state.replies = ['{"verdict": "supported"}']
    make(tmp_path, url).generate_json(Role.judge, PROMPT, PARTS, Verdict)
    assert "/api/generate" not in state.paths


def test_image_part_refused(tmp_path: Path, stub: tuple[Stub, str]) -> None:
    _, url = stub
    with pytest.raises(StageError) as e:
        make(tmp_path, url).generate_json(
            Role.judge, PROMPT, [ImagePart(b"x", "image/png"), *PARTS], Verdict
        )
    assert e.value.category is ErrorCategory.internal
