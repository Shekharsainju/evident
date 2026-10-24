"""Base class for every contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Strict, immutable and versioned. Unknown fields fail instead of being dropped."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    schema_version: Literal["2.0"] = "2.0"
