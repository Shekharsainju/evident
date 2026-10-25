"""Layer 2: the entailment judge (design: Grounding and validation; P1).

The judge sees only the claim and its cited facts, inside an <evidence> tag, and returns a
verdict with a confidence. The confidence is self-reported and uncalibrated, which every
report states through `limitations`.
"""

from __future__ import annotations

import logging

from evident.contracts.facts import FactVersion
from evident.contracts.plan import Claim
from evident.contracts.validation import JudgeVerdict
from evident.errors import StageError
from evident.models.adapter import ModelAdapter, TextPart
from evident.prompts import load_prompt, render_prompt
from evident.settings import ModelConfig, Provider, Role

log = logging.getLogger("evident.validation")

JUDGE_THRESHOLD = 0.8  # tuned only on the dev split (spec 8.5)
PROMPT_VERSION = "v1"


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _dates(fact: FactVersion) -> str:
    a = fact.attributes
    if a.start and a.end:
        return f"{a.start} to {a.end}"
    if a.start:
        return f"{a.start} to present"
    return a.end or "no dates"


def evidence_block(facts: list[FactVersion]) -> str:
    """One entry per cited fact: text, span, dates, ownership, deployment and metrics."""
    lines: list[str] = []
    for f in facts:
        a = f.attributes
        lines.append(f"{f.fact_id}@{f.version} ({f.kind.value}): {_one_line(f.text)}")
        lines.append(f"  source span: {_one_line(f.source.span_text)}")
        lines.append(f"  dates: {_dates(f)}")
        lines.append(f"  ownership: {a.ownership.value if a.ownership else 'not stated'}; "
                     f"deployment: {a.deployment.value if a.deployment else 'not stated'}")
        if a.skills:
            lines.append(f"  skills: {', '.join(_one_line(s) for s in a.skills)}")
        for m in a.metrics:
            lines.append(f"  metric {m.metric_id}: {m.metric} {m.direction.value} {m.value:g} "
                         f"{m.unit} ({_one_line(m.span_text)})")
    return "\n".join(lines) if lines else "(no cited facts)"


def run_judge(
    claim: Claim, facts: list[FactVersion], adapter: ModelAdapter
) -> tuple[JudgeVerdict | None, str | None, str | None]:
    """Returns (verdict, model_id, error). A provider or quota error becomes a judge error."""
    prompt = load_prompt("judge", PROMPT_VERSION)
    text = render_prompt(prompt, cited_facts_with_spans=evidence_block(facts),
                         claim_text=_one_line(claim.text))
    try:
        result = adapter.generate_json(Role.judge, prompt, [TextPart(text)], JudgeVerdict)
    except StageError as exc:
        log.warning("judge error claim=%s code=%s", claim.claim_id, exc.code)
        return None, None, f"{exc.code}: {exc.detail}" if exc.detail else exc.code
    return result.value, result.model_id, None


def limitations(config: ModelConfig) -> list[str]:
    """Report lines derived from the judge actually configured, so they can't go stale."""
    judge = config.roles[Role.judge]
    planner = config.roles[Role.planner]
    if judge.provider is Provider.ollama:
        first = (f"Small local judge: {judge.model}, 4B quantised, self-reported uncalibrated "
                 f"confidence (P1)")
    else:
        first = f"Same-family judge: {judge.model} is also the planner (P1 fallback)"
    return [
        first,
        f"Free-tier {planner.model} for extraction, coverage and planning, not a Pro-class "
        f"model (P3)",
    ]
