from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from evident.contracts.enums import FactStatus
from evident.contracts.facts import FactRef
from evident.errors import ErrorCategory, StageError
from evident.review.actions import (
    FactEdit,
    confirm,
    confirm_low_impact,
    edit,
    is_high_impact,
    reject,
)
from evident.store.files import FileRepository
from tests.builders import NOW, OWNER, attrs, fact, metric, pdf_source, vision_source


@pytest.fixture
def repo(tmp_path: Path) -> FileRepository:
    return FileRepository(tmp_path)


def ref(fact_id: str = "doc_01_f01", version: int = 1) -> FactRef:
    return FactRef(fact_id=fact_id, version=version)


LOW = fact(kind="skill", text="Python", attributes=attrs(skills=["Python"]))


@pytest.mark.parametrize(
    "f,high",
    [
        (LOW, False),
        (fact(attributes=attrs(ownership="contributed", deployment="concept")), False),
        (fact(attributes=attrs(start="2025-03")), True),
        (fact(attributes=attrs(metrics=[metric()])), True),
        (fact(kind="education", attributes=attrs()), True),
        (fact(kind="certification", attributes=attrs()), True),
        (fact(attributes=attrs(ownership="built")), True),
        (fact(attributes=attrs(deployment="prototype")), True),
        (fact(kind="skill", attributes=attrs(), source=pdf_source(span_found=False)), True),
        (fact(kind="skill", attributes=attrs(), source=vision_source(bbox_verified=False)), True),
    ],
)
def test_is_high_impact(f: object, high: bool) -> None:
    from evident.contracts.facts import FactVersion

    assert isinstance(f, FactVersion)
    assert is_high_impact(f) is high


def test_confirm_low_impact_skips_high_impact(repo: FileRepository) -> None:
    repo.put_fact(LOW)
    repo.put_fact(fact("doc_01_f02", attributes=attrs(start="2025-03")))
    repo.put_fact(fact("doc_02_f01", kind="skill", attributes=attrs(),
                       source=pdf_source("doc_02")))
    assert confirm_low_impact(repo, OWNER, "doc_01", NOW) == 1
    assert repo.get_fact(OWNER, ref()).status is FactStatus.confirmed  # type: ignore[union-attr]
    assert repo.get_fact(OWNER, ref("doc_01_f02")).status is FactStatus.extracted  # type: ignore[union-attr]
    assert repo.get_fact(OWNER, ref("doc_02_f01")).status is FactStatus.extracted  # type: ignore[union-attr]


def test_confirm_sets_confirmed(repo: FileRepository) -> None:
    repo.put_fact(fact(attributes=attrs(start="2025-03")))
    confirmed = confirm(repo, OWNER, ref(), NOW)
    assert confirmed.status is FactStatus.confirmed and confirmed.confirmed_at == NOW


def test_cannot_confirm_unmatched_span_until_edited(repo: FileRepository) -> None:
    repo.put_fact(fact(source=pdf_source(span_found=False, bbox=(0.0, 0.0, 0.0, 0.0))))
    with pytest.raises(StageError) as e:
        confirm(repo, OWNER, ref(), NOW)
    assert e.value.code == "span_not_found" and e.value.category is ErrorCategory.validation
    new = edit(repo, OWNER, ref(), FactEdit(text="Built a clash checker"), NOW)
    assert confirm(repo, OWNER, FactRef(fact_id=new.fact_id, version=new.version),
                   NOW).status is FactStatus.confirmed


def test_edit_creates_new_version_and_supersedes_old(repo: FileRepository) -> None:
    repo.put_fact(fact(status="confirmed", confirmed_at=NOW))
    new = edit(repo, OWNER, ref(), FactEdit(text="Built a Flask app", ownership="contributed",
                                            start="2025-02", skills=["Flask"]), NOW)
    assert (new.version, new.supersedes, new.edited_by_user) == (2, 1, True)
    assert new.status is FactStatus.extracted and new.confirmed_at is None
    assert new.text == "Built a Flask app" and new.attributes.skills == ["Flask"]
    assert new.attributes.ownership is not None and new.attributes.ownership.value == "contributed"
    old = repo.get_fact(OWNER, ref())
    assert old is not None and old.status is FactStatus.superseded and old.text != new.text
    assert [(f.fact_id, f.version) for f in repo.current_facts(OWNER)] == [("doc_01_f01", 2)]


def test_edit_with_invalid_value_is_rejected_without_change(repo: FileRepository) -> None:
    repo.put_fact(fact())
    with pytest.raises(StageError) as e:
        edit(repo, OWNER, ref(), FactEdit(start="March 2025"), NOW)
    assert e.value.category is ErrorCategory.validation
    assert repo.get_fact(OWNER, ref(version=2)) is None
    assert repo.get_fact(OWNER, ref()).status is FactStatus.extracted  # type: ignore[union-attr]


def test_reject(repo: FileRepository) -> None:
    repo.put_fact(fact())
    assert reject(repo, OWNER, ref()).status is FactStatus.rejected


def test_actions_on_other_owner_fact_fail(repo: FileRepository) -> None:
    repo.put_fact(fact())
    actions: list[Callable[[], object]] = [
        lambda: confirm(repo, "someone-else", ref(), NOW),
        lambda: reject(repo, "someone-else", ref()),
        lambda: edit(repo, "someone-else", ref(), FactEdit(text="x"), NOW),
    ]
    for action in actions:
        with pytest.raises(StageError):
            action()
