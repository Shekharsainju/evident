"""Scope checks: dates, durations, ownership, deployment, skills and entities (Task 18).

Design check table rows Durations, Dates, Ownership, Deployment, Skills and Entities.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from evident.contracts.enums import Deployment, Ownership
from evident.contracts.facts import FactVersion
from evident.contracts.plan import Claim
from evident.contracts.validation import CheckFailure
from evident.validation.layer1.config import Aliases, Layer1Context, evidence_texts
from evident.validation.layer1.normalise import contains_phrase, normalise_text
from evident.validation.layer1.numbers import (
    DATE_WORDS,
    YEAR_MAX,
    YEAR_MIN,
    NumberKind,
    duration_months,
    find_numbers,
    parse_date_range,
)

OWNERSHIP_RANK = {v: i + 1 for i, v in enumerate(Ownership)}
DEPLOYMENT_RANK = {v: i + 1 for i, v in enumerate(Deployment)}
CONNECTORS = {"of", "and", "&", "the", "for", "in", "at", "on", "de"}
_CAP_WORD = r"(?:[A-Z][\w+#.'-]*|\d+[\w+#.-]*)"
_CAP_GAP = r"\s+(?:(?:of|and|&|the|for|in|at|on)\s+)?"
_CAP_RUN = re.compile(rf"{_CAP_WORD}(?:{_CAP_GAP}{_CAP_WORD})+")
_EVIDENCE_NAME = re.compile(rf"{_CAP_WORD}(?:{_CAP_GAP}{_CAP_WORD})*")
# A month or season directly before a year, with an optional day first: "Mar 2025",
# "3 June 2025". Only with a year, so a name that starts with a month word ("March Networks")
# is still a name. Not "June 3, 2025": the date rule reads only the word before the year, so
# it would check the year and not the month, and cutting it out here would pass it unchecked.
_DATE_SPAN = re.compile(
    rf"\b(?:\d{{1,2}}\s+)?(?:{'|'.join(sorted(DATE_WORDS, key=len, reverse=True))})\.?"
    r"\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
# Capitalised words that may open a date at the start of a sentence ("Since Feb 2024, ...").
_DATE_LEADS = {"since", "from", "during", "until", "till", "by", "before", "after", "between",
               "through", "throughout", "around"}


def _fail(rule: str, phrase: str, detail: str) -> CheckFailure:
    return CheckFailure(rule=rule, phrase=phrase, detail=detail)


# Month arithmetic


def _index(ym: str) -> int:
    year, month = ym.split("-")
    return int(year) * 12 + int(month) - 1


def _fact_range(fact: FactVersion, as_of: str) -> tuple[int, int] | None:
    a = fact.attributes
    if a.start is None and a.end is None:
        return None
    start = _index(a.start) if a.start else _index(a.end or as_of)
    end = _index(a.end) if a.end else _index(as_of)
    return (start, end) if start <= end else (end, start)


def _union_months(facts: Iterable[FactVersion], as_of: str) -> int:
    months: set[int] = set()
    for f in facts:
        r = _fact_range(f, as_of)
        if r is not None:
            months.update(range(r[0], r[1] + 1))
    return len(months)


# Phrase lookup


def _phrases(norm: str, table: Iterable[str]) -> list[str]:
    return [p for p in table if contains_phrase(norm, p)]


def claimed_skills(norm: str, aliases: Aliases) -> set[str]:
    """Canonical names of every skill alias that appears in the normalised claim."""
    return {canonical for alias, canonical in aliases.skills.items()
            if contains_phrase(norm, alias)}


def _fact_skills(fact: FactVersion, aliases: Aliases) -> set[str]:
    return {aliases.canonical_skill(s) or normalise_text(s) for s in fact.attributes.skills}


def _aliases_of(canonical: str, aliases: Aliases) -> list[str]:
    return [alias for alias, c in aliases.skills.items() if c == canonical]


def _evidence_norm(facts: list[FactVersion]) -> str:
    parts = list(evidence_texts(facts))
    for f in facts:
        parts.extend(x for x in (f.attributes.title, f.attributes.organisation) if x)
        parts.extend(f.attributes.skills)
    return " | ".join(normalise_text(p) for p in parts)


def _evidence_names(facts: list[FactVersion]) -> set[str]:
    """Whole names in the evidence: titles, organisations, skills and capitalised runs in the
    text. A lowercase prose word ("top marks") is not a name, and neither is a lone word that
    opens a sentence ("Young users liked it"). A longer run is kept only whole: dropping its
    first word would turn "Dr Johnson" or "Goldman Sachs" into a name it is not. Runs are
    split at the joiners, as on the claim side: "Interned at Acme" names "Acme"."""
    names: set[str] = set()
    for f in facts:
        names.update(normalise_text(x) for x in (f.attributes.title, f.attributes.organisation)
                     if x)
        names.update(normalise_text(x) for x in f.attributes.skills)
        for text in (f.text, f.source.span_text):
            for m in _EVIDENCE_NAME.finditer(text):
                words = m.group(0).split()
                before = text[:m.start()].rstrip(" \t")
                at_start = not before or before[-1] in _LINE_OPENERS
                if not (at_start and len(words) == 1):
                    names.add(normalise_text(" ".join(words)))
                pieces: list[list[str]] = [[]]
                for word in words:
                    if word in _JOINERS:
                        pieces.append([])
                    else:
                        pieces[-1].append(word)
                for i, piece in enumerate(pieces):
                    if piece and not (i == 0 and at_start and len(piece) == 1):
                        names.add(normalise_text(" ".join(piece)))
    names.discard("")
    return names


# Evidence is often line-broken or bulleted span text, so a word after a line break, a
# bullet or an opening bracket opens a sentence as much as one after a full stop.
_LINE_OPENERS = frozenset(".;:!?\n\r([\"'*-\u2022\u00b7\u2013\u2014\u201c\u2018")


# Checks


def check_dates(claim: Claim, facts: list[FactVersion], ctx: Layer1Context) -> list[CheckFailure]:
    """Each claimed date overlaps at least one cited fact's range, ongoing roles to as_of."""
    norm = normalise_text(claim.text)
    ranges = [r for f in facts if (r := _fact_range(f, ctx.as_of)) is not None]
    failures: list[CheckFailure] = []
    for m in find_numbers(claim.text, evidence_texts(facts), ctx.lex):
        if m.kind is not NumberKind.date:
            continue
        lo, hi = parse_date_range(norm[:m.start], int(m.value))
        a, b = _index(lo), _index(hi)
        if not any(max(a, r0) <= min(b, r1) for r0, r1 in ranges):
            phrase = " ".join((norm[:m.start].split()[-1:]) + [m.span])
            failures.append(_fail("dates", phrase,
                                  f"'{phrase}' is outside every cited fact's dates."))
    return failures


