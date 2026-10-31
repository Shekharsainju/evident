"""Task 22 submission zip: `git ls-files` plus the generated examples, minus spec 12a exclusions.

The scan is the last guard against leaking a key. It reports the file and pattern name only:
matched text and .env values are compared in memory and never printed, logged or returned, and
a file name that itself matches is withheld. Any hit, or any failure while scanning, removes
the zip and exits 1. The zip gets its final name only after a clean scan.

Not covered: a key that exists only as pixels in an image, or one that was base64 encoded.

Usage:
  uv run python scripts/build_zip.py --group-id <GroupID>
"""

from __future__ import annotations

import argparse
import io
import logging
import lzma
import os
import re
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath

import pdfplumber

# Spec 12a, plus the other private tool folders in .gitignore. Matched on any path segment,
# ignoring case, because Windows treats ".ENV" and ".env" as the same file.
EXCLUDED_SEGMENTS = {
    ".git", ".claude", ".superpowers", "var", ".cache", "dist", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".venv", "venv", "node_modules", ".agents", ".aider-desk",
    "skills-lock.json", ".mcp.json",
}
ENV_TEMPLATE = ".env.example"
ENV_LIKE = re.compile(r"^\.env|\.env([^a-z0-9]|$)")
CLAUDE_NOTES = re.compile(r"^claude.*\.md$")
REQUIRED = ["README.md", ENV_TEMPLATE]
# Exactly what build_examples writes. Nothing else under examples/ can enter the zip, so a
# stray copy, archive or junction there is ignored rather than trusted to the scan.
EXAMPLE_FILES = [
    "input_cv_photo.jpg", "job_ad_screenshot.png", "facts.json", "coverage.json", "coverage.md",
    "profile.pdf", "profile.html", "deck.pptx", "validation_report.json",
    "inflated_claim_rejected.md", "RESULTS.md", "README.md",
]

PATTERNS = {
    "google_api_key": re.compile(rb"AIza[0-9A-Za-z_-]{35}"),
    "sk_key": re.compile(rb"(?<![0-9A-Za-z])sk-[0-9A-Za-z_-]{20,}"),
    "private_key_header": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"),
    # No leading [A-Z0-9_]*: the prefix adds nothing and made this quadratic on long runs.
    "api_key_assignment": re.compile(rb"API_KEY[\"']?[ \t]*[:=][ \t]*[\"']?[^\s\"'`]"),
}
# .env settings that aren't secrets and legitimately appear in the code and README.
NON_SECRET_ENV = {"OLLAMA_URL", "EVIDENT_DEMO", "DEMO", "DATA_DIR", "CACHE_DIR", "QUOTA_DIR",
                  "AS_OF"}
# Shorter values match by chance ("x", "1"), and no real key is this short.
MIN_SECRET_LENGTH = 8
MAX_NESTING = 3
GROUP_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# A commented-out line is read too: it is often the previous key.
ENV_LINE = re.compile(r"^\s*(?:#+\s*)?(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
QUOTED = re.compile(r"""^(["'])((?:\\.|(?!\1).)*)\1""")
PDF_STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.DOTALL)
XML_TAG = re.compile(rb"<[^>]+>")
UNPACKED_ARCHIVES = (b"\x1f\x8b", b"BZh", b"\xfd7zXZ", b"7z\xbc\xaf\x27\x1c", b"Rar!")
ARCHIVE_ERRORS = (zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error, EOFError,
                  OSError, ValueError, lzma.LZMAError)
WITHHELD = "<file name withheld>"


def is_excluded(rel: str) -> bool:
    # Windows ignores trailing dots and spaces, so ".env." opens the same file as ".env".
    parts = [p.lower().rstrip(". ") or p for p in PurePosixPath(rel.replace("\\", "/")).parts]
    if EXCLUDED_SEGMENTS.intersection(parts):
        return True
    if any(pair == ("data", "private") for pair in zip(parts, parts[1:], strict=False)):
        return True
    if any(ENV_LIKE.search(p) for p in parts[:-1]):
        return True
    if ENV_LIKE.search(parts[-1]) and parts[-1] != ENV_TEMPLATE:
        return True
    return bool(CLAUDE_NOTES.match(parts[-1])) or parts[-1].endswith(".pyc")


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True,
                          encoding="utf-8")
    return done.stdout


