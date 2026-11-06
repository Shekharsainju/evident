"""Compare Layer 1 outcomes between a base git ref and the current checkout.

The probe claims are generated here with the current code and written to a temp JSONL. Both
sides then score that file. The base side runs in a temporary git worktree with its own src and
config, using only modules that exist at older refs. Exit 1 if any unsupported claim newly
passes. Dev profiles only: any claim from a locked test profile raises LockedSplitError.

Usage: uv run python scripts/layer1_diff.py --base <git-ref> [--extra probes.jsonl]
       [--out diff.json] [--report gate.txt]

--report writes the printed gate output to a UTF-8 file. Redirecting stdout on Windows
re-encodes it in the console code page, which breaks bullets and dashes in claim text.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from evident.eval.grounding import LabelledClaim, dump_claims, load_claims
from evident.eval.layer1_probe import (
    classify,
    dedupe_fail_closed,
    layer1_outcomes,
    probe_claims,
)
from evident.eval.splits import require_dev

ROOT = Path(__file__).resolve().parents[1]
# Targeted probes from every fix stay in the gate for good, so a later fix can't reopen an
# earlier false-accept path unnoticed.
PROBES_DIR = ROOT / "experiments" / "p1-layer1" / "probes"

# Runs inside the worktree. Imports only modules that exist at older refs.
RUNNER = """
import json, sys
from pathlib import Path
import evident
from evident.eval.grounding import DEFAULT_AS_OF, layer1_context, load_claims
from evident.validation.layer1.run import run_layer1
print("IMPORTED " + str(Path(evident.__file__).resolve()), file=sys.stderr)
claims = load_claims(Path(sys.argv[1]))
ctxs = {}
out = []
for c in claims:
    if c.profile_id not in ctxs:
        ctxs[c.profile_id] = layer1_context(c.profile_id, DEFAULT_AS_OF)
    res = run_layer1(c.claim, ctxs[c.profile_id])
    out.append(sorted({f.rule for f in res.failures}))
Path(sys.argv[2]).write_text(json.dumps(out), encoding="utf-8")
"""


# Every printed gate line, kept for --report.
_LINES: list[str] = []


def _emit(line: str) -> None:
    _LINES.append(line)
    print(line)


class ToolError(Exception):
    """The diff tool itself failed. Exit 2, never 1, so a tool error can't read as a gate result."""


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)


def _base_env() -> dict[str, str]:
    # An inherited PYTHONPATH could make the base import the current checkout's code.
    return {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}


def _check_base_import(stderr: str, wt: Path) -> None:
    """Fail unless the base run imported evident from inside its own worktree."""
    for line in stderr.splitlines():
        if line.startswith("IMPORTED "):
            path = Path(line.removeprefix("IMPORTED ").strip()).resolve()
            if not path.is_relative_to(wt.resolve()):
                raise ToolError(f"base imported evident from {path}, outside worktree {wt}")
            _emit(f"base imports evident from: {path}")
            return
    raise ToolError("base run did not report where it imported evident from")


def _score_base(base: str, claims_path: Path, scratch: Path) -> list[list[str]]:
    wt = scratch / "base-worktree"
    result = scratch / "base-outcomes.json"
    _git("worktree", "add", "--detach", str(wt), base)
    try:
        proc = subprocess.run(
            ["uv", "run", "--project", str(wt), "python", "-c", RUNNER,
             str(claims_path), str(result)],
            cwd=wt, check=True, capture_output=True, text=True, env=_base_env())
        _check_base_import(proc.stderr, wt)
        data: list[list[str]] = json.loads(result.read_text(encoding="utf-8"))
        return data
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT,
                       capture_output=True, text=True)


def main() -> int:
    try:
        return _main()
    except subprocess.CalledProcessError as e:
        print(f"tool error: {e}", file=sys.stderr)
        print(e.stderr or "", file=sys.stderr)
        return 2
    except (ToolError, OSError, json.JSONDecodeError) as e:
        print(f"tool error: {e}", file=sys.stderr)
        return 2


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="HEAD", help="git ref to compare against")
    ap.add_argument("--extra", type=Path, help="LabelledClaim JSONL of extra probes")
    ap.add_argument("--profile", action="append", default=[],
                    help="restrict to these dev profiles (test profiles are refused)")
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "layer1_diff.json")
    ap.add_argument("--report", type=Path, help="also write the printed output here as UTF-8")
    args = ap.parse_args()

    require_dev(args.profile)
    claims: list[LabelledClaim] = probe_claims()
    for path in sorted(PROBES_DIR.glob("*.jsonl")):
        standing = load_claims(path)
        require_dev(c.profile_id for c in standing)
        claims.extend(standing)
    if args.extra:
        extra = load_claims(args.extra)
        require_dev(c.profile_id for c in extra)
        claims.extend(extra)
    claims = dedupe_fail_closed(claims)
    if args.profile:
        claims = [c for c in claims if c.profile_id in args.profile]
    _LINES.clear()
    _emit(f"probes: {len(claims)}")

    with tempfile.TemporaryDirectory(prefix="layer1-diff-") as tmp:
        scratch = Path(tmp)
        claims_path = scratch / "probes.jsonl"
        claims_path.write_text(dump_claims(claims), encoding="utf-8")
        old = _score_base(args.base, claims_path, scratch)
    new = layer1_outcomes(claims)

    changed, counts = classify(claims, old, new)
    for row in changed:
        _emit(f"{row['label']} | {','.join(row['old']) or 'pass'} -> "
              f"{','.join(row['new']) or 'pass'} | {row['text']}")
    _emit(f"changed: {len(changed)} (newly passing unsupported: {counts['K']}, "
          f"newly passing supported: {counts['S']}, newly failing supported: {counts['F']}, "
          f"newly failing unsupported: {counts['U']})")
    args.out.write_text(json.dumps({"base": args.base, "probes": len(claims),
                                    "counts": counts, "changed": changed}, indent=2),
                        encoding="utf-8")
    if args.report:
        args.report.write_text("\n".join(_LINES) + "\n", encoding="utf-8")
    return 1 if counts["K"] else 0


if __name__ == "__main__":
    sys.exit(main())
