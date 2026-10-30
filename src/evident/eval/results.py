"""The test-split section of experiments/a3-slice/RESULTS.md (spec 9).

Only the section under TEST_HEADING is generated. Everything above it, including the pass
criteria stated before running and the dev tuning log, is kept exactly as written.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from evident.eval.extraction import FieldCounts, f1, precision, recall
from evident.eval.grounding import Category, GroundingResults
from evident.eval.metrics import Rate, bootstrap_ci
from evident.eval.runner import DocResult, EvalRecord, sum_counts
from evident.settings import ModelConfig
from evident.validation.judge import limitations

TEST_HEADING = "## Test split results"
F1_PDF_TARGET = 0.95
F1_PHOTO_TARGET = 0.90
FALSE_REJECT_LIMIT = 0.10
PATH_NAMES = {"pdf_text": "Digital PDF (pdf_text)", "vision": "Simulated photo (vision)"}
DATA_LIMITATIONS = [
    "Pilot results on synthetic data: only 5 underlying profiles, and 4 of them in the "
    "extraction test split, so every interval is wide",
    "Simulated photos (warp, tilt, uneven light, blur, noise, JPEG), easier than real phone "
    "photos",
    "Claims are built from templates and hand-checked by the builder, not the owner; real "
    "planner output is more varied",
    "About 45 unsupported test claims: 0 false accepts gives an upper bound near 6.4%, so "
    "even a pass can't show the design's 2% target",
    "Layer 1 metric direction (known, not fixed by owner decision): a decrease word such as "
    "\"cut\" does not bind to a metric recorded as absolute, so such supported claims are "
    "rejected (fails closed)",
    "Layer 1 entity rule: two names each found whole in the evidence can combine through "
    "\"and\" into a name no fact mentions; see the dev tuning log for the full list",
]


def replace_section(document: str, heading: str, body: str) -> str:
    """Replace `heading` and everything after it, or append it if absent."""
    start = document.find(f"\n{heading}\n")
    kept = document if start < 0 else document[:start]
    return f"{kept.rstrip()}\n\n{heading}\n\n{body.strip()}\n"


def _f1_cells(c: FieldCounts, interval: str) -> str:
    return (f"{c.tp} | {c.fp} | {c.fn} | {precision(c):.3f} | {recall(c):.3f} | "
            f"{f1(c):.3f} | {interval} |")


def _profile_interval(results: list[DocResult]) -> str:
    by_profile: dict[str, list[DocResult]] = {}
    for r in results:
        by_profile.setdefault(r.doc.profile_id, []).append(r)
    clusters = [sum_counts(rs) for rs in by_profile.values()]
    if len(clusters) < 2:
        return "n/a (one profile)"
    def statistic(sample: Sequence[FieldCounts]) -> float:
        return f1(sum(sample, FieldCounts(0, 0, 0)))

    lo, hi = bootstrap_ci(clusters, statistic)
    return f"{lo:.3f} to {hi:.3f} ({len(clusters)} profiles)"


def extraction_section(results: list[DocResult]) -> tuple[str, dict[str, bool]]:
    lines = ["### Extraction F1 (spec 9.1)", "",
             "Field-level counts; F1 = 2tp / (2tp + fp + fn). Interval: 95% bootstrap "
             "resampling whole underlying profiles (10,000 resamples, seed 0).", "",
             "| Path | tp | fp | fn | Precision | Recall | F1 | 95% interval |",
             "|---|---|---|---|---|---|---|---|"]
    passed: dict[str, bool] = {}
    for kind, target in (("pdf_text", F1_PDF_TARGET), ("vision", F1_PHOTO_TARGET)):
        group = [r for r in results if r.doc.path_kind == kind]
        if not group:
            continue
        c = sum_counts(group)
        lines.append(f"| {PATH_NAMES[kind]} | {_f1_cells(c, _profile_interval(group))}")
        passed[kind] = f1(c) >= target
    lines += ["", "Per template:", "",
              "| Path | Template | tp | fp | fn | Precision | Recall | F1 | 95% interval |",
              "|---|---|---|---|---|---|---|---|---|"]
    for kind in ("pdf_text", "vision"):
        for template in sorted({r.doc.template for r in results}):
            group = [r for r in results if r.doc.path_kind == kind and r.doc.template == template]
            if group:
                cells = _f1_cells(sum_counts(group), _profile_interval(group))
                lines.append(f"| {PATH_NAMES[kind]} | {template} | {cells}")
    return "\n".join(lines), passed


def _rate_or_dash(r: Rate | None) -> str:
    return str(r) if r is not None else "n/a"


def grounding_section(g: GroundingResults) -> tuple[str, bool, bool]:
    lines = ["### Claim grounding (spec 9.2)", "",
             f"Judge prompt `judge/{g.judge_prompt_version}`, threshold {g.threshold:.2f}. "
             "A claim in user review is not accepted, so it is not a false accept.", "",
             f"- False accept rate (unsupported accepted / all unsupported): {g.false_accepts}",
             f"- False reject rate (supported rejected / all supported): {g.false_rejects}",
             f"- User review, unsupported claims: {g.review_unsupported}",
             f"- User review, supported claims: {g.review_supported}",
             f"- Judge errors: {g.judge_errors} of {len(g.outcomes)} claims", "",
             "Per category (unsupported claims):", "",
             "| Category | n | False accepts | User review | Rejected |", "|---|---|---|---|---|"]
    for category in Category:
        r = g.per_category.get(category)
        if r is not None:
            lines.append(f"| {category.value} | {r.n} | {r.false_accepts} | {r.review} | "
                         f"{r.rejected} |")
    n_bad = g.false_accepts.n
    lines += ["", "Which layer flagged each unsupported claim (regardless of final outcome):", ""]
    for key in ("layer1 and judge", "layer1 only", "judge only", "none"):
        lines.append(f"- {key}: {_rate_or_dash(Rate(g.caught_by.get(key, 0), n_bad))}")
    n_rejected = g.false_rejects.k
    lines += ["", f"Which layer flagged each falsely rejected supported claim ({n_rejected}):",
              ""]
    for key in ("layer1 and judge", "layer1 only", "judge only", "none"):
        lines.append(f"- {key}: {g.false_rejects_by.get(key, 0)}")
    fa_pass = g.false_accepts.k == 0
    fr_pass = g.false_rejects.value <= FALSE_REJECT_LIMIT
    return "\n".join(lines), fa_pass, fr_pass


def _calls_section(record: dict[str, object]) -> str:
    lines = ["### Cost and latency (observations, no criterion)", "",
             "Estimated cost uses paid list prices from `config/models.toml`; actual cost is "
             "zero on the free tier. Latency is for uncached calls only.", "",
             "| Role | Calls | Cached | Model IDs | Prompt versions | Tokens in/out | "
             "Est. cost USD | Uncached latency |", "|---|---|---|---|---|---|---|---|"]
    calls = record["calls"]
    assert isinstance(calls, dict)
    for role, c in calls.items():
        lat = c["uncached_latency_ms"]
        latency = (f"n={lat['n']}, p50 {lat['p50'] / 1000:.1f} s, p90 {lat['p90'] / 1000:.1f} s"
                   if lat["n"] else "n=0")
        lines.append(f"| {role} | {c['calls']} | {c['cached']} | {', '.join(c['model_ids'])} | "
                     f"{', '.join(c['prompt_versions'])} | {c['input_tokens']}/"
                     f"{c['output_tokens']} | {c['est_cost_usd']:.4f} | {latency} |")
    return "\n".join(lines)


def _verdict(ok: bool) -> str:
    return "**Pass**" if ok else "**Fail**"


def results_body(result: EvalRecord, config: ModelConfig, dev_log_anchor: str) -> str:
    r = result.record
    hits = r["cache_hit_share"]
    assert isinstance(hits, list)
    dataset = r["dataset_version"]
    models = r["configured_models"]
    assert isinstance(dataset, dict) and isinstance(models, dict)
    lines = [
        f"Run started {r['started']} (UTC). One locked run; nothing was tuned on this split.", "",
        f"- Models configured: {', '.join(f'{k} `{v}`' for k, v in models.items())}",
        f"- Ollama digests: {r['ollama_digests']}",
        f"- Prompt versions: extraction `{r['extraction_prompt_version']}`, judge "
        f"`{r['judge_prompt_version']}` (chosen on the dev split, see {dev_log_anchor})",
        f"- Dataset version: `a3_enriched` tree `{dataset['a3_enriched_tree']}`"
        + (" (with uncommitted changes)" if dataset["uncommitted_changes"] else ""),
        f"- Lexicons version {r['lexicons_version']}, aliases version {r['aliases_version']}, "
        f"`as_of` {r['as_of']}",
        f"- Cache hits: {hits[0]}/{hits[1]} calls; uncached Gemini calls planned at "
        f"pre-flight: {r['uncached_gemini_calls_planned']}", ""]
    verdicts = []
    if result.extraction:
        text, passed = extraction_section(result.extraction)
        lines += [text, ""]
        if "pdf_text" in passed:
            verdicts.append(f"- Extraction F1 on digital PDFs >= {F1_PDF_TARGET}: "
                            f"{_verdict(passed['pdf_text'])}")
        if "vision" in passed:
            verdicts.append(f"- Extraction F1 on photos >= {F1_PHOTO_TARGET}: "
                            f"{_verdict(passed['vision'])}")
    if result.grounding is not None:
        text, fa_pass, fr_pass = grounding_section(result.grounding)
        lines += [text, ""]
        verdicts.append(f"- Zero false accepts on the test split: {_verdict(fa_pass)}")
        verdicts.append(f"- False reject rate <= {FALSE_REJECT_LIMIT:.0%}: {_verdict(fr_pass)}")
    lines += [_calls_section(r), "", "### Pass or fail against the stated criteria", "",
              *verdicts, "",
              "A pass on extraction does not establish the phase 0 result: the CVs are "
              "synthetic, the photos simulated, and there are only 4 test profiles.", "",
              "### Limitations", "", *(f"- {x}" for x in DATA_LIMITATIONS + limitations(config))]
    return "\n".join(lines)


def write_results(path: Path, result: EvalRecord, config: ModelConfig,
                  dev_log_anchor: str = "the Dev tuning log") -> None:
    document = path.read_text(encoding="utf-8") if path.exists() else ""
    body = results_body(result, config, dev_log_anchor)
    path.write_text(replace_section(document, TEST_HEADING, body), encoding="utf-8")
