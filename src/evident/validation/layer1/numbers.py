"""Find every number in a claim and say what kind it is (plan Task 16).

Classification order, from the plan: date, duration, aggregate, identifier, metric. Identifiers
(subject codes, version numbers) are numbers that appear verbatim in the evidence next to a
word; they are not figures and must not be sent to the metric check (Review Focus 1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from evident.validation.layer1.config import Lexicons
from evident.validation.layer1.normalise import normalise_text

_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4,
    "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_SEASONS = {"summer": (12, 2), "autumn": (3, 5), "fall": (3, 5), "winter": (6, 8),
            "spring": (9, 11), "semester": (1, 12), "q1": (1, 3), "q2": (4, 6), "q3": (7, 9),
            "q4": (10, 12)}
# Words that open a written date ("Mar 2025", "Summer 2024"), for checks that must skip dates.
DATE_WORDS = frozenset(_MONTHS) | frozenset(s for s in _SEASONS if s != "semester")
_DURATION_UNITS = {"year": 12.0, "years": 12.0, "yr": 12.0, "yrs": 12.0, "month": 1.0,
                   "months": 1.0, "mo": 1.0, "mos": 1.0, "week": 12 / 52, "weeks": 12 / 52,
                   "wk": 12 / 52, "wks": 12 / 52}
_GE_BEFORE = ("over", "more than", "at least", "above", "upwards of", "exceeding", "beyond",
              "greater than", "no fewer than", "in excess of")
_GLUE = {"of", "a", "an", "the", "and", "by", "to", "in", "on", "than", "percent", "%"}

YEAR_MIN, YEAR_MAX = 1990, 2039
_NUMBER = re.compile(r"^\$?(\d+(?:\.\d+)?)([km])?(%|\+)?$")


class NumberKind(StrEnum):
    metric = "metric"
    date = "date"
    duration = "duration"
    aggregate = "aggregate"
    identifier = "identifier"


@dataclass(frozen=True)
class NumberMention:
    value: float
    unit: str | None
    comparator: Literal["eq", "ge"]
    kind: NumberKind
    span: str
    start: int
    end: int


@dataclass(frozen=True)
class _Tok:
    text: str
    start: int
    end: int


def _tokenise(text: str) -> list[_Tok]:
    out: list[_Tok] = []
    for m in re.finditer(r"\S+", text):
        out.append(_Tok(m.group(0), m.start(), m.end()))
    return out


def _words_to_number(toks: list[_Tok], i: int) -> tuple[float, int] | None:
    """Parse number words starting at toks[i]. Returns (value, next index) or None."""
    total = 0.0
    current = 0.0
    j = i
    seen = False
    while j < len(toks):
        w = toks[j].text
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w in _SCALES:
            if not seen:
                current = 1
            current *= _SCALES[w]
            if _SCALES[w] >= 1000:
                total += current
                current = 0
        elif w == "and" and seen and j + 1 < len(toks) and toks[j + 1].text in (
            _UNITS | _TENS
        ):
            j += 1
            continue
        else:
            break
        seen = True
        j += 1
    if not seen:
        return None
    return total + current, j


def _digits(tok: str) -> tuple[float, bool, bool] | None:
    """Return (value, is_percent, has_plus) for a digit token, else None."""
    m = _NUMBER.match(tok)
    if not m:
        return None
    value = float(m.group(1))
    if m.group(2) == "k":
        value *= 1_000
    elif m.group(2) == "m":
        value *= 1_000_000
    return value, m.group(3) == "%", m.group(3) == "+"


def _preceded_by_ge(text: str, start: int) -> bool:
    before = text[:start].rstrip()
    return any(before.endswith(p) for p in _GE_BEFORE)


def _lookup_phrase(words: list[str], table: dict[str, object]) -> str | None:
    """Longest phrase (up to 3 words) at the start of words that is a key in table."""
    for n in (3, 2, 1):
        phrase = " ".join(words[:n])
        if len(words) >= n and phrase in table:
            return phrase
    return None


def _is_identifier(norm_claim: str, number_text: str, start: int, end: int,
                   evidence: list[str]) -> bool:
    """Codes lead a name ("43007 Advanced AI") and versions trail one ("Python 3").

    The pair must appear verbatim in an evidence string with the number as its first or
    last token. A figure quoted from the middle of a sentence ("covered 1,200 responses")
    is not an identifier, so it still has to bind to a metric record.
    """
    before = norm_claim[:start].split()
    after = norm_claim[end:].split()
    for ev in evidence:
        words = ev.split()
        if len(words) < 2:
            continue
        if after and after[0].isalpha() and words[0] == number_text and words[1] == after[0]:
            return True
        if before and before[-1].isalpha() and words[-1] == number_text \
                and words[-2] == before[-1]:
            return True
    return False


def find_numbers(claim_text: str, evidence_texts: list[str], lex: Lexicons) -> list[NumberMention]:
    norm = normalise_text(claim_text)
    evidence = [normalise_text(e) for e in evidence_texts]
    toks = _tokenise(norm)
    out: list[NumberMention] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        parsed = _digits(tok.text)
        next_i = i + 1
        is_percent = has_plus = False
        if parsed is None:
            words = _words_to_number(toks, i)
            if words is None:
                i += 1
                continue
            value, next_i = words
        else:
            value, is_percent, has_plus = parsed
        start, end = tok.start, toks[next_i - 1].end
        span = norm[start:end]
        rest = [t.text for t in toks[next_i:]]
        comparator: Literal["eq", "ge"] = "ge" if has_plus or _preceded_by_ge(norm, start) else "eq"
        unit: str | None = None
        kind: NumberKind
        following = rest[0] if rest else ""
        if following in ("percent", "%"):
            is_percent = True
            rest = rest[1:]
            end = toks[next_i].end
            next_i += 1
            span = norm[start:end]
        bare = tok.text.lstrip("$").rstrip("%+")
        is_year = (parsed is not None and bare.isdigit() and YEAR_MIN <= int(bare) <= YEAR_MAX
                   and not is_percent and not has_plus)
        if is_year:
            kind = NumberKind.date
        elif rest and rest[0] in _DURATION_UNITS and not is_percent:
            kind = NumberKind.duration
            unit = rest[0]
            end = toks[next_i].end
            next_i += 1
            span = norm[start:end]
        elif (noun := _lookup_phrase(rest, dict(lex.aggregate_nouns))) is not None \
                and not is_percent:
            kind = NumberKind.aggregate
            unit = noun
        elif parsed is not None and not is_percent and _is_identifier(
                norm, bare, start, end, evidence):
            kind = NumberKind.identifier
        else:
            kind = NumberKind.metric
            if is_percent:
                unit = "percent"
            elif tok.text.startswith("$"):
                unit = "usd"
            elif rest and rest[0] not in _GLUE and not rest[0][:1].isdigit():
                unit = rest[0]
        out.append(NumberMention(value, unit, comparator, kind, span, start, end))
        i = next_i
    # "march 2024" and "summer 2024" are dates because the year token itself is one;
    # parse_date_range narrows them to the month or season.
    return out


def parse_date_range(span_before: str, year: int) -> tuple[str, str]:
    """Year-month range a claimed date covers. span_before holds the words before the year."""
    words = span_before.split()
    last = words[-1] if words else ""
    if last in _MONTHS:
        ym = f"{year:04d}-{_MONTHS[last]:02d}"
        return ym, ym
    if last in _SEASONS:
        a, b = _SEASONS[last]
        if a > b:  # summer wraps the year end
            return f"{year - 1:04d}-{a:02d}", f"{year:04d}-{b:02d}"
        return f"{year:04d}-{a:02d}", f"{year:04d}-{b:02d}"
    return f"{year:04d}-01", f"{year:04d}-12"


def duration_months(mention: NumberMention) -> float:
    return mention.value * _DURATION_UNITS.get(mention.unit or "", 1.0)
