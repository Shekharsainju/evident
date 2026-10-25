"""Shared builders for validation tests. All data is synthetic."""

from __future__ import annotations

import json
from typing import Any

from evident.contracts.enums import OutputType
from evident.contracts.facts import FactRef, FactVersion
from evident.contracts.plan import Claim
from evident.validation.layer1.config import Layer1Context, load_aliases, load_lexicons
from tests.builders import NOW, OWNER, attrs, fact, metric

LEX = load_lexicons()
ALIASES = load_aliases()
AS_OF = "2026-10"


def confirmed(fact_id: str = "doc_01_f01", version: int = 1, **overrides: Any) -> FactVersion:
    return fact(fact_id, version, status="confirmed", confirmed_at=NOW, **overrides)


def project(fact_id: str = "doc_01_f01", text: str = "Built a timetable clash checker in "
            "Python and Flask", **attr_overrides: Any) -> FactVersion:
    base: dict[str, Any] = {
        "ownership": "built", "deployment": "prototype", "skills": ["Python", "Flask"],
        "start": "2025-02", "end": "2025-06", "title": "Team Course Planner",
    }
    base.update(attr_overrides)
    return confirmed(fact_id, text=text, kind="project", attributes=attrs(**base))


def claim(text: str, *facts: FactVersion, refs: list[FactRef] | None = None,
          claim_id: str = "c_01") -> Claim:
    evidence = refs if refs is not None else [
        FactRef(fact_id=f.fact_id, version=f.version) for f in facts
    ]
    return Claim(claim_id=claim_id, text=text, evidence=evidence, section="Projects",
                 emphasis=3, allowed_transformations=[], output_types=[OutputType.visual_profile],
                 parent_claim_id=None)


def context(*facts: FactVersion, owner_id: str = OWNER, as_of: str = AS_OF) -> Layer1Context:
    table = {(f.fact_id, f.version): f for f in facts}
    return Layer1Context(owner_id=owner_id, resolve=lambda r: table.get((r.fact_id, r.version)),
                         lex=LEX, aliases=ALIASES, as_of=as_of)


def judge_reply(verdict: str = "supported", confidence: float = 0.95,
                phrase: str | None = None) -> str:
    return json.dumps({"verdict": verdict, "offending_phrase": phrase,
                       "corrected_phrasing": None, "confidence": confidence})


__all__ = ["ALIASES", "AS_OF", "LEX", "OWNER", "claim", "confirmed", "context", "judge_reply",
           "metric", "project"]
