"""Focused adapter regressions; native Hydra/reset behavior needs later Kit validation."""

import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from tools.isaac_vr_camera_rendering import ROLES, suspend_dataset_camera_rendering


@pytest.fixture
def resources(monkeypatch):
    class AnnotatorRegistryError(Exception):
        pass

    module = ModuleType("omni.replicator.core.scripts.annotators")
    module.AnnotatorRegistryError = AnnotatorRegistryError
    monkeypatch.setitem(sys.modules, module.__name__, module)

    class Annotator:
        is_attached = True  # The pinned implementation leaves this stale.

        def __init__(self, path):
            self.path = path
            self.detached = False

        def detach(self, paths):
            assert paths == [self.path]
            self.detached = True

        def get_node(self):
            if self.detached:
                raise AnnotatorRegistryError()
            return NS(is_valid=lambda: True)

    paths = {role: f"/World/{role}" for role in ROLES}
    prims = {}
    cameras = {}
    # An unrelated operator resource must survive even though it shares the stage.
    for role in (*ROLES, "operator_xr"):
        path = f"/Render/{role}"
        cameras[role] = NS(
            _render_data=NS(
                spec=NS(camera_prim_paths=[f"/World/{role}"]),
                render_product=NS(path=path, hydra_texture=NS(updates_enabled=True)),
                annotators={"rgba": Annotator(path)},
            )
        )
        prims[f"/World/{role}"] = NS(IsValid=lambda: True, GetTypeName=lambda: "Camera")
        prims[path] = NS(IsValid=lambda: True)
    return cameras, NS(GetPrimAtPath=prims.__getitem__), paths, prims


def test_suspend_exact_dataset_products_preserving_objects_prims_and_xr(resources):
    cameras, stage, paths, prims = resources
    original_prims = dict(prims)
    original_resources = {role: camera._render_data for role, camera in cameras.items()}
    suspend_dataset_camera_rendering({r: cameras[r] for r in ROLES}, stage, paths)
    for role in ROLES:
        data = cameras[role]._render_data
        assert data is original_resources[role]
        assert not data.render_product.hydra_texture.updates_enabled
        assert data.annotators["rgba"].detached
        assert data.annotators["rgba"].is_attached  # Not used as proof of binding.
    xr = cameras["operator_xr"]._render_data
    assert xr.render_product.hydra_texture.updates_enabled
    assert not xr.annotators["rgba"].detached
    assert prims == original_prims


@pytest.mark.parametrize(
    "fault", ["missing_role", "extra_role", "same_camera", "same_product", "wrong_prim"]
)
def test_bad_bindings_rejected_before_any_suspension(resources, fault):
    cameras, stage, paths, _ = resources
    selected = {r: cameras[r] for r in ROLES}
    if fault == "missing_role":
        del selected["scene"]
    elif fault == "extra_role":
        selected["operator_xr"] = cameras["operator_xr"]
    elif fault == "same_camera":
        selected["scene"] = selected["left_wrist"]
    elif fault == "same_product":
        selected["scene"]._render_data.render_product = selected[
            "left_wrist"
        ]._render_data.render_product
    else:
        selected["scene"]._render_data.spec.camera_prim_paths = ["/World/operator_xr"]
    with pytest.raises(RuntimeError):
        suspend_dataset_camera_rendering(selected, stage, paths)
    assert all(
        c._render_data.render_product.hydra_texture.updates_enabled for c in cameras.values()
    )


def test_still_bound_reader_fails_startup(resources):
    cameras, stage, paths, _ = resources
    cameras["scene"]._render_data.annotators["rgba"].detach = lambda paths: None
    with pytest.raises(RuntimeError, match="annotator is still bound"):
        suspend_dataset_camera_rendering({r: cameras[r] for r in ROLES}, stage, paths)
