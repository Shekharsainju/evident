"""Compare Layer 1 outcomes between a base git ref and the current checkout.

The probe claims are generated here with the current code and written to a temp JSONL. Both
sides then score that file. The base side runs in a temporary git worktree with its own src and
config, using only modules that exist at older refs. Exit 1 if any unsupported claim newly
passes. Dev profiles only: any claim from a locked test profile raises LockedSplitError.

Usage: uv run python scripts/layer1_diff.py --base <git-ref> [--extra probes.jsonl]
       [--out diff.json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from evident.eval.grounding import LabelledClaim, dump_claims, load_claims
from evident.eval.layer1_probe import layer1_outcomes, outcome_key, probe_claims
from evident.eval.splits import require_dev

ROOT = Path(__file__).resolve().parents[1]

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


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)


def _score_base(base: str, claims_path: Path, scratch: Path) -> list[list[str]]:
    wt = scratch / "base-worktree"
    result = scratch / "base-outcomes.json"
    _git("worktree", "add", "--detach", str(wt), base)
    try:
        proc = subprocess.run(
            ["uv", "run", "--project", str(wt), "python", "-c", RUNNER,
             str(claims_path), str(result)],
            cwd=wt, check=True, capture_output=True, text=True)
        for line in proc.stderr.splitlines():
            if line.startswith("IMPORTED "):
                print(line.replace("IMPORTED ", "base imports evident from: ", 1))
        data: list[list[str]] = json.loads(result.read_text(encoding="utf-8"))
        return data
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT,
                       capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="HEAD", help="git ref to compare against")
    ap.add_argument("--extra", type=Path, help="LabelledClaim JSONL of extra probes")
    ap.add_argument("--profile", action="append", default=[],
                    help="restrict to these dev profiles (test profiles are refused)")
    ap.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "layer1_diff.json")
    args = ap.parse_args()

    require_dev(args.profile)
    claims: list[LabelledClaim] = probe_claims()
    if args.extra:
        extra = load_claims(args.extra)
        require_dev(c.profile_id for c in extra)
        claims.extend(extra)
    claims = list({outcome_key(c): c for c in reversed(claims)}.values())[::-1]
    if args.profile:
        claims = [c for c in claims if c.profile_id in args.profile]
    print(f"probes: {len(claims)}")

    with tempfile.TemporaryDirectory(prefix="layer1-diff-") as tmp:
        scratch = Path(tmp)
        claims_path = scratch / "probes.jsonl"
        claims_path.write_text(dump_claims(claims), encoding="utf-8")
        old = _score_base(args.base, claims_path, scratch)
    new = layer1_outcomes(claims)

    changed = []
    counts = {"K": 0, "S": 0, "F": 0, "U": 0}
    for c, old_rules in zip(claims, old, strict=True):
        new_rules = new[outcome_key(c)]
        if bool(old_rules) == bool(new_rules):
            continue
        newly_passing = not new_rules
        letter = {(True, "unsupported"): "K", (True, "supported"): "S",
                  (False, "supported"): "F", (False, "unsupported"): "U"}[(newly_passing, c.label)]
        counts[letter] += 1
        changed.append({"label": c.label, "old": old_rules, "new": new_rules,
                        "text": c.claim.text, "evidence": outcome_key(c).split("|")[-1]})
        print(f"{c.label} | {','.join(old_rules) or 'pass'} -> "
              f"{','.join(new_rules) or 'pass'} | {c.claim.text}")
    print(f"changed: {len(changed)} (newly passing unsupported: {counts['K']}, "
          f"newly passing supported: {counts['S']}, newly failing supported: {counts['F']}, "
          f"newly failing unsupported: {counts['U']})")
    args.out.write_text(json.dumps({"base": args.base, "probes": len(claims),
                                    "counts": counts, "changed": changed}, indent=2),
                        encoding="utf-8")
    return 1 if counts["K"] else 0


if __name__ == "__main__":
    sys.exit(main())
