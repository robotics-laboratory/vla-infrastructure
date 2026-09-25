"""Live/smoke Gate S2 loop layered on the accepted S1 environment."""

from __future__ import annotations

from functools import partial
from contextlib import nullcontext
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import time
from uuid import uuid4
from typing import Any, cast

import numpy as np
import yaml

from tools.isaac_vr_decision import (
    CausalTransactionValidator,
    SolvedControlDecision,
    capture_state_snapshot,
    check_observation,
    commit_recording_transition,
    decision_epoch,
    recordable_teleop_command,
)
from isaac_s1_runtime import NativeBimanualTargets, jsonable
from isaac_s2_performance import S2PerformanceLogger
from isaac_vr_camera_guard import CameraGuard
from isaac_s2_processor import (
    BimanualS2TeleopProcessor,
    PROCESSOR_REVISION,
    S2ProcessorConfig,
    SensitivityControlMode,
    SensitivityMode,
    unpack_pipeline_action,
)
from isaac_s2_upstream import (
    DEMO_BACKDROP_BUTTON_INDEX,
    DEMO_DISPLAY_BUTTON_INDEX,
    DEMO_RECENTER_BUTTON_INDEX,
    RECORD_STOP_BUTTON_INDEX,
    PIPELINE_ACTION_DIM,
    build_piper_x_bimanual_pipeline,
    create_piper_x_teleop_device,
)
from isaac_vr_recording_smoke import (
    recording_portable_roots,
    recording_session_metadata,
    run_injected_lifecycle_audit,
    run_recording_lifecycle_smoke,
)
from isaac_vr_episode_lifecycle import (
    RecordingLifecycle, RecordingState, publish_saved_demo, publish_unsaved_demo,
    technical_episode_output_dir,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/isaac_s2_runtime.yaml"


def _solve_native_decision(
    ik, command, observation, xr, control_tick_id, *, recording_requested: bool, eligible: bool
):
    """Solve safe teleoperation; bind causal identities only for eligible ticks."""
    return ik.solve(
        command,
        observation if eligible else None,
        xr if eligible else None,
        control_tick_id if eligible else None,
    )


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

    device: Any
    processor: BimanualS2TeleopProcessor

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
            DifferentialIKController(cfg, num_envs=1, device=env.sim.device) for _ in env.robots
        )
        for controller, robot, ids in zip(self.controllers, env.robots, env.joint_ids, strict=True):
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
            poses.append(self.torch.cat((position, quaternion), dim=-1)[0].detach().cpu().numpy())
        return poses

    def solve(self, command, observation=None, xr=None, tick=None):
        check_observation(self.env, observation)
        native = []
        preclip: list[float] = []
        for robot, wrist_id, ids, controller, arm_command in zip(
            self.env.robots,
            self.env.wrist_ids,
            self.env.joint_ids,
            self.controllers,
            (command.left, command.right),
            strict=True,
        ):
            tcp_world = robot.data.body_link_pose_w.torch[:, wrist_id]
            # Pose, spatial delta and Jacobian share the Isaac world frame.
            ee_pos, ee_quat = tcp_world[:, :3], tcp_world[:, 3:]
            joint_pos = robot.data.joint_pos.torch[:, ids[:6]]
            jacobian_index = wrist_id - 1 if robot.is_fixed_base else wrist_id
            jacobian_joint_ids = [joint_id + robot.num_base_dofs for joint_id in ids[:6]]
            jacobian = robot.data.body_link_jacobian_w.torch[
                :, jacobian_index, :, jacobian_joint_ids
            ]
            delta = self.torch.as_tensor(
                arm_command.delta_pose.copy(),
                dtype=self.torch.float32,
                device=self.env.sim.device,
            ).unsqueeze(0)
            controller.set_command(delta, ee_pos=ee_pos, ee_quat=ee_quat)
            desired = controller.compute(ee_pos, ee_quat, jacobian, joint_pos)[0]
            if not bool(self.torch.isfinite(desired).all()):
                raise RuntimeError("Non-finite IK target")
            limits = robot.data.joint_limits.torch[0, ids[:6], :]
            clipped = desired.clamp(limits[:, 0], limits[:, 1])
            preclip.extend((*desired.detach().cpu().numpy(), arm_command.gripper_aperture_m))
            values = clipped.detach().cpu().numpy()
            native.append(np.concatenate((values, [arm_command.gripper_aperture_m])))
        check_observation(self.env, observation)
        return SolvedControlDecision.from_native(
            tick, observation, xr, command, preclip, np.concatenate(native)
        )

    def apply(self, solution) -> bool:
        if solution.xr_identity is not None:
            self.device.validate_xr(solution.xr_identity)
            if solution.cartesian_intent.processor_generation != self.processor.generation:
                raise RuntimeError("Processor generation changed before application")
        check_observation(self.env, solution.observation_identity)
        native = np.asarray(solution.native_clipped).reshape(2, 7)
        self.env._apply(NativeBimanualTargets(native[0], native[1], solution.saturated))
        if solution.xr_identity is not None:
            self.device.xr_receipt.last_consumed = solution.xr_identity.deviceio_update_epoch
        return solution.saturated