def check_durations(claim: Claim, facts: list[FactVersion], ctx: Layer1Context
                    ) -> list[CheckFailure]:
    """A duration may not exceed the months of cited facts naming that skill or role."""
    norm = normalise_text(claim.text)
    failures: list[CheckFailure] = []
    mentions = [m for m in find_numbers(claim.text, evidence_texts(facts), ctx.lex)
                if m.kind is NumberKind.duration]
    if not mentions:
        return failures
    skills = claimed_skills(norm, ctx.aliases)
    if skills:
        available = min(
            _union_months((f for f in facts if s in _fact_skills(f, ctx.aliases)), ctx.as_of)
            for s in skills
        )
        subject = ", ".join(sorted(skills))
    else:
        by_title = [f for f in facts
                    if f.attributes.title and contains_phrase(norm,
                                                              normalise_text(f.attributes.title))]
        available = _union_months(by_title or facts, ctx.as_of)
        subject = "the cited facts"
    for m in mentions:
        if duration_months(m) > available:
            failures.append(_fail("durations", m.span,
                                  f"'{m.span}' but {subject} cover {available} months."))
    return failures


def _rank_check(rule: str, norm: str, words: dict[str, int], fact_ranks: list[int]
                ) -> list[CheckFailure]:
    found = _phrases(norm, words)
    if not found:
        return []
    top = max(found, key=lambda w: words[w])
    allowed = min(fact_ranks) if fact_ranks else 1
    if words[top] <= allowed:
        return []
    return [_fail(rule, top, f"'{top}' is rank {words[top]}; the cited facts allow rank "
                             f"{allowed}.")]


