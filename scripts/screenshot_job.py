"""Render one job ad as a plain job-board page and save a screenshot for the vision path.

Usage: uv run python scripts/screenshot_job.py
"""

from __future__ import annotations

import json
from pathlib import Path

from evident.eval.assets import JOB_SCREENSHOT, SCREENSHOT_JOB_ID, render_job_html
from evident.render.pdf import html_to_png

JOBS = Path("data/synthetic/jobs.jsonl")


def main() -> None:
    jobs = [json.loads(line) for line in JOBS.read_text(encoding="utf-8").splitlines() if line]
    job = next(j for j in jobs if j["document_id"] == SCREENSHOT_JOB_ID)
    print(html_to_png(render_job_html(job), JOB_SCREENSHOT, width=1200))


if __name__ == "__main__":
    main()
