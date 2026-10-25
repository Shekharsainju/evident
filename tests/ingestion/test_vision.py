from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from evident.contracts.facts import FactRef, FactVersion, VisionSource
from evident.ingestion.vision import ingest_photo, verify_bbox
from evident.models.adapter import ImagePart, TextPart
from evident.render.pdf import html_to_png
from evident.settings import Role
from evident.store.files import FileRepository
from tests.builders import document
from tests.fakes import FakeAdapter

SPAN = "Built a timetable clash checker"
HTML = f"""<!doctype html><html><body style="margin:0;background:#fff">
<p style="font:32px Arial;margin:40px 30px">{SPAN}</p>
<p style="font:32px Arial;margin:400px 30px 40px">Second line far below</p>
</body></html>"""


@pytest.fixture(scope="module")
def page_png(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    path = html_to_png(HTML, tmp_path_factory.mktemp("png") / "page.png", width=900)
    return path.read_bytes()


def size(png: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(png)) as img:
        return img.size


def test_verify_bbox_true_on_rendered_text_crop(page_png: bytes) -> None:
    assert verify_bbox(page_png, (20.0, 30.0, 700.0, 100.0), SPAN)


def test_verify_bbox_false_when_box_misses_the_span(page_png: bytes) -> None:
    w, h = size(page_png)
    assert not verify_bbox(page_png, (20.0, h - 120.0, 700.0, h - 20.0), SPAN)


def reply(box: list[int] | None, kind: str = "project") -> str:
    return json.dumps({
        "facts": [{
            "kind": kind, "text": SPAN, "span_text": SPAN, "box_2d": box,
            "attributes": {"ownership": "built", "deployment": None, "start": None,
                           "end": None, "title": None, "organisation": None,
                           "skills": [], "metrics": []},
        }],
        "unreadable_regions": [],
    })


def run(tmp_path: Path, png: bytes, box: list[int] | None) -> tuple[VisionSource, FakeAdapter]:
    w, h = size(png)
    doc = document(media_type="image/png", width_px=w, height_px=h)
    repo = FileRepository(tmp_path)
    adapter = FakeAdapter({Role.extraction_vision: [reply(box)]})
    [fact] = ingest_photo(doc, png, adapter, repo)
    assert repo.get_fact(doc.owner_id, fact_ref(fact)) == fact
    assert isinstance(fact.source, VisionSource)
    return fact.source, adapter


def fact_ref(fact: object) -> FactRef:


    assert isinstance(fact, FactVersion)
    return FactRef(fact_id=fact.fact_id, version=fact.version)


def to_box_2d(png: bytes, x0: float, y0: float, x1: float, y1: float) -> list[int]:
    w, h = size(png)
    return [int(y0 / h * 1000), int(x0 / w * 1000), int(y1 / h * 1000), int(x1 / w * 1000)]


def test_verified_box_kept_in_pixels(tmp_path: Path, page_png: bytes) -> None:
    source, _ = run(tmp_path, page_png, to_box_2d(page_png, 20, 30, 700, 100))
    assert source.bbox_verified
    assert source.bbox[0] == pytest.approx(20, abs=2)
    assert source.bbox[3] == pytest.approx(100, abs=2)
    assert source.confidence > 0.8


def test_unverified_box_falls_back_to_whole_image(tmp_path: Path, page_png: bytes) -> None:
    w, h = size(page_png)
    source, _ = run(tmp_path, page_png, to_box_2d(page_png, 20, h - 120, 700, h - 20))
    assert not source.bbox_verified
    assert source.bbox == (0.0, 0.0, float(w), float(h))


def test_missing_box_falls_back_to_whole_image(tmp_path: Path, page_png: bytes) -> None:
    w, h = size(page_png)
    source, _ = run(tmp_path, page_png, None)
    assert not source.bbox_verified and source.bbox == (0.0, 0.0, float(w), float(h))


def test_image_sent_as_image_part_with_document_tags(tmp_path: Path, page_png: bytes) -> None:
    _, adapter = run(tmp_path, page_png, None)
    [call] = adapter.calls
    assert call.role is Role.extraction_vision
    images = [p for p in call.parts if isinstance(p, ImagePart)]
    texts = [p.text for p in call.parts if isinstance(p, TextPart)]
    assert len(images) == 1 and images[0].data == page_png
    assert images[0].mime_type == "image/png"
    assert any("<document>" in t and "</document>" in t for t in texts)


def test_unknown_kind_skipped_without_storing(tmp_path: Path, page_png: bytes) -> None:
    w, h = size(page_png)
    doc = document(media_type="image/png", width_px=w, height_px=h)
    repo = FileRepository(tmp_path)
    adapter = FakeAdapter({Role.extraction_vision: [reply(None, kind="hobby")]})
    assert ingest_photo(doc, page_png, adapter, repo) == []
    assert repo.current_facts(doc.owner_id) == []