def check_ownership(claim: Claim, facts: list[FactVersion], ctx: Layer1Context
                    ) -> list[CheckFailure]:
    ranks = [OWNERSHIP_RANK[f.attributes.ownership] for f in facts
             if f.attributes.ownership is not None]
    return _rank_check("ownership", normalise_text(claim.text), ctx.lex.ownership, ranks)


def check_deployment(claim: Claim, facts: list[FactVersion], ctx: Layer1Context
                     ) -> list[CheckFailure]:
    ranks = [DEPLOYMENT_RANK[f.attributes.deployment] for f in facts
             if f.attributes.deployment is not None]
    return _rank_check("deployment", normalise_text(claim.text), ctx.lex.deployment, ranks)


def check_skills(claim: Claim, facts: list[FactVersion], ctx: Layer1Context
                 ) -> list[CheckFailure]:
    """Every skill named in the claim is in a cited fact's skills or evidence text."""
    norm = normalise_text(claim.text)
    evidence = _evidence_norm(facts)
    known = set[str]().union(*(_fact_skills(f, ctx.aliases) for f in facts)) if facts else set()
    failures: list[CheckFailure] = []
    for skill in sorted(claimed_skills(norm, ctx.aliases)):
        if skill in known:
            continue
        if any(contains_phrase(evidence, alias) for alias in _aliases_of(skill, ctx.aliases)):
            continue
        failures.append(_fail("skills", skill, f"'{skill}' is not in any cited fact."))
    return failures


_JOINERS = {"at", "for", "in", "on"}


def _date_spans(text: str) -> list[tuple[int, int]]:
    """Written dates the date rule reads (years YEAR_MIN to YEAR_MAX), as character spans."""
    return [m.span() for m in _DATE_SPAN.finditer(text)
            if YEAR_MIN <= int(m.group("year")) <= YEAR_MAX]


def _split_on_and(words: list[str]) -> list[list[str]]:
    parts: list[list[str]] = [[]]
    for word in words:
        if word == "and":
            parts.append([])
        else:
            parts[-1].append(word)
    return [p for p in parts if p]


def _pieces(text: str, start: int, end: int, dates: list[tuple[int, int]]
            ) -> list[tuple[str, bool, bool]]:
    """A run's text with written dates cut out, each piece with whether a date was just
    before it and just after it."""
    pieces: list[tuple[str, bool, bool]] = []
    pos = start
    for a, b in dates:
        if b <= start or a >= end:
            continue
        pieces.append((text[pos:max(a, pos)], pos != start, True))
        pos = max(pos, b)
    pieces.append((text[pos:end], pos != start, False))
    return pieces


def _name_runs(text: str) -> list[tuple[list[str], bool, bool]]:
    """Capitalised runs split into parts, each with whether it opens a sentence and whether
    it touches a written date. Dates are cut out: the date rule checks them."""
    runs: list[tuple[list[str], bool, bool]] = []
    dates = _date_spans(text)
    for m in _CAP_RUN.finditer(text):
        at_start = m.start() == 0 or text[:m.start()].rstrip().endswith((".", ";", ":"))
        for piece, date_before, date_after in _pieces(text, m.start(), m.end(), dates):
            words = piece.split()
            while words and words[0] in ("and", "&"):
                words.pop(0)
            while words and words[-1] in ("and", "&"):
                words.pop()
            parts: list[list[str]] = [[]]
            for word in words:
                if word in _JOINERS:
                    parts.append([])
                else:
                    parts[-1].append(word)
            # "Since Feb 2024": a preposition that opens the run and the date, not a name.
            # After a joiner ("at After Mar 2025") the word stands where a name would.
            if (date_after and not date_before and len(parts) == 1 and len(parts[0]) == 1
                    and parts[0][0].lower() in _DATE_LEADS):
                parts = [[]]
            last = len(parts) - 1
            for i, part in enumerate(parts):
                if part:
                    by_date = (i == 0 and date_before) or (i == last and date_after)
                    runs.append((part, at_start, by_date))
                    at_start = False
            at_start = False
    return runs


