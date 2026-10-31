"""Evidence-grounded visual profile HTML and PDF (Tasks 13 and 21)."""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from evident.contracts.enums import ClaimOutcome, OutputType
from evident.contracts.plan import Claim, ContentPlan
from evident.contracts.validation import ClaimValidation, ValidationReport
from evident.errors import ErrorCategory, StageError
from evident.render.pdf import html_to_pdf

COPY_PATH = Path("config/template_copy.toml")


def load_template_copy(path: Path = COPY_PATH) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


COPY = load_template_copy()
HEADINGS: dict[str, str] = COPY["headings"]
TEMPLATE_COPY: set[str] = {v for v in COPY.values() if isinstance(v, str)} | set(HEADINGS.values())

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(enabled_extensions=("j2", "html"), default=True),
    undefined=StrictUndefined,
)


def _renderable(v: ClaimValidation) -> bool:
    return v.outcome == ClaimOutcome.passed or (
        v.outcome == ClaimOutcome.user_review and v.approved_by_user)


def _validated(plan: ContentPlan, report: ValidationReport) -> set[tuple[str, int]]:
    if report.plan_id != plan.plan_id:
        raise StageError(code="report_plan_mismatch", category=ErrorCategory.internal,
                         detail=f"Report {report.plan_id} is not for plan {plan.plan_id}.")
    dropped = set(report.dropped_claim_ids)
    counts = Counter(c.claim_id for c in plan.claims)
    ok: set[tuple[str, int]] = set()
    for c in plan.claims:
        # A repeated ID makes "which version was validated" ambiguous, so none of them render.
        if counts[c.claim_id] > 1 or c.claim_id in dropped:
            continue
        matches = [v for v in report.results
                   if v.claim_id == c.claim_id and v.claim_version == c.version]
        # Every record for this exact version must allow it, so a conflicting duplicate fails
        # closed instead of depending on list order.
        if matches and all(_renderable(v) for v in matches):
            ok.add((c.claim_id, c.version))
    return ok


def renderable_claims(plan: ContentPlan, report: ValidationReport,
                      output_type: OutputType) -> list[Claim]:
    """The only way a claim reaches a rendered output. Keeps plan order."""
    ok = _validated(plan, report)
    ok_ids = {claim_id for claim_id, _ in ok}
    # A derived claim is only as good as its parent: drop it if the parent did not validate.
    # Parents are cited by ID alone, which is safe because repeated IDs never reach ok.
    return [c for c in plan.claims
            if (c.claim_id, c.version) in ok and output_type in c.output_types
            and (c.parent_claim_id is None or c.parent_claim_id in ok_ids)]


def heading(section: str) -> str:
    return HEADINGS.get(section.casefold(), HEADINGS["other"])


def by_section(claims: list[Claim]) -> list[tuple[str, list[Claim]]]:
    """Groups claims by heading, highest emphasis first; ties keep plan order."""
    groups: dict[str, list[Claim]] = {}
    for c in claims:
        groups.setdefault(heading(c.section), []).append(c)
    ordered = sorted(groups.items(), key=lambda kv: -max(c.emphasis for c in kv[1]))
    return [(h, sorted(cs, key=lambda c: -c.emphasis)) for h, cs in ordered]


def render_profile(plan: ContentPlan, report: ValidationReport, identity: dict[str, str],
                   receipt_base: str) -> str:
    claims = renderable_claims(plan, report, OutputType.visual_profile)
    return _env.get_template("profile.html.j2").render(
        copy=COPY, identity=identity, sections=by_section(claims),
        receipt_base=receipt_base.rstrip("/"), plan_id=plan.plan_id)


def _add_pdf_claim_links(html: str, claim_links: dict[str, str]) -> str:
    """Attach receipt links without altering a claim's verified text.

    ``render_profile`` normally supplies these links itself.  Keeping this small fallback
    makes the PDF boundary explicit and protects callers which pass a previously-rendered
    profile without links.
    """
    pattern = re.compile(r'(<span data-claim-id="(?P<id>[^"]+)"[^>]*>.*?</span>)', re.DOTALL)

    def wrap(match: re.Match[str]) -> str:
        claim_id = match.group("id")
        href = claim_links.get(claim_id)
        if href is None:
            return match.group(0)
        return f'<a class="claim-link" href="{href}">{match.group(0)}</a>'

    return pattern.sub(wrap, html)


def _replace_pdf_claim_links(html: str, claim_links: dict[str, str]) -> str:
    """Use absolute URLs in the PDF; Chromium omits relative URL annotations."""
    pattern = re.compile(
        r'(<a class="claim-link" href=")[^"]+("\s*>\s*<span data-claim-id="(?P<id>[^"]+)")',
        re.DOTALL,
    )

    def replace(match: re.Match[str]) -> str:
        href = claim_links.get(match.group("id"))
        return match.group(0) if href is None else f'{match.group(1)}{href}{match.group(2)}'

    return pattern.sub(replace, html)


def render_profile_pdf(html: str, out: Path, claim_links: dict[str, str] | None = None) -> Path:
    """Render an A4 PDF, retaining receipt URLs as Chromium link annotations."""
    links = claim_links or {}
    linked = (_replace_pdf_claim_links(html, links) if 'class="claim-link"' in html
              else _add_pdf_claim_links(html, links))
    return html_to_pdf(linked, out)
