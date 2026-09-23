#!/usr/bin/env python3
"""Moving Fabric/Isaac-Lab-native pose parity qualification.

The numerical core has no Kit dependency.  ``run_live_pose_parity_assay`` is a
bounded diagnostic for the already constructed VR environment and samples the
same upstream Recordables/shared Fabric batch as the production recorder.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import runpy
import sys
from typing import Any

import numpy as np


SCHEMA = "piper_x_fabric_native_pose_parity_v1"
POSITION_THRESHOLD_M = 1.0e-5
ORIENTATION_THRESHOLD_RAD = 2.0e-5
MOVEMENT_POSITION_M = 5.0e-4
MOVEMENT_ORIENTATION_RAD = 1.0e-3


class PoseParityError(RuntimeError):
    """The parity evidence is incomplete or exceeds a fixed threshold."""


@dataclass(frozen=True)
class PoseIdentity:
    group: str
    paths: tuple[str, ...]
    kind: str
    motion: str = "all"
    motion_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.group or not self.paths or len(self.paths) != len(set(self.paths)):
            raise ValueError("pose identity requires a non-empty group and unique paths")
        if self.motion not in {"none", "any", "all"}:
            raise ValueError(f"unsupported motion policy: {self.motion}")
        if not set(self.motion_paths).issubset(self.paths):
            raise ValueError("motion paths must be a subset of identity paths")


@dataclass(frozen=True)
class PoseThresholds:
    position_m: float = POSITION_THRESHOLD_M
    orientation_rad: float = ORIENTATION_THRESHOLD_RAD
    movement_position_m: float = MOVEMENT_POSITION_M
    movement_orientation_rad: float = MOVEMENT_ORIENTATION_RAD

    def __post_init__(self) -> None:
        if min(asdict(self).values()) <= 0.0:
            raise ValueError("all pose parity thresholds must be positive")


def _numpy(value: Any) -> np.ndarray:
    if hasattr(value, "torch"):
        value = value.torch
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def xyzw_to_wxyz(value: Any) -> np.ndarray:
    quaternion = np.asarray(value, dtype=np.float64)
    if quaternion.shape[-1:] != (4,):
        raise PoseParityError(f"native quaternion shape must end in 4, got {quaternion.shape}")
    return quaternion[..., (3, 0, 1, 2)]


def quaternion_error_rad(left: Any, right: Any) -> np.ndarray:
    """Return sign-invariant shortest-arc error for matching ``wxyz`` arrays."""
    a = np.asarray(left, dtype=np.float64)
    b = np.asarray(right, dtype=np.float64)
    if a.shape != b.shape or a.shape[-1:] != (4,):
        raise PoseParityError(f"quaternion shape mismatch: {a.shape} != {b.shape}")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise PoseParityError("non-finite quaternion")
    a_norm = np.linalg.norm(a, axis=-1)
    b_norm = np.linalg.norm(b, axis=-1)
    if np.any(a_norm < 1.0e-12) or np.any(b_norm < 1.0e-12):
        raise PoseParityError("zero-length quaternion")
    unit_a = a / a_norm[..., None]
    unit_b = b / b_norm[..., None]
    dot = np.clip(np.abs(np.sum(unit_a * unit_b, axis=-1)), 0.0, 1.0)
    return 2.0 * np.arccos(dot)


def _pose_arrays(
    frame: Mapping[str, Any], count: int, *, group: str
) -> tuple[np.ndarray, np.ndarray]:
    if "positions" in frame or "orientations" in frame:
        if set(("positions", "orientations")).difference(frame):
            raise PoseParityError(f"{group}: incomplete batched pose channels")
        positions = np.asarray(frame["positions"], dtype=np.float64)
        orientations = np.asarray(frame["orientations"], dtype=np.float64)
    else:
        if set(("position", "orientation")).difference(frame):
            raise PoseParityError(f"{group}: incomplete pose channels")
        positions = np.asarray(frame["position"], dtype=np.float64).reshape(1, 3)
        orientations = np.asarray(frame["orientation"], dtype=np.float64).reshape(1, 4)
    if positions.shape != (count, 3) or orientations.shape != (count, 4):
        raise PoseParityError(
            f"{group}: pose shapes {(positions.shape, orientations.shape)} "
            f"!= {((count, 3), (count, 4))}"
        )
    if not np.isfinite(positions).all() or not np.isfinite(orientations).all():
        raise PoseParityError(f"{group}: non-finite pose")
    # Validate quaternion length before returning the arrays.
    quaternion_error_rad(orientations, orientations)
    return positions, orientations


def compare_pose_frame(
    fabric: Mapping[str, Mapping[str, Any]],
    native: Mapping[str, Mapping[str, Any]],
    identities: Sequence[PoseIdentity],
    *,
    thresholds: PoseThresholds = PoseThresholds(),
) -> dict[str, Any]:
    """Compare one complete Fabric/native boundary and return a fail-closed row."""
    expected = {identity.group for identity in identities}
    if len(expected) != len(identities):
        raise PoseParityError("duplicate pose identity group")
    if set(fabric) != expected or set(native) != expected:
        raise PoseParityError(
            f"pose groups incomplete: fabric={sorted(fabric)} native={sorted(native)} "
            f"expected={sorted(expected)}"
        )
    entities: list[dict[str, Any]] = []
    for identity in identities:
        count = len(identity.paths)
        fabric_pos, fabric_quat = _pose_arrays(fabric[identity.group], count, group=identity.group)
        native_pos, native_quat = _pose_arrays(native[identity.group], count, group=identity.group)
        position_errors = np.linalg.norm(fabric_pos - native_pos, axis=1)
        orientation_errors = quaternion_error_rad(fabric_quat, native_quat)
        for index, path in enumerate(identity.paths):
            position_error = float(position_errors[index])
            orientation_error = float(orientation_errors[index])
            entities.append(
                {
                    "group": identity.group,
                    "kind": identity.kind,
                    "path": path,
                    "position_error_m": position_error,
                    "orientation_error_rad": orientation_error,
                    "passed": bool(
                        position_error <= thresholds.position_m
                        and orientation_error <= thresholds.orientation_rad
                    ),
                }
            )
    return {
        "entities": entities,
        "maximum_position_error_m": max(item["position_error_m"] for item in entities),
        "maximum_orientation_error_rad": max(item["orientation_error_rad"] for item in entities),
        "passed": all(item["passed"] for item in entities),
    }


def qualify_pose_sequence(
    fabric_frames: Sequence[Mapping[str, Mapping[str, Any]]],
    native_frames: Sequence[Mapping[str, Mapping[str, Any]]],
    identities: Sequence[PoseIdentity],
    *,
    thresholds: PoseThresholds = PoseThresholds(),
) -> dict[str, Any]:
    """Qualify parity and declared motion over a multi-boundary integration run."""
    if len(fabric_frames) != len(native_frames) or len(fabric_frames) < 2:
        raise PoseParityError("moving parity requires at least two paired boundaries")
    rows = [
        compare_pose_frame(fabric, native, identities, thresholds=thresholds)
        for fabric, native in zip(fabric_frames, native_frames, strict=True)
    ]
    motion: list[dict[str, Any]] = []
    first = native_frames[0]
    for identity in identities:
        if identity.motion == "none":
            continue
        first_pos, first_quat = _pose_arrays(
            first[identity.group], len(identity.paths), group=identity.group
        )
        selected = identity.motion_paths or identity.paths
        selected_indices = [identity.paths.index(path) for path in selected]
        per_path: list[dict[str, Any]] = []
        for index in selected_indices:
            max_position = 0.0
            max_orientation = 0.0
            for frame in native_frames[1:]:
                position, orientation = _pose_arrays(
                    frame[identity.group], len(identity.paths), group=identity.group
                )
                max_position = max(
                    max_position, float(np.linalg.norm(position[index] - first_pos[index]))
                )
                max_orientation = max(
                    max_orientation,
                    float(quaternion_error_rad(orientation[index], first_quat[index])),
                )
            moved = bool(
                max_position >= thresholds.movement_position_m
                or max_orientation >= thresholds.movement_orientation_rad
            )
            per_path.append(
                {
                    "path": identity.paths[index],
                    "maximum_position_delta_m": max_position,
                    "maximum_orientation_delta_rad": max_orientation,
                    "moved": moved,
                }
            )
        passed = (
            any(item["moved"] for item in per_path)
            if identity.motion == "any"
            else all(item["moved"] for item in per_path)
        )
        motion.append(
            {
                "group": identity.group,
                "kind": identity.kind,
                "policy": identity.motion,
                "entities": per_path,
                "passed": passed,
            }
        )
    report = {
        "schema": SCHEMA,
        "thresholds": asdict(thresholds),
        "sample_count": len(rows),
        "required_groups": [asdict(identity) for identity in identities],
        "rows": rows,
        "motion": motion,
        "maximum_position_error_m": max(row["maximum_position_error_m"] for row in rows),
        "maximum_orientation_error_rad": max(row["maximum_orientation_error_rad"] for row in rows),
    }
    report["passed"] = bool(
        all(row["passed"] for row in rows) and all(item["passed"] for item in motion)
    )
    return report


def _native_articulation(robot: Any, recordable: Any) -> tuple[PoseIdentity, dict[str, np.ndarray]]:
    recorded_paths = tuple(recordable.link_paths)
    if not recorded_paths:
        raise PoseParityError(f"{recordable.group}: articulation has no recorded links")
    body_names = tuple(str(name) for name in robot.body_names)
    if len(body_names) != len(set(body_names)):
        raise PoseParityError(f"{recordable.group}: duplicate native body names")
    body_poses = _numpy(robot.data.body_link_pose_w)
    root_pose = _numpy(robot.data.root_pose_w)
    if body_poses.shape != (1, len(body_names), 7) or root_pose.shape != (1, 7):
        raise PoseParityError(
            f"{recordable.group}: unexpected native articulation shapes "
            f"{body_poses.shape}, {root_pose.shape}"
        )
    index_by_name = {name: index for index, name in enumerate(body_names)}
    # The recordable also includes its grouping Xform (/World/LeftPiper),
    # which is not a PhysX body.  The native articulation root is base_link.
    path_by_name: dict[str, str] = {}
    for path in recorded_paths:
        name = path.rsplit("/", 1)[-1]
        if name in index_by_name:
            if name in path_by_name:
                raise PoseParityError(f"{recordable.group}: duplicate recorded body {name}")
            path_by_name[name] = path
    if set(path_by_name) != set(body_names):
        raise PoseParityError(
            f"{recordable.group}: recorded/native link closure mismatch; "
            f"missing={sorted(set(body_names) - set(path_by_name))}"
        )
    paths = tuple(path_by_name[name] for name in body_names)
    positions: list[np.ndarray] = []
    orientations: list[np.ndarray] = []
    for index, _name in enumerate(body_names):
        pose = root_pose[0] if index == 0 else body_poses[0, index]
        positions.append(np.asarray(pose[:3], dtype=np.float64))
        orientations.append(xyzw_to_wxyz(pose[3:]))
    root_position_error = float(np.linalg.norm(root_pose[0, :3] - body_poses[0, 0, :3]))
    root_orientation_error = float(
        quaternion_error_rad(xyzw_to_wxyz(root_pose[0, 3:]), xyzw_to_wxyz(body_poses[0, 0, 3:]))
    )
    if (
        root_position_error > POSITION_THRESHOLD_M
        or root_orientation_error > ORIENTATION_THRESHOLD_RAD
    ):
        raise PoseParityError(
            f"{recordable.group}: native root_pose_w disagrees with root body tensor: "
            f"{root_position_error} m, {root_orientation_error} rad"
        )
    return (
        PoseIdentity(
            recordable.group,
            paths,
            "articulation",
            motion="any",
            motion_paths=paths[1:],
        ),
        {
            "positions": np.asarray(positions, dtype=np.float32),
            "orientations": np.asarray(orientations, dtype=np.float32),
        },
    )


def _project_fabric_frame(
    raw: Mapping[str, Mapping[str, Any]],
    recordables: Sequence[Any],
    identities: Sequence[PoseIdentity],
) -> dict[str, dict[str, Any]]:
    """Drop non-physical articulation container Xforms from parity comparison."""
    identity_by_group = {identity.group: identity for identity in identities}
    projected: dict[str, dict[str, Any]] = {}
    for recordable in recordables:
        sample = dict(raw[recordable.group])
        identity = identity_by_group[recordable.group]
        if "positions" in sample:
            recorded_paths = tuple(recordable.link_paths)
            indices = [recorded_paths.index(path) for path in identity.paths]
            sample["positions"] = np.asarray(sample["positions"])[indices]
            sample["orientations"] = np.asarray(sample["orientations"])[indices]
        projected[recordable.group] = sample
    return projected


def _native_single(
    group: str, path: str, pose_xyzw: Any, kind: str
) -> tuple[PoseIdentity, dict[str, np.ndarray]]:
    pose = np.asarray(pose_xyzw, dtype=np.float64)
    if pose.shape != (7,) or not np.isfinite(pose).all():
        raise PoseParityError(f"{group}: native pose must be one finite [position, xyzw] vector")
    return (
        PoseIdentity(group, (path,), kind, motion="all"),
        {
            "position": pose[:3].astype(np.float32),
            "orientation": xyzw_to_wxyz(pose[3:]).astype(np.float32),
        },
    )


def _recordables_and_sources(env: Any) -> tuple[list[Any], dict[str, tuple[str, Any]]]:
    from isaacsim.replicator.episode_recorder import (
        ArticulationRecordable,
        CameraRecordable,
        RigidBodyRecordable,
    )

    cameras = {
        "left_wrist": env.camera.wrists[0],
        "right_wrist": env.camera.wrists[1],
        "scene": env.camera.scene_camera,
    }
    recordables: list[Any] = []
    sources: dict[str, tuple[str, Any]] = {}
    for side, robot in zip(("left", "right"), env.robots, strict=True):
        group = f"state/{side}_robot"
        recordable = ArticulationRecordable(group=group, prim_path=f"/World/{side.title()}Piper")
        recordables.append(recordable)
        sources[group] = ("articulation", robot)
    for index, asset in enumerate(env.vr_runtime.dynamic_assets):
        group = f"state/object_{index}"
        recordable = RigidBodyRecordable(group=group, prim_path=asset.cfg.prim_path)
        recordables.append(recordable)
        sources[group] = ("rigid_body", asset)
    for role, camera in cameras.items():
        group = f"state/camera/{role}"
        path = camera._view.prim_paths[0]
        recordable = CameraRecordable(group=group, prim_path=path, resolution=(640, 480))
        recordables.append(recordable)
        sources[group] = ("camera", camera)
    for recordable in recordables:
        recordable.on_session_open(env.sim.stage)
    return recordables, sources


def _capture_native(
    recordables: Sequence[Any], sources: Mapping[str, tuple[str, Any]]
) -> tuple[list[PoseIdentity], dict[str, dict[str, np.ndarray]]]:
    identities: list[PoseIdentity] = []
    frame: dict[str, dict[str, np.ndarray]] = {}
    for recordable in recordables:
        kind, source = sources[recordable.group]
        if kind == "articulation":
            identity, sample = _native_articulation(source, recordable)
        elif kind == "rigid_body":
            pose = _numpy(source.data.root_pose_w)
            if pose.shape != (1, 7):
                raise PoseParityError(f"{recordable.group}: native rigid pose shape {pose.shape}")
            identity, sample = _native_single(recordable.group, recordable.prim_path, pose[0], kind)
        elif kind == "camera":
            position = _numpy(source.data.pos_w)
            # UsdGeom.Camera uses OpenGL camera axes.  This remains the native
            # Isaac Lab tensor, selected in the convention matching the prim.
            orientation = _numpy(source.data.quat_w_opengl)
            if position.shape != (1, 3) or orientation.shape != (1, 4):
                raise PoseParityError(
                    f"{recordable.group}: native camera shapes {position.shape}, {orientation.shape}"
                )
            identity, sample = _native_single(
                recordable.group,
                recordable.prim_path,
                np.concatenate((position[0], orientation[0])),
                kind,
            )
        else:  # pragma: no cover - closed construction above
            raise PoseParityError(f"unsupported native pose source: {kind}")
        identities.append(identity)
        frame[recordable.group] = sample
    return identities, frame


def _apply_motion(
    env: Any, index: int, object_origins: Sequence[np.ndarray], scene_origin: np.ndarray
) -> None:
    import torch
    from isaac_s1_runtime import d0_action_to_native

    target = np.asarray(env.home_d0, dtype=np.float64).copy()
    phase = float(index + 1)
    target[0] += 1.0 * phase
    target[7] -= 1.0 * phase
    target[3] += 0.5 * phase
    target[10] -= 0.5 * phase
    env._apply(d0_action_to_native(target))
    for asset_index, (asset, origin) in enumerate(
        zip(env.vr_runtime.dynamic_assets, object_origins, strict=True)
    ):
        pose = torch.as_tensor(origin.copy(), dtype=torch.float32, device=env.sim.device).reshape(
            1, 7
        )
        pose[0, asset_index % 2] += 0.001 * phase
        asset.write_root_pose_to_sim_index(root_pose=pose)
        asset.write_root_velocity_to_sim_index(
            root_velocity=torch.zeros((1, 6), device=env.sim.device)
        )
    scene = env.camera.scene_camera
    position = torch.as_tensor(
        scene_origin[:3], dtype=torch.float32, device=env.sim.device
    ).reshape(1, 3)
    position[0, 2] += 0.001 * phase
    orientation = torch.as_tensor(
        scene_origin[3:], dtype=torch.float32, device=env.sim.device
    ).reshape(1, 4)
    scene.set_world_poses(positions=position, orientations=orientation, convention="world")
    env._advance(4)


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_live_pose_parity_assay(env: Any, report_path: Path, *, samples: int = 5) -> int:
    """Run deterministic moving parity against native tensors in real Kit."""
    if samples < 3:
        raise ValueError("live moving parity requires at least three samples")
    import carb.settings
    from tools.isaac_vr_recording import ExplicitFrameSampler

    if not carb.settings.get_settings().get_as_bool("/app/useFabricSceneDelegate"):
        raise PoseParityError("Fabric Scene Delegate is disabled")
    recordables: list[Any] = []
    report: dict[str, Any]
    try:
        recordables, sources = _recordables_and_sources(env)
        sampler = ExplicitFrameSampler(object(), recordables)
        object_origins = [
            _numpy(asset.data.root_pose_w)[0].astype(np.float64).copy()
            for asset in env.vr_runtime.dynamic_assets
        ]
        scene = env.camera.scene_camera
        scene_origin = np.concatenate(
            (_numpy(scene.data.pos_w)[0], _numpy(scene.data.quat_w_world)[0])
        ).astype(np.float64)
        fabric_frames: list[dict[str, dict[str, Any]]] = []
        native_frames: list[dict[str, dict[str, np.ndarray]]] = []
        identities: list[PoseIdentity] | None = None
        for index in range(samples):
            if index:
                _apply_motion(env, index - 1, object_origins, scene_origin)
            raw_fabric = sampler.capture_frame()
            current_identities, native = _capture_native(recordables, sources)
            if identities is None:
                identities = current_identities
            elif current_identities != identities:
                raise PoseParityError("pose identity changed during assay")
            fabric_frames.append(_project_fabric_frame(raw_fabric, recordables, current_identities))
            native_frames.append(native)
        assert identities is not None
        report = qualify_pose_sequence(fabric_frames, native_frames, identities)
        report.update(
            {
                "backend_requested": "fabric",
                "backend_effective": "fabric",
                "episode_recorder_version": "0.1.6",
                "native_sources": {
                    "articulation": "Isaac Lab body_link_pose_w/root_pose_w tensors (xyzw)",
                    "rigid_body": "Isaac Lab root_pose_w tensor (xyzw)",
                    "camera": "Isaac Lab Camera pos_w/quat_w_opengl tensors (xyzw)",
                },
            }
        )
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "passed": False,
            "failure": f"{type(exc).__name__}: {exc}",
            "thresholds": asdict(PoseThresholds()),
        }
        _write_report(report_path, report)
        raise
    finally:
        for recordable in reversed(recordables):
            recordable.on_session_close()
    _write_report(report_path, report)
    if not report["passed"]:
        raise PoseParityError(
            "moving Fabric/native pose parity exceeded a threshold or lacked required motion"
        )
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0


def _run_child(report: Path, child_args: Sequence[str]) -> int:
    """Use the existing scene launcher while replacing only its no-client callback."""
    import isaac_vr_recording_smoke

    def callback(env, args_cli, **_kwargs):
        return run_live_pose_parity_assay(env, report)

    isaac_vr_recording_smoke.run_recording_lifecycle_smoke = callback
    child = Path(__file__).with_name("run_isaac_s1.py")
    sys.argv = [str(child), *child_args]
    try:
        runpy.run_path(str(child), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("child_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    child_args = list(args.child_args)
    if child_args[:1] == ["--"]:
        child_args.pop(0)
    if not child_args:
        parser.error("the run_isaac_s1.py child arguments are required after --")
    return _run_child(args.report, child_args)


if __name__ == "__main__":
    raise SystemExit(main())
