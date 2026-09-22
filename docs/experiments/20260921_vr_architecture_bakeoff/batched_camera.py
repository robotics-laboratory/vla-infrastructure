"""Experiment-only adapter for one three-view Isaac Lab ``Camera`` owner."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import numpy as np


ROLES = ("left_wrist", "right_wrist", "scene")


def _tensor(value):
    return getattr(value, "torch", value)


class _RoleCameraData:
    """A one-row public view over the owner's explicit batch dimension."""

    def __init__(self, camera: "BatchedCameraRole") -> None:
        self._camera = camera

    def _slice(self, value):
        index = self._camera.batch_index
        return _tensor(value)[index : index + 1]

    @property
    def output(self):
        return {name: self._slice(value) for name, value in self._camera.owner.data.output.items()}

    @property
    def pos_w(self):
        return self._slice(self._camera.owner.data.pos_w)

    @property
    def quat_w_world(self):
        return self._slice(self._camera.owner.data.quat_w_world)

    @property
    def quat_w_opengl(self):
        return self._slice(self._camera.owner.data.quat_w_opengl)

    @property
    def intrinsic_matrices(self):
        return self._slice(self._camera.owner.data.intrinsic_matrices)


class BatchedCameraRole:
    """Compatibility view only; this is deliberately not a ``Camera`` sensor."""

    def __init__(self, role: str, path: str, cfg) -> None:
        self.role = role
        self.path = path
        self.cfg = cfg
        self.owner = None
        self.data = _RoleCameraData(self)

    @property
    def batch_index(self) -> int:
        if self.owner is None or not self.owner.is_initialized:
            raise RuntimeError(f"{self.role}: batched Camera owner is not initialized")
        paths = tuple(str(camera.GetPath()) for camera in self.owner._sensor_prims)
        render_paths = tuple(self.owner._render_data.spec.camera_prim_paths)
        if paths != render_paths:
            raise RuntimeError("Camera view order differs from tiled render-product order")
        if set(paths) != set(self.owner._batched_expected_paths):
            raise RuntimeError(f"Unexpected batched camera paths: {paths!r}")
        return paths.index(self.path)

    @property
    def frame(self):
        index = self.batch_index
        return _tensor(self.owner.frame)[index : index + 1]

    @property
    def _data_generation(self):
        return self.owner._data_generation

    @property
    def _data_generation_last_update(self):
        return self.owner._data_generation_last_update

    def reset(self) -> None:
        self.owner.reset(env_ids=[self.batch_index])

    def set_world_poses_from_view(self, eyes, targets) -> None:
        self.owner.set_world_poses_from_view(eyes, targets, env_ids=[self.batch_index])


@dataclass(frozen=True)
class _CameraIdentity:
    role: str
    frame: int
    data_generation: int


@dataclass(frozen=True)
class _ObservationCapture:
    producer: Any
    capture_cycle: int
    cameras: tuple[_CameraIdentity, ...]
    state: tuple[float, ...]
    eligible: bool


class BatchedThreeCameraCapture:
    """One extraction and one immutable role projection from a three-view batch."""

    def __init__(self, cameras, boundary, read_state) -> None:
        if tuple(cameras) != ROLES:
            raise ValueError("Expected ordered left_wrist, right_wrist, scene")
        owners = {id(camera.owner) for camera in cameras.values()}
        if len(owners) != 1:
            raise ValueError("Batched capture requires exactly one Camera owner")
        self.cameras = cameras
        self.owner = next(iter(cameras.values())).owner
        self.boundary = boundary
        self.read_state = read_state
        self.successful_capture_cycle = 0
        self.failed_attempts = 0
        self.last_error = None
        self._latest = None
        self._buffer = None
        self._indices = None

    def invalidate(self) -> None:
        self._latest = None
        self._buffer = None
        self._indices = None

    def _output(self):
        if self.owner._data_generation_last_update != self.owner._data_generation:
            raise RuntimeError("Batched Camera output has no completed producer generation")
        output = self.owner.data.output
        value = output.get("rgba", output.get("rgb"))
        if value is None or tuple(value.shape) not in ((3, 480, 640, 3), (3, 480, 640, 4)):
            raise RuntimeError(
                f"Batched Camera output missing or wrong shape: {getattr(value, 'shape', None)}"
            )
        if str(_tensor(value).dtype).split(".")[-1] != "uint8":
            raise RuntimeError("Batched Camera output must be uint8")
        return value

    def capture(self, dt: float, *, eligible: bool = True):
        self.invalidate()
        try:
            producer = self.boundary()
            state_step, state = self.read_state()
            if state_step != producer.physics_step or self.boundary() != producer:
                raise RuntimeError("Measured state does not belong to batched capture boundary")
            if len(state) != 14 or not np.isfinite(state).all():
                raise RuntimeError("Invalid measured state")
            previous_frames = _tensor(self.owner.frame).detach().clone()
            generation = self.owner._data_generation
            self.owner.update(dt, force_recompute=True)
            current_frames = _tensor(self.owner.frame).detach().clone()
            if not bool((current_frames == previous_frames + 1).all()):
                raise RuntimeError("Batched Camera views did not advance atomically exactly once")
            if self.owner._data_generation != generation + 1:
                raise RuntimeError("Batched Camera generation did not advance exactly once")
            buffer = self._output()
            indices = {role: camera.batch_index for role, camera in self.cameras.items()}
            if len(set(indices.values())) != 3:
                raise RuntimeError(f"Duplicate batched role indices: {indices}")
            identities = tuple(
                _CameraIdentity(
                    role, int(current_frames[index].item()), self.owner._data_generation
                )
                for role, index in indices.items()
            )
            if self.boundary() != producer:
                raise RuntimeError("Producer changed during batched extraction")
            self._buffer = buffer
            self._indices = indices
            capture = _ObservationCapture(
                producer, self.successful_capture_cycle + 1, identities, state, eligible
            )
            self._latest = capture
            self._check_current(capture)
            self.successful_capture_cycle += 1
            self.last_error = None
            return capture
        except Exception as error:
            self.invalidate()
            self.failed_attempts += 1
            self.last_error = str(error)
            return None

    def _check_current(self, capture) -> None:
        if self.boundary() != capture.producer:
            raise RuntimeError("Batched capture is no longer at its producer boundary")
        frames = _tensor(self.owner.frame)
        for identity in capture.cameras:
            if int(frames[self._indices[identity.role]].item()) != identity.frame:
                raise RuntimeError("Batched role frame changed after capture")
            if self.owner._data_generation != identity.data_generation:
                raise RuntimeError("Batched source generation changed after capture")
        if self._output() is not self._buffer:
            raise RuntimeError("Batched Camera buffer replaced after capture")

    def latest(self, *, require_eligible: bool = True):
        if self._latest is None:
            raise RuntimeError(self.last_error or "No successful batched observation capture")
        self._check_current(self._latest)
        if require_eligible and not self._latest.eligible:
            raise RuntimeError("Startup settling is not an eligible observation")
        return self._latest

    def freeze(self):
        capture = self.latest()
        batch = _tensor(self._buffer)
        result = {"observation.state": np.asarray(capture.state, dtype=np.float32)}
        for role in ROLES:
            rgb = batch[self._indices[role], ..., :3].detach().cpu().numpy()
            result[f"observation.images.{role}"] = np.array(rgb, dtype=np.uint8, copy=True)
        self._check_current(capture)
        return result


