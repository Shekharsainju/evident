# Layer 1 checks

## What it does

Layer 1 is the model-free half of claim validation. Given a claim from the content plan and the fact versions it cites, it runs a fixed list of checks and returns every failure with the rule name, the offending phrase and a one-line reason. The code is in `src/evident/validation/layer1/`; `run_layer1` in `run.py` is the entry point.

The checks, in the order they run:

| Rule | Module | What it catches |
|---|---|---|
| `fact_ids` | `checks_ids.py` | No evidence, a fact that doesn't exist, belongs to another user, or isn't `confirmed` (extracted, rejected or superseded). If this fails, nothing else runs. |
| `metrics` | `checks_refs.py` | A number that binds to no cited metric record (`unbound`), to more than one (`ambiguous`), or goes beyond the recorded value. `metrics_other_needs_review` for records with an `other:` metric. |
| `scale` | `checks_refs.py` | "Thousands of users", "40 customers" and similar with no `users` or `throughput` record, or beyond it. |
| `aggregates` | `checks_refs.py` | "Three projects" when the claim does not cite exactly three project facts. |
| `dates` | `checks_scope.py` | A year, month-year or season-year outside every cited fact's range. Ongoing roles run to the `as_of` month. |
| `durations` | `checks_scope.py` | "Three years of Python" when the cited facts that list Python cover fewer months, overlaps counted once. |
| `ownership` | `checks_scope.py` | A word ranked above the facts: led (3) on a built (2) fact. |
| `deployment` | `checks_scope.py` | A word ranked above the facts: production (4) on a prototype (2) fact. |
| `skills` | `checks_scope.py` | A skill named in the claim that is in no cited fact's skills or text, after alias mapping (JS = JavaScript). |
| `entities` | `checks_scope.py` | A seniority or credential word (senior, certified) with no support, or a capitalised name (Acme Robotics) that no cited fact mentions. |

Every rejection is a `CheckFailure(rule, phrase, detail)` so the claims page can show the user exactly which words to change.

## Why it's built this way

- **Same normalisation on both sides** (design: Deterministic check rules). `normalise_text` applies NFKC, lowercases, unifies dashes and quotes, removes thousands separators and strips punctuation except `.`, `%` and `$` inside numbers. The claim and the evidence go through the same function, so "Built – FastAPI" and "built - fastapi" compare equal and a different dash can't cause a false rejection.
- **Numbers are classified before they are checked** (plan Task 16, Review Focus 1). `find_numbers` turns number words into digits ("forty" to 40), expands `k` and `m`, and records "over 40", "40+" and "more than 40" as at-least-40. Then it labels each number, in this order: date (a year 1990 to 2039), duration (followed by weeks, months or years), aggregate (followed by a count noun from the lexicon), identifier, or metric. An identifier is a number that appears verbatim in the evidence as the first token of a name ("43007 Advanced Artificial Intelligence") or the last ("Python 3"). Those are names, not figures, so they skip the metric check. A figure quoted from the middle of a sentence ("covered 1,200 survey responses") is not an identifier and still has to bind to a metric record, because numbers in evidence text with no record cannot support a claim (invariants section 1).
- **Metric binding fails closed.** Candidates are the cited records with a compatible unit, narrowed by any metric keyword near the number ("latency", "accuracy") and any direction word before it ("cut", "raised"). Exactly one must remain. A record with unit `count` matches a counted noun ("1,200 survey responses") but not a percent or a time. The claimed value may round toward zero, never away: 40% against a 45% record passes, 50% fails.
- **Lexicons and aliases are versioned config**, `config/lexicons.toml` and `config/aliases.toml`, not code. The ownership and deployment ranks are the design's Lexicons table. Words that are not listed pass Layer 1 and are left to the judge, as the design says. Aliases cover every skill in the enriched profiles plus about 150 common tools; common English words (go, make, word) were left out on purpose so that ordinary prose is not read as a skill.
- **Facts without the attribute don't lower the bar.** For ownership and deployment the allowed rank is the lowest among cited facts that state it. A cited skill fact has no ownership, so citing it next to a built project does not turn "built" into a rejection. If no cited fact states the attribute, the allowed rank is 1, so "led" on a retail role still fails.
- **Durations follow the skill.** "Three years of Python" is measured against the union of the ranges of cited facts whose skills include Python, with a fact ending `null` measured to `as_of` (Review Focus 2). If the claim names no skill, the facts whose title appears in the claim are used, then all cited facts.
- **Entities are checked conservatively.** Only capitalised runs of two or more words are treated as names; single capitalised words are too noisy. Runs that are just skills ("Python and Flask") are left to the skills check, a leading sentence verb ("Built Team Course Planner") is dropped, and "at", "for", "in", "on" split one run into separate names so "Bachelor of Computing Science at UTS" is two lookups. Entity aliases map UTS to its full name.
- **Written dates are not names, and "and" separates names** (A3 dev findings, commit `76fb242`). A month or season directly before a year ("Mar 2025", "3 June 2025") is cut out of a run, because the date rule already checks it. "June 3, 2025" is not cut, because the date rule reads only the word before the year and would check the year alone. A run that fails as a whole is split on "and", so "Team Course Planner and Text Classification Study" is two lookups. Each part of that split, and the words left beside a cut date, are checked strictly: they must equal a whole name in the evidence (a title, organisation, skill, or capitalised run in the fact text), and a single word is not skipped. A prose word ("top marks"), a fragment of a longer name ("Johnson" in "Dr Johnson") or a lone word opening a sentence, line or bullet in the evidence does not count. On these parts only a known verb (an ownership word or an "-ed" deployment word) is dropped from the front.
- **Every check runs and every failure is kept** (except after `fact_ids`), so an inflated claim shows all of its problems at once instead of one per round.

