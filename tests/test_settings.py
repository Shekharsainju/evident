from pathlib import Path

import pytest

from evident.settings import Provider, Role, Settings, load_model_config

GEMINI_ROLES = set(Role) - {Role.judge}
CONFIG = Path("config/models.toml")


def test_gemini_roles_use_flash_lite() -> None:
    cfg = load_model_config()
    assert set(cfg.roles) == set(Role)
    assert {cfg.roles[r].model for r in GEMINI_ROLES} == {"gemini-3.5-flash-lite"}
    assert {cfg.roles[r].provider for r in GEMINI_ROLES} == {Provider.gemini}
    for role, rc in cfg.roles.items():
        assert rc.timeout_s == (45 if role is Role.extraction_vision else 30)


def test_judge_is_local_and_not_gemini_family() -> None:
    rc = load_model_config().roles[Role.judge]
    assert rc.provider is Provider.ollama
    assert not rc.model.startswith(("gemini", "gemma"))


def test_spare_model_never_mapped_to_a_role(tmp_path: Path) -> None:
    cfg = load_model_config()
    assert "gemini-3.8-flash" in cfg.spare
    assert all(rc.model not in cfg.spare for rc in cfg.roles.values())

    text = CONFIG.read_text(encoding="utf-8")
    planner_block = '[roles.planner]\nprovider = "gemini"\nmodel = "gemini-3.5-flash-lite"'
    assert planner_block in text
    bad = tmp_path / "models.toml"
    bad.write_text(
        text.replace(planner_block, planner_block.replace("3.5-flash-lite", "3.8-flash")),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="spare"):
        load_model_config(bad)


def test_flash_lite_limits_and_spacing() -> None:
    lim = load_model_config().limits["gemini-3.5-flash-lite"]
    assert (lim.rpm, lim.rpd) == (15, 500)
    assert lim.min_interval_s >= 4.5


def test_settings_reads_key_without_exposing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-a-key")
    assert "test-not-a-key" not in repr(Settings())
