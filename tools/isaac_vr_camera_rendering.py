"""RECORD-only suspension of the three dataset render products.

Compatibility boundary: Isaac Lab 17.0.2, source ae37b028 / materialization
0c2e2c64, Isaac Sim 6.1 / Kit 110.3, Replicator 1.13.36. Camera exposes no
public render-resource accessor: only ``Camera._render_data`` is private here.
Its IsaacRtxRenderData supplies public spec, product and annotator handles.
Hydra updates_enabled, drawable events and Annotator.detach/is_attached are
public APIs. Replicator 1.13.36 leaves is_attached stale after detach: get_node
raises AnnotatorRegistryError when its graph node is no longer bound. Retain
resources for normal Camera.reset/destructor ownership;
never clean up the shared renderer or enumerate viewport/XR render products.
"""

from __future__ import annotations

from typing import Any


ROLES = ("left_wrist", "right_wrist", "scene")


class DatasetCameraSuspension:
    """Suspend once, then fail closed on renderer/readback/frame activity."""

    def __init__(self, cameras: dict[str, Any], stage: Any, *, reset_epoch: int) -> None:
        if set(cameras) != set(ROLES) or len({id(c) for c in cameras.values()}) != 3:
            raise RuntimeError("Expected exactly three distinct canonical dataset cameras")
        self.cameras = cameras
        self.stage = stage
        self.resources = {role: camera._render_data for role, camera in cameras.items()}
        paths = [str(data.render_product.path) for data in self.resources.values()]
        if len(set(paths)) != 3:
            raise RuntimeError("Dataset cameras must own distinct render products")
        self.subscriptions: list[Any] = []
        self.report: dict[str, Any] = {
            "roles": {}, "control_steps_checked": 0, "reset_epoch": reset_epoch,
            "hydra_drawable_events_after_suspension": dict.fromkeys(ROLES, 0),
            "hydra_last_frame_number": dict.fromkeys(ROLES),
        }
        # Inspect all bindings before touching any resource. No global renderer state.
        before = {role: self._state(role) for role in ROLES}
        for role in ROLES:
            data = self.resources[role]
            data.render_product.hydra_texture.updates_enabled = False
            for annotator in data.annotators.values():
                if self._annotator_active(annotator):
                    annotator.detach([data.render_product.path])
            self.report["roles"][role] = {"before": before[role], "after": self._state(role)}
        self.check(control_steps=0, reset_epoch=reset_epoch)
        self._watch_hydra()

    def _state(self, role: str) -> dict[str, Any]:
        data = self.resources[role]
        if self.cameras[role]._render_data is not data:
            raise RuntimeError(f"{role}: camera render resources replaced after suspension")
        paths = data.spec.camera_prim_paths
        if len(paths) != 1:
            raise RuntimeError(f"{role}: expected a single camera prim")
        prim = self.stage.GetPrimAtPath(paths[0])
        product = data.render_product
        if not prim.IsValid() or prim.GetTypeName() != "Camera":
            raise RuntimeError(f"{role}: camera prim missing or changed")
        if not self.stage.GetPrimAtPath(product.path).IsValid():
            raise RuntimeError(f"{role}: render product missing")
        return {
            "role": role, "camera_prim_path": str(paths[0]), "camera_prim_exists": True,
            "render_product_path": str(product.path), "render_product_exists": True,
            "hydra_texture": product.hydra_texture.get_name(),
            "updates_enabled": bool(product.hydra_texture.updates_enabled),
            "annotators": {name: self._annotator_active(a) for name, a in data.annotators.items()},
            "annotator_is_attached_property": {
                name: bool(a.is_attached) for name, a in data.annotators.items()
            },
            "camera_frame": [int(v) for v in self.cameras[role].frame.torch.tolist()],
        }

    @staticmethod
    def _annotator_active(annotator: Any) -> bool:
        from omni.replicator.core.scripts.annotators import AnnotatorRegistryError  # type: ignore[import-not-found]

        try:
            return bool(annotator.get_node().is_valid())
        except AnnotatorRegistryError:
            return False

    def _watch_hydra(self) -> None:
        from carb.eventdispatcher import get_eventdispatcher  # type: ignore[import-not-found]
        import omni.hydratexture  # type: ignore[import-not-found]

        for role, data in self.resources.items():
            texture = data.render_product.hydra_texture

            def observed(event, role=role, texture=texture):
                self.report["hydra_drawable_events_after_suspension"][role] += 1
                # Kit requires a live event result_handle here. The default
                # handle is not a per-product counter and can segfault after
                # suspension; never query frame metadata outside this callback.
                self.report["hydra_last_frame_number"][role] = texture.get_frame_info(
                    event["result_handle"]
                ).get("frame_number")

            self.subscriptions.append(get_eventdispatcher().observe_event(
                observer_name=f"record_dataset_suspension_{role}",
                event_name=omni.hydratexture.GLOBAL_EVENT_DRAWABLE_CHANGED,
                on_event=observed, filter=texture.get_event_key(),
            ))

    def check(self, *, control_steps: int, reset_epoch: int) -> dict[str, Any]:
        """Read counters/flags only, never camera.data or an annotator buffer."""
        for role in ROLES:
            current = self._state(role)
            entry = self.report["roles"][role]
            previous = entry.get("latest", entry["after"])
            reset = reset_epoch != self.report["reset_epoch"]
            expected_frame = [0] if reset else previous["camera_frame"]
            if (current["updates_enabled"] or any(current["annotators"].values())
                    or current["camera_frame"] != expected_frame
                    or self.report["hydra_drawable_events_after_suspension"][role]):
                raise RuntimeError(f"{role}: dataset camera rendering/readback resumed: {current}; "
                                   f"drawable_events={self.report['hydra_drawable_events_after_suspension']}")
            self.report["roles"][role]["latest"] = current
        self.report["control_steps_checked"] = control_steps
        self.report["reset_epoch"] = reset_epoch
        return self.report

    def close(self) -> None:
        """Release observers only; Camera retains resource teardown ownership."""
        for subscription in self.subscriptions:
            subscription.reset()
        self.subscriptions.clear()
