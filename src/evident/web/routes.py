"""Pages and form actions for starting a run and reviewing facts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from evident.contracts.enums import RunState
from evident.contracts.facts import FactRef
from evident.contracts.runs import RunStatus
from evident.errors import ErrorCategory, StageError
from evident.render.receipts import crop_source
from evident.review.actions import (
    FactEdit,
    confirm,
    confirm_low_impact,
    edit,
    is_high_impact,
    reject,
)
from evident.runs import MAX_UPLOAD_BYTES, RunService, load_jobs, sample_cvs, utc_now
from evident.settings import LOCAL_OWNER_ID
from evident.store.repository import Repository
from evident.web.app import TEMPLATES

router = APIRouter()
# No auth in the slice (spec 3): every request acts as the single local owner.
OWNER = LOCAL_OWNER_ID
ACTIVE = {RunState.pending, RunState.running}


def _repo(request: Request) -> Repository:
    repo: Repository = request.app.state.repo
    return repo


def _service(request: Request) -> RunService:
    service: RunService = request.app.state.service
    return service


def _run(request: Request, run_id: str) -> RunStatus:
    run = _repo(request).get_run(OWNER, run_id)
    if run is None:
        raise StageError(code="not_found", category=ErrorCategory.input, detail="No such run.")
    return run


def _see_other(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


@router.get("/", response_class=HTMLResponse)
def start_page(request: Request) -> Response:
    return TEMPLATES.TemplateResponse(request, "start.html", {
        "samples": sorted(sample_cvs()), "jobs": load_jobs(),
    })


@router.post("/runs")
async def start_run(
    request: Request,
    background: BackgroundTasks,
    cv: Annotated[str | None, Form()] = None,
    job_id: Annotated[str | None, Form()] = None,
    use_job_screenshot: Annotated[bool, Form()] = False,
    upload: Annotated[UploadFile | None, File()] = None,
) -> Response:
    uploaded = None
    if upload is not None and upload.filename:
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        uploaded = (upload.filename, data)
    sample = None if uploaded is not None else (cv or None)  # an upload wins over a sample
    run = _service(request).start(OWNER, sample, uploaded,
                                  job_id or None, use_job_screenshot)
    background.add_task(_service(request).run_ingest, OWNER, run.run_id)
    return _see_other(f"/runs/{run.run_id}")


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: str) -> Response:
    run = _run(request, run_id)
    return TEMPLATES.TemplateResponse(request, "run.html", {
        "run": run, "refresh": run.state in ACTIVE,
    })


def _facts_page(request: Request, run: RunStatus, error: str | None = None,
                status_code: int = 200) -> Response:
    facts = _repo(request).current_facts(OWNER, run.document_id)
    rows = [{"fact": f, "high_impact": is_high_impact(f)} for f in facts]
    return TEMPLATES.TemplateResponse(request, "facts.html", {
        "run": run, "rows": rows, "error": error,
    }, status_code=status_code)


@router.get("/runs/{run_id}/facts", response_class=HTMLResponse)
def facts_page(request: Request, run_id: str) -> Response:
    return _facts_page(request, _run(request, run_id))


@router.post("/runs/{run_id}/facts/confirm-low-impact")
def confirm_low(request: Request, run_id: str) -> Response:
    run = _run(request, run_id)
    confirm_low_impact(_repo(request), OWNER, run.document_id, utc_now())
    return _see_other(f"/runs/{run_id}/facts")


def _split(value: str | None) -> list[str] | None:
    return None if value is None else [s.strip() for s in value.split(",") if s.strip()]


@router.post("/facts/{fact_id}/v/{version}/{action}")
def fact_action(
    request: Request,
    fact_id: str,
    version: int,
    action: str,
    run_id: Annotated[str, Form()],
    text: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
    organisation: Annotated[str | None, Form()] = None,
    start: Annotated[str | None, Form()] = None,
    end: Annotated[str | None, Form()] = None,
    ownership: Annotated[str | None, Form()] = None,
    deployment: Annotated[str | None, Form()] = None,
    skills: Annotated[str | None, Form()] = None,
) -> Response:
    run = _run(request, run_id)
    repo = _repo(request)
    ref = FactRef(fact_id=fact_id, version=version)
    fact = repo.get_fact(OWNER, ref)
    if fact is None or getattr(fact.source, "document_id", None) != run.document_id:
        raise StageError(code="not_found", category=ErrorCategory.input, detail="No such fact.")
    try:
        if action == "confirm":
            confirm(repo, OWNER, ref, utc_now())
        elif action == "reject":
            reject(repo, OWNER, ref)
        elif action == "edit":
            edit(repo, OWNER, ref, FactEdit(text=text, title=title, organisation=organisation,
                                           start=start, end=end, ownership=ownership,
                                           deployment=deployment, skills=_split(skills)),
                 utc_now())
        else:
            raise StageError(code="not_found", category=ErrorCategory.input,
                             detail="Unknown action.")
    except StageError as exc:
        if exc.category is ErrorCategory.validation:
            return _facts_page(request, run, error=exc.detail, status_code=400)
        raise
    return _see_other(f"/runs/{run_id}/facts#{fact_id}")


@router.get("/documents/{document_id}/source")
def source_crop(request: Request, document_id: str, fact_id: str, version: int) -> Response:
    repo = _repo(request)
    doc = repo.get_document(OWNER, document_id)
    fact = repo.get_fact(OWNER, FactRef(fact_id=fact_id, version=version))
    # The same answer for "not yours" and "doesn't exist", so IDs can't be probed.
    if doc is None or fact is None or getattr(fact.source, "document_id", None) != document_id:
        raise StageError(code="not_found", category=ErrorCategory.input, detail="Not found.")
    png = crop_source(doc, repo.get_document_bytes(OWNER, document_id), fact.source)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
