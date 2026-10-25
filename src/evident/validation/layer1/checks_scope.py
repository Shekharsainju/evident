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
    NumberKind,
    duration_months,
    find_numbers,
    parse_date_range,
)

OWNERSHIP_RANK = {v: i + 1 for i, v in enumerate(Ownership)}
DEPLOYMENT_RANK = {v: i + 1 for i, v in enumerate(Deployment)}
CONNECTORS = {"of", "and", "&", "the", "for", "in", "at", "on", "de"}
_CAP_WORD = r"(?:[A-Z][\w+#.'-]*|\d+[\w+#.-]*)"
_CAP_RUN = re.compile(rf"{_CAP_WORD}(?:\s+(?:(?:of|and|&|the|for|in|at|on)\s+)?{_CAP_WORD})+")


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


def _name_runs(text: str) -> list[tuple[list[str], bool]]:
    """Capitalised runs split into parts, each with whether it opens a sentence."""
    runs: list[tuple[list[str], bool]] = []
    for m in _CAP_RUN.finditer(text):
        at_start = m.start() == 0 or text[:m.start()].rstrip().endswith((".", ";", ":"))
        part: list[str] = []
        for word in m.group(0).split():
            if word in _JOINERS:
                if part:
                    runs.append((part, at_start))
                    at_start = False
                part = []
            else:
                part.append(word)
        if part:
            runs.append((part, at_start))
    return runs


def _name_supported(words: list[str], evidence: str, aliases: Aliases) -> bool:
    run_norm = normalise_text(" ".join(words))
    norm_words = run_norm.split()
    if not norm_words or all(w in CONNECTORS or w in aliases.skills for w in norm_words):
        return True  # a list of skills, handled by check_skills
    if run_norm in aliases.skills:
        return True
    if len(norm_words) == 1 and run_norm not in aliases.entities:
        return True  # single capitalised words are too noisy to judge
    spellings = [run_norm]
    canonical = aliases.canonical_entity(run_norm)
    if canonical is not None:
        spellings.extend(a for a, c in aliases.entities.items() if c == canonical)
    if any(contains_phrase(evidence, s) for s in spellings):
        return True
    # Drop skill words and connectors at the edges ("Python Developer") and look again.
    core = [w for w in norm_words if w not in aliases.skills and w not in CONNECTORS]
    return len(core) >= 2 and contains_phrase(evidence, " ".join(core))


def check_entities(claim: Claim, facts: list[FactVersion], ctx: Layer1Context
                   ) -> list[CheckFailure]:
    """Seniority and credential words, and named organisations or titles, must be in evidence."""
    norm = normalise_text(claim.text)
    evidence = _evidence_norm(facts)
    failures: list[CheckFailure] = []
    for word in _phrases(norm, ctx.lex.seniority_words | ctx.lex.credential_words):
        if not contains_phrase(evidence, word):
            failures.append(_fail("entities", word,
                                  f"'{word}' is not supported by the cited evidence."))
    for words, at_start in _name_runs(claim.text):
        if _name_supported(words, evidence, ctx.aliases):
            continue
        # A sentence-initial verb ("Built Team Course Planner") is not part of the name.
        if at_start and len(words) > 1 and _name_supported(words[1:], evidence, ctx.aliases):
            continue
        run = " ".join(words[1:] if at_start and len(words) > 2 else words)
        failures.append(_fail("entities", run,
                              f"'{run}' is a name that no cited fact mentions."))
    return failures
