from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from evident.contracts.enums import ClaimOutcome, OutputType, RunStage, RunState
from evident.contracts.outputs import Output, PostRenderResult
from evident.contracts.runs import RunStatus
from evident.errors import ErrorCategory, StageError
from evident.runs import RunService
from evident.settings import LOCAL_OWNER_ID, Role, Settings
from evident.store.files import FileRepository
from evident.web.app import create_app
from tests.fakes import FakeAdapter
from tests.validation.support import judge_reply

OWNER = LOCAL_OWNER_ID
SAMPLE = "student_profile_01_classic_photo"
GOOD = "Built a timetable clash checker in Python"
INFLATED = "Led a production deployment of the timetable clash checker"


def vision_reply() -> str:
    return json.dumps({"facts": [
        {"kind": "project", "text": "Built a timetable clash checker in Python and Flask",
         "span_text": "Built a timetable clash checker (Python, Flask)", "box_2d": None,
         "attributes": {"ownership": "built", "deployment": "prototype", "start": "2025-02",
                        "end": "2025-06", "title": "Team Course Planner",
                        "skills": ["Python", "Flask"]}},
        {"kind": "skill", "text": "Python", "span_text": "Python", "box_2d": None,
         "attributes": {"skills": ["Python"]}},
    ], "unreadable_regions": []})


def requirements_reply() -> str:
    return json.dumps({"requirements": [{"text": "Python", "category": "required"}]})


def coverage_reply(fact_id: str) -> str:
    return json.dumps({"rows": [{"requirement_id": "req_01", "grade": "strong",
                                 "evidence": [f"{fact_id}@1"], "rationale": "ok"}]})


def plan_reply(fact_id: str, *texts: str,
               output_types: tuple[str, ...] = ("visual_profile", "interview_deck")) -> str:
    return json.dumps({"claims": [
        {"text": t, "evidence": [f"{fact_id}@1"], "section": "Projects", "emphasis": 3,
         "output_types": list(output_types), "narrative_for": None}
        for t in texts]})


def make(tmp_path: Path) -> tuple[TestClient, FileRepository, FakeAdapter, Settings]:
    settings = Settings(_env_file=None, gemini_api_key=SecretStr("x"), data_dir=tmp_path / "var")
    repo = FileRepository(settings.data_dir)
    adapter = FakeAdapter({Role.extraction_vision: [vision_reply()]})
    return TestClient(create_app(settings, repo, adapter)), repo, adapter, settings


def reviewed_run(client: TestClient, repo: FileRepository) -> tuple[str, str]:
    """Start a photo run and confirm every fact; returns (run_id, project fact_id)."""
    resp = client.post("/runs", data={"cv": SAMPLE, "job_id": "graduate_ai_engineer"},
                       follow_redirects=False)
    run_id = str(resp.headers["location"]).rsplit("/", 1)[-1]
    run = get_run(repo, run_id)
    client.post(f"/runs/{run_id}/facts/confirm-low-impact", follow_redirects=False)
    facts = repo.current_facts(OWNER, run.document_id)
    for f in facts:  # photo boxes are unverified here, so each fact needs its own confirm
        client.post(f"/facts/{f.fact_id}/v/1/confirm", data={"run_id": run_id},
                    follow_redirects=False)
    project = next(f for f in facts if f.kind.value == "project")
    return run_id, project.fact_id


def get_run(repo: FileRepository, run_id: str) -> RunStatus:
    run = repo.get_run(OWNER, run_id)
    assert run is not None
    return run


def queue_pipeline(adapter: FakeAdapter, fact_id: str, good_confidence: float = 0.95) -> None:
    adapter.responses[Role.requirements] = [requirements_reply()]
    adapter.responses[Role.coverage] = [coverage_reply(fact_id)]
    adapter.responses[Role.planner] = [plan_reply(fact_id, GOOD, INFLATED),
                                       plan_reply(fact_id, GOOD, INFLATED)]
    adapter.responses[Role.judge] = [judge_reply(confidence=good_confidence),
                                     judge_reply("overstated", 0.9, "production")]


