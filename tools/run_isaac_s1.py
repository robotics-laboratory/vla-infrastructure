#!/usr/bin/env python3
"""Launch and validate the one concrete bimanual PIPER-X Gate S1 environment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import platform
import subprocess
import traceback
from pathlib import Path
from typing import Any, cast

import numpy as np
import yaml

from isaac_s1_runtime import (
    ISAAC_ARM_JOINT_NAMES,
    JOINT_LIMITS_DEG,
    NativeBimanualTargets,
    d0_action_to_native,
    jsonable,
    materialize_gate_c_urdf,
    native_observation_to_d0,
    relative_pose_matrix,
    seed_reset,
    transform_error,
)

from isaaclab.app import AppLauncher  # type: ignore[import-not-found]
import isaaclab  # type: ignore[import-not-found]  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/isaac_s1_runtime.yaml"
MODEL_PATH = ROOT / "configs/piper_x_model_contract.yaml"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--report", type=Path)
parser.add_argument(
    "--eval-socket",
    type=Path,
    help="Serve the concrete EVAL v2 boundary on this Unix-domain socket.",
)
parser.add_argument(
    "--eval-run-manifest",
    type=Path,
    help="JSON handshake manifest for --eval-socket.",
)
parser.add_argument(
    "--s2-teleop",
    action="store_true",
    help="Run the S2 Quest-to-simulation loop on this exact S1 environment.",
)
parser.add_argument(
    "--s2-cloudxr-profile",
    choices=("cloudxrjs", "standalone"),
    default="cloudxrjs",
)
parser.add_argument("--s2-max-control-steps", type=int, default=300)
parser.add_argument("--s2-reset-step", type=int, default=120)
parser.add_argument(
    "--s2-require-session",
    action=argparse.BooleanOptionalAction,
    default=True,
)
parser.add_argument(
    "--s2-require-tracking",
    action="store_true",
    help="Require at least one valid physical sample from each controller.",
)
parser.add_argument(
    "--robosyn-vr-demo",
    action="store_true",
    help="Run the isolated RoboSyn-inspired experiment instead of the S1 scene.",
)
parser.add_argument(
    "--demo-profile",
    choices=("dual_cube_to_matching_plates", "robosyn_asset_lab"),
    default="dual_cube_to_matching_plates",
)
parser.add_argument(
    "--demo-hud-on-start",
    action="store_true",
    help="Start the upstream wrist-camera XR panels visible (measurement/debug only).",
)
parser.add_argument(
    "--demo-scene-preview",
    type=Path,
    help="Optional PNG destination for the non-D0 demo scene camera.",
)
parser.add_argument(
    "--demo-display-toggle-smoke",
    action="store_true",
    help=argparse.SUPPRESS,
)
parser.add_argument(
    "--demo-backdrop-toggle-smoke",
    action="store_true",
    help=argparse.SUPPRESS,
)
parser.add_argument(
    "--demo-recenter-smoke",
    action="store_true",
    help=argparse.SUPPRESS,
)
AppLauncher.add_app_launcher_args(parser)
parser.set_defaults(headless=True, enable_cameras=True)
args_cli = parser.parse_args()

if (args_cli.eval_socket is None) != (args_cli.eval_run_manifest is None):
    parser.error("--eval-socket and --eval-run-manifest must be provided together")

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

import torch  # noqa: E402

import isaaclab.sim as sim_utils  # type: ignore[import-not-found]  # noqa: E402
from isaaclab.actuators import ImplicitActuatorCfg  # type: ignore[import-not-found]  # noqa: E402
from isaaclab.assets import (  # type: ignore[import-not-found]  # noqa: E402
    Articulation,
    ArticulationCfg,
    RigidObject,
    RigidObjectCfg,
)
from isaaclab.sensors.camera import Camera, CameraCfg  # type: ignore[import-not-found]  # noqa: E402
from isaaclab.utils.math import combine_frame_transforms  # type: ignore[import-not-found]  # noqa: E402


PHYSICS_DT = 1.0 / 120.0
CONTROL_DT = 1.0 / 30.0
ACTION_REPEAT = 4
HOME_PER_ARM = np.asarray([0.0, 30.0, -60.0, 0.0, 20.0, 0.0, 50.0], dtype=np.float64)
ISAAC_ACTUATED_JOINT_NAMES = (*ISAAC_ARM_JOINT_NAMES, "gripper_joint1", "gripper_joint2")
PARITY_POSITION_TOLERANCE_M = 5.0e-4
PARITY_ORIENTATION_TOLERANCE_RAD = 5.0e-4
ZERO_POSITION_TOLERANCE_RAD = 2.0e-5
JOINT_LIMIT_TOLERANCE_RAD = 2.0e-5
CAMERA_OFFSET_POS_M = (0.10, 0.0, 0.05)
CAMERA_OFFSET_QUAT_XYZW = (0.0, 0.0, 0.0, 1.0)
CAMERA_ROLES = ("left_wrist", "right_wrist")
CAMERA_TARGET_PATHS = ("/World/S1LeftCameraTarget", "/World/S1RightCameraTarget")
CAMERA_TARGET_CHANNELS = (0, 0)
CAMERA_FRAMES = 110


def _cpu(proxy) -> np.ndarray:
    tensor = proxy if isinstance(proxy, torch.Tensor) else proxy.torch
    return tensor.detach().cpu().numpy()


def _robot_cfg(
    prim_path: str,
    position: tuple[float, float, float],
    usd_path: str,
    *,
    home_per_arm: np.ndarray = HOME_PER_ARM,
    enable_self_collisions: bool = False,
    activate_contact_sensors: bool = False,
) -> ArticulationCfg:
    home = np.asarray(home_per_arm, dtype=np.float64)
    if home.shape != (7,):
        raise ValueError(f"home_per_arm must have shape (7,), got {home.shape}")
    return ArticulationCfg(
        prim_path=prim_path,
        spawn=sim_utils.UsdFileCfg(
            usd_path=usd_path,
            activate_contact_sensors=activate_contact_sensors,
            rigid_props=sim_utils.RigidBodyPropertiesCfg(
                disable_gravity=True,
                max_depenetration_velocity=1.0,
            ),
            articulation_props=sim_utils.ArticulationRootPropertiesCfg(
                enabled_self_collisions=enable_self_collisions,
                solver_position_iteration_count=8,
                solver_velocity_iteration_count=2,
            ),
        ),
        init_state=ArticulationCfg.InitialStateCfg(
            pos=position,
            joint_pos={
                "joint1": math.radians(float(home[0])),
                "joint2": math.radians(float(home[1])),
                "joint3": math.radians(float(home[2])),
                "joint4": math.radians(float(home[3])),
                "joint5": math.radians(float(home[4])),
                "joint6": math.radians(float(home[5])),
                "gripper": float(home[6]) / 1000.0,
                "gripper_joint1": float(home[6]) / 2000.0,
                "gripper_joint2": -float(home[6]) / 2000.0,
            },
            joint_vel={".*": 0.0},
        ),
        actuators={
            "arm_position_drives": ImplicitActuatorCfg(
                joint_names_expr=["joint[1-6]"],
                effort_limit_sim=100.0,
                velocity_limit_sim=5.0,
                stiffness=None,
                damping=None,
            ),
            "gripper_position_drives": ImplicitActuatorCfg(
                joint_names_expr=["gripper", "gripper_joint[1-2]"],
                effort_limit_sim=10.0,
                velocity_limit_sim=3.0,
                stiffness=2000.0,
                damping=100.0,
            ),
        },
    )


def _wrist_path(sim, arm_path: str) -> str:
    from pxr import Usd, UsdPhysics  # type: ignore[import-not-found]

    matches = [
        prim
        for prim in Usd.PrimRange(sim.stage.GetPrimAtPath(arm_path))
        if prim.GetName() == "gripper_base" and prim.HasAPI(UsdPhysics.RigidBodyAPI)
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one imported wrist frame: {matches}")
    return str(matches[0].GetPath())


def _camera(sim, arm_paths: tuple[str, str]) -> tuple[Camera, tuple[str, str], str]:
    wrist_paths = cast(tuple[str, str], tuple(_wrist_path(sim, arm_path) for arm_path in arm_paths))
    left_suffix = wrist_paths[0].split(arm_paths[0], maxsplit=1)[1]
    right_suffix = wrist_paths[1].split(arm_paths[1], maxsplit=1)[1]
    if left_suffix != right_suffix:
        raise RuntimeError(f"left/right wrist hierarchy mismatch: {wrist_paths}")
    prim_expression = f"/World/[^/]*Piper{left_suffix}/S1WristCamera"
    return (
        Camera(
            CameraCfg(
                prim_path=prim_expression,
                update_period=0.0,
                height=480,
                width=640,
                data_types=["rgb"],
                update_latest_camera_pose=True,
                spawn=sim_utils.PinholeCameraCfg(
                    focal_length=18.0,
                    focus_distance=1.0,
                    horizontal_aperture=20.955,
                    clipping_range=(0.02, 10.0),
                ),
                offset=CameraCfg.OffsetCfg(
                    pos=CAMERA_OFFSET_POS_M,
                    rot=CAMERA_OFFSET_QUAT_XYZW,
                    convention="world",
                ),
            )
        ),
        wrist_paths,
        prim_expression,
    )


class BimanualPiperXIsaacEnvironment:
    """The S1 environment itself; intentionally concrete rather than a simulator API."""

    def __init__(
        self,
        sim,
        left,
        right,
        camera,
        wrist_paths,
        camera_prim_expression,
        physics_probe,
        *,
        home_d0: np.ndarray | None = None,
        experiment_runtime=None,
    ):
        self.sim = sim
        self.robots = (left, right)
        self.camera = camera
        self.wrist_paths = wrist_paths
        self.camera_prim_expression = camera_prim_expression
        self.camera_prim_paths = tuple(f"{path}/S1WristCamera" for path in wrist_paths)
        self.physics_probe = physics_probe
        self.home_d0 = (
            np.tile(HOME_PER_ARM, 2)
            if home_d0 is None
            else np.asarray(home_d0, dtype=np.float64).copy()
        )
        if self.home_d0.shape != (14,):
            raise ValueError(f"home_d0 must have shape (14,), got {self.home_d0.shape}")
        self.experiment_runtime = experiment_runtime
        self.joint_ids: list[list[int]] = []
        self.actuated_joint_ids: list[list[int]] = []
        self.wrist_ids: list[int] = []
        self.step_count = 0
        for robot in self.robots:
            ids, names = robot.find_joints(list(ISAAC_ARM_JOINT_NAMES), preserve_order=True)
            if tuple(names) != ISAAC_ARM_JOINT_NAMES:
                raise RuntimeError(f"native joint order mismatch: {names}")
            self.joint_ids.append(ids)
            actuated_ids, actuated_names = robot.find_joints(
                list(ISAAC_ACTUATED_JOINT_NAMES), preserve_order=True
            )
            if tuple(actuated_names) != ISAAC_ACTUATED_JOINT_NAMES:
                raise RuntimeError(f"native actuated joint order mismatch: {actuated_names}")
            self.actuated_joint_ids.append(actuated_ids)
            self.wrist_ids.append(robot.find_bodies("gripper_base")[0][0])
        if self.camera.num_instances != 2:
            raise RuntimeError(
                f"expected two batched wrist cameras, got {self.camera.num_instances}"
            )

    @staticmethod
    def _with_mimics(values: np.ndarray) -> np.ndarray:
        aperture = values[6]
        return np.concatenate((values, [0.5 * aperture, -0.5 * aperture]))

    def _set_state(self, targets: NativeBimanualTargets) -> None:
        for robot, ids, values in zip(
            self.robots,
            self.actuated_joint_ids,
            (targets.left_rad_m, targets.right_rad_m),
            strict=True,
        ):
            position = torch.as_tensor(
                self._with_mimics(values), device=self.sim.device, dtype=torch.float32
            ).unsqueeze(0)
            velocity = torch.zeros_like(position)
            robot.write_joint_position_to_sim_index(position=position, joint_ids=ids)
            robot.write_joint_velocity_to_sim_index(velocity=velocity, joint_ids=ids)
            robot.actuators.target_command.set_position_index(value=position, joint_ids=ids)
            robot.write_data_to_sim()

    def _apply(self, targets: NativeBimanualTargets) -> None:
        for robot, ids, values in zip(
            self.robots,
            self.actuated_joint_ids,
            (targets.left_rad_m, targets.right_rad_m),
            strict=True,
        ):
            target = torch.as_tensor(
                self._with_mimics(values), device=self.sim.device, dtype=torch.float32
            ).unsqueeze(0)
            robot.actuators.target_command.set_position_index(value=target, joint_ids=ids)

    def expected_camera_poses(self) -> list[tuple[torch.Tensor, torch.Tensor]]:
        result = []
        for robot, wrist_id in zip(self.robots, self.wrist_ids, strict=True):
            wrist = robot.data.body_link_pose_w.torch[:, wrist_id]
            position, rotation = combine_frame_transforms(
                wrist[:, :3],
                wrist[:, 3:],
                torch.tensor([CAMERA_OFFSET_POS_M], device=self.sim.device),
                torch.tensor([CAMERA_OFFSET_QUAT_XYZW], device=self.sim.device),
            )
            result.append((position.detach().clone(), rotation.detach().clone()))
        return result

    def _advance(self, repeat: int) -> None:
        for _ in range(repeat):
            for robot in self.robots:
                robot.write_data_to_sim()
            self.sim.step()
            for robot in self.robots:
                robot.update(PHYSICS_DT)
            self.camera.update(PHYSICS_DT, force_recompute=True)
            self.physics_probe.update(PHYSICS_DT)
            if self.experiment_runtime is not None:
                self.experiment_runtime.update(PHYSICS_DT)

    def reset(self, seed: int = 0) -> dict[str, np.ndarray]:
        seed_reset(seed)
        for robot in self.robots:
            robot.write_root_pose_to_sim_index(root_pose=robot.data.default_root_pose.torch.clone())
            robot.write_root_velocity_to_sim_index(
                root_velocity=robot.data.default_root_vel.torch.clone()
            )
        self.physics_probe.write_root_pose_to_sim_index(
            root_pose=self.physics_probe.data.default_root_pose.torch.clone()
        )
        self.physics_probe.write_root_velocity_to_sim_index(
            root_velocity=self.physics_probe.data.default_root_vel.torch.clone()
        )
        self.physics_probe.reset()
        if self.experiment_runtime is not None:
            self.experiment_runtime.reset_scene()
        self._set_state(d0_action_to_native(self.home_d0))
        for robot in self.robots:
            robot.reset()
        self.camera.reset()
        self.step_count = 0
        # Candidate B's qualified native reset lifecycle uses 24 non-evidence
        # renderer-settling ticks followed by one captured physics tick.
        self._advance(25)
        return self.observation()

    def observation(self) -> dict[str, np.ndarray]:
        measured = []
        for robot, ids in zip(self.robots, self.joint_ids, strict=True):
            measured.append(_cpu(robot.data.joint_pos)[0, ids])
        images = _cpu(self.camera.data.output["rgb"])
        if images.shape != (2, 480, 640, 3):
            raise RuntimeError(f"batched camera output shape mismatch: {images.shape}")
        return native_observation_to_d0(measured[0], measured[1], images[0], images[1])

    def step(self, d0_action: np.ndarray):
        targets = d0_action_to_native(d0_action)
        self._apply(targets)
        self._advance(ACTION_REPEAT)
        self.step_count += 1
        observation = self.observation()
        error = np.abs(observation["observation.state"] - np.asarray(d0_action, dtype=np.float64))
        success = bool(
            np.max(error[[*range(6), *range(7, 13)]]) <= 2.0 and max(error[6], error[13]) <= 2.0
        )
        reward = -float(np.max(error))
        truncated = self.step_count >= 120 and not success
        return observation, reward, success, truncated, {"native_saturated": targets.saturated}


def _body_transform(robot: Articulation, body_name: str) -> np.ndarray:
    ids, names = robot.find_bodies(body_name, preserve_order=True)
    if names != [body_name]:
        raise RuntimeError(f"body frame missing or ambiguous: {body_name}: {names}")
    return _cpu(robot.data.body_link_pose_w)[0, ids[0]]


def _set_kinematic_probe(
    env: BimanualPiperXIsaacEnvironment, q_deg: list[float], gripper_mm=50.0
) -> None:
    arm = np.asarray([*q_deg, gripper_mm], dtype=np.float64)
    env._set_state(d0_action_to_native(np.tile(arm, 2)))
    env.sim.forward()
    for robot in env.robots:
        robot.update(0.0)


def _parity_report(env: BimanualPiperXIsaacEnvironment, model: dict) -> dict:
    report: dict = {
        "namespaces": ["/World/LeftPiper", "/World/RightPiper"],
        "joint_names": list(ISAAC_ARM_JOINT_NAMES),
        "frames": ["base_link", "flange_link", "gripper_base"],
        "fk": {},
        "positive_direction": {},
    }
    maximum_position = 0.0
    maximum_orientation = 0.0
    for reference_name, reference in model["verification"]["fk_references"].items():
        _set_kinematic_probe(env, reference["q_deg"])
        for side, robot in zip(("left", "right"), env.robots, strict=True):
            actual = relative_pose_matrix(
                _body_transform(robot, "base_link"), _body_transform(robot, "gripper_base")
            )
            position, orientation = transform_error(actual, reference["T_base_tcp"])
            report["fk"][f"{side}_{reference_name}"] = {
                "position_error_m": position,
                "orientation_error_rad": orientation,
            }
            maximum_position = max(maximum_position, position)
            maximum_orientation = max(maximum_orientation, orientation)

    direction = model["verification"]["positive_direction_reference"]
    for joint_index, mapping in enumerate(model["joint_mapping"]):
        q = list(direction["q_deg"])
        q[joint_index] += direction["delta_deg"]
        _set_kinematic_probe(env, q)
        actual = relative_pose_matrix(
            _body_transform(env.robots[0], "base_link"),
            _body_transform(env.robots[0], "gripper_base"),
        )
        position, orientation = transform_error(
            actual, direction["T_base_tcp"][mapping["plugin_name"]]
        )
        report["positive_direction"][mapping["plugin_name"]] = {
            "position_error_m": position,
            "orientation_error_rad": orientation,
        }
        maximum_position = max(maximum_position, position)
        maximum_orientation = max(maximum_orientation, orientation)

    _set_kinematic_probe(env, [0.0] * 6, 0.0)
    closed_fingers = [
        _body_transform(env.robots[0], name)[:3] for name in ("gripper_link1", "gripper_link2")
    ]
    zero_measured = _cpu(env.robots[0].data.joint_pos)[0, env.joint_ids[0]]
    _set_kinematic_probe(env, [0.0] * 6, 100.0)
    open_fingers = [
        _body_transform(env.robots[0], name)[:3] for name in ("gripper_link1", "gripper_link2")
    ]
    finger_displacements = [
        float(np.linalg.norm(end - start))
        for start, end in zip(closed_fingers, open_fingers, strict=True)
    ]

    expected_limits = np.vstack((np.deg2rad(JOINT_LIMITS_DEG), [0.0, 0.1]))
    actual_limits = _cpu(env.robots[0].data.joint_limits)[0, env.joint_ids[0], :]
    limit_error = float(np.max(np.abs(actual_limits - expected_limits)))
    zero_error = float(np.max(np.abs(zero_measured)))
    report.update(
        {
            "maximum_position_error_m": maximum_position,
            "maximum_orientation_error_rad": maximum_orientation,
            "zero_position_error_rad_or_m": zero_error,
            "joint_limit_error_rad_or_m": limit_error,
            "gripper": {
                "model_aperture_endpoints_m": [0.0, 0.1],
                "finger_displacements_m": finger_displacements,
                "expected_each_m": 0.05,
            },
            "tolerances": {
                "position_m": PARITY_POSITION_TOLERANCE_M,
                "orientation_rad": PARITY_ORIENTATION_TOLERANCE_RAD,
                "zero_position": ZERO_POSITION_TOLERANCE_RAD,
                "joint_limit": JOINT_LIMIT_TOLERANCE_RAD,
            },
        }
    )
    report["passed"] = bool(
        maximum_position <= PARITY_POSITION_TOLERANCE_M
        and maximum_orientation <= PARITY_ORIENTATION_TOLERANCE_RAD
        and zero_error <= ZERO_POSITION_TOLERANCE_RAD
        and limit_error <= JOINT_LIMIT_TOLERANCE_RAD
        and np.allclose(finger_displacements, [0.05, 0.05], atol=PARITY_POSITION_TOLERANCE_M)
    )
    return report


def _quaternion_error_rad(actual: np.ndarray, expected: np.ndarray) -> float:
    actual = actual / np.linalg.norm(actual)
    expected = expected / np.linalg.norm(expected)
    cosine = float(np.clip(abs(np.dot(actual, expected)), 0.0, 1.0))
    return 2.0 * math.acos(cosine)


def _target_image_stats(image: np.ndarray, dominant_channel: int) -> dict:
    values = image.astype(np.int16)
    other_channels = [channel for channel in range(3) if channel != dominant_channel]
    mask = (
        (values[..., dominant_channel] >= 90)
        & (values[..., dominant_channel] - values[..., other_channels[0]] >= 35)
        & (values[..., dominant_channel] - values[..., other_channels[1]] >= 35)
    )
    rows, columns = np.nonzero(mask)
    if not len(rows):
        return {"pixel_count": 0, "centroid_xy_px": None, "center_offset_px": None}
    centroid = np.asarray([columns.mean(), rows.mean()])
    center = np.asarray([(image.shape[1] - 1) / 2.0, (image.shape[0] - 1) / 2.0])
    return {
        "pixel_count": int(len(rows)),
        "centroid_xy_px": centroid.tolist(),
        "center_offset_px": (centroid - center).tolist(),
    }


def _target_shift_px(first: dict, second: dict) -> float | None:
    if first["centroid_xy_px"] is None or second["centroid_xy_px"] is None:
        return None
    return float(np.linalg.norm(np.asarray(second["centroid_xy_px"]) - first["centroid_xy_px"]))


def _camera_pose_snapshot(env: BimanualPiperXIsaacEnvironment) -> list[dict]:
    positions = _cpu(env.camera.data.pos_w)
    orientations = _cpu(env.camera.data.quat_w_world)
    return [
        {"position": positions[index].copy(), "orientation": orientations[index].copy()}
        for index in range(2)
    ]


def _camera_sample(env: BimanualPiperXIsaacEnvironment) -> list[dict]:
    observation = env.observation()
    actual = _camera_pose_snapshot(env)
    expected = env.expected_camera_poses()
    frame_indices = _cpu(env.camera.frame).astype(np.int64)
    samples = []
    for index, role in enumerate(CAMERA_ROLES):
        image = observation[f"observation.images.{role}"]
        target = _target_image_stats(image, CAMERA_TARGET_CHANNELS[index])
        expected_position = _cpu(expected[index][0])[0]
        expected_orientation = _cpu(expected[index][1])[0]
        samples.append(
            {
                "role": role,
                "d0_key": f"observation.images.{role}",
                "wrist_parent_path": env.wrist_paths[index],
                "camera_prim_path": env.camera_prim_paths[index],
                "frame_index": int(frame_indices[index]),
                "shape": list(image.shape),
                "dtype": str(image.dtype),
                "minimum": int(image.min()),
                "maximum": int(image.max()),
                "mean": float(image.mean()),
                "standard_deviation": float(image.std()),
                "sha256": hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest(),
                "target": target,
                "actual_position_world_m": actual[index]["position"].tolist(),
                "actual_orientation_world_xyzw": actual[index]["orientation"].tolist(),
                "expected_position_world_m": expected_position.tolist(),
                "expected_orientation_world_xyzw": expected_orientation.tolist(),
                "position_error_m": float(
                    np.linalg.norm(actual[index]["position"] - expected_position)
                ),
                "orientation_error_rad": _quaternion_error_rad(
                    actual[index]["orientation"], expected_orientation
                ),
                "valid": bool(
                    image.shape == (480, 640, 3)
                    and image.dtype == np.uint8
                    and np.isfinite(image).all()
                    and image.max() > 16
                    and image.mean() > 2.0
                    and image.std() > 1.0
                    and target["pixel_count"] >= 40
                ),
            }
        )
    return samples


def _camera_sequence(env: BimanualPiperXIsaacEnvironment, label: str) -> tuple[dict, list[dict]]:
    per_camera: list[list[dict]] = [[], []]
    for frame_index in range(CAMERA_FRAMES):
        fraction = frame_index / (CAMERA_FRAMES - 1)
        target = np.tile(HOME_PER_ARM, 2)
        target[0] += 25.0 * fraction
        target[3] += 8.0 * fraction
        target[4] += 5.0 * fraction
        target[7] -= 25.0 * fraction
        target[10] -= 8.0 * fraction
        target[11] += 5.0 * fraction
        env._apply(d0_action_to_native(target))
        env._advance(ACTION_REPEAT)
        for index, sample in enumerate(_camera_sample(env)):
            per_camera[index].append(sample)

    summaries = []
    for index, samples in enumerate(per_camera):
        hashes = [sample["sha256"] for sample in samples]
        frame_indices = [sample["frame_index"] for sample in samples]
        first = samples[0]
        final = samples[-1]
        centroids = [sample["target"]["centroid_xy_px"] for sample in samples]
        visible = [np.asarray(value) for value in centroids if value is not None]
        maximum_target_shift = (
            max(float(np.linalg.norm(value - visible[0])) for value in visible) if visible else 0.0
        )
        summary = {
            "role": CAMERA_ROLES[index],
            "d0_key": first["d0_key"],
            "wrist_parent_path": first["wrist_parent_path"],
            "camera_prim_path": first["camera_prim_path"],
            "frames": len(samples),
            "valid_frames": sum(sample["valid"] for sample in samples),
            "unique_frame_hashes": len(set(hashes)),
            "exact_consecutive_changes": sum(a != b for a, b in zip(hashes, hashes[1:])),
            "strictly_increasing_frame_indices": all(
                second > first_index
                for first_index, second in zip(frame_indices, frame_indices[1:])
            ),
            "target_visible_frames": len(visible),
            "maximum_target_centroid_shift_px": maximum_target_shift,
            "camera_translation_m": float(
                np.linalg.norm(
                    np.asarray(final["actual_position_world_m"])
                    - np.asarray(first["actual_position_world_m"])
                )
            ),
            "camera_rotation_rad": _quaternion_error_rad(
                np.asarray(final["actual_orientation_world_xyzw"]),
                np.asarray(first["actual_orientation_world_xyzw"]),
            ),
            "maximum_position_error_m": max(sample["position_error_m"] for sample in samples),
            "maximum_orientation_error_rad": max(
                sample["orientation_error_rad"] for sample in samples
            ),
            "first": first,
            "final": final,
        }
        summary["passed"] = bool(
            summary["frames"] == CAMERA_FRAMES
            and summary["valid_frames"] == CAMERA_FRAMES
            and summary["unique_frame_hashes"] == CAMERA_FRAMES
            and summary["exact_consecutive_changes"] == CAMERA_FRAMES - 1
            and summary["strictly_increasing_frame_indices"]
            and summary["target_visible_frames"] == CAMERA_FRAMES
            and summary["maximum_target_centroid_shift_px"] > 8.0
            and summary["camera_translation_m"] > 0.015
            and summary["maximum_position_error_m"] < 1.0e-3
            and summary["maximum_orientation_error_rad"] < 2.0e-3
        )
        summaries.append(summary)
    return {
        "label": label,
        "cameras": summaries,
        "passed": all(summary["passed"] for summary in summaries),
    }, [samples[-1] for samples in per_camera]


def _camera_identity_regression(env: BimanualPiperXIsaacEnvironment, seed: int) -> dict:
    perturbations: list[dict[str, Any]] = []
    for moved_index, delta_deg in ((0, 15.0), (1, -15.0)):
        env.reset(seed)
        before = _camera_sample(env)
        target = np.tile(HOME_PER_ARM, 2)
        target[7 * moved_index] += delta_deg
        env._set_state(d0_action_to_native(target))
        env._advance(2 * ACTION_REPEAT)
        after = _camera_sample(env)
        pose_changes: list[dict[str, Any]] = []
        target_shifts: list[float | None] = []
        for index in range(2):
            pose_changes.append(
                {
                    "role": CAMERA_ROLES[index],
                    "position_m": float(
                        np.linalg.norm(
                            np.asarray(after[index]["actual_position_world_m"])
                            - np.asarray(before[index]["actual_position_world_m"])
                        )
                    ),
                    "orientation_rad": _quaternion_error_rad(
                        np.asarray(after[index]["actual_orientation_world_xyzw"]),
                        np.asarray(before[index]["actual_orientation_world_xyzw"]),
                    ),
                }
            )
            target_shifts.append(_target_shift_px(before[index]["target"], after[index]["target"]))
        unchanged_index = 1 - moved_index
        moved_target_shift = target_shifts[moved_index]
        unchanged_target_shift = target_shifts[unchanged_index]
        perturbations.append(
            {
                "moved_role": CAMERA_ROLES[moved_index],
                "joint_1_delta_deg": delta_deg,
                "pose_changes": pose_changes,
                "target_centroid_shifts_px": target_shifts,
                "passed": bool(
                    max(
                        pose_changes[moved_index]["position_m"],
                        pose_changes[moved_index]["orientation_rad"],
                    )
                    > 1.0e-3
                    and max(
                        pose_changes[unchanged_index]["position_m"],
                        pose_changes[unchanged_index]["orientation_rad"],
                    )
                    < 1.0e-4
                    and moved_target_shift is not None
                    and moved_target_shift > 5.0
                    and unchanged_target_shift is not None
                    and unchanged_target_shift < 5.0
                    and after[moved_index]["position_error_m"] < 1.0e-3
                    and after[moved_index]["orientation_error_rad"] < 2.0e-3
                ),
            }
        )
    return {
        "camera_prim_expression": env.camera_prim_expression,
        "left": {
            "role": CAMERA_ROLES[0],
            "d0_key": "observation.images.left_wrist",
            "wrist_parent_path": env.wrist_paths[0],
            "camera_prim_path": env.camera_prim_paths[0],
        },
        "right": {
            "role": CAMERA_ROLES[1],
            "d0_key": "observation.images.right_wrist",
            "wrist_parent_path": env.wrist_paths[1],
            "camera_prim_path": env.camera_prim_paths[1],
        },
        "unilateral_perturbations": perturbations,
        "passed": all(item["passed"] for item in perturbations),
    }


def _camera_regression(env: BimanualPiperXIsaacEnvironment, seed: int) -> dict:
    env.reset(seed)
    baseline = _camera_sample(env)
    first_sequence, pre_reset = _camera_sequence(env, "before_reset")
    env.reset(seed)
    post_reset = _camera_sample(env)
    reset_checks = []
    for index in range(2):
        centroid_error = _target_shift_px(baseline[index]["target"], post_reset[index]["target"])
        reset_checks.append(
            {
                "role": CAMERA_ROLES[index],
                "pre_to_post_pose_change_m": float(
                    np.linalg.norm(
                        np.asarray(pre_reset[index]["actual_position_world_m"])
                        - np.asarray(post_reset[index]["actual_position_world_m"])
                    )
                ),
                "post_to_baseline_pose_error_m": float(
                    np.linalg.norm(
                        np.asarray(post_reset[index]["actual_position_world_m"])
                        - np.asarray(baseline[index]["actual_position_world_m"])
                    )
                ),
                "pre_reset_frame_sha256": pre_reset[index]["sha256"],
                "post_reset_frame_sha256": post_reset[index]["sha256"],
                "frame_changed_across_reset": pre_reset[index]["sha256"]
                != post_reset[index]["sha256"],
                "target_centroid_return_error_px": centroid_error,
                "post_reset_frame_valid": post_reset[index]["valid"],
            }
        )
        reset_checks[-1]["passed"] = bool(
            reset_checks[-1]["pre_to_post_pose_change_m"] > 0.015
            and reset_checks[-1]["post_to_baseline_pose_error_m"] < 2.0e-3
            and reset_checks[-1]["frame_changed_across_reset"]
            and centroid_error is not None
            and centroid_error < 0.03
            and reset_checks[-1]["post_reset_frame_valid"]
        )
    second_sequence, _ = _camera_sequence(env, "after_reset")
    identity = _camera_identity_regression(env, seed)
    report: dict[str, Any] = {
        "native_upstream_path": "Isaac Lab Camera with regex-batched FrameView over parented wrist prims",
        "resolution": [640, 480],
        "dtype_layout_color": "uint8 HWC RGB",
        "initial_renderer_warmup_physics_steps": 24,
        "sequences": [first_sequence, second_sequence],
        "reset": {"checks": reset_checks, "passed": all(item["passed"] for item in reset_checks)},
        "identity": identity,
    }
    report["passed"] = bool(
        all(sequence["passed"] for sequence in report["sequences"])
        and report["reset"]["passed"]
        and identity["passed"]
    )
    return report


def main() -> int:
    print("[S1] loading checked configuration", flush=True)
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    model = yaml.safe_load(MODEL_PATH.read_text(encoding="utf-8"))
    urdf_path = Path(config["asset"]["composed_urdf"])
    urdf_sha = materialize_gate_c_urdf(Path(config["asset"]["source_checkout"]), urdf_path)

    if args_cli.robosyn_vr_demo:
        from isaac_robosyn_vr_demo import run_robosyn_vr_demo

        return run_robosyn_vr_demo(
            args_cli,
            simulation_app,
            urdf_path=urdf_path,
            urdf_sha=urdf_sha,
            robot_cfg_factory=_robot_cfg,
            wrist_path_resolver=_wrist_path,
            environment_type=BimanualPiperXIsaacEnvironment,
        )

    print("[S1] creating 120 Hz PhysX context", flush=True)
    sim = sim_utils.SimulationContext(
        sim_utils.SimulationCfg(
            dt=PHYSICS_DT, render_interval=1, device=args_cli.device, use_fabric=True
        )
    )
    ground = sim_utils.GroundPlaneCfg(size=(4.0, 4.0), color=(0.08, 0.08, 0.08))
    ground.func("/World/Ground", ground)
    light = sim_utils.DomeLightCfg(intensity=2500.0, color=(0.75, 0.75, 0.75))
    light.func("/World/Light", light)
    base_positions = ((-0.35, 0.0, 0.0), (0.35, 0.0, 0.0))
    for target_path, base, color in zip(
        CAMERA_TARGET_PATHS,
        base_positions,
        ((0.95, 0.01, 0.01), (0.95, 0.01, 0.01)),
        strict=True,
    ):
        target_cfg = sim_utils.CuboidCfg(
            size=(0.07, 0.07, 0.07),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=color),
        )
        target_cfg.func(
            target_path,
            target_cfg,
            translation=(base[0] + 0.34497344, base[1] - 0.03061081, base[2] + 0.23541836),
        )
    cube_cfg = RigidObjectCfg(
        prim_path="/World/PhysicsProbe",
        spawn=sim_utils.CuboidCfg(
            size=(0.06, 0.06, 0.06),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(),
            mass_props=sim_utils.MassPropertiesCfg(mass=0.1),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.85, 0.05, 0.05)),
        ),
        init_state=RigidObjectCfg.InitialStateCfg(pos=(0.0, 0.65, 0.5)),
    )
    physics_probe = RigidObject(cube_cfg)
    print("[S1] importing exact Gate C articulation", flush=True)
    converter = sim_utils.UrdfConverter(
        sim_utils.UrdfConverterCfg(
            asset_path=str(urdf_path),
            usd_dir=f"/data/vla-infrastructure/assets/isaac_s1/converted/{urdf_sha}",
            fix_base=True,
            merge_fixed_joints=False,
            self_collision=False,
            robot_type="Manipulator",
            run_multi_physics_conversion=False,
            ros_package_paths=[{"name": "agx_arm_description", "path": "/data/vla-infrastructure/assets"}],
            joint_drive=sim_utils.UrdfConverterCfg.JointDriveCfg(
                drive_type="force",
                target_type="position",
                gains=sim_utils.UrdfConverterCfg.JointDriveCfg.PDGainsCfg(
                    stiffness=400.0, damping=40.0
                ),
            ),
        )
    )
    left = Articulation(_robot_cfg("/World/LeftPiper", base_positions[0], converter.usd_path))
    right = Articulation(_robot_cfg("/World/RightPiper", base_positions[1], converter.usd_path))
    print("[S1] attaching one upstream regex-batched Camera to both wrists", flush=True)
    camera, wrist_paths, camera_prim_expression = _camera(
        sim, ("/World/LeftPiper", "/World/RightPiper")
    )
    print("[S1] resetting simulator", flush=True)
    sim.reset()
    env = BimanualPiperXIsaacEnvironment(
        sim, left, right, camera, wrist_paths, camera_prim_expression, physics_probe
    )

    if args_cli.eval_socket is not None:
        from isaac_eval_rpc import IsaacEvalEndpoint, serve_unix_socket

        handshake = json.loads(args_cli.eval_run_manifest.read_text(encoding="utf-8"))
        endpoint = IsaacEvalEndpoint(env, handshake)
        print(
            f"[E1] serving {endpoint.handshake['run_id']} on {args_cli.eval_socket}",
            flush=True,
        )
        serve_unix_socket(endpoint, args_cli.eval_socket)
        return 0

    if args_cli.s2_teleop:
        print("[S2] extending the accepted S1 environment", flush=True)
        from isaac_s2_runtime import run_s2

        return run_s2(env, args_cli, simulation_app)

    print("[S1] running native camera continuous/reset/identity regression", flush=True)
    camera_validation = _camera_regression(env, 0)
    reset_observation = env.reset(0)
    initial_cube_z = float(_cpu(physics_probe.data.root_pos_w)[0, 2])
    print("[S1] checking Gate C FK, direction, limit, frame, and gripper parity", flush=True)
    parity = _parity_report(env, model)
    repeated_reset = env.reset(0)
    reset_repeat_error = float(
        np.max(np.abs(repeated_reset["observation.state"] - reset_observation["observation.state"]))
    )
    target = np.tile(HOME_PER_ARM, 2)
    target[0] += 5.0
    target[7] -= 5.0
    target[6] = target[13] = 40.0
    print("[S1] stepping bounded bimanual task", flush=True)
    success_terminated = success_truncated = False
    success_steps = 0
    for success_steps in range(1, 121):
        observation, success_reward, success_terminated, success_truncated, success_info = env.step(
            target
        )
        if success_terminated or success_truncated:
            break
    # Bounded hold probe outside task transitions, with the last native target unchanged.
    env._advance(120)
    observation = env.observation()
    final_cube_z = float(_cpu(physics_probe.data.root_pos_w)[0, 2])
    state_error = np.abs(observation["observation.state"] - target)
    env.reset(0)
    saturated_target = np.tile(HOME_PER_ARM, 2)
    saturated_target[0] = 1000.0
    timeout_terminated = timeout_truncated = False
    timeout_info = {"native_saturated": False}
    for timeout_steps in range(1, 121):
        _, timeout_reward, timeout_terminated, timeout_truncated, timeout_info = env.step(
            saturated_target
        )
        if timeout_terminated or timeout_truncated:
            break

    runtime_commit = subprocess.check_output(
        ["git", "-C", config["environment"]["isaac_lab_path"], "rev-parse", "HEAD"],
        text=True,
    ).strip()
    driver = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], text=True
    ).splitlines()[0]
    report: dict[str, Any] = {
        "gate": "S1",
        "environment": {
            "python": platform.python_version(),
            "isaac_sim": importlib.metadata.version("isaacsim"),
            "isaac_lab_source_version": importlib.metadata.version("isaaclab"),
            "isaac_lab_source_file": str(Path(isaaclab.__file__).resolve()),
            "isaac_lab_expected_commit": config["environment"]["isaac_lab_commit"],
            "isaac_lab_runtime_commit": runtime_commit,
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "torchvision": importlib.metadata.version("torchvision"),
            "torchaudio": importlib.metadata.version("torchaudio"),
            "nvidia_driver": driver,
            "cuda_available": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0),
            "lerobot_present": importlib.util.find_spec("lerobot") is not None,
            "headless": args_cli.headless,
            "upstream_override_conflicts": config["environment"]["upstream_override_conflicts"],
        },
        "asset": {
            "composed_urdf": str(urdf_path),
            "sha256": urdf_sha,
            "shared_converted_usd": converter.usd_path,
        },
        "execution": {
            "physics_dt_s": sim.get_physics_dt(),
            "control_dt_s": CONTROL_DT,
            "action_repeat": ACTION_REPEAT,
            "render_interval_physics_steps": 1,
            "control_mode": "absolute joint position",
            "actuator_type": "Isaac Lab implicit PhysX force PD drive",
            "action_hold": "zero-order hold for four physics steps",
            "saturation": "D0 label preserved; native target clipped to accepted URDF limits",
            "reset_seed_protocol": "seed Python, NumPy, and torch before deterministic fixed reset",
            "physics_probe_initial_z_m": initial_cube_z,
            "physics_probe_final_z_m": final_cube_z,
        },
        "reset": {
            "repeated_reset_maximum_error": reset_repeat_error,
            "state_shape": list(reset_observation["observation.state"].shape),
            "maximum_home_error": float(
                np.max(np.abs(reset_observation["observation.state"] - np.tile(HOME_PER_ARM, 2)))
            ),
        },
        "task": {
            "task_id": config["task"]["id"],
            "revision": config["task"]["revision"],
            "success_episode": {
                "steps": success_steps,
                "terminated": success_terminated,
                "truncated": success_truncated,
                "reward": success_reward,
                "maximum_joint_error_deg": float(np.max(state_error[[*range(6), *range(7, 13)]])),
                "maximum_gripper_error_mm": float(max(state_error[6], state_error[13])),
                "native_saturated": success_info["native_saturated"],
            },
            "timeout_episode": {
                "steps": timeout_steps,
                "terminated": timeout_terminated,
                "truncated": timeout_truncated,
                "reward": timeout_reward,
                "native_saturated": timeout_info["native_saturated"],
            },
        },
        "cameras": camera_validation,
        "parity": parity,
    }
    report["passed"] = bool(
        report["environment"]["python"] == "3.12.13"
        and report["environment"]["isaac_sim"] == "6.0.1.0"
        and report["environment"]["isaac_lab_source_version"] == "16.4.0"
        and report["environment"]["isaac_lab_runtime_commit"]
        == report["environment"]["isaac_lab_expected_commit"]
        and Path(report["environment"]["isaac_lab_source_file"]).is_relative_to(
            Path(config["environment"]["isaac_lab_path"]) / "source/isaaclab"
        )
        and report["environment"]["torch"] == "2.11.0+cu128"
        and report["environment"]["torch_cuda"] == "12.8"
        and report["environment"]["torchvision"] == "0.26.0+cu128"
        and report["environment"]["torchaudio"] == "2.11.0+cu128"
        and report["environment"]["nvidia_driver"] == "580.159.03"
        and report["environment"]["cuda_available"]
        and report["environment"]["headless"]
        and not report["environment"]["lerobot_present"]
        and report["execution"]["physics_probe_final_z_m"]
        < report["execution"]["physics_probe_initial_z_m"] - 0.1
        and report["reset"]["state_shape"] == [14]
        and reset_repeat_error < 0.01
        and report["task"]["success_episode"]["terminated"]
        and not report["task"]["success_episode"]["truncated"]
        and not report["task"]["success_episode"]["native_saturated"]
        and not report["task"]["timeout_episode"]["terminated"]
        and report["task"]["timeout_episode"]["truncated"]
        and report["task"]["timeout_episode"]["native_saturated"]
        and report["cameras"]["passed"]
        and parity["passed"]
    )
    print("S1_RESULT_JSON=" + json.dumps(jsonable(report), sort_keys=True), flush=True)
    if args_cli.report:
        args_cli.report.parent.mkdir(parents=True, exist_ok=True)
        args_cli.report.write_text(json.dumps(jsonable(report), indent=2, sort_keys=True) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    return_code = 1
    try:
        return_code = main()
    except BaseException:
        traceback.print_exc()
    finally:
        simulation_app.close(exit_code=return_code)
    raise SystemExit(return_code)
