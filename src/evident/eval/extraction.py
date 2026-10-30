"""Extraction scoring (spec 9.1): match predicted facts to ground truth, then count fields.

Scoring rules are fixed here before any test-split run:
- A prediction and a ground-truth fact match only if their kinds agree and the
  `token_set_ratio` of their titles (falling back to text) is at least 85. Matching is
  one-to-one and greedy, best score first.
- Fields: kind, title, organisation, start, end, each skill, and each metric (value, unit
  family and direction together). A field that is None on both sides isn't counted.
- Title and organisation agree at a `fuzz.ratio` of 90 or more after normalisation, so a
  case or punctuation difference is not an error. Dates, skills and metrics must be equal
  after normalisation.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image
from rapidfuzz import fuzz

from evident.contracts.documents import Document
from evident.contracts.enums import DocumentKind
from evident.contracts.facts import FactVersion, PdfTextSource, VisionSource
from evident.eval.datasets import GROUND_TRUTH_OWNER
from evident.ingestion.drafts import ExtractionDraft, draft_to_fact
from evident.ingestion.pdf_text import NO_BOX, extract_pages, request_pdf_draft
from evident.ingestion.vision import request_photo_draft
from evident.models.adapter import ModelAdapter
from evident.validation.layer1.config import Lexicons, load_lexicons
from evident.validation.layer1.normalise import normalise_text

MATCH_THRESHOLD = 85.0
FIELD_TEXT_THRESHOLD = 90.0

Pair = tuple[FactVersion | None, FactVersion | None]


@dataclass(frozen=True)
class FieldCounts:
    tp: int
    fp: int
    fn: int

    def __add__(self, other: FieldCounts) -> FieldCounts:
        return FieldCounts(self.tp + other.tp, self.fp + other.fp, self.fn + other.fn)


ZERO = FieldCounts(0, 0, 0)


def f1(c: FieldCounts) -> float:
    denominator = 2 * c.tp + c.fp + c.fn
    return 2 * c.tp / denominator if denominator else 0.0


def precision(c: FieldCounts) -> float:
    return c.tp / (c.tp + c.fp) if c.tp + c.fp else 0.0


def recall(c: FieldCounts) -> float:
    return c.tp / (c.tp + c.fn) if c.tp + c.fn else 0.0


def _name(f: FactVersion) -> str:
    return normalise_text(f.attributes.title or f.text)


def match_facts(pred: list[FactVersion], truth: list[FactVersion]) -> list[Pair]:
    """Matched pairs in ground-truth order, then unmatched predictions, then unmatched truth."""
    scored = []
    for i, p in enumerate(pred):
        for j, t in enumerate(truth):
            if p.kind is not t.kind:
                continue
            score = fuzz.token_set_ratio(_name(p), _name(t))
            if score >= MATCH_THRESHOLD:
                scored.append((-score, i, j))
    scored.sort()
    pred_used: dict[int, int] = {}
    truth_used: set[int] = set()
    for _, i, j in scored:
        if i in pred_used or j in truth_used:
            continue
        pred_used[i] = j
        truth_used.add(j)
    by_truth = {j: i for i, j in pred_used.items()}
    pairs: list[Pair] = [(pred[by_truth[j]], truth[j]) for j in sorted(by_truth)]
    pairs += [(p, None) for i, p in enumerate(pred) if i not in pred_used]
    pairs += [(None, t) for j, t in enumerate(truth) if j not in truth_used]
    return pairs


def _text_equal(a: str, b: str) -> bool:
    return fuzz.ratio(normalise_text(a), normalise_text(b)) >= FIELD_TEXT_THRESHOLD


def _scalar(p: str | None, t: str | None, equal: Callable[[str, str], bool]) -> FieldCounts:
    if p is None and t is None:
        return ZERO
    if p is None:
        return FieldCounts(0, 0, 1)
    if t is None:
        return FieldCounts(0, 1, 0)
    return FieldCounts(1, 0, 0) if equal(p, t) else FieldCounts(0, 1, 1)


def _multiset(p: list[object], t: list[object]) -> FieldCounts:
    pc, tc = Counter(p), Counter(t)
    tp = sum((pc & tc).values())
    return FieldCounts(tp, sum(pc.values()) - tp, sum(tc.values()) - tp)


def _skills(f: FactVersion | None) -> list[object]:
    return [normalise_text(s) for s in f.attributes.skills] if f else []


def _metrics(f: FactVersion | None, lex: Lexicons) -> list[object]:
    if f is None:
        return []
    return [(round(m.value, 6), lex.unit_family(m.unit), m.direction.value)
            for m in f.attributes.metrics]


def _pair_counts(p: FactVersion | None, t: FactVersion | None, lex: Lexicons) -> FieldCounts:
    def get(f: FactVersion | None, name: str) -> str | None:
        if f is None:
            return None
        value = f.kind.value if name == "kind" else getattr(f.attributes, name)
        return value if value is None else str(value)

    total = _scalar(get(p, "kind"), get(t, "kind"), str.__eq__)
    total += _scalar(get(p, "title"), get(t, "title"), _text_equal)
    total += _scalar(get(p, "organisation"), get(t, "organisation"), _text_equal)
    total += _scalar(get(p, "start"), get(t, "start"), str.__eq__)
    total += _scalar(get(p, "end"), get(t, "end"), str.__eq__)
    total += _multiset(_skills(p), _skills(t))
    total += _multiset(_metrics(p, lex), _metrics(t, lex))
    return total


def field_counts(pairs: list[Pair], lex: Lexicons | None = None) -> FieldCounts:
    lex = lex or load_lexicons()
    total = ZERO
    for p, t in pairs:
        total += _pair_counts(p, t, lex)
    return total


# Running extraction for the evaluation


EVAL_CREATED_AT = datetime(2026, 10, 25, tzinfo=UTC)


def eval_document(document_id: str, path: Path) -> Document:
    photo = path.suffix.lower() == ".jpg"
    width = height = None
    if photo:
        with Image.open(path) as img:
            width, height = img.size
    return Document(document_id=document_id, owner_id=GROUND_TRUTH_OWNER, kind=DocumentKind.cv,
                    media_type="image/jpeg" if photo else "application/pdf",
                    filename=path.name, sha256="0" * 64, width_px=width, height_px=height,
                    created_at=EVAL_CREATED_AT)


def request_draft(path: Path, adapter: ModelAdapter) -> ExtractionDraft:
    """The same model request the pipeline makes for this file, at the pipeline's prompt."""
    content = path.read_bytes()
    if path.suffix.lower() == ".jpg":
        return request_photo_draft(content, "image/jpeg", adapter)
    return request_pdf_draft(extract_pages(content), adapter)


def draft_facts(draft: ExtractionDraft, doc: Document) -> list[FactVersion]:
    """Drafts become facts through the pipeline's own conversion. Sources are placeholders:
    span location and box verification are not part of field F1."""
    facts = []
    for index, item in enumerate(draft.facts, start=1):
        source: PdfTextSource | VisionSource
        if doc.media_type == "application/pdf":
            source = PdfTextSource(document_id=doc.document_id, page=1, bbox=NO_BOX,
                                   span_text=item.span_text.strip(), confidence=0.0,
                                   span_found=False)
        else:
            source = VisionSource(document_id=doc.document_id, bbox=NO_BOX, bbox_verified=False,
                                  span_text=item.span_text.strip(), confidence=0.0)
        fact = draft_to_fact(item, index, doc, source)
        if fact is not None:
            facts.append(fact)
    return facts
