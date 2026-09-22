"""Fail-closed, portable asset closure for an exported Isaac USD stage.

The core of this module deliberately has no Kit or USD imports.  Production uses
``pxr.UsdUtils.ComputeAllDependencies`` through a lazy adapter, while unit tests
can supply a dependency provider without importing Isaac Sim.

Resolved host paths are never serialized.  Each file must be below one of the
explicitly named portable roots and is recorded as ``<root-name>/<relative-path>``.
Replay can therefore bind the same names to different local roots without
depending on the recording host's absolute directory layout.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit


SCHEMA_VERSION = "piper_x_isaac_vr_asset_closure_v1"
_PORTABLE_ROOT_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")


class AssetClosureError(RuntimeError):
    """The saved stage does not have a complete, portable local closure."""


DependencyProvider = Callable[[str], tuple[Iterable[Any], Iterable[Any], Iterable[Any]]]


def _usd_dependencies(snapshot: str) -> tuple[Iterable[Any], Iterable[Any], Iterable[Any]]:
    """Load the pinned USD API only inside an initialized Kit process."""

    try:
        from pxr import UsdUtils  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised in the Isaac environment
        raise AssetClosureError(
            "pxr.UsdUtils is unavailable; asset closure must run in the declared Isaac "
            "environment"
        ) from exc
    return UsdUtils.ComputeAllDependencies(snapshot)


def _dependency_path(value: Any, *, kind: str) -> str:
    """Extract a resolved filesystem path from an Sdf layer/asset or a test fake."""

    if kind == "layer":
        candidate = getattr(value, "realPath", None)
    else:
        candidate = getattr(value, "resolvedPath", None)
        if not candidate:
            candidate = getattr(value, "path", None)
    if not candidate:
        candidate = value if isinstance(value, (str, os.PathLike)) else None
    if candidate is None or not str(candidate).strip():
        raise AssetClosureError(f"resolved {kind} has no local filesystem path: {value!r}")
    return os.fspath(candidate)


def _reject_uri(path: str, *, kind: str) -> None:
    parsed = urlsplit(path)
    if parsed.scheme:
        raise AssetClosureError(
            f"resolved {kind} is not a portable local file: {path!r} "
            f"(URI scheme {parsed.scheme!r})"
        )


def _resolved_file(path: str, *, snapshot_directory: Path, kind: str) -> Path:
    _reject_uri(path, kind=kind)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = snapshot_directory / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AssetClosureError(f"resolved {kind} is missing or inaccessible: {path!r}") from exc
    if not resolved.is_file():
        raise AssetClosureError(f"resolved {kind} is not a regular file: {resolved}")
    return resolved


def _portable_roots(
    snapshot: Path | None, roots: Mapping[str, str | os.PathLike[str]] | None
) -> tuple[tuple[str, Path], ...]:
    if roots is not None:
        configured = roots
    elif snapshot is not None:
        configured = {"recording": snapshot.parent}
    else:
        raise AssetClosureError("portable root bindings are required for verification")
    if not configured:
        raise AssetClosureError("at least one portable root is required")

    normalized: list[tuple[str, Path]] = []
    names: set[str] = set()
    for raw_name, raw_root in configured.items():
        name = str(raw_name)
        if not _PORTABLE_ROOT_NAME.fullmatch(name) or name in {".", ".."}:
            raise AssetClosureError(f"invalid portable root name: {name!r}")
        folded = name.casefold()
        if folded in names:
            raise AssetClosureError(f"portable root names collide case-insensitively: {name!r}")
        names.add(folded)
        try:
            root = Path(raw_root).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise AssetClosureError(
                f"portable root is missing or inaccessible: {raw_root!r}"
            ) from exc
        if not root.is_dir():
            raise AssetClosureError(f"portable root is not a directory: {root}")
        normalized.append((name, root))

    # Most-specific root wins for nested declarations.  Name is the stable tie breaker.
    return tuple(sorted(normalized, key=lambda item: (-len(item[1].parts), item[0])))


def _portable_path(path: Path, roots: tuple[tuple[str, Path], ...]) -> str:
    for name, root in roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise AssetClosureError(f"path cannot be represented portably: {path}")
        result = f"{name}/{relative.as_posix()}"
        if Path(result).is_absolute() or ".." in Path(result).parts:
            raise AssetClosureError(f"path cannot be represented portably: {path}")
        return result
    declared = ", ".join(f"{name}={root}" for name, root in roots)
    raise AssetClosureError(f"dependency is outside declared portable roots: {path} ({declared})")


def _resolve_portable_path(path: str, roots: tuple[tuple[str, Path], ...]) -> Path:
    """Resolve one serialized alias/path while rejecting traversal and symlink escape."""

    portable = PurePosixPath(path)
    if (
        not path
        or portable.is_absolute()
        or len(portable.parts) < 2
        or any(part in {"", ".", ".."} for part in portable.parts)
        or "\\" in path
        or portable.as_posix() != path
    ):
        raise AssetClosureError(f"invalid portable dependency path: {path!r}")
    bindings = dict(roots)
    alias, relative_parts = portable.parts[0], portable.parts[1:]
    root = bindings.get(alias)
    if root is None:
        raise AssetClosureError(f"portable dependency path uses unbound root {alias!r}: {path!r}")
    candidate = root.joinpath(*relative_parts)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise AssetClosureError(f"portable dependency is missing or inaccessible: {path!r}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AssetClosureError(f"portable dependency escapes root {alias!r}: {path!r}") from exc
    if not resolved.is_file():
        raise AssetClosureError(f"portable dependency is not a regular file: {path!r}")
    return resolved


def _hash_stable_file(path: Path) -> tuple[int, str]:
    """Hash a file and reject mutation during the read."""

    try:
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
    except OSError as exc:
        raise AssetClosureError(f"dependency is unreadable: {path}") from exc

    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        raise AssetClosureError(f"dependency changed while it was hashed: {path}")
    return before.st_size, digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_asset_closure_manifest(
    stage_snapshot: str | os.PathLike[str],
    *,
    portable_roots: Mapping[str, str | os.PathLike[str]] | None = None,
    dependency_provider: DependencyProvider | None = None,
) -> dict[str, object]:
    """Return the complete deterministic manifest for a saved USD snapshot.

    ``portable_roots`` maps stable logical names to recording-host directories.
    With no explicit mapping, only files beside/below the snapshot are accepted.
    All transitive layers and assets returned by USD must fit one of these roots.

    The aggregate digest covers the schema, portable snapshot identity and every
    sorted entry (including its kinds, size and content digest).  It intentionally
    excludes absolute paths and therefore remains stable after relocating roots.
    """

    snapshot_input = Path(stage_snapshot)
    try:
        snapshot = snapshot_input.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AssetClosureError(
            f"stage snapshot is missing or inaccessible: {stage_snapshot!r}"
        ) from exc
    if not snapshot.is_file():
        raise AssetClosureError(f"stage snapshot is not a regular file: {snapshot}")

    roots = _portable_roots(snapshot, portable_roots)
    provider = dependency_provider or _usd_dependencies
    try:
        layers, assets, unresolved = provider(str(snapshot))
    except AssetClosureError:
        raise
    except Exception as exc:
        raise AssetClosureError(f"USD dependency traversal failed for {snapshot}") from exc

    unresolved_items = sorted({str(item) for item in unresolved})
    if unresolved_items:
        raise AssetClosureError(
            "USD dependency traversal reported unresolved references: "
            + ", ".join(repr(item) for item in unresolved_items)
        )

    paths: dict[Path, set[str]] = {snapshot: {"snapshot"}}
    for kind, dependencies in (("layer", layers), ("asset", assets)):
        for dependency in dependencies:
            raw_path = _dependency_path(dependency, kind=kind)
            resolved = _resolved_file(
                raw_path,
                snapshot_directory=snapshot.parent,
                kind=kind,
            )
            paths.setdefault(resolved, set()).add(kind)

    entries: list[dict[str, object]] = []
    portable_names: dict[str, Path] = {}
    for path, kinds in paths.items():
        portable_path = _portable_path(path, roots)
        collision_key = portable_path.casefold()
        previous = portable_names.get(collision_key)
        if previous is not None and previous != path:
            raise AssetClosureError(
                "portable dependency paths collide case-insensitively: "
                f"{previous} and {path}"
            )
        portable_names[collision_key] = path
        size, sha256 = _hash_stable_file(path)
        entries.append(
            {
                "path": portable_path,
                "kinds": sorted(kinds),
                "size_bytes": size,
                "sha256": sha256,
            }
        )

    entries.sort(key=lambda entry: str(entry["path"]))
    snapshot_path = _portable_path(snapshot, roots)
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "stage_snapshot_path": snapshot_path,
        "entry_count": len(entries),
        "entries": entries,
    }
    payload["asset_closure_sha256"] = _canonical_sha256(payload)
    return payload


def _required_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise AssetClosureError(f"asset closure {field} must be a lowercase SHA-256 digest")
    return value


def verify_asset_closure_manifest(
    sidecar: str | os.PathLike[str],
    *,
    portable_roots: Mapping[str, str | os.PathLike[str]],
    expected_stage_snapshot: str | os.PathLike[str] | None = None,
) -> dict[str, object]:
    """Verify a closure sidecar and re-hash every bound file.

    Root bindings are mandatory and there is deliberately no absolute-path or
    sidecar-directory fallback.  A verifier on another host must explicitly bind
    every logical root used by the recording.
    """

    sidecar_path = Path(sidecar)
    try:
        document = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssetClosureError(f"asset closure sidecar is unreadable: {sidecar_path}") from exc
    if not isinstance(document, dict):
        raise AssetClosureError("asset closure sidecar root must be an object")
    required_fields = {
        "schema_version",
        "stage_snapshot_path",
        "entry_count",
        "entries",
        "asset_closure_sha256",
    }
    if set(document) != required_fields:
        raise AssetClosureError(
            "asset closure sidecar fields differ from schema: "
            f"missing={sorted(required_fields - set(document))}, "
            f"extra={sorted(set(document) - required_fields)}"
        )
    if document["schema_version"] != SCHEMA_VERSION:
        raise AssetClosureError(
            f"unsupported asset closure schema: {document['schema_version']!r}"
        )

    declared_aggregate = _required_sha256(
        document["asset_closure_sha256"], field="asset_closure_sha256"
    )
    aggregate_payload = dict(document)
    del aggregate_payload["asset_closure_sha256"]
    actual_aggregate = _canonical_sha256(aggregate_payload)
    if actual_aggregate != declared_aggregate:
        raise AssetClosureError(
            "asset closure aggregate digest mismatch: "
            f"expected {declared_aggregate}, got {actual_aggregate}"
        )

    entries = document["entries"]
    count = document["entry_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise AssetClosureError("asset closure entry_count must be a positive integer")
    if not isinstance(entries, list) or len(entries) != count:
        raise AssetClosureError("asset closure entry_count does not match entries")
    stage_path = document["stage_snapshot_path"]
    if not isinstance(stage_path, str):
        raise AssetClosureError("asset closure stage_snapshot_path must be a string")

    roots = _portable_roots(None, portable_roots)
    seen_paths: dict[str, str] = {}
    seen_files: dict[Path, str] = {}
    snapshot_entries = 0
    resolved_stage: Path | None = None
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict) or set(raw_entry) != {
            "path",
            "kinds",
            "size_bytes",
            "sha256",
        }:
            raise AssetClosureError(f"asset closure entry {index} does not match schema")
        path = raw_entry["path"]
        if not isinstance(path, str):
            raise AssetClosureError(f"asset closure entry {index} path must be a string")
        collision_key = path.casefold()
        if collision_key in seen_paths:
            raise AssetClosureError(
                "asset closure paths are duplicate or collide case-insensitively: "
                f"{seen_paths[collision_key]!r}, {path!r}"
            )
        seen_paths[collision_key] = path
        kinds = raw_entry["kinds"]
        if (
            not isinstance(kinds, list)
            or not kinds
            or not all(isinstance(kind, str) for kind in kinds)
            or kinds != sorted(set(kinds))
            or not set(kinds) <= {"snapshot", "layer", "asset"}
        ):
            raise AssetClosureError(f"asset closure entry {path!r} has invalid kinds")
        size = raw_entry["size_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise AssetClosureError(f"asset closure entry {path!r} has invalid size_bytes")
        declared_sha256 = _required_sha256(raw_entry["sha256"], field=f"{path}.sha256")
        resolved = _resolve_portable_path(path, roots)
        previous_path = seen_files.get(resolved)
        if previous_path is not None:
            raise AssetClosureError(
                "asset closure maps multiple portable paths to one file: "
                f"{previous_path!r}, {path!r}"
            )
        seen_files[resolved] = path
        actual_size, actual_sha256 = _hash_stable_file(resolved)
        if actual_size != size:
            raise AssetClosureError(
                f"asset closure size mismatch for {path!r}: expected {size}, got {actual_size}"
            )
        if actual_sha256 != declared_sha256:
            raise AssetClosureError(
                f"asset closure digest mismatch for {path!r}: "
                f"expected {declared_sha256}, got {actual_sha256}"
            )
        if "snapshot" in kinds:
            snapshot_entries += 1
            if path != stage_path:
                raise AssetClosureError(
                    "asset closure snapshot entry does not match stage_snapshot_path"
                )
            resolved_stage = resolved

    if snapshot_entries != 1 or resolved_stage is None:
        raise AssetClosureError("asset closure must contain exactly one stage snapshot entry")
    if expected_stage_snapshot is not None:
        try:
            expected = Path(expected_stage_snapshot).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise AssetClosureError("expected stage snapshot is missing or inaccessible") from exc
        if resolved_stage != expected:
            raise AssetClosureError(
                f"asset closure stage snapshot {resolved_stage} != expected {expected}"
            )
    return document
