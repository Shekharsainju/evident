from __future__ import annotations

from typing import Any

from pydantic import SecretStr

from evident.models.gemini import GeminiAdapter
from evident.models.ollama import OllamaAdapter
from evident.models.router import RoutingAdapter, build_adapter
from evident.settings import Role, Settings, load_model_config


def settings(tmp_path: Any, demo: bool) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key=SecretStr("test-not-a-key"),
        demo=demo,
        cache_dir=tmp_path / "cache",
        quota_dir=tmp_path / "quota",
    )


def test_roles_route_by_provider(tmp_path: Any) -> None:
    router = build_adapter(settings(tmp_path, demo=False), load_model_config())
    assert isinstance(router, RoutingAdapter)
    assert isinstance(router.adapter_for(Role.judge), OllamaAdapter)
    for role in set(Role) - {Role.judge}:
        adapter = router.adapter_for(role)
        assert isinstance(adapter, GeminiAdapter) and not adapter.cache_only


def test_demo_mode_makes_gemini_roles_cache_only(tmp_path: Any) -> None:
    router = build_adapter(settings(tmp_path, demo=True), load_model_config())
    for role in set(Role) - {Role.judge}:
        adapter = router.adapter_for(role)
        assert isinstance(adapter, GeminiAdapter) and adapter.cache_only


def test_demo_mode_leaves_judge_role_live_even_on_gemini_fallback(tmp_path: Any) -> None:
    cfg = load_model_config()
    fallback = cfg.roles[Role.extraction_text]
    cfg.roles[Role.judge] = type(fallback)(
        provider=fallback.provider, model=fallback.model, timeout_s=30, max_output_tokens=512
    )
    router = build_adapter(settings(tmp_path, demo=True), cfg)
    judge = router.adapter_for(Role.judge)
    assert isinstance(judge, GeminiAdapter) and not judge.cache_only


def test_gemini_roles_share_one_quota_guard_per_model(tmp_path: Any) -> None:
    router = build_adapter(settings(tmp_path, demo=False), load_model_config())
    a = router.adapter_for(Role.planner)
    b = router.adapter_for(Role.coverage)
    assert isinstance(a, GeminiAdapter) and isinstance(b, GeminiAdapter)
    assert a.guards["gemini-3.5-flash-lite"] is b.guards["gemini-3.5-flash-lite"]
