"""Simulate a phone photo of page 1 of every rendered CV, at fixed seeds.

Usage: uv run python scripts/make_photos.py (after render_cvs.py)
"""

from __future__ import annotations

from evident.eval.assets import (
    TEMPLATES,
    cv_pdf_path,
    cv_photo_path,
    pdf_page_png,
    simulate_photo,
)
from evident.eval.datasets import load_enriched_profiles


def main() -> None:
    for i, profile in enumerate(load_enriched_profiles()):
        for j, template in enumerate(TEMPLATES):
            seed = 100 * (i + 1) + j
            page = pdf_page_png(cv_pdf_path(profile["document_id"], template).read_bytes())
            out = cv_photo_path(profile["document_id"], template)
            out.write_bytes(simulate_photo(page, seed=seed))
            print(out, "seed", seed)


if __name__ == "__main__":
    main()
