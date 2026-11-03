"""Claim grounding evaluation (spec 9.2): a labelled claim set and the rates it yields.

Supported claims are template rephrasings of ground-truth facts. Each unsupported claim is
one mutation of a supported claim in one adversarial category, so its label comes from how
it was built. Every claim is hand-checked before any test-split call (claims_review.md).
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from evident.contracts.enums import (
    ClaimOutcome,
    Deployment,
    FactKind,
    OutputType,
    Ownership,
    Verdict,
)
from evident.contracts.facts import FactRef, FactVersion, MetricRecord
from evident.contracts.plan import Claim
from evident.contracts.validation import ClaimValidation
from evident.eval.assets import month
from evident.eval.datasets import GROUND_TRUTH_OWNER, load_ground_truth
from evident.eval.metrics import Rate
from evident.models.adapter import ModelAdapter
from evident.settings import Settings
from evident.validation.layer1.config import Layer1Context, load_aliases, load_lexicons
from evident.validation.outcome import validate_claim


class Category(StrEnum):
    wrong_number = "wrong_number"
    wrong_date = "wrong_date"
    inflated_ownership = "inflated_ownership"
    inflated_deployment = "inflated_deployment"
    unsupported_skill = "unsupported_skill"
    wrong_entity = "wrong_entity"
    fake_id = "fake_id"
    wrong_aggregate = "wrong_aggregate"
    paraphrase_overstatement = "paraphrase_overstatement"


Label = Literal["supported", "unsupported"]
Split = Literal["dev", "test"]

DEFAULT_AS_OF: str = Settings.model_fields["as_of"].default
DEV_PROFILES = ("student_profile_01", "student_profile_02")
TEST_PROFILES = ("student_profile_03", "student_profile_04", "student_profile_05")
DEV_SUPPORTED = 20
DEV_UNSUPPORTED = 20
TEST_SUPPORTED = 40
TEST_PER_CATEGORY = 5


class LabelledClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: Claim
    label: Label
    category: Category | None
    profile_id: str
    split: Split
    template: str
    # For a mutation: the supported template instance it came from, and that claim's text
    # and evidence, so a reviewer can see exactly what changed.
    mutated_from: str | None = None
    base_text: str | None = None
    base_evidence: list[FactRef] | None = None


# Templates

OWNERSHIP_VERB = {Ownership.contributed: "Contributed to", Ownership.built: "Built",
                  Ownership.led: "Led"}
DEPLOYMENT_PHRASE = {Deployment.concept: "as a concept", Deployment.prototype: "as a prototype",
                     Deployment.internal: "for internal use",
                     Deployment.production: "in production"}
DEPLOYMENT_ORDER = list(Deployment)
NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
# Metrics where a smaller number is the stronger claim.
LOWER_IS_BETTER = {"latency", "cost", "error_rate"}
OUTSIDE_SKILLS = ["Kubernetes", "Rust", "TensorFlow", "React", "AWS", "Terraform",
                  "Apache Spark", "Go"]
OTHER_EMPLOYERS = ["Fictional national bank", "Fictional consulting firm",
                   "Fictional games studio"]
OTHER_INSTITUTIONS = ["Fictional Institute of Technology", "Fictional State University"]
OVERSTATED_TAILS = [", and it became the tool the whole faculty relies on.",
                    ", delivering results that far exceeded everyone's expectations.",
                    ", and it is now regarded as the best project in the cohort."]
OVERSTATED_SKILL = ["Is an expert in {skill}.", "Has deep, advanced mastery of {skill}."]
OVERSTATED_ROLE_TAIL = ", where the work transformed how the whole organisation operates."
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass(frozen=True)
class Instance:
    """One supported claim built from a template, before it gets an ID."""

    key: str
    template: str
    text: str
    refs: tuple[FactRef, ...]
    section: str
    facts: tuple[FactVersion, ...]
    metric: MetricRecord | None = None


@dataclass(frozen=True)
class Mutation:
    category: Category
    base: Instance
    text: str
    refs: tuple[FactRef, ...]


def _ref(f: FactVersion) -> FactRef:
    return FactRef(fact_id=f.fact_id, version=f.version)


def _span_sentence(span: str) -> str:
    return span[0].upper() + span[1:] if span else span


def _article(word: str) -> str:
    # "an IT Support Assistant": the letter's sound decides, so initialisms take "an".
    first = word.split()[0] if word.split() else word
    vowel_sound = first[0].lower() in "aeiou" or (first.isupper() and first[0] in "AEFHILMNORSX")
    return "an" if vowel_sound else "a"


def _dates(start: str | None, end: str | None) -> str:
    assert start is not None
    return f"from {month(start)} to {month(end) if end else 'the present'}"


def _instances(profile_id: str) -> list[Instance]:
    facts = load_ground_truth(profile_id)
    out: list[Instance] = []

    def add(template: str, text: str, cited: Iterable[FactVersion], section: str,
            metric: MetricRecord | None = None, suffix: str = "") -> None:
        cited = tuple(cited)
        key = f"{profile_id}:{template}:{cited[0].fact_id}{suffix}"
        out.append(Instance(key, template, text, tuple(_ref(f) for f in cited), section, cited,
                            metric))

    # Only these kinds get claims. Certification and award facts are skipped: no templates yet.
    projects = [f for f in facts if f.kind is FactKind.project]
    roles = [f for f in facts if f.kind is FactKind.experience]
    education = [f for f in facts if f.kind is FactKind.education]
    degree, subjects = education[0], education[1:]
    for p in projects:
        a = p.attributes
        assert a.ownership and a.deployment and len(a.skills) >= 2
        add("project_scope", f"{OWNERSHIP_VERB[a.ownership]} the {a.title} project "
            f"{DEPLOYMENT_PHRASE[a.deployment]}, using {a.skills[0]} and {a.skills[1]}.",
            [p], "projects")
        add("project_dates", f"Worked on the {a.title} project {_dates(a.start, a.end)}.",
            [p], "projects")
        for m in a.metrics:
            add("metric", f"{a.title}: {_span_sentence(m.span_text)}.", [p], "projects", m,
                f":{m.metric_id}")
    for r in roles:
        a = r.attributes
        add("role", f"Worked as {_article(str(a.title))} {a.title} at {a.organisation} "
            f"{_dates(a.start, a.end)}.", [r], "experience")
        for m in a.metrics:
            add("metric", f"{a.title}: {_span_sentence(m.span_text)}.", [r], "experience", m,
                f":{m.metric_id}")
    d = degree.attributes
    assert d.start is not None
    add("degree", f"Started a {d.title} at {d.organisation} in {month(d.start)}.", [degree],
        "education")
    for s in subjects:
        add("subject", f"Enrolled in {s.attributes.title} at {s.attributes.organisation}.",
            [s], "education")
    for k in (f for f in facts if f.kind is FactKind.skill):
        add("skill", f"Skills include {k.attributes.skills[0]}.", [k], "skills")
    noun = "project" if len(projects) == 1 else "projects"
    add("aggregate_projects", f"Worked on {NUMBER_WORDS[len(projects)]} {noun}: "
        f"{' and '.join(str(p.attributes.title) for p in projects)}.", projects, "projects")
    add("aggregate_subjects", f"Enrolled in {NUMBER_WORDS[len(subjects)]} subjects at "
        f"{d.organisation}.", subjects, "education")
    return out


def _wrong_number(i: Instance) -> str | None:
    m = i.metric
    if m is None:
        return None
    for token in NUMBER.findall(i.text):
        if float(token.replace(",", "")) != m.value:
            continue
        if m.metric in LOWER_IS_BETTER:
            new = m.value / 2
        elif m.unit == "percent":
            new = min(m.value + 10, 99)
        else:
            new = m.value * 2
        written = f"{new:,.0f}" if "," in token else f"{new:g}"
        return i.text.replace(token, written, 1)
    return None


def _year_earlier(i: Instance, start: str | None) -> str | None:
    if start is None or month(start) not in i.text:
        return None
    year, mm = start.split("-")
    return i.text.replace(month(start), month(f"{int(year) - 1}-{mm}"), 1)


def _mutations(instances: list[Instance], rng: random.Random) -> list[Mutation]:
    out: list[Mutation] = []
    skills_here = {s.casefold() for i in instances for f in i.facts for s in f.attributes.skills}
    outside = [s for s in OUTSIDE_SKILLS if s.casefold() not in skills_here]

    def add(category: Category, base: Instance, text: str | None,
            refs: tuple[FactRef, ...] | None = None) -> None:
        if text is not None:
            out.append(Mutation(category, base, text, refs or base.refs))

    for i in instances:
        f = i.facts[0]
        a = f.attributes
        if i.template == "metric":
            add(Category.wrong_number, i, _wrong_number(i))
        if i.template in ("project_dates", "role", "degree"):
            add(Category.wrong_date, i, _year_earlier(i, a.start))
        if i.template == "project_scope" and a.ownership is not Ownership.led:
            verb = OWNERSHIP_VERB[a.ownership or Ownership.contributed]
            higher = "Led" if a.ownership is Ownership.built else "Built"
            add(Category.inflated_ownership, i, i.text.replace(verb, higher, 1))
        if i.template == "role":
            add(Category.inflated_ownership, i,
                re.sub(r"^Worked as an? ", "Led a team as the ", i.text, count=1))
        if i.template == "project_scope" and a.deployment is not None \
                and a.deployment is not Deployment.production:
            rank = DEPLOYMENT_ORDER.index(a.deployment)
            higher_d = DEPLOYMENT_ORDER[min(rank + 2, len(DEPLOYMENT_ORDER) - 1)]
            add(Category.inflated_deployment, i, i.text.replace(
                DEPLOYMENT_PHRASE[a.deployment], DEPLOYMENT_PHRASE[higher_d], 1))
        if i.template == "project_scope":
            add(Category.unsupported_skill, i,
                i.text.replace(f"and {a.skills[1]}.", f"and {rng.choice(outside)}.", 1))
        if i.template == "skill":
            add(Category.unsupported_skill, i, f"Skills include {rng.choice(outside)}.")
        if i.template == "role" and a.organisation:
            add(Category.wrong_entity, i,
                i.text.replace(a.organisation, rng.choice(OTHER_EMPLOYERS), 1))
        if i.template in ("degree", "subject") and a.organisation:
            add(Category.wrong_entity, i,
                i.text.replace(a.organisation, rng.choice(OTHER_INSTITUTIONS), 1))
        if i.template in ("project_scope", "role", "skill", "subject"):
            first = i.refs[0]
            fake = (FactRef(fact_id=first.fact_id, version=2) if rng.random() < 0.5
                    else FactRef(fact_id=f"{first.fact_id.rsplit('_gt', 1)[0]}_gt99",
                                 version=1))
            add(Category.fake_id, i, i.text, (fake, *i.refs[1:]))
        if i.template.startswith("aggregate_"):
            n = len(i.refs)
            text = i.text.replace(NUMBER_WORDS[n], NUMBER_WORDS[n + 1], 1)
            if n == 1:
                # "one project" becomes "two projects", not "two project".
                text = text.replace(" project:", " projects:", 1)
            add(Category.wrong_aggregate, i, text)
        if i.template == "project_scope":
            add(Category.paraphrase_overstatement, i,
                i.text.removesuffix(".") + rng.choice(OVERSTATED_TAILS))
        if i.template == "skill":
            add(Category.paraphrase_overstatement, i,
                rng.choice(OVERSTATED_SKILL).format(skill=a.skills[0]))
        if i.template == "role":
            add(Category.paraphrase_overstatement, i,
                i.text.removesuffix(".") + OVERSTATED_ROLE_TAIL)
    return out


def _round_robin[T](pools: list[list[T]], n: int, *, allow_short: bool = False) -> list[T]:
    """Take n items, one pool at a time in turn, skipping empty pools."""
    pools = [list(p) for p in pools]
    out: list[T] = []
    while len(out) < n and any(pools):
        for pool in pools:
            if pool and len(out) < n:
                out.append(pool.pop(0))
    if len(out) < n and not allow_short:
        raise ValueError(f"only {len(out)} of {n} items available")
    return out


def _pick_supported(by_profile: dict[str, list[Instance]], n: int,
                    rng: random.Random) -> list[Instance]:
    # Spread across profiles, and within a profile across templates, so no single template
    # dominates the supported set.
    per_profile = []
    for instances in by_profile.values():
        by_template: dict[str, list[Instance]] = {}
        for i in instances:
            by_template.setdefault(i.template, []).append(i)
        groups = list(by_template.values())
        for g in groups:
            rng.shuffle(g)
        per_profile.append(_round_robin(groups, len(instances)))
    return _round_robin(per_profile, n)


def _pick_unsupported(by_profile: dict[str, list[Mutation]], category: Category, n: int,
                      rng: random.Random, *, allow_short: bool = False) -> list[Mutation]:
    # Spread across profiles, and within a profile across the templates the mutation came
    # from, so a category is not tested on one sentence shape only.
    pools = []
    for mutations in by_profile.values():
        by_template: dict[str, list[Mutation]] = {}
        for m in mutations:
            if m.category is category:
                by_template.setdefault(m.base.template, []).append(m)
        groups = list(by_template.values())
        for g in groups:
            rng.shuffle(g)
        pools.append(_round_robin(groups, sum(len(g) for g in groups)))
    return _round_robin(pools, n, allow_short=allow_short)


def _claim(claim_id: str, text: str, refs: Iterable[FactRef], section: str) -> Claim:
    return Claim(claim_id=claim_id, text=text, evidence=list(refs), section=section,
                 emphasis=3, allowed_transformations=[], output_types=[OutputType.visual_profile],
                 parent_claim_id=None)


def _split(split: Split, profiles: tuple[str, ...], n_supported: int,
           per_category: dict[Category, int], rng: random.Random,
           allow_short: bool = False) -> list[LabelledClaim]:
    instances = {p: _instances(p) for p in profiles}
    mutations = {p: _mutations(instances[p], rng) for p in profiles}
    out: list[LabelledClaim] = []

    def next_id() -> str:
        return f"{split}_{len(out) + 1:03d}"

    for i in _pick_supported(instances, n_supported, rng):
        out.append(LabelledClaim(claim=_claim(next_id(), i.text, i.refs, i.section),
                                 label="supported", category=None,
                                 profile_id=i.key.split(":")[0], split=split,
                                 template=i.template))
    for category, n in per_category.items():
        for m in _pick_unsupported(mutations, category, n, rng,
                                    allow_short=allow_short):
            out.append(LabelledClaim(
                claim=_claim(next_id(), m.text, m.refs, m.base.section), label="unsupported",
                category=category, profile_id=m.base.key.split(":")[0], split=split,
                template=m.base.template, mutated_from=m.base.key, base_text=m.base.text,
                base_evidence=list(m.base.refs)))
    return out


@dataclass(frozen=True)
class SplitSpec:
    """One split to build: which profiles, how many supported claims, and how many
    unsupported claims per category (one number for every category, or a map)."""

    split: Split
    profiles: tuple[str, ...]
    n_supported: int
    per_category: dict[Category, int] | int


def build_claim_set(seed: int = 0, splits: Sequence[SplitSpec] | None = None
                    ) -> list[LabelledClaim]:
    """With splits=None, the A3 dev and test sets. With specs, exactly those splits; a
    category with fewer mutations than asked for yields what exists (callers print counts)."""
    rng = random.Random(seed)
    if splits is not None:
        out: list[LabelledClaim] = []
        for spec in splits:
            counts = (dict.fromkeys(Category, spec.per_category)
                      if isinstance(spec.per_category, int) else spec.per_category)
            out += _split(spec.split, spec.profiles, spec.n_supported, counts, rng,
                          allow_short=True)
        return out
    categories = list(Category)
    # 20 dev unsupported over 9 categories: two each, and a third for two categories
    # chosen by the seed.
    dev_counts = dict.fromkeys(categories, 2)
    for extra in rng.sample(categories, DEV_UNSUPPORTED - 2 * len(categories)):
        dev_counts[extra] += 1
    test_counts = dict.fromkeys(categories, TEST_PER_CATEGORY)
    return (_split("dev", DEV_PROFILES, DEV_SUPPORTED, dev_counts, rng)
            + _split("test", TEST_PROFILES, TEST_SUPPORTED, test_counts, rng))


_CLAIMS = TypeAdapter(LabelledClaim)


def dump_claims(claims: list[LabelledClaim]) -> str:
    return "".join(c.model_dump_json() + "\n" for c in claims)


def load_claims(path: Path) -> list[LabelledClaim]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [_CLAIMS.validate_json(line) for line in lines if line.strip()]


# Running the validator over the claim set


@dataclass(frozen=True)
class CategoryResult:
    n: int
    false_accepts: Rate
    review: Rate
    rejected: Rate


@dataclass
class GroundingResults:
    judge_prompt_version: str
    threshold: float
    claims: list[LabelledClaim]
    outcomes: list[ClaimValidation]
    false_accepts: Rate
    false_rejects: Rate
    review_unsupported: Rate
    review_supported: Rate
    per_category: dict[Category, CategoryResult]
    # Unsupported claims by the layer that flagged them; supported claims rejected, by layer.
    caught_by: Counter[str] = field(default_factory=Counter)
    false_rejects_by: Counter[str] = field(default_factory=Counter)
    judge_errors: int = 0


def _flagged_by(v: ClaimValidation) -> str:
    layer1 = not v.layer1.passed
    judge = v.judge is not None and v.judge.verdict is not Verdict.supported
    if layer1 and judge:
        return "layer1 and judge"
    if layer1:
        return "layer1 only"
    if judge:
        return "judge only"
    return "none"


def _rate(k: int, n: int) -> Rate:
    return Rate(k, n)


def layer1_context(profile_id: str, as_of: str) -> Layer1Context:
    facts = {(f.fact_id, f.version): f for f in load_ground_truth(profile_id)}
    return Layer1Context(owner_id=GROUND_TRUTH_OWNER,
                         resolve=lambda ref: facts.get((ref.fact_id, ref.version)),
                         lex=load_lexicons(), aliases=load_aliases(), as_of=as_of)


def run_grounding(claims: list[LabelledClaim], adapter: ModelAdapter, threshold: float,
                  judge_prompt_version: str, as_of: str = DEFAULT_AS_OF,
                  progress: Callable[[int, int], None] | None = None) -> GroundingResults:
    contexts: dict[str, Layer1Context] = {}
    outcomes: list[ClaimValidation] = []
    for n, c in enumerate(claims, start=1):
        ctx = contexts.setdefault(c.profile_id, layer1_context(c.profile_id, as_of))
        outcomes.append(validate_claim(c.claim, ctx, adapter, threshold,
                                       judge_prompt_version=judge_prompt_version))
        if progress:
            progress(n, len(claims))

    pairs = list(zip(claims, outcomes, strict=True))
    bad = [(c, v) for c, v in pairs if c.label == "unsupported"]
    good = [(c, v) for c, v in pairs if c.label == "supported"]

    def count(group: list[tuple[LabelledClaim, ClaimValidation]], outcome: ClaimOutcome) -> int:
        return sum(1 for _, v in group if v.outcome is outcome)

    per_category: dict[Category, CategoryResult] = {}
    for category in Category:
        group = [(c, v) for c, v in bad if c.category is category]
        if group:
            per_category[category] = CategoryResult(
                n=len(group),
                false_accepts=_rate(count(group, ClaimOutcome.passed), len(group)),
                review=_rate(count(group, ClaimOutcome.user_review), len(group)),
                rejected=_rate(count(group, ClaimOutcome.rejected), len(group)))
    return GroundingResults(
        judge_prompt_version=judge_prompt_version,
        threshold=threshold,
        claims=claims,
        outcomes=outcomes,
        false_accepts=_rate(count(bad, ClaimOutcome.passed), len(bad)),
        false_rejects=_rate(count(good, ClaimOutcome.rejected), len(good)),
        review_unsupported=_rate(count(bad, ClaimOutcome.user_review), len(bad)),
        review_supported=_rate(count(good, ClaimOutcome.user_review), len(good)),
        per_category=per_category,
        caught_by=Counter(_flagged_by(v) for _, v in bad),
        false_rejects_by=Counter(_flagged_by(v) for _, v in good
                                 if v.outcome is ClaimOutcome.rejected),
        judge_errors=sum(1 for v in outcomes if v.judge_error is not None),
    )


def summary(results: GroundingResults) -> dict[str, object]:
    """Counts only, for the dev tuning log and the run record. No claim text."""
    return {
        "judge_prompt_version": results.judge_prompt_version,
        "threshold": results.threshold,
        "false_accepts": [results.false_accepts.k, results.false_accepts.n],
        "false_rejects": [results.false_rejects.k, results.false_rejects.n],
        "review_unsupported": [results.review_unsupported.k, results.review_unsupported.n],
        "review_supported": [results.review_supported.k, results.review_supported.n],
        "per_category": {c.value: {"n": r.n, "false_accepts": r.false_accepts.k,
                                   "review": r.review.k, "rejected": r.rejected.k}
                         for c, r in results.per_category.items()},
        "caught_by": dict(results.caught_by),
        "false_rejects_by": dict(results.false_rejects_by),
        "judge_errors": results.judge_errors,
        "outcomes": {v.claim_id: v.outcome.value for v in results.outcomes},
    }


def dump_summary(results: GroundingResults) -> str:
    return json.dumps(summary(results), indent=2)
