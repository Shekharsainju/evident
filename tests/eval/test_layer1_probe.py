from __future__ import annotations

from evident.contracts.facts import FactRef
from evident.eval.grounding import Label, LabelledClaim, _claim
from evident.eval.layer1_probe import layer1_outcomes, outcome_key, probe_claims
from evident.eval.splits import P1_TEST_PROFILES, load_p1_dev_claims


def test_probe_claims_dev_only() -> None:
    claims = probe_claims(range(3))
    assert claims
    assert not {c.profile_id for c in claims} & set(P1_TEST_PROFILES)


def test_probe_claims_deterministic() -> None:
    assert probe_claims(range(3)) == probe_claims(range(3))


def test_probe_claims_include_dev_claims_deduplicated() -> None:
    claims = probe_claims(range(3))
    keys = [outcome_key(c) for c in claims]
    assert len(keys) == len(set(keys))
    assert set(keys) >= {outcome_key(c) for c in load_p1_dev_claims()}


def test_outcomes_shape() -> None:
    dev = load_p1_dev_claims()
    supported = next(c for c in dev if c.label == "supported")
    wrong = next(c for c in dev if c.category is not None and c.category.value == "wrong_number")
    out = layer1_outcomes([supported, wrong])
    assert out[outcome_key(supported)] == []
    assert "metrics" in out[outcome_key(wrong)]


