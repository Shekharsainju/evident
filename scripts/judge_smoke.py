"""Local judge smoke test (plan Task 3a): speed and accuracy on 10 obvious claims.

Prints only claim id, label, verdict, confidence and timing. Claim text stays out of the log.
Usage: uv run python scripts/judge_smoke.py
"""

from __future__ import annotations

import json
import statistics
import time
import urllib.request
from pathlib import Path

from evident.contracts.validation import JudgeVerdict
from evident.models.adapter import TextPart
from evident.models.cache import DiskCache
from evident.models.ollama import OllamaAdapter
from evident.prompts import load_prompt, render_prompt
from evident.settings import Role, Settings, load_model_config

CLAIMS = Path("experiments/a3-slice/judge_smoke_claims.jsonl")
FALSE_ACCEPT_CONFIDENCE = 0.8


def post(url: str, body: dict[str, object], timeout: float) -> dict[str, object]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result: dict[str, object] = json.loads(resp.read())
        return result


def gpu_share(base: str, tag: str) -> float:
    with urllib.request.urlopen(f"{base}/api/ps", timeout=5) as resp:
        models = json.loads(resp.read())["models"]
    m = next(m for m in models if m["name"] == tag)
    return float(m["size_vram"]) / float(m["size"])


def main() -> None:
    settings = Settings()
    config = load_model_config()
    tag = config.roles[Role.judge].model
    base = settings.ollama_url.rstrip("/")
    prompt = load_prompt("judge")
    adapter = OllamaAdapter(settings, config, DiskCache(Path("var/unused")), use_cache=False)
    claims = [json.loads(line) for line in CLAIMS.read_text(encoding="utf-8").splitlines()]

    def judge(item: dict[str, str]) -> tuple[JudgeVerdict, float]:
        text = render_prompt(prompt, cited_facts_with_spans=item["evidence"],
                             claim_text=item["claim"])
        start = time.perf_counter()
        result = adapter.generate_json(Role.judge, prompt, [TextPart(text)], JudgeVerdict)
        return result.value, time.perf_counter() - start

    # Unload first so the cold start is measured honestly.
    post(f"{base}/api/generate", {"model": tag, "keep_alive": 0}, 60)
    _, cold = judge(claims[0])
    print(f"warm-up (cold start, discarded): {cold:.1f} s")

    rows = []
    for item in claims:
        verdict, seconds = judge(item)
        correct = (verdict.verdict.value == "supported") == (item["label"] == "supported")
        false_accept = (
            item["label"] == "inflated"
            and verdict.verdict.value == "supported"
            and verdict.confidence >= FALSE_ACCEPT_CONFIDENCE
        )
        rows.append((item["id"], item["label"], item["kind"], verdict.verdict.value,
                     verdict.confidence, seconds, correct, false_accept))
        print(f"{item['id']:>2} {item['label']:<9} {item['kind']:<10} -> "
              f"{verdict.verdict.value:<11} conf={verdict.confidence:.2f} {seconds:5.1f} s "
              f"{'ok' if correct else 'WRONG'}")

    times = [r[5] for r in rows]
    k_correct = sum(r[6] for r in rows)
    k_fa = sum(r[7] for r in rows)
    share = gpu_share(base, tag)
    print(f"correct {k_correct}/{len(rows)}; false accepts {k_fa}/5; "
          f"median {statistics.median(times):.1f} s; max {max(times):.1f} s (n={len(times)}); "
          f"GPU share {share:.0%}")


if __name__ == "__main__":
    main()
