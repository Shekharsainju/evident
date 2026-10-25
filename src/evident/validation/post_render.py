"""Layer 3: post-render verification (design: Grounding and validation, Layer 3; spec 8.7).

After rendering, every factual span must carry its claim ID and match the validated wording,
and every other piece of text must be template copy from the whitelist. The check is
deterministic and model-free; it catches truncation, template bugs and renderer rewriting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from evident.contracts.outputs import PostRenderResult

CLAIM_ATTR = "data-claim-id"
VERSION_ATTR = "data-claim-version"
IDENTITY_ATTR = "data-identity"
SOURCES_HEADING = "sources:"
# Elements that never have a closing tag; they must not change the nesting depth.
VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                       "meta", "param", "source", "track", "wbr"})
IGNORED_TAGS = frozenset({"script", "style"})


def collapse(text: str) -> str:
    """Whitespace normalisation only: the one difference the check allows."""
    return " ".join(text.split())


def _is_structural(text: str) -> bool:
    """Punctuation-only nodes (separators, bullets) carry no words and are allowed."""
    return not any(ch.isalnum() for ch in text)


@dataclass
class _Span:
    kind: str  # "claim" or "identity"
    key: str
    depth: int = 0
    text: list[str] = field(default_factory=list)


@dataclass
class _Seen:
    claims: list[tuple[str, str]] = field(default_factory=list)  # (id, rendered text)
    identities: list[tuple[str, str]] = field(default_factory=list)
    free_text: list[str] = field(default_factory=list)
    title: str | None = None


class _Collector(HTMLParser):
    """Collects claim spans, identity spans and every other text node."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.seen = _Seen()
        self._spans: list[_Span] = []
        self._ignore_depth = 0
        self._in_title = False
        self._title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in VOID_TAGS:
            return
        if tag in IGNORED_TAGS:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            self._ignore_depth += 1
            return
        if tag == "title":
            self._in_title = True
        attributes = dict(attrs)
        claim_id = attributes.get(CLAIM_ATTR)
        identity = attributes.get(IDENTITY_ATTR)
        if claim_id:
            self._spans.append(_Span("claim", claim_id))
        elif identity:
            self._spans.append(_Span("identity", identity))
        elif self._spans:
            self._spans[-1].depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return  # self-closing: no text, no depth change

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if self._ignore_depth:
            self._ignore_depth -= 1
            return
        if tag == "title":
            self._in_title = False
            self.seen.title = collapse("".join(self._title))
            return
        if not self._spans:
            return
        span = self._spans[-1]
        if span.depth:
            span.depth -= 1
            return
        self._spans.pop()
        text = collapse("".join(span.text))
        target = self.seen.claims if span.kind == "claim" else self.seen.identities
        target.append((span.key, text))

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        if self._in_title:
            self._title.append(data)
            return
        if self._spans:
            self._spans[-1].text.append(data)
            return
        text = collapse(data)
        if text:
            self.seen.free_text.append(text)


def verify_html(
    html: str, expected: dict[str, str], identity: dict[str, str], whitelist: set[str]
) -> PostRenderResult:
    """Every claim span matches its validated wording; everything else is template copy.

    `expected` maps claim ID to the validated wording for this output. `identity` maps
    identity keys (name, email) to the values the renderer was given. `whitelist` holds the
    template copy, compared after whitespace collapse.
    """
    collector = _Collector()
    collector.feed(html)
    collector.close()
    seen = collector.seen
    allowed = {collapse(w) for w in whitelist}
    problems: list[str] = []

    rendered_ids: set[str] = set()
    for claim_id, text in seen.claims:
        rendered_ids.add(claim_id)
        wanted = expected.get(claim_id)
        if wanted is None:
            problems.append(f"unknown claim id {claim_id!r} in the rendered output")
        elif text != collapse(wanted):
            problems.append(f"claim {claim_id}: rendered text differs from the validated "
                            f"wording (rendered {text!r})")
    for claim_id in expected:
        if claim_id not in rendered_ids:
            problems.append(f"claim {claim_id} is missing from the rendered output")

    for key, text in seen.identities:
        wanted = identity.get(key)
        if wanted is None:
            problems.append(f"unknown identity field {key!r} in the rendered output")
        elif text != collapse(wanted):
            problems.append(f"identity {key}: rendered {text!r}, expected {collapse(wanted)!r}")

    if seen.title is not None and seen.title and seen.title not in allowed:
        problems.append(f"title {seen.title!r} is not template copy")
    for text in seen.free_text:
        if text not in allowed and not _is_structural(text):
            problems.append(f"text {text!r} has no claim id and is not template copy")

    return PostRenderResult(passed=not problems, problems=problems)


# PPTX


def _shape_paragraphs(shape: Any) -> list[str]:
    """Non-empty paragraph texts in a shape, descending into groups and tables."""
    out: list[str] = []
    if getattr(shape, "shape_type", None) == 6 and hasattr(shape, "shapes"):  # group
        for inner in shape.shapes:
            out.extend(_shape_paragraphs(inner))
        return out
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            for cell in row.cells:
                out.extend(collapse(p.text) for p in cell.text_frame.paragraphs if p.text.strip())
        return out
    if getattr(shape, "has_text_frame", False):
        out.extend(collapse(p.text) for p in shape.text_frame.paragraphs if p.text.strip())
    return out


def _note_claim_ids(notes_text: str) -> list[str]:
    """Claim IDs from the `Sources:` block of a slide's notes (Task 13 format)."""
    ids: list[str] = []
    in_sources = False
    for raw in notes_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower() == SOURCES_HEADING:
            in_sources = True
            continue
        if in_sources:
            head, sep, _ = line.partition(":")
            if sep and head.strip():
                ids.append(head.strip())
    return ids


def verify_pptx(path: Path, expected: dict[str, str], whitelist: set[str]) -> PostRenderResult:
    """Lighter check for the deck (spec 8.7): body text is a claim or template copy, and
    every claim ID named in the speaker notes exists in the validated plan."""
    from pptx import Presentation

    allowed = {collapse(w) for w in whitelist}
    wordings = {collapse(w) for w in expected.values()}
    problems: list[str] = []
    prs = Presentation(str(path))
    for number, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            for text in _shape_paragraphs(shape):
                if text in wordings or text in allowed or _is_structural(text):
                    continue
                problems.append(f"slide {number}: body text {text!r} is neither a validated "
                                f"claim nor template copy")
        if slide.has_notes_slide:
            for claim_id in _note_claim_ids(slide.notes_slide.notes_text_frame.text):
                if claim_id not in expected:
                    problems.append(f"slide {number}: notes cite unknown claim id {claim_id!r}")
    return PostRenderResult(passed=not problems, problems=problems)
