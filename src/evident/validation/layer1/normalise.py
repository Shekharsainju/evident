"""Text normalisation shared by every Layer 1 check (design: Deterministic check rules).

The claim and the evidence go through the same function, so wording differences in case,
dashes, quotes and punctuation do not cause false rejections.
"""

from __future__ import annotations

import re
import unicodedata

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = {
    ord("‘"): "'", ord("’"): "'", ord("‚"): "'", ord("‛"): "'",
    ord("“"): '"', ord("”"): '"', ord("„"): '"', ord("«"): '"',
    ord("»"): '"',
}
# Keep ".", "%" and "$" only when they sit inside or against a number ("2.5", "40%", "$2k").
_NUMBER_PUNCT = re.compile(r"(?<=\d)%|\$(?=\d)|(?<=\d)\.(?=\d)")
_PLACEHOLDER = "\x00"
_PUNCT = re.compile(r"[^\w\s\x00+#]")  # "+" and "#" stay for c++, c#, "40+"
_SPACES = re.compile(r"\s+")


def normalise_text(s: str) -> str:
    """NFKC, lowercase, unified dashes and quotes, punctuation stripped, whitespace collapsed."""
    text = unicodedata.normalize("NFKC", s).lower()
    text = text.translate(_DASHES).translate(_QUOTES)
    text = text.replace(",", "")  # thousands separators
    kept: list[str] = []

    def keep(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return _PLACEHOLDER

    text = _NUMBER_PUNCT.sub(keep, text)
    text = _PUNCT.sub(" ", text)
    for symbol in kept:
        text = text.replace(_PLACEHOLDER, symbol, 1)
    # A "+" or "#" that is not glued to a token is punctuation.
    text = re.sub(r"(?<![\w+#])[+#](?![\w+#])", " ", text)
    return _SPACES.sub(" ", text).strip()


def tokens(s: str) -> list[str]:
    return normalise_text(s).split()


def contains_phrase(haystack: str, phrase: str) -> bool:
    """Whole-word phrase match on already normalised text."""
    return f" {phrase} " in f" {haystack} "