def _is_link(path: Path, root: Path) -> bool:
    """True if the path or any folder between it and the root is a symlink or junction."""
    return any(p.is_symlink() or p.is_junction()
               for p in [path, *path.parents] if p.is_relative_to(root) and p != root)


def collect_files(root: Path) -> list[str]:
    """Tracked files plus the named examples, so gitignored files can't enter."""
    examples = root / "examples"
    if _is_link(examples, root):
        raise SystemExit("Stopped: examples/ is a link, so it could point anywhere.")
    tracked = [p for p in _git(root, "ls-files", "-z").split("\0") if p]
    wanted = [rel for rel in tracked if not rel.startswith("examples/")]
    wanted += [f"examples/{name}" for name in EXAMPLE_FILES if (examples / name).is_file()]
    links = [rel for rel in wanted if _is_link(root / rel, root)]
    if links:  # a count, because a name is printed only after it has been scanned
        print(f"Skipped {len(links)} linked path(s).", file=sys.stderr)
    return sorted(rel for rel in set(wanted) - set(links) if not is_excluded(rel))


def _env_secrets(env_path: Path) -> list[bytes]:
    if not env_path.is_file():
        return []
    # Dropping zeros and byte order marks reads UTF-8, UTF-16 and UTF-32 alike.
    raw = env_path.read_bytes().replace(b"\0", b"")
    text = raw.removeprefix(b"\xef\xbb\xbf").removeprefix(b"\xff\xfe").removeprefix(b"\xfe\xff")
    secrets = []
    for line in text.decode("utf-8", errors="replace").splitlines():
        match = ENV_LINE.match(line)
        if match is None or match.group(1).upper() in NON_SECRET_ENV:
            continue
        value = match.group(2).strip()
        quoted = QUOTED.match(value)
        if quoted:
            forms = [quoted.group(2), re.sub(r"\\(.)", r"\1", quoted.group(2))]
        else:
            forms = [re.split(r"\s+#", value, maxsplit=1)[0].strip()]
        secrets += [form.encode() for form in forms if len(form) >= MIN_SECRET_LENGTH]
    return secrets


def _pdf_views(data: bytes) -> tuple[list[bytes], bool]:
    """Decompressed streams plus extracted text, and whether the text could be read. Chromium
    writes text as glyph IDs, so only extraction sees it. Unread text fails closed."""
    views = []
    for match in PDF_STREAM.finditer(data):
        try:
            views.append(zlib.decompressobj().decompress(match.group(1)))
        except zlib.error:
            continue  # not Flate data; the raw bytes are scanned anyway
    # pdfminer's warnings quote bad operands, which can be the very text being scanned.
    logging.disable(logging.CRITICAL)
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages).encode()
    except Exception:  # any parser failure means the text went unseen
        return views, False
    finally:
        logging.disable(logging.NOTSET)
    return [*views, text, re.sub(rb"\s", b"", text)], True


def _matches(views: list[bytes], secrets: list[bytes]) -> set[str]:
    found = {pattern for pattern, regex in PATTERNS.items()
             if any(regex.search(view) for view in views)}
    if any(secret in view for secret in secrets for view in views):
        found.add("env_value")
    return found


def _scan_blob(name: str, data: bytes, secrets: list[bytes], depth: int) -> set[tuple[str, str]]:
    name_matches = _matches([name.encode()], secrets)
    label = WITHHELD if name_matches else name
    views = [data]
    pdf_views, pdf_read = _pdf_views(data) if b"%PDF-" in data[:1024] else ([], True)
    views += pdf_views
    if name.lower().endswith(".xml"):  # Office text can be split across runs
        views.append(XML_TAG.sub(b"", data))
    # UTF-16 text, which PowerShell 5.1's > writes by default, has a zero between characters.
    views += [view.replace(b"\0", b"") for view in views]
    hits = {(label, pattern) for pattern in name_matches | _matches(views, secrets)}
    if not pdf_read:
        hits.add((label, "unreadable_pdf"))
    if data.startswith(UNPACKED_ARCHIVES):
        hits.add((label, "unreadable_archive"))
    if data.startswith(b"PK\x03\x04") or zipfile.is_zipfile(io.BytesIO(data)):
        hits |= _scan_nested(label, data, secrets, depth)
    return hits


