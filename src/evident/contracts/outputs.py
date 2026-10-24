"""Rendered outputs and their lineage."""

from __future__ import annotations

from evident.contracts.common import Contract
from evident.contracts.enums import OutputType
from evident.contracts.facts import FactRef


class PostRenderResult(Contract):
    passed: bool
    problems: list[str]


class Output(Contract):
    output_id: str
    owner_id: str
    plan_id: str
    output_type: OutputType
    claim_ids: list[str]
    fact_refs: list[FactRef]
    files: dict[str, str]
    post_render: PostRenderResult | None