class BatchedCameraFactory:
    """Collect three canonical cfgs, then construct one genuine upstream Camera."""

    def __init__(self, camera_type) -> None:
        self._camera_type = camera_type
        self._roles = []

    @staticmethod
    def _spawn(cfg) -> None:
        import torch
        import isaaclab.sim as sim_utils
        from isaaclab.utils.math import convert_camera_frame_orientation_convention

        target = cfg.spawn.spawn_path or cfg.prim_path
        if sim_utils.find_first_matching_prim(target) is not None:
            raise RuntimeError(f"Experiment camera prim already exists: {target}")
        if cfg.spawn.vertical_aperture is None:
            cfg.spawn.vertical_aperture = cfg.spawn.horizontal_aperture * cfg.height / cfg.width
        rotation = torch.tensor(cfg.offset.rot, dtype=torch.float32).unsqueeze(0)
        rotation = (
            convert_camera_frame_orientation_convention(
                rotation, origin=cfg.offset.convention, target="opengl"
            )[0]
            .cpu()
            .numpy()
        )
        cfg.spawn.func(target, cfg.spawn, translation=cfg.offset.pos, orientation=rotation)

    def __call__(self, cfg):
        index = len(self._roles)
        if index >= len(ROLES):
            raise RuntimeError("Unexpected fourth Camera construction in batched experiment")
        role = ROLES[index]
        cfg = cfg.copy()
        path = str(cfg.prim_path)
        self._spawn(cfg)
        proxy = BatchedCameraRole(role, path, cfg)
        self._roles.append(proxy)
        if len(self._roles) == len(ROLES):
            parent_paths = [path.rsplit("/", 1)[0] for path in (item.path for item in self._roles)]
            leaf_names = [path.rsplit("/", 1)[1] for path in (item.path for item in self._roles)]
            parent_expr = "/(?:" + "|".join(re.escape(path[1:]) for path in parent_paths) + ")"
            leaf_expr = "(?:" + "|".join(dict.fromkeys(map(re.escape, leaf_names))) + ")"
            batch_cfg = cfg.copy()
            batch_cfg.prim_path = f"{parent_expr}/{leaf_expr}"
            batch_cfg.spawn = None
            batch_cfg.data_types = ["rgba"]
            owner = self._camera_type(batch_cfg)
            owner._batched_expected_paths = tuple(item.path for item in self._roles)
            owner._batched_role_proxies = tuple(self._roles)
            for item in self._roles:
                item.owner = owner
        return proxy


def install_construction(module, args) -> None:
    """Patch only the experiment process before ``run_vr`` constructs sensors."""
    factory = BatchedCameraFactory(module.Camera)
    module.Camera = factory
    module.ThreeCameraCapture = BatchedThreeCameraCapture


def ownership(env) -> dict[str, Any]:
    roles = tuple(env.scene.sensors[name] for name in ("left_wrist", "right_wrist", "demo_scene"))
    owner = roles[0].owner
    if any(role.owner is not owner for role in roles):
        raise RuntimeError("Role proxies do not share one Camera owner")
    paths = tuple(str(camera.GetPath()) for camera in owner._sensor_prims)
    mapping = {role.role: role.batch_index for role in roles}
    return {
        "camera_instance_count": 1,
        "render_product_count": 1 if owner._render_data.render_product is not None else 0,
        "output_shape": list(_tensor(owner.data.output["rgba"]).shape),
        "camera_paths_in_batch_order": list(paths),
        "role_to_batch_index": mapping,
        "render_product_path": str(owner._render_data.render_product.path),
        "render_spec_camera_paths": list(owner._render_data.spec.camera_prim_paths),
    }
