from __future__ import annotations

import pytest

from evident.contracts.enums import FactKind, FactStatus, MetricDirection, Ownership
from evident.ingestion.drafts import (
    DraftAttributes,
    DraftMetric,
    ExtractedFactDraft,
    box_2d_to_pixels,
    draft_to_fact,
)
from tests.builders import document, vision_source


def draft(**overrides: object) -> ExtractedFactDraft:
    base: dict[str, object] = {
        "kind": "project",
        "text": "Built a timetable clash checker",
        "span_text": "Built a timetable clash checker (Python, Flask)",
        "box_2d": None,
        "attributes": DraftAttributes(ownership="built", deployment="prototype",
                                      start="2025-03", end="2025-06", skills=["Python"]),
    }
    base.update(overrides)
    return ExtractedFactDraft.model_validate(base)


def test_box_2d_order_and_scale() -> None:  # Review Focus 3
    assert box_2d_to_pixels([100, 200, 300, 400], width=1000, height=2000) == (
        200.0, 200.0, 400.0, 600.0
    )


def test_box_2d_clamped_to_image() -> None:
    assert box_2d_to_pixels([-50, -10, 1200, 1100], width=500, height=800) == (
        0.0, 0.0, 500.0, 800.0
    )


@pytest.mark.parametrize("bad", [[1, 2, 3], [300, 100, 200, 400], [100, 400, 300, 400]])
def test_box_2d_malformed_or_empty_raises(bad: list[int]) -> None:
    with pytest.raises(ValueError):
        box_2d_to_pixels(bad, width=100, height=100)


def test_draft_becomes_extracted_fact_version() -> None:
    fact = draft_to_fact(draft(), 3, document(), vision_source())
    assert fact is not None
    assert fact.fact_id == "doc_01_f03" and fact.version == 1
    assert fact.status is FactStatus.extracted and fact.kind is FactKind.project
    assert fact.attributes.ownership is Ownership.built
    assert (fact.attributes.start, fact.attributes.end) == ("2025-03", "2025-06")
    assert fact.confirmed_at is None and not fact.edited_by_user


def test_invalid_enum_in_draft_becomes_none_not_crash() -> None:
    d = draft(attributes=DraftAttributes(ownership="architected", deployment="global",
                                         start="March 2025", end="2025-13"))
    fact = draft_to_fact(d, 1, document(), vision_source())
    assert fact is not None
    a = fact.attributes
    assert (a.ownership, a.deployment, a.start, a.end) == (None, None, None, None)


def test_unknown_metric_becomes_other_prefix() -> None:
    m = DraftMetric(metric="Clash Checks!", direction="decrease", value=2, unit="seconds",
                    subject="clash check", span_text="under 2 seconds")
    fact = draft_to_fact(draft(attributes=DraftAttributes(metrics=[m])), 1, document(),
                         vision_source())
    assert fact is not None
    [record] = fact.attributes.metrics
    assert record.metric == "other:clash_checks"
    assert record.direction is MetricDirection.decrease and record.value == 2.0


def test_known_metric_kept_and_bad_direction_dropped() -> None:
    good = DraftMetric(metric="Latency", direction="decrease", value=40, unit="percent",
                       subject="api", span_text="cut latency by 40%")
    bad = DraftMetric(metric="accuracy", direction="sideways", value=3, unit="percent",
                      subject="x", span_text="3%")
    fact = draft_to_fact(draft(attributes=DraftAttributes(metrics=[good, bad])), 1, document(),
                         vision_source())
    assert fact is not None
    assert [m.metric for m in fact.attributes.metrics] == ["latency"]


def test_unknown_kind_is_skipped() -> None:
    assert draft_to_fact(draft(kind="hobby"), 1, document(), vision_source()) is None


def test_empty_span_is_skipped() -> None:
    assert draft_to_fact(draft(span_text="  "), 1, document(), vision_source()) is None