def outputs(repo: FileRepository, run_id: str) -> list[Output]:
    found = [repo.get_output(OWNER, oid) for oid in get_run(repo, run_id).output_ids]
    return [o for o in found if o is not None]


def test_full_flow_with_fake_adapter(tmp_path: Path) -> None:
    client, repo, adapter, settings = make(tmp_path)
    run_id, fact_id = reviewed_run(client, repo)
    queue_pipeline(adapter, fact_id)
    assert client.post(f"/runs/{run_id}/continue", follow_redirects=False).status_code == 303

    run = get_run(repo, run_id)
    assert (run.stage, run.state) == (RunStage.done, RunState.done), run.message
    outs = outputs(repo, run_id)
    assert sorted(o.output_type.value for o in outs) == ["interview_deck", "visual_profile"]
    for o in outs:
        assert o.post_render is not None and o.post_render.passed, o.post_render
        assert o.claim_ids == ["c_001"]
        for name, rel in o.files.items():
            path = settings.data_dir / rel
            assert path.is_file()
            assert path.is_relative_to(settings.data_dir / OWNER / "output_files" / o.output_id)
            assert client.get(f"/outputs/{o.output_id}/files/{name}").status_code == 200

    claims_page = client.get(f"/runs/{run_id}/claims").text
    assert INFLATED in claims_page and "rejected" in claims_page
    assert "rule ownership" in claims_page and '"production"' in claims_page
    assert client.post(f"/runs/{run_id}/claims/c_001/review",
                       data={"action": "approve"}).status_code == 400  # passed, not in review
    assert "Python" in client.get(f"/runs/{run_id}/coverage").text
    outputs_page = client.get(f"/runs/{run_id}/outputs").text
    assert "Small local judge" in outputs_page or "Same-family judge" in outputs_page

    adapter.responses[Role.judge] = [judge_reply("overstated", 0.9, "production")]
    tried = client.post(f"/runs/{run_id}/claims/try",
                        data={"text": "Led a production deployment", "fact_ref": f"{fact_id}@1"})
    assert tried.status_code == 200 and "rejected" in tried.text
    plan = repo.get_plan(OWNER, run.plan_id or "")
    assert plan is not None and [c.text for c in plan.claims] == [GOOD, INFLATED]


