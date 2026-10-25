"""Dev-split tuning for photo extraction: prompt versions and box verification settings.

Development data only: refuses any profile except student_profile_01 (spec 9.1 dev split).
Prints counts and rates only, never CV text.

Usage: uv run python scripts/tune_extraction_dev.py --versions v1 v2
"""

from __future__ import annotations

import argparse
import io
import re
from dataclasses import dataclass

from PIL import Image, ImageOps
from rapidfuzz import fuzz

from evident.contracts.enums import FactKind
from evident.eval.assets import TEMPLATES, cv_photo_path
from evident.eval.datasets import load_ground_truth
from evident.ingestion.drafts import ExtractedFactDraft, box_2d_to_pixels
from evident.ingestion.vision import _normalise, _tesseract, request_photo_draft
from evident.models.router import build_adapter
from evident.settings import Settings, load_model_config

DEV_PROFILE = "student_profile_01"
MATCH_TEXT = 85.0
MATCH_SKILL = 90.0
# (name, share of image size, share of box height, white border px, upscale);
# names starting "v" pad only vertically, by a share of image height.
PADDINGS = [("raw+white+x2+invert", 0.0, 0.0, 12, 2),
            ("v0.75%+white+x2", 0.0075, 0.0, 12, 2), ("v1.25%+white+x2", 0.0125, 0.0, 12, 2),
            ("v1.75%+white+x2", 0.0175, 0.0, 12, 2), ("raw", 0.0, 0.0, 0, 1),
            ("img4", 0.04, 0.0, 0, 1),
            ("img2+box0.5", 0.02, 0.5, 0, 1),
            ("raw+white", 0.0, 0.0, 12, 1), ("raw+white+x2", 0.0, 0.0, 12, 2),
            ("box0.25+white+x2", 0.0, 0.25, 12, 2), ("box0.5+white+x2", 0.0, 0.5, 12, 2)]
CUTOFFS = [80.0, 75.0, 70.0]
SHORT_SPAN_WORDS = 3


def score_partial(span: str, text: str) -> float:
    return float(fuzz.partial_ratio(span, text)) if span and text else 0.0


def score_words(span: str, text: str) -> float:
    """Short spans must appear as whole words; fuzzy substring matching lets "git" match
    "github" anywhere on the page."""
    if not span or not text:
        return 0.0
    if len(span.split()) <= SHORT_SPAN_WORDS:
        return 100.0 if re.search(rf"(?<!\w){re.escape(span)}(?!\w)", text) else 0.0
    return float(fuzz.partial_ratio(span, text))


SCORERS = [("partial", score_partial), ("words", score_words)]

Box = tuple[float, float, float, float]


def padded(bbox: Box, width: int, height: int, image_margin: float, box_pad: float) -> Box:
    x0, y0, x1, y1 = bbox
    mx, my = image_margin * width, image_margin * height + box_pad * (y1 - y0)
    return (max(0.0, x0 - mx), max(0.0, y0 - my), min(float(width), x1 + mx),
            min(float(height), y1 + my))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def truth_keys() -> list[tuple[FactKind, str]]:
    keys: list[tuple[FactKind, str]] = []
    for f in load_ground_truth(DEV_PROFILE):
        if f.kind is FactKind.skill:
            keys.append((f.kind, f.attributes.skills[0]))
        else:
            keys.append((f.kind, f.attributes.title or f.text))
    return keys


def pred_keys(items: list[ExtractedFactDraft]) -> list[tuple[str, list[str]]]:
    out = []
    for d in items:
        kind = d.kind.strip().lower()
        if kind == "skill":
            out.append((kind, d.attributes.skills or [d.text]))
        else:
            out.append((kind, [d.attributes.title or d.text]))
    return out


