"""Pure-Python tests for fail-closed USD asset dependency closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.isaac_vr_asset_closure import (
    AssetClosureError,
    SCHEMA_VERSION,
    build_asset_closure_manifest,
    verify_asset_closure_manifest,
)


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _provider(*, layers=(), assets=(), unresolved=()):
    def provide(_snapshot: str):
        return layers, assets, unresolved

    return provide


def test_manifest_is_complete_portable_deterministic_and_json_serializable(tmp_path: Path):
    snapshot = _write(tmp_path / "episode" / "stage_snapshot.usd", b"#usda 1.0\n")
    layer = _write(tmp_path / "scene" / "task.usda", b"task")
    texture = _write(tmp_path / "assets" / "table color.png", b"pixels")
    provider = _provider(
        layers=[SimpleNamespace(realPath=str(layer)), SimpleNamespace(realPath=str(snapshot))],
        assets=[SimpleNamespace(resolvedPath=str(texture)), str(layer)],
    )

    roots = {
        "recording": snapshot.parent,
        "scene": tmp_path / "scene",
        "assets": tmp_path / "assets",
    }
    first = build_asset_closure_manifest(
        snapshot, portable_roots=roots, dependency_provider=provider
    )
    second = build_asset_closure_manifest(
        snapshot, portable_roots=dict(reversed(tuple(roots.items()))), dependency_provider=provider
    )

    assert first == second
    assert json.loads(json.dumps(first, sort_keys=True)) == first
    assert first["schema_version"] == SCHEMA_VERSION
    assert first["stage_snapshot_path"] == "recording/stage_snapshot.usd"
    assert first["entry_count"] == 3
    assert first["entries"] == [
        {
            "path": "assets/table color.png",
            "kinds": ["asset"],
            "size_bytes": 6,
            "sha256": hashlib.sha256(b"pixels").hexdigest(),
        },
        {
            "path": "recording/stage_snapshot.usd",
            "kinds": ["layer", "snapshot"],
            "size_bytes": 10,
            "sha256": hashlib.sha256(b"#usda 1.0\n").hexdigest(),
        },
        {
            "path": "scene/task.usda",
            "kinds": ["asset", "layer"],
            "size_bytes": 4,
            "sha256": hashlib.sha256(b"task").hexdigest(),
        },
    ]
    assert len(first["asset_closure_sha256"]) == 64
    assert all(not Path(entry["path"]).is_absolute() for entry in first["entries"])
    assert str(tmp_path) not in json.dumps(first)


def test_aggregate_changes_for_content_kind_and_portable_path(tmp_path: Path):
    snapshot = _write(tmp_path / "stage.usd", b"stage")
    asset = _write(tmp_path / "asset.bin", b"one")
    one = build_asset_closure_manifest(
        snapshot,
        dependency_provider=_provider(assets=[asset]),
    )
    asset.write_bytes(b"two")
    two = build_asset_closure_manifest(
        snapshot,
        dependency_provider=_provider(assets=[asset]),
    )
    assert one["asset_closure_sha256"] != two["asset_closure_sha256"]

    as_layer = build_asset_closure_manifest(
        snapshot,
        dependency_provider=_provider(layers=[asset]),
    )
    assert two["asset_closure_sha256"] != as_layer["asset_closure_sha256"]

    renamed_root = build_asset_closure_manifest(
        snapshot,
        portable_roots={"bundle": tmp_path},
        dependency_provider=_provider(assets=[asset]),
    )
    assert as_layer["asset_closure_sha256"] != renamed_root["asset_closure_sha256"]


@pytest.mark.parametrize("missing", ["layer", "asset"])
def test_missing_dependencies_fail_closed(tmp_path: Path, missing: str):
    snapshot = _write(tmp_path / "stage.usd", b"stage")
    path = tmp_path / "missing.usd"
    kwargs = {f"{missing}s": [path]}
    with pytest.raises(AssetClosureError, match="missing or inaccessible"):
        build_asset_closure_manifest(snapshot, dependency_provider=_provider(**kwargs))


def test_unresolved_references_fail_before_manifest(tmp_path: Path):
    snapshot = _write(tmp_path / "stage.usd", b"stage")
    with pytest.raises(AssetClosureError, match="unresolved references.*missing.png"):
        build_asset_closure_manifest(
            snapshot,
            dependency_provider=_provider(unresolved=["missing.png", "missing.png"]),
        )


@pytest.mark.parametrize("dependency", ["https://example.invalid/a.usd", "omniverse://host/a.usd"])
def test_nonlocal_dependency_uris_fail_closed(tmp_path: Path, dependency: str):
    snapshot = _write(tmp_path / "stage.usd", b"stage")
    with pytest.raises(AssetClosureError, match="not a portable local file"):
        build_asset_closure_manifest(
            snapshot,
            dependency_provider=_provider(assets=[dependency]),
        )


def test_dependency_outside_declared_roots_fails_closed(tmp_path: Path):
    snapshot = _write(tmp_path / "recording" / "stage.usd", b"stage")
    dependency = _write(tmp_path / "external" / "asset.bin", b"asset")
    with pytest.raises(AssetClosureError, match="outside declared portable roots"):
        build_asset_closure_manifest(
            snapshot,
            dependency_provider=_provider(assets=[dependency]),
        )

    manifest = build_asset_closure_manifest(
        snapshot,
        portable_roots={"recording": snapshot.parent, "assets": dependency.parent},
        dependency_provider=_provider(assets=[dependency]),
    )
    assert [entry["path"] for entry in manifest["entries"]] == [
        "assets/asset.bin",
        "recording/stage.usd",
    ]


def test_unreadable_dependency_fails_closed(monkeypatch, tmp_path: Path):
    snapshot = _write(tmp_path / "stage.usd", b"stage")
    dependency = _write(tmp_path / "asset.bin", b"asset")
    original_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path == dependency:
            raise PermissionError("denied by test")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    with pytest.raises(AssetClosureError, match="dependency is unreadable"):
        build_asset_closure_manifest(
            snapshot,
            dependency_provider=_provider(assets=[dependency]),
        )


def test_symlink_escape_is_checked_after_resolution(tmp_path: Path):
    recording = tmp_path / "recording"
    snapshot = _write(recording / "stage.usd", b"stage")
    external = _write(tmp_path / "external" / "asset.bin", b"asset")
    recording.mkdir(exist_ok=True)
    link = recording / "linked.bin"
    link.symlink_to(external)
    with pytest.raises(AssetClosureError, match="outside declared portable roots"):
        build_asset_closure_manifest(
            snapshot,
            dependency_provider=_provider(assets=[link]),
        )


def test_case_insensitive_portable_path_collision_fails_closed(tmp_path: Path):
    snapshot = _write(tmp_path / "stage.usd", b"stage")
    upper = _write(tmp_path / "Asset.bin", b"upper")
    lower = _write(tmp_path / "asset.bin", b"lower")
    with pytest.raises(AssetClosureError, match="collide case-insensitively"):
        build_asset_closure_manifest(
            snapshot,
            dependency_provider=_provider(assets=[upper, lower]),
        )


@pytest.mark.parametrize("name", ["Bad", "two/parts", "..", "", "white space"])
def test_invalid_portable_root_names_fail_closed(tmp_path: Path, name: str):
    snapshot = _write(tmp_path / "stage.usd", b"stage")
    with pytest.raises(AssetClosureError, match="invalid portable root name"):
        build_asset_closure_manifest(
            snapshot,
            portable_roots={name: tmp_path},
            dependency_provider=_provider(),
        )


def test_layer_and_asset_objects_without_resolved_paths_fail_closed(tmp_path: Path):
    snapshot = _write(tmp_path / "stage.usd", b"stage")
    with pytest.raises(AssetClosureError, match="has no local filesystem path"):
        build_asset_closure_manifest(
            snapshot,
            dependency_provider=_provider(assets=[SimpleNamespace(path="")]),
        )


def test_default_provider_import_is_lazy(tmp_path: Path):
    snapshot = _write(tmp_path / "stage.usd", b"stage")
    # Supplying a provider proves core use never needs pxr to be importable.
    manifest = build_asset_closure_manifest(snapshot, dependency_provider=_provider())
    assert manifest["entry_count"] == 1


def _sidecar(tmp_path: Path):
    recording = tmp_path / "recording"
    assets = tmp_path / "assets"
    snapshot = _write(recording / "stage_snapshot.usd", b"stage")
    asset = _write(assets / "texture.png", b"pixels")
    roots = {"recording": recording, "assets": assets}
    manifest = build_asset_closure_manifest(
        snapshot,
        portable_roots=roots,
        dependency_provider=_provider(assets=[asset]),
    )
    path = recording / "asset_closure.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, snapshot, asset, roots, manifest


def _resign(manifest):
    payload = dict(manifest)
    payload.pop("asset_closure_sha256", None)
    manifest["asset_closure_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def test_verify_rehashes_every_entry_and_accepts_explicit_relocation(tmp_path: Path):
    path, snapshot, _, roots, manifest = _sidecar(tmp_path / "source")
    assert verify_asset_closure_manifest(
        path,
        portable_roots=roots,
        expected_stage_snapshot=snapshot,
    ) == manifest

    relocated = tmp_path / "relocated"
    relocated_recording = relocated / "recording"
    relocated_assets = relocated / "assets"
    relocated_snapshot = _write(relocated_recording / snapshot.name, snapshot.read_bytes())
    _write(relocated_assets / "texture.png", b"pixels")
    relocated_sidecar = relocated_recording / path.name
    relocated_sidecar.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    assert verify_asset_closure_manifest(
        relocated_sidecar,
        portable_roots={"recording": relocated_recording, "assets": relocated_assets},
        expected_stage_snapshot=relocated_snapshot,
    ) == manifest


@pytest.mark.parametrize("target", ["snapshot", "asset"])
def test_verify_rejects_dependency_content_mutation(tmp_path: Path, target: str):
    path, snapshot, asset, roots, _ = _sidecar(tmp_path)
    (snapshot if target == "snapshot" else asset).write_bytes(b"tampered")
    with pytest.raises(AssetClosureError, match="(size|digest) mismatch"):
        verify_asset_closure_manifest(path, portable_roots=roots)


def test_verify_rejects_sidecar_aggregate_mutation(tmp_path: Path):
    path, _, _, roots, manifest = _sidecar(tmp_path)
    manifest["entry_count"] = 99
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssetClosureError, match="aggregate digest mismatch"):
        verify_asset_closure_manifest(path, portable_roots=roots)


def test_verify_requires_every_explicit_root_binding(tmp_path: Path):
    path, _, _, roots, _ = _sidecar(tmp_path)
    with pytest.raises(AssetClosureError, match="unbound root 'assets'"):
        verify_asset_closure_manifest(
            path,
            portable_roots={"recording": roots["recording"]},
        )


def test_verify_rejects_symlink_escape_even_with_valid_signed_sidecar(tmp_path: Path):
    path, _, asset, roots, manifest = _sidecar(tmp_path)
    asset.unlink()
    external = _write(tmp_path / "outside" / "texture.png", b"pixels")
    asset.symlink_to(external)
    with pytest.raises(AssetClosureError, match="escapes root 'assets'"):
        verify_asset_closure_manifest(path, portable_roots=roots)


@pytest.mark.parametrize(
    "malicious_path",
    ["assets/../outside/texture.png", "assets//texture.png", "./assets/texture.png"],
)
def test_verify_rejects_resigned_noncanonical_path(tmp_path: Path, malicious_path: str):
    path, _, _, roots, manifest = _sidecar(tmp_path)
    manifest["entries"][0]["path"] = malicious_path
    _resign(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssetClosureError, match="invalid portable dependency path"):
        verify_asset_closure_manifest(path, portable_roots=roots)


def test_verify_rejects_resigned_non_string_kinds(tmp_path: Path):
    path, _, _, roots, manifest = _sidecar(tmp_path)
    manifest["entries"][0]["kinds"] = [{"asset": True}]
    _resign(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssetClosureError, match="invalid kinds"):
        verify_asset_closure_manifest(path, portable_roots=roots)


def test_verify_rejects_snapshot_identity_mismatch(tmp_path: Path):
    path, _, _, roots, _ = _sidecar(tmp_path)
    other = _write(tmp_path / "recording" / "other.usd", b"stage")
    with pytest.raises(AssetClosureError, match="!= expected"):
        verify_asset_closure_manifest(
            path,
            portable_roots=roots,
            expected_stage_snapshot=other,
        )
