from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr

from evident.contracts.enums import FactStatus, RunStage, RunState
from evident.contracts.facts import FactRef
from evident.errors import ErrorCategory, StageError
from evident.settings import LOCAL_OWNER_ID, Role, Settings
from evident.store.files import FileRepository
from evident.web.app import create_app
from tests.builders import document, fact, vision_source
from tests.fakes import FakeAdapter

SAMPLE = "student_profile_01_classic_photo"


def draft_reply(*texts: str, start: str | None = None) -> str:
    return json.dumps({"facts": [
        {"kind": "skill" if start is None else "project", "text": t, "span_text": t,
         "box_2d": None, "attributes": {"skills": [t] if start is None else [],
                                        "start": start}}
        for t in texts
    ], "unreadable_regions": []})


def make(tmp_path: Path, replies: list[str | Exception]) -> tuple[TestClient, FileRepository]:
    settings = Settings(_env_file=None, gemini_api_key=SecretStr("x"), data_dir=tmp_path / "var")
    repo = FileRepository(settings.data_dir)
    app = create_app(settings, repo, FakeAdapter({Role.extraction_vision: replies}))
    return TestClient(app), repo


def start(client: TestClient) -> str:
    resp = client.post("/runs", data={"cv": SAMPLE, "job_id": "graduate_ai_engineer"},
                       follow_redirects=False)
    assert resp.status_code == 303
    return str(resp.headers["location"]).rsplit("/", 1)[-1]


def test_start_page_lists_samples_and_marks_synthetic(tmp_path: Path) -> None:
    client, _ = make(tmp_path, [])
    page = client.get("/").text
    assert SAMPLE in page and "graduate_ai_engineer" in page
    assert "Synthetic" in page


def test_run_ingests_sample_photo_and_waits_for_review(tmp_path: Path) -> None:
    client, repo = make(tmp_path, [draft_reply("Python", "Flask")])
    run_id = start(client)
    run = repo.get_run(LOCAL_OWNER_ID, run_id)
    assert run is not None
    assert (run.stage, run.state) == (RunStage.review, RunState.waiting_for_user)
    assert "Review" in client.get(f"/runs/{run_id}").text


def test_facts_page_lists_fact_with_crop_link(tmp_path: Path) -> None:
    client, repo = make(tmp_path, [draft_reply("Python")])
    run_id = start(client)
    run = repo.get_run(LOCAL_OWNER_ID, run_id)
    assert run is not None
    page = client.get(f"/runs/{run_id}/facts").text
    [f] = repo.current_facts(LOCAL_OWNER_ID, run.document_id)
    assert "Python" in page
    assert f"/documents/{run.document_id}/source?fact_id={f.fact_id}&amp;version=1" in page


def test_source_route_returns_png_for_own_fact(tmp_path: Path) -> None:
    client, repo = make(tmp_path, [draft_reply("Python")])
    run_id = start(client)
    run = repo.get_run(LOCAL_OWNER_ID, run_id)
    assert run is not None
    [f] = repo.current_facts(LOCAL_OWNER_ID, run.document_id)
    resp = client.get(f"/documents/{run.document_id}/source",
                      params={"fact_id": f.fact_id, "version": 1})
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    Image.open(io.BytesIO(resp.content)).verify()


def test_source_route_404_for_other_owner(tmp_path: Path) -> None:
    client, repo = make(tmp_path, [])
    other = "someone-else"
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    repo.put_document(document(owner_id=other, media_type="image/png", width_px=40,
                               height_px=40), buf.getvalue())
    repo.put_fact(fact(owner_id=other, source=vision_source(bbox=(0.0, 0.0, 40.0, 40.0))))
    for params in ({"fact_id": "doc_01_f01", "version": 1}, {"fact_id": "nope", "version": 1}):
        assert client.get("/documents/doc_01/source", params=params).status_code == 404
    assert client.get("/documents/missing/source",
                      params={"fact_id": "x", "version": 1}).status_code == 404


