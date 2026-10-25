"""FastAPI app for the local demo. Runs on localhost only; there is no auth in the slice."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

from evident.errors import ErrorCategory, StageError
from evident.models.adapter import ModelAdapter
from evident.models.router import build_adapter
from evident.runs import RunService
from evident.settings import Settings, load_model_config
from evident.store.files import FileRepository
from evident.store.repository import Repository

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
NOT_FOUND_CODES = {"not_found", "bad_id"}


def create_app(settings: Settings, repo: Repository, adapter: ModelAdapter) -> FastAPI:
    from evident.web.routes import router

    app = FastAPI(title="Evident (A3 slice)", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.repo = repo
    app.state.service = RunService(repo, adapter, settings)
    app.include_router(router)

    @app.exception_handler(StageError)
    async def stage_error(request: Request, exc: StageError) -> Response:
        if exc.code in NOT_FOUND_CODES:
            return PlainTextResponse("Not found", status_code=404)
        status = 400 if exc.category in (ErrorCategory.input, ErrorCategory.validation) else 500
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"message": exc.detail or exc.code}, status_code=status
        )

    return app


def main() -> FastAPI:
    settings = Settings()
    return create_app(settings, FileRepository(settings.data_dir),
                      build_adapter(settings, load_model_config()))


