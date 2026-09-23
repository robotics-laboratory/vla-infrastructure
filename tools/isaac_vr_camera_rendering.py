"""One-time RECORD suspension; Camera retains all resource/teardown ownership.

Pinned adapter: Isaac Lab 17.0.2 (ae37b028 / materialization 0c2e2c64),
Isaac Sim 6.1 / Kit 110.3, Replicator 1.13.36. Camera has no public
render-resource accessor; its private ``_render_data`` dependency lives here.
Hydra update control and annotator detach/node inspection are public APIs.
No global renderer, viewport/XR enumeration, or per-control observers are used.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


ROLES = ("left_wrist", "right_wrist", "scene")


def suspend_dataset_camera_rendering(
    cameras: Mapping[str, Any], stage: Any, camera_prim_paths: Mapping[str, str]
) -> None:
    """Suspend only initialized dataset products, after snapshot/Recordable setup."""
    from omni.replicator.core.scripts.annotators import AnnotatorRegistryError

    if set(cameras) != set(ROLES) or set(camera_prim_paths) != set(ROLES):
        raise RuntimeError("Expected exactly the three canonical dataset camera roles")
    if len({id(camera) for camera in cameras.values()}) != 3:
        raise RuntimeError("Expected three distinct canonical dataset cameras")
    resources = {role: cameras[role]._render_data for role in ROLES}
    # Resolve and validate every owned binding before changing any resource.
    for role, data in resources.items():
        if data is None or data.spec is None or data.render_product is None:
            raise RuntimeError(f"{role}: dataset camera render resources are not initialized")
        if tuple(map(str, data.spec.camera_prim_paths)) != (camera_prim_paths[role],):
            raise RuntimeError(f"{role}: render product does not match the recorded camera")
        prim = stage.GetPrimAtPath(camera_prim_paths[role])
        if not prim.IsValid() or prim.GetTypeName() != "Camera":
            raise RuntimeError(f"{role}: recorded camera prim is missing or changed")
        if not stage.GetPrimAtPath(data.render_product.path).IsValid():
            raise RuntimeError(f"{role}: dataset render product is missing")
    if len({str(data.render_product.path) for data in resources.values()}) != 3:
        raise RuntimeError("Expected three distinct dataset render products")

    for data in resources.values():
        data.render_product.hydra_texture.updates_enabled = False
        # State-only recording needs no live annotator, including the RGB reader
        # exposed as 'rgba' by this pin. Keep handles for Camera's own teardown.
        for annotator in data.annotators.values():
            annotator.detach([data.render_product.path])

    for role, data in resources.items():
        if data.render_product.hydra_texture.updates_enabled:
            raise RuntimeError(f"{role}: dataset render product did not suspend")
        for name, annotator in data.annotators.items():
            # is_attached stays stale after detach at this pin; check the graph
            # binding once here, never at a control/observation boundary.
            try:
                active = annotator.get_node().is_valid()
            except AnnotatorRegistryError:
                active = False
            if active:
                raise RuntimeError(f"{role}: live {name} annotator is still bound")
