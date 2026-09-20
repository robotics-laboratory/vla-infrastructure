#!/usr/bin/env python3
"""Refresh or verify the explicitly reviewed manifest set; never discover files."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "MANIFEST.sha256"
PATHS = "configs/manifest_paths.txt"
# Local/runtime directories are never a substitute for reviewed source paths.
FORBIDDEN_PARTS = frozenset(
    {
        ".git",
        ".worktrees",
        ".venv",
        ".codegraph",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "git-safety",
        "cache",
        "caches",
        "runtime",
        "captures",
        "build",
        "dist",
    }
)
ENTRY = re.compile(r"([0-9a-f]{64})  (.+)")


def checked_path(root: Path, name: str, *, missing_ok: bool = False) -> Path:
    """Only normalized, repo-relative paths, with no symlink components."""
    parts = PurePosixPath(name).parts
    if (
        not parts
        or PurePosixPath(name).is_absolute()
        or PurePosixPath(name).as_posix() != name
        or ".." in parts
        or "\\" in name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or FORBIDDEN_PARTS.intersection(parts)
    ):
        raise ValueError(f"Unsafe/local path: {name!r}")
    path = root
    for i, part in enumerate(parts):
        path = path / part
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            if missing_ok and i == len(parts) - 1:
                return path
            raise ValueError(f"Missing path: {name}") from None
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlink is not supported: {name}")
        if i < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise ValueError(f"Non-directory parent: {name}")
    if not stat.S_ISREG(mode):
        raise ValueError(f"Not a regular file: {name}")
    return path


def read_paths(root: Path, source: str = PATHS) -> list[str]:
    """Preserve reviewed list order; comments and blank lines are not entries."""
    text = checked_path(root, source).read_text(encoding="utf-8")
    paths = [line for line in text.splitlines() if line and not line.startswith("#")]
    if not paths or len(set(paths)) != len(paths):
        raise ValueError("Protected set must be nonempty and contain no duplicates")
    for name in paths:
        if name == MANIFEST:
            raise ValueError("Manifest self-reference is forbidden")
        checked_path(root, name)
    return paths


def render(root: Path, paths: list[str]) -> bytes:
    lines = []
    for name in paths:
        with checked_path(root, name).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        lines.append(f"{digest}  {name}\n")
    return "".join(lines).encode("utf-8")


def verify(root: Path, paths: list[str], expected: bytes) -> list[str]:
    """Check exact inventory/order/format as well as every protected byte."""
    raw = checked_path(root, MANIFEST).read_bytes()
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return ["Manifest is not UTF-8"]
    matches = [ENTRY.fullmatch(line) for line in lines]
    if not all(matches):
        return ["Malformed entry (expected lowercase SHA256, two spaces, POSIX path)"]
    actual_paths = [match[2] for match in matches if match is not None]
    errors = []
    if actual_paths != paths:
        errors.append("Manifest inventory/order differs from the reviewed path list")
    if len(set(actual_paths)) != len(actual_paths):
        errors.append("Duplicate manifest entry")
    if raw != expected:
        expected_lines = dict(zip(paths, expected.decode("utf-8").splitlines(), strict=True))
        for name, line in zip(actual_paths, lines, strict=True):
            if name in expected_lines and line != expected_lines[name]:
                errors.append(f"SHA256 mismatch: {name}")
        if raw.replace(b"\r\n", b"\n") != raw or not raw.endswith(b"\n"):
            errors.append("Expected LF-terminated entries")
        if not errors:
            errors.append("Manifest bytes differ from canonical output")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "verify"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--paths", default=PATHS, help="Reviewed repo-relative path list")
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    try:
        paths = read_paths(root, args.paths)
        output = checked_path(root, MANIFEST, missing_ok=args.command == "generate")
        expected = render(root, paths)
        if args.command == "verify":
            errors = verify(root, paths, expected)
            if errors:
                print("\n".join(errors))
                return 1
            print(f"MANIFEST OK: {len(paths)} reviewed files")
            return 0
        # Complete all reads before replacing the output. No partial manifest on failure.
        mode = stat.S_IMODE(output.stat().st_mode) if output.exists() else 0o644
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=root, prefix=".manifest-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(expected)
            temporary.chmod(mode)
            os.replace(temporary, output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        print(f"MANIFEST generated: {len(paths)} reviewed files")
        return 0
    except (OSError, ValueError) as exc:
        print(f"MANIFEST ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
