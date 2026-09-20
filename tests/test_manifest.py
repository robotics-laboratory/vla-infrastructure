"""The manifest is a reviewed set, not a recursive source-tree inventory."""

import hashlib
from pathlib import Path
import subprocess

import pytest

from tools.generate_manifest import main


def fixture(root: Path, paths: str = "z.bin\na.txt\n") -> None:
    (root / "configs").mkdir()
    (root / "configs/manifest_paths.txt").write_text(paths)
    (root / "z.bin").write_bytes(bytes(range(256)))
    (root / "a.txt").write_bytes(b"hello\r\n")


def run(root: Path, command: str = "generate") -> int:
    return main([command, "--root", str(root)])


def test_deterministic_explicit_order_binary_and_sha256sum(tmp_path):
    fixture(tmp_path)
    assert run(tmp_path) == 0
    first = (tmp_path / "MANIFEST.sha256").read_bytes()
    assert first.startswith(hashlib.sha256(bytes(range(256))).hexdigest().encode() + b"  z.bin\n")
    assert run(tmp_path) == 0
    assert (tmp_path / "MANIFEST.sha256").read_bytes() == first
    assert run(tmp_path, "verify") == 0
    result = subprocess.run(
        ["sha256sum", "-c", "MANIFEST.sha256"], cwd=tmp_path, capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_does_not_discover_unlisted_files(tmp_path):
    fixture(tmp_path)
    for name in [".venv/env", ".worktrees/other/file", "runtime/frame.png", "new.py"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not selected")
    assert run(tmp_path) == 0
    assert len((tmp_path / "MANIFEST.sha256").read_text().splitlines()) == 2


@pytest.mark.parametrize("kind", ["mismatch", "missing", "extra", "duplicate", "order", "format"])
def test_verify_rejects_corrupt_hash_or_inventory(tmp_path, kind):
    fixture(tmp_path)
    assert run(tmp_path) == 0
    manifest = tmp_path / "MANIFEST.sha256"
    lines = manifest.read_text().splitlines(keepends=True)
    if kind == "mismatch":
        (tmp_path / "a.txt").write_text("changed")
    elif kind == "missing":
        manifest.write_text(lines[0])
    elif kind == "extra":
        manifest.write_text("".join(lines) + "0" * 64 + "  unexpected.py\n")
    elif kind == "duplicate":
        manifest.write_text("".join(lines) + lines[0])
    elif kind == "order":
        manifest.write_text("".join(reversed(lines)))
    else:
        manifest.write_text("".join(lines).replace("  ", " "))
    assert run(tmp_path, "verify") == 1


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/etc/passwd",
        "a/../a.txt",
        "./a.txt",
        "a//b",
        "a\\b",
        "MANIFEST.sha256",
        ".git/config",
        ".venv/env",
        ".worktrees/other/file",
        "runtime/frame.png",
        "git-safety/capture",
        ".pytest_cache/file",
    ],
)
def test_rejects_unsafe_or_local_selection_without_changing_manifest(tmp_path, name):
    fixture(tmp_path)
    assert run(tmp_path) == 0
    manifest = tmp_path / "MANIFEST.sha256"
    before = manifest.read_bytes()
    (tmp_path / "configs/manifest_paths.txt").write_text(name + "\n")
    assert run(tmp_path) == 1
    assert manifest.read_bytes() == before


@pytest.mark.parametrize("kind", ["internal", "external", "parent", "source", "output"])
def test_rejects_all_symlinks(tmp_path, kind):
    fixture(tmp_path)
    if kind in ("internal", "external"):
        (tmp_path / "a.txt").unlink()
        (tmp_path / "a.txt").symlink_to("z.bin" if kind == "internal" else "/etc/passwd")
    elif kind == "parent":
        (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
        (tmp_path / "configs/manifest_paths.txt").write_text("alias/a.txt\n")
    elif kind == "source":
        (tmp_path / "configs/manifest_paths.txt").unlink()
        (tmp_path / "configs/manifest_paths.txt").symlink_to("../a.txt")
    else:
        (tmp_path / "MANIFEST.sha256").symlink_to("a.txt")
    before = (tmp_path / "z.bin").read_bytes()
    assert run(tmp_path) == 1
    assert (tmp_path / "z.bin").read_bytes() == before


@pytest.mark.parametrize("paths", ["", "a.txt\na.txt\n", "missing\n", "configs\n"])
def test_rejects_invalid_protected_set(tmp_path, paths):
    fixture(tmp_path, paths)
    assert run(tmp_path) == 1
    assert not (tmp_path / "MANIFEST.sha256").exists()


def test_reviewed_new_path_is_explicit(tmp_path):
    fixture(tmp_path)
    (tmp_path / "selected.png").write_bytes(b"\x89PNG\x00\xff")
    (tmp_path / "configs/manifest_paths.txt").write_text("# Review order\na.txt\nselected.png\n")
    assert run(tmp_path) == 0
    assert run(tmp_path, "verify") == 0
    assert "selected.png" in (tmp_path / "MANIFEST.sha256").read_text()
    assert "z.bin" not in (tmp_path / "MANIFEST.sha256").read_text()


def test_archived_manifest_is_hashed_as_opaque_bytes(tmp_path):
    fixture(tmp_path)
    archive = tmp_path / "docs/archive/old/MANIFEST.sha256"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"historical hashes may reference files that no longer exist\n")
    before = archive.read_bytes()
    (tmp_path / "configs/manifest_paths.txt").write_text("docs/archive/old/MANIFEST.sha256\n")
    assert run(tmp_path) == 0
    assert run(tmp_path, "verify") == 0
    assert archive.read_bytes() == before
    assert (tmp_path / "MANIFEST.sha256").read_text().startswith(hashlib.sha256(before).hexdigest())
