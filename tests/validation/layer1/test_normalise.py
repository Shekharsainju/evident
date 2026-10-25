from __future__ import annotations

from evident.validation.layer1.normalise import contains_phrase, normalise_text


def test_normalise_unifies_en_dash_and_case() -> None:
    assert normalise_text("Built – FastAPI") == normalise_text("built - fastapi")


def test_normalise_keeps_number_punctuation_only() -> None:
    assert normalise_text("Cut latency by 40%, to 2.5s!") == "cut latency by 40% to 2.5s"


def test_normalise_removes_thousands_separators_and_quotes() -> None:
    assert normalise_text("“1,200 requests”") == "1200 requests"


def test_normalise_nfkc_and_whitespace() -> None:
    assert normalise_text("Ｐython   3 tests") == "python 3 tests"


def test_normalise_keeps_glued_plus_and_hash() -> None:
    assert normalise_text("C++ and C# with 40+ users") == "c++ and c# with 40+ users"


def test_contains_phrase_is_whole_word() -> None:
    assert contains_phrase("built rest apis in flask", "rest apis")
    assert not contains_phrase("built restful apis", "rest")