def test_diff_script_refuses_extra_with_test_profile(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import sys

    import pytest

    from evident.eval.splits import P1_TEST_CLAIMS, LockedSplitError
    from tests.eval.test_splits import _load_script

    module = _load_script("layer1_diff")
    monkeypatch.setattr(sys, "argv", ["diff", "--base", "HEAD", "--extra", str(P1_TEST_CLAIMS)])
    with pytest.raises(LockedSplitError):
        module.main()


def _lc(text: str, label: Label, profile: str = "student_profile_01") -> LabelledClaim:
    claim = _claim("probe", text, [FactRef(fact_id="f1", version=1)], "experience")
    return LabelledClaim(claim=claim, label=label, category=None, profile_id=profile,
                         split="dev", template="t")


def test_dedupe_conflicting_labels_keeps_unsupported() -> None:
    from evident.eval.layer1_probe import dedupe_fail_closed

    sup, uns = _lc("same text", "supported"), _lc("same text", "unsupported")
    for order in ([sup, uns], [uns, sup]):
        out = dedupe_fail_closed(order)
        assert len(out) == 1
        assert out[0].label == "unsupported"


def test_dedupe_keeps_distinct_and_first_of_equal_labels() -> None:
    from evident.eval.layer1_probe import dedupe_fail_closed

    a, b = _lc("a", "supported"), _lc("b", "supported")
    assert dedupe_fail_closed([a, b, a]) == [a, b]


def test_classify_all_four_cells_and_unchanged() -> None:
    from evident.eval.layer1_probe import classify

    sup, uns = _lc("s", "supported"), _lc("u", "unsupported")
    for claim, old, new, letter in [
        (uns, ["metrics"], [], "K"),
        (sup, ["metrics"], [], "S"),
        (sup, [], ["metrics"], "F"),
        (uns, [], ["metrics"], "U"),
    ]:
        changed, counts = classify([claim], [old], {outcome_key(claim): new})
        assert counts == {k: int(k == letter) for k in "KSFU"}, letter
        assert len(changed) == 1
        assert changed[0]["old"] == old and changed[0]["new"] == new
    # Unchanged pass/fail state, even with different rules, is not a change.
    changed, counts = classify([uns, sup], [["a"], []], {outcome_key(uns): ["b"],
                                                          outcome_key(sup): []})
    assert changed == [] and counts == {"K": 0, "S": 0, "F": 0, "U": 0}


def test_main_returns_1_when_unsupported_newly_passes(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import sys

    from tests.eval.test_splits import _load_script

    module = _load_script("layer1_diff")
    weaker_base = lambda base, path, scratch: [["metrics"]] * len(  # noqa: E731
        module.load_claims(path))
    monkeypatch.setattr(module, "_score_base", weaker_base)
    # New side: every probe passes, so every claim the base failed newly passes.
    monkeypatch.setattr(module, "layer1_outcomes",
                        lambda claims: {outcome_key(c): [] for c in claims})
    monkeypatch.setattr(sys, "argv", ["diff", "--base", "X", "--out", str(tmp_path / "o.json")])
    assert module.main() == 1


def test_main_returns_0_when_nothing_changes(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import sys

    from tests.eval.test_splits import _load_script

    module = _load_script("layer1_diff")
    monkeypatch.setattr(module, "_score_base",
                        lambda base, path, scratch: [[]] * len(module.load_claims(path)))
    monkeypatch.setattr(module, "layer1_outcomes",
                        lambda claims: {outcome_key(c): [] for c in claims})
    monkeypatch.setattr(sys, "argv", ["diff", "--base", "X", "--out", str(tmp_path / "o.json")])
    assert module.main() == 0


def test_main_returns_2_on_tool_error(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    import subprocess
    import sys

    from tests.eval.test_splits import _load_script

    module = _load_script("layer1_diff")

    def boom(base, path, scratch):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(128, ["git"], stderr="fatal: bad ref")

    monkeypatch.setattr(module, "_score_base", boom)
    monkeypatch.setattr(sys, "argv", ["diff", "--base", "nope", "--out", str(tmp_path / "o.json")])
    assert module.main() == 2
    assert "fatal: bad ref" in capsys.readouterr().err


def test_base_import_check(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import pytest

    from tests.eval.test_splits import _load_script

    module = _load_script("layer1_diff")
    wt = tmp_path / "wt"
    inside = wt / "src" / "evident" / "__init__.py"
    inside.parent.mkdir(parents=True)
    inside.write_text("")
    module._check_base_import(f"noise\nIMPORTED {inside}\n", wt)  # accepted
    with pytest.raises(module.ToolError):
        module._check_base_import("no marker here\n", wt)
    with pytest.raises(module.ToolError):
        module._check_base_import(f"IMPORTED {tmp_path / 'main' / 'evident' / '__init__.py'}\n", wt)


def test_base_env_drops_pythonpath(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from tests.eval.test_splits import _load_script

    module = _load_script("layer1_diff")
    monkeypatch.setenv("PYTHONPATH", "C:/dev/evident/src")
    assert "PYTHONPATH" not in module._base_env()


def test_probe_claims_mutation_equal_to_instance_stays_unsupported(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    from evident.eval import layer1_probe
    from evident.eval.grounding import _instances
    from evident.eval.grounding import _mutations as real_mutations

    inst = _instances("student_profile_01")[0]

    def colliding(instances, rng):  # type: ignore[no-untyped-def]
        clash = SimpleNamespace(text=inst.text, refs=inst.refs, base=inst, category=None)
        return [clash, *real_mutations(instances, rng)]

    monkeypatch.setattr(layer1_probe, "_mutations", colliding)
    claims = probe_claims(range(1))
    hit = [c for c in claims if outcome_key(c) == outcome_key(
        next(x for x in claims if x.claim.text == inst.text))]
    assert len(hit) == 1 and hit[0].label == "unsupported"


def test_diff_script_always_loads_standing_probes(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import sys

    from evident.eval.grounding import dump_claims
    from tests.eval.test_splits import _load_script

    module = _load_script("layer1_diff")
    probe = _lc("Standing probe sentence for the gate.", "unsupported")
    (tmp_path / "p.jsonl").write_text(dump_claims([probe]), encoding="utf-8")
    monkeypatch.setattr(module, "PROBES_DIR", tmp_path)
    seen: list[str] = []

    def base(ref, path, scratch):  # type: ignore[no-untyped-def]
        claims = module.load_claims(path)
        seen.extend(c.claim.text for c in claims)
        return [[]] * len(claims)

    monkeypatch.setattr(module, "_score_base", base)
    monkeypatch.setattr(module, "layer1_outcomes",
                        lambda claims: {outcome_key(c): [] for c in claims})
    monkeypatch.setattr(sys, "argv", ["diff", "--base", "X", "--out", str(tmp_path / "o.json")])
    assert module.main() == 0
    assert "Standing probe sentence for the gate." in seen


def test_diff_script_refuses_a_standing_probe_from_a_test_profile(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import sys

    import pytest

    from evident.eval.grounding import dump_claims
    from evident.eval.splits import LockedSplitError
    from tests.eval.test_splits import _load_script

    module = _load_script("layer1_diff")
    bad = _lc("Locked profile probe.", "unsupported", profile=P1_TEST_PROFILES[0])
    (tmp_path / "p.jsonl").write_text(dump_claims([bad]), encoding="utf-8")
    monkeypatch.setattr(module, "PROBES_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["diff", "--base", "X", "--out", str(tmp_path / "o.json")])
    with pytest.raises(LockedSplitError):
        module.main()


def test_diff_script_writes_its_report_as_utf8(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import sys

    from evident.eval.grounding import dump_claims
    from tests.eval.test_splits import _load_script

    module = _load_script("layer1_diff")
    probe = _lc("• Our Team Course Planner project – a bullet probe.", "supported")
    (tmp_path / "p.jsonl").write_text(dump_claims([probe]), encoding="utf-8")
    monkeypatch.setattr(module, "PROBES_DIR", tmp_path)
    monkeypatch.setattr(module, "probe_claims", lambda: [])
    monkeypatch.setattr(module, "_score_base",
                        lambda ref, path, scratch: [["entities"]] * len(module.load_claims(path)))
    monkeypatch.setattr(module, "layer1_outcomes",
                        lambda claims: {outcome_key(c): [] for c in claims})
    report = tmp_path / "gate.txt"
    monkeypatch.setattr(sys, "argv", ["diff", "--base", "X", "--out", str(tmp_path / "o.json"),
                                      "--report", str(report)])
    assert module.main() == 0
    text = report.read_bytes().decode("utf-8")
    assert "• Our Team Course Planner project – a bullet probe." in text
    assert "newly passing supported: 1" in text


def test_plain_start_sentences_broken_by_task_6_round_2_pass() -> None:
    # Task 6 round 2 rejected these supported dev sentences (re-review 2). The revert must
    # pass them again, and any future sentence-start fix must keep them passing.
    from evident.eval.grounding import DEFAULT_AS_OF, layer1_context
    from evident.validation.layer1.run import run_layer1

    rows = [("student_profile_02", "student_profile_02_gt07",
             "The Classifier reached 84% accuracy on the held-out test set."),
            ("student_profile_01", "student_profile_01_gt08",
             "The Agent selected local course tools."),
            ("student_profile_05", "student_profile_05_gt08", "The Loop logged tool observations."),
            ("student_profile_03", "student_profile_03_gt07",
             "The Survey covered 1,200 survey responses."),
            ("student_profile_04", "student_profile_04_gt08", "The Container ran the service.")]
    for profile, fact_id, text in rows:
        c = _claim("r", text, [FactRef(fact_id=fact_id, version=1)], "projects")
        result = run_layer1(c, layer1_context(profile, DEFAULT_AS_OF))
        assert result.passed, (text, result.failures)
