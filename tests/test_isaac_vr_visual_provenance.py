"""Pure contract tests for offline-RGB visual provenance."""

from __future__ import annotations

import copy

import pytest

from tools.isaac_vr_visual_provenance import (
    CANONICAL_CAMERA_ROLES,
    RENDERER_SETTING_PATHS,
    VisualProvenanceError,
    assert_visual_provenance_matches,
    build_visual_provenance,
    verify_visual_provenance,
)


class FakeAttribute:
    def __init__(self, name, value, *, type_name="token", samples=None):
        self.name = name
        self.value = value
        self.type_name = type_name
        self.samples = dict(samples or {})

    def GetName(self):
        return self.name

    def Get(self, time=None):
        return self.value if time is None else self.samples[time]

    def GetTimeSamples(self):
        return sorted(self.samples)

    def GetTypeName(self):
        return self.type_name


class FakeRelationship:
    def __init__(self, name, targets):
        self.name = name
        self.targets = targets

    def GetName(self):
        return self.name

    def GetTargets(self):
        return list(self.targets)


class FakePrim:
    def __init__(self, path, prim_type, *, attributes=(), relationships=()):
        self.path = path
        self.prim_type = prim_type
        self.attributes = list(attributes)
        self.relationships = list(relationships)

    def GetPath(self):
        return self.path

    def GetTypeName(self):
        return self.prim_type

    def GetAttributes(self):
        return list(self.attributes)

    def GetRelationships(self):
        return list(self.relationships)

    def IsValid(self):
        return True


class FakeStage:
    def __init__(self, prims):
        self.prims = {prim.path: prim for prim in prims}

    def Traverse(self):
        return list(self.prims.values())

    def GetPrimAtPath(self, path):
        return self.prims.get(path)


def fixture_stage(*, focal_length=18.0, color=(0.5, 0.25, 0.125)):
    cameras = [
        FakePrim(
            f"/World/{role}",
            "Camera",
            attributes=(
                FakeAttribute("clippingRange", (0.02, 10.0), type_name="float2"),
                FakeAttribute("focalLength", focal_length, type_name="float"),
                FakeAttribute("projection", "perspective"),
            ),
        )
        for role in CANONICAL_CAMERA_ROLES
    ]
    material = FakePrim(
        "/World/Looks/Task",
        "Shader",
        attributes=(FakeAttribute("inputs:diffuse_color_constant", color, type_name="color3f"),),
        relationships=(FakeRelationship("outputs:surface", ["/World/Looks/Task.out"]),),
    )
    mesh = FakePrim(
        "/World/Object",
        "Mesh",
        attributes=(
            FakeAttribute("points", [(0.0, 0.0, 0.0)], type_name="point3f[]"),
            FakeAttribute("physics:mass", 1.0, type_name="float"),
        ),
        relationships=(FakeRelationship("material:binding", ["/World/Looks/Task"]),),
    )
    transient = FakePrim(
        "/Render/Product_1",
        "RenderProduct",
        attributes=(FakeAttribute("cameraPrim", "/World/left_wrist"),),
    )
    return FakeStage([*cameras, material, mesh, transient])


def camera_specs():
    return {
        role: {
            "prim_path": f"/World/{role}",
            "resolution": (640, 480),
            "data_type": "rgb",
        }
        for role in CANONICAL_CAMERA_ROLES
    }


def setting_reader(path):
    return {"present": True, "type_code": 1, "value": path != "/renderer/multiGpu/enabled"}


def build(stage=None):
    return build_visual_provenance(
        stage or fixture_stage(),
        camera_specs(),
        setting_reader=setting_reader,
        runtime_identity={"version": "106.5", "build_version": "fixture"},
    )


def test_visual_provenance_is_canonical_hashed_and_complete():
    document = build()

    assert verify_visual_provenance(document) == document
    assert [entry["path"] for entry in document["renderer"]["settings"]] == list(
        RENDERER_SETTING_PATHS
    )
    assert [entry["role"] for entry in document["camera_roles"]] == list(
        CANONICAL_CAMERA_ROLES
    )
    assert document["materialization"] == {
        "annotator": "rgb",
        "capture_driver": "kit_app_update",
        "camera_role_order": list(CANONICAL_CAMERA_ROLES),
        "materialization_revision": "piper_x_offline_rgb_materializer_v1",
        "orchestrator_reference_time_gate": False,
        "render_product_lifecycle": "persistent_per_role",
        "render_updates_per_frame": 4,
        "warmup_updates": 3,
    }
    visuals = document["mutable_visual_state"]
    assert "transient_prims_present_at_capture" not in visuals
    assert all(not item["prim_path"].startswith("/Render") for item in visuals["properties"])
    # All authored state on a renderable prim is conservatively bound; this is
    # preferable to silently omitting a future schema's visual input.
    assert any(item["name"] == "physics:mass" for item in visuals["properties"])
    assert any(item["name"] == "points" for item in visuals["properties"])
    assert any(item["name"] == "material:binding" for item in visuals["properties"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["renderer"]["settings"][0]["state"].update(value=False),
        lambda value: value["camera_roles"][0].update(resolution=[1, 1]),
        lambda value: value["mutable_visual_state"]["properties"][0].update(
            payload_sha256="0" * 64
        ),
    ],
)
def test_visual_provenance_self_hash_rejects_manifest_tampering(mutation):
    document = copy.deepcopy(build())
    mutation(document)
    with pytest.raises(VisualProvenanceError, match="self-hash mismatch"):
        verify_visual_provenance(document)


def test_replay_stage_and_renderer_must_match_recording():
    recorded = build()
    assert_visual_provenance_matches(
        recorded,
        fixture_stage(),
        setting_reader=setting_reader,
        runtime_identity={"version": "106.5", "build_version": "fixture"},
    )

    with pytest.raises(VisualProvenanceError, match="do not match"):
        assert_visual_provenance_matches(
            recorded,
            fixture_stage(focal_length=24.0),
            setting_reader=setting_reader,
            runtime_identity={"version": "106.5", "build_version": "fixture"},
        )
    with pytest.raises(VisualProvenanceError, match="do not match"):
        assert_visual_provenance_matches(
            recorded,
            fixture_stage(color=(1.0, 0.0, 0.0)),
            setting_reader=setting_reader,
            runtime_identity={"version": "106.5", "build_version": "fixture"},
        )
    with pytest.raises(VisualProvenanceError, match="do not match"):
        assert_visual_provenance_matches(
            recorded,
            fixture_stage(),
            setting_reader=lambda path: {"present": True, "value": path},
            runtime_identity={"version": "106.5", "build_version": "fixture"},
        )


def test_invalid_camera_contract_and_nonfinite_values_fail_closed():
    specs = camera_specs()
    specs.pop("scene")
    with pytest.raises(VisualProvenanceError, match="exactly"):
        build_visual_provenance(
            fixture_stage(),
            specs,
            setting_reader=setting_reader,
            runtime_identity={"version": "fixture"},
        )
    with pytest.raises(VisualProvenanceError, match="non-finite"):
        build_visual_provenance(
            fixture_stage(focal_length=float("nan")),
            camera_specs(),
            setting_reader=setting_reader,
            runtime_identity={"version": "fixture"},
        )
