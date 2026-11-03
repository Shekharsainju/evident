"""Render every enriched profile of a dataset in every CV template to PDF.

Usage: uv run python scripts/render_cvs.py [--dataset a3_enriched|heldout_p1]
"""

from __future__ import annotations

import argparse

from evident.eval.assets import TEMPLATES, cv_pdf_path, render_cv_html
from evident.eval.datasets import DATASETS, load_enriched_profiles
from evident.render.pdf import html_to_pdf


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="a3_enriched")
    ds = DATASETS[parser.parse_args().dataset]
    for profile in load_enriched_profiles(ds):
        for template in TEMPLATES:
            out = html_to_pdf(render_cv_html(profile, template),
                              cv_pdf_path(profile["document_id"], template))
            print(out)


if __name__ == "__main__":
    main()
