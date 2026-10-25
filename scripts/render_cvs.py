"""Render every enriched profile in every CV template to PDF (5 x 3 = 15 CVs).

Usage: uv run python scripts/render_cvs.py
"""

from __future__ import annotations

from evident.eval.assets import TEMPLATES, cv_pdf_path, render_cv_html
from evident.eval.datasets import load_enriched_profiles
from evident.render.pdf import html_to_pdf


def main() -> None:
    for profile in load_enriched_profiles():
        for template in TEMPLATES:
            out = html_to_pdf(render_cv_html(profile, template),
                              cv_pdf_path(profile["document_id"], template))
            print(out)


if __name__ == "__main__":
    main()
