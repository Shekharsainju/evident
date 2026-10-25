"""Run orchestration for the slice: no queue, stages run in order in a background task and
write a status record the UI polls (spec 7.2). Stage functions take and return contracts,
so they can move onto queue workers later unchanged."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from evident.contracts.coverage import Target
from evident.contracts.documents import Document
from evident.contracts.enums import DocumentKind, RunStage, RunState
from evident.contracts.runs import RunStatus
from evident.errors import ErrorCategory, StageError
from evident.eval.assets import JOB_SCREENSHOT, TEMPLATES, cv_pdf_path, cv_photo_path
from evident.ingestion.pdf_text import ingest_pdf
from evident.ingestion.vision import ingest_photo
from evident.models.adapter import ModelAdapter
from evident.settings import Settings
from evident.store.repository import Repository

log = logging.getLogger("evident.runs")

JOBS = Path("data/synthetic/jobs.jsonl")
PROFILE_IDS = [f"student_profile_0{i}" for i in range(1, 6)]
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
QUOTA_CODES = {"daily_quota", "rate_limited"}
MediaType = Literal["application/pdf", "image/png", "image/jpeg"]
MAGIC: dict[bytes, MediaType] = {
    b"%PDF-": "application/pdf",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def sample_cvs() -> dict[str, Path]:
    """The synthetic CVs a run may start from, by key. Only these paths are ever opened."""
    samples: dict[str, Path] = {}
    for profile in PROFILE_IDS:
        for template in TEMPLATES:
            samples[f"{profile}_{template}"] = cv_pdf_path(profile, template)
            samples[f"{profile}_{template}_photo"] = cv_photo_path(profile, template)
    return samples


def load_jobs() -> list[dict[str, Any]]:
    lines = JOBS.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def sniff_media_type(data: bytes) -> MediaType | None:
    """Decide the type from the file's bytes, never from its name or the browser's claim."""
    return next((media for magic, media in MAGIC.items() if data.startswith(magic)), None)


def _bad_input(detail: str) -> StageError:
    return StageError(code="bad_input", category=ErrorCategory.input, detail=detail)


class RunService:
    def __init__(self, repo: Repository, adapter: ModelAdapter, settings: Settings,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self.repo = repo
        self.adapter = adapter
        self.settings = settings
        self.clock = clock

    def _document(self, owner_id: str, kind: DocumentKind, filename: str,
                  content: bytes) -> Document:
        media = sniff_media_type(content)
        if media is None:
            raise _bad_input("Upload a PDF, PNG or JPEG file.")
        width = height = None
        if media != "application/pdf":
            try:
                with Image.open(io.BytesIO(content)) as img:
                    width, height = img.size
            except OSError as exc:
                raise _bad_input("The image could not be read.") from exc
        doc = Document(
            document_id=_new_id("doc"), owner_id=owner_id, kind=kind, media_type=media,
            filename=Path(filename).name[:100] or "upload",
            sha256=hashlib.sha256(content).hexdigest(),
            width_px=width, height_px=height, created_at=self.clock(),
        )
        self.repo.put_document(doc, content)
        return doc

    def start(self, owner_id: str, cv: str | None, upload: tuple[str, bytes] | None,
              job_id: str | None, use_job_screenshot: bool) -> RunStatus:
        if (cv is None) == (upload is None):
            raise _bad_input("Choose a sample CV or upload one, not both.")
        if upload is not None:
            name, content = upload
            if len(content) > MAX_UPLOAD_BYTES:
                raise _bad_input("Uploads are limited to 10 MB.")
        else:
            path = sample_cvs().get(cv or "")
            if path is None:
                raise _bad_input("Unknown sample CV.")
            name, content = path.name, path.read_bytes()

        jobs = {j["document_id"]: j for j in load_jobs()}
        if use_job_screenshot:
            shot = self._document(owner_id, DocumentKind.job_ad, JOB_SCREENSHOT.name,
                                  JOB_SCREENSHOT.read_bytes())
            target = Target(target_id=_new_id("t"), owner_id=owner_id,
                            title="Graduate AI Engineer (screenshot)", source_job_id=None,
                            document_id=shot.document_id)
        elif job_id in jobs:
            target = Target(target_id=_new_id("t"), owner_id=owner_id,
                            title=str(jobs[job_id]["title"]), source_job_id=job_id,
                            document_id=None)
        else:
            raise _bad_input("Choose a job ad.")

        doc = self._document(owner_id, DocumentKind.cv, name, content)
        self.repo.put_target(target)
        run = RunStatus(run_id=_new_id("r"), owner_id=owner_id, stage=RunStage.ingest,
                        state=RunState.pending, message="Queued.", error=None,
                        document_id=doc.document_id, target_id=target.target_id, plan_id=None,
                        output_ids=[])
        self.repo.put_run(run)
        return run

    def _update(self, run: RunStatus, **changes: Any) -> RunStatus:
        updated = RunStatus.model_validate_json(run.model_copy(update=changes).model_dump_json())
        self.repo.put_run(updated)
        return updated

    def run_ingest(self, owner_id: str, run_id: str) -> None:
        run = self.repo.get_run(owner_id, run_id)
        if run is None:
            return
        run = self._update(run, stage=RunStage.ingest, state=RunState.running,
                           message="Reading the CV.", error=None)
        try:
            doc = self.repo.get_document(owner_id, run.document_id)
            if doc is None:
                raise StageError(code="not_found", category=ErrorCategory.input,
                                 detail="The CV document is missing.")
            content = self.repo.get_document_bytes(owner_id, doc.document_id)
            if doc.media_type == "application/pdf":
                facts = ingest_pdf(doc, content, self.adapter, self.repo)
            else:
                facts = ingest_photo(doc, content, self.adapter, self.repo)
        except StageError as exc:
            state = RunState.quota_exhausted if exc.code in QUOTA_CODES else RunState.failed
            self._update(run, state=state, message=exc.detail or exc.code, error=exc.code)
            return
        except Exception as exc:  # never let a background task die silently
            log.error("ingest failed run=%s error=%s", run_id, type(exc).__name__)
            self._update(run, state=RunState.failed, message="Internal error while reading the CV.",
                         error="internal")
            return
        self._update(run, stage=RunStage.review, state=RunState.waiting_for_user,
                     message=f"Review the extracted facts: {len(facts)} found.")
