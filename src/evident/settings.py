"""Runtime settings and the model configuration in config/models.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_OWNER_ID = "local-demo"


class Role(StrEnum):
    extraction_text = "extraction_text"
    extraction_vision = "extraction_vision"
    requirements = "requirements"
    coverage = "coverage"
    planner = "planner"
    judge = "judge"


class Provider(StrEnum):
    gemini = "gemini"
    ollama = "ollama"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: SecretStr = SecretStr("")
    ollama_url: str = "http://127.0.0.1:11434"
    demo: bool = Field(default=False, validation_alias=AliasChoices("EVIDENT_DEMO", "demo"))
    data_dir: Path = Path("var")
    cache_dir: Path = Path(".cache/models")
    quota_dir: Path = Path(".cache/quota")
    as_of: str = "2026-10"


@dataclass(frozen=True)
class RoleConfig:
    provider: Provider
    model: str
    timeout_s: int
    max_output_tokens: int


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float
    checked: str
    source: str


@dataclass(frozen=True)
class FreeTierLimits:
    rpm: int
    tpm: int
    rpd: int
    min_interval_s: float
    checked: str
    source: str


@dataclass(frozen=True)
class ModelConfig:
    roles: dict[Role, RoleConfig]
    spare: list[str]
    prices: dict[str, Price]
    limits: dict[str, FreeTierLimits]
    ollama_digests: dict[str, str]


def load_model_config(path: Path = Path("config/models.toml")) -> ModelConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    roles = {
        Role(name): RoleConfig(
            provider=Provider(r["provider"]),
            model=str(r["model"]),
            timeout_s=int(r["timeout_s"]),
            max_output_tokens=int(r["max_output_tokens"]),
        )
        for name, r in raw["roles"].items()
    }
    missing = set(Role) - set(roles)
    if missing:
        raise ValueError(f"models.toml has no config for roles: {sorted(missing)}")
    spare = [str(m) for m in raw.get("spare", [])]
    on_spare = sorted(role.value for role, rc in roles.items() if rc.model in spare)
    if on_spare:
        # The spare has 20 calls a day; a role on it would exhaust that in one run.
        raise ValueError(f"roles mapped to a spare model: {on_spare}")
    return ModelConfig(
        roles=roles,
        spare=spare,
        prices={k: Price(**v) for k, v in raw.get("prices", {}).items()},
        limits={k: FreeTierLimits(**v) for k, v in raw.get("limits", {}).items()},
        ollama_digests={str(k): str(v) for k, v in raw.get("ollama_digests", {}).items()},
    )
