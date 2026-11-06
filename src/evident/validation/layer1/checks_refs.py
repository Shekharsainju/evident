"""Metric, scale and aggregate checks: numbers in a claim must be backed by records (Task 17).

Design check table rows Metrics, Scale and Aggregates. Numbers that appear only in evidence
text, with no metric record, cannot support a claim (invariants section 1).
"""

from __future__ import annotations

from evident.contracts.enums import MetricDirection
from evident.contracts.facts import FactVersion, MetricRecord
from evident.contracts.plan import Claim
from evident.contracts.validation import CheckFailure
from evident.validation.layer1.config import Layer1Context, Lexicons, evidence_texts
from evident.validation.layer1.normalise import contains_phrase, normalise_text
from evident.validation.layer1.numbers import NumberKind, NumberMention, find_numbers

WINDOW = 60  # characters of claim text around a number that may name its metric or direction


def _fail(rule: str, phrase: str, detail: str) -> CheckFailure:
    return CheckFailure(rule=rule, phrase=phrase, detail=detail)


def _records(facts: list[FactVersion]) -> list[MetricRecord]:
    return [m for f in facts for m in f.attributes.metrics]


def _unit_matches(lex: Lexicons, claim_unit: str | None, record_unit: str) -> bool:
    record_family = lex.unit_family(record_unit)
    if claim_unit is None:
        return True
    claim_family = lex.unit_family(claim_unit)
    if record_family == "count":
        # A bare count ("1,200 survey responses") carries the thing counted as its unit.
        return claim_family not in set(lex.unit_aliases.values())
    return claim_family == record_family


def _phrases_in(window: str, table: dict[str, str] | dict[str, MetricDirection]) -> set[str]:
    return {str(v) for phrase, v in table.items() if contains_phrase(window, phrase)}


def _candidates(mention: NumberMention, norm: str, records: list[MetricRecord],
                lex: Lexicons) -> list[MetricRecord]:
    window = norm[max(0, mention.start - WINDOW): mention.end + WINDOW]
    before = norm[max(0, mention.start - WINDOW): mention.start]
    keywords = _phrases_in(window, lex.metric_keywords) or _phrases_in(norm, lex.metric_keywords)
    directions = _phrases_in(before, lex.direction_words)
    found = [r for r in records if _unit_matches(lex, mention.unit, r.unit)]
    if keywords:
        found = [r for r in found if r.metric in keywords]
    if directions:
        found = [r for r in found if r.direction.value in directions]
    return found


def _within(mention: NumberMention, record: MetricRecord) -> bool:
    """The claim may round toward zero, never away, and must keep the sign."""
    if (mention.value < 0) != (record.value < 0):
        return False
    return abs(mention.value) <= abs(record.value)


def check_metrics(claim: Claim, facts: list[FactVersion], ctx: Layer1Context
                  ) -> list[CheckFailure]:
    norm = normalise_text(claim.text)
    records = _records(facts)
    failures: list[CheckFailure] = []
    for m in find_numbers(claim.text, evidence_texts(facts), ctx.lex):
        if m.kind is not NumberKind.metric:
            continue
        found = _candidates(m, norm, records, ctx.lex)
        if not found:
            failures.append(_fail("metrics", m.span,
                                  f"unbound: no cited metric record matches '{m.span}'."))
        elif len(found) > 1:
            ids = ", ".join(r.metric_id for r in found)
            failures.append(_fail("metrics", m.span,
                                  f"ambiguous: '{m.span}' could bind to {ids}."))
        elif found[0].metric.startswith("other:"):
            failures.append(_fail("metrics_other_needs_review", m.span,
                                  f"'{m.span}' binds to an uncontrolled metric "
                                  f"{found[0].metric}, which needs user review."))
        elif not _within(m, found[0]):
            r = found[0]
            failures.append(_fail("metrics", m.span,
                                  f"'{m.span}' goes beyond the record {r.metric_id} "
                                  f"({r.value:g} {r.unit})."))
    return failures


SCALE_METRICS = {"users", "throughput"}


def check_scale(claim: Claim, facts: list[FactVersion], ctx: Layer1Context
                ) -> list[CheckFailure]:
    """A user, customer or traffic figure needs a users or throughput metric record."""
    lex = ctx.lex
    norm = normalise_text(claim.text)
    words = norm.split()
    scale_records = [r for r in _records(facts) if r.metric in SCALE_METRICS]
    ceiling = max((abs(r.value) for r in scale_records), default=None)
    failures: list[CheckFailure] = []

    def noun_follows(i: int) -> str | None:
        for j in (i + 1, i + 2):
            if j < len(words) and words[j] in lex.scale_nouns:
                return words[j]
            if j < len(words) and words[j] not in ("of", "the", "our", "active", "daily",
                                                     "monthly", "concurrent"):
                return None
        return None

    seen: set[str] = set()
    for i, w in enumerate(words):
        lower_bound: float | None = None
        if w in lex.quantity_words:
            lower_bound = lex.quantity_words[w]
        elif w.rstrip("%+").replace(".", "").isdigit():
            lower_bound = float(w.rstrip("%+"))
        else:
            continue
        noun = noun_follows(i)
        if noun is None:
            continue
        phrase = f"{w} {noun}" if words[i + 1] == noun else f"{w} {words[i + 1]} {noun}"
        if phrase in seen:
            continue
        seen.add(phrase)
        if ceiling is None:
            failures.append(_fail("scale", phrase,
                                  f"'{phrase}' has no users or throughput metric record."))
        elif lower_bound is not None and lower_bound > ceiling:
            failures.append(_fail("scale", phrase,
                                  f"'{phrase}' exceeds the recorded figure of {ceiling:g}."))
    return failures


def check_aggregates(claim: Claim, facts: list[FactVersion], ctx: Layer1Context
                     ) -> list[CheckFailure]:
    """"Three projects" must cite exactly three project facts."""
    failures: list[CheckFailure] = []
    for m in find_numbers(claim.text, evidence_texts(facts), ctx.lex):
        if m.kind is not NumberKind.aggregate or m.unit is None:
            continue
        kind = ctx.lex.aggregate_nouns[m.unit]
        count = sum(1 for f in facts if f.kind is kind)
        ok = count >= m.value if m.comparator == "ge" else count == m.value
        if not ok:
            failures.append(_fail("aggregates", m.span,
                                  f"'{m.span}' but the claim cites {count} {kind.value} "
                                  f"fact{'s' if count != 1 else ''}."))
    return failures
