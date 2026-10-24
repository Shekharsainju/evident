"""Disk cache of validated model replies, keyed by everything that shapes the reply."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from evident.models.adapter import ImagePart, Part, TextPart
from evident.prompts import Prompt


def cache_key(model_id: str, prompt: Prompt, parts: list[Part], schema: type[BaseModel]) -> str:
    h = hashlib.sha256()
    schema_json = json.dumps(schema.model_json_schema(), sort_keys=True)
    for item in (model_id, prompt.name, prompt.version, schema.__name__, schema_json):
        h.update(item.encode("utf-8"))
        h.update(b"\x00")
    for part in parts:
        if isinstance(part, TextPart):
            h.update(b"text\x00" + part.text.encode("utf-8"))
        elif isinstance(part, ImagePart):
            h.update(b"image\x00" + part.mime_type.encode() + hashlib.sha256(part.data).digest())
        h.update(b"\x00")
    return h.hexdigest()


@dataclass(frozen=True)
class CachedReply:
    text: str
    input_tokens: int
    output_tokens: int

    def dumps(self) -> str:
        return json.dumps(
            {"text": self.text, "input_tokens": self.input_tokens,
             "output_tokens": self.output_tokens}
        )

    @classmethod
    def loads(cls, raw: str) -> CachedReply:
        data = json.loads(raw)
        return cls(str(data["text"]), int(data["input_tokens"]), int(data["output_tokens"]))


class DiskCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> str | None:
        path = self._path(key)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def put(self, key: str, value: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(value, encoding="utf-8")
        os.replace(tmp, path)
