"""Pages and form actions for starting a run and reviewing facts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from evident.contracts.enums import FactStatus, RunState
from evident.contracts.facts import FactRef
from evident.contracts.runs import RunStatus
from evident.contracts.validation import ClaimValidation
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
MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


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
    service = _service(request)
    service.ensure_idle(OWNER, run_id)
    if confirm_low_impact(_repo(request), OWNER, run.document_id, utc_now()):
        service.facts_changed(OWNER, run_id)
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
    _service(request).ensure_idle(OWNER, run_id)
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
    # Outputs keep the fact versions they used; the run goes back to review so Continue
    # grades and validates against the changed facts.
    _service(request).facts_changed(OWNER, run_id)
    return _see_other(f"/runs/{run_id}/facts#{fact_id}")


@router.post("/runs/{run_id}/continue")
def continue_run(request: Request, run_id: str, background: BackgroundTasks) -> Response:
    _run(request, run_id)
    service = _service(request)
    # Marked pending here, not in the task, so a second click sees the run as busy.
    if service.mark_pending(OWNER, run_id):
        background.add_task(service.continue_after_review, OWNER, run_id)
    return _see_other(f"/runs/{run_id}")


@router.get("/runs/{run_id}/coverage", response_class=HTMLResponse)
def coverage_page(request: Request, run_id: str) -> Response:
    run = _run(request, run_id)
    rows = (_repo(request).get_coverage(OWNER, run.target_id)
            if run.target_id is not None else None)
    return TEMPLATES.TemplateResponse(request, "coverage.html", {"run": run, "rows": rows})


def _claims_page(request: Request, run: RunStatus, tried: ClaimValidation | None = None,
                 tried_text: str = "", tried_refs: list[str] | None = None,
                 try_error: str | None = None, status_code: int = 200) -> Response:
    repo = _repo(request)
    plan = repo.get_plan(OWNER, run.plan_id) if run.plan_id else None
    report = repo.get_report(OWNER, run.plan_id) if run.plan_id else None
    texts = {c.claim_id: c.text for c in plan.claims} if plan else {}
    facts = [f for f in repo.current_facts(OWNER, run.document_id)
             if f.status is FactStatus.confirmed]
    return TEMPLATES.TemplateResponse(request, "claims.html", {
        "run": run, "plan": plan, "report": report, "texts": texts, "facts": facts,
        "tried": tried, "tried_text": tried_text, "tried_refs": tried_refs or [],
        "try_error": try_error,
    }, status_code=status_code)


@router.get("/runs/{run_id}/claims", response_class=HTMLResponse)
def claims_page(request: Request, run_id: str) -> Response:
    return _claims_page(request, _run(request, run_id))


def _parse_ref(value: str) -> FactRef:
    fact_id, sep, version = value.strip().rpartition("@")
    if not sep or not fact_id or not version.isdigit():
        raise StageError(code="bad_input", category=ErrorCategory.input,
                         detail="Fact references look like fact_id@version.")
    return FactRef(fact_id=fact_id, version=int(version))


@router.post("/runs/{run_id}/claims/try", response_class=HTMLResponse)
def try_claim(request: Request, run_id: str, text: Annotated[str, Form()] = "",
              fact_ref: Annotated[list[str] | None, Form()] = None) -> Response:
    # Both fields are optional here: a browser omits unticked boxes entirely, and a missing
    # field must come back as a readable message on the page, not FastAPI's JSON error.
    run = _run(request, run_id)
    ticked = fact_ref or []
    try:
        refs = [_parse_ref(r) for r in ticked]
        result = _service(request).try_claim(OWNER, run_id, text, refs)
    except StageError as exc:
        if exc.category not in (ErrorCategory.input, ErrorCategory.validation) or (
                exc.code == "not_found"):
            raise
        return _claims_page(request, run, tried_text=text, tried_refs=ticked,
                            try_error=exc.detail or exc.code, status_code=400)
    return _claims_page(request, run, tried=result, tried_text=text, tried_refs=ticked)


@router.post("/runs/{run_id}/claims/{claim_id}/review")
def review_claim(request: Request, run_id: str, claim_id: str,
                 action: Annotated[str, Form()]) -> Response:
    _run(request, run_id)  # the run must be the owner's before anything else is looked up
    _service(request).review_claim(OWNER, run_id, claim_id, action)
    return _see_other(f"/runs/{run_id}/claims")


@router.get("/runs/{run_id}/outputs", response_class=HTMLResponse)
def outputs_page(request: Request, run_id: str) -> Response:
    run = _run(request, run_id)
    repo = _repo(request)
    found = [repo.get_output(OWNER, oid) for oid in run.output_ids]
    report = repo.get_report(OWNER, run.plan_id) if run.plan_id else None
    return TEMPLATES.TemplateResponse(request, "outputs.html", {
        "run": run, "outputs": [o for o in found if o is not None], "report": report,
    })


@router.get("/outputs/{output_id}/files/{name}")
def output_file(request: Request, output_id: str, name: str) -> Response:
    # Only names listed in the output are served; the URL never becomes part of a path.
    path = _service(request).output_file(OWNER, output_id, name)
    if path is None:
        raise StageError(code="not_found", category=ErrorCategory.input, detail="Not found.")
    media = MEDIA_TYPES.get(path.suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)


@router.get("/receipts/{claim_id}", response_class=HTMLResponse)
def receipt(request: Request, claim_id: str, plan_id: str) -> Response:
    found = _service(request).receipt(OWNER, plan_id, claim_id)
    if found is None:
        raise StageError(code="not_found", category=ErrorCategory.input, detail="Not found.")
    claim, facts = found
    return TEMPLATES.TemplateResponse(request, "receipt.html", {"claim": claim, "facts": facts})


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
