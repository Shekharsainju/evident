"""Live smoke checks: 1 Flash-Lite call (counts against free-tier quota) and 1 local judge call.

Run with `uv run pytest -m live tests/models`.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import BaseModel

from evident.models.adapter import ImagePart, TextPart
from evident.models.cache import DiskCache
from evident.models.gemini import GeminiAdapter
from evident.models.ollama import OllamaAdapter
from evident.models.router import build_guards
from evident.prompts import Prompt, render_prompt
from evident.settings import Role, Settings, load_model_config

pytestmark = pytest.mark.live
MODEL = "gemini-3.5-flash-lite"


class ImageText(BaseModel):
    text: str


class Verdict(BaseModel):
    verdict: str
    confidence: float


def synthetic_png() -> bytes:
    img = Image.new("RGB", (480, 120), "white")
    ImageDraw.Draw(img).text((20, 45), "Synthetic test card 4217", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_flash_lite_reads_an_image(tmp_path: Path) -> None:
    settings = Settings()
    config = load_model_config()
    guard = build_guards(settings, config)[MODEL]
    before = guard.remaining_today()
    adapter = GeminiAdapter(settings, config, DiskCache(tmp_path), {MODEL: guard})
    prompt = Prompt("live_smoke", "v1", "Return the text in the image as {\"text\": ...}.")
    result = adapter.generate_json(
        Role.extraction_vision,
        prompt,
        [ImagePart(synthetic_png(), "image/png"), TextPart(prompt.text)],
        ImageText,
    )
    assert "4217" in result.value.text
    assert not result.cached and result.input_tokens > 0
    assert guard.remaining_today() == before - 1




def test_local_judge_answers_with_schema(tmp_path: Path) -> None:
    adapter = OllamaAdapter(Settings(), load_model_config(), DiskCache(tmp_path))
    prompt = Prompt("live_smoke", "v1", "{claim}")
    text = render_prompt(
        prompt,
        claim=(
            'Evidence: "Built a Flask timetable app." Claim: "Built a Flask app." '
            'Reply as {"verdict": "supported|overstated|unsupported", "confidence": 0-1}.'
        ),
    )
    result = adapter.generate_json(Role.judge, prompt, [TextPart(text)], Verdict)
    assert result.value.verdict in {"supported", "overstated", "unsupported"}
    assert result.model_id == "qwen3:4b-instruct-2507-q4_K_M"
