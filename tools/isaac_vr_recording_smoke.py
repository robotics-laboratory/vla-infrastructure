"""No-client Episode Recorder lifecycle smoke, isolated from XR/teleop imports."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

import yaml

from isaac_s2_performance import S2PerformanceLogger


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _place_rgb_assay_witnesses(env: Any) -> None:
    """Place live task cubes through Isaac's rigid-body API before recording opens."""
    experiment = env.vr_runtime
    if experiment is None or experiment.profile != "dual_cube_to_matching_plates":
        raise ValueError("RGB assay requires the current dual-cube native scene")
    for asset, position in zip(
        experiment.dynamic_assets,
        ((0.82, 0.13, 0.86), (0.87, -0.13, 0.87)),
        strict=True,
    ):
        pose = asset.data.default_root_pose.torch.clone()
        pose[0, :3] = pose.new_tensor(position)
        asset.write_root_pose_to_sim_index(root_pose=pose)
        asset.write_root_velocity_to_sim_index(
            root_velocity=asset.data.default_root_vel.torch.clone()
        )
    env._advance(4)


def _nvml_resource_sampler():
    """Create the benchmark sampler without spawning a process in the control loop."""
    from isaac_vr_recording_benchmark import ProcessResourceSampler

    class Utilization(ctypes.Structure):
        _fields_ = (("gpu", ctypes.c_uint), ("memory", ctypes.c_uint))

    class Memory(ctypes.Structure):
        _fields_ = (
            ("total", ctypes.c_ulonglong),
            ("free", ctypes.c_ulonglong),
            ("used", ctypes.c_ulonglong),
        )

    library = ctypes.CDLL("libnvidia-ml.so.1")
    handle = ctypes.c_void_p()

    def checked(result: int, operation: str) -> None:
        if result != 0:
            raise RuntimeError(f"NVML {operation} failed with status {result}")

    checked(library.nvmlInit_v2(), "initialization")
    checked(
        library.nvmlDeviceGetHandleByIndex_v2(ctypes.c_uint(0), ctypes.byref(handle)),
        "device lookup",
    )

    def gpu_probe() -> dict[str, float | int]:
        utilization = Utilization()
        memory = Memory()
        checked(
            library.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(utilization)),
            "utilization query",
        )
        checked(library.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(memory)), "memory query")
        return {
            "gpu_utilization_percent": float(utilization.gpu),
            "gpu_memory_bytes": int(memory.used),
        }

    def shutdown() -> None:
        checked(library.nvmlShutdown(), "shutdown")

    return ProcessResourceSampler(gpu_probe), shutdown


def recording_portable_roots(args_cli) -> dict[str, Path]:
    s1_config = yaml.safe_load(Path(args_cli.config).read_text(encoding="utf-8"))
    return {
        "recording": Path(args_cli.s2_recording_dir),
        "isaac61_production": Path(s1_config["environment"]["materialized_path"]).parent,
        "project_assets": Path(s1_config["asset"]["source_checkout"]).parent,
    }


def recording_session_metadata(
    *,
    config_path: Path,
    environment_pins: dict[str, Any],
    run_id: str,
    session_id: str,
    episode_id: str,
    execution_profile: str,
    processor_revision: str,
    xr_render: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        **({"xr_render": xr_render} if xr_render else {}),
        "run_id": run_id,
        "session_id": session_id,
        "episode_id": episode_id,
        "source_profile": "isaac_human_vr_offline_rgb_v2",
        "task": "dual_cube_to_matching_plates",
        "execution_profile": execution_profile,
        "live_rgb": False,
        "d0_revision": processor_revision,
        "runtime_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "environment_pins": environment_pins,
    }