def match_count(items: list[ExtractedFactDraft]) -> int:
    """Greedy one-to-one: each prediction matches at most one ground-truth fact."""
    truth = truth_keys()
    used = [False] * len(truth)
    matched = 0
    for kind, names in pred_keys(items):
        best, best_i = 0.0, -1
        for i, (tkind, tname) in enumerate(truth):
            if used[i] or tkind.value != kind:
                continue
            for name in names:
                if kind == "skill":
                    score = fuzz.ratio(norm(name), norm(tname))
                    ok = score >= MATCH_SKILL
                else:
                    score = fuzz.token_set_ratio(norm(name), norm(tname))
                    ok = score >= MATCH_TEXT
                if ok and score > best:
                    best, best_i = score, i
        if best_i >= 0:
            used[best_i] = True
            matched += 1
    return matched


@dataclass
class Item:
    span: str
    box: Box


def overlap(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def box_study(image: bytes, items: list[Item], totals: dict[str, list[int]]) -> None:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = _tesseract()
    with Image.open(io.BytesIO(image)) as img:
        w, h = img.size
        gray = img.convert("L")
        for name, image_margin, box_pad, border, scale in PADDINGS:
            texts = []
            for it in items:
                if name.startswith("v"):
                    x0, y0, x1, y1 = it.box
                    dy = image_margin * h
                    r = (x0, max(0.0, y0 - dy), x1, min(float(h), y1 + dy))
                else:
                    r = padded(it.box, w, h, image_margin, box_pad)
                crop = gray.crop((int(r[0]), int(r[1]), int(r[2]), int(r[3])))
                mean = sum(crop.getdata()) / max(1, crop.width * crop.height)
                if name.endswith("invert") and mean < 128:
                    crop = ImageOps.invert(crop)
                if scale != 1:
                    crop = crop.resize((crop.width * scale, crop.height * scale),
                                       Image.Resampling.LANCZOS)
                if border:
                    crop = ImageOps.expand(crop, border=border * scale, fill=255)
                texts.append(_normalise(pytesseract.image_to_string(crop)))
            for scorer_name, scorer in SCORERS:
                for cutoff in CUTOFFS:
                    key = f"{scorer_name}:{name}@{int(cutoff)}"
                    t = totals.setdefault(key, [0, 0, 0, 0, 0])
                    for i, it in enumerate(items):
                        span = _normalise(it.span)
                        t[0] += scorer(span, texts[i]) >= cutoff
                        t[1] += 1
                        for j, other in enumerate(items):
                            if j == i or overlap(it.box, other.box) > 0.3:
                                continue
                            if fuzz.partial_ratio(span, _normalise(other.span)) >= 70:
                                continue  # same words; a hit there would be a fair match
                            hit = scorer(span, texts[j]) >= cutoff
                            t[2] += hit
                            t[3] += 1
                            t[4] += hit and len(span.split()) <= SHORT_SPAN_WORDS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions", nargs="+", default=["v1", "v2"])
    parser.add_argument("--profile", default=DEV_PROFILE)
    args = parser.parse_args()
    if args.profile != DEV_PROFILE:
        raise SystemExit("Dev tuning uses student_profile_01 only.")
    adapter = build_adapter(Settings(), load_model_config())
    n_truth = len(truth_keys())
    for version in args.versions:
        totals: dict[str, list[int]] = {}
        print(f"\n== extraction/{version} ==")
        for template in TEMPLATES:
            path = cv_photo_path(DEV_PROFILE, template)
            image = path.read_bytes()
            with Image.open(io.BytesIO(image)) as img:
                w, h = img.size
            draft = request_photo_draft(image, "image/jpeg", adapter, version)
            items = []
            for d in draft.facts:
                if d.box_2d is None:
                    continue
                try:
                    items.append(Item(d.span_text, box_2d_to_pixels(d.box_2d, w, h)))
                except ValueError:
                    continue
            k = match_count(draft.facts)
            print(f"{template:<8} predicted {len(draft.facts):>2}  matched {k:>2}/{n_truth}  "
                  f"precision {k}/{len(draft.facts)}  boxes {len(items)}")
            box_study(image, items, totals)
        print("scorer:padding@cutoff       own verified    wrong-box accepted (short spans)")
        for key, (ok, n, bad, nn, short) in totals.items():
            print(f"{key:<26} {ok:>3}/{n:<3} ({ok / n:.0%})   {bad:>3}/{nn:<4} "
                  f"({bad / nn:.1%}) ({short})")


if __name__ == "__main__":
    main()
