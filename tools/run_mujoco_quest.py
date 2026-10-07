#!/usr/bin/env python3
"""Run the accepted M1 MuJoCo scene from Meta Quest 3 controllers and panels."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, cast
import xml.etree.ElementTree as ET

import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_CONFIG = ROOT / "configs/mujoco_quest_runtime.yaml"
_CLOUDXR_WSS_HOST = "127.0.0.1"
_CLOUDXR_WSS_PORT = 48322
_CLOUDXR_WSS_READY_TIMEOUT_S = 10.0
_CLOUDXR_WEB_CLIENT_URL = "https://nvidia.github.io/IsaacTeleop/client/v1.3.131/"


def _load_config(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one YAML mapping")
    return value


def _check_versions(config: dict[str, Any]) -> dict[str, str]:
    expected = config["environment"]
    actual = {
        "mujoco_version": importlib.metadata.version("mujoco"),
        "lerobot_version": importlib.metadata.version("lerobot"),
        "placo_version": importlib.metadata.version("placo"),
        "isaacteleop_version": importlib.metadata.version("isaacteleop"),
    }
    from isaacteleop.cloudxr.runtime import runtime_version

    actual["cloudxr_runtime_version"] = runtime_version()
    mismatches = {
        name: {"expected": str(expected[name]), "actual": actual[name]}
        for name in actual
        if actual[name] != str(expected[name])
    }
    if mismatches:
        raise RuntimeError(f"MuJoCo Quest upstream version mismatch: {mismatches}")
    return actual


def _host_connection_hint() -> dict[str, str | None]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("8.8.8.8", 80))
            host = sock.getsockname()[0]
        except OSError:
            host = None
    return {
        "quest_client": _CLOUDXR_WEB_CLIENT_URL,
        "certificate": f"https://{host}:{_CLOUDXR_WSS_PORT}/" if host else None,
        "host_ipv4": host,
    }


def _wait_for_cloudxr_wss(
    *,
    host: str = _CLOUDXR_WSS_HOST,
    port: int = _CLOUDXR_WSS_PORT,
    timeout_s: float = _CLOUDXR_WSS_READY_TIMEOUT_S,
    process: subprocess.Popen[bytes] | None = None,
) -> None:
    """Wait until the separately scheduled CloudXR WSS proxy is listening."""
    deadline = time.monotonic() + timeout_s
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(
                f"CloudXR process exited before WSS became ready (code {process.returncode})"
            )
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError(
        f"CloudXR WSS proxy did not listen on {host}:{port} within {timeout_s:.1f}s"
    ) from last_error


class _CloudXRSubprocess:
    """Own the upstream CloudXR CLI outside Televiz's blocking process."""

    def __init__(
        self,
        *,
        install_dir: str,
        env_file: str | None,
        accept_eula: bool,
    ) -> None:
        self.command = [
            sys.executable,
            "-m",
            "isaacteleop.cloudxr",
            "--cloudxr-install-dir",
            install_dir,
        ]
        if env_file is not None:
            self.command.extend(["--cloudxr-env-config", env_file])
        if accept_eula:
            self.command.append("--accept-eula")
        self.process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> "_CloudXRSubprocess":
        self.process = subprocess.Popen(self.command, start_new_session=True)
        try:
            _wait_for_cloudxr_wss(process=self.process)
        except BaseException:
            self.stop()
            raise
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=15.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)


def _build_solvers() -> tuple[tempfile.TemporaryDirectory[str], dict[str, Any]]:
    from lerobot.model import RobotKinematics
    from tools.verify_piperx_model import MODEL_CONTRACT_PATH, _compose_model, _load_yaml

    temporary = tempfile.TemporaryDirectory(prefix="piperx-mujoco-quest-")
    contract = _load_yaml(MODEL_CONTRACT_PATH)
    model = _compose_model(contract)
    urdf_path = Path(temporary.name) / "piper_x_quest_kinematics.urdf"
    ET.ElementTree(model).write(urdf_path, encoding="utf-8", xml_declaration=True)
    spec = contract["kinematics"]
    solvers = {
        side: RobotKinematics(str(urdf_path), spec["target_frame"], spec["joint_names"])
        for side in ("left", "right")
    }
    return temporary, solvers


