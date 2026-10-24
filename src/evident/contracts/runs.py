"""Pipeline run status as shown to the user."""

from __future__ import annotations

from evident.contracts.common import Contract
from evident.contracts.enums import RunStage, RunState


class RunStatus(Contract):
    run_id: str
    owner_id: str
    stage: RunStage
    state: RunState
    message: str
    error: str | None
    document_id: str
    target_id: str | None
    plan_id: str | None
    output_ids: list[str]
