"""Uploaded files."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from evident.contracts.common import Contract
from evident.contracts.enums import DocumentKind


class Document(Contract):
    document_id: str
    owner_id: str
    kind: DocumentKind
    media_type: Literal["application/pdf", "image/png", "image/jpeg"]
    filename: str
    sha256: str
    width_px: int | None
    height_px: int | None
    created_at: datetime
