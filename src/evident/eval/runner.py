"""Evaluation runs for Task 20: pre-flight, extraction F1, grounding rates and the run record.

`scripts/run_eval.py` is the command line around `run_eval`. The run record holds counts,
IDs and timings only, never CV text.
"""

from __future__ import annotations

import json
import statistics
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from evident.eval.assets import TEMPLATES, cv_pdf_path, cv_photo_path
from evident.eval.budget import PlannedCall, preflight
from evident.eval.datasets import ENRICHED_DIR, load_ground_truth
from evident.eval.extraction import (
    ZERO,
    FieldCounts,
    draft_facts,
    eval_document,
    field_counts,
    match_facts,
    request_draft,
)
from evident.eval.grounding import (
    DEFAULT_AS_OF,
    GroundingResults,
    LabelledClaim,
    layer1_context,
    load_claims,
    run_grounding,
    summary,
)
from evident.ingestion.drafts import EXTRACTION_PROMPT_VERSION
from evident.models.adapter import ModelAdapter, ModelResult, Part, T
from evident.models.quota import QuotaGuard
from evident.prompts import Prompt
from evident.settings import ModelConfig, Provider, Role
from evident.validation.judge import JUDGE_THRESHOLD
from evident.validation.judge import PROMPT_VERSION as JUDGE_PROMPT_VERSION
from evident.validation.layer1.config import load_aliases, load_lexicons
from evident.validation.outcome import validate_claim

Split = Literal["dev", "test"]
Suite = Literal["extraction", "grounding", "all"]
PathKind = Literal["pdf_text", "vision"]

# Spec 9.1: profile 01 is the extraction dev split, 02 to 05 the test split.
EXTRACTION_PROFILES: dict[str, tuple[str, ...]] = {
    "dev": ("student_profile_01",),
    "test": ("student_profile_02", "student_profile_03", "student_profile_04",
             "student_profile_05"),
}


@dataclass(frozen=True)
class EvalOptions:
    split: Split
    suite: Suite
    judge_prompt: str = JUDGE_PROMPT_VERSION
    write_results: bool = False
    threshold: float = JUDGE_THRESHOLD
    as_of: str = DEFAULT_AS_OF


@dataclass(frozen=True)
class ExtractionDoc:
    profile_id: str
    template: str
    path_kind: PathKind
    path: Path


@dataclass(frozen=True)
class DocResult:
    doc: ExtractionDoc
    counts: FieldCounts
    predicted: int
    truth: int


@dataclass
class EvalRecord:
    options: EvalOptions
    uncached_planned: int
    started: str
    record: dict[str, Any]
    extraction: list[DocResult] = field(default_factory=list)
    grounding: GroundingResults | None = None


def extraction_docs(split: str) -> list[ExtractionDoc]:
    docs = []
    for profile in EXTRACTION_PROFILES[split]:
        for template in TEMPLATES:
            docs.append(ExtractionDoc(profile, template, "pdf_text",
                                      cv_pdf_path(profile, template)))
            docs.append(ExtractionDoc(profile, template, "vision",
                                      cv_photo_path(profile, template)))
    return docs


# Planning calls without making them


class _Captured(Exception):  # noqa: N818 (a control-flow signal, not an error)
    def __init__(self, call: PlannedCall) -> None:
        self.call = call


class _CapturingAdapter:
    """Records the request the pipeline would send, then stops it before any provider."""

    def is_cached(self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]) -> bool:
        return False

    def generate_json(
        self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]
    ) -> ModelResult[T]:
        raise _Captured(PlannedCall(role, prompt, list(parts), schema))


def _capture(run: Callable[[ModelAdapter], object]) -> PlannedCall:
    try:
        run(_CapturingAdapter())
    except _Captured as captured:
        return captured.call
    raise AssertionError("expected exactly one model call")


def planned_extraction_calls(split: str) -> list[PlannedCall]:
    calls = []
    for doc in extraction_docs(split):
        def request(adapter: ModelAdapter, path: Path = doc.path) -> object:
            return request_draft(path, adapter)
        calls.append(_capture(request))
    return calls


def planned_judge_calls(claims: list[LabelledClaim], version: str,
                        as_of: str) -> list[PlannedCall]:
    calls = []
    for c in claims:
        def judge(adapter: ModelAdapter, c: LabelledClaim = c) -> object:
            return validate_claim(c.claim, layer1_context(c.profile_id, as_of), adapter,
                                  judge_prompt_version=version)
        calls.append(_capture(judge))
    return calls


# Recording what the run actually did


class RecordingAdapter:
    def __init__(self, inner: ModelAdapter) -> None:
        self.inner = inner
        self.results: list[tuple[Role, ModelResult[Any]]] = []

    def is_cached(self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]) -> bool:
        return self.inner.is_cached(role, prompt, parts, schema)

    def generate_json(
        self, role: Role, prompt: Prompt, parts: list[Part], schema: type[T]
    ) -> ModelResult[T]:
        result = self.inner.generate_json(role, prompt, parts, schema)
        self.results.append((role, result))
        return result