def _scan_nested(label: str, data: bytes, secrets: list[bytes],
                 depth: int) -> set[tuple[str, str]]:
    """Office files are zips, so a plain byte scan can't see inside them."""
    if depth >= MAX_NESTING:
        return {(label, "unreadable_archive")}
    hits: set[tuple[str, str]] = set()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                inner = f"{label}!{info.filename}"
                hits |= _scan_blob(inner, zf.read(info), secrets, depth + 1)
    except ARCHIVE_ERRORS:  # corrupt or encrypted
        hits.add((label, "unreadable_archive"))
    return hits


def scan_zip(path: Path, env_path: Path = Path(".env")) -> list[tuple[str, str]]:
    """Returns (file, pattern name) pairs only, never the matched text."""
    return _scan(path, _env_secrets(env_path))


def _scan(path: Path, secrets: list[bytes]) -> list[tuple[str, str]]:
    hits: set[tuple[str, str]] = set()
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            hits |= _scan_blob(info.filename, zf.read(info), secrets, 0)
    return sorted(hits)


def _env_paths(root: Path) -> list[Path]:
    """The checkout's .env and, in a git worktree, the main checkout's."""
    common = Path(_git(root, "rev-parse", "--git-common-dir").strip())
    main = (root / common).resolve().parent
    return [p for p in {root / ".env", main / ".env"} if p.is_file()]


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        print(f"COULD NOT DELETE {path}. Delete it by hand; do not submit it.", file=sys.stderr)


def build_zip(group_id: str, out_dir: Path = Path("dist"),
              allow_incomplete_examples: bool = False) -> Path:
    if not GROUP_ID.fullmatch(group_id):
        raise SystemExit("The group ID may contain only letters, digits, - and _.")
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    folder = root / out_dir
    folder.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob("A3_Code_*.zip*"):
        stale.unlink()  # a failure here stops the build, so no old zip passes for a new one
    target = folder / f"A3_Code_{group_id}.zip"
    partial = folder / f"{target.name}.partial"
    env_paths = _env_paths(root)
    if not env_paths:
        print("No .env found: patterns scanned, no key values to compare.", file=sys.stderr)
    clean = False
    try:
        files = collect_files(root)
        required = list(REQUIRED)
        if not allow_incomplete_examples:
            required += [f"examples/{name}" for name in EXAMPLE_FILES]
        missing = [name for name in required if name not in files]
        if missing:
            raise SystemExit(f"Stopped: the zip would lack {', '.join(missing)}.")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in files:
                zf.write(root / rel, rel)
        # One pass over every secret, so a name withheld for one .env can't print for another.
        hits = _scan(partial, [s for env in env_paths for s in _env_secrets(env)])
        if hits:
            for name, pattern in hits:
                print(f"{name}: {pattern}", file=sys.stderr)
            print(f"Zip deleted: {len(hits)} hit(s).", file=sys.stderr)
            raise SystemExit(1)
        os.replace(partial, target)
        clean = True
    except Exception as exc:
        # The traceback would hold file names that were never scanned.
        raise SystemExit(f"Stopped: {type(exc).__name__} while building the zip.") from None
    finally:
        if not clean:
            _remove(partial)
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--allow-incomplete-examples", action="store_true",
                        help="for checks only: build without the full examples/ folder")
    args = parser.parse_args()
    path = build_zip(args.group_id, allow_incomplete_examples=args.allow_incomplete_examples)
    with zipfile.ZipFile(path) as zf:
        print(f"wrote {path} ({len(zf.namelist())} files, scan clean)")


if __name__ == "__main__":
    main()