def _camera_sample(env, previous_indices: np.ndarray | None) -> dict[str, Any]:
    images = env.observation()
    frame_value = env.camera.frame
    frame_tensor = frame_value if hasattr(frame_value, "detach") else frame_value.torch
    frame_indices = frame_tensor.detach().cpu().numpy().astype(np.int64)
    result: dict[str, Any] = {"valid": True, "strictly_advanced": True, "roles": {}}
    for index, role in enumerate(("left_wrist", "right_wrist")):
        image = images[f"observation.images.{role}"]
        valid = bool(
            image.shape == (480, 640, 3) and image.dtype == np.uint8 and np.isfinite(image).all()
        )
        advanced = previous_indices is None or bool(frame_indices[index] > previous_indices[index])
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

    recording_requested = bool(getattr(args_cli, "s2_record", False))
    if recording_requested and not getattr(args_cli, "s2_teleop", False):
        return run_recording_lifecycle_smoke(
            env,
            args_cli,
            default_config_path=CONFIG_PATH,
            processor_revision=PROCESSOR_REVISION,
        )

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

    config_path = getattr(args_cli, "s2_config", None) or CONFIG_PATH
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["processor"]["revision"] != PROCESSOR_REVISION:
        raise RuntimeError("S2 processor config/code revision mismatch")
    diagnostic = getattr(args_cli, "s2_mode", "diagnostic") == "diagnostic"
    if recording_requested and (diagnostic or getattr(args_cli, "s2_recording_dir", None) is None):
        raise ValueError("recording requires run mode and --s2-recording-dir")
    if not diagnostic and any(
        getattr(args_cli, name, False)
        for name in (
            "demo_display_toggle_smoke",
            "demo_backdrop_toggle_smoke",
            "demo_recenter_smoke",
            "demo_scene_preview",
        )
    ):
        raise ValueError("Diagnostic-only flags require ./run-vr diag ...")
    experiment = getattr(env, "vr_runtime", None)
    experimental = experiment is not None and experiment.profile == "robosyn_asset_lab"
    if experimental and not diagnostic:
        raise ValueError("robosyn_asset_lab requires ./run-vr diag ...")
    camera_guard = CameraGuard(
        0
        if diagnostic
        else (
            experiment.config["validation"]["camera_max_stale_control_steps"]
            if experiment is not None
            else 2
        )
    )
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

    sensitivity = (
        experiment.sensitivity if experiment is not None else config["processor"]["sensitivity"]
    )
    sensitivity_control_mode = cast(
        SensitivityControlMode, str(sensitivity.get("control_mode", "toggle"))
    )
    if sensitivity_control_mode == "slider":
        slider = sensitivity["slider"]
        normal_scales = slider["center"]
        precise_scales = slider["minimum"]
        initial_sensitivity_mode: SensitivityMode = "normal"
        sensitivity_toggle_threshold = 0.5
    else:
        slider = {
            "minimum": sensitivity["modes"]["precise"],
            "center": sensitivity["modes"]["normal"],
            "maximum": sensitivity["modes"]["normal"],
        }
        normal_scales = sensitivity["modes"]["normal"]
        precise_scales = sensitivity["modes"]["precise"]
        initial_sensitivity_mode = cast(SensitivityMode, str(sensitivity["initial_mode"]))
        sensitivity_toggle_threshold = float(sensitivity["toggle_threshold"])
    gripper = config["processor"]["gripper"]
    processor_cfg = S2ProcessorConfig(
        normal_translation_scale=float(normal_scales["translation_scale"]),
        normal_rotation_scale=float(normal_scales["rotation_scale"]),
        precise_translation_scale=float(precise_scales["translation_scale"]),
        precise_rotation_scale=float(precise_scales["rotation_scale"]),
        initial_sensitivity_mode=initial_sensitivity_mode,
        sensitivity_control_mode=sensitivity_control_mode,
        sensitivity_toggle_threshold=sensitivity_toggle_threshold,
        slider_min_translation_scale=float(slider["minimum"]["translation_scale"]),
        slider_min_rotation_scale=float(slider["minimum"]["rotation_scale"]),
        slider_center_translation_scale=float(slider["center"]["translation_scale"]),
        slider_center_rotation_scale=float(slider["center"]["rotation_scale"]),
        slider_max_translation_scale=float(slider["maximum"]["translation_scale"]),
        slider_max_rotation_scale=float(slider["maximum"]["rotation_scale"]),
        clutch_threshold=float(config["processor"]["clutch"]["threshold"]),
        gripper_trigger_min=float(gripper["trigger_input_range"][0]),
        gripper_trigger_max=float(gripper["trigger_input_range"][1]),
        gripper_open_m=float(gripper["open_aperture_m"]),
        gripper_closed_m=float(gripper["closed_aperture_m"]),
        reset_gripper_m=float(gripper["reset_aperture_m"]),
    )
    processor = BimanualS2TeleopProcessor(processor_cfg)
    ik = _BimanualDifferentialIk(env)
    cloudxr_env = (
        CLOUDXR_JS_ENV if args_cli.s2_cloudxr_profile == "cloudxrjs" else CLOUDXR_STANDALONE_ENV
    )
    presentation = (
        experiment.xr_presentation if experiment is not None else config["xr_presentation"]
    )
    anchor_position = tuple(float(value) for value in presentation["anchor_pos_m"])
    anchor_rotation = tuple(float(value) for value in presentation["anchor_rot_xyzw"])
    pipeline_kwargs: dict[str, Any] = {
        "sensitivity_control": str(
            sensitivity.get("input_control", sensitivity.get("toggle_control"))
        )
    }
    pipeline_action_dim = PIPELINE_ACTION_DIM
    if experiment is not None:
        pipeline_kwargs["display_control"] = experiment.display_control
        pipeline_kwargs["backdrop_control"] = experiment.backdrop_control
        pipeline_kwargs["recenter_control"] = experiment.recenter_control
        pipeline_action_dim = experiment.pipeline_action_dim
    if recording_requested:
        # X, Y and B travel through the existing single ControllersSource.
        pipeline_kwargs.update(
            display_control="left_primary_click",
            backdrop_control="right_secondary_click",
            recenter_control="right_thumbstick_click",
            record_stop_control="left_secondary_click",
        )
        pipeline_action_dim = RECORD_STOP_BUTTON_INDEX + 1
    teleop_cfg = IsaacTeleopCfg(
        xr_cfg=XrCfg(
            anchor_pos=anchor_position,
            anchor_rot=anchor_rotation,
            near_plane=float(presentation["near_plane_m"]),
        ),
        pipeline_builder=partial(build_piper_x_bimanual_pipeline, **pipeline_kwargs),
        sim_device=env.sim.device,
        teleoperation_active_default=True,
    )
    device = create_piper_x_teleop_device(
        teleop_cfg,
        cloudxr_env_file=cloudxr_env,
        use_kit_xr_bridge=bool(args_cli.xr),
        include_xr_navigation_in_controller_transform=experiment is not None,
    )

    ik.device, ik.processor = device, processor
    reset_observation = env.reset(0)
    del reset_observation
    processor.reset()
    ik.reset()
    if getattr(args_cli, "s2_current_record_audit", None) is not None:
        # The existing no-client injected receipt seam supplies controlled
        # targets while the ordinary S2 device/Kit context remains active.
        # It makes no physical-XR or human-IK claim.
        if experiment is not None:
            if recording_requested:
                experiment.prepare_recording_view()
            else:
                experiment.open(env)
        with device:
            if recording_requested:
                if args_cli.s2_current_record_audit == "lifecycle":
                    return run_injected_lifecycle_audit(
                        env, args_cli, default_config_path=CONFIG_PATH,
                        processor_revision=PROCESSOR_REVISION, audit_device=device,
                    )
                return run_recording_lifecycle_smoke(
                    env, args_cli, default_config_path=CONFIG_PATH,
                    processor_revision=PROCESSOR_REVISION, audit_device=device,
                )
            from isaac_vr_injected_recording import run_injected_controls

            if args_cli.s2_performance_log is None:
                raise RuntimeError("matched no-client RUN requires the performance log")
            audit_performance = S2PerformanceLogger(
                args_cli.s2_performance_log,
                window_steps=args_cli.s2_performance_window_steps,
                warmup_steps=args_cli.s2_performance_warmup_steps,
                target_hz=30.0,
            )
            try:
                audit_result = run_injected_controls(
                    env, count=args_cli.s2_injected_count,
                    performance_logger=audit_performance,
                    input_pump=device.advance,
                )
            finally:
                audit_summary = audit_performance.close()
                if experiment is not None:
                    experiment.close()
            audit_result["performance"] = audit_summary
            audit_result.update({
                "mode": "matched_injected_run_no_client",
                "passed": True,
                "teleop_initialized": True,
                "kit_xr_bridge_configured": bool(args_cli.xr),
                "cloudxr_profile": args_cli.s2_cloudxr_profile,
                "session_running_at_end": bool(device.session_running),
                "xr_input_available_at_end": getattr(device, "xr_input", None) is not None,
                "input_pump_calls": args_cli.s2_injected_count,
                "processor_executed": False,
                "ik_executed": False,
                "xr_receipt": "none",
            })
            if args_cli.report is not None:
                Path(args_cli.report).write_text(
                    json.dumps(audit_result, indent=2) + "\n", encoding="utf-8"
                )
            print(json.dumps(audit_result, sort_keys=True), flush=True)
            return 0
    started = time.perf_counter()
    gpu_start = _gpu_observation() if diagnostic else None
    gpu_samples = [gpu_start]
    previous_camera_indices: np.ndarray | None = None
    camera_valid_frames = 0
    camera_advanced_frames = 0
    session_started_ever = False
    action_frames = 0
    tracking_valid_frames = {"left": 0, "right": 0}
    sensitivity_modes = (
        ("slider",) if sensitivity_control_mode == "slider" else ("normal", "precise")
    )
    sensitivity_mode_frames = {
        side: {mode: 0 for mode in sensitivity_modes} for side in ("left", "right")
    }
    motion_scale_observed: dict[str, dict[str, float | None]] = {
        side: {
            "translation_min": None,
            "translation_max": None,
            "rotation_min": None,
            "rotation_max": None,
        }
        for side in ("left", "right")
    }
    transition_counts: dict[str, int] = {}
    maximum_rebase_motion_m = {"left": 0.0, "right": 0.0}
    saturated_frames = 0
    control_steps = 0
    run_id = str(uuid4())
    validator = None
    control_tick_id = 0
    env.last_control_decision = None
    env.prepared_control_transaction = None
    recording = None
    recording_session = None
    recording_token = None
    recording_stop_reason: str | None = None
    recording_failure_reason: str | None = None
    recording_summary: dict[str, Any] | None = None
    recording_episodes: list[dict[str, Any]] = []
    recording_episode_index = 0
    demo_episodes: list[dict[str, Any]] = []
    demo_start_tick = 0
    demo_stop_tick = 0
    lifecycle: RecordingLifecycle | None = None
    demo_start_requested_ns: int | None = None

    def finalize_recording(outcome: str, reason: str) -> None:
        nonlocal recording, recording_summary
        if recording is None:
            return
        active = recording
        summary = {
            "committed_frames": active.committed_frames,
            "discarded_observations": active.discarded_observations,
            "outcome": outcome,
            "reason": reason,
            "rejections": dict(active.rejections),
            "run_id": active.run_id,
            "session_id": active.session_id,
            "episode_id": active.episode_id,
            "source_profile": active.source_profile,
            "output_dir": str(active.output_dir),
        }
        try:
            with (performance.boundary("technical_episode_end", reason=reason)
                  if performance is not None else nullcontext()):
                recording_session.end_episode(outcome=outcome, reason=reason)
        finally:
            recording = None
        recording_summary = summary
        recording_episodes.append(summary)
        demo_episodes.append(summary)
        print(
            json.dumps({"event": "recording_episode_finalized", **summary}, sort_keys=True),
            flush=True,
        )

    performance = (
        S2PerformanceLogger(
            args_cli.s2_performance_log,
            window_steps=args_cli.s2_performance_window_steps,
            warmup_steps=args_cli.s2_performance_warmup_steps,
            target_hz=30.0,
        )
        if args_cli.s2_performance_log is not None
        else None
    )
    performance_summary: dict[str, Any] | None = None
    env.performance_logger = performance
    interrupted = False

    def observe_recording_timing(name: str, elapsed_ns: int) -> None:
        if performance is None:
            return
        if name in {"hdf_append_ms", "hdf_flush_ms"}:
            performance.add_nested(name, elapsed_ns)
        else:
            performance.record_boundary(name, elapsed_ns)

    def seal_demo(reason: str) -> None:
        nonlocal recording, recording_session, validator, recording_token
        with (performance.boundary("demo_stop_seal", reason=reason)
              if performance is not None else nullcontext()):
            if recording is not None:
                finalize_recording(
                    "operator_stopped" if reason == "explicit_stop" else "aborted", reason
                )
            if recording_session is not None:
                session = recording_session
                recording_session = None
                session.close(outcome="aborted", reason=reason)
            recording_token = None
            if validator is not None:
                validator.abort()
                validator = None

    def reset_demo() -> None:
        nonlocal previous_camera_indices
        with (performance.boundary("demo_reset") if performance is not None
              else nullcontext()):
            env.reset(0)
            processor.reset()
            ik.reset()
            camera_guard.reset()
            previous_camera_indices = None
            device.reset(pause=False)

    def demo_index_root() -> Path:
        return Path(
            getattr(args_cli, "s2_recordings_root", None)
            or Path(args_cli.s2_recording_dir).parent
        )

    def save_demo(demo_id: str, task_outcome: str) -> None:
        with (performance.boundary("demo_save_publication", task_outcome=task_outcome)
              if performance is not None else nullcontext()):
            publish_saved_demo(
                demo_index_root() / "saved_demos",
                demo_id=demo_id,
                episodes=demo_episodes,
                profile="isaac_human_vr_offline_rgb_v2",
                start_tick=demo_start_tick,
                stop_tick=demo_stop_tick,
                task_outcome=task_outcome,
            )

    def classify_unsaved(demo_id: str, classification: str) -> None:
        with (performance.boundary("demo_classification_publication",
                                   classification=classification)
              if performance is not None else nullcontext()):
            publish_unsaved_demo(
                demo_index_root(), demo_id=demo_id,
                classification=classification, episodes=demo_episodes,
            )

    print(
        f"[S2] CloudXR {actual_versions['cloudxr']} profile={args_cli.s2_cloudxr_profile} "
        f"kit_xr_bridge={bool(args_cli.xr)}",
        flush=True,
    )
    try:
        if recording_requested:
            if experiment is not None:
                experiment.prepare_recording_view()
            lifecycle = RecordingLifecycle(
                seal=seal_demo, publish=save_demo, reset=reset_demo,
                discard=lambda demo_id: classify_unsaved(demo_id, "discarded"),
                interrupted=lambda demo_id: classify_unsaved(demo_id, "interrupted"),
            )
            print(json.dumps({"event": "human_recording_state", "state": "waiting", "buttons":
                {"start": "X", "stop": "Y", "save": "X", "discard": "B",
                 "success": "X", "failure": "Y", "incomplete": "B"}}), flush=True)
        if experiment is not None and not recording_requested:
            # Pinned Candidate B requires camera-feed bind(env) before the XR
            # teleop session is entered. This also makes the panels available
            # when X is first pressed after the headset connects.
            experiment.open(env)
        with device:
            if getattr(args_cli, "xr_render_readback", None):
                import carb.settings
                from isaac_vr_config import xr_render_readback

                xr_render_readback(
                    yaml.safe_load(args_cli.config.read_text()), carb.settings.get_settings()
                )
            for step in range(1, args_cli.s2_max_control_steps + 1):
                if not simulation_app.is_running():
                    break
                control_steps = step
                if performance is not None:
                    performance.begin_step()
                    stage_started_ns = time.perf_counter_ns()
                before_pose = ik.tcp_poses_base() if diagnostic else ()
                if performance is not None:
                    performance.add_stage(
                        "tcp_pose_before", time.perf_counter_ns() - stage_started_ns
                    )
                    stage_started_ns = time.perf_counter_ns()
                env.last_control_decision = None
                env.prepared_control_transaction = None
                if validator is not None and recording is None:
                    # Ordinary RUN prepares receipts for observability only; it
                    # has no persistence/successor phase and must clear them.
                    validator.abort()
                observation = None
                recording_token = None
                if recording is not None:
                    # The recorder either captures a fresh full Fabric boundary or
                    # returns the exact O_(t+1) promoted by the prior commit.
                    recording_token = recording.capture_observation()
                    observation = recording_token.observation
                elif lifecycle is not None and lifecycle.admits_recording:
                    observation = capture_state_snapshot(env)
                elif getattr(env, "vr_runtime", None) is not None:
                    try:
                        observation = env.latest_observation_capture()
                    except RuntimeError:
                        pass  # Existing RUN camera guard still owns failed-capture policy.
                if performance is not None:
                    performance.add_stage(
                        "observation_capture", time.perf_counter_ns() - stage_started_ns
                    )
                    stage_started_ns = time.perf_counter_ns()
                action = device.advance()
                if performance is not None:
                    performance.add_stage(
                        "teleop_advance", time.perf_counter_ns() - stage_started_ns
                    )
                    stage_started_ns = time.perf_counter_ns()
                events = poll_control_events(device)
                if lifecycle is not None:
                    if lifecycle.state in (
                        RecordingState.RECORDING, RecordingState.REVIEW,
                        RecordingState.CLASSIFY_OUTCOME,
                    ) and not device.session_running:
                        lifecycle.disconnect()
                        print(json.dumps({"event": "human_recording_state", "state": lifecycle.state.value,
                            "demo_id": lifecycle.demo_id}), flush=True)
                    if lifecycle.state is RecordingState.INTERRUPTED:
                        break
                    buttons = np.zeros(3, dtype=np.float32)
                    if action is not None:
                        if tuple(action.shape) != (pipeline_action_dim,):
                            raise RuntimeError(f"unexpected S2 pipeline action shape: {tuple(action.shape)}")
                        values = action.detach().cpu().numpy()
                        buttons[:] = values[[DEMO_DISPLAY_BUTTON_INDEX, RECORD_STOP_BUTTON_INDEX,
                                              DEMO_BACKDROP_BUTTON_INDEX]]
                        if not np.isfinite(buttons).all():
                            raise RuntimeError("Non-finite recording buttons")
                    previous_state = lifecycle.state
                    event = lifecycle.buttons(x=buttons[0] >= 0.5, y=buttons[1] >= 0.5,
                                              b=buttons[2] >= 0.5)
                    if event == "start":
                        demo_start_requested_ns = time.perf_counter_ns()
                        demo_start_tick = control_steps
                        demo_episodes = []
                        recording_episode_index = 0
                        session_id = str(uuid4())
                    elif event == "stop":
                        demo_stop_tick = control_steps
                    if event is not None or lifecycle.state != previous_state:
                        print(json.dumps({"event": "human_recording_state", "state": lifecycle.state.value,
                            "demo_id": lifecycle.demo_id, "input": event}), flush=True)
                    if (
                        lifecycle.state in (
                            RecordingState.WAITING, RecordingState.REVIEW,
                            RecordingState.CLASSIFY_OUTCOME,
                        )
                        and (args_cli.s2_reset_step == control_steps or
                             (events.should_reset and not device.navigation_reset_applied))
                    ):
                        if lifecycle.state in (
                            RecordingState.REVIEW, RecordingState.CLASSIFY_OUTCOME
                        ):
                            lifecycle.external_reset()
                        else:
                            reset_demo()
                        continue
                    if lifecycle.state in (
                        RecordingState.REVIEW, RecordingState.CLASSIFY_OUTCOME
                    ) or event in ("save", "discard", "success", "failure", "incomplete"):
                        # Keep XR input/rendering alive; no IK or D0 on menu ticks.
                        if event not in ("stop", "save", "discard", "success", "failure", "incomplete"):
                            env._advance(4)
                        continue
                if performance is not None:
                    performance.add_stage(
                        "control_events", time.perf_counter_ns() - stage_started_ns
                    )
                    command_started_ns = time.perf_counter_ns()
                recenter_execution_reset = bool(
                    device.navigation_reset_applied and events.should_reset
                )
                if recenter_execution_reset:
                    processor.session_inactive()
                    print(
                        json.dumps(
                            {
                                "environment_reset": False,
                                "event": "demo_xr_navigation_retargeters_rebased",
                                "monotonic_ns": time.monotonic_ns(),
                                "session_running": device.session_running,
                                "step": control_steps,
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                host_reset = args_cli.s2_reset_step > 0 and control_steps == args_cli.s2_reset_step
                environment_reset_requested = bool(
                    (action is not None and events.should_reset and not recenter_execution_reset)
                    or host_reset
                )
                if environment_reset_requested and recording is not None:
                    assert recording_token is not None
                    recording.discard_observation(
                        recording_token, reason="environment_reset_requested"
                    )
                    recording_token = None
                if environment_reset_requested and lifecycle is not None:
                    lifecycle.external_reset()
                    action = None
                    observation = None
                    continue
                if environment_reset_requested:
                    env.reset(0)
                    processor.reset()
                    ik.reset()
                    if experiment is not None and not recording_requested:
                        experiment.after_reset()
                    # Camera frame indices are local to a reset epoch. Comparing the
                    # first post-reset index with the prior epoch would report a
                    # false stale frame even when both RGB observations are valid.
                    previous_camera_indices = None
                    camera_guard.reset()
                    device.reset(pause=False)
                    action = None  # Never reuse an action acquired before this reset.
                    observation = None
                    before_pose = ik.tcp_poses_base() if diagnostic else ()

                session_started_ever |= device.session_running
                display_button_value = 0.0
                backdrop_button_value = 0.0
                recenter_button_value = 0.0
                if action is None:
                    command = processor.session_inactive()
                else:
                    if tuple(action.shape) != (pipeline_action_dim,):
                        raise RuntimeError(
                            f"unexpected S2 pipeline action shape: {tuple(action.shape)}"
                        )
                    action_frames += 1
                    action_numpy = action.detach().cpu().numpy()
                    if not np.isfinite(action_numpy[PIPELINE_ACTION_DIM:]).all():
                        raise RuntimeError("Non-finite presentation controls")
                    if experiment is not None:
                        display_button_value = float(action_numpy[DEMO_DISPLAY_BUTTON_INDEX])
                        backdrop_button_value = float(action_numpy[DEMO_BACKDROP_BUTTON_INDEX])
                        recenter_button_value = float(action_numpy[DEMO_RECENTER_BUTTON_INDEX])
                    left, right = unpack_pipeline_action(action_numpy[:PIPELINE_ACTION_DIM])
                    command = processor.advance(
                        left,
                        right,
                        session_active=events.is_active is not False,
                    )
                if experiment is not None and not recording_requested:
                    smoke_display_edge = bool(
                        args_cli.demo_display_toggle_smoke and control_steps in (10, 20, 40, 50)
                    )
                    experiment.consume_display_button(
                        1.0 if smoke_display_edge else display_button_value,
                        event_origin=(
                            "bounded_xr_smoke_after_controller_mapping"
                            if args_cli.demo_display_toggle_smoke
                            else "controller_pipeline"
                        ),
                    )
                    smoke_backdrop_edge = bool(
                        args_cli.demo_backdrop_toggle_smoke and control_steps in (15, 25, 45, 55)
                    )
                    experiment.consume_backdrop_button(
                        1.0 if smoke_backdrop_edge else backdrop_button_value,
                        event_origin=(
                            "bounded_xr_smoke_after_controller_mapping"
                            if args_cli.demo_backdrop_toggle_smoke
                            else "controller_pipeline"
                        ),
                    )
                    smoke_recenter_edge = bool(
                        args_cli.demo_recenter_smoke and control_steps in (18, 48)
                    )
                    recenter_scheduled = (
                        action is not None or args_cli.demo_recenter_smoke
                    ) and experiment.consume_recenter_button(
                        1.0 if smoke_recenter_edge else recenter_button_value,
                        schedule_recenter=lambda: device.schedule_recenter_to_view(
                            experiment.recenter_view_prim_path
                        ),
                        event_origin=(
                            "bounded_xr_smoke_after_controller_mapping"
                            if args_cli.demo_recenter_smoke
                            else "controller_pipeline"
                        ),
                    )
                    if recenter_scheduled:
                        # Hold the accepted target on the teleport frame. The
                        # Device.advance keeps holding until the scheduled view
                        # is applied, then rebases upstream relative history.
                        command = processor.session_inactive()
                mode_changes = {
                    side: arm.sensitivity_mode
                    for side, arm in zip(
                        ("left", "right"),
                        (command.left, command.right),
                        strict=True,
                    )
                    if arm.transition.startswith("sensitivity_switched_")
                }
                if mode_changes:
                    print(
                        json.dumps(
                            {
                                "control": sensitivity["toggle_control"],
                                "event": "sensitivity_mode_changed",
                                "modes": mode_changes,
                                "session_running": device.session_running,
                                "step": control_steps,
                                "zero_delta_on_switch": True,
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                if performance is not None:
                    performance.add_stage(
                        "command_processing", time.perf_counter_ns() - command_started_ns
                    )
                    stage_started_ns = time.perf_counter_ns()
                xr = getattr(device, "xr_input", None)
                eligible = (
                    (lifecycle is None or lifecycle.admits_recording)
                    and
                    observation is not None
                    and xr is not None
                    and not xr.rebased
                    and xr.ran_synchronously
                    and all(xr.tracking_valid)
                    and recordable_teleop_command(command)
                )
                if lifecycle is not None and lifecycle.admits_recording and eligible and recording is None:
                    # First technical episode and every subsequent gap segment
                    # open only at a valid pre-action boundary.
                    from isaac_vr_recording import RecordingSession, start_live_recording

                    episode_id = f"episode_{recording_episode_index:06d}"
                    recordings_root = getattr(args_cli, "s2_recordings_root", None)
                    output_dir = technical_episode_output_dir(
                        first_dir=Path(args_cli.s2_recording_dir),
                        recordings_root=Path(recordings_root) if recordings_root is not None else None,
                        demo_id=str(lifecycle.demo_id), episode_index=recording_episode_index,
                        prior_episodes=bool(recording_episodes), repository=ROOT,
                    )
                    if recording_session is None:
                        recording_options: dict[str, Any] = {}
                        if performance is not None:
                            recording_options["timing_observer"] = observe_recording_timing
                        roots = recording_portable_roots(args_cli)
                        roots["recording"] = output_dir
                        with (performance.boundary("recording_session_preparation")
                              if performance is not None else nullcontext()):
                            recording = start_live_recording(
                                output_dir, env,
                                session_metadata=recording_session_metadata(
                                    xr_render=getattr(args_cli, "xr_render_readback", None),
                                    config_path=config_path, environment_pins=actual_versions,
                                    run_id=run_id, session_id=session_id, episode_id=episode_id,
                                    execution_profile="isaac_vr_record",
                                    processor_revision=PROCESSOR_REVISION,
                                ), portable_roots=roots, **recording_options,
                            )
                        recording_session = RecordingSession(recording)
                    else:
                        with (performance.boundary("technical_episode_open")
                              if performance is not None else nullcontext()):
                            recording = recording_session.start_episode(output_dir, episode_id)
                    if performance is not None and demo_start_requested_ns is not None:
                        performance.record_boundary(
                            "start_to_first_recording_ready",
                            time.perf_counter_ns() - demo_start_requested_ns,
                        )
                        demo_start_requested_ns = None
                    recording_episode_index += 1
                    recording_token = recording.capture_observation()
                    observation = recording_token.observation
                if recording is not None and not eligible:
                    assert recording_token is not None
                    if xr is None:
                        rejection_reason = "xr_receipt_unavailable"
                    elif not xr.ran_synchronously or not all(xr.tracking_valid):
                        rejection_reason = "xr_tracking_untrusted"
                    elif xr.rebased or any(arm.rebased for arm in (command.left, command.right)):
                        rejection_reason = "control_reference_rebased"
                    elif not command.session_active:
                        rejection_reason = "teleop_session_inactive"
                    elif any(not arm.tracking_valid for arm in (command.left, command.right)):
                        rejection_reason = "tracking_invalid"
                    else:
                        rejection_reason = "operator_hold"
                    recording.discard_observation(recording_token, reason=rejection_reason)
                    recording_token = None
                    # Seal this causal segment before unrecorded physics. The
                    # static recording session and CloudXR remain open.
                    if recording.committed_frames:
                        print(
                            json.dumps(
                                {
                                    "event": "recording_episode_boundary",
                                    "reason": rejection_reason,
                                    "left_transition": command.left.transition,
                                    "right_transition": command.right.transition,
                                    "xr_rebased": xr.rebased if xr is not None else None,
                                    "step": control_steps,
                                },
                                sort_keys=True,
                            ),
                            flush=True,
                        )
                        finalize_recording("operator_stopped", rejection_reason)
                        validator = None
                if eligible:
                    control_tick_id += 1  # Monotonic attempts; failures never reuse this ID.
                    device.validate_xr(xr)
                solution = _solve_native_decision(
                    ik,
                    command,
                    observation,
                    xr,
                    control_tick_id,
                    recording_requested=recording_requested,
                    eligible=eligible,
                )
                if eligible:
                    assert observation is not None and xr is not None
                    device.validate_xr(xr)
                    epoch = decision_epoch(
                        run_id,
                        observation,
                        xr,
                        episode_id=(
                            recording.episode_id if recording is not None else "unrecorded"
                        ),
                    )
                    if validator is None:
                        validator = CausalTransactionValidator(
                            "isaac",
                            "human_vr",
                            epoch,
                            profile=(recording.source_profile if recording is not None else None),
                        )
                    elif validator.epoch != epoch:
                        if recording is not None and recording.committed_frames:
                            assert recording_token is not None
                            recording.discard_observation(
                                recording_token, reason="causal_epoch_changed"
                            )
                            recording_token = None
                            print(
                                json.dumps(
                                    {
                                        "event": "recording_episode_boundary",
                                        "reason": "causal_epoch_changed",
                                        "left_transition": command.left.transition,
                                        "right_transition": command.right.transition,
                                        "xr_rebased": xr.rebased,
                                        "step": control_steps,
                                    },
                                    sort_keys=True,
                                ),
                                flush=True,
                            )
                            finalize_recording("operator_stopped", "causal_epoch_changed")
                            validator = None
                            # The solved command remains safe to apply; only its
                            # recording admission is rejected for this tick.
                            eligible = False
                        else:
                            validator.begin_epoch(epoch)
                    if eligible:
                        assert validator is not None
                        env.prepared_control_transaction = solution.prepare(validator)
                if solution is not None:
                    saturated_frames += int(ik.apply(solution))
                if eligible:
                    env.last_control_decision = solution
                if performance is not None:
                    performance.add_stage("ik_apply", time.perf_counter_ns() - stage_started_ns)
                    stage_started_ns = time.perf_counter_ns()
                env._advance(4)
                if performance is not None:
                    performance.add_stage(
                        "simulation_advance", time.perf_counter_ns() - stage_started_ns
                    )
                    stage_started_ns = time.perf_counter_ns()
                if recording is not None and eligible:
                    from isaac_vr_recording import build_committed_transition_sample

                    assert recording_token is not None
                    assert validator is not None
                    prepared = env.prepared_control_transaction
                    if prepared is None:
                        raise RuntimeError("recording transition was not prepared")
                    successor_token = recording.capture_successor(recording_token)
                    if performance is not None:
                        performance.add_stage(
                            "successor_capture", time.perf_counter_ns() - stage_started_ns
                        )
                        stage_started_ns = time.perf_counter_ns()
                    committed = commit_recording_transition(
                        validator,
                        solution,
                        prepared,
                        successor_token.observation,
                        physics_steps=4,
                    )
                    row = build_committed_transition_sample(
                        recording,
                        recording_token,
                        successor_token,
                        solution,
                        committed,
                    )
                    recording.commit_transition(recording_token, successor_token, row)
                    recording_token = None
                if performance is not None:
                    performance.add_stage(
                        "causal_commit_and_record", time.perf_counter_ns() - stage_started_ns
                    )
                    stage_started_ns = time.perf_counter_ns()
                after_pose = ik.tcp_poses_base() if diagnostic else ()
                if performance is not None:
                    performance.add_stage(
                        "tcp_pose_after", time.perf_counter_ns() - stage_started_ns
                    )
                    bookkeeping_started_ns = time.perf_counter_ns()

                for side, arm in zip(("left", "right"), (command.left, command.right), strict=True):
                    tracking_valid_frames[side] += int(arm.tracking_valid)
                for side, arm, before, after in zip(
                    ("left", "right") if diagnostic else (),
                    (command.left, command.right) if diagnostic else (),
                    before_pose,
                    after_pose,
                    strict=True,
                ):
                    sensitivity_mode_frames[side][arm.sensitivity_mode] += 1
                    observed = motion_scale_observed[side]
                    for channel, scale in (
                        ("translation", arm.translation_scale),
                        ("rotation", arm.rotation_scale),
                    ):
                        minimum = observed[f"{channel}_min"]
                        maximum = observed[f"{channel}_max"]
                        observed[f"{channel}_min"] = (
                            scale if minimum is None else min(minimum, scale)
                        )
                        observed[f"{channel}_max"] = (
                            scale if maximum is None else max(maximum, scale)
                        )
                    transition_counts[f"{side}:{arm.transition}"] = (
                        transition_counts.get(f"{side}:{arm.transition}", 0) + 1
                    )
                    if arm.rebased or arm.clutch_active:
                        maximum_rebase_motion_m[side] = max(
                            maximum_rebase_motion_m[side],
                            float(np.linalg.norm(after[:3] - before[:3])),
                        )

                if performance is not None:
                    performance.add_stage(
                        "runtime_bookkeeping", time.perf_counter_ns() - bookkeeping_started_ns
                    )
                    stage_started_ns = time.perf_counter_ns()
                camera = {"valid": True, "strictly_advanced": False, "roles": {}}
                if not recording_requested:
                    camera = camera_guard.sample(env)
                if diagnostic:
                    camera = _camera_sample(env, previous_camera_indices)
                    previous_camera_indices = camera.pop("frame_indices")
                    if not camera["valid"] or not camera["strictly_advanced"]:
                        raise RuntimeError(f"Strict diagnostic camera validation failed: {camera}")
                if performance is not None:
                    performance.add_stage(
                        "camera_observation", time.perf_counter_ns() - stage_started_ns
                    )
                    stage_started_ns = time.perf_counter_ns()
                camera_valid_frames += int(camera["valid"])
                camera_advanced_frames += int(camera["strictly_advanced"])
                if diagnostic and control_steps % 15 == 0:
                    gpu_samples.append(_gpu_observation())
                if performance is not None:
                    performance.add_stage("gpu_probe", time.perf_counter_ns() - stage_started_ns)
                    stage_started_ns = time.perf_counter_ns()
                if diagnostic and control_steps % 30 == 0:
                    print(
                        json.dumps(
                            {
                                "event": "s2_status",
                                "monotonic_ns": time.monotonic_ns(),
                                "step": control_steps,
                                "session_running": device.session_running,
                                "left": command.left.transition,
                                "right": command.right.transition,
                                "left_mode": command.left.sensitivity_mode,
                                "right_mode": command.right.sensitivity_mode,
                                "left_scale": command.left.translation_scale,
                                "right_scale": command.right.translation_scale,
                                "camera_valid": camera["valid"],
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                if performance is not None:
                    performance.add_stage("status_emit", time.perf_counter_ns() - stage_started_ns)
                    window = performance.end_step(
                        control_steps,
                        session_running=bool(device.session_running),
                        action_available=action is not None,
                        left_tracking_valid=bool(command.left.tracking_valid),
                        right_tracking_valid=bool(command.right.tracking_valid),
                        camera_valid=bool(camera["valid"]),
                        camera_advanced=bool(camera["strictly_advanced"]),
                        camera_diagnostics=camera,
                        left_transition=command.left.transition,
                        right_transition=command.right.transition,
                        left_scale=command.left.translation_scale,
                        right_scale=command.right.translation_scale,
                        environment_reset=bool(
                            host_reset or (events.should_reset and not recenter_execution_reset)
                        ),
                        navigation_rebased=recenter_execution_reset,
                        hud_visible=(
                            experiment.display_visible if experiment is not None else None
                        ),
                        backdrop_visible=(
                            experiment.backdrop_visible if experiment is not None else None
                        ),
                    )
                    if window is not None:
                        print(json.dumps(window, sort_keys=True), flush=True)
    except KeyboardInterrupt:
        interrupted = True
        recording_stop_reason = "keyboard_interrupt"
        print(
            json.dumps(
                {
                    "event": "s2_stop_requested",
                    "reason": "keyboard_interrupt",
                    "step": control_steps,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    except Exception as exc:
        recording_failure_reason = f"{type(exc).__name__}: {exc}"
        if lifecycle is not None:
            lifecycle.fail(exc)
            print(json.dumps({"event": "human_recording_state", "state": "failed",
                "error": lifecycle.error, "demo_id": lifecycle.demo_id}), flush=True)
        raise
    finally:
        try:
            try:
                if lifecycle is not None and lifecycle.state in (
                    RecordingState.RECORDING, RecordingState.REVIEW,
                    RecordingState.CLASSIFY_OUTCOME,
                ) and recording_failure_reason is None:
                    lifecycle.interrupt(
                        "keyboard_interrupt" if interrupted else "control_loop_completed"
                    )
                if recording is not None:
                    if recording_failure_reason is not None:
                        recording_outcome = "failure"
                        close_reason = recording_failure_reason
                    elif recording.committed_frames == 0:
                        recording_outcome = "aborted"
                        close_reason = recording_stop_reason or "no_committed_transitions"
                    else:
                        recording_outcome = "operator_stopped"
                        close_reason = recording_stop_reason or (
                            "keyboard_interrupt" if interrupted else "control_loop_completed"
                        )
                    if recording_session is None:
                        recording.close(outcome=recording_outcome, reason=close_reason)
                    else:
                        finalize_recording(recording_outcome, close_reason)
            finally:
                if recording_session is not None:
                    recording_session.close(
                        outcome="failure" if recording_failure_reason else "aborted",
                        reason=recording_failure_reason or "session_closed",
                    )
            if experiment is not None:
                experiment.close()
        finally:
            if performance is not None:
                performance_summary = performance.close()

    elapsed = time.perf_counter() - started
    gpu_end = _gpu_observation() if diagnostic else None
    gpu_samples.append(gpu_end)
    session_requirement_met = session_started_ever or not args_cli.s2_require_session
    tracking_requirement_met = (
        all(count > 0 for count in tracking_valid_frames.values())
        or not args_cli.s2_require_tracking
    )
    display_toggle_requirement_met = bool(
        not args_cli.demo_display_toggle_smoke
        or (experiment is not None and experiment.display_toggle_count == 4)
    )
    backdrop_toggle_requirement_met = bool(
        not args_cli.demo_backdrop_toggle_smoke
        or (experiment is not None and experiment.backdrop_toggle_count == 4)
    )
    recenter_smoke_requirement_met = bool(
        not args_cli.demo_recenter_smoke
        or (experiment is not None and experiment.recenter_request_count == 2)
    )
    passed = bool(
        control_steps == args_cli.s2_max_control_steps
        and camera_valid_frames == control_steps
        and (not diagnostic or camera_advanced_frames == control_steps)
        and session_requirement_met
        and tracking_requirement_met
        and display_toggle_requirement_met
        and backdrop_toggle_requirement_met
        and recenter_smoke_requirement_met
    )
    if sensitivity_control_mode == "slider":
        sensitivity_report = {
            "control_mode": "slider",
            "input_control": sensitivity["input_control"],
            "quest_control": sensitivity["quest_control"],
            "scope": sensitivity["scope"],
            "input_range": sensitivity["input_range"],
            "minimum": slider["minimum"],
            "center": slider["center"],
            "maximum": slider["maximum"],
            "mapping": sensitivity["mapping"],
        }
    else:
        sensitivity_report = {
            "control_mode": "toggle",
            "toggle_control": sensitivity["toggle_control"],
            **(
                {"quest_button": sensitivity["quest_button"]}
                if "quest_button" in sensitivity
                else {}
            ),
            "scope": sensitivity["scope"],
            "initial_mode": processor_cfg.initial_sensitivity_mode,
            "normal": {
                "translation_scale": processor_cfg.normal_translation_scale,
                "rotation_scale": processor_cfg.normal_rotation_scale,
            },
            "precise": {
                "translation_scale": processor_cfg.precise_translation_scale,
                "rotation_scale": processor_cfg.precise_rotation_scale,
            },
            "switch_behavior": "rising edge changes mode and emits zero Cartesian delta",
        }
    report: dict[str, Any] = {
        "gate": "NONE_EXPERIMENTAL" if experimental else "S2",
        "mode": "diagnostic" if diagnostic else "run",
        "status": (
            "experimental_runtime_smoke_passed_physical_demo_required"
            if experimental and passed
            else "runtime_smoke_passed_physical_human_gate_required"
            if passed
            else "failed"
        ),
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
            "sensitivity": sensitivity_report,
            "clutch": "independent squeeze > 0.5; release discards one delta",
            "gripper": (
                "independent analog trigger [0,1] maps linearly and monotonically "
                "from 0.1 m open to 0.0 m closed"
            ),
            "tracking_recovery": (
                "unusable pose invalidates upstream SE(3) baseline and smoothing; "
                "first recovered frame emits zero delta"
            ),
            "source_timestamp_threshold": None,
        },
        "xr_presentation": {
            "anchor_pos_m": anchor_position,
            "anchor_rot_xyzw": anchor_rotation,
            "near_plane_m": float(presentation["near_plane_m"]),
            "controller_transform_source": (
                "XRCore.get_physical_to_virtual_world_transform"
                if experiment is not None
                else "XrAnchorManager.get_world_matrix"
            ),
            "authoritative_scene_geometry_changed": False,
            **({"selected_vr_scene_geometry_applied": True} if experiment is not None else {}),
        },
        "session": {
            "single_controller_source": True,
            "started_ever": session_started_ever,
            "action_frames": action_frames,
            "require_session": bool(args_cli.s2_require_session),
            "require_physical_tracking": bool(args_cli.s2_require_tracking),
            **(
                {
                    "demo_display_toggle_smoke_met": display_toggle_requirement_met,
                    "demo_backdrop_toggle_smoke_met": backdrop_toggle_requirement_met,
                    "demo_recenter_smoke_met": recenter_smoke_requirement_met,
                }
                if experiment is not None
                else {}
            ),
        },
        "execution": {
            "control_steps": control_steps,
            "stopped_by_user": interrupted,
            "wall_seconds": elapsed,
            "control_hz": control_steps / elapsed,
            "physics_hz": (control_steps * 4) / elapsed,
            "saturated_frames": saturated_frames,
            "tracking_valid_frames": tracking_valid_frames,
            "sensitivity_mode_frames": sensitivity_mode_frames,
            "motion_scale_observed": motion_scale_observed,
            "transitions": transition_counts,
            "maximum_rebase_or_clutch_tcp_motion_m": maximum_rebase_motion_m,
            **({"performance": performance_summary} if performance_summary is not None else {}),
        },
        "cameras": {
            "left_wrist": "640x480 uint8 RGB HWC",
            "right_wrist": "640x480 uint8 RGB HWC",
            "valid_bimanual_frames": camera_valid_frames,
            "strictly_advanced_bimanual_frames": camera_advanced_frames,
        },
        "gpu": {"start": gpu_start, "end": gpu_end},
        "physical_human_gate": "required_not_implied_by_runtime_smoke",
        "passed": passed and not interrupted,
    }
    if experiment is not None and diagnostic:
        report["gpu"]["samples"] = gpu_samples
        report["composition"] = experiment.performance_report(elapsed, camera_advanced_frames)
        report["canonical_d0_changed"] = False
        report["production_gate_status_changed"] = False
    if recording_summary is not None:
        report["recording"] = recording_summary
    if recording_episodes:
        report["recording_episodes"] = recording_episodes
    if lifecycle is not None:
        report["human_recording"] = {
            "state": lifecycle.state.value,
            "demo_id": lifecycle.demo_id,
            "error": lifecycle.error,
            "saved_index_root": str(demo_index_root() / "saved_demos"),
        }
    if not diagnostic:
        report.pop("gpu")
        for key in (
            "sensitivity_mode_frames",
            "motion_scale_observed",
            "transitions",
            "maximum_rebase_or_clutch_tcp_motion_m",
        ):
            report["execution"].pop(key)
    if args_cli.report is not None:
        args_cli.report.write_text(
            json.dumps(jsonable(report), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(jsonable(report), sort_keys=True), flush=True)
    return 130 if interrupted else (0 if passed else 1)