def test_passed_output_files_are_served_with_their_content_type(tmp_path: Path) -> None:
    client, repo, adapter, _ = make(tmp_path)
    run_id, fact_id = reviewed_run(client, repo)
    queue_pipeline(adapter, fact_id)
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    wanted = {
        "profile.html": "text/html; charset=utf-8",
        "profile.pdf": "application/pdf",
        "deck.pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    served: dict[str, bytes] = {}
    for o in outputs(repo, run_id):
        for name in o.files:
            resp = client.get(f"/outputs/{o.output_id}/files/{name}")
            assert resp.status_code == 200 and resp.headers["content-type"] == wanted[name]
            served[name] = resp.content
    assert set(served) == set(wanted)
    assert served["profile.pdf"].startswith(b"%PDF-")
    assert served["deck.pptx"].startswith(b"PK")
    assert GOOD in served["profile.html"].decode("utf-8")


def test_dropped_claim_text_never_rendered(tmp_path: Path) -> None:
    from pptx import Presentation

    client, repo, adapter, settings = make(tmp_path)
    run_id, fact_id = reviewed_run(client, repo)
    queue_pipeline(adapter, fact_id)
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    report = repo.get_report(OWNER, get_run(repo, run_id).plan_id or "")
    assert report is not None and report.dropped_claim_ids == ["c_002"]
    outs = {o.output_type: o for o in outputs(repo, run_id)}
    html = (settings.data_dir / outs[OutputType.visual_profile].files["profile.html"]).read_text(
        encoding="utf-8")
    assert GOOD in html and INFLATED not in html and "c_002" not in html
    deck = Presentation(str(settings.data_dir / outs[OutputType.interview_deck].files["deck.pptx"]))
    texts: list[str] = []
    for slide in deck.slides:
        texts.extend(s.text_frame.text for s in slide.shapes if s.has_text_frame)
        texts.append(slide.notes_slide.notes_text_frame.text)
    joined = "\n".join(texts)
    assert GOOD in joined and INFLATED not in joined and "c_002" not in joined


def done_run(tmp_path: Path, good_confidence: float = 0.95) -> tuple[
        TestClient, FileRepository, FakeAdapter, Settings, str, str]:
    client, repo, adapter, settings = make(tmp_path)
    run_id, fact_id = reviewed_run(client, repo)
    queue_pipeline(adapter, fact_id, good_confidence)
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    assert get_run(repo, run_id).state is RunState.done
    return client, repo, adapter, settings, run_id, fact_id


def service_of(client: TestClient) -> RunService:
    service: RunService = client.app.state.service  # type: ignore[attr-defined]
    return service


def edit_fact(client: TestClient, run_id: str, fact_id: str) -> None:
    """Edits supersede v1; confirmed facts can only change this way."""
    resp = client.post(f"/facts/{fact_id}/v/1/edit", data={"run_id": run_id, "text": "Edited"},
                       follow_redirects=False)
    assert resp.status_code == 303


def test_render_skips_claims_whose_facts_changed(tmp_path: Path) -> None:
    client, repo, _, _, run_id, fact_id = done_run(tmp_path)
    edit_fact(client, run_id, fact_id)
    service_of(client).run_render(OWNER, run_id)
    outs = outputs(repo, run_id)
    assert len(outs) == 2 and all(o.claim_ids == [] for o in outs)


def test_approving_a_claim_whose_fact_was_superseded_does_not_render_it(tmp_path: Path) -> None:
    client, repo, _, _, run_id, fact_id = done_run(tmp_path, good_confidence=0.5)
    edit_fact(client, run_id, fact_id)
    client.post(f"/runs/{run_id}/claims/c_001/review", data={"action": "approve"},
                follow_redirects=False)
    profile = next(o for o in outputs(repo, run_id)
                   if o.output_type is OutputType.visual_profile)
    assert profile.claim_ids == [] and profile.files == {}
    assert profile.post_render is not None and not profile.post_render.passed


def test_superseded_outputs_are_not_served(tmp_path: Path) -> None:
    client, repo, _, _, run_id, _ = done_run(tmp_path)
    old = outputs(repo, run_id)
    service_of(client).run_render(OWNER, run_id)
    new = outputs(repo, run_id)
    assert {o.output_id for o in old}.isdisjoint({o.output_id for o in new})
    for o in old:
        for name in o.files:
            assert client.get(f"/outputs/{o.output_id}/files/{name}").status_code == 404
    for o in new:
        for name in o.files:
            assert client.get(f"/outputs/{o.output_id}/files/{name}").status_code == 200


def test_continue_after_failed_render_keeps_plan_and_approvals(tmp_path: Path) -> None:
    client, repo, adapter, _, run_id, _ = done_run(tmp_path, good_confidence=0.5)
    client.post(f"/runs/{run_id}/claims/c_001/review", data={"action": "approve"},
                follow_redirects=False)
    run = get_run(repo, run_id)
    repo.put_run(run.model_copy(update={"stage": RunStage.render, "state": RunState.failed}))
    planner_calls = [c.role for c in adapter.calls].count(Role.planner)
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    after = get_run(repo, run_id)
    assert after.state is RunState.done and after.plan_id == run.plan_id
    assert [c.role for c in adapter.calls].count(Role.planner) == planner_calls
    assert all(o.claim_ids == ["c_001"] for o in outputs(repo, run_id))


def test_fact_change_after_quota_stop_forces_regrade(tmp_path: Path) -> None:
    client, repo, adapter, _ = make(tmp_path)
    run_id, fact_id = reviewed_run(client, repo)
    queue_pipeline(adapter, fact_id)
    quota = StageError(code="daily_quota", category=ErrorCategory.provider, detail="quota")
    adapter.responses[Role.planner].insert(0, quota)
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    run = get_run(repo, run_id)
    skill = next(f for f in repo.current_facts(OWNER, run.document_id) if f.fact_id != fact_id)
    edit_fact(client, run_id, skill.fact_id)
    assert get_run(repo, run_id).stage is RunStage.review
    client.post(f"/facts/{skill.fact_id}/v/2/confirm", data={"run_id": run_id},
                follow_redirects=False)
    adapter.responses[Role.requirements] = [requirements_reply()]
    adapter.responses[Role.coverage] = [coverage_reply(fact_id)]
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    assert get_run(repo, run_id).state is RunState.done
    assert [c.role for c in adapter.calls].count(Role.coverage) == 2


def test_review_refused_and_continue_ignored_while_run_is_active(tmp_path: Path) -> None:
    client, repo, adapter, _, run_id, _ = done_run(tmp_path, good_confidence=0.5)
    run = get_run(repo, run_id)
    repo.put_run(run.model_copy(update={"state": RunState.running}))
    calls = len(adapter.calls)
    resp = client.post(f"/runs/{run_id}/claims/c_001/review", data={"action": "approve"})
    assert resp.status_code == 400
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    assert len(adapter.calls) == calls
    report = repo.get_report(OWNER, run.plan_id or "")
    assert report is not None and not any(v.approved_by_user for v in report.results)


def test_continue_marks_run_pending_before_background_work(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, repo, _, _ = make(tmp_path)
    run_id, _ = reviewed_run(client, repo)
    seen: list[RunState] = []
    monkeypatch.setattr(service_of(client), "continue_after_review",
                        lambda owner, rid: seen.append(get_run(repo, rid).state))
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    assert seen == [RunState.pending]


def test_receipts_only_for_rendered_claims(tmp_path: Path) -> None:
    client, repo, _, _, run_id, _ = done_run(tmp_path)
    plan_id = get_run(repo, run_id).plan_id
    assert client.get("/receipts/c_001", params={"plan_id": plan_id}).status_code == 200
    assert client.get("/receipts/c_002", params={"plan_id": plan_id}).status_code == 404


def test_failed_verification_leaves_no_files(tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from evident.render.profile_html import render_profile as real

    monkeypatch.setattr("evident.runs.render_profile",
                        lambda *a: real(*a).replace("</body>", "<p>Led 50 engineers</p></body>"))
    client, repo, _, settings, run_id, _ = done_run(tmp_path)
    profile = next(o for o in outputs(repo, run_id)
                   if o.output_type is OutputType.visual_profile)
    assert profile.post_render is not None and not profile.post_render.passed
    assert profile.files == {}
    assert not (settings.data_dir / OWNER / "output_files" / profile.output_id).exists()
    assert client.get(f"/outputs/{profile.output_id}/files/profile.html").status_code == 404
    assert "blocked" in get_run(repo, run_id).message


def test_drop_removes_review_claim_from_outputs(tmp_path: Path) -> None:
    client, repo, _, _, run_id, _ = done_run(tmp_path, good_confidence=0.5)
    resp = client.post(f"/runs/{run_id}/claims/c_001/review", data={"action": "drop"},
                       follow_redirects=False)
    assert resp.status_code == 303
    report = repo.get_report(OWNER, get_run(repo, run_id).plan_id or "")
    assert report is not None and "c_001" in report.dropped_claim_ids
    assert all(o.claim_ids == [] for o in outputs(repo, run_id))
    again = client.post(f"/runs/{run_id}/claims/c_001/review", data={"action": "approve"})
    assert again.status_code == 400


class _TryForm(HTMLParser):
    """Reads the Live box form the way a browser would: its action, text input and the
    fact checkboxes inside it."""

    def __init__(self) -> None:
        super().__init__()
        self.inside = False
        self.action: str | None = None
        self.fields: list[tuple[str, str, str]] = []  # (type, name, value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "form" and (a.get("action") or "").endswith("/claims/try"):
            self.inside, self.action = True, a.get("action")
        elif self.inside and tag in ("input", "select", "textarea"):
            self.fields.append((a.get("type") or tag, a.get("name") or "", a.get("value") or ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.inside = False


def try_form(client: TestClient, run_id: str) -> _TryForm:
    form = _TryForm()
    form.feed(client.get(f"/runs/{run_id}/claims").text)
    assert form.action == f"/runs/{run_id}/claims/try"
    return form


def test_try_form_posts_ticked_fact_as_the_browser_does(tmp_path: Path) -> None:
    client, _, adapter, _, run_id, fact_id = done_run(tmp_path)
    form = try_form(client, run_id)
    boxes = [(n, v) for t, n, v in form.fields if t == "checkbox"]
    assert ("fact_ref", f"{fact_id}@1") in boxes  # every confirmed fact is a box in the form
    assert ("text", "text", "") in form.fields
    adapter.responses[Role.judge] = [judge_reply()]
    # A browser sends the text input and only the ticked boxes.
    resp = client.post(form.action or "", data={"text": "Built a prototype clash checker",
                                                "fact_ref": f"{fact_id}@1"})
    assert resp.status_code == 200
    assert "Built a prototype clash checker" in resp.text and "passed" in resp.text


def test_try_form_with_no_fact_ticked_shows_readable_error(tmp_path: Path) -> None:
    client, _, adapter, _, run_id, _ = done_run(tmp_path)
    form = try_form(client, run_id)
    calls = len(adapter.calls)
    resp = client.post(form.action or "", data={"text": "Built a prototype clash checker"})
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("text/html")
    assert "Tick at least one fact" in resp.text
    assert len(adapter.calls) == calls  # nothing sent to the judge


def test_output_with_no_claims_is_blocked_with_review_reason(tmp_path: Path) -> None:
    client, repo, _, _, run_id, _ = done_run(tmp_path, good_confidence=0.5)
    outs = outputs(repo, run_id)
    assert len(outs) == 2
    reason = "No validated claims for this output: 1 claim is waiting for your review."
    for o in outs:
        assert o.claim_ids == [] and o.files == {}
        assert o.post_render == PostRenderResult(passed=False, problems=[reason])
    page = client.get(f"/runs/{run_id}/outputs").text
    assert reason in page and "post-render verification failed" not in page
    assert "blocked" in get_run(repo, run_id).message
    client.post(f"/runs/{run_id}/claims/c_001/review", data={"action": "approve"},
                follow_redirects=False)
    assert all(o.post_render is not None and o.post_render.passed and o.files
               for o in outputs(repo, run_id))


def test_output_with_no_claims_and_none_pending_is_blocked(tmp_path: Path) -> None:
    client, repo, adapter, _ = make(tmp_path)
    run_id, fact_id = reviewed_run(client, repo)
    queue_pipeline(adapter, fact_id)
    adapter.responses[Role.judge] = [judge_reply("overstated", 0.9, "timetable"),
                                     judge_reply("overstated", 0.9, "production")]
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    for o in outputs(repo, run_id):
        assert o.post_render == PostRenderResult(
            passed=False, problems=["No validated claims for this output."])
        assert o.files == {}


def test_deck_filled_when_planner_tags_no_deck_claims(tmp_path: Path) -> None:
    from pptx import Presentation

    client, repo, adapter, settings = make(tmp_path)
    run_id, fact_id = reviewed_run(client, repo)
    queue_pipeline(adapter, fact_id)
    profile_only = plan_reply(fact_id, GOOD, INFLATED, output_types=("visual_profile",))
    adapter.responses[Role.planner] = [profile_only, profile_only]
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    deck = next(o for o in outputs(repo, run_id) if o.output_type is OutputType.interview_deck)
    assert deck.claim_ids == ["c_001"]
    assert deck.post_render is not None and deck.post_render.passed
    prs = Presentation(str(settings.data_dir / deck.files["deck.pptx"]))
    assert len(prs.slides) == 2
    body = [s.text_frame.text for s in prs.slides[1].shapes if s.has_text_frame]
    assert GOOD in body and INFLATED not in body


def test_blocked_output_files_are_not_served(tmp_path: Path) -> None:
    client, repo, _, settings = make(tmp_path)
    folder = settings.data_dir / OWNER / "output_files" / "out_blocked"
    folder.mkdir(parents=True)
    (folder / "profile.html").write_text("<p>x</p>", encoding="utf-8")
    repo.put_output(Output(output_id="out_blocked", owner_id=OWNER, plan_id="plan_x",
                           output_type=OutputType.visual_profile, claim_ids=[], fact_refs=[],
                           files={"profile.html": f"{OWNER}/output_files/out_blocked/profile.html"},
                           post_render=PostRenderResult(passed=False, problems=["changed"])))
    assert client.get("/outputs/out_blocked/files/profile.html").status_code == 404
    assert client.get("/outputs/out_missing/files/profile.html").status_code == 404


def test_file_route_serves_only_named_files(tmp_path: Path) -> None:
    client, repo, adapter, _ = make(tmp_path)
    run_id, fact_id = reviewed_run(client, repo)
    queue_pipeline(adapter, fact_id)
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    profile = next(o for o in outputs(repo, run_id)
                   if o.output_type is OutputType.visual_profile)
    for name in ("profile.json", "..%2F..%2Fruns", "deck.pptx"):
        assert client.get(f"/outputs/{profile.output_id}/files/{name}").status_code == 404


def test_quota_mid_run_resumes_from_stage(tmp_path: Path) -> None:
    client, repo, adapter, _ = make(tmp_path)
    run_id, fact_id = reviewed_run(client, repo)
    queue_pipeline(adapter, fact_id)
    quota = StageError(code="daily_quota", category=ErrorCategory.provider,
                       detail="Free-tier daily quota reached (500/500).")
    adapter.responses[Role.planner].insert(0, quota)
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    run = get_run(repo, run_id)
    assert (run.stage, run.state, run.error) == (RunStage.plan, RunState.quota_exhausted,
                                                 "daily_quota")
    assert run.plan_id is None and run.output_ids == []

    # Requirements and coverage have no replies left, so a rerun of those stages would fail.
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    run = get_run(repo, run_id)
    assert run.state is RunState.done, run.message
    assert [c.role for c in adapter.calls].count(Role.coverage) == 1


def test_review_approve_renders_claim_and_rejected_cannot_be_approved(tmp_path: Path) -> None:
    client, repo, adapter, _ = make(tmp_path)
    run_id, fact_id = reviewed_run(client, repo)
    queue_pipeline(adapter, fact_id, good_confidence=0.5)  # GOOD goes to user review
    client.post(f"/runs/{run_id}/continue", follow_redirects=False)
    assert all(o.claim_ids == [] for o in outputs(repo, run_id))

    # c_002 was still rejected after the last round: it stays in the plan but can't be approved.
    bad = client.post(f"/runs/{run_id}/claims/c_002/review", data={"action": "approve"})
    assert bad.status_code == 400
    assert client.post("/runs/r_other/claims/c_001/review",
                       data={"action": "approve"}).status_code == 404

    resp = client.post(f"/runs/{run_id}/claims/c_001/review", data={"action": "approve"},
                       follow_redirects=False)
    assert resp.status_code == 303
    run = get_run(repo, run_id)
    report = repo.get_report(OWNER, run.plan_id or "")
    assert report is not None
    [good] = [v for v in report.results if v.claim_id == "c_001"]
    assert good.outcome is ClaimOutcome.user_review and good.approved_by_user
    outs = outputs(repo, run_id)
    assert len(outs) == 2 and all(o.claim_ids == ["c_001"] for o in outs)
    assert all(o.post_render is not None and o.post_render.passed for o in outs)
