#!/usr/bin/env python3
"""Produce the executable Gate M1 parity and runtime evidence artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/piperx-mujoco-cache")

import gymnasium as gym  # noqa: E402
import mujoco  # noqa: E402
import numpy as np  # noqa: E402
import yaml  # noqa: E402
from gymnasium.utils.env_checker import check_env  # noqa: E402
from OpenGL import GL  # noqa: E402

from lerobot_env_piperx_mujoco import ENV_ID  # noqa: E402
from lerobot_env_piperx_mujoco.constants import (  # noqa: E402
    ACTION_REPEAT,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    HOME_D0,
    HORIZON,
    PHYSICS_HZ,
    SIDES,
)
from lerobot_env_piperx_mujoco.processors import (  # noqa: E402
    PROCESSOR_REVISION,
    PiperXMujocoActionProcessor,
    PiperXMujocoObservationProcessor,
)
from lerobot_env_piperx_mujoco.env import (  # noqa: E402
    PiperXDualCubeToMatchingPlateMujocoEnv,
)


ROOT = Path(__file__).resolve().parents[1]
ARM_PATH = ROOT / "assets/mujoco/piper_x/f6642ce0d7872c686f29c99e9e10cd23d1d49313/piper_x.xml"
SCENE_PATH = ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml"
MODEL_CONTRACT_PATH = ROOT / "configs/piper_x_model_contract.yaml"
RESOLVED_CONTRACT_PATH = ROOT / "configs/resolved_contract.yaml"


def _sha256_array(value: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rotation_error(actual: np.ndarray, expected: np.ndarray) -> float:
    cosine = np.clip((np.trace(actual @ expected.T) - 1.0) * 0.5, -1.0, 1.0)
    return float(np.arccos(cosine))


def _set_gripper_target(
    model: mujoco.MjModel, data: mujoco.MjData, side: str, aperture_m: float
) -> None:
    data.actuator(f"{side}_gripper_aperture_position").ctrl = aperture_m


def _tcp_transform(model: mujoco.MjModel, q_deg: list[float]) -> np.ndarray:
    data = mujoco.MjData(model)
    for index, value in enumerate(q_deg, start=1):
        data.joint(f"joint{index}").qpos = math.radians(value)
    mujoco.mj_forward(model, data)
    body = data.body("gripper_base")
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = body.xmat.reshape(3, 3)
    transform[:3, 3] = body.xpos
    return transform


def _renderer_identity() -> dict[str, str]:
    context = mujoco.GLContext(8, 8)
    try:
        context.make_current()
        return {
            "vendor": GL.glGetString(GL.GL_VENDOR).decode(),
            "renderer": GL.glGetString(GL.GL_RENDERER).decode(),
            "version": GL.glGetString(GL.GL_VERSION).decode(),
        }
    finally:
        context.free()


def _embodiment_parity() -> dict[str, Any]:
    model = mujoco.MjModel.from_xml_path(str(ARM_PATH))
    contract = yaml.safe_load(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
    tolerances = yaml.safe_load(RESOLVED_CONTRACT_PATH.read_text(encoding="utf-8"))["model"][
        "parity_tolerances"
    ]

    expected_names = [
        *[f"joint{index}" for index in range(1, 7)],
        "gripper",
        "gripper_joint1",
        "gripper_joint2",
    ]
    actual_names = [model.joint(index).name for index in range(model.njnt)]
    joint_limit_error = 0.0
    for mapping in contract["joint_mapping"]:
        expected = np.deg2rad(mapping["limits_deg"])
        actual = model.joint(mapping["urdf_name"]).range
        joint_limit_error = max(joint_limit_error, float(np.max(np.abs(actual - expected))))

    position_errors: list[float] = []
    orientation_errors: list[float] = []
    verification = contract["verification"]
    for reference in verification["fk_references"].values():
        actual = _tcp_transform(model, reference["q_deg"])
        expected = np.asarray(reference["T_base_tcp"], dtype=np.float64)
        position_errors.append(float(np.linalg.norm(actual[:3, 3] - expected[:3, 3])))
        orientation_errors.append(_rotation_error(actual[:3, :3], expected[:3, :3]))
    direction = verification["positive_direction_reference"]
    for index, mapping in enumerate(contract["joint_mapping"]):
        q_deg = list(direction["q_deg"])
        q_deg[index] += direction["delta_deg"]
        actual = _tcp_transform(model, q_deg)
        expected = np.asarray(direction["T_base_tcp"][mapping["plugin_name"]], dtype=np.float64)
        position_errors.append(float(np.linalg.norm(actual[:3, 3] - expected[:3, 3])))
        orientation_errors.append(_rotation_error(actual[:3, :3], expected[:3, :3]))

    aperture_actuator = model.actuator("gripper_aperture_position")
    pad_names = tuple(f"gripper_pad{index}" for index in (1, 2))
    gripper_pads = {
        model.geom(name).name: {
            "position_m": model.geom(name).pos.tolist(),
            "size_m": model.geom(name).size.tolist(),
            "orientation_wxyz": model.geom(name).quat.tolist(),
            "contact_dimensions": int(model.geom(name).condim.item()),
            "friction": model.geom(name).friction.tolist(),
        }
        for name in pad_names
    }
    aperture_tendon = model.tendon("gripper_aperture")
    center_tendon = model.tendon("gripper_center")
    center_constraint = model.equality("gripper_center_constraint")
    zero_position_error = float(np.max(np.abs(model.qpos0)))
    report = {
        "passed": False,
        "model_dimensions": {"nq": model.nq, "nv": model.nv, "nu": model.nu, "neq": model.neq},
        "contact_solver": {
            "cone": "elliptic"
            if model.opt.cone == mujoco.mjtCone.mjCONE_ELLIPTIC
            else "pyramidal",
            "impratio": float(model.opt.impratio),
            "noslip_iterations": int(model.opt.noslip_iterations),
        },
        "joint_names_expected": expected_names,
        "joint_names_actual": actual_names,
        "joint_limit_max_error_rad_or_m": joint_limit_error,
        "zero_position_max_error_rad_or_m": zero_position_error,
        "fk_direction_max_position_error_m": max(position_errors),
        "fk_direction_max_orientation_error_rad": max(orientation_errors),
        "gripper_range_m": model.joint("gripper").range.tolist(),
        "gripper_control": "one external aperture drives q1-q2; one soft equality constrains the passive q1+q2 centre tendon",
        "gripper_aperture_tendon": {
            "range_m": model.tendon_range[aperture_tendon.id].tolist(),
            "kp": float(model.actuator_gainprm[aperture_actuator.id, 0]),
            "aperture_position_bias_stiffness": float(
                -model.actuator_biasprm[aperture_actuator.id, 1]
            ),
            "kv": float(-model.actuator_biasprm[aperture_actuator.id, 2]),
            "force_range_n": aperture_actuator.forcerange.tolist(),
            "center_tendon_stiffness_n_m": float(model.tendon_stiffness[center_tendon.id]),
            "center_constraint_solref": model.eq_solref[center_constraint.id].tolist(),
            "center_constraint_solimp": model.eq_solimp[center_constraint.id, :3].tolist(),
        },
        "gripper_collision_pads": gripper_pads,
        "tolerances": tolerances,
    }
    report["passed"] = bool(
        actual_names == expected_names
        and (model.nq, model.nv, model.nu, model.neq) == (9, 9, 7, 1)
        and model.opt.cone == mujoco.mjtCone.mjCONE_ELLIPTIC
        and float(model.opt.impratio) == 10.0
        and int(model.opt.noslip_iterations) == 0
        and joint_limit_error <= tolerances["joint_limit"]
        and zero_position_error <= tolerances["zero_position"]
        and max(position_errors) <= tolerances["position_m"]
        and max(orientation_errors) <= tolerances["orientation_rad"]
        and np.allclose(model.joint("gripper").range, [0.0, 0.1], atol=tolerances["joint_limit"])
        and np.allclose(model.tendon_range[aperture_tendon.id], [0.0, 0.1])
        and float(model.actuator_gainprm[aperture_actuator.id, 0]) == 1250.0
        and float(-model.actuator_biasprm[aperture_actuator.id, 1]) == 1250.0
        and float(-model.actuator_biasprm[aperture_actuator.id, 2]) == 30.0
        and np.array_equal(aperture_actuator.forcerange, [-8.0, 8.0])
        and float(model.tendon_stiffness[center_tendon.id]) == 0.0
        and np.allclose(model.eq_solref[center_constraint.id], [0.02, 1.0])
        and np.allclose(
            model.eq_solimp[center_constraint.id, :3], [0.9, 0.95, 0.001]
        )
        and all(
            float(model.joint(f"gripper_joint{index}").stiffness) == 0.0
            for index in (1, 2)
        )
        and all(
            values["contact_dimensions"] == 6
            and np.allclose(values["friction"], [1.5, 0.005, 0.0001])
            for values in gripper_pads.values()
        )
        and all(
            np.allclose(
                gripper_pads[f"gripper_pad{index}"]["position_m"],
                [0.0, -0.043, 0.001],
            )
            and np.allclose(
                gripper_pads[f"gripper_pad{index}"]["size_m"],
                [0.028, 0.033, 0.001],
            )
            for index in (1, 2)
        )
    )
    return report


def _rss_bytes() -> int:
    pages = int(Path("/proc/self/statm").read_text(encoding="utf-8").split()[1])
    return pages * os.sysconf("SC_PAGE_SIZE")


def _home_action() -> np.ndarray:
    return np.concatenate((HOME_D0["left"], HOME_D0["right"]))


def _reset_stress(env: gym.Env[Any, Any], resets: int) -> dict[str, Any]:
    processor = PiperXMujocoObservationProcessor()
    expected_state = _home_action().astype(np.float32)
    first_images: dict[str, np.ndarray] | None = None
    previous_images: dict[str, np.ndarray] | None = None
    previous_serial = 0
    maximum_state_error = 0.0
    maximum_cube_xy_error = 0.0
    maximum_penetration = 0.0
    rss_after_warmup = 0
    maximum_rss_after_warmup = 0

    for seed in range(resets):
        observation, info = env.reset(seed=seed)
        state = processor.observation(observation)["observation.state"]
        maximum_state_error = max(
            maximum_state_error, float(np.max(np.abs(state - expected_state)))
        )
        unwrapped = cast(PiperXDualCubeToMatchingPlateMujocoEnv, env.unwrapped)
        if not np.isfinite(unwrapped.data.qpos).all() or not np.isfinite(unwrapped.data.qvel).all():
            raise RuntimeError(f"non-finite state on reset {seed}")
        for side, xy in (("left", [0.52, 0.17]), ("right", [0.52, -0.17])):
            actual = unwrapped.data.body(f"{side}_cube").xpos[:2]
            maximum_cube_xy_error = max(
                maximum_cube_xy_error, float(np.max(np.abs(actual - np.asarray(xy))))
            )
        for contact_index in range(unwrapped.data.ncon):
            maximum_penetration = max(
                maximum_penetration, max(0.0, -float(unwrapped.data.contact[contact_index].dist))
            )
        images = observation["images"]
        if previous_images is not None:
            for role in ("left_wrist", "right_wrist"):
                if np.shares_memory(previous_images[role], images[role]):
                    raise RuntimeError(f"stale shared camera buffer on reset {seed}: {role}")
        serial = int(unwrapped._observation_capture_serial)
        if serial != previous_serial + 1:
            raise RuntimeError(f"non-contiguous capture serial on reset {seed}: {serial}")
        previous_serial = serial
        if first_images is None:
            first_images = {role: image.copy() for role, image in images.items()}
        previous_images = images
        if seed == min(99, resets - 1):
            rss_after_warmup = _rss_bytes()
            maximum_rss_after_warmup = rss_after_warmup
        if seed >= min(99, resets - 1):
            maximum_rss_after_warmup = max(maximum_rss_after_warmup, _rss_bytes())

    assert first_images is not None
    repeated, _ = env.reset(seed=777)
    repeated_serial = cast(
        PiperXDualCubeToMatchingPlateMujocoEnv, env.unwrapped
    )._observation_capture_serial
    repeated_again, _ = env.reset(seed=777)
    repeated_again_serial = cast(
        PiperXDualCubeToMatchingPlateMujocoEnv, env.unwrapped
    )._observation_capture_serial
    exact_same_seed = all(
        np.array_equal(repeated["qpos"][name], repeated_again["qpos"][name])
        for name in repeated["qpos"]
    ) and all(
        np.array_equal(repeated["images"][role], repeated_again["images"][role])
        for role in repeated["images"]
    )
    memory_growth = maximum_rss_after_warmup - rss_after_warmup
    return {
        "passed": bool(
            maximum_state_error <= 1e-4
            and maximum_cube_xy_error <= 1e-9
            and maximum_penetration <= 0.002
            and exact_same_seed
            and memory_growth <= 64 * 1024 * 1024
        ),
        "resets": resets,
        "maximum_home_state_error_d0": maximum_state_error,
        "maximum_cube_xy_error_m": maximum_cube_xy_error,
        "maximum_initial_penetration_m": maximum_penetration,
        "same_seed_post_settle_exact": exact_same_seed,
        "capture_serial_first": 1,
        "capture_serial_last": repeated_again_serial,
        "same_seed_capture_serial_delta": repeated_again_serial - repeated_serial,
        "rss_after_warmup_bytes": rss_after_warmup,
        "maximum_rss_after_warmup_bytes": maximum_rss_after_warmup,
        "maximum_rss_growth_after_warmup_bytes": memory_growth,
        "initial_image_sha256": {
            role: _sha256_array(image) for role, image in first_images.items()
        },
    }


def _step_determinism_diagnostics(
    env: PiperXDualCubeToMatchingPlateMujocoEnv, seed: int = 123
) -> dict[str, Any]:
    """Explain a Gymnasium same-seed step failure without weakening the check."""

    env.action_space.seed(seed)
    action = env.action_space.sample()
    env.reset(seed=seed)
    first_observation, *_ = env.step(action)
    first_qpos = env.data.qpos.copy()
    first_qvel = env.data.qvel.copy()

    env.reset(seed=seed)
    second_observation, *_ = env.step(action)
    state_differences = {
        name: float(
            np.max(np.abs(first_observation["qpos"][name] - second_observation["qpos"][name]))
        )
        for name in first_observation["qpos"]
    }
    image_differences = {}
    for role in first_observation["images"]:
        first = first_observation["images"][role]
        second = second_observation["images"][role]
        absolute = np.abs(first.astype(np.int16) - second.astype(np.int16))
        image_differences[role] = {
            "different_values": int(np.count_nonzero(absolute)),
            "maximum_channel_delta": int(absolute.max()),
            "first_sha256": _sha256_array(first),
            "second_sha256": _sha256_array(second),
        }
    return {
        "maximum_native_observation_difference": max(state_differences.values()),
        "native_observation_differences": state_differences,
        "maximum_qpos_difference": float(np.max(np.abs(first_qpos - env.data.qpos))),
        "maximum_qvel_difference": float(np.max(np.abs(first_qvel - env.data.qvel))),
        "image_differences": image_differences,
    }


def _camera_contract(env: gym.Env[Any, Any]) -> dict[str, Any]:
    observation, _ = env.reset(seed=0)
    unwrapped = cast(PiperXDualCubeToMatchingPlateMujocoEnv, env.unwrapped)
    model, data = unwrapped.model, unwrapped.data
    role_hashes = {role: _sha256_array(image) for role, image in observation["images"].items()}
    marker_offsets: dict[str, float] = {}
    optical_axis_lateral_errors: dict[str, float] = {}
    gripper_approach_axis_alignment: dict[str, float] = {}
    for role in ("left_wrist", "right_wrist"):
        camera_id = model.camera(role).id
        unwrapped.renderer.update_scene(
            data, camera=role, scene_option=unwrapped.render_options
        )
        rotation = data.cam_xmat[camera_id].reshape(3, 3)
        side = role.removesuffix("_wrist")
        gripper_rotation = data.body(f"{side}_gripper_base").xmat.reshape(3, 3)
        gripper_approach_axis_alignment[role] = float(
            np.dot(-rotation[:, 2], gripper_rotation[:, 2])
        )
        # Keep the projection probe in front of the near plane but before the
        # task geometry; the forward-facing v2 view intersects a target plate
        # at 0.15 m and would otherwise partially occlude the marker.
        marker_position = data.cam_xpos[camera_id] - 0.08 * rotation[:, 2]
        marker_camera = rotation.T @ (marker_position - data.cam_xpos[camera_id])
        optical_axis_lateral_errors[role] = float(np.linalg.norm(marker_camera[:2]))
        geom = unwrapped.renderer.scene.geoms[unwrapped.renderer.scene.ngeom]
        mujoco.mjv_initGeom(
            geom,
            mujoco.mjtGeom.mjGEOM_SPHERE,
            np.asarray([0.003, 0.0, 0.0]),
            marker_position,
            np.eye(3).reshape(-1),
            np.asarray([0.0, 1.0, 0.0, 1.0], dtype=np.float32),
        )
        unwrapped.renderer.scene.ngeom += 1
        frame = unwrapped.renderer.render()
        mask = (
            (frame[..., 1] > 100)
            & (frame[..., 1] > 1.4 * frame[..., 0])
            & (frame[..., 1] > 1.4 * frame[..., 2])
        )
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            raise RuntimeError(f"optical-axis marker not visible in {role}")
        centroid = np.asarray([float(xs.mean()), float(ys.mean())])
        center = np.asarray([(CAMERA_WIDTH - 1) / 2.0, (CAMERA_HEIGHT - 1) / 2.0])
        marker_offsets[role] = float(np.linalg.norm(centroid - center))

    action_processor = PiperXMujocoActionProcessor()
    baseline_positions = {
        role: data.cam_xpos[model.camera(role).id].copy() for role in ("left_wrist", "right_wrist")
    }
    left_action = _home_action()
    left_action[0] += 15.0
    for _ in range(PHYSICS_HZ // 4):
        env.step(action_processor.action(left_action))
    left_probe = {
        role: float(np.linalg.norm(data.cam_xpos[model.camera(role).id] - baseline_positions[role]))
        for role in baseline_positions
    }
    env.reset(seed=0)
    baseline_positions = {
        role: data.cam_xpos[model.camera(role).id].copy() for role in ("left_wrist", "right_wrist")
    }
    right_action = _home_action()
    right_action[7] -= 15.0
    for _ in range(30):
        env.step(action_processor.action(right_action))
    right_probe = {
        role: float(np.linalg.norm(data.cam_xpos[model.camera(role).id] - baseline_positions[role]))
        for role in baseline_positions
    }
    passed = bool(
        role_hashes["left_wrist"] != role_hashes["right_wrist"]
        and max(marker_offsets.values()) <= 8.0
        and max(optical_axis_lateral_errors.values()) <= 1e-12
        and min(gripper_approach_axis_alignment.values()) >= 0.999999
        and left_probe["left_wrist"] > 0.01
        and left_probe["right_wrist"] < 1e-8
        and right_probe["right_wrist"] > 0.01
        and right_probe["left_wrist"] < 1e-8
    )
    return {
        "passed": passed,
        "shape_hwc": [CAMERA_HEIGHT, CAMERA_WIDTH, 3],
        "dtype": "uint8",
        "role_image_sha256": role_hashes,
        "optical_axis_marker_center_offset_px": marker_offsets,
        "optical_axis_marker_lateral_error_m": optical_axis_lateral_errors,
        "gripper_approach_axis_alignment": gripper_approach_axis_alignment,
        "optical_axis_image_tolerance_px": 8.0,
        "left_joint_probe_camera_translation_m": left_probe,
        "right_joint_probe_camera_translation_m": right_probe,
    }


def _task_lifecycle(env: gym.Env[Any, Any]) -> dict[str, Any]:
    action_processor = PiperXMujocoActionProcessor()
    native_home = action_processor.action(_home_action())
    env.reset(seed=0)
    unwrapped = cast(PiperXDualCubeToMatchingPlateMujocoEnv, env.unwrapped)
    for side, y in (("left", 0.17), ("right", -0.17)):
        cube = unwrapped.data.joint(f"{side}_cube_free")
        cube.qpos[:3] = [0.72, y, 0.855]
        cube.qpos[3:] = [1.0, 0.0, 0.0, 0.0]
        cube.qvel[:] = 0.0
    mujoco.mj_forward(unwrapped.model, unwrapped.data)
    for _ in range(30):
        mujoco.mj_step(unwrapped.model, unwrapped.data)
    unwrapped._stable_ticks = {side: 0 for side in SIDES}
    terminated_tick = None
    final_success_info: dict[str, Any] = {}
    for tick in range(1, 6):
        _, reward, terminated, truncated, info = env.step(native_home)
        if terminated:
            terminated_tick = tick
            final_success_info = info
            if reward != 1.0 or truncated:
                raise RuntimeError("invalid success lifecycle")
            break

    env.reset(seed=0)
    saturated_action = np.full(14, 1e6, dtype=np.float64)
    _, _, _, _, saturation_info = env.step(saturated_action)
    env.reset(seed=0)
    native_home = action_processor.action(_home_action())
    final_timeout = (False, False)
    timeout_info: dict[str, Any] = {}
    for _ in range(HORIZON):
        _, _, terminated, truncated, timeout_info = env.step(native_home)
        final_timeout = (terminated, truncated)
        if terminated or truncated:
            break
    passed = bool(
        terminated_tick == 5
        and final_success_info.get("success") is True
        and saturation_info["native_action_saturated"] is True
        and final_timeout == (False, True)
        and timeout_info["control_tick"] == HORIZON
    )
    return {
        "passed": passed,
        "success_terminated_control_tick": terminated_tick,
        "success_stable_ticks": {
            side: final_success_info.get("sides", {}).get(side, {}).get("stable_ticks")
            for side in SIDES
        },
        "native_saturation_reported": saturation_info["native_action_saturated"],
        "timeout_control_tick": timeout_info.get("control_tick"),
        "timeout_terminated": final_timeout[0],
        "timeout_truncated": final_timeout[1],
    }


def _performance(env: gym.Env[Any, Any], ticks: int) -> dict[str, Any]:
    env.reset(seed=0)
    action = PiperXMujocoActionProcessor().action(_home_action())
    capture_indices: list[int] = []
    simulation_times: list[float] = []
    start = time.perf_counter()
    for _ in range(ticks):
        _, _, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            raise RuntimeError("performance episode ended unexpectedly")
        capture_indices.append(int(info["episode_capture_index"]))
        simulation_times.append(float(info["simulation_time_s"]))
    elapsed = time.perf_counter() - start
    rate = ticks / elapsed
    expected_indices = list(range(2, ticks + 2))
    expected_times = np.arange(1, ticks + 1, dtype=np.float64) / 30.0
    time_error = float(np.max(np.abs(np.asarray(simulation_times) - expected_times)))
    return {
        "passed": bool(
            rate >= 30.0 and capture_indices == expected_indices and time_error <= 1e-10
        ),
        "control_render_ticks": ticks,
        "elapsed_s": elapsed,
        "control_render_ticks_per_s": rate,
        "minimum_required_ticks_per_s": 30.0,
        "capture_indices_contiguous": capture_indices == expected_indices,
        "simulation_time_max_error_s": time_error,
        "physics_steps_per_control_tick": ACTION_REPEAT,
    }


def _contact_smoke() -> dict[str, Any]:
    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    for side, lateral_offset in (("left", 0.006), ("right", -0.006)):
        for index in range(1, 7):
            data.actuator(f"{side}_joint{index}_position").ctrl = data.joint(
                f"{side}_joint{index}"
            ).qpos
        _set_gripper_target(
            model, data, side, float(data.joint(f"{side}_gripper").qpos[0])
        )
    mujoco.mj_forward(model, data)
    for _ in range(PHYSICS_HZ):
        mujoco.mj_step(model, data)
    left_cube = data.joint("left_cube_free")
    midpoint = 0.5 * (data.body("left_gripper_link1").xpos + data.body("left_gripper_link2").xpos)
    left_cube.qpos[:3] = midpoint
    left_cube.qpos[3:] = [1.0, 0.0, 0.0, 0.0]
    left_cube.qvel[:] = 0.0
    _set_gripper_target(model, data, "left", 0.0)
    mujoco.mj_forward(model, data)
    cube_geom = model.geom("left_cube_geom").id
    robot_geoms = {
        geom_id
        for geom_id in range(model.ngeom)
        if model.body(int(model.geom_bodyid[geom_id])).name.startswith("left_")
        and model.body(int(model.geom_bodyid[geom_id])).name != "left_cube"
    }
    robot_contact_ticks = 0
    finite = True
    maximum_robot_cube_penetration = 0.0
    for _ in range(PHYSICS_HZ // 12):
        mujoco.mj_step(model, data)
        finite &= bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all())
        contacts = [
            data.contact[index]
            for index in range(data.ncon)
            if cube_geom in (data.contact[index].geom1, data.contact[index].geom2)
            and bool({data.contact[index].geom1, data.contact[index].geom2} & robot_geoms)
        ]
        if contacts:
            robot_contact_ticks += 1
            maximum_robot_cube_penetration = max(
                maximum_robot_cube_penetration,
                max(max(0.0, -float(contact.dist)) for contact in contacts),
            )

    left_cube.qpos[:3] = [0.52, 0.17, 0.847]
    left_cube.qpos[3:] = [1.0, 0.0, 0.0, 0.0]
    left_cube.qvel[:] = 0.0
    _set_gripper_target(model, data, "left", 0.05)
    mujoco.mj_forward(model, data)
    for _ in range(2 * PHYSICS_HZ):
        mujoco.mj_step(model, data)
        finite &= bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all())
    final_speed = float(np.linalg.norm(data.body("left_cube").cvel[3:]))
    return {
        "passed": bool(finite and robot_contact_ticks > 0 and final_speed < 0.01),
        "robot_cube_contact_ticks": robot_contact_ticks,
        "maximum_robot_cube_contact_penetration_m": maximum_robot_cube_penetration,
        "finite_state": finite,
        "released_and_settled_final_linear_speed_m_s": final_speed,
        "probe_semantics": "Settle at home, place the cube between the fingers, command close for a bounded contact impulse, then release to the canonical table pose and require finite settling without sustained oscillation.",
    }


def _open_aperture_retention() -> dict[str, Any]:
    """Verify open follower fingers do not wander during smooth arm motion."""

    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    home = {
        side: np.asarray(
            [data.joint(f"{side}_joint{index}").qpos[0] for index in range(1, 7)]
        )
        for side in SIDES
    }
    for side in SIDES:
        _set_gripper_target(model, data, side, 0.1)
    for _ in range(3 * PHYSICS_HZ):
        mujoco.mj_step(model, data)

    minimum_aperture = {side: 0.1 for side in SIDES}
    maximum_symmetry_error = {side: 0.0 for side in SIDES}
    amplitudes = np.deg2rad([10.0, 10.0, 10.0, 8.0, 8.0, 15.0])
    ticks = 300
    for tick in range(ticks):
        offset = amplitudes * np.sin(2.0 * np.pi * tick / ticks)
        for side in SIDES:
            for index in range(1, 7):
                data.actuator(f"{side}_joint{index}_position").ctrl = (
                    home[side][index - 1] + offset[index - 1]
                )
        for _ in range(ACTION_REPEAT):
            mujoco.mj_step(model, data)
        for side in SIDES:
            follower_1 = float(data.joint(f"{side}_gripper_joint1").qpos[0])
            follower_2 = float(data.joint(f"{side}_gripper_joint2").qpos[0])
            minimum_aperture[side] = min(
                minimum_aperture[side], follower_1 - follower_2
            )
            maximum_symmetry_error[side] = max(
                maximum_symmetry_error[side], 0.5 * abs(follower_1 + follower_2)
            )

    return {
        "passed": bool(
            min(minimum_aperture.values()) >= 0.095
            and max(maximum_symmetry_error.values()) < 0.003
            and np.isfinite(data.qpos).all()
            and np.isfinite(data.qvel).all()
        ),
        "control_ticks": ticks,
        "joint_motion_amplitude_deg": [10.0, 10.0, 10.0, 8.0, 8.0, 15.0],
        "minimum_follower_aperture_m": minimum_aperture,
        "minimum_allowed_aperture_m": 0.095,
        "maximum_finger_symmetry_error_m": maximum_symmetry_error,
        "maximum_allowed_finger_symmetry_error_m": 0.003,
    }


def _grasp_retention() -> dict[str, Any]:
    """Verify offset 40 mm cubes stay on the planar pads during wrist motion."""

    model = mujoco.MjModel.from_xml_path(str(SCENE_PATH))
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    mujoco.mj_forward(model, data)
    for side in SIDES:
        _set_gripper_target(model, data, side, 0.1)
    model.opt.gravity[:] = 0.0
    for _ in range(3 * PHYSICS_HZ):
        mujoco.mj_step(model, data)

    for side, lateral_offset in (("left", 0.006), ("right", -0.006)):
        base = data.body(f"{side}_gripper_base")
        rotation = base.xmat.reshape(3, 3).copy()
        quaternion = np.zeros(4)
        mujoco.mju_mat2Quat(quaternion, rotation.reshape(-1))
        cube = data.joint(f"{side}_cube_free")
        cube.qpos[:3] = base.xpos + rotation @ np.asarray(
            [0.0, lateral_offset, 0.108]
        )
        cube.qpos[3:] = quaternion
        cube.qvel[:] = 0.0
    mujoco.mj_forward(model, data)
    for side in SIDES:
        _set_gripper_target(model, data, side, 0.0)
    for _ in range(2 * PHYSICS_HZ):
        mujoco.mj_step(model, data)

    model.opt.gravity[:] = (0.0, 0.0, -9.81)
    for _ in range(PHYSICS_HZ):
        mujoco.mj_step(model, data)
    initial_relative = {}
    for side in SIDES:
        base = data.body(f"{side}_gripper_base")
        # Express the cube offset in the moving gripper frame; a world-frame
        # vector changes during the commanded wrist roll even without slip.
        initial_relative[side] = base.xmat.reshape(3, 3).T @ (
            data.body(f"{side}_cube").xpos - base.xpos
        )
    joint6_home = {
        side: float(data.joint(f"{side}_joint6").qpos[0]) for side in SIDES
    }
    maximum_shift = {side: 0.0 for side in SIDES}
    maximum_symmetry_error = {side: 0.0 for side in SIDES}
    contact_ticks = {side: 0 for side in SIDES}
    ticks = 300
    for tick in range(ticks):
        offset = math.radians(5.0) * math.sin(2.0 * math.pi * tick / 120.0)
        for side in SIDES:
            data.actuator(f"{side}_joint6_position").ctrl = joint6_home[side] + offset
        for _ in range(ACTION_REPEAT):
            mujoco.mj_step(model, data)
        for side in SIDES:
            cube_geom = model.geom(f"{side}_cube_geom").id
            has_contact = any(
                cube_geom in (data.contact[index].geom1, data.contact[index].geom2)
                for index in range(data.ncon)
            )
            contact_ticks[side] += int(has_contact)
            base = data.body(f"{side}_gripper_base")
            relative = base.xmat.reshape(3, 3).T @ (
                data.body(f"{side}_cube").xpos - base.xpos
            )
            maximum_shift[side] = max(
                maximum_shift[side],
                float(np.linalg.norm(relative - initial_relative[side])),
            )
            follower_1 = float(data.joint(f"{side}_gripper_joint1").qpos[0])
            follower_2 = float(data.joint(f"{side}_gripper_joint2").qpos[0])
            maximum_symmetry_error[side] = max(
                maximum_symmetry_error[side], 0.5 * abs(follower_1 + follower_2)
            )

    passed = bool(
        all(contact_ticks[side] == ticks for side in SIDES)
        and max(maximum_shift.values()) < 0.02
        and max(maximum_symmetry_error.values()) < 0.01
        and np.isfinite(data.qpos).all()
        and np.isfinite(data.qvel).all()
    )
    return {
        "passed": passed,
        "control_ticks": ticks,
        "wrist_roll_amplitude_deg": 5.0,
        "cube_contact_ticks": contact_ticks,
        "relative_shift_frame": "moving_gripper",
        "maximum_cube_relative_shift_m": maximum_shift,
        "maximum_finger_symmetry_error_m": maximum_symmetry_error,
        "maximum_allowed_relative_shift_m": 0.02,
        "maximum_allowed_finger_symmetry_error_m": 0.01,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resets", type=int, default=1000)
    parser.add_argument("--performance-ticks", type=int, default=180)
    parser.add_argument(
        "--result", type=Path, default=ROOT / "docs/project/GATE_M1_RUNTIME_RESULT.json"
    )
    parser.add_argument(
        "--parity", type=Path, default=ROOT / "docs/project/GATE_M1_PARITY_REPORT.json"
    )
    args = parser.parse_args()
    if args.resets < 1000:
        parser.error("Gate M1 evidence requires at least 1000 resets")
    if args.performance_ticks < 60:
        parser.error("Gate M1 performance evidence requires at least 60 ticks")

    gl = _renderer_identity()
    parity = _embodiment_parity()
    check_target = gym.make(ENV_ID, render_mode="rgb_array").unwrapped
    try:
        try:
            check_env(check_target, skip_render_check=False)
        except AssertionError as error:
            diagnostics = _step_determinism_diagnostics(check_target)
            raise AssertionError(
                f"{error}; same_seed_step_diagnostics={json.dumps(diagnostics, sort_keys=True)}"
            ) from error
    finally:
        check_target.close()

    env = gym.make(ENV_ID, render_mode="rgb_array")
    try:
        reset_stress = _reset_stress(env, args.resets)
        camera = _camera_contract(env)
        lifecycle = _task_lifecycle(env)
        performance = _performance(env, args.performance_ticks)
    finally:
        env.close()
    contact = _contact_smoke()
    open_aperture = _open_aperture_retention()
    grasp = _grasp_retention()

    checks = {
        "embodiment_parity": parity["passed"],
        "gymnasium_checker": True,
        "reset_stress": reset_stress["passed"],
        "camera_contract": camera["passed"],
        "task_lifecycle": lifecycle["passed"],
        "contact_smoke": contact["passed"],
        "open_aperture_retention": open_aperture["passed"],
        "grasp_retention": grasp["passed"],
        "performance": performance["passed"],
        "nvidia_egl": gl["vendor"] == "NVIDIA Corporation",
    }
    result = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "gate": "M1",
        "passed": all(checks.values()),
        "checks": checks,
        "environment_id": ENV_ID,
        "processor_revision": PROCESSOR_REVISION,
        "runtime": {
            "mujoco_version": mujoco.__version__,
            "gymnasium_version": gym.__version__,
            "python_gl": gl,
        },
        "provenance_sha256": {
            str(path.relative_to(ROOT)): _sha256_file(path)
            for path in (
                Path(__file__).resolve(),
                ROOT / "configs/mujoco_m1_runtime.yaml",
                ROOT / "uv.lock",
                SCENE_PATH,
                ARM_PATH.parent / "manifest.json",
                ROOT / "packages/lerobot_env_piperx_mujoco/src/lerobot_env_piperx_mujoco/env.py",
                ROOT
                / "packages/lerobot_env_piperx_mujoco/src/lerobot_env_piperx_mujoco/processors.py",
            )
        },
        "reset_stress": reset_stress,
        "camera_contract": camera,
        "task_lifecycle": lifecycle,
        "contact_smoke": contact,
        "open_aperture_retention": open_aperture,
        "grasp_retention": grasp,
        "performance": performance,
    }
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.parity.write_text(json.dumps(parity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
