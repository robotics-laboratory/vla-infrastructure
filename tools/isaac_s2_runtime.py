"""Live/smoke Gate S2 loop layered on the accepted S1 environment."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import time
from typing import Any

import numpy as np
import yaml

from isaac_s1_runtime import NativeBimanualTargets, jsonable
from isaac_s2_processor import (
    BimanualS2TeleopProcessor,
    PROCESSOR_REVISION,
    S2ProcessorConfig,
    unpack_pipeline_action,
)
from isaac_s2_upstream import (
    PIPELINE_ACTION_DIM,
    build_piper_x_bimanual_pipeline,
    create_piper_x_teleop_device,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/isaac_s2_runtime.yaml"


def _gpu_observation() -> dict[str, Any]:
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5.0,
        ).splitlines()[0]
        utilization, used, total = (int(value.strip()) for value in output.split(","))
        return {
            "gpu_utilization_percent": utilization,
            "vram_used_mib": used,
            "vram_total_mib": total,
        }
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
        return {"unavailable": f"{type(exc).__name__}: {exc}"}


class _BimanualDifferentialIk:
    """Bind upstream differential IK to the two accepted S1 articulations."""

    def __init__(self, env) -> None:
        import torch
        from isaaclab.controllers import (  # type: ignore[import-not-found]
            DifferentialIKController,
            DifferentialIKControllerCfg,
        )

        self.env = env
        self.torch = torch
        cfg = DifferentialIKControllerCfg(
            command_type="pose", use_relative_mode=True, ik_method="dls"
        )
        self.controllers = tuple(
            DifferentialIKController(cfg, num_envs=1, device=env.sim.device)
            for _ in env.robots
        )
        for controller, robot, ids in zip(
            self.controllers, env.robots, env.joint_ids, strict=True
        ):
            limits = robot.data.joint_limits.torch[0, ids[:6], :]
            controller.set_joint_pos_limits(limits[:, 0], limits[:, 1])

    def reset(self) -> None:
        for controller in self.controllers:
            controller.reset()

    def tcp_poses_base(self) -> list[np.ndarray]:
        from isaaclab.utils.math import subtract_frame_transforms  # type: ignore[import-not-found]

        poses = []
        for robot, wrist_id in zip(self.env.robots, self.env.wrist_ids, strict=True):
            tcp_world = robot.data.body_link_pose_w.torch[:, wrist_id]
            root_world = robot.data.root_pose_w.torch
            position, quaternion = subtract_frame_transforms(
                root_world[:, :3], root_world[:, 3:], tcp_world[:, :3], tcp_world[:, 3:]
            )
            poses.append(
                self.torch.cat((position, quaternion), dim=-1)[0]
                .detach()
                .cpu()
                .numpy()
            )
        return poses

    def apply(self, command) -> bool:
        from isaaclab.utils.math import subtract_frame_transforms  # type: ignore[import-not-found]

        native = []
        saturated = False
        for robot, wrist_id, ids, controller, arm_command in zip(
            self.env.robots,
            self.env.wrist_ids,
            self.env.joint_ids,
            self.controllers,
            (command.left, command.right),
            strict=True,
        ):
            tcp_world = robot.data.body_link_pose_w.torch[:, wrist_id]
            root_world = robot.data.root_pose_w.torch
            ee_pos, ee_quat = subtract_frame_transforms(
                root_world[:, :3], root_world[:, 3:], tcp_world[:, :3], tcp_world[:, 3:]
            )
            joint_pos = robot.data.joint_pos.torch[:, ids[:6]]
            jacobian_index = wrist_id - 1 if robot.is_fixed_base else wrist_id
            jacobian_joint_ids = [joint_id + robot.num_base_dofs for joint_id in ids[:6]]
            jacobian = robot.data.body_link_jacobian_w.torch[
                :, jacobian_index, :, jacobian_joint_ids
            ]
            delta = self.torch.as_tensor(
                arm_command.delta_pose,
                dtype=self.torch.float32,
                device=self.env.sim.device,
            ).unsqueeze(0)
            controller.set_command(delta, ee_pos=ee_pos, ee_quat=ee_quat)
            desired = controller.compute(ee_pos, ee_quat, jacobian, joint_pos)[0]
            limits = robot.data.joint_limits.torch[0, ids[:6], :]
            clipped = desired.clamp(limits[:, 0], limits[:, 1])
            saturated |= not bool(self.torch.equal(desired, clipped))
            values = clipped.detach().cpu().numpy()
            native.append(np.concatenate((values, [arm_command.gripper_aperture_m])))
        self.env._apply(NativeBimanualTargets(native[0], native[1], saturated))
        return saturated


def _camera_sample(env, previous_indices: np.ndarray | None) -> dict[str, Any]:
    images = env.observation()
    frame_value = env.camera.frame
    frame_tensor = frame_value if hasattr(frame_value, "detach") else frame_value.torch
    frame_indices = frame_tensor.detach().cpu().numpy().astype(np.int64)
    result: dict[str, Any] = {"valid": True, "strictly_advanced": True, "roles": {}}
    for index, role in enumerate(("left_wrist", "right_wrist")):
        image = images[f"observation.images.{role}"]
        valid = bool(
            image.shape == (480, 640, 3)
            and image.dtype == np.uint8
            and np.isfinite(image).all()
        )
        advanced = previous_indices is None or bool(
            frame_indices[index] > previous_indices[index]
        )
        result["roles"][role] = {
            "frame_index": int(frame_indices[index]),
            "valid": valid,
            "advanced": advanced,
            "sha256": hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest(),
        }
        result["valid"] &= valid
        result["strictly_advanced"] &= advanced
    result["frame_indices"] = frame_indices
    return result


def run_s2(env, args_cli, simulation_app) -> int:
    """Run S2 using an already-created accepted S1 environment."""

    from isaacteleop.cloudxr.runtime import runtime_version
    from isaaclab_teleop import (  # type: ignore[import-not-found]
        CLOUDXR_JS_ENV,
        CLOUDXR_STANDALONE_ENV,
        IsaacTeleopCfg,
    )
    from isaaclab_teleop.control_events import (  # type: ignore[import-not-found]
        poll_control_events,
    )
    from isaaclab_teleop.xr_cfg import XrCfg  # type: ignore[import-not-found]

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    expected = config["environment"]
    actual_versions = {
        "isaac_sim": importlib.metadata.version("isaacsim"),
        "isaac_lab_package": importlib.metadata.version("isaaclab"),
        "isaac_lab_release": expected["isaac_lab_release"],
        "isaacteleop": importlib.metadata.version("isaacteleop"),
        "isaaclab_teleop": importlib.metadata.version("isaaclab-teleop"),
        "cloudxr": runtime_version(),
    }
    required = {
        "isaac_sim": expected["isaac_sim_version"],
        "isaac_lab_package": expected["isaac_lab_package_version"],
        "isaacteleop": expected["isaacteleop_version"],
        "isaaclab_teleop": expected["isaaclab_teleop_version"],
        "cloudxr": expected["cloudxr_runtime_version"],
    }
    mismatches = {
        name: {"expected": version, "actual": actual_versions[name]}
        for name, version in required.items()
        if actual_versions[name] != version
    }
    if mismatches:
        raise RuntimeError(f"S2 upstream version mismatch: {mismatches}")

    processor_cfg = S2ProcessorConfig(
        translation_scale=float(config["processor"]["translation_scale"]),
        rotation_scale=float(config["processor"]["rotation_scale"]),
        clutch_threshold=float(config["processor"]["clutch"]["threshold"]),
        gripper_threshold=float(config["processor"]["gripper"]["threshold"]),
        gripper_open_m=float(config["processor"]["gripper"]["open_aperture_m"]),
        gripper_closed_m=float(config["processor"]["gripper"]["closed_aperture_m"]),
        reset_gripper_m=float(config["processor"]["gripper"]["reset_aperture_m"]),
    )
    processor = BimanualS2TeleopProcessor(processor_cfg)
    ik = _BimanualDifferentialIk(env)
    cloudxr_env = (
        CLOUDXR_JS_ENV if args_cli.s2_cloudxr_profile == "cloudxrjs" else CLOUDXR_STANDALONE_ENV
    )
    teleop_cfg = IsaacTeleopCfg(
        xr_cfg=XrCfg(anchor_pos=(0.0, 0.0, 0.0)),
        pipeline_builder=build_piper_x_bimanual_pipeline,
        sim_device=env.sim.device,
        teleoperation_active_default=True,
    )
    device = create_piper_x_teleop_device(
        teleop_cfg,
        cloudxr_env_file=cloudxr_env,
        use_kit_xr_bridge=bool(args_cli.xr),
    )

    reset_observation = env.reset(0)
    del reset_observation
    processor.reset()
    ik.reset()
    started = time.perf_counter()
    gpu_start = _gpu_observation()
    previous_camera_indices: np.ndarray | None = None
    camera_valid_frames = 0
    camera_advanced_frames = 0
    session_started_ever = False
    action_frames = 0
    tracking_valid_frames = {"left": 0, "right": 0}
    transition_counts: dict[str, int] = {}
    maximum_rebase_motion_m = {"left": 0.0, "right": 0.0}
    saturated_frames = 0
    control_steps = 0

    print(
        f"[S2] CloudXR {actual_versions['cloudxr']} profile={args_cli.s2_cloudxr_profile} "
        f"kit_xr_bridge={bool(args_cli.xr)}",
        flush=True,
    )
    with device:
        for step in range(1, args_cli.s2_max_control_steps + 1):
            if not simulation_app.is_running():
                break
            control_steps = step
            before_pose = ik.tcp_poses_base()
            action = device.advance()
            events = poll_control_events(device)
            host_reset = args_cli.s2_reset_step > 0 and control_steps == args_cli.s2_reset_step
            if events.should_reset or host_reset:
                env.reset(0)
                processor.reset()
                ik.reset()
                # Camera frame indices are local to a reset epoch. Comparing the
                # first post-reset index with the prior epoch would report a
                # false stale frame even when both RGB observations are valid.
                previous_camera_indices = None
                device.reset(pause=False)
                before_pose = ik.tcp_poses_base()

            session_started_ever |= device.session_running
            if action is None:
                command = processor.session_inactive()
            else:
                if tuple(action.shape) != (PIPELINE_ACTION_DIM,):
                    raise RuntimeError(f"unexpected S2 pipeline action shape: {tuple(action.shape)}")
                action_frames += 1
                left, right = unpack_pipeline_action(action.detach().cpu().numpy())
                command = processor.advance(
                    left,
                    right,
                    session_active=events.is_active is not False,
                )
            saturated_frames += int(ik.apply(command))
            env._advance(4)
            after_pose = ik.tcp_poses_base()

            for side, arm, before, after in zip(
                ("left", "right"),
                (command.left, command.right),
                before_pose,
                after_pose,
                strict=True,
            ):
                tracking_valid_frames[side] += int(arm.tracking_valid)
                transition_counts[f"{side}:{arm.transition}"] = (
                    transition_counts.get(f"{side}:{arm.transition}", 0) + 1
                )
                if arm.rebased or arm.clutch_active:
                    maximum_rebase_motion_m[side] = max(
                        maximum_rebase_motion_m[side],
                        float(np.linalg.norm(after[:3] - before[:3])),
                    )

            camera = _camera_sample(env, previous_camera_indices)
            previous_camera_indices = camera.pop("frame_indices")
            camera_valid_frames += int(camera["valid"])
            camera_advanced_frames += int(camera["strictly_advanced"])
            if control_steps % 30 == 0:
                print(
                    json.dumps(
                        {
                            "event": "s2_status",
                            "step": control_steps,
                            "session_running": device.session_running,
                            "left": command.left.transition,
                            "right": command.right.transition,
                            "camera_valid": camera["valid"],
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

    elapsed = time.perf_counter() - started
    gpu_end = _gpu_observation()
    session_requirement_met = session_started_ever or not args_cli.s2_require_session
    tracking_requirement_met = (
        all(count > 0 for count in tracking_valid_frames.values())
        or not args_cli.s2_require_tracking
    )
    passed = bool(
        control_steps == args_cli.s2_max_control_steps
        and camera_valid_frames == control_steps
        and camera_advanced_frames == control_steps
        and session_requirement_met
        and tracking_requirement_met
    )
    report = {
        "gate": "S2",
        "status": "runtime_smoke_passed_physical_human_gate_required" if passed else "failed",
        "environment": {
            **actual_versions,
            "python": platform.python_version(),
            "isaac_lab_commit": expected["isaac_lab_commit"],
            "cloudxr_profile": args_cli.s2_cloudxr_profile,
            "kit_xr_bridge": bool(args_cli.xr),
        },
        "runtime_path": (
            "Quest -> CloudXR/isaacteleop -> isaaclab_teleop -> one ControllersSource "
            "-> S2 processor -> DifferentialIKController -> accepted S1 native actuation"
        ),
        "processor": {
            "revision": PROCESSOR_REVISION,
            "translation_scale": processor_cfg.translation_scale,
            "rotation_scale": processor_cfg.rotation_scale,
            "clutch": "independent squeeze > 0.5; release discards one delta",
            "gripper": "independent binary trigger > 0.5 closes",
            "source_timestamp_threshold": None,
        },
        "session": {
            "single_controller_source": True,
            "started_ever": session_started_ever,
            "action_frames": action_frames,
            "require_session": bool(args_cli.s2_require_session),
            "require_physical_tracking": bool(args_cli.s2_require_tracking),
        },
        "execution": {
            "control_steps": control_steps,
            "wall_seconds": elapsed,
            "control_hz": control_steps / elapsed,
            "physics_hz": (control_steps * 4) / elapsed,
            "saturated_frames": saturated_frames,
            "tracking_valid_frames": tracking_valid_frames,
            "transitions": transition_counts,
            "maximum_rebase_or_clutch_tcp_motion_m": maximum_rebase_motion_m,
        },
        "cameras": {
            "left_wrist": "640x480 uint8 RGB HWC",
            "right_wrist": "640x480 uint8 RGB HWC",
            "valid_bimanual_frames": camera_valid_frames,
            "strictly_advanced_bimanual_frames": camera_advanced_frames,
        },
        "gpu": {"start": gpu_start, "end": gpu_end},
        "physical_human_gate": "required_not_implied_by_runtime_smoke",
        "passed": passed,
    }
    if args_cli.report is not None:
        args_cli.report.write_text(
            json.dumps(jsonable(report), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(jsonable(report), sort_keys=True), flush=True)
    return 0 if passed else 1