def run_recording_lifecycle_smoke(
    env,
    args_cli,
    *,
    default_config_path: Path,
    processor_revision: str,
) -> int:
    """Exercise recording capture/finalization without importing XR or teleop."""

    from isaac_vr_recording import start_live_recording

    config_path = Path(getattr(args_cli, "s2_config", None) or default_config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["processor"]["revision"] != processor_revision:
        raise RuntimeError("S2 processor config/code revision mismatch")
    if not getattr(args_cli, "s2_record", False) or args_cli.s2_recording_dir is None:
        raise ValueError("recording lifecycle smoke requires --s2-recording-dir")
    if getattr(args_cli, "s2_teleop", False) or getattr(args_cli, "xr", False):
        raise ValueError("recording lifecycle smoke must not initialize teleop or XR")

    expected = config["environment"]
    environment_pins = {
        "isaac_sim": importlib.metadata.version("isaacsim"),
        "isaac_lab_package": importlib.metadata.version("isaaclab"),
        "isaac_lab_release": expected["isaac_lab_release"],
        "isaacteleop": importlib.metadata.version("isaacteleop"),
        "isaaclab_teleop": importlib.metadata.version("isaaclab-teleop"),
        "cloudxr_expected_not_initialized": expected["cloudxr_runtime_version"],
    }
    experiment = getattr(env, "vr_runtime", None)
    recording = None
    recording_session = None
    benchmark_logger = None
    benchmark_sampler = None
    benchmark_shutdown = None
    performance_path = getattr(args_cli, "s2_performance_log", None)
    performance = (
        S2PerformanceLogger(
            Path(performance_path),
            window_steps=args_cli.s2_performance_window_steps,
            warmup_steps=args_cli.s2_performance_warmup_steps,
            target_hz=30.0,
        )
        if performance_path is not None
        else None
    )
    env.performance_logger = performance
    summary: dict[str, Any] = {}
    try:
        if experiment is not None:
            experiment.disable_live_rgb()
        if getattr(args_cli, "s2_rgb_e2e_assay", False):
            _place_rgb_assay_witnesses(env)
        # The caller has already reset, settled and validated this exact scene.
        # A second reset would invalidate the accepted three-camera boundary and
        # make this lifecycle probe exercise renderer startup instead of storage.
        run_id, session_id = str(uuid4()), str(uuid4())
        episode_id = "episode_000000"
        benchmark_log = getattr(args_cli, "s2_recording_benchmark_log", None)

        def observe_recording_timing(name: str, elapsed_ns: int) -> None:
            if benchmark_log is not None and benchmark_logger is None:
                raise RuntimeError("recording timing arrived before benchmark logger startup")
            if benchmark_logger is not None:
                benchmark_logger.add_stage(name, elapsed_ns)
            if performance is not None:
                performance.add_nested(name, elapsed_ns)

        recording_options: dict[str, Any] = {}
        if benchmark_log is not None:
            recording_options = {
                "flush_every_frames": int(args_cli.s2_recording_benchmark_flush_every_frames),
            }
        if benchmark_log is not None or performance is not None:
            recording_options["timing_observer"] = observe_recording_timing
        recording = start_live_recording(
            args_cli.s2_recording_dir,
            env,
            session_metadata=recording_session_metadata(
                xr_render=getattr(args_cli, "xr_render_readback", None),
                config_path=config_path,
                environment_pins=environment_pins,
                run_id=run_id,
                session_id=session_id,
                episode_id=episode_id,
                execution_profile="isaac_vr_record_no_client_lifecycle_smoke",
                processor_revision=processor_revision,
            ),
            portable_roots=recording_portable_roots(args_cli),
            **recording_options,
        )
        if getattr(args_cli, "s2_rgb_e2e_assay", False):
            from isaac_vr_recording import RecordingSession

            recording_session = RecordingSession(recording)
        if getattr(args_cli, "s2_injected_recording_smoke", False):
            from isaac_vr_injected_recording import (
                record_injected_transitions,
                validate_injected_recording,
            )

            rgb_e2e_assay = bool(getattr(args_cli, "s2_rgb_e2e_assay", False))
            injected_count = 6 if rgb_e2e_assay else 3
            if benchmark_log is not None:
                from isaac_vr_recording_benchmark import BenchmarkRunLogger

                warmup_steps = int(args_cli.s2_recording_benchmark_warmup_steps)
                measured_steps = int(args_cli.s2_recording_benchmark_measured_steps)
                injected_count = warmup_steps + measured_steps
                manifest = json.loads((recording.output_dir / "manifest.json").read_text())
                repository = Path(__file__).resolve().parents[1]
                dirty_status = subprocess.check_output(
                    ["git", "-C", str(repository), "status", "--porcelain=v1"], text=True
                )
                measurement_files = (
                    Path(__file__),
                    repository / "tools/isaac_vr_injected_recording.py",
                    repository / "tools/isaac_vr_recording.py",
                    repository / "tools/isaac_vr_recording_benchmark.py",
                )
                benchmark_identity = {
                    "pair_id": str(args_cli.s2_recording_benchmark_pair_id),
                    "condition": "recording",
                    "run_id": recording.run_id,
                    "git_commit": manifest["git_commit"],
                    "dirty_status_sha256": hashlib.sha256(dirty_status.encode()).hexdigest(),
                    "environment_sha256": _canonical_sha256(environment_pins),
                    "measurement_provenance_sha256": _canonical_sha256(
                        {
                            "files": {
                                str(path.relative_to(repository)): hashlib.sha256(
                                    path.read_bytes()
                                ).hexdigest()
                                for path in measurement_files
                            },
                            "unavailable_timing_metrics": ["render_ms", "xr_ms"],
                        }
                    ),
                    "scene_snapshot_sha256": manifest["stage_snapshot_sha256"],
                    "visual_provenance_sha256": manifest["visual_provenance_sha256"],
                    "source_profile": recording.source_profile,
                    "quest_session_id": "not-applicable:no-headset-injected",
                    "target_hz": 30.0,
                    "warmup_steps": warmup_steps,
                    "measured_steps": measured_steps,
                    "headset_connected": False,
                    "pair_order": int(args_cli.s2_recording_benchmark_pair_order),
                }
                benchmark_logger = BenchmarkRunLogger(
                    Path(benchmark_log),
                    benchmark_identity,
                    unavailable_timing_metrics=("render_ms", "xr_ms"),
                )
                benchmark_sampler, benchmark_shutdown = _nvml_resource_sampler()
            injected = record_injected_transitions(
                recording,
                env,
                count=injected_count,
                benchmark_logger=benchmark_logger,
                resource_sampler=benchmark_sampler,
                performance_logger=performance,
                rgb_e2e_assay=rgb_e2e_assay,
            )
            summary = {
                **injected,
                "artifact_state": "finalized",
                "discarded_observations": recording.discarded_observations,
                "episode_id": recording.episode_id,
                "mode": "injected_recording_integration_smoke",
                "outcome": "operator_stopped",
                "passed": True,
                "reason": "deterministic_injected_xr_completed",
                "run_id": recording.run_id,
                "session_id": recording.session_id,
                "teleop_initialized": False,
                "xr_initialized": False,
            }
            hdf5_path = recording.hdf5_path
            owner = recording_session if recording_session is not None else recording
            owner.close(outcome="operator_stopped", reason="deterministic_injected_xr_completed")
            recording = None
            recording_session = None
            if benchmark_logger is not None:
                benchmark_logger.close(recording_hdf5=hdf5_path)
                summary["benchmark"] = {
                    "log": str(Path(benchmark_log).resolve()),
                    "qualification": "not_eligible_no_headset_render_xr_not_measured",
                    "unavailable_timing_metrics": ["render_ms", "xr_ms"],
                }
            summary["reader_validation"] = validate_injected_recording(
                hdf5_path,
                portable_roots=recording_portable_roots(args_cli),
            )
        else:
            token = recording.capture_observation()
            recording.discard_observation(token, reason="no_client_lifecycle_smoke")
            summary = {
                "artifact_state": "failed",
                "committed_frames": 0,
                "discarded_observations": recording.discarded_observations,
                "episode_id": recording.episode_id,
                "mode": "recording_lifecycle_smoke",
                "outcome": "aborted",
                "passed": True,
                "reason": "no_client_lifecycle_smoke",
                "run_id": recording.run_id,
                "session_id": recording.session_id,
                "teleop_initialized": False,
                "xr_initialized": False,
            }
            recording.close(outcome="aborted", reason="no_client_lifecycle_smoke")
            recording = None
    except Exception as exc:
        if recording is not None:
            owner = recording_session if recording_session is not None else recording
            owner.close(outcome="failure", reason=f"recording_lifecycle_smoke_failed:{type(exc).__name__}:{exc}")
        raise
    finally:
        try:
            if benchmark_shutdown is not None:
                benchmark_shutdown()
            if experiment is not None:
                experiment.close()
        finally:
            if performance is not None:
                summary["performance"] = performance.close()
    if getattr(args_cli, "report", None) is not None:
        Path(args_cli.report).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0
