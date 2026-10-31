"""The zip is the last guard against leaking a key, so these run real git in a temp repo.

Fake keys are assembled at runtime: this file ships in the zip and must not match a pattern.
"""

from __future__ import annotations

import bz2
import gzip
import logging
import shutil
import subprocess
import sys
import time
import zipfile
import zlib
from pathlib import Path

import pytest

from evident.render.profile_html import render_profile_pdf
from scripts.build_examples import EXPECTED_FILES
from scripts.build_zip import EXAMPLE_FILES, build_zip, collect_files, is_excluded, scan_zip

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = [f"examples/{n}" for n in EXAMPLE_FILES]
FAKE_GOOGLE_KEY = "AIza" + "B1c2D3e4F5" * 3 + "g6H7i"
FAKE_SK_KEY = "sk-" + "a1B2c3D4e5" * 3
ENV_SECRET = "plain-value-" + "matching-no-pattern"
ENV_KEY = "GEMINI_API" + "_KEY"
PRIVATE_HEADER = "-----BEGIN RSA " + "PRIVATE KEY-----"

SENSITIVE = [
    ".env",
    ".env.local",
    "CLAUDE.md",
    ".claude/settings.json",
    ".superpowers/state.json",
    "var/local-demo/run.json",
    ".cache/models/reply.json",
    "data/private/real_cv.pdf",
    ".venv/pyvenv.cfg",
    "src/__pycache__/a.pyc",
    ".pytest_cache/v",
    ".mypy_cache/v",
    ".ruff_cache/v",
    "nested/.ENV",
    ".env - Copy",
    "backup.env",
    ".envrc",
    "CLAUDE.local.md",
    ".mcp.json",
    "venv/pyvenv.cfg",
    "stray.pyc",
]


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def write(root: Path, rel: str, text: str = "ok\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    write(root, "README.md")
    write(root, ".env.example", f"{ENV_KEY}=\n")
    for name in EXAMPLE_FILES:
        write(root, f"examples/{name}")
    git(root, "add", "README.md", ".env.example")
    monkeypatch.chdir(root)
    return root


def names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        return zf.namelist()


def plain_zip(tmp_path: Path, members: dict[str, bytes],
              compression: int = zipfile.ZIP_STORED) -> Path:
    path = tmp_path / "plain.zip"
    with zipfile.ZipFile(path, "w", compression) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_zip_excludes_sensitive_paths(repo: Path) -> None:
    for rel in SENSITIVE:
        write(repo, rel, "harmless\n")
    # Force-added, so tracked: the explicit rules must hold even if .gitignore is bypassed.
    git(repo, "add", "-f", *SENSITIVE)

    built = build_zip("TEST")

    assert built == repo / "dist" / "A3_Code_TEST.zip"
    assert sorted(names(built)) == sorted([".env.example", "README.md", *EXAMPLES])


@pytest.mark.parametrize("rel", [*SENSITIVE, ".env.local/secret.txt", "examples/.env"])
def test_is_excluded_for_each_sensitive_path(rel: str) -> None:
    assert is_excluded(rel)


@pytest.mark.parametrize("rel", [".env.example", "README.md", "docs/environment.md",
                                 "src/evident/variables.py", "data/synthetic/jobs.jsonl",
                                 "tests/test_env.py", "src/dotenv.py"])
def test_is_excluded_keeps_ordinary_files(rel: str) -> None:
    assert not is_excluded(rel)


def test_untracked_files_outside_examples_are_not_picked_up(repo: Path) -> None:
    write(repo, "notes.txt")
    assert "notes.txt" not in names(build_zip("TEST"))


@pytest.mark.parametrize(("content", "pattern"), [
    (f"key = '{FAKE_GOOGLE_KEY}'\n", "google_api_key"),
    (f"token = {FAKE_SK_KEY}\n", "sk_key"),
    (f"{PRIVATE_HEADER}\n", "private_key_header"),
    (f"{ENV_KEY}=abc123\n", "api_key_assignment"),
    (f'$env:{ENV_KEY} = "abc123"\n', "api_key_assignment"),
])
def test_planted_fake_key_detected_and_zip_deleted(
    repo: Path, content: str, pattern: str, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "src/leak.py", content)
    git(repo, "add", "src/leak.py")

    with pytest.raises(SystemExit) as stopped:
        build_zip("TEST")

    assert stopped.value.code == 1
    assert not (repo / "dist" / "A3_Code_TEST.zip").exists()
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "src/leak.py" in output and pattern in output
    assert "abc123" not in output and FAKE_GOOGLE_KEY not in output and FAKE_SK_KEY not in output


def test_a_stale_zip_does_not_survive_a_failed_build(repo: Path) -> None:
    assert build_zip("TEST").exists()
    write(repo, "src/leak.py", FAKE_GOOGLE_KEY)
    git(repo, "add", "src/leak.py")
    with pytest.raises(SystemExit):
        build_zip("TEST")
    assert not (repo / "dist" / "A3_Code_TEST.zip").exists()


def test_env_value_detected_without_printing(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, ".env", f"{ENV_KEY}={ENV_SECRET}\n")
    write(repo, "docs/note.md", f"pasted by mistake: {ENV_SECRET}\n")
    git(repo, "add", "docs/note.md")

    with pytest.raises(SystemExit):
        build_zip("TEST")

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "docs/note.md" in output and "env_value" in output
    assert ENV_SECRET not in output
    assert not (repo / "dist" / "A3_Code_TEST.zip").exists()


def test_scan_returns_only_file_and_pattern_name(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(f"{ENV_KEY}={ENV_SECRET}\n", encoding="utf-8")
    path = plain_zip(tmp_path, {"a.txt": ENV_SECRET.encode()})
    assert scan_zip(path, env) == [("a.txt", "env_value")]


@pytest.mark.parametrize("text", [
    f'{ENV_KEY}="{ENV_SECRET}"\n',
    f"export {ENV_KEY}='{ENV_SECRET}'\n",
    f"{ENV_KEY}={ENV_SECRET} # my key\n",
])
def test_env_values_are_read_through_quotes_and_comments(tmp_path: Path, text: str) -> None:
    env = tmp_path / ".env"
    env.write_text(text, encoding="utf-8")
    assert scan_zip(plain_zip(tmp_path, {"a.txt": ENV_SECRET.encode()}), env) == [
        ("a.txt", "env_value")]


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
def test_env_file_written_by_powershell_is_still_read(tmp_path: Path, encoding: str) -> None:
    env = tmp_path / ".env"
    env.write_text(f"{ENV_KEY}={ENV_SECRET}\n", encoding=encoding)
    assert scan_zip(plain_zip(tmp_path, {"a.txt": ENV_SECRET.encode()}), env) == [
        ("a.txt", "env_value")]


def test_utf16_file_does_not_hide_a_key(tmp_path: Path) -> None:
    path = plain_zip(tmp_path, {"a.txt": FAKE_GOOGLE_KEY.encode("utf-16")})
    assert scan_zip(path, tmp_path / "absent") == [("a.txt", "google_api_key")]


def test_key_inside_nested_office_file_is_found(tmp_path: Path) -> None:
    inner = plain_zip(tmp_path, {"ppt/slides/slide1.xml": FAKE_GOOGLE_KEY.encode()},
                      zipfile.ZIP_DEFLATED).read_bytes()
    path = plain_zip(tmp_path, {"examples/deck.pptx": inner})
    assert scan_zip(path, tmp_path / "absent") == [
        ("examples/deck.pptx!ppt/slides/slide1.xml", "google_api_key")]


def test_key_inside_compressed_pdf_stream_is_found(tmp_path: Path) -> None:
    pdf = (b"%PDF-1.7\n1 0 obj\n<<>>\nstream\n" + zlib.compress(FAKE_GOOGLE_KEY.encode())
           + b"\nendstream\nendobj\n")
    path = plain_zip(tmp_path, {"examples/profile.pdf": pdf})
    assert ("examples/profile.pdf", "google_api_key") in scan_zip(path, tmp_path / "absent")


def test_key_in_a_member_name_is_found(tmp_path: Path) -> None:
    path = plain_zip(tmp_path, {f"{FAKE_GOOGLE_KEY}.txt": b"ok"})
    assert scan_zip(path, tmp_path / "absent") == [("<file name withheld>", "google_api_key")]


def test_unreadable_nested_archive_fails_closed(tmp_path: Path) -> None:
    path = plain_zip(tmp_path, {"a.pptx": b"PK\x03\x04 not really a zip"})
    assert scan_zip(path, tmp_path / "absent") == [("a.pptx", "unreadable_archive")]


def test_short_and_config_env_values_are_not_treated_as_keys(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(f"{ENV_KEY}=x\nEVIDENT_DEMO=1\nOLLAMA_URL=http://127.0.0.1:11434\n",
                   encoding="utf-8")
    path = plain_zip(tmp_path, {"a.txt": b"x 1 http://127.0.0.1:11434"})
    assert scan_zip(path, env) == []


def test_clean_zip_passes(repo: Path) -> None:
    write(repo, ".env", f"{ENV_KEY}={ENV_SECRET}\n")
    built = build_zip("TEST")
    assert built.exists()
    assert scan_zip(built, repo / ".env") == []


def test_empty_key_lines_and_pattern_descriptions_are_clean(tmp_path: Path) -> None:
    text = (f"{ENV_KEY}=\n`*_API_KEY=` with a non-empty value\n".encode()
            + rb"AIza[0-9A-Za-z_-]{35}")
    assert scan_zip(plain_zip(tmp_path, {"a.md": text}), tmp_path / "absent") == []


@pytest.mark.parametrize("group_id", ["../evil", "a/b", "a\\b", ""])
def test_group_id_cannot_escape_the_output_folder(repo: Path, group_id: str) -> None:
    with pytest.raises(SystemExit):
        build_zip(group_id)


def test_runs_from_a_subfolder_still_scans_the_root_env(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repo, ".env", f"{ENV_KEY}={ENV_SECRET}\n")
    write(repo, "docs/note.md", ENV_SECRET)
    git(repo, "add", "docs/note.md")
    monkeypatch.chdir(repo / "docs")
    with pytest.raises(SystemExit) as stopped:
        build_zip("TEST")
    assert stopped.value.code == 1


def test_key_in_a_file_name_is_not_printed(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, f"{FAKE_GOOGLE_KEY}.txt")
    git(repo, "add", f"{FAKE_GOOGLE_KEY}.txt")
    with pytest.raises(SystemExit):
        build_zip("TEST")
    captured = capsys.readouterr()
    assert "google_api_key" in captured.err
    assert FAKE_GOOGLE_KEY not in captured.out + captured.err


def test_key_visible_in_a_chromium_pdf_is_found(tmp_path: Path) -> None:
    pdf = render_profile_pdf(f"<html><body><p>{FAKE_GOOGLE_KEY}</p></body></html>",
                             tmp_path / "profile.pdf")
    path = plain_zip(tmp_path, {"examples/profile.pdf": pdf.read_bytes()})
    assert scan_zip(path, tmp_path / "absent") == [("examples/profile.pdf", "google_api_key")]


def test_unreadable_pdf_fails_closed(tmp_path: Path) -> None:
    path = plain_zip(tmp_path, {"a.pdf": b"%PDF-1.7 truncated"})
    assert scan_zip(path, tmp_path / "absent") == [("a.pdf", "unreadable_pdf")]


@pytest.mark.parametrize("data", [gzip.compress(b"hidden"), bz2.compress(b"hidden")])
def test_compressed_files_we_do_not_open_fail_closed(tmp_path: Path, data: bytes) -> None:
    path = plain_zip(tmp_path, {"a.bin": data})
    assert scan_zip(path, tmp_path / "absent") == [("a.bin", "unreadable_archive")]


def test_key_split_across_office_text_runs_is_found(tmp_path: Path) -> None:
    runs = f"<a:t>{FAKE_GOOGLE_KEY[:9]}</a:t><a:t>{FAKE_GOOGLE_KEY[9:]}</a:t>".encode()
    path = plain_zip(tmp_path, {"ppt/slides/slide1.xml": runs})
    assert scan_zip(path, tmp_path / "absent") == [("ppt/slides/slide1.xml", "google_api_key")]


def test_pgp_private_key_header_is_found(tmp_path: Path) -> None:
    header = "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----"
    path = plain_zip(tmp_path, {"a.txt": header.encode()})
    assert scan_zip(path, tmp_path / "absent") == [("a.txt", "private_key_header")]


def test_json_style_key_assignment_is_found(tmp_path: Path) -> None:
    path = plain_zip(tmp_path, {"a.json": f'{{"{ENV_KEY}": "abc123"}}'.encode()})
    assert scan_zip(path, tmp_path / "absent") == [("a.json", "api_key_assignment")]


@pytest.mark.parametrize("text", [f"{ENV_KEY}={ENV_SECRET}\t# old\n",
                                  f"# {ENV_KEY}={ENV_SECRET}\n"])
def test_tab_comments_and_commented_out_keys_are_read(tmp_path: Path, text: str) -> None:
    env = tmp_path / ".env"
    env.write_text(text, encoding="utf-8")
    assert scan_zip(plain_zip(tmp_path, {"a.txt": ENV_SECRET.encode()}), env) == [
        ("a.txt", "env_value")]


def test_long_runs_do_not_stall_the_scan(tmp_path: Path) -> None:
    started = time.monotonic()
    scan_zip(plain_zip(tmp_path, {"a.html": b"A" * 500_000}), tmp_path / "absent")
    assert time.monotonic() - started < 5


def test_missing_env_is_reported(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build_zip("TEST")
    assert "No .env found" in capsys.readouterr().err


def test_worktree_scan_uses_the_main_checkout_env(repo: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    write(repo, ".env", f"{ENV_KEY}={ENV_SECRET}\n")
    write(repo, "docs/note.md", ENV_SECRET)
    git(repo, "add", "docs/note.md")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x")
    tree = repo.parent / "tree"
    git(repo, "worktree", "add", "-q", str(tree))
    monkeypatch.chdir(tree)
    with pytest.raises(SystemExit) as stopped:
        build_zip("TEST", allow_incomplete_examples=True)
    assert stopped.value.code == 1


def test_only_named_example_files_enter_the_zip(repo: Path) -> None:
    write(repo, "examples/.env - Copy", "harmless")
    write(repo, "examples/notes.zip", "harmless")
    write(repo, "examples/sub/profile.html", "harmless")
    built = names(build_zip("TEST"))
    assert sorted(n for n in built if n.startswith("examples/")) == sorted(EXAMPLES)


def test_example_list_matches_what_build_examples_writes() -> None:
    assert sorted(EXAMPLE_FILES) == sorted(EXPECTED_FILES)


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_examples_junction_is_refused(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "profile.html").write_text("outside", encoding="utf-8")
    shutil.rmtree(repo / "examples")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(repo / "examples"), str(outside)],
                   check=True, capture_output=True)
    with pytest.raises(SystemExit, match="link"):
        build_zip("TEST")


def test_failed_delete_still_reports_the_hit(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repo, "src/leak.py", FAKE_GOOGLE_KEY)
    git(repo, "add", "src/leak.py")
    real_unlink = Path.unlink

    def locked(self: Path, missing_ok: bool = False) -> None:
        if self.name.endswith(".partial"):
            raise PermissionError("in use")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(SystemExit):
        build_zip("TEST")
    err = capsys.readouterr().err
    assert "src/leak.py: google_api_key" in err and "COULD NOT DELETE" in err
    assert not (repo / "dist" / "A3_Code_TEST.zip").exists()


def test_stale_zip_from_another_group_is_removed(repo: Path) -> None:
    old = build_zip("OLD")
    write(repo, "src/leak.py", FAKE_GOOGLE_KEY)
    git(repo, "add", "src/leak.py")
    with pytest.raises(SystemExit):
        build_zip("NEW")
    assert not old.exists()
    assert list((repo / "dist").iterdir()) == []


def test_newline_in_group_id_is_refused(repo: Path) -> None:
    with pytest.raises(SystemExit, match="group ID"):
        build_zip("TEST\n")


def test_missing_env_template_stops_the_build(repo: Path) -> None:
    git(repo, "rm", "-q", "--cached", ".env.example")
    with pytest.raises(SystemExit, match="would lack"):
        build_zip("TEST")


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs the git checkout")
def test_the_real_tree_scans_clean(tmp_path: Path) -> None:
    files = collect_files(ROOT)
    assert ".env.example" in files and "src/evident/runs.py" in files
    path = tmp_path / "real.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            zf.write(ROOT / rel, rel)
    assert scan_zip(path, tmp_path / "absent") == []


def test_incomplete_examples_stop_the_build_unless_allowed(repo: Path) -> None:
    (repo / "examples" / "coverage.md").unlink()
    with pytest.raises(SystemExit, match=r"examples/coverage\.md"):
        build_zip("TEST")
    assert list((repo / "dist").iterdir()) == []
    assert build_zip("TEST", allow_incomplete_examples=True).exists()


def test_two_env_files_do_not_unmask_a_withheld_name(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repo, ".env", f"{ENV_KEY}={ENV_SECRET}\n")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x")
    tree = repo.parent / "tree"
    git(repo, "worktree", "add", "-q", str(tree))
    for name in EXAMPLE_FILES:
        write(tree, f"examples/{name}")
    write(tree, ".env", f"{ENV_KEY}=another-unrelated-value\n")
    leaky = f"src/note-{ENV_SECRET}.txt"
    write(tree, leaky, FAKE_GOOGLE_KEY)
    git(tree, "add", leaky)
    monkeypatch.chdir(tree)
    with pytest.raises(SystemExit):
        build_zip("TEST")
    captured = capsys.readouterr()
    assert "google_api_key" in captured.err
    assert ENV_SECRET not in captured.out + captured.err


def test_pdf_parser_logs_cannot_print_scanned_text(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    logging.lastResort = logging.StreamHandler()
    stream = zlib.compress(f"({FAKE_GOOGLE_KEY}) g\n".encode())
    pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
           b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
           b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 9 9]/Contents 4 0 R>>endobj\n"
           b"4 0 obj<</Filter/FlateDecode/Length " + str(len(stream)).encode() + b">>\nstream\n"
           + stream + b"\nendstream\nendobj\ntrailer<</Root 1 0 R>>\n")
    hits = scan_zip(plain_zip(tmp_path, {"doc.pdf": pdf}), tmp_path / "absent")
    assert ("doc.pdf", "google_api_key") in hits
    captured = capfd.readouterr()
    assert FAKE_GOOGLE_KEY not in captured.out + captured.err
    assert not logging.root.manager.disable


def test_deleted_tracked_file_does_not_print_its_name(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    name = f"{FAKE_GOOGLE_KEY}.txt"
    write(repo, name)
    git(repo, "add", name)
    (repo / name).unlink()
    with pytest.raises(SystemExit) as stopped:
        build_zip("TEST")
    assert FAKE_GOOGLE_KEY not in str(stopped.value.code)
    captured = capsys.readouterr()
    assert FAKE_GOOGLE_KEY not in captured.out + captured.err
    assert list((repo / "dist").iterdir()) == []


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_tracked_folder_replaced_by_a_junction_is_left_out(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "docs/a.txt")
    git(repo, "add", "docs/a.txt")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_text("OUTSIDE", encoding="utf-8")
    shutil.rmtree(repo / "docs")
    subprocess.run(["cmd", "/c", "mklink", "/J", str(repo / "docs"), str(outside)],
                   check=True, capture_output=True)
    assert "docs/a.txt" not in names(build_zip("TEST"))
    assert "Skipped 1 linked" in capsys.readouterr().err


def test_partial_is_removed_when_reporting_fails(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(repo, "src/leak.py", FAKE_GOOGLE_KEY)
    git(repo, "add", "src/leak.py")

    def broken(*args: object, **_kwargs: object) -> None:
        if "google_api_key" in str(args[0]):
            raise OSError("stderr closed")

    monkeypatch.setattr("builtins.print", broken)
    with pytest.raises(SystemExit):
        build_zip("TEST")
    assert list((repo / "dist").iterdir()) == []


def test_leftover_partial_is_swept(repo: Path) -> None:
    (repo / "dist").mkdir()
    (repo / "dist" / "A3_Code_OLD.zip.partial").write_text("x", encoding="utf-8")
    build_zip("TEST")
    assert [p.name for p in (repo / "dist").iterdir()] == ["A3_Code_TEST.zip"]


@pytest.mark.parametrize(("raw", "value"), [
    ('"ab\\"cdefghijklmnop"', 'ab"cdefghijklmnop'),
    ('"C:\\\\vault\\\\secret-path"', "C:\\vault\\secret-path"),
    ("'abc\\def-ghijklmnop'", "abc\\def-ghijklmnop"),
])
def test_quoted_env_values_with_backslashes_are_read(
    tmp_path: Path, raw: str, value: str
) -> None:
    env = tmp_path / ".env"
    env.write_text(f"{ENV_KEY}={raw}\n", encoding="utf-8")
    path = plain_zip(tmp_path, {"a.txt": value.encode()})
    assert scan_zip(path, env) == [("a.txt", "env_value")]


def test_folder_named_like_the_template_is_excluded() -> None:
    assert is_excluded(".env.example/secret.txt")
