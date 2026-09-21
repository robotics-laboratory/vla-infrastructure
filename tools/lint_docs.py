#!/usr/bin/env python3
"""Read-only, offline documentation inventory/navigation/preservation check."""

from __future__ import annotations

import argparse
from collections import Counter
import html
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import yaml

# Importing the shared checker must not create repository bytecode caches.
sys.dont_write_bytecode = True

try:  # Direct script and normal pytest/module entrypoints.
    from .lint_spec_references import check_references
except ImportError:
    from lint_spec_references import check_references  # type: ignore[import-not-found, no-redef]

ROOT = Path(__file__).resolve().parents[1]
INDEX = "docs/INDEX.yaml"
BOOTSTRAP_BASE = "98fb74f278e91a7f29a3b00f44a4a2284a053607"
KINDS = set(
    "normative policy operations design plan template evidence experiment migration incident reference generated".split()
)
DESTINATIONS = {
    "operations": "operations",
    "design": "design",
    "plan": "plans",
    "template": "templates",
    "evidence": "evidence",
    "experiment": "experiments",
    "migration": "migrations",
    "incident": "incidents",
    "reference": "reference",
}


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate mapping keys instead of silently keeping the last value."""


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors="replace").strip() or f"git {args} failed")
    return result.stdout


def inventory(root: Path) -> set[str]:
    return set(git(root, "ls-files", "-z").decode().split("\0")) - {""}


def tree(root: Path, commit: str) -> dict[str, str]:
    entries = {}
    for item in git(root, "ls-tree", "-rz", "--full-tree", commit).decode().split("\0"):
        if item:
            metadata, path = item.split("\t", 1)
            entries[path] = metadata.split()[0]
    return entries


def in_scope(path: str) -> bool:
    return path.startswith("docs/") or path.lower().endswith(".md")


def normalized(path: object) -> bool:
    return (
        isinstance(path, str)
        and bool(path)
        and not path.startswith(("/", "~"))
        and PurePosixPath(path).as_posix() == path
        and not {"..", ".git", ".worktrees"}.intersection(PurePosixPath(path).parts)
        and "\\" not in path
        and not any(ord(c) < 32 or ord(c) == 127 for c in path)
    )


def local_path(root: Path, name: str) -> Path | None:
    """Do not follow a local link into external storage or another worktree."""
    path = root
    for part in PurePosixPath(name).parts:
        path = path / part
        if path.is_symlink():
            return None
    return path


def regular(root: Path, name: str) -> bool:
    path = local_path(root, name)
    return path is not None and path.is_file()


def read_index(raw: str) -> dict[str, dict]:
    data = yaml.load(raw, Loader=UniqueLoader)
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "documents"}
        or type(data["version"]) is not int
        or data["version"] != 1
    ):
        raise ValueError("INDEX requires version: 1 and documents")
    if not isinstance(data["documents"], list):
        raise ValueError("documents must be a list")
    entries: dict[str, dict] = {}
    required = {"path", "kind", "status", "owner", "mutable"}
    for entry in data["documents"]:
        if (
            not isinstance(entry, dict)
            or not required <= set(entry)
            or set(entry) - required - {"gates", "superseded_by"}
        ):
            raise ValueError(f"invalid INDEX fields: {entry!r}")
        path = entry["path"]
        if not normalized(path):
            raise ValueError(f"invalid index path: {path!r}")
        if path in entries:
            raise ValueError(f"duplicate index path: {path}")
        if not isinstance(entry["kind"], str) or entry["kind"] not in KINDS:
            raise ValueError(f"{path}: invalid kind")
        if entry["status"] not in ("current", "historical"):
            raise ValueError(f"{path}: invalid status")
        if type(entry["mutable"]) is not bool:
            raise ValueError(f"{path}: mutable must be boolean")
        if entry["status"] == "historical" and entry["mutable"]:
            raise ValueError(f"{path}: historical must be immutable")
        if not isinstance(entry["owner"], str) or not re.fullmatch(
            r"[a-z][a-z0-9_.-]*", entry["owner"]
        ):
            raise ValueError(f"{path}: invalid owner")
        gates = entry.get("gates", [])
        if (
            not isinstance(gates, list)
            or any(not isinstance(g, str) for g in gates)
            or len(gates) != len(set(gates))
        ):
            raise ValueError(f"{path}: invalid gates")
        if "superseded_by" in entry and not normalized(entry["superseded_by"]):
            raise ValueError(f"{path}: invalid superseded_by path")
        entries[path] = entry
    return entries


def placement(path: str, entry: dict, legacy: set[str], gates: set[str]) -> bool:
    if path in legacy:
        return True
    if path in {INDEX, "docs/README.md"}:
        return entry["kind"] == "reference"
    parts = PurePosixPath(path).parts
    kind = entry["kind"]
    if kind in {"normative", "policy", "generated"}:
        return len(parts) == 2 and parts[0] == "docs" and path.endswith(".md")
    if len(parts) < 3 or parts[:2] != ("docs", DESTINATIONS.get(kind)):
        return False
    if kind == "evidence":
        return len(parts) >= 5 and parts[2] in gates
    if kind in {"experiment", "migration", "incident"}:
        return len(parts) >= 4
    return True


def prose_lines(text: str) -> list[tuple[str, bool]]:
    """Remove fenced/indented code; mark only explicit Sources of truth sections."""
    lines: list[tuple[str, bool]] = []
    fence = ""
    authority_level = 0
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match[1]
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ""
            continue
        if fence or line.startswith(("    ", "\t")):
            continue
        heading = re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            level = len(heading[1])
            if authority_level and level <= authority_level:
                authority_level = 0
            if heading[2].strip().casefold() == "sources of truth":
                authority_level = level
        lines.append((re.sub(r"(`+).*?\1", "", line), bool(authority_level)))
    return lines


def destination(text: str, start: int) -> tuple[str, int]:
    """Parse a Markdown destination, including escapes and balanced parentheses."""
    start += len(text[start:]) - len(text[start:].lstrip())
    if start < len(text) and text[start] == "<":
        end = text.find(">", start + 1)
        if end < 0:
            raise ValueError("unterminated angle link destination")
        return text[start + 1 : end], end + 1
    depth, end = 0, start
    while end < len(text):
        char = text[end]
        if char == "\\" and end + 1 < len(text):
            end += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            if not depth:
                break
            depth -= 1
        elif char.isspace() and not depth:
            break
        end += 1
    return text[start:end], end


def markdown_links(text: str) -> list[tuple[str, bool]]:
    # Join prose across soft line breaks, keeping explicit authority boundaries.
    chunks: list[tuple[str, bool]] = []
    for line, authoritative in prose_lines(text):
        if chunks and chunks[-1][1] == authoritative:
            previous, _ = chunks[-1]
            chunks[-1] = (previous + "\n" + line, authoritative)
        else:
            chunks.append((line, authoritative))
    definitions: dict[str, str] = {}
    result: list[tuple[str, bool]] = []
    definition = re.compile(r"^ {0,3}\[([^\]\n]+)\]:[^\S\n]*(.*)$", re.MULTILINE)

    def label(s: str) -> str:
        return " ".join(s.split()).casefold()

    for chunk, _ in chunks:
        for match in definition.finditer(chunk):
            definitions[label(match[1])] = destination(match[2], 0)[0]
    for chunk, authoritative in chunks:
        line = definition.sub("", chunk)
        for match in re.finditer(r"(?<![!\\])\[([^\]]*)\]|(?<!\\)!\[([^\]]*)\]", line):
            name = match[1] if match[1] is not None else match[2]
            end = match.end()
            if end < len(line) and line[end] == "(":
                target, _ = destination(line, end + 1)
                result.append((target, authoritative))
            elif end < len(line) and line[end] == "[":
                close = line.find("]", end + 1)
                if close >= 0:
                    key = label(line[end + 1 : close] or name)
                    if key not in definitions:
                        raise ValueError(f"undefined Markdown reference: {key}")
                    result.append((definitions[key], authoritative))
            elif label(name) in definitions:
                result.append((definitions[label(name)], authoritative))
    return result


def navigation(root: Path, path: str, entries: dict[str, dict]) -> list[str]:
    errors = []
    for target, authoritative in markdown_links((root / path).read_text()):
        target = html.unescape(
            re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])", r"\1", target)
        )
        url = urlsplit(target)
        if url.scheme or url.netloc or not url.path:
            continue
        decoded = unquote(url.path)
        if decoded.startswith("/"):
            errors.append(f"{path}: local links must be repository-relative: {target}")
            continue
        dest = posixpath.normpath(posixpath.join(posixpath.dirname(path), decoded))
        local = local_path(root, dest) if normalized(dest) else None
        if local is None or not local.exists():
            errors.append(f"{path}: missing/unsafe local target: {target}")
        elif authoritative and in_scope(dest):
            if (
                dest not in entries
                or entries[dest]["status"] != "current"
                or entries[dest].get("superseded_by")
            ):
                errors.append(f"{path}: authoritative reference is not a current owner: {dest}")
    return errors


def preservation(root: Path, base: str, entries: dict[str, dict]) -> tuple[list[str], int]:
    commit = (
        git(root, "rev-parse", "--verify", "--end-of-options", base + "^{commit}").decode().strip()
    )
    git(root, "merge-base", "--is-ancestor", commit, "HEAD")
    old_paths = tree(root, commit)
    if INDEX in old_paths:
        old = read_index(git(root, "show", f"{commit}:{INDEX}").decode())
    else:
        if commit != BOOTSTRAP_BASE:
            raise ValueError("base without INDEX must be the audited bootstrap commit")
        old = {p: e for p, e in entries.items() if p in old_paths}
    protected = {p: e for p, e in old.items() if e["status"] == "historical" or not e["mutable"]}
    staged_changes = set(
        git(root, "diff", "--cached", "--name-only", "-z", commit).decode().split("\0")
    )
    errors = []
    for path, before in protected.items():
        after = entries.get(path)
        if (
            after is None
            or after["status"] != before["status"]
            or after["mutable"] != before["mutable"]
        ):
            errors.append(f"{path}: cannot remove or relax trusted immutable classification")
        if not regular(root, path) or old_paths.get(path) not in {"100644", "100755"}:
            errors.append(f"{path}: historical/immutable file missing or not regular")
        elif (root / path).read_bytes() != git(
            root, "show", f"{commit}:{path}"
        ) or path in staged_changes:
            errors.append(f"{path}: historical/immutable bytes or staged identity changed")
    return errors, len(protected)


def check(root: Path, base: str | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes = []
    try:
        tracked = inventory(root)
        for source in (INDEX, "configs/gate_rules.yaml", "configs/resolved_contract.yaml"):
            if not regular(root, source):
                raise ValueError(f"{source}: input missing or not regular")
        entries = read_index((root / INDEX).read_text())
        rules = yaml.safe_load((root / "configs/gate_rules.yaml").read_text())
        contract = yaml.safe_load((root / "configs/resolved_contract.yaml").read_text())
        legacy = set(tree(root, BOOTSTRAP_BASE))
        scope = {p for p in tracked if in_scope(p)}
        for path in sorted(scope - entries.keys()):
            errors.append(f"{path}: missing index entry")
        for path, entry in entries.items():
            if path not in tracked:
                errors.append(f"{path}: indexed path is not tracked")
            if not regular(root, path):
                errors.append(f"{path}: indexed path missing or not regular")
            if not in_scope(path):
                errors.append(f"{path}: outside documentation coverage")
            if not placement(path, entry, legacy, set(rules)):
                errors.append(f"{path}: forbidden new documentation placement")
            for gate in entry.get("gates", []):
                if gate not in rules:
                    errors.append(f"{path}: unknown navigation gate {gate}")
            seen = {path}
            target = entry.get("superseded_by")
            while target:
                if target in seen:
                    errors.append(f"{path}: supersession cycle")
                    break
                if target not in entries:
                    errors.append(f"{path}: missing superseded_by target {target}")
                    break
                seen.add(target)
                target = entries[target].get("superseded_by")
            if entry["status"] == "current" and path.endswith(".md") and regular(root, path):
                errors.extend(navigation(root, path, entries))
                errors.extend(
                    check_references(
                        (root / path).read_text(),
                        Path(path).name,
                        set(rules),
                        set(contract["execution_profiles"]),
                        set(contract["taxonomy"]["source_classes"]),
                    )
                )
        notes.append(
            f"INDEX: {len(entries)} entries; classification {dict(Counter(e['status'] for e in entries.values()))}"
        )
        if base:
            issues, count = preservation(root, base, entries)
            errors.extend(issues)
            notes.append(
                f"HISTORICAL PRESERVATION: {'FAIL' if issues else 'PASS'} ({count} frozen files vs {base})"
            )
        else:
            notes.append(
                "HISTORICAL PRESERVATION: NOT CHECKED (supply --base for full pre-merge check)"
            )
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        errors.append(str(exc))
    notes.append(
        "KNOWN HISTORICAL INTEGRITY DEBT: UNRESOLVED; see docs/plans/DOCUMENTATION_GOVERNANCE.md. Bundle authenticity and external artifacts NOT CHECKED."
    )
    return errors, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Reviewer-supplied trusted ancestor commit")
    args = parser.parse_args(argv)
    errors, notes = check(ROOT, args.base)
    print("\n".join(notes))
    for error in errors:
        print(f"- {error}")
    print("DOC GOVERNANCE CHECKS: " + ("FAIL" if errors else "PASS"))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
