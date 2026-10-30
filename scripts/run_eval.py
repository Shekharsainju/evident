"""Task 20 evaluation: extraction F1 and claim grounding on the dev or test split.

Always runs the quota pre-flight first and makes no call if the run won't fit today.
--write-results writes the test-split section of RESULTS.md and is refused on dev.
Prints counts and IDs only, never CV text.

Usage:
  uv run python scripts/run_eval.py --split dev --suite all --judge-prompt v1
  uv run python scripts/run_eval.py --split test --suite all --write-results
"""

from __future__ import annotations

import argparse
from pathlib import Path

from evident.errors import StageError
from evident.eval.runner import EvalOptions, run_eval
from evident.models.router import build_adapter, build_guards
from evident.settings import Role, Settings, load_model_config
from evident.validation.judge import PROMPT_VERSION

EXPERIMENT = Path("experiments/a3-slice")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--suite", choices=["extraction", "grounding", "all"], default="all")
    parser.add_argument("--judge-prompt", default=PROMPT_VERSION)
    parser.add_argument("--write-results", action="store_true")
    args = parser.parse_args()
    if args.write_results and args.split != "test":
        raise SystemExit("--write-results is only allowed with --split test.")

    settings = Settings()
    config = load_model_config()
    adapter = build_adapter(settings, config)
    guard = build_guards(settings, config)[config.roles[Role.extraction_text].model]
    options = EvalOptions(split=args.split, suite=args.suite, judge_prompt=args.judge_prompt,
                          write_results=args.write_results, as_of=settings.as_of)
    try:
        result = run_eval(options, adapter, guard, config, EXPERIMENT, EXPERIMENT / "runs")
    except StageError as exc:
        raise SystemExit(f"Stopped: {exc.code}: {exc.detail}") from None
    if args.write_results:
        from evident.eval.results import write_results

        write_results(EXPERIMENT / "RESULTS.md", result, config)
        print(f"wrote {EXPERIMENT / 'RESULTS.md'}")
    g = result.grounding
    if g is not None:
        print(f"false accepts {g.false_accepts}")
        print(f"false rejects {g.false_rejects}")
        print(f"review (unsupported) {g.review_unsupported}")
        print(f"review (supported) {g.review_supported}")


if __name__ == "__main__":
    main()
