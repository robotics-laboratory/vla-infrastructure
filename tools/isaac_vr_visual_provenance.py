"""Canonical renderer, camera, and mutable-visual provenance for offline RGB.

The pure validation and canonicalization functions in this module intentionally
do not import Kit or USD.  Production adapters load those APIs lazily after
``AppLauncher`` has initialized Isaac Sim.

The exported USD digest proves byte identity, but it does not say which renderer
or camera contract must consume that stage.  This document binds those inputs
explicitly.  Mutable visual properties are represented by per-property hashes so
large meshes and texture arrays are not duplicated into the recording manifest.
Replay rebuilds the index from the verified stage and requires an exact match.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
import hashlib
import json
import math
from typing import Any


VISUAL_PROVENANCE_SCHEMA = "piper_x_isaac_vr_visual_provenance_v2"
CANONICAL_CAMERA_ROLES = ("left_wrist", "right_wrist", "scene")
TRANSIENT_PRIM_PREFIXES = ("/Render", "/Replicator", "/_xr")

# These settings affect RTX output or the scene submitted to RTX.  Missing
# settings remain explicit entries; an upgrade cannot silently add a new default
# without changing the provenance hash.
RENDERER_SETTING_PATHS = (
    "/app/useFabricSceneDelegate",
    "/renderer/active",
    "/renderer/enabled",
    "/renderer/multiGpu/enabled",
    "/renderer/scenePartitioning/enabled",
    "/rtx/rendermode",
    "/rtx/pathtracing/spp",
    "/rtx/pathtracing/totalSpp",
    "/rtx/post/aa/op",
    "/rtx/post/tonemap/op",
    "/rtx-transient/resourcemanager/texturestreaming/enabled",
)

_VISUAL_PRIM_TYPES = frozenset(
    {
        "BasisCurves",
        "Camera",
        "Capsule",
        "Cone",
        "Cube",
        "Cylinder",
        "GeomSubset",
        "Material",
        "Mesh",
        "Plane",
        "PointInstancer",
        "Points",
        "Shader",
        "Sphere",
    }
)
_VISUAL_ATTRIBUTE_PREFIXES = (
    "camera:",
    "clipping",
    "corner",
    "crease",
    "display",
    "doubleSided",
    "extent",
    "faceVertex",
    "focalLength",
    "focusDistance",
    "fStop",
    "horizontalAperture",
    "inputs:",
    "light:",
    "material:",
    "normals",
    "orientation",
    "outputs:",
    "points",
    "primvars:",
    "projection",
    "purpose",
    "shutter:",
    "subdivisionScheme",
    "verticalAperture",
    "visibility",
    "widths",
    "xformOp:",
    "xformOpOrder",
)
_VISUAL_RELATIONSHIP_PREFIXES = ("material:", "inputs:", "outputs:", "light:")


class VisualProvenanceError(RuntimeError):
    """The renderer or composed visual scene is not reproducibly described."""


def _canonical_value(value: Any) -> Any:
    """Convert a USD/Carb value to strict deterministic JSON data."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise VisualProvenanceError("visual provenance contains a non-finite float")
        # JSON uses the shortest round-trippable representation for Python floats.
        return value
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise VisualProvenanceError("visual provenance mapping keys must be strings")
            result[key] = _canonical_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    asset_path = getattr(value, "path", None)
    if isinstance(asset_path, str):
        return {"asset_path": asset_path}
    if hasattr(value, "tolist"):
        return _canonical_value(value.tolist())
    if isinstance(value, Iterable):
        return [_canonical_value(item) for item in value]
    # Tokens, paths, enums, and scalar Gf values all have stable textual forms.
    text = str(value)
    if not text or text.startswith("<"):
        raise VisualProvenanceError(f"unsupported visual provenance value: {value!r}")
    return {"text": text, "python_type": type(value).__name__}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _is_transient(path: str) -> bool:
    return any(
        path == prefix or path.startswith(prefix + "/") for prefix in TRANSIENT_PRIM_PREFIXES
    )


def _is_visual_attribute(prim_type: str, name: str) -> bool:
    return (
        prim_type in _VISUAL_PRIM_TYPES
        or prim_type.endswith("Light")
        or name.startswith(_VISUAL_ATTRIBUTE_PREFIXES)
    )


