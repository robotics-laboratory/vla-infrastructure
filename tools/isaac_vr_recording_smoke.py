"""No-client Episode Recorder lifecycle smoke, isolated from XR/teleop imports."""

from __future__ import annotations

import ctypes
from contextlib import nullcontext
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import time
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


def _run_gap_audit(
    recording, session, env, args_cli, performance, audit_device, *, count: int,
) -> tuple[Any, dict[str, Any], list[Path]]:
    """Inject sparse tracking-invalid rejections through the current session owner."""
    from isaac_vr_episode_lifecycle import technical_episode_output_dir
    from isaac_vr_injected_recording import record_injected_transitions

    gaps = int(args_cli.s2_audit_gaps)
    sizes = [count // (gaps + 1) + (index < count % (gaps + 1))
             for index in range(gaps + 1)]
    first_dir = recording.output_dir
    paths: list[Path] = []
    episodes: list[dict[str, Any]] = []
    tick = 1
    committed_before = 0
    pending_first_commit = None
    for index, size in enumerate(sizes):
        record_injected_transitions(
            recording, env, count=size, performance_logger=performance,
            input_pump=audit_device.advance, fixed_input=True,
            require_distinct_actions=False, start_tick=tick,
            target_index_offset=committed_before,
            first_commit_callback=pending_first_commit,
        )
        tick += size
        committed_before += size
        episodes.append({
            "episode_id": recording.episode_id,
            "hdf5": str(recording.hdf5_path),
            "committed_frames": recording.committed_frames,
            "first_committed_tick": tick - size,
            "last_committed_tick": tick - 1,
        })
        paths.append(recording.hdf5_path)
        pending_first_commit = None
        if index == gaps:
            break
        gap_started_ns = time.perf_counter_ns()
        token = recording.capture_observation()
        recording.discard_observation(token, reason="tracking_invalid")
        with performance.boundary("technical_episode_end", gap_index=index + 1):
            session.end_episode(outcome="operator_stopped", reason="tracking_invalid")
        episodes[-1]["discarded_observations"] = recording.discarded_observations
        env._advance(4)  # The inadmissible control advances without a committed row.
        tick += 1
        next_dir = technical_episode_output_dir(
            first_dir=first_dir,
            recordings_root=Path(args_cli.s2_recordings_root),
            demo_id=recording.session_id,
            episode_index=index + 1,
            prior_episodes=True,
            repository=Path(__file__).resolve().parents[1],
        )
        with performance.boundary("technical_episode_open", gap_index=index + 1):
            recording = session.start_episode(next_dir, f"episode_{index + 1:06d}")

        def first_commit(gap_index=index + 1, started_ns=gap_started_ns) -> None:
            performance.record_boundary(
                "technical_gap_to_first_commit",
                time.perf_counter_ns() - started_ns,
                gap_index=gap_index,
            )

        pending_first_commit = first_commit
    return recording, {
        "accepted_transactions": sum(item["committed_frames"] for item in episodes),
        "committed_frames": sum(item["committed_frames"] for item in episodes),
        "expected_gaps": gaps,
        "technical_episodes": episodes,
        "source": "deterministic_injected_xr_v1",
    }, paths


