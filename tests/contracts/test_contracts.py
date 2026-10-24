from pathlib import Path

import pytest
from pydantic import ValidationError

from evident.contracts import ALL_CONTRACTS
from evident.contracts.facts import FactAttributes, FactRef, FactVersion, MetricRecord, VisionSource

FIXTURES = Path(__file__).parent / "fixtures"

METRIC = {
    "metric_id": "m_01",
    "metric": "latency",
    "direction": "decrease",
    "value": 45.0,
    "unit": "percent",
    "baseline": None,
    "subject": "demo API",
    "span_text": "cut latency by 45%",
}

ATTRS = {
    "ownership": "built",
    "deployment": "prototype",
    "scale": None,
    "metrics": [],
    "start": "2026-05",
    "end": "2026-07",
    "skills": ["FastAPI"],
    "title": None,
    "organisation": None,
}


def test_design_fact_example_round_trips() -> None:
    fact = FactVersion.model_validate_json((FIXTURES / "fact_version.json").read_text())
    assert FactVersion.model_validate_json(fact.model_dump_json()) == fact


def test_strict_rejects_coercion() -> None:
    with pytest.raises(ValidationError):
        FactRef.model_validate({"fact_id": "exp_03", "version": "2"})


def test_unknown_field_rejected() -> None:
    with pytest.raises(ValidationError):
        FactRef.model_validate({"fact_id": "x", "version": 1, "extra": 1})


def test_metric_vocab_and_other_prefix() -> None:
    MetricRecord.model_validate({**METRIC, "metric": "other:clash_checks"})
    with pytest.raises(ValidationError):
        MetricRecord.model_validate({**METRIC, "metric": "vibes"})


def test_source_discriminates_on_extraction_path() -> None:
    f = FactVersion.model_validate_json((FIXTURES / "fact_vision.json").read_text())
    assert isinstance(f.source, VisionSource)


def test_every_contract_has_schema_version() -> None:
    for model in ALL_CONTRACTS:
        assert model.model_fields["schema_version"].default == "2.0"


@pytest.mark.parametrize("bad", ["2026-13", "26-05", "2026-5"])
def test_year_month_format(bad: str) -> None:
    with pytest.raises(ValidationError):
        FactAttributes.model_validate({**ATTRS, "start": bad})