def _percentile(values: list[int], q: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    return statistics.quantiles(ordered, n=100, method="inclusive")[int(q) - 1]


def _calls_summary(rec: RecordingAdapter) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for role in sorted({r for r, _ in rec.results}, key=lambda r: r.value):
        results = [m for r, m in rec.results if r is role]
        live = [m.latency_ms for m in results if not m.cached]
        out[role.value] = {
            "calls": len(results),
            "cached": sum(m.cached for m in results),
            "model_ids": sorted({m.model_id for m in results}),
            "prompt_versions": sorted({m.prompt_version for m in results}),
            "input_tokens": sum(m.input_tokens for m in results),
            "output_tokens": sum(m.output_tokens for m in results),
            "est_cost_usd": round(sum(m.est_cost_usd for m in results), 6),
            "uncached_latency_ms": ({"n": len(live), "p50": _percentile(live, 50),
                                     "p90": _percentile(live, 90)} if live else {"n": 0}),
        }
    return out


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def dataset_version() -> dict[str, Any]:
    tree = _git("rev-parse", f"HEAD:{ENRICHED_DIR.as_posix()}")
    dirty = bool(_git("status", "--porcelain", "--", ENRICHED_DIR.as_posix()))
    return {"a3_enriched_tree": tree, "uncommitted_changes": dirty}


def _doc_record(r: DocResult) -> dict[str, Any]:
    return {"profile": r.doc.profile_id, "template": r.doc.template, "path": r.doc.path_kind,
            "tp": r.counts.tp, "fp": r.counts.fp, "fn": r.counts.fn,
            "predicted_facts": r.predicted, "truth_facts": r.truth}


def run_eval(options: EvalOptions, adapter: ModelAdapter, quota: QuotaGuard,
             config: ModelConfig, claims_dir: Path, out_dir: Path,
             log: Callable[[str], None] = print) -> EvalRecord:
    if options.write_results and options.split != "test":
        raise ValueError("--write-results is only allowed on the test split")
    started = datetime.now(UTC).isoformat(timespec="seconds")
    do_extraction = options.suite in ("extraction", "all")
    do_grounding = options.suite in ("grounding", "all")
    claims = (load_claims(claims_dir / f"claims_{options.split}.jsonl")
              if do_grounding else [])

    # Pre-flight before any call. The local judge has no quota, so its calls join the
    # Gemini count only if the judge has fallen back to Gemini.
    gemini_calls = planned_extraction_calls(options.split) if do_extraction else []
    if do_grounding and config.roles[Role.judge].provider is Provider.gemini:
        gemini_calls += planned_judge_calls(claims, options.judge_prompt, options.as_of)
    needed = preflight(gemini_calls, adapter, quota)
    log(f"pre-flight: {len(gemini_calls)} Gemini calls planned, {needed} uncached, "
        f"{quota.remaining_today()} left today")

    rec = RecordingAdapter(adapter)
    result = EvalRecord(options=options, uncached_planned=needed, started=started, record={})
    if do_extraction:
        lex = load_lexicons()
        for doc in extraction_docs(options.split):
            draft = request_draft(doc.path, rec)
            facts = draft_facts(draft, eval_document(f"{doc.profile_id}_{doc.template}",
                                                     doc.path))
            truth = load_ground_truth(doc.profile_id)
            counts = field_counts(match_facts(facts, truth), lex)
            result.extraction.append(DocResult(doc, counts, len(facts), len(truth)))
            log(f"extraction {doc.profile_id} {doc.template} {doc.path_kind}: "
                f"tp {counts.tp} fp {counts.fp} fn {counts.fn}")
    if do_grounding:
        result.grounding = run_grounding(
            claims, rec, options.threshold, options.judge_prompt, options.as_of,
            progress=lambda n, total: log(f"grounding {n}/{total}") if n % 10 == 0 or
            n == total else None)

    total_calls = len(rec.results)
    result.record = {
        "started": started,
        "split": options.split,
        "suite": options.suite,
        "judge_prompt_version": options.judge_prompt,
        "extraction_prompt_version": EXTRACTION_PROMPT_VERSION,
        "judge_threshold": options.threshold,
        "as_of": options.as_of,
        "configured_models": {r.value: c.model for r, c in config.roles.items()},
        "ollama_digests": config.ollama_digests,
        "lexicons_version": load_lexicons().version,
        "aliases_version": load_aliases().version,
        "dataset_version": dataset_version(),
        "uncached_gemini_calls_planned": needed,
        "cache_hit_share": ([sum(m.cached for _, m in rec.results), total_calls]
                            if total_calls else [0, 0]),
        "calls": _calls_summary(rec),
        "extraction": [_doc_record(r) for r in result.extraction],
        "grounding": summary(result.grounding) if result.grounding else None,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{options.split}_{options.suite}_judge-{options.judge_prompt}.json"
    (out_dir / name).write_text(json.dumps(result.record, indent=2), encoding="utf-8")
    log(f"run record written to {out_dir / name}")
    return result


def sum_counts(results: list[DocResult]) -> FieldCounts:
    total = ZERO
    for r in results:
        total += r.counts
    return total
