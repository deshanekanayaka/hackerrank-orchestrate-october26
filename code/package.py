"""Build code.zip for submission, then check what went into it.

A zip command alone cannot say whether the archive is safe. This builds the
archive and then reads it back, so an excluded item that slips in fails the
run instead of reaching a grader.

    python3 code/package.py            # build code.zip and check it
    python3 code/package.py --check    # check the existing code.zip only
    python3 code/package.py --list     # print what would go in

What goes in: README.md, code/, evaluation/, and docs/. What stays out:
dataset/, .env, every dependency cache, every nested archive, and every
secret.
"""

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "code.zip"

INCLUDE = ["README.md", "code", "evaluation", "docs"]

# A path segment that must never appear in the archive.
SKIP_DIRS = {"__pycache__", ".venv", "venv", "env", "node_modules", ".git",
             ".pytest_cache", ".mypy_cache", ".ipynb_checkpoints",
             "dataset", ".scratch", "artifacts"}
SKIP_NAMES = {".DS_Store", "code.zip", ".env"}
# A nested archive makes the submission invalid.
ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2",
                    ".xz"}
# The whole point of the check: a key must never ship.
SECRETS = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"ANTHROPIC_API_KEY\s*=\s*['\"]?[A-Za-z0-9_-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def wanted(path):
    """Does this file belong in the archive?"""
    parts = path.relative_to(ROOT).parts
    if set(parts) & SKIP_DIRS or path.name in SKIP_NAMES:
        return False
    if path.name.startswith(".env"):
        return False
    if path.suffix.lower() in ARCHIVE_SUFFIXES:
        return False
    return True


def members():
    """Every file to archive, sorted, so two builds give the same order."""
    out = []
    for entry in INCLUDE:
        start = ROOT / entry
        if not start.exists():
            raise SystemExit(f"FAIL: {entry} is missing")
        if start.is_file():
            if wanted(start):
                out.append(start)
            continue
        out.extend(p for p in start.rglob("*") if p.is_file() and wanted(p))
    return sorted(out, key=lambda p: str(p.relative_to(ROOT)))


def build():
    files = members()
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(ROOT).as_posix())
    size = ARCHIVE.stat().st_size
    print(f"wrote code.zip: {len(files)} files, {size / 1024:.0f} KiB")
    return files


def secrets_in(data, name):
    """Lines of this file that look like a credential."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    hits = []
    for pattern in SECRETS:
        for found in pattern.finditer(text):
            hits.append(f"{name}: {found.group(0)[:24]}...")
    return hits


def check():
    """Read the archive back and fail on anything that must not be there."""
    if not ARCHIVE.exists():
        raise SystemExit("FAIL: no code.zip. Run python3 code/package.py")
    problems = []
    with zipfile.ZipFile(ARCHIVE) as zf:
        names = zf.namelist()
        for name in names:
            parts = Path(name).parts
            if set(parts) & SKIP_DIRS:
                problems.append(f"excluded directory in the archive: {name}")
            if Path(name).name in SKIP_NAMES or Path(name).name \
                    .startswith(".env"):
                problems.append(f"excluded file in the archive: {name}")
            if Path(name).suffix.lower() in ARCHIVE_SUFFIXES:
                problems.append(f"nested archive: {name}")
        # Every member that decodes as text is scanned. An allowlist of
        # extensions would miss a key in a Makefile or an unnamed script.
        for name in names:
            problems.extend(secrets_in(zf.read(name), name))
        required = ["README.md",
                    "code/main.py",
                    "code/cache/intent.json",
                    "code/cache/vision.json",
                    "evaluation/evaluation_report.md",
                    "evaluation/usage_report.md",
                    "docs/data-quality.md"]
        for need in required:
            if need not in names:
                problems.append(f"missing from the archive: {need}")
        if zf.testzip() is not None:
            problems.append("the archive is corrupt")

        # An archive that no longer matches the tree is worse than none: it
        # submits code nobody reviewed. Size is enough to catch an edit.
        tree = {p.relative_to(ROOT).as_posix(): p.stat().st_size
                for p in members()}
        stored = {i.filename: i.file_size for i in zf.infolist()}
        for name in sorted(set(tree) | set(stored)):
            if name not in stored:
                problems.append(f"in the tree but not the archive: {name}")
            elif name not in tree:
                problems.append(f"in the archive but not the tree: {name}")
            elif tree[name] != stored[name]:
                problems.append(f"changed since the archive was built: "
                                f"{name}")

    for line in problems:
        print("FAIL", line)
    if problems:
        # Remove it, so nobody submits the archive these lines rejected.
        ARCHIVE.unlink(missing_ok=True)
        print("removed code.zip")
        return 1
    print(f"PASS: {len(names)} files, no excluded item, no nested archive, "
          f"no credential")
    return 0


def main(argv):
    if "--list" in argv:
        for path in members():
            print(path.relative_to(ROOT).as_posix())
        return 0
    if "--check" not in argv:
        build()
    return check()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
