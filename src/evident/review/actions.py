"""User review of extracted facts (design: Pipeline 3; spec 8.2).

Only confirmed facts flow downstream. An edit never changes a fact in place: it creates a
new version marked as user-edited, and the old version is superseded.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError

from evident.contracts.enums import Deployment, FactKind, FactStatus, Ownership
from evident.contracts.facts import (
    FactRef,
    FactVersion,
    OcrSource,
    PdfTextSource,
    VisionSource,
)
from evident.errors import ErrorCategory, StageError
from evident.store.repository import Repository

HIGH_IMPACT_KINDS = {FactKind.education, FactKind.certification}


def is_high_impact(fact: FactVersion) -> bool:
    """Facts whose details change what a claim may say get a per-fact confirm."""
    a = fact.attributes
    if a.start or a.end or a.metrics or fact.kind in HIGH_IMPACT_KINDS:
        return True
    if a.ownership is not None and a.ownership is not Ownership.contributed:
        return True
    if a.deployment is not None and a.deployment is not Deployment.concept:
        return True
    source = fact.source
    if isinstance(source, PdfTextSource | OcrSource) and not source.span_found:
        return True
    return isinstance(source, VisionSource) and not source.bbox_verified


def _get(repo: Repository, owner_id: str, ref: FactRef) -> FactVersion:
    fact = repo.get_fact(owner_id, ref)
    if fact is None:
        raise StageError(code="not_found", category=ErrorCategory.input,
                         detail="Fact version not found.")
    return fact


def confirm(repo: Repository, owner_id: str, ref: FactRef, now: datetime) -> FactVersion:
    fact = _get(repo, owner_id, ref)
    source = fact.source
    if (isinstance(source, PdfTextSource | OcrSource) and not source.span_found
            and not fact.edited_by_user):
        raise StageError(
            code="span_not_found", category=ErrorCategory.validation,
            detail="The supporting text wasn't found in the document. Edit or reject this fact.",
        )
    return repo.set_fact_status(owner_id, ref, FactStatus.confirmed, now)


def confirm_low_impact(repo: Repository, owner_id: str, document_id: str, now: datetime) -> int:
    count = 0
    for fact in repo.current_facts(owner_id, document_id):
        if fact.status is FactStatus.extracted and not is_high_impact(fact):
            confirm(repo, owner_id, FactRef(fact_id=fact.fact_id, version=fact.version), now)
            count += 1
    return count


def reject(repo: Repository, owner_id: str, ref: FactRef) -> FactVersion:
    _get(repo, owner_id, ref)
    return repo.set_fact_status(owner_id, ref, FactStatus.rejected, datetime.now().astimezone())


@dataclass(frozen=True)
class FactEdit:
    """Fields the user changed. None means unchanged; an empty string clears a field."""

    text: str | None = None
    title: str | None = None
    organisation: str | None = None
    start: str | None = None
    end: str | None = None
    ownership: str | None = None
    deployment: str | None = None
    skills: list[str] | None = None


def edit(repo: Repository, owner_id: str, ref: FactRef, changes: FactEdit,
         now: datetime) -> FactVersion:
    old = _get(repo, owner_id, ref)
    if old.status not in (FactStatus.extracted, FactStatus.confirmed):
        raise StageError(code="bad_status_change", category=ErrorCategory.validation,
                         detail=f"A {old.status.value} fact can't be edited.")
    data = json.loads(old.model_dump_json())
    attrs = data["attributes"]
    for field in ("title", "organisation", "start", "end", "ownership", "deployment"):
        value = getattr(changes, field)
        if value is not None:
            attrs[field] = value.strip() or None
    if changes.skills is not None:
        attrs["skills"] = [s.strip() for s in changes.skills if s.strip()]
    if changes.text is not None:
        if not changes.text.strip():
            raise StageError(code="bad_edit", category=ErrorCategory.validation,
                             detail="A fact needs some text.")
        data["text"] = changes.text.strip()
    data.update(version=old.version + 1, supersedes=old.version, edited_by_user=True,
                status=FactStatus.extracted.value, confirmed_at=None)
    try:
        new = FactVersion.model_validate_json(json.dumps(data))
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})
        raise StageError(
            code="bad_edit", category=ErrorCategory.validation,
            detail=f"Invalid value for {', '.join(fields)}. Dates use YYYY-MM.",
        ) from exc
    # Write the new version first: if the second step fails, the newest version still wins.
    repo.put_fact(new)
    repo.set_fact_status(owner_id, ref, FactStatus.superseded, now)
    return new
