"""Job ad to requirements (design: Pipeline 4; spec 8.3).

The job ad is untrusted. It goes to the model inside <job_ad> tags, and the reply is read
through a loose draft schema: an item that doesn't fit is dropped rather than guessed.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from evident.contracts.coverage import Requirement
from evident.contracts.enums import RequirementCategory
from evident.errors import ErrorCategory, StageError
from evident.models.adapter import ImagePart, ModelAdapter, Part, TextPart
from evident.prompts import load_prompt, render_prompt
from evident.settings import Role

log = logging.getLogger("evident.coverage")

IMAGE_PLACEHOLDER = "The job ad is the attached image."
JPEG_MAGIC = b"\xff\xd8\xff"


class DraftRequirement(BaseModel):
    text: str
    category: str


class RequirementsDraft(BaseModel):
    requirements: list[DraftRequirement]


def _category(value: str) -> RequirementCategory | None:
    try:
        return RequirementCategory(value.strip().lower())
    except ValueError:
        return None


def extract_requirements(
    adapter: ModelAdapter, *, text: str | None = None, image: bytes | None = None
) -> list[Requirement]:
    if (text is None) == (image is None):
        raise ValueError("Give exactly one of text or image.")
    prompt = load_prompt("requirements")
    parts: list[Part]
    if image is not None:
        mime = "image/jpeg" if image.startswith(JPEG_MAGIC) else "image/png"
        parts = [ImagePart(data=image, mime_type=mime),
                 TextPart(render_prompt(prompt, content=IMAGE_PLACEHOLDER))]
    else:
        assert text is not None
        parts = [TextPart(render_prompt(prompt, content=text))]
    draft = adapter.generate_json(Role.requirements, prompt, parts, RequirementsDraft).value

    reqs: list[Requirement] = []
    for item in draft.requirements:
        category = _category(item.category)
        clean = " ".join(item.text.split())
        if category is None or not clean:
            log.info("requirement draft skipped: unknown category or empty text")
            continue
        reqs.append(Requirement(requirement_id=f"req_{len(reqs) + 1:02d}", text=clean,
                                category=category))
    if not reqs:
        raise StageError(code="no_requirements", category=ErrorCategory.validation,
                         detail="No usable requirements were found in the job ad.")
    log.info("requirements extracted count=%d", len(reqs))
    return reqs
