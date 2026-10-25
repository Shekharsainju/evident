"""JSON file store: one file per record under root/<owner_id>/<type>/ (spec 7.2)."""

from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

from evident.contracts.coverage import CoverageRow, Target
from evident.contracts.documents import Document
from evident.contracts.enums import FactStatus
from evident.contracts.facts import FactRef, FactVersion
from evident.contracts.outputs import Output
from evident.contracts.plan import ContentPlan
from evident.contracts.runs import RunStatus
from evident.contracts.validation import ValidationReport
from evident.errors import ErrorCategory, StageError

M = TypeVar("M", bound=BaseModel)

# IDs become path segments, so anything outside this set could escape the owner's folder.
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
ALLOWED_STATUS = {
    FactStatus.extracted: {FactStatus.confirmed, FactStatus.rejected, FactStatus.superseded},
    FactStatus.confirmed: {FactStatus.superseded},
}
_ROWS = TypeAdapter(list[CoverageRow])


def _safe(value: str) -> str:
    if not SAFE_ID.match(value):
        raise StageError(code="bad_id", category=ErrorCategory.input, detail="Invalid record ID.")
    return value


def _write_atomic(path: Path, data: bytes, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and path.exists():
        raise StageError(code="version_exists", category=ErrorCategory.internal,
                         detail=f"{path.name} already exists; records are never overwritten.")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class FileRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        # Background stages and the web thread share one store; writes check-then-write.
        self._lock = threading.Lock()

    def _path(self, owner_id: str, kind: str, name: str) -> Path:
        return self.root / _safe(owner_id) / kind / f"{name}.json"

    def _put(self, owner_id: str, kind: str, name: str, model: BaseModel,
             overwrite: bool = True) -> None:
        with self._lock:
            _write_atomic(self._path(owner_id, kind, name),
                          model.model_dump_json(indent=2).encode("utf-8"), overwrite)

    def _get(self, owner_id: str, kind: str, name: str, schema: type[M]) -> M | None:
        path = self._path(owner_id, kind, name)
        if not path.exists():
            return None
        return schema.model_validate_json(path.read_text(encoding="utf-8"))

    # Documents

    def put_document(self, doc: Document, content: bytes) -> None:
        with self._lock:
            blob = self.root / _safe(doc.owner_id) / "blobs" / _safe(doc.document_id)
            _write_atomic(blob, content, overwrite=False)
            _write_atomic(self._path(doc.owner_id, "documents", _safe(doc.document_id)),
                          doc.model_dump_json(indent=2).encode("utf-8"), overwrite=False)

    def get_document(self, owner_id: str, document_id: str) -> Document | None:
        return self._get(owner_id, "documents", _safe(document_id), Document)

    def get_document_bytes(self, owner_id: str, document_id: str) -> bytes:
        blob = self.root / _safe(owner_id) / "blobs" / _safe(document_id)
        if not blob.exists():
            raise StageError(code="not_found", category=ErrorCategory.input,
                             detail="Document not found.")
        return blob.read_bytes()

    # Facts: each version is its own file and is never rewritten except for its status.

    def _fact_name(self, ref: FactRef) -> str:
        return f"{_safe(ref.fact_id)}_v{ref.version}"

    def put_fact(self, fact: FactVersion) -> None:
        ref = FactRef(fact_id=fact.fact_id, version=fact.version)
        self._put(fact.owner_id, "facts", self._fact_name(ref), fact, overwrite=False)

    def get_fact(self, owner_id: str, ref: FactRef) -> FactVersion | None:
        return self._get(owner_id, "facts", self._fact_name(ref), FactVersion)

    def set_fact_status(
        self, owner_id: str, ref: FactRef, status: FactStatus, now: datetime
    ) -> FactVersion:
        with self._lock:
            current = self.get_fact(owner_id, ref)
            if current is None:
                raise StageError(code="not_found", category=ErrorCategory.input,
                                 detail="Fact version not found.")
            if status not in ALLOWED_STATUS.get(current.status, set()):
                raise StageError(
                    code="bad_status_change", category=ErrorCategory.validation,
                    detail=f"Cannot change a {current.status.value} fact to {status.value}.",
                )
            update: dict[str, object] = {"status": status}
            if status is FactStatus.confirmed:
                update["confirmed_at"] = now
            updated = current.model_copy(update=update)
            # Round-trip through validation so a bad update can't be written.
            updated = FactVersion.model_validate_json(updated.model_dump_json())
            _write_atomic(self._path(owner_id, "facts", self._fact_name(ref)),
                          updated.model_dump_json(indent=2).encode("utf-8"))
            return updated

    def current_facts(self, owner_id: str, document_id: str | None = None) -> list[FactVersion]:
        folder = self.root / _safe(owner_id) / "facts"
        if not folder.exists():
            return []
        latest: dict[str, FactVersion] = {}
        for path in sorted(folder.glob("*.json")):
            fact = FactVersion.model_validate_json(path.read_text(encoding="utf-8"))
            if fact.status is FactStatus.superseded:
                continue
            if document_id is not None and getattr(fact.source, "document_id", None) != document_id:
                continue
            best = latest.get(fact.fact_id)
            if best is None or fact.version > best.version:
                latest[fact.fact_id] = fact
        return [latest[k] for k in sorted(latest)]

    # Other records are replaced as a whole; they are derived, and outputs keep the fact
    # versions they used, so replacing them never changes a fact.

    def put_target(self, target: Target) -> None:
        self._put(target.owner_id, "targets", _safe(target.target_id), target)

    def get_target(self, owner_id: str, target_id: str) -> Target | None:
        return self._get(owner_id, "targets", _safe(target_id), Target)

    def put_coverage(self, owner_id: str, target_id: str, rows: list[CoverageRow]) -> None:
        with self._lock:
            _write_atomic(self._path(owner_id, "coverage", _safe(target_id)),
                          _ROWS.dump_json(rows, indent=2))

    def get_coverage(self, owner_id: str, target_id: str) -> list[CoverageRow] | None:
        path = self._path(owner_id, "coverage", _safe(target_id))
        if not path.exists():
            return None
        return _ROWS.validate_json(path.read_bytes())

    def put_plan(self, plan: ContentPlan) -> None:
        self._put(plan.owner_id, "plans", _safe(plan.plan_id), plan)

    def get_plan(self, owner_id: str, plan_id: str) -> ContentPlan | None:
        return self._get(owner_id, "plans", _safe(plan_id), ContentPlan)

    def put_report(self, owner_id: str, report: ValidationReport) -> None:
        self._put(owner_id, "reports", _safe(report.plan_id), report)

    def get_report(self, owner_id: str, plan_id: str) -> ValidationReport | None:
        return self._get(owner_id, "reports", _safe(plan_id), ValidationReport)

    def put_output(self, output: Output) -> None:
        self._put(output.owner_id, "outputs", _safe(output.output_id), output)

    def get_output(self, owner_id: str, output_id: str) -> Output | None:
        return self._get(owner_id, "outputs", _safe(output_id), Output)

    def put_run(self, run: RunStatus) -> None:
        self._put(run.owner_id, "runs", _safe(run.run_id), run)

    def get_run(self, owner_id: str, run_id: str) -> RunStatus | None:
        return self._get(owner_id, "runs", _safe(run_id), RunStatus)