def _is_visual_relationship(prim_type: str, name: str) -> bool:
    return (
        prim_type in {"Material", "Shader", "GeomSubset"}
        or prim_type.endswith("Light")
        or name.startswith(_VISUAL_RELATIONSHIP_PREFIXES)
    )


def _attribute_payload(attribute: Any) -> dict[str, Any]:
    samples = []
    if hasattr(attribute, "GetTimeSamples"):
        for time_code in attribute.GetTimeSamples():
            samples.append(
                {
                    "time": _canonical_value(time_code),
                    "value": _canonical_value(attribute.Get(time_code)),
                }
            )
    payload = {
        "default": _canonical_value(attribute.Get()),
        "time_samples": samples,
        "type_name": str(attribute.GetTypeName()) if hasattr(attribute, "GetTypeName") else "",
    }
    return payload


def _property_index(stage: Any) -> list[dict[str, Any]]:
    properties: list[dict[str, Any]] = []
    try:
        prims = list(stage.Traverse())
    except Exception as exc:
        raise VisualProvenanceError("could not traverse the composed USD stage") from exc
    for prim in sorted(prims, key=lambda item: str(item.GetPath())):
        path = str(prim.GetPath())
        if not path.startswith("/"):
            raise VisualProvenanceError(f"non-absolute prim path in visual stage: {path!r}")
        if _is_transient(path):
            continue
        prim_type = str(prim.GetTypeName())
        for attribute in sorted(prim.GetAttributes(), key=lambda item: str(item.GetName())):
            name = str(attribute.GetName())
            if not _is_visual_attribute(prim_type, name):
                continue
            payload = _attribute_payload(attribute)
            properties.append(
                {
                    "kind": "attribute",
                    "name": name,
                    "payload_sha256": _sha256(payload),
                    "prim_path": path,
                    "prim_type": prim_type,
                }
            )
        for relationship in sorted(prim.GetRelationships(), key=lambda item: str(item.GetName())):
            name = str(relationship.GetName())
            if not _is_visual_relationship(prim_type, name):
                continue
            targets = sorted(str(target) for target in relationship.GetTargets())
            properties.append(
                {
                    "kind": "relationship",
                    "name": name,
                    "payload_sha256": _sha256({"targets": targets}),
                    "prim_path": path,
                    "prim_type": prim_type,
                }
            )
    identities = [(item["prim_path"], item["kind"], item["name"]) for item in properties]
    if len(identities) != len(set(identities)):
        raise VisualProvenanceError("composed visual stage contains duplicate property identities")
    return properties


