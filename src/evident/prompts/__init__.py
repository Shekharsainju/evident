"""Versioned prompt files and the shared preamble (design: Prompts)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).parent
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
# Untrusted content must not be able to close its own data block and continue as instructions.
DATA_TAG = re.compile(r"<(/?)\s*(document|job_ad|transcript|evidence)\s*>", re.IGNORECASE)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str


def load_prompt(name: str, version: str = "v1") -> Prompt:
    path = PROMPT_DIR / name / f"{version}.txt"
    return Prompt(name=name, version=version, text=path.read_text(encoding="utf-8"))


def _neutralise(value: str) -> str:
    return DATA_TAG.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}&gt;", value)


def render_prompt(prompt: Prompt, **fields: str) -> str:
    """Fill the prompt's placeholders and prepend the shared preamble."""
    wanted = set(PLACEHOLDER.findall(prompt.text))
    if wanted != set(fields):
        raise ValueError(
            f"prompt {prompt.name}/{prompt.version} needs fields {sorted(wanted)}, "
            f"got {sorted(fields)}"
        )
    body = PLACEHOLDER.sub(lambda m: _neutralise(fields[m.group(1)]), prompt.text)
    preamble = load_prompt("preamble").text.strip()
    return f"{preamble}\n\n{body}"