## How the model is used

Layer 1 makes no model calls. It is deterministic, costs nothing and runs in well under a millisecond per claim, which is why it runs before the judge.

## Limits

- **A lower figure on a decrease metric passes.** The record "cut clash checks to under 2 seconds" is stored as latency, decrease, 2 seconds. "Under 1 second" rounds toward zero and passes Layer 1, although it overstates the result. The judge caught this case in the live smoke run (overstated, confidence 0.80). The rule follows the design; distinguishing "reduced by 2 s" from "reduced to 2 s" needs a baseline on the record.
- **Unit matching is a short alias table.** A unit spelling not in `unit_aliases` is compared literally, so "40 pct" binds to a percent record but "40 per cent" does not.
- **Rephrasing is not checked here.** By design Layer 1 flags only new concrete content. "Developed" for "built" passes (both rank 2); whether the sentence still means the same thing is the judge's job.
- **Number words cover up to the billions in plain English**; "a dozen", fractions and ranges ("3 to 5 years") are not parsed and pass through unchecked.
- **"And" can join two real names into a false one.** If "Marks" and "Spencer" each appear whole in the evidence, "Marks and Spencer" passes. A name whose first word is an ownership verb ("Led Zeppelin") can lose that word at the start of a sentence, and on the older whole-run path any sentence-opening word is dropped, so "Goldman Sachs backed the planner." passes with no evidence. The judge is the check for these.
- **The entity heuristic depends on capitalisation.** A lower-case organisation name is not caught, and an unusual capitalised phrase in the claim that is not a name can be a false rejection, which routes the claim to user review rather than losing it.
- **Lexicon coverage is what was written on 2026-10-25.** New ownership or deployment words the judge flags should be added to `config/lexicons.toml` through the feedback loop the design describes.

## Example

Cited fact (profile 01, Team Course Planner): built, prototype, Python and Flask, 2025-02 to 2025-06, with one metric record `latency decrease 2 seconds`.

Claim: "Led a production timetable system serving thousands of users since 2023"

Layer 1 result, from the live run on 2026-10-25:

```
scale:      'thousands of users' has no users or throughput metric record.
ownership:  'led' is rank 3; the cited facts allow rank 2.
deployment: 'production' is rank 4; the cited facts allow rank 2.
dates:      'since 2023' is outside every cited fact's dates.
```

Claim: "Developed a timetable clash checker using Python and Flask" passes every check and goes to the judge with nothing flagged.
