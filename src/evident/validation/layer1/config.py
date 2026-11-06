"""Lexicons, aliases and the context every Layer 1 check receives.

Both config files are versioned so a rejection can be traced to the word list that caused it
(design: Deterministic check rules, "Lexicons").
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evident.contracts.enums import FactKind, MetricDirection
from evident.contracts.facts import FactRef, FactVersion
from evident.validation.layer1.normalise import normalise_text

LEXICONS_PATH = Path("config/lexicons.toml")
ALIASES_PATH = Path("config/aliases.toml")


@dataclass(frozen=True)
class Lexicons:
    version: str
    ownership: dict[str, int]
    deployment: dict[str, int]
    metric_keywords: dict[str, str]
    direction_words: dict[str, MetricDirection]
    scale_nouns: set[str]
    quantity_words: dict[str, float]
    aggregate_nouns: dict[str, FactKind]
    seniority_words: set[str]
    credential_words: set[str]
    # Words that may open a sentence without being part of a name (spec 7.2).
    sentence_openers: frozenset[str] = frozenset()
    unit_aliases: dict[str, str] = field(default_factory=dict)

    def unit_family(self, unit: str) -> str:
        """Map a unit spelling to its family name, or return it normalised."""
        key = normalise_text(unit)
        return self.unit_aliases.get(key, key)


@dataclass(frozen=True)
class Aliases:
    version: str
    skills: dict[str, str]
    entities: dict[str, str]

    def canonical_skill(self, text: str) -> str | None:
        return self.skills.get(normalise_text(text))

    def canonical_entity(self, text: str) -> str | None:
        return self.entities.get(normalise_text(text))


def _norm_keys(table: dict[str, Any]) -> dict[str, Any]:
    return {normalise_text(k): v for k, v in table.items()}


def load_lexicons(path: Path = LEXICONS_PATH) -> Lexicons:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    unit_aliases: dict[str, str] = {}
    for family, spellings in raw.get("unit_aliases", {}).items():
        unit_aliases[normalise_text(family)] = family
        for spelling in spellings:
            # "%" normalises to itself; plain words lose nothing.
            unit_aliases[normalise_text(spelling) or spelling] = family
    ownership = {k: int(v) for k, v in _norm_keys(raw["ownership"]).items()}
    deployment = {k: int(v) for k, v in _norm_keys(raw["deployment"]).items()}
    # Ownership keys are all verbs and open sentences too. Deployment keys only when past
    # tense: "Live", "Pilot" and "Concept" start real names (as known_verb already assumes).
    listed = {normalise_text(w) for w in raw["sentence_openers"]}
    openers = listed | set(ownership) | {w for w in deployment if w.endswith("ed")}
    return Lexicons(
        version=str(raw.get("version", "unversioned")),
        ownership=ownership,
        deployment=deployment,
        metric_keywords={k: str(v) for k, v in _norm_keys(raw["metric_keywords"]).items()},
        direction_words={
            k: MetricDirection(str(v)) for k, v in _norm_keys(raw["direction_words"]).items()
        },
        scale_nouns={normalise_text(w) for w in raw["scale_nouns"]},
        quantity_words={k: float(v) for k, v in _norm_keys(raw["quantity_words"]).items()},
        aggregate_nouns={
            k: FactKind(str(v)) for k, v in _norm_keys(raw["aggregate_nouns"]).items()
        },
        seniority_words={normalise_text(w) for w in raw["seniority_words"]},
        credential_words={normalise_text(w) for w in raw["credential_words"]},
        sentence_openers=frozenset(openers),
        unit_aliases=unit_aliases,
    )


def _alias_map(table: dict[str, list[str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for canonical, aliases in table.items():
        out[normalise_text(canonical)] = canonical
        for alias in aliases:
            out[normalise_text(alias)] = canonical
    return out


def load_aliases(path: Path = ALIASES_PATH) -> Aliases:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return Aliases(
        version=str(raw.get("version", "unversioned")),
        skills=_alias_map(raw["skills"]),
        entities=_alias_map(raw.get("entities", {})),
    )


@dataclass(frozen=True)
class Layer1Context:
    owner_id: str
    resolve: Callable[[FactRef], FactVersion | None]
    lex: Lexicons
    aliases: Aliases
    as_of: str


def evidence_texts(facts: list[FactVersion]) -> list[str]:
    """Every text a check may compare against: text, source span, title and skills."""
    out: list[str] = []
    for f in facts:
        out.append(f.text)
        out.append(f.source.span_text)
        if f.attributes.title:
            out.append(f.attributes.title)
        out.extend(f.attributes.skills)
    return out
