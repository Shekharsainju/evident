"""Simulate a phone photo of page 1 of every rendered CV in a dataset, at fixed seeds.

Usage: uv run python scripts/make_photos.py [--dataset a3_enriched|heldout_p1]
(after render_cvs.py)
"""

from __future__ import annotations

import argparse

from evident.eval.assets import (
    TEMPLATES,
    cv_pdf_path,
    cv_photo_path,
    pdf_page_png,
    photo_seed,
    simulate_photo,
)
from evident.eval.datasets import DATASETS, load_enriched_profiles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="a3_enriched")
    ds = DATASETS[parser.parse_args().dataset]
    for profile in load_enriched_profiles(ds):
        for template in TEMPLATES:
            seed = photo_seed(profile["document_id"], template)
            page = pdf_page_png(cv_pdf_path(profile["document_id"], template).read_bytes())
            out = cv_photo_path(profile["document_id"], template)
            out.write_bytes(simulate_photo(page, seed=seed))
            print(out, "seed", seed)


if __name__ == "__main__":
    main()
