"""Sends each role to the adapter its provider names in config/models.toml."""

from __future__ import annotations

from evident.errors import ErrorCategory, StageError
from evident.models.adapter import ModelAdapter, ModelResult, Part, T
from evident.models.cache import DiskCache
from evident.models.gemini import GeminiAdapter
from evident.models.ollama import OllamaAdapter
from evident.models.quota import QuotaGuard
from evident.prompts import Prompt
from evident.settings import ModelConfig, Provider, Role, Settings


class RoutingAdapter:
    def __init__(self, config: ModelConfig, adapters: dict[Role, ModelAdapter]) -> None:
        self.config = config
        self.adapters = adapters

    def adapter_for(self, role: Role) -> ModelAdapter:
        if self.config.roles[role].model in self.config.spare:
            raise StageError(
                code="spare_model_in_role",
                category=ErrorCategory.internal,
                detail="The spare model is never used by a pipeline role.",
            )
        return self.adapters[role]

    def generate_json(
        self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]
    ) -> ModelResult[T]:
        return self.adapter_for(role).generate_json(role, prompt, parts, schema)

    def is_cached(self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]) -> bool:
        return self.adapter_for(role).is_cached(role, prompt, parts, schema)


def build_guards(settings: Settings, config: ModelConfig) -> dict[str, QuotaGuard]:
    return {
        model: QuotaGuard(limits, settings.quota_dir / f"{model}.json")
        for model, limits in config.limits.items()
    }


def build_adapter(settings: Settings, config: ModelConfig) -> RoutingAdapter:
    cache = DiskCache(settings.cache_dir)
    guards = build_guards(settings, config)
    gemini_live = GeminiAdapter(settings, config, cache, guards)
    # Demo mode replays a recorded run: every role except the judge must come from the
    # cache, so the live claim box works whichever provider the judge uses (spec 10.1).
    gemini_replay = (
        GeminiAdapter(settings, config, cache, guards, cache_only=True)
        if settings.demo
        else gemini_live
    )
    ollama = OllamaAdapter(settings, config, cache)
    adapters: dict[Role, ModelAdapter] = {}
    for role, rc in config.roles.items():
        if rc.provider is Provider.ollama:
            adapters[role] = ollama
        elif role is Role.judge:
            adapters[role] = gemini_live
        else:
            adapters[role] = gemini_replay
    return RoutingAdapter(config, adapters)