def _name_supported(words: list[str], evidence: str, names: set[str], aliases: Aliases,
                    strict: bool = False) -> bool:
    """`strict` is for one item of an "and" list, or words left beside a removed date. They
    must equal a whole name in the evidence (`names`): "Johnson" is not supported by
    "Dr Johnson", nor "Amazon" by "Amazon Web Services". A single word there is not skipped
    as sentence noise."""
    run_norm = normalise_text(" ".join(words))
    norm_words = run_norm.split()
    if strict and run_norm in aliases.skills:
        # A skill alias in the name slot ("at Networks Mar 2025") must still be a cited
        # name, under any spelling of the same skill.
        canonical = aliases.canonical_skill(run_norm)
        return run_norm in names or any(aliases.canonical_skill(n) == canonical for n in names)
    if not norm_words or all(w in CONNECTORS or w in aliases.skills for w in norm_words):
        return True  # a list of skills, handled by check_skills
    if run_norm in aliases.skills:
        return True
    if len(norm_words) == 1 and run_norm not in aliases.entities and not strict:
        return True  # single capitalised words are too noisy to judge
    def found(phrase: str) -> bool:
        return phrase in names if strict else contains_phrase(evidence, phrase)

    spellings = [run_norm]
    canonical = aliases.canonical_entity(run_norm)
    if canonical is not None:
        spellings.extend(a for a, c in aliases.entities.items() if c == canonical)
    if any(found(s) for s in spellings):
        return True
    # Drop skill words and connectors at the edges ("Python Developer") and look again.
    core = [w for w in norm_words if w not in aliases.skills and w not in CONNECTORS]
    return len(core) >= 2 and found(" ".join(core))


def check_entities(claim: Claim, facts: list[FactVersion], ctx: Layer1Context
                   ) -> list[CheckFailure]:
    """Seniority and credential words, and named organisations or titles, must be in evidence."""
    norm = normalise_text(claim.text)
    evidence = _evidence_norm(facts)
    names = _evidence_names(facts)
    failures: list[CheckFailure] = []
    for word in _phrases(norm, ctx.lex.seniority_words | ctx.lex.credential_words):
        if not contains_phrase(evidence, word):
            failures.append(_fail("entities", word,
                                  f"'{word}' is not supported by the cited evidence."))

    def supported(words: list[str], strict: bool) -> bool:
        return _name_supported(words, evidence, names, ctx.aliases, strict)

    def known_verb(word: str) -> bool:
        # Ownership words are all past-tense verbs; deployment also holds adjectives and
        # nouns ("Internal", "Live", "Pilot") that start real names, so only its "-ed" forms.
        w = normalise_text(word)
        return w in ctx.lex.ownership or (w in ctx.lex.deployment and w.endswith("ed"))

    for words, at_start, by_date in _name_runs(claim.text):
        if supported(words, by_date):
            continue
        # A sentence-initial verb ("Built Team Course Planner") is not part of the name. On a
        # strict part only a known verb is dropped: in "Goldman Sachs Mar 2025" the first
        # word belongs to the name.
        if (at_start and len(words) > 1 and (not by_date or known_verb(words[0]))
                and supported(words[1:], by_date)):
            continue
        parts = _split_on_and(words)
        if len(parts) > 1:
            # "Team Course Planner and Text Classification Study" is two names, each of
            # which must be supported on its own.
            for i, part in enumerate(parts):
                verb_first = i == 0 and at_start and len(part) > 1 and known_verb(part[0])
                if supported(part, True) or (verb_first and supported(part[1:], True)):
                    continue
                run = " ".join(part[1:] if verb_first else part)
                failures.append(_fail("entities", run,
                                      f"'{run}' is a name that no cited fact mentions."))
            continue
        run = " ".join(words[1:] if at_start and len(words) > 2 else words)
        failures.append(_fail("entities", run,
                              f"'{run}' is a name that no cited fact mentions."))
    return failures