def test_confirm_reject_and_low_impact_routes(tmp_path: Path) -> None:
    client, repo = make(tmp_path, [draft_reply("Python", "Flask", "SQL")])
    run_id = start(client)
    run = repo.get_run(LOCAL_OWNER_ID, run_id)
    assert run is not None
    a, b, c = repo.current_facts(LOCAL_OWNER_ID, run.document_id)
    # Photo boxes here are unverified, so every fact is high impact and needs its own confirm.
    assert client.post(f"/runs/{run_id}/facts/confirm-low-impact",
                       follow_redirects=False).status_code == 303
    for f, action in ((a, "confirm"), (b, "reject")):
        resp = client.post(f"/facts/{f.fact_id}/v/1/{action}", data={"run_id": run_id},
                           follow_redirects=False)
        assert resp.status_code == 303
    statuses = {f.fact_id: f.status for f in repo.current_facts(LOCAL_OWNER_ID)}
    assert statuses == {a.fact_id: FactStatus.confirmed, b.fact_id: FactStatus.rejected,
                        c.fact_id: FactStatus.extracted}


def test_edit_route_creates_new_version(tmp_path: Path) -> None:
    client, repo = make(tmp_path, [draft_reply("Pythn")])
    run_id = start(client)
    run = repo.get_run(LOCAL_OWNER_ID, run_id)
    assert run is not None
    [f] = repo.current_facts(LOCAL_OWNER_ID, run.document_id)
    resp = client.post(f"/facts/{f.fact_id}/v/1/edit",
                       data={"run_id": run_id, "text": "Python", "skills": "Python"},
                       follow_redirects=False)
    assert resp.status_code == 303
    new = repo.get_fact(LOCAL_OWNER_ID, FactRef(fact_id=f.fact_id, version=2))
    assert new is not None and new.text == "Python" and new.edited_by_user


def test_bad_edit_shows_error_not_crash(tmp_path: Path) -> None:
    client, repo = make(tmp_path, [draft_reply("Python")])
    run_id = start(client)
    run = repo.get_run(LOCAL_OWNER_ID, run_id)
    assert run is not None
    [f] = repo.current_facts(LOCAL_OWNER_ID, run.document_id)
    resp = client.post(f"/facts/{f.fact_id}/v/1/edit",
                       data={"run_id": run_id, "start": "March 2025"})
    assert resp.status_code == 400 and "YYYY-MM" in resp.text


def test_fact_text_is_escaped(tmp_path: Path) -> None:
    client, _ = make(tmp_path, [draft_reply("<script>alert(1)</script>")])
    run_id = start(client)
    page = client.get(f"/runs/{run_id}/facts").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_upload_rejects_non_cv_file(tmp_path: Path) -> None:
    client, _ = make(tmp_path, [])
    resp = client.post("/runs", data={"job_id": "graduate_ai_engineer"},
                       files={"upload": ("notes.txt", b"hello", "text/plain")})
    assert resp.status_code == 400


def test_quota_error_sets_quota_exhausted_state(tmp_path: Path) -> None:  # Review Focus 5
    detail = "Free-tier daily quota reached (498/500). Resets at midnight Pacific."
    quota = StageError(code="daily_quota", category=ErrorCategory.provider, detail=detail)
    client, repo = make(tmp_path, [quota])
    run_id = start(client)
    run = repo.get_run(LOCAL_OWNER_ID, run_id)
    assert run is not None and run.state is RunState.quota_exhausted
    assert run.stage is RunStage.ingest
    assert "daily quota reached" in client.get(f"/runs/{run_id}").text
    assert repo.current_facts(LOCAL_OWNER_ID) == []


def test_unknown_run_is_404(tmp_path: Path) -> None:
    client, _ = make(tmp_path, [])
    assert client.get("/runs/r_nothere").status_code == 404
    assert client.get("/runs/r_nothere/facts").status_code == 404


@pytest.mark.parametrize("cv", ["../../.env", "student_profile_01_classic_photo.jpg"])
def test_unknown_sample_rejected(tmp_path: Path, cv: str) -> None:
    client, _ = make(tmp_path, [])
    resp = client.post("/runs", data={"cv": cv, "job_id": "graduate_ai_engineer"})
    assert resp.status_code == 400
