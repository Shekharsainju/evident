from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from pydantic import SecretStr

import evident.runs
import scripts.build_examples as module
from evident.settings import Role, Settings
from scripts.build_examples import EXPECTED_FILES, build_examples
from tests.fakes import FakeAdapter
from tests.validation.support import judge_reply
from tests.web.test_flow import (
    GOOD,
    INFLATED,
    coverage_reply,
    plan_reply,
    requirements_reply,
    vision_reply,
)


@pytest.fixture(autouse=True)
def stable_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = itertools.count(1)
    monkeypatch.setattr(evident.runs, "_new_id", lambda prefix: f"{prefix}_{next(counter)}")


def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, gemini_api_key=SecretStr("x"), data_dir=tmp_path / "var")


def adapter(*judge: str) -> FakeAdapter:
    # start() numbers the screenshot (1), then the target (2), then the CV (3). Fact 1 is the
    # project in vision_reply.
    fact_id = "doc_3_f01"
    return FakeAdapter({
        Role.extraction_vision: [vision_reply()],
        Role.requirements: [requirements_reply()],
        Role.coverage: [coverage_reply(fact_id)],
        Role.planner: [plan_reply(fact_id, GOOD, INFLATED), plan_reply(fact_id, GOOD, INFLATED)],
        Role.judge: list(judge),
    })


def good_adapter() -> FakeAdapter:
    return adapter(judge_reply(confidence=0.95), judge_reply("overstated", 0.9, "production"),
                   judge_reply("overstated", 0.95, "production"))


def test_examples_folder_complete(tmp_path: Path) -> None:
    out = tmp_path / "examples"
    build_examples(out, adapter=good_adapter(), settings=settings(tmp_path))

    assert sorted(p.name for p in out.iterdir()) == sorted(EXPECTED_FILES)
    assert all((out / name).stat().st_size > 0 for name in EXPECTED_FILES)
    assert json.loads((out / "facts.json").read_text(encoding="utf-8"))
    assert json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    assert "| strong |" in (out / "coverage.md").read_text(encoding="utf-8")
    report = json.loads((out / "validation_report.json").read_text(encoding="utf-8"))
    assert report["results"]
    assert (out / "input_cv_photo.jpg").read_bytes().startswith(b"\xff\xd8\xff")
    assert (out / "job_ad_screenshot.png").read_bytes().startswith(b"\x89PNG")
    assert (out / "profile.pdf").read_bytes().startswith(b"%PDF-")
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "synthetic" in readme and "confirmed automatically" in readme
    for name in EXPECTED_FILES:
        assert name == "README.md" or f"`{name}`" in readme


def test_inflated_claim_records_outcome_rule_and_phrase(tmp_path: Path) -> None:
    out = tmp_path / "examples"
    build_examples(out, adapter=good_adapter(), settings=settings(tmp_path))
    text = (out / "inflated_claim_rejected.md").read_text(encoding="utf-8")
    assert "**Outcome:** rejected" in text
    assert "| Rule | Phrase |" in text
    assert "| ownership |" in text
    assert "production" in text


def test_blocked_output_stops_the_build_and_keeps_old_examples(tmp_path: Path) -> None:
    out = tmp_path / "examples"
    out.mkdir()
    (out / "profile.pdf").write_text("old", encoding="utf-8")
    fake = adapter(judge_reply("overstated", 0.9, "production"),
                   judge_reply("overstated", 0.9, "production"))

    with pytest.raises(SystemExit, match="post-render"):
        build_examples(out, adapter=fake, settings=settings(tmp_path))

    assert (out / "profile.pdf").read_text(encoding="utf-8") == "old"
    assert [p.name for p in out.iterdir()] == ["profile.pdf"]


def test_inflated_claim_that_is_not_rejected_stops_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "inflated_text", lambda _title: GOOD)
    out = tmp_path / "examples"
    fake = adapter(judge_reply(confidence=0.95), judge_reply("overstated", 0.9, "production"),
                   judge_reply(confidence=0.95))

    with pytest.raises(SystemExit, match="not rejected"):
        build_examples(out, adapter=fake, settings=settings(tmp_path))

    assert not out.exists()


def test_failed_run_stops_before_writing(tmp_path: Path) -> None:
    out = tmp_path / "examples"
    fake = FakeAdapter({Role.extraction_vision: ['{"facts": "not a list"}'] * 3})
    with pytest.raises(SystemExit, match="reading the CV failed"):
        build_examples(out, adapter=fake, settings=settings(tmp_path))
    assert not out.exists()


def test_missing_key_stops_with_a_clear_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    plain = Settings(_env_file=None, data_dir=tmp_path / "var")
    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        build_examples(tmp_path / "examples", settings=plain)
    assert not (tmp_path / "examples").exists()