def _normalize_quaternion_wxyz(value: Any, *, label: str) -> np.ndarray:
    quaternion = np.asarray(value, dtype=np.float64)
    if quaternion.shape != (4,) or not np.isfinite(quaternion).all():
        raise ValueError(f"{label} must be one finite WXYZ quaternion")
    norm = float(np.linalg.norm(quaternion))
    if norm <= 1.0e-8:
        raise ValueError(f"{label} must not be a zero quaternion")
    return quaternion / norm


def _quaternion_multiply_wxyz(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return np.asarray(
        [
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        ],
        dtype=np.float64,
    )


def _rotate_vector_wxyz(quaternion: np.ndarray, vector: np.ndarray) -> np.ndarray:
    w = float(quaternion[0])
    xyz = quaternion[1:]
    return (
        vector
        + 2.0 * w * np.cross(xyz, vector)
        + 2.0 * np.cross(xyz, np.cross(xyz, vector))
    )


def _head_relative_stage_pose(
    head_pose: Any,
    position_head_m: Any,
    orientation_head_wxyz: Any,
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    """Freeze one head-relative panel pose into upstream OpenXR stage space."""

    head_position = np.asarray(head_pose.position, dtype=np.float64)
    local_position = np.asarray(position_head_m, dtype=np.float64)
    if (
        head_position.shape != (3,)
        or local_position.shape != (3,)
        or not np.isfinite(head_position).all()
        or not np.isfinite(local_position).all()
    ):
        raise ValueError("head and panel positions must be finite XYZ vectors")
    head_orientation = _normalize_quaternion_wxyz(
        head_pose.orientation, label="head orientation"
    )
    local_orientation = _normalize_quaternion_wxyz(
        orientation_head_wxyz, label="panel orientation"
    )
    stage_position = head_position + _rotate_vector_wxyz(head_orientation, local_position)
    stage_orientation = _quaternion_multiply_wxyz(head_orientation, local_orientation)
    stage_orientation = _normalize_quaternion_wxyz(
        stage_orientation, label="composed panel orientation"
    )
    return tuple(stage_position.tolist()), tuple(stage_orientation.tolist())


class _CudaRgbaFrame:
    """Own one CUDA upload long enough for Televiz to consume it."""

    def __init__(self, width: int, height: int, televiz: Any, torch: Any) -> None:
        self.width = width
        self.height = height
        self.televiz = televiz
        self.torch = torch
        self.tensor: Any | None = None
        self.buffer = televiz.VizBuffer()
        self.buffer.width = width
        self.buffer.height = height
        self.buffer.pitch = width * 4
        self.buffer.format = televiz.PixelFormat.kRGBA8
        self.buffer.space = televiz.MemorySpace.kDevice

    def upload(self, rgb: np.ndarray) -> tuple[Any, int]:
        image = np.asarray(rgb)
        if image.shape != (self.height, self.width, 3) or image.dtype != np.uint8:
            raise ValueError(
                f"XR camera image has unexpected shape/dtype: {image.shape}/{image.dtype}"
            )
        rgba = np.empty((self.height, self.width, 4), dtype=np.uint8)
        rgba[:, :, :3] = image
        rgba[:, :, 3] = 255
        self.tensor = self.torch.from_numpy(rgba).to(device="cuda", non_blocking=False)
        self.buffer.data = int(self.tensor.data_ptr())
        stream = int(self.torch.cuda.current_stream().cuda_stream)
        return self.buffer, stream


class _QuestPanels:
    def __init__(self, config: dict[str, Any], required_extensions: list[str]) -> None:
        import isaacteleop.viz as televiz
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("Quest Televiz panels require a CUDA-capable GPU")
        self.televiz = televiz
        self.torch = torch
        presentation = config["xr_presentation"]
        session_cfg = televiz.VizSessionConfig()
        session_cfg.mode = televiz.DisplayMode.kXr
        session_cfg.app_name = "PiperXMujocoQuestTeleop"
        session_cfg.xr_near_z = float(presentation["near_m"])
        session_cfg.xr_far_z = float(presentation["far_m"])
        session_cfg.xr_system_wait_seconds = int(presentation["system_wait_s"])
        session_cfg.required_extensions = required_extensions
        session_cfg.clear_color = tuple(float(v) for v in presentation["clear_rgba"])
        self.session = televiz.VizSession.create(session_cfg)
        self.layers: dict[str, Any] = {}
        self.uploaders: dict[str, _CudaRgbaFrame] = {}
        self.blank = np.zeros((480, 640, 3), dtype=np.uint8)
        try:
            head_pose = self._wait_for_head_pose(float(presentation["head_pose_wait_s"]))
            for name, layer_spec in presentation["layers"].items():
                layer_cfg = televiz.QuadLayerConfig()
                layer_cfg.name = f"piper_x_{name}"
                layer_cfg.resolution = televiz.Resolution(640, 480)
                layer_cfg.format = televiz.PixelFormat.kRGBA8
                layer_cfg.generate_mipmaps = True
                position, orientation = _head_relative_stage_pose(
                    head_pose,
                    layer_spec["position_head_m"],
                    layer_spec["orientation_head_wxyz"],
                )
                pose = televiz.Pose3D(position=position, orientation=orientation)
                layer_cfg.placement = televiz.QuadLayerPlacement(
                    pose=pose,
                    size_meters=tuple(float(v) for v in layer_spec["size_m"]),
                )
                self.layers[name] = self.session.add_quad_layer(layer_cfg)
                self.uploaders[name] = _CudaRgbaFrame(640, 480, televiz, torch)
        except BaseException:
            self.session.destroy()
            raise

    def _wait_for_head_pose(self, timeout_s: float) -> Any:
        if not np.isfinite(timeout_s) or timeout_s <= 0.0:
            raise ValueError("head_pose_wait_s must be finite and positive")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            pose = self.session.head_pose_now()
            if pose is not None:
                return pose
            if self.session.should_close():
                raise RuntimeError("XR session closed before a valid head pose was available")
            self.session.render()
        raise RuntimeError(
            "Televiz did not provide a valid head pose for initial panel placement "
            f"within {timeout_s:.1f}s"
        )

    def oxr_handles(self) -> Any:
        from isaacteleop.oxr import OpenXRSessionHandles

        handles = self.session.get_oxr_handles()
        if handles is None:
            raise RuntimeError("Televiz did not create OpenXR handles")
        return OpenXRSessionHandles(*handles)

    def present(self, scene: np.ndarray, images: dict[str, np.ndarray]) -> None:
        frames = {
            "scene": scene,
            "left_wrist": images["left_wrist"],
            "right_wrist": images["right_wrist"],
        }
        for name, frame in frames.items():
            buffer, stream = self.uploaders[name].upload(frame)
            self.layers[name].submit(buffer, stream=stream)
        self.session.render()

    def present_blank(self) -> None:
        self.present(
            self.blank,
            {"left_wrist": self.blank, "right_wrist": self.blank},
        )

    def close(self) -> None:
        self.session.destroy()


def _close_runtime_resources(
    panels: Any | None,
    env: Any | None,
    temporary: Any | None,
    cloudxr: _CloudXRSubprocess | None,
) -> list[str]:
    """Release each owner in order, recording failures instead of aborting.

    MuJoCo owns an EGL context on the process display while Televiz owns the
    Vulkan/XR session that talks to the same driver, so ``env.close()`` runs
    first: destroying the panels first left MuJoCo's ``eglDestroyContext``
    raising ``EGL_NOT_INITIALIZED``, and that exception escaped :func:`run`
    before the final ``mujoco_quest_finished`` report was printed. CloudXR
    stops last because Televiz and MuJoCo still own live IPC and EGL resources
    while their graphics are torn down. Every owner is attempted even when an
    earlier one fails, so one bad teardown can no longer orphan the rest.
    """

    failures: list[str] = []

    def _release(label: str, action: Callable[[], None]) -> None:
        try:
            action()
        except BaseException as error:  # noqa: BLE001 - teardown must not abort
            failures.append(f"{label}: {type(error).__name__}: {error}")

    def _retire_failed_mujoco_renderer() -> None:
        """Prevent upstream destructors from retrying an invalid EGL handle.

        MuJoCo 3.9.0 only clears ``GLContext._context`` after a successful
        ``eglDestroyContext``. If the shared display has already become
        uninitialized, its Renderer and GLContext destructors otherwise retry
        the same failing call twice during interpreter shutdown. The context is
        already unusable in that failure mode, so this Quest-local teardown
        guard only clears those upstream ownership handles; it does not alter
        rendering during the session or the accepted M1 environment.
        """

        if env is None:
            return
        native_env = getattr(env, "unwrapped", env)
        renderer = getattr(native_env, "renderer", None)
        if renderer is None:
            return
        gl_context = getattr(renderer, "_gl_context", None)
        if gl_context is not None and hasattr(gl_context, "_context"):
            gl_context._context = None
        renderer._gl_context = None
        mjr_context = getattr(renderer, "_mjr_context", None)
        if mjr_context is not None:
            try:
                mjr_context.free()
            except BaseException:  # noqa: BLE001 - invalid graphics teardown
                pass
        renderer._mjr_context = None

    if env is not None:
        failure_count = len(failures)
        _release("env", env.close)
        if len(failures) != failure_count:
            _retire_failed_mujoco_renderer()
    if panels is not None:
        _release("panels", panels.close)
    if temporary is not None:
        _release("temporary", temporary.cleanup)
    if cloudxr is not None:
        _release("cloudxr", cloudxr.stop)
    return failures


def _processor_config(config: dict[str, Any]) -> Any:
    from tools.isaac_s2_processor import S2ProcessorConfig, SensitivityMode

    control = config["control"]
    sensitivity = control["sensitivity"]
    gripper = control["gripper"]
    return S2ProcessorConfig(
        normal_translation_scale=float(sensitivity["modes"]["normal"]["translation_scale"]),
        normal_rotation_scale=float(sensitivity["modes"]["normal"]["rotation_scale"]),
        precise_translation_scale=float(sensitivity["modes"]["precise"]["translation_scale"]),
        precise_rotation_scale=float(sensitivity["modes"]["precise"]["rotation_scale"]),
        initial_sensitivity_mode=cast(SensitivityMode, str(sensitivity["initial_mode"])),
        sensitivity_toggle_threshold=float(sensitivity["toggle_threshold"]),
        clutch_threshold=float(control["clutch"]["threshold"]),
        gripper_trigger_min=float(gripper["trigger_input_range"][0]),
        gripper_trigger_max=float(gripper["trigger_input_range"][1]),
        gripper_open_m=float(gripper["open_aperture_m"]),
        gripper_closed_m=float(gripper["closed_aperture_m"]),
        reset_gripper_m=float(gripper["reset_aperture_m"]),
    )


def _diagnostic_arm(sample: Any, command: Any) -> dict[str, Any]:
    return {
        "available": sample.available,
        "grip_pose_valid": sample.grip_pose_valid,
        "squeeze": round(sample.squeeze_value, 4),
        "trigger": round(sample.trigger_value, 4),
        "delta_position_m": np.round(sample.delta_position_m, 5).tolist(),
        "delta_rotation_rad": np.round(sample.delta_rotation_rotvec_rad, 5).tolist(),
        "scaled_delta_pose": np.round(command.delta_pose, 5).tolist(),
        "tracking_valid": command.tracking_valid,
        "clutch_active": command.clutch_active,
        "transition": command.transition,
    }


def _missing_controller_tracking(sample: Any) -> tuple[str, ...]:
    """Return controllers that cannot provide one usable grip pose."""

    return tuple(
        side
        for side in ("left", "right")
        if not (
            bool(getattr(sample, side).available)
            and bool(getattr(sample, side).grip_pose_valid)
        )
    )


def _gripper_plant_diagnostics(native_env: Any) -> dict[str, dict[str, Any]]:
    """Expose aperture-tendon tracking and compliant finger common mode."""

    diagnostics: dict[str, dict[str, Any]] = {}
    for side in ("left", "right"):
        follower_1 = float(native_env.data.joint(f"{side}_gripper_joint1").qpos[0])
        follower_2 = float(native_env.data.joint(f"{side}_gripper_joint2").qpos[0])
        actuator_id = native_env.model.actuator(
            f"{side}_gripper_aperture_position"
        ).id
        aperture = follower_1 - follower_2
        target = float(native_env.data.ctrl[actuator_id])
        force = float(native_env.data.actuator_force[actuator_id])
        force_range = native_env.model.actuator_forcerange[actuator_id]
        diagnostics[side] = {
            "finger_aperture_mm": 1000.0 * aperture,
            "aperture_tracking_error_mm": 1000.0 * abs(aperture - target),
            "finger_center_offset_mm": 500.0 * (follower_1 + follower_2),
            "aperture_target_mm": 1000.0 * target,
            "aperture_actuator_force_n": force,
            "force_limited": (
                force <= 0.99 * float(force_range[0])
                or force >= 0.99 * float(force_range[1])
            ),
        }
    return diagnostics


def _arm_plant_diagnostics(
    native_env: Any,
    current_state: np.ndarray,
    target: np.ndarray | None,
    last_ik_result: Any | None,
) -> dict[str, dict[str, Any]]:
    """Report per-joint target, response, saturation, and force for asymmetry diagnosis."""

    diagnostics: dict[str, dict[str, Any]] = {}
    for side, offset in (("left", 0), ("right", 7)):
        measured = np.asarray(current_state[offset : offset + 6], dtype=np.float64)
        desired = measured if target is None else np.asarray(target[offset : offset + 6])
        saturated = (
            np.zeros(6, dtype=np.bool_)
            if last_ik_result is None
            else np.asarray(last_ik_result.saturation_mask[offset : offset + 6])
        )
        diagnostics[side] = {
            "target_joint_deg": np.round(desired, 3).tolist(),
            "measured_joint_deg": np.round(measured, 3).tolist(),
            "joint_error_deg": np.round(desired - measured, 3).tolist(),
            "joint_saturated": saturated.tolist(),
            "actuator_force_nm": [
                round(
                    float(
                        native_env.data.actuator_force[
                            native_env.model.actuator(
                                f"{side}_joint{index}_position"
                            ).id
                        ]
                    ),
                    3,
                )
                for index in range(1, 7)
            ],
            "ik_failed": bool(
                last_ik_result is not None and last_ik_result.ik_failed[side]
            ),
        }
    return diagnostics


def run(args: argparse.Namespace) -> int:
    os.environ.setdefault("MUJOCO_GL", "egl")

    import gymnasium as gym
    import isaacteleop.deviceio as deviceio
    from isaacteleop.cloudxr.env_config import EnvConfig
    from isaacteleop.retargeting_engine.interface import ExecutionState
    from isaacteleop.teleop_session_manager import TeleopSession, TeleopSessionConfig
    import lerobot_env_piperx_mujoco  # noqa: F401
    from lerobot_env_piperx_mujoco.processors import (
        PiperXMujocoActionProcessor,
        PiperXMujocoObservationProcessor,
    )
    from lerobot_env_piperx_mujoco.teleop import (
        PiperXMujocoQuestIkProcessor,
        QuestGripperActuatorConfig,
        QuestIkConfig,
        configure_quest_gripper_actuators,
    )
    from tools.isaac_s2_processor import BimanualS2TeleopProcessor
    from tools.mujoco_quest_upstream import (
        PIPELINE_REVISION,
        build_mujoco_quest_pipeline,
        unpack_pipeline_output,
    )

    config = _load_config(args.config)
    versions = _check_versions(config)
    pipeline = build_mujoco_quest_pipeline()
    extensions = deviceio.DeviceIOSession.get_required_extensions(
        [pipeline.controllers.get_tracker(), pipeline.control_source.get_tracker()]
    )
    env: Any = gym.make(
        config["environment"]["gymnasium_id"],
        render_mode="rgb_array",
        terminate_on_task_end=False,
    )
    native_env = cast(Any, env.unwrapped)
    gripper_actuator = config["control"]["gripper"]["actuator"]
    gripper_actuator_config = QuestGripperActuatorConfig(
        aperture_kp=float(gripper_actuator["aperture_kp"]),
        aperture_kv=float(gripper_actuator["aperture_kv"]),
        aperture_force_limit_n=float(gripper_actuator["aperture_force_limit_n"]),
        finger_armature_kg=float(gripper_actuator["finger_armature_kg"]),
        finger_damping_n_s_m=float(gripper_actuator["finger_damping_n_s_m"]),
        center_constraint_timeconst_s=float(
            gripper_actuator["center_constraint_timeconst_s"]
        ),
        center_constraint_damping_ratio=float(
            gripper_actuator["center_constraint_damping_ratio"]
        ),
    )
    configure_quest_gripper_actuators(native_env.model, gripper_actuator_config)
    action_processor = PiperXMujocoActionProcessor()
    observation_processor = PiperXMujocoObservationProcessor()
    state_processor = BimanualS2TeleopProcessor(_processor_config(config))
    temporary, solvers = _build_solvers()
    ik_spec = config["control"]["ik"]
    ik_processor = PiperXMujocoQuestIkProcessor(
        solvers,
        QuestIkConfig(
            position_weight=float(ik_spec["position_weight"]),
            orientation_weight=float(ik_spec["orientation_weight"]),
            controller_rotation_enabled=ik_spec["controller_rotation_enabled"],
            rotation_activation_threshold_rad=float(
                ik_spec["rotation_activation_threshold_rad"]
            ),
            iterations_per_tick=int(ik_spec["iterations_per_tick"]),
            max_translation_delta_m=float(ik_spec["max_translation_delta_m"]),
            max_rotation_delta_rad=float(ik_spec["max_rotation_delta_rad"]),
            max_joint_step_deg=float(ik_spec["max_joint_step_deg"]),
            max_joint_tracking_error_deg=float(ik_spec["max_joint_tracking_error_deg"]),
            minimum_translation_alignment=float(
                ik_spec["minimum_translation_alignment"]
            ),
            max_gripper_step_mm=float(ik_spec["max_gripper_step_mm"]),
            gripper_arm_open_threshold_mm=float(
                ik_spec["gripper_arm_open_threshold_mm"]
            ),
        ),
    )
    reset_threshold = float(config["control"]["reset"]["threshold"])
    tracking_startup_timeout_s = float(
        config["control"]["lifecycle"]["required_tracking_startup_timeout_s"]
    )
    if tracking_startup_timeout_s <= 0.0:
        raise ValueError("required_tracking_startup_timeout_s must be positive")
    control_period_s = 1.0 / float(config["control"]["fps"])
    observation, _ = env.reset(seed=0)
    current_state = observation_processor.observation(observation)["observation.state"]
    state_processor.reset()
    ik_processor.reset(current_state)
    previous_reset_pressed = False
    tracked_frames = {"left": 0, "right": 0}
    saturation_counts = {
        "any": 0,
        "cartesian": 0,
        "joint": 0,
        "gripper": 0,
        "gripper_force": 0,
    }
    ik_failure_frames = 0
    loop_overruns = 0
    steps = 0
    session_frames = 0
    session_started_ever = False
    final_execution_state = ExecutionState.STOPPED.value
    explicit_resets = 0
    last_ik_result: Any | None = None
    tracking_gate_ready = not args.require_tracking
    tracking_gate_deadline: float | None = None
    started = time.monotonic()

    print(json.dumps({"event": "quest_connection", **_host_connection_hint()}, sort_keys=True))
    print(
        json.dumps(
            {
                "event": "mujoco_quest_starting",
                "profile": config["revision"],
                "pipeline": PIPELINE_REVISION,
                "versions": versions,
                "e2_started": False,
                "real_robot_motion": False,
            },
            sort_keys=True,
        )
    )

    panels: _QuestPanels | None = None
    cloudxr: _CloudXRSubprocess | None = None
    teardown_failures: list[str] = []
    try:
        EnvConfig.from_args(args.cloudxr_install_dir, args.cloudxr_env_file)
        if not args.no_auto_launch_cloudxr:
            cloudxr = _CloudXRSubprocess(
                install_dir=args.cloudxr_install_dir,
                env_file=args.cloudxr_env_file,
                accept_eula=args.accept_cloudxr_eula,
            )
            cloudxr.__enter__()
        else:
            _wait_for_cloudxr_wss()
        panels = _QuestPanels(config, extensions)
        teleop_config = TeleopSessionConfig(
            app_name="PiperXMujocoQuestTeleop",
            pipeline=pipeline.graph,
            teleop_control_pipeline=pipeline.control_graph,
            oxr_handles=panels.oxr_handles(),
        )
        with TeleopSession(teleop_config) as session:
            try:
                next_control_deadline = time.monotonic()
                while args.max_control_steps == 0 or steps < args.max_control_steps:
                    output = session.step()
                    session_frames += 1
                    events = session.last_context.execution_events
                    final_execution_state = events.execution_state.value
                    session_active = events.execution_state == ExecutionState.RUNNING
                    sample = unpack_pipeline_output(output)
                    # Controllers remain live while the WebXR menu is paused.
                    # Clear both the relative pose and the upstream smoothing
                    # tail on every inactive frame so menu-pointing motion
                    # cannot leak into the first running control interval.
                    if not session_active:
                        for retargeter in pipeline.pose_retargeters.values():
                            retargeter.reset_relative_reference()
                    command = state_processor.advance(
                        sample.left,
                        sample.right,
                        session_active=session_active,
                    )

                    if args.require_tracking and not tracking_gate_ready:
                        missing_tracking = _missing_controller_tracking(sample)
                        if session_active and not missing_tracking:
                            # Rebase every stateful edge before the first
                            # bimanual command. No one-arm motion accumulated
                            # while waiting is allowed into the actuator target.
                            state_processor.reset()
                            ik_processor.reset(current_state)
                            for retargeter in pipeline.pose_retargeters.values():
                                retargeter.reset_relative_reference()
                            command = state_processor.advance(
                                sample.left,
                                sample.right,
                                session_active=True,
                            )
                            tracking_gate_ready = True
                            tracking_gate_deadline = None
                        elif session_active:
                            now = time.monotonic()
                            if tracking_gate_deadline is None:
                                tracking_gate_deadline = now + tracking_startup_timeout_s
                            elif now >= tracking_gate_deadline:
                                missing = ", ".join(missing_tracking)
                                raise RuntimeError(
                                    "required Quest controller tracking unavailable "
                                    f"after {tracking_startup_timeout_s:.1f}s: {missing}"
                                )
                        else:
                            tracking_gate_deadline = None
                    tracked_frames["left"] += int(command.left.tracking_valid)
                    tracked_frames["right"] += int(command.right.tracking_valid)

                    reset_pressed = sample.right_primary_click > reset_threshold
                    controller_reset = reset_pressed and not previous_reset_pressed
                    previous_reset_pressed = reset_pressed
                    if controller_reset:
                        pipeline.control_processor.inject_reset(pause=False)

                    if events.reset:
                        observation, _ = env.reset(seed=0)
                        state_processor.reset()
                        current_state = observation_processor.observation(observation)[
                            "observation.state"
                        ]
                        ik_processor.reset(current_state)
                        for retargeter in pipeline.pose_retargeters.values():
                            retargeter.reset_relative_reference()
                        last_ik_result = None
                        explicit_resets += 1
                    elif session_active and tracking_gate_ready:
                        session_started_ever = True
                        last_ik_result = ik_processor.action(current_state, command)
                        saturation_counts["cartesian"] += int(last_ik_result.cartesian_saturated)
                        saturation_counts["joint"] += int(last_ik_result.joint_saturated)
                        saturation_counts["gripper"] += int(last_ik_result.gripper_saturated)
                        ik_failure_frames += int(any(last_ik_result.ik_failed.values()))
                        native_action = action_processor.action(last_ik_result.d0_action)
                        observation, _, terminated, truncated, _ = env.step(native_action)
                        if terminated or truncated:
                            raise RuntimeError(
                                "continuous Quest profile unexpectedly ended the M1 episode"
                            )
                        current_state = observation_processor.observation(observation)[
                            "observation.state"
                        ]
                        plant = _gripper_plant_diagnostics(native_env)
                        force_limited = any(
                            bool(values["force_limited"]) for values in plant.values()
                        )
                        saturation_counts["gripper_force"] += int(force_limited)
                        saturation_counts["any"] += int(
                            last_ik_result.saturated or force_limited
                        )
                        steps += 1

                    if session_started_ever:
                        scene = native_env.render()
                        if scene is None:
                            raise RuntimeError("M1 scene camera returned no RGB frame")
                        if not isinstance(scene, np.ndarray):
                            raise RuntimeError(
                                f"M1 scene camera returned unexpected value: {type(scene).__name__}"
                            )
                        panels.present(scene, observation["images"])
                    else:
                        panels.present_blank()
                    next_control_deadline += control_period_s
                    delay = next_control_deadline - time.monotonic()
                    if delay > 0.0:
                        time.sleep(delay)
                    else:
                        loop_overruns += 1
                        if delay < -control_period_s:
                            next_control_deadline = time.monotonic()
                    if session_frames % 30 == 0:
                        plant = _gripper_plant_diagnostics(native_env)
                        target = ik_processor.target_d0
                        arm_plant = _arm_plant_diagnostics(
                            native_env, current_state, target, last_ik_result
                        )
                        target_error = None
                        gripper_error = None
                        if last_ik_result is not None:
                            target_error = last_ik_result.target_tracking_error_deg
                            gripper_error = last_ik_result.gripper_target_error_mm
                        print(
                            json.dumps(
                                {
                                    "event": "mujoco_quest_status",
                                    "step": steps,
                                    "session_frame": session_frames,
                                    "execution_state": final_execution_state,
                                    "tracking_gate_ready": tracking_gate_ready,
                                    "left_mode": command.left.sensitivity_mode,
                                    "right_mode": command.right.sensitivity_mode,
                                    "controllers": {
                                        "left": _diagnostic_arm(sample.left, command.left),
                                        "right": _diagnostic_arm(sample.right, command.right),
                                    },
                                    "target_gripper_mm": (
                                        None
                                        if target is None
                                        else np.round(target[[6, 13]], 3).tolist()
                                    ),
                                    "measured_gripper_mm": np.round(
                                        current_state[[6, 13]], 3
                                    ).tolist(),
                                    "finger_aperture_mm": {
                                        side: round(float(values["finger_aperture_mm"]), 3)
                                        for side, values in plant.items()
                                    },
                                    "aperture_tracking_error_mm": {
                                        side: round(
                                            float(values["aperture_tracking_error_mm"]), 3
                                        )
                                        for side, values in plant.items()
                                    },
                                    "finger_center_offset_mm": {
                                        side: round(
                                            float(values["finger_center_offset_mm"]), 3
                                        )
                                        for side, values in plant.items()
                                    },
                                    "aperture_target_mm": {
                                        side: round(float(values["aperture_target_mm"]), 3)
                                        for side, values in plant.items()
                                    },
                                    "gripper_aperture_force_n": {
                                        side: round(
                                            float(values["aperture_actuator_force_n"]), 3
                                        )
                                        for side, values in plant.items()
                                    },
                                    "gripper_force_limited": {
                                        side: bool(values["force_limited"])
                                        for side, values in plant.items()
                                    },
                                    "joint_target_error_deg": target_error,
                                    "arm_plant": arm_plant,
                                    "gripper_target_error_mm": gripper_error,
                                    "gripper_armed": (
                                        None
                                        if last_ik_result is None
                                        else last_ik_result.gripper_armed
                                    ),
                                    "translation_alignment": (
                                        None
                                        if last_ik_result is None
                                        else last_ik_result.translation_alignment
                                    ),
                                    "achieved_translation_m": (
                                        None
                                        if last_ik_result is None
                                        else last_ik_result.achieved_translation_m
                                    ),
                                    "cartesian_delta_clipped": (
                                        None
                                        if last_ik_result is None
                                        else last_ik_result.cartesian_delta_clipped
                                    ),
                                    "saturation_frames": saturation_counts["any"],
                                    "saturation_by_type": saturation_counts,
                                    "ik_failure_frames": ik_failure_frames,
                                    "explicit_resets": explicit_resets,
                                    "automatic_resets": 0,
                                    "loop_overruns": loop_overruns,
                                },
                                sort_keys=True,
                            )
                        )
            except KeyboardInterrupt:
                pass
            finally:
                # MuJoCo's EGL context must be released while the shared
                # graphics-bound TeleopSession is still alive. Closing it after
                # the session has torn down can invalidate the process EGL
                # display before Renderer.close() reaches eglDestroyContext.
                teardown_failures.extend(
                    _close_runtime_resources(None, env, None, None)
                )
                env = None
    finally:
        teardown_failures.extend(
            _close_runtime_resources(panels, env, temporary, cloudxr)
        )

    if teardown_failures:
        print(
            json.dumps(
                {"event": "mujoco_quest_teardown_failures", "failures": teardown_failures},
                sort_keys=True,
            )
        )

    report = {
        "event": "mujoco_quest_finished",
        "status": "physical_validation_required",
        "profile": config["revision"],
        "steps": steps,
        "session_frames": session_frames,
        "session_started_ever": session_started_ever,
        "final_execution_state": final_execution_state,
        "elapsed_s": time.monotonic() - started,
        "tracking_valid_frames": tracked_frames,
        "saturation_frames": saturation_counts["any"],
        "saturation_by_type": saturation_counts,
        "ik_failure_frames": ik_failure_frames,
        "explicit_resets": explicit_resets,
        "automatic_resets": 0,
        "loop_overruns": loop_overruns,
        "teardown_failures": teardown_failures,
        "e2_started": False,
        "real_robot_motion": False,
    }
    print(json.dumps(report, sort_keys=True))
    if args.require_tracking and not all(value > 0 for value in tracked_frames.values()):
        return 2
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--max-control-steps", type=int, default=0, help="0 runs until Ctrl-C")
    parser.add_argument("--require-tracking", action="store_true")
    parser.add_argument("--no-auto-launch-cloudxr", action="store_true")
    parser.add_argument("--cloudxr-install-dir", default="~/.cloudxr")
    parser.add_argument("--cloudxr-env-file", default=None)
    parser.add_argument("--accept-cloudxr-eula", action="store_true")
    args = parser.parse_args()
    if args.max_control_steps < 0:
        parser.error("--max-control-steps must be non-negative")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
