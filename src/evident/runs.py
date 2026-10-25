"""Run orchestration for the slice: no queue, stages run in order in a background task and
write a status record the UI polls (spec 7.2). Stage functions take and return contracts,
so they can move onto queue workers later unchanged."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from evident.contracts.coverage import Requirement, Target
from evident.contracts.documents import Document
from evident.contracts.enums import (
    ClaimOutcome,
    DocumentKind,
    FactStatus,
    OutputType,
    RunStage,
    RunState,
)
from evident.contracts.facts import FactRef, FactVersion
from evident.contracts.outputs import Output, PostRenderResult
from evident.contracts.plan import Claim, ContentPlan
from evident.contracts.runs import RunStatus
from evident.contracts.validation import ClaimValidation, ValidationReport
from evident.coverage.grading import check_coverage_gate, grade_requirements
from evident.coverage.requirements import extract_requirements
from evident.errors import ErrorCategory, StageError
from evident.eval.assets import JOB_SCREENSHOT, TEMPLATES, cv_pdf_path, cv_photo_path
from evident.ingestion.pdf_text import ingest_pdf
from evident.ingestion.vision import ingest_photo
from evident.models.adapter import ModelAdapter
from evident.planning.planner import plan_and_validate
from evident.render.deck import render_deck
from evident.render.profile_html import (
    TEMPLATE_COPY,
    render_profile,
    render_profile_pdf,
    renderable_claims,
)
from evident.review.actions import is_high_impact
from evident.settings import Settings
from evident.store.repository import Repository
from evident.validation.layer1.checks_ids import check_fact_ids
from evident.validation.layer1.config import Layer1Context, load_aliases, load_lexicons
from evident.validation.outcome import validate_claim
from evident.validation.post_render import verify_html, verify_pptx

log = logging.getLogger("evident.runs")

JOBS = Path("data/synthetic/jobs.jsonl")
PROFILE_IDS = [f"student_profile_0{i}" for i in range(1, 6)]
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
QUOTA_CODES = {"daily_quota", "rate_limited"}
# No contact details in outputs until the owner decides where a display name comes from.
IDENTITY: dict[str, str] = {}
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SUPERSEDED = ".superseded"
NO_CLAIMS = "No validated claims for this output."
BUSY = {RunState.pending, RunState.running}
PLANNED_STAGES = {RunStage.validate, RunStage.render, RunStage.verify, RunStage.done}
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


def _no_claims_reason(plan: ContentPlan, report: ValidationReport,
                      output_type: OutputType) -> str:
    """Says whether approving claims in review would fill the output."""
    versions = {c.claim_id: c.version for c in plan.claims if output_type in c.output_types}
    waiting = {v.claim_id for v in report.results
               if versions.get(v.claim_id) == v.claim_version
               and v.claim_id not in report.dropped_claim_ids
               and v.outcome is ClaimOutcome.user_review and not v.approved_by_user}
    if not waiting:
        return NO_CLAIMS
    noun = "claim is" if len(waiting) == 1 else "claims are"
    return f"{NO_CLAIMS[:-1]}: {len(waiting)} {noun} waiting for your review."


def _bad_input(detail: str) -> StageError:
    return StageError(code="bad_input", category=ErrorCategory.input, detail=detail)


class RunService:
    def __init__(self, repo: Repository, adapter: ModelAdapter, settings: Settings,
                 clock: Callable[[], datetime] = utc_now) -> None:
        self.repo = repo
        self.adapter = adapter
        self.settings = settings
        self.clock = clock
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

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

    def _job_requirements(self, owner_id: str, target: Target) -> list[Requirement]:
        if target.document_id is not None:
            if self.repo.get_document(owner_id, target.document_id) is None:
                raise StageError(code="not_found", category=ErrorCategory.input,
                                 detail="The job ad screenshot is missing.")
            image = self.repo.get_document_bytes(owner_id, target.document_id)
            return extract_requirements(self.adapter, image=image)
        job = {j["document_id"]: j for j in load_jobs()}.get(target.source_job_id or "")
        if job is None:
            raise StageError(code="not_found", category=ErrorCategory.input,
                             detail="The job ad is missing.")
        return extract_requirements(self.adapter,
                                    text=f"{job['title']}\n{job['description']}")

    def run_coverage(self, owner_id: str, run_id: str) -> None:
        """Grade the job's requirements against confirmed facts and store the matrix.

        The matrix is written only after the gate passes, so a quota stop or a failed gate
        leaves nothing half-written. The run stays in the coverage stage, because the next
        stage is chained by the caller (plan Task 15).
        """
        run = self.repo.get_run(owner_id, run_id)
        if run is None:
            return
        facts = self.repo.current_facts(owner_id, run.document_id)
        if any(f.status is FactStatus.extracted and is_high_impact(f) for f in facts):
            self._update(run, stage=RunStage.review, state=RunState.waiting_for_user,
                         message="Confirm or reject the highlighted facts first.", error=None)
            return
        confirmed = [f for f in facts if f.status is FactStatus.confirmed]
        run = self._update(run, stage=RunStage.coverage, state=RunState.running,
                           message="Grading the job requirements.", error=None)
        try:
            target = (self.repo.get_target(owner_id, run.target_id)
                      if run.target_id is not None else None)
            if target is None:
                raise StageError(code="not_found", category=ErrorCategory.input,
                                 detail="The target job is missing.")
            rows = grade_requirements(self._job_requirements(owner_id, target), confirmed,
                                      self.adapter)
            check_coverage_gate(rows, confirmed)
            self.repo.put_coverage(owner_id, target.target_id, rows)
        except StageError as exc:
            state = RunState.quota_exhausted if exc.code in QUOTA_CODES else RunState.failed
            self._update(run, state=state, message=exc.detail or exc.code, error=exc.code)
            return
        except Exception as exc:  # never let a background task die silently
            log.error("coverage failed run=%s error=%s", run_id, type(exc).__name__)
            self._update(run, state=RunState.failed, message="Internal error while grading.",
                         error="internal")
            return
        self._update(run, message=f"Graded {len(rows)} requirements.")

    def _fail(self, run: RunStatus, exc: Exception, what: str) -> None:
        if isinstance(exc, StageError):
            state = RunState.quota_exhausted if exc.code in QUOTA_CODES else RunState.failed
            self._update(run, state=state, message=exc.detail or exc.code, error=exc.code)
            return
        log.error("%s failed run=%s error=%s", what, run.run_id, type(exc).__name__)
        self._update(run, state=RunState.failed, message=f"Internal error while {what}.",
                     error="internal")

    def _context(self, owner_id: str) -> Layer1Context:
        return Layer1Context(owner_id=owner_id,
                             resolve=lambda ref: self.repo.get_fact(owner_id, ref),
                             lex=load_lexicons(), aliases=load_aliases(),
                             as_of=self.settings.as_of)

    def _target(self, owner_id: str, run: RunStatus) -> Target:
        target = (self.repo.get_target(owner_id, run.target_id)
                  if run.target_id is not None else None)
        if target is None:
            raise StageError(code="not_found", category=ErrorCategory.input,
                             detail="The target job is missing.")
        return target

    def run_plan_and_validate(self, owner_id: str, run_id: str) -> None:
        """Plan and validate claims; the plan and report are written only once both exist."""
        run = self.repo.get_run(owner_id, run_id)
        if run is None:
            return
        run = self._update(run, stage=RunStage.plan, state=RunState.running,
                           message="Planning and validating claims.", error=None)
        try:
            target = self._target(owner_id, run)
            coverage = self.repo.get_coverage(owner_id, target.target_id)
            if coverage is None:
                raise StageError(code="not_found", category=ErrorCategory.input,
                                 detail="Grade the job requirements first.")
            facts = [f for f in self.repo.current_facts(owner_id, run.document_id)
                     if f.status is FactStatus.confirmed]
            plan, report = plan_and_validate(owner_id, target, facts, coverage,
                                             self._context(owner_id), self.adapter)
            self.repo.put_plan(plan)
            self.repo.put_report(owner_id, report)
        except Exception as exc:  # never let a background task die silently
            self._fail(run, exc, "planning")
            return
        self._update(run, stage=RunStage.validate, plan_id=plan.plan_id,
                     message=f"Validated {len(report.results)} claims.")

    def _output_dir(self, owner_id: str, output_id: str) -> Path:
        if not SAFE_SEGMENT.match(owner_id) or not SAFE_SEGMENT.match(output_id):
            raise StageError(code="bad_id", category=ErrorCategory.input, detail="Bad ID.")
        return self.settings.data_dir / owner_id / "output_files" / output_id

    def _mark_superseded(self, owner_id: str, output_id: str) -> None:
        # The record and files stay (outputs keep the versions they used), but a newer render
        # replaced this one, so it is no longer offered for download.
        folder = self._output_dir(owner_id, output_id)
        if folder.is_dir():
            (folder / SUPERSEDED).write_text("superseded\n", encoding="utf-8")

    def output_file(self, owner_id: str, output_id: str, name: str) -> Path | None:
        """The file for `name` only if it is listed in the output and verification passed."""
        if not SAFE_SEGMENT.match(output_id):
            return None
        out = self.repo.get_output(owner_id, output_id)
        if out is None or out.post_render is None or not out.post_render.passed:
            return None
        rel = out.files.get(name)
        folder = self._output_dir(owner_id, output_id).resolve()
        if rel is None or (folder / SUPERSEDED).exists():
            return None
        path = (self.settings.data_dir / rel).resolve()
        return path if path.is_relative_to(folder) and path.is_file() else None

    def current_plan(self, owner_id: str, plan: ContentPlan) -> ContentPlan:
        """The plan without claims whose cited facts are no longer current and confirmed.

        A fact rejected or edited after validation must not stay in an output just because
        the report still says passed; the claim needs validating again first.
        """
        ctx = self._context(owner_id)
        kept = [c for c in plan.claims if not check_fact_ids(c, ctx)]
        if len(kept) < len(plan.claims):
            log.info("render skipped stale claims=%d plan=%s", len(plan.claims) - len(kept),
                     plan.plan_id)
        return plan.model_copy(update={"claims": kept})

    def receipt(self, owner_id: str, plan_id: str,
                claim_id: str) -> tuple[Claim, list[FactVersion]] | None:
        """A receipt exists only for a claim an output may show."""
        plan = self.repo.get_plan(owner_id, plan_id)
        report = self.repo.get_report(owner_id, plan_id)
        if plan is None or report is None:
            return None
        current = self.current_plan(owner_id, plan)
        claim = next((c for t in OutputType for c in renderable_claims(current, report, t)
                      if c.claim_id == claim_id), None)
        if claim is None:
            return None
        facts = [f for f in (self.repo.get_fact(owner_id, r) for r in claim.evidence)
                 if f is not None]
        return claim, facts

    def _render_one(self, owner_id: str, plan: ContentPlan, report: ValidationReport,
                    output_type: OutputType) -> Output:
        output_id = _new_id("out")
        folder = self._output_dir(owner_id, output_id)
        claims = renderable_claims(plan, report, output_type)
        expected = {c.claim_id: c.text for c in claims}
        written: list[Path] = []
        if not claims:
            # An empty template passes verification trivially; it is not a validated output.
            result = PostRenderResult(passed=False,
                                      problems=[_no_claims_reason(plan, report, output_type)])
        elif output_type is OutputType.visual_profile:
            html = render_profile(plan, report, IDENTITY, "/receipts/")
            result = verify_html(html, expected, IDENTITY, TEMPLATE_COPY)
            if result.passed:
                folder.mkdir(parents=True, exist_ok=True)
                page = folder / "profile.html"
                page.write_text(html, encoding="utf-8")
                written = [page, render_profile_pdf(html, folder / "profile.pdf")]
        else:
            deck = render_deck(plan, report, IDENTITY, folder / "deck.pptx")
            result = verify_pptx(deck, expected, TEMPLATE_COPY)
            if result.passed:
                written = [deck]
            else:
                deck.unlink()  # a deck that failed verification must not be exportable
        refs: list[FactRef] = []
        for c in claims:
            refs.extend(r for r in c.evidence if r not in refs)
        root = self.settings.data_dir
        return Output(output_id=output_id, owner_id=owner_id, plan_id=plan.plan_id,
                      output_type=output_type, claim_ids=list(expected), fact_refs=refs,
                      files={p.name: p.relative_to(root).as_posix() for p in written},
                      post_render=result)

    def run_render(self, owner_id: str, run_id: str) -> None:
        """Render both outputs and verify them. A failed check leaves that output with no
        files, so nothing unverified can be downloaded."""
        run = self.repo.get_run(owner_id, run_id)
        if run is None:
            return
        run = self._update(run, stage=RunStage.render, state=RunState.running,
                           message="Rendering and verifying the outputs.", error=None)
        try:
            plan = self.repo.get_plan(owner_id, run.plan_id or "")
            report = self.repo.get_report(owner_id, run.plan_id or "")
            if plan is None or report is None:
                raise StageError(code="not_found", category=ErrorCategory.input,
                                 detail="Plan and validate the claims first.")
            current = self.current_plan(owner_id, plan)
            outs = [self._render_one(owner_id, current, report, t) for t in OutputType]
            for out in outs:
                self.repo.put_output(out)
        except Exception as exc:  # never let a background task die silently
            self._fail(run, exc, "rendering")
            return
        for old in run.output_ids:
            self._mark_superseded(owner_id, old)
        blocked = sum(1 for o in outs if o.post_render is None or not o.post_render.passed)
        message = (f"{blocked} output(s) blocked. See the outputs page for the reasons."
                   if blocked else "Outputs rendered and verified.")
        self._update(run, stage=RunStage.done, state=RunState.done, message=message,
                     output_ids=[o.output_id for o in outs])

    @contextmanager
    def _exclusive(self, run_id: str) -> Iterator[bool]:
        """Yields False if another request is already working on this run."""
        with self._locks_guard:
            lock = self._locks.setdefault(run_id, threading.Lock())
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()

    def mark_pending(self, owner_id: str, run_id: str) -> bool:
        """Claims the run for a Continue before the background task starts, so a second
        click sees it as busy. Returns False if the run is already busy."""
        with self._exclusive(run_id) as acquired:
            run = self.repo.get_run(owner_id, run_id)
            if not acquired or run is None or run.state in BUSY:
                return False
            self._update(run, state=RunState.pending, message="Queued.", error=None)
            return True

    def facts_changed(self, owner_id: str, run_id: str) -> None:
        """A fact changed after review: send the run back so Continue grades again."""
        run = self.repo.get_run(owner_id, run_id)
        if run is None or run.stage in (RunStage.ingest, RunStage.review):
            return
        self._update(run, stage=RunStage.review, state=RunState.waiting_for_user, error=None,
                     message="Facts changed. Continue to grade, plan and render again.")

    def ensure_idle(self, owner_id: str, run_id: str) -> None:
        run = self.repo.get_run(owner_id, run_id)
        if run is not None and run.state in BUSY:
            raise StageError(code="run_busy", category=ErrorCategory.validation,
                             detail="This run is still working. Try again when it finishes.")

    def continue_after_review(self, owner_id: str, run_id: str) -> None:
        """Coverage, then plan and validate, then render.

        A run that already has a plan and report renders again without re-planning, so user
        approvals survive. A run stopped after coverage (on quota, say) reuses its stored
        matrix while it still matches the confirmed facts.
        """
        with self._exclusive(run_id) as acquired:
            run = self.repo.get_run(owner_id, run_id)
            if not acquired or run is None:
                return
            if run.stage in PLANNED_STAGES and self._has_plan(owner_id, run):
                self.run_render(owner_id, run_id)
                return
            if not self._coverage_reusable(owner_id, run):
                self.run_coverage(owner_id, run_id)
            for step in (self.run_plan_and_validate, self.run_render):
                run = self.repo.get_run(owner_id, run_id)
                if run is None or run.state is not RunState.running:
                    return
                step(owner_id, run_id)

    def _has_plan(self, owner_id: str, run: RunStatus) -> bool:
        return (run.plan_id is not None
                and self.repo.get_plan(owner_id, run.plan_id) is not None
                and self.repo.get_report(owner_id, run.plan_id) is not None)

    def _coverage_reusable(self, owner_id: str, run: RunStatus) -> bool:
        if run.stage in (RunStage.ingest, RunStage.review, RunStage.coverage):
            return False
        rows = (self.repo.get_coverage(owner_id, run.target_id)
                if run.target_id is not None else None)
        if rows is None:
            return False
        try:
            check_coverage_gate(rows, self.repo.current_facts(owner_id, run.document_id))
        except StageError:
            return False  # facts changed since grading, so grade again
        self._update(run, state=RunState.running, error=None)
        return True

    def review_claim(self, owner_id: str, run_id: str, claim_id: str, action: str) -> None:
        """Approve or drop a claim in user review, then render again."""
        with self._exclusive(run_id) as acquired:
            if not acquired:
                raise StageError(code="run_busy", category=ErrorCategory.validation,
                                 detail="This run is still working. Try again when it finishes.")
            self.ensure_idle(owner_id, run_id)
            self._review_claim(owner_id, run_id, claim_id, action)

    def _review_claim(self, owner_id: str, run_id: str, claim_id: str, action: str) -> None:
        run = self.repo.get_run(owner_id, run_id)
        plan = self.repo.get_plan(owner_id, run.plan_id or "") if run is not None else None
        report = self.repo.get_report(owner_id, plan.plan_id) if plan is not None else None
        claim = next((c for c in plan.claims if c.claim_id == claim_id), None) if plan else None
        if run is None or report is None or claim is None:
            raise StageError(code="not_found", category=ErrorCategory.input,
                             detail="No such claim.")
        matches = [v for v in report.results
                   if v.claim_id == claim_id and v.claim_version == claim.version]
        if (not matches or claim_id in report.dropped_claim_ids
                or any(v.outcome is not ClaimOutcome.user_review for v in matches)):
            raise StageError(code="not_in_review", category=ErrorCategory.validation,
                             detail="Only claims in user review can be approved or dropped.")
        if action == "approve":
            results = [v.model_copy(update={"approved_by_user": True}) if v in matches else v
                       for v in report.results]
            report = report.model_copy(update={"results": results})
        elif action == "drop":
            report = report.model_copy(
                update={"dropped_claim_ids": [*report.dropped_claim_ids, claim_id]})
        else:
            raise _bad_input("Unknown review action.")
        self.repo.put_report(owner_id, ValidationReport.model_validate_json(
            report.model_dump_json()))
        self.run_render(owner_id, run_id)

    def try_claim(self, owner_id: str, run_id: str, text: str,
                  refs: list[FactRef]) -> ClaimValidation:
        """Validate a typed claim live. It is never added to the plan."""
        if self.repo.get_run(owner_id, run_id) is None:
            raise StageError(code="not_found", category=ErrorCategory.input,
                             detail="No such run.")
        if not text.strip():
            raise _bad_input("Type a claim to try.")
        if not refs:
            raise _bad_input("Tick at least one fact for the claim to cite.")
        claim = Claim(claim_id="try", text=text.strip(), evidence=refs, section="Try",
                      emphasis=1, allowed_transformations=[],
                      output_types=[OutputType.visual_profile], parent_claim_id=None)
        return validate_claim(claim, self._context(owner_id), self.adapter)