def run_recording_lifecycle_smoke(
    env,
    args_cli,
    *,
    default_config_path: Path,
    processor_revision: str,
    audit_device: Any | None = None,
) -> int:
    """Exercise the native recorder with the existing deterministic input seam."""

    from isaac_vr_recording import start_live_recording

    config_path = Path(getattr(args_cli, "s2_config", None) or default_config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config["processor"]["revision"] != processor_revision:
        raise RuntimeError("S2 processor config/code revision mismatch")
    if not getattr(args_cli, "s2_record", False) or args_cli.s2_recording_dir is None:
        raise ValueError("recording lifecycle smoke requires --s2-recording-dir")
    if audit_device is None and (getattr(args_cli, "s2_teleop", False) or getattr(args_cli, "xr", False)):
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
    if audit_device is not None:
        from isaacteleop.cloudxr.runtime import runtime_version

        environment_pins.pop("cloudxr_expected_not_initialized")
        environment_pins["cloudxr"] = runtime_version()
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
            if benchmark_logger is not None and name in {"hdf_append_ms", "hdf_flush_ms"}:
                benchmark_logger.add_stage(name, elapsed_ns)
            if performance is not None:
                if name in {"hdf_append_ms", "hdf_flush_ms"}:
                    performance.add_nested(name, elapsed_ns)
                else:
                    performance.record_boundary(name, elapsed_ns)

        recording_options: dict[str, Any] = {}
        if benchmark_log is not None:
            recording_options = {
                "flush_every_frames": int(args_cli.s2_recording_benchmark_flush_every_frames),
            }
        if benchmark_log is not None or performance is not None:
            recording_options["timing_observer"] = observe_recording_timing
        with (performance.boundary("recording_session_preparation")
              if performance is not None else nullcontext()):
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
                    execution_profile=(
                        "isaac_vr_record_injected_no_client_audit"
                        if getattr(args_cli, "s2_current_record_audit", None) is not None
                        else "isaac_vr_record_no_client_lifecycle_smoke"
                    ),
                    processor_revision=processor_revision,
                ),
                portable_roots=recording_portable_roots(args_cli),
                **recording_options,
            )
            if getattr(args_cli, "s2_injected_recording_smoke", False):
                from isaac_vr_recording import RecordingSession

                recording_session = RecordingSession(recording)
        if getattr(args_cli, "s2_injected_recording_smoke", False):
            from isaac_vr_injected_recording import (
                record_injected_transitions,
                validate_injected_recording,
            )

            rgb_e2e_assay = bool(getattr(args_cli, "s2_rgb_e2e_assay", False))
            injected_count = 6 if rgb_e2e_assay else int(args_cli.s2_injected_count)
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
            audit_mode = getattr(args_cli, "s2_current_record_audit", None)
            if audit_mode == "gap":
                recording, injected, hdf5_paths = _run_gap_audit(
                    recording, recording_session, env, args_cli, performance,
                    audit_device, count=injected_count,
                )
            else:
                injected = record_injected_transitions(
                    recording,
                    env,
                    count=injected_count,
                    benchmark_logger=benchmark_logger,
                    resource_sampler=benchmark_sampler,
                    performance_logger=performance,
                    rgb_e2e_assay=rgb_e2e_assay,
                    input_pump=audit_device.advance if audit_device is not None else None,
                    fixed_input=audit_mode is not None,
                    clutch_pattern=audit_mode == "clutch",
                    require_distinct_actions=audit_mode is None,
                )
                hdf5_paths = [recording.hdf5_path]
            summary = {
                **injected,
                "artifact_state": "finalized",
                "discarded_observations": (
                    sum(item.get("discarded_observations", 0)
                        for item in injected["technical_episodes"])
                    if audit_mode == "gap" else recording.discarded_observations
                ),
                "episode_id": recording.episode_id,
                "mode": "injected_recording_integration_smoke",
                "outcome": "operator_stopped",
                "passed": True,
                "reason": "deterministic_injected_xr_completed",
                "run_id": recording.run_id,
                "session_id": recording.session_id,
                "teleop_initialized": audit_device is not None,
                "xr_initialized": bool(audit_device is not None and args_cli.xr),
                "kit_xr_bridge": bool(audit_device is not None and args_cli.xr),
                "session_running_at_end": bool(audit_device.session_running)
                if audit_device is not None else False,
                "xr_input_available_at_end": (
                    getattr(audit_device, "xr_input", None) is not None
                    if audit_device is not None else False
                ),
                "cloudxr_profile": getattr(args_cli, "s2_cloudxr_profile", None),
                "input_pump_calls": injected_count if audit_device is not None else 0,
                "processor_executed": False,
                "ik_executed": False,
                "xr_receipt": "synthetic",
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
            validations = []
            for path in hdf5_paths:
                roots = recording_portable_roots(args_cli)
                roots["recording"] = path.parent
                validations.append(validate_injected_recording(path, portable_roots=roots))
            summary["reader_validation"] = (
                validations if audit_mode == "gap" else validations[0]
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


def run_injected_lifecycle_audit(
    env, args_cli, *, default_config_path: Path, processor_revision: str, audit_device: Any,
) -> int:
    """Drive the real lifecycle callbacks with bounded synthetic button edges."""
    from isaacteleop.cloudxr.runtime import runtime_version
    from isaac_vr_episode_lifecycle import (
        RecordingLifecycle, publish_saved_demo, publish_unsaved_demo,
        technical_episode_output_dir,
    )
    from isaac_vr_injected_recording import record_injected_transitions, validate_injected_recording
    from isaac_vr_recording import RecordingSession, start_live_recording

    config_path = Path(getattr(args_cli, "s2_config", None) or default_config_path)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    expected = config["environment"]
    environment_pins = {
        "isaac_sim": importlib.metadata.version("isaacsim"),
        "isaac_lab_package": importlib.metadata.version("isaaclab"),
        "isaac_lab_release": expected["isaac_lab_release"],
        "isaacteleop": importlib.metadata.version("isaacteleop"),
        "isaaclab_teleop": importlib.metadata.version("isaaclab-teleop"),
        "cloudxr": runtime_version(),
    }
    performance = S2PerformanceLogger(
        Path(args_cli.s2_performance_log),
        window_steps=args_cli.s2_performance_window_steps,
        warmup_steps=args_cli.s2_performance_warmup_steps,
        target_hz=30.0,
    )
    experiment = getattr(env, "vr_runtime", None)
    if experiment is not None:
        experiment.disable_live_rgb()
    root = Path(args_cli.s2_recordings_root)
    first_dir = Path(args_cli.s2_recording_dir)
    run_id = str(uuid4())
    active = None
    session = None
    episodes: list[dict[str, Any]] = []
    hdf5_paths: list[Path] = []
    events: list[dict[str, Any]] = []
    tick = 1

    def observe(name: str, elapsed_ns: int) -> None:
        if name in {"hdf_append_ms", "hdf_flush_ms"}:
            performance.add_nested(name, elapsed_ns)
        else:
            performance.record_boundary(name, elapsed_ns)

    def seal(reason: str) -> None:
        nonlocal active, session
        with performance.boundary("demo_stop_seal", reason=reason):
            assert session is not None and active is not None
            episode = {"episode_id": active.episode_id, "output_dir": str(active.output_dir),
                       "committed_frames": active.committed_frames}
            hdf5_path = active.hdf5_path
            session.close(outcome="operator_stopped", reason=reason)
            session, active = None, None
            episodes.append(episode)
            hdf5_paths.append(hdf5_path)

    def publish(demo_id: str, outcome: str) -> None:
        with performance.boundary("demo_classification_publication", classification=outcome):
            publish_saved_demo(
                root / "saved_demos", demo_id=demo_id, episodes=episodes[-1:],
                profile="isaac_human_vr_offline_rgb_v2", start_tick=tick - args_cli.s2_injected_count,
                stop_tick=tick - 1, task_outcome=outcome,
            )

    def discard(demo_id: str) -> None:
        with performance.boundary("demo_discard_publication"):
            publish_unsaved_demo(
                root, demo_id=demo_id, classification="discarded", episodes=episodes[-1:]
            )

    def reset() -> None:
        with performance.boundary("demo_reset"):
            env.reset(0)
            audit_device.reset(pause=False)

    lifecycle = RecordingLifecycle(
        seal=seal, publish=publish, reset=reset, discard=discard,
    )
    outcomes = ("success", "failure", "incomplete", "discard", "success")
    cycles = int(args_cli.s2_audit_lifecycle_cycles)
    try:
        for index in range(cycles):
            after_reset_ns = time.perf_counter_ns()
            event = lifecycle.buttons(x=True, y=False, b=False)
            assert event == "start" and lifecycle.demo_id is not None
            demo_id = lifecycle.demo_id
            lifecycle.buttons(x=False, y=False, b=False)
            if index:
                performance.record_boundary("next_start_after_reset",
                                            time.perf_counter_ns() - after_reset_ns)
            start_ns = time.perf_counter_ns()
            output_dir = technical_episode_output_dir(
                first_dir=first_dir, recordings_root=root, demo_id=demo_id,
                episode_index=0, prior_episodes=index > 0,
                repository=Path(__file__).resolve().parents[1],
            )
            roots = recording_portable_roots(args_cli)
            roots["recording"] = output_dir
            with performance.boundary("recording_session_preparation", cycle=index + 1):
                active = start_live_recording(
                    output_dir, env,
                    session_metadata=recording_session_metadata(
                        config_path=config_path, environment_pins=environment_pins,
                        run_id=run_id, session_id=str(uuid4()), episode_id="episode_000000",
                        execution_profile="isaac_vr_record_injected_no_client_lifecycle_audit",
                        processor_revision=processor_revision,
                        xr_render=getattr(args_cli, "xr_render_readback", None),
                    ),
                    portable_roots=roots, timing_observer=observe,
                )
                session = RecordingSession(active)
            performance.record_boundary("start_to_first_recording_ready",
                                        time.perf_counter_ns() - start_ns, cycle=index + 1)
            record_injected_transitions(
                active, env, count=args_cli.s2_injected_count,
                performance_logger=performance, input_pump=audit_device.advance,
                fixed_input=True, require_distinct_actions=False, start_tick=tick,
            )
            tick += args_cli.s2_injected_count
            event = lifecycle.buttons(x=False, y=True, b=False)
            assert event == "stop"
            lifecycle.buttons(x=False, y=False, b=False)
            outcome = outcomes[index]
            if outcome == "discard":
                event = lifecycle.buttons(x=False, y=False, b=True)
                assert event == "discard"
                lifecycle.buttons(x=False, y=False, b=False)
            else:
                started_ns = time.perf_counter_ns()
                event = lifecycle.buttons(x=True, y=False, b=False)
                assert event == "save"
                performance.record_boundary("demo_save_selection",
                                            time.perf_counter_ns() - started_ns)
                lifecycle.buttons(x=False, y=False, b=False)
                button = {"success": "x", "failure": "y", "incomplete": "b"}[outcome]
                event = lifecycle.buttons(**{key: key == button for key in ("x", "y", "b")})
                assert event == outcome
                lifecycle.buttons(x=False, y=False, b=False)
            events.append({"cycle": index + 1, "outcome": outcome, "demo_id": demo_id,
                           "state_after": lifecycle.state.value})
    finally:
        if session is not None:
            session.close(outcome="failure", reason="lifecycle_audit_interrupted")
        summary = performance.close()
        if experiment is not None:
            experiment.close()
    result = {
        "mode": "injected_no_client_lifecycle_audit", "passed": True,
        "cycles": cycles, "events": events, "technical_episodes": episodes,
        "reader_validation": [], "performance": summary,
        "source_profile": "isaac_human_vr_offline_rgb_v2",
        "processor_executed": False, "ik_executed": False,
        "xr_receipt": "synthetic", "kit_xr_bridge_configured": bool(args_cli.xr),
        "cloudxr_profile": args_cli.s2_cloudxr_profile,
        "session_running_at_end": bool(audit_device.session_running),
    }
    for path in hdf5_paths:
        roots = recording_portable_roots(args_cli)
        roots["recording"] = path.parent
        result["reader_validation"].append(
            validate_injected_recording(path, portable_roots=roots)
        )
    Path(args_cli.report).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0