def _camera_entry(stage: Any, role: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    path = spec.get("prim_path")
    resolution = spec.get("resolution")
    if not isinstance(path, str) or not path.startswith("/") or "//" in path:
        raise VisualProvenanceError(f"camera {role} has an invalid absolute prim path")
    if (
        not isinstance(resolution, Sequence)
        or isinstance(resolution, (str, bytes))
        or len(resolution) != 2
        or any(type(value) is not int or value <= 0 for value in resolution)
    ):
        raise VisualProvenanceError(f"camera {role} has an invalid resolution")
    prim = stage.GetPrimAtPath(path)
    if prim is None or (hasattr(prim, "IsValid") and not prim.IsValid()):
        raise VisualProvenanceError(f"camera {role} prim is missing: {path}")
    if str(prim.GetTypeName()) != "Camera":
        raise VisualProvenanceError(f"camera {role} prim is not a USD Camera: {path}")
    attributes = []
    for attribute in sorted(prim.GetAttributes(), key=lambda item: str(item.GetName())):
        payload = _attribute_payload(attribute)
        attributes.append(
            {
                "name": str(attribute.GetName()),
                "payload": payload,
                "payload_sha256": _sha256(payload),
            }
        )
    if not attributes:
        raise VisualProvenanceError(f"camera {role} has no composed attributes: {path}")
    entry = {
        "attributes": attributes,
        "data_type": str(spec.get("data_type", "rgb")),
        "prim_path": path,
        "prim_type": "Camera",
        "resolution": [int(resolution[0]), int(resolution[1])],
        "role": role,
    }
    entry["camera_configuration_sha256"] = _sha256(entry)
    return entry


def _kit_runtime_identity() -> dict[str, Any]:
    try:
        import omni.kit.app
    except ImportError as exc:  # pragma: no cover - requires initialized Isaac environment
        raise VisualProvenanceError("Kit is unavailable while capturing visual provenance") from exc
    app = omni.kit.app.get_app()
    identity: dict[str, Any] = {}
    for name in ("get_version", "get_build_version"):
        method = getattr(app, name, None)
        identity[name.removeprefix("get_")] = str(method()) if callable(method) else None
    return identity


def _kit_setting_reader(path: str) -> Any:
    try:
        import carb.settings
    except ImportError as exc:  # pragma: no cover - requires initialized Isaac environment
        raise VisualProvenanceError("Carb settings are unavailable") from exc
    settings = carb.settings.get_settings()
    try:
        type_code = int(settings.get_type(path))
    except Exception:
        type_code = None
    try:
        value = settings.get(path)
    except Exception as exc:
        raise VisualProvenanceError(f"could not read renderer setting {path}") from exc
    return {"present": value is not None, "type_code": type_code, "value": value}


def build_visual_provenance(
    stage: Any,
    camera_specs: Mapping[str, Mapping[str, Any]],
    *,
    setting_reader: Callable[[str], Any] | None = None,
    runtime_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic semantic index for all offline-RGB inputs."""

    if set(camera_specs) != set(CANONICAL_CAMERA_ROLES):
        raise VisualProvenanceError(
            f"camera specs must contain exactly {list(CANONICAL_CAMERA_ROLES)}"
        )
    reader = setting_reader or _kit_setting_reader
    settings = [
        {"path": path, "state": _canonical_value(reader(path))} for path in RENDERER_SETTING_PATHS
    ]
    cameras = [_camera_entry(stage, role, camera_specs[role]) for role in CANONICAL_CAMERA_ROLES]
    if len({camera["prim_path"] for camera in cameras}) != len(cameras):
        raise VisualProvenanceError("canonical camera roles must use unique prim paths")
    properties = _property_index(stage)
    renderer = {
        "implementation": "RTX",
        "runtime_identity": _canonical_value(runtime_identity or _kit_runtime_identity()),
        "settings": settings,
        "settings_policy": "piper_x_rtx_settings_v1",
    }
    renderer["renderer_configuration_sha256"] = _sha256(renderer)
    document: dict[str, Any] = {
        "camera_roles": cameras,
        "materialization": {
            "annotator": "rgb",
            "capture_driver": "kit_app_update",
            "camera_role_order": list(CANONICAL_CAMERA_ROLES),
            "materialization_revision": "piper_x_offline_rgb_materializer_v1",
            "orchestrator_reference_time_gate": False,
            "render_product_lifecycle": "persistent_per_role",
            "render_updates_per_frame": 4,
            "warmup_updates": 3,
        },
        "mutable_visual_state": {
            "excluded_transient_prefixes": list(TRANSIENT_PRIM_PREFIXES),
            "property_count": len(properties),
            "properties": properties,
        },
        "renderer": renderer,
        "schema": VISUAL_PROVENANCE_SCHEMA,
    }
    document["visual_provenance_sha256"] = _sha256(document)
    verify_visual_provenance(document)
    return document


def verify_visual_provenance(document: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the document's structure and self-hash without importing Kit."""

    if not isinstance(document, Mapping) or document.get("schema") != VISUAL_PROVENANCE_SCHEMA:
        raise VisualProvenanceError("unsupported visual provenance schema")
    digest = document.get("visual_provenance_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise VisualProvenanceError("visual provenance requires a SHA-256 self-hash")
    unsigned = dict(document)
    unsigned.pop("visual_provenance_sha256", None)
    actual = _sha256(unsigned)
    if digest != actual:
        raise VisualProvenanceError(
            f"visual provenance self-hash mismatch: expected {digest}, got {actual}"
        )
    cameras = document.get("camera_roles")
    if not isinstance(cameras, list) or [item.get("role") for item in cameras] != list(
        CANONICAL_CAMERA_ROLES
    ):
        raise VisualProvenanceError("visual provenance camera role order is invalid")
    paths = [item.get("prim_path") for item in cameras]
    if any(not isinstance(path, str) or not path.startswith("/") for path in paths):
        raise VisualProvenanceError("visual provenance has an invalid camera path")
    if len(paths) != len(set(paths)):
        raise VisualProvenanceError("visual provenance camera paths are not unique")
    for camera in cameras:
        camera_digest = camera.get("camera_configuration_sha256")
        if not isinstance(camera_digest, str) or len(camera_digest) != 64:
            raise VisualProvenanceError("visual provenance camera has no configuration hash")
        unsigned_camera = dict(camera)
        unsigned_camera.pop("camera_configuration_sha256", None)
        if camera_digest != _sha256(unsigned_camera):
            raise VisualProvenanceError("visual provenance camera configuration hash mismatch")
    renderer = document.get("renderer")
    settings = renderer.get("settings") if isinstance(renderer, Mapping) else None
    if not isinstance(settings, list) or [entry.get("path") for entry in settings] != list(
        RENDERER_SETTING_PATHS
    ):
        raise VisualProvenanceError("visual provenance renderer settings policy is incomplete")
    renderer_digest = renderer.get("renderer_configuration_sha256")
    if not isinstance(renderer_digest, str) or len(renderer_digest) != 64:
        raise VisualProvenanceError("visual provenance renderer has no configuration hash")
    unsigned_renderer = dict(renderer)
    unsigned_renderer.pop("renderer_configuration_sha256", None)
    if renderer_digest != _sha256(unsigned_renderer):
        raise VisualProvenanceError("visual provenance renderer configuration hash mismatch")
    materialization = document.get("materialization")
    if (
        not isinstance(materialization, Mapping)
        or materialization.get("materialization_revision") != "piper_x_offline_rgb_materializer_v1"
    ):
        raise VisualProvenanceError("visual provenance materialization revision is invalid")
    visuals = document.get("mutable_visual_state")
    if not isinstance(visuals, Mapping):
        raise VisualProvenanceError("visual provenance mutable state is invalid")
    properties = visuals.get("properties")
    if not isinstance(properties, list) or visuals.get("property_count") != len(properties):
        raise VisualProvenanceError("visual provenance property index count is invalid")
    identities = []
    for item in properties:
        if not isinstance(item, Mapping):
            raise VisualProvenanceError("visual provenance property entry is not an object")
        identities.append((item.get("prim_path"), item.get("kind"), item.get("name")))
        property_digest = item.get("payload_sha256")
        if not isinstance(property_digest, str) or len(property_digest) != 64:
            raise VisualProvenanceError("visual provenance property has no SHA-256 digest")
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise VisualProvenanceError("visual provenance properties are not canonical and unique")
    return dict(document)


def assert_visual_provenance_matches(
    recorded: Mapping[str, Any],
    stage: Any,
    *,
    setting_reader: Callable[[str], Any] | None = None,
    runtime_identity: Mapping[str, Any] | None = None,
) -> None:
    """Rebuild provenance from a replay stage and require exact equivalence."""

    verified = verify_visual_provenance(recorded)
    camera_specs = {
        str(entry["role"]): {
            "data_type": entry["data_type"],
            "prim_path": entry["prim_path"],
            "resolution": entry["resolution"],
        }
        for entry in verified["camera_roles"]
    }
    rebuilt = build_visual_provenance(
        stage,
        camera_specs,
        setting_reader=setting_reader,
        runtime_identity=runtime_identity,
    )
    if rebuilt["visual_provenance_sha256"] != verified["visual_provenance_sha256"]:
        mismatches: list[str] = []
        for section in ("camera_roles", "materialization", "renderer"):
            if rebuilt[section] != verified[section]:
                mismatches.append(
                    f"{section}: recorded={_sha256(verified[section])} "
                    f"replayed={_sha256(rebuilt[section])}"
                )
        recorded_visuals = verified["mutable_visual_state"]
        replayed_visuals = rebuilt["mutable_visual_state"]
        if recorded_visuals != replayed_visuals:
            recorded_properties = {
                (item["prim_path"], item["kind"], item["name"]): item["payload_sha256"]
                for item in recorded_visuals["properties"]
            }
            replayed_properties = {
                (item["prim_path"], item["kind"], item["name"]): item["payload_sha256"]
                for item in replayed_visuals["properties"]
            }
            changed = sorted(
                key
                for key in set(recorded_properties) | set(replayed_properties)
                if recorded_properties.get(key) != replayed_properties.get(key)
            )
            mismatches.append(
                "mutable_visual_state: "
                f"recorded={_sha256(recorded_visuals)} replayed={_sha256(replayed_visuals)}; "
                f"changed_properties={changed[:8]!r}"
            )
        raise VisualProvenanceError(
            "opened replay stage, cameras, or RTX runtime do not match recording provenance; "
            + "; ".join(mismatches)
        )
