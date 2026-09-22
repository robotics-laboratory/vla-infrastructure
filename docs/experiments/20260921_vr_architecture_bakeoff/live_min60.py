"""Exact LIVE-MIN deferred-camera experiment boundary.

Two 60 Hz or four 120 Hz integrations feed one synchronized Kit/RTX render,
then the existing three-Camera capture barrier extracts and owns RGB copies.
Canonical sources and configuration remain untouched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import numpy as np


ROLES = ("left_wrist", "right_wrist", "scene")


def install(env, args) -> None:
    import carb.settings
    from omni.kit.xr.core import XRSettings

    out = Path(os.environ["VR_BAKEOFF_OUTPUT"])
    candidate = os.environ["VR_BAKEOFF_CANDIDATE"]
    physics_hz, physics_steps = (
        (120.0, 4) if candidate == "LIVE-MIN120-DEFERRED" else (60.0, 2)
    )
    dt = 1.0 / physics_hz
    settings = carb.settings.get_settings()
    settings.set("/rtx/rendermode", "MinimalRendering")
    settings.set("/rtx/minimal/mode", 2)
    # The pinned XR experience enables asynchronous app rendering. Its camera
    # products were measured one physics boundary behind. SyntheticData does
    # not support that mode; use the supported synchronous Kit handoff here.
    settings.set("/app/asyncRendering", False)
    settings.set("/app/asyncRenderingLowLatency", False)
    settings.set("/omni/replicator/asyncRendering", False)
    XRSettings.get_singleton().set_setting(
        "profile/persistent/render/resolutionMultiplier", 0.4
    )

    if abs(float(env.sim.cfg.dt) - dt) > 1.0e-12:
        raise RuntimeError(f"{candidate} requires physics dt {dt}, got {env.sim.cfg.dt}")

    # Do not bind SceneUI panels; canonical camera products remain live.
    runtime = env.vr_runtime
    runtime.hud_on_start = False
    runtime.feed_session_prepared_enabled = False
    runtime.consume_display_button = lambda *a, **kw: None
    args.demo_display_toggle_smoke = False

    original_advance = env._advance
    samples_path = out / "live_min60_samples.jsonl"
    accepted = {role: 0 for role in ROLES}
    sequence = 0
    capture_sync_installed = False
    capture_sync_previous = None

    def add_nested(name: str, elapsed_ns: int) -> None:
        logger = getattr(env, "performance_logger", None)
        if logger is not None:
            logger.add_nested(name, elapsed_ns)

    def control_advance() -> None:
        nonlocal sequence, capture_sync_installed, capture_sync_previous
        if not capture_sync_installed:
            # Apply only after the SimulationApp, scene, and render products
            # exist. Loading this interface during Kit startup can stall the
            # application before the scene is available.
            import omni.kit.renderer_capture

            renderer_capture = omni.kit.renderer_capture.acquire_renderer_capture_interface()
            capture_sync_previous = renderer_capture.set_capture_sync(True)
            capture_sync_installed = True
        boundary_started = time.perf_counter_ns()
        physics_ns = 0
        update_ns = 0
        for _ in range(physics_steps):
            started = time.perf_counter_ns()
            for robot in env.robots:
                robot.write_data_to_sim()
            env.sim.step(render=False)
            physics_ns += time.perf_counter_ns() - started

            started = time.perf_counter_ns()
            for robot in env.robots:
                robot.update(dt)
            env._state_physics_step = env.sim.get_physics_step_count()
            env.physics_probe.update(dt)
            runtime.update(dt)
            update_ns += time.perf_counter_ns() - started

        started = time.perf_counter_ns()
        env.sim.forward()
        synchronization_ns = time.perf_counter_ns() - started

        started = time.perf_counter_ns()
        runtime.before_render()
        env.sim.render()
        render_ns = time.perf_counter_ns() - started

        started = time.perf_counter_ns()
        env.camera.capture_boundary(env)
        extraction_ns = time.perf_counter_ns() - started

        started = time.perf_counter_ns()
        frozen = env.camera.capture.freeze()
        freeze_ns = time.perf_counter_ns() - started
        capture = env.latest_observation_capture()
        if capture.producer.physics_step != env.sim.get_physics_step_count():
            raise RuntimeError(f"{candidate} capture does not belong to current physics state")
        for role in ROLES:
            image = frozen[f"observation.images.{role}"]
            if image.shape != (480, 640, 3) or image.dtype != np.uint8 or not image.flags.owndata:
                raise RuntimeError(f"{role}: RGB snapshot is not owned uint8 640x480 RGB")
            accepted[role] += 1
        sequence += 1
        total_ns = time.perf_counter_ns() - boundary_started
        sample = {
            "sequence": sequence,
            "physics_step": env.sim.get_physics_step_count(),
            "reset_epoch": capture.producer.reset_epoch,
            "physics_ms": physics_ns / 1.0e6,
            "state_updates_ms": update_ns / 1.0e6,
            "synchronization_ms": synchronization_ns / 1.0e6,
            "render_app_ms": render_ns / 1.0e6,
            "camera_extraction_ms": extraction_ns / 1.0e6,
            "rgb_freeze_ms": freeze_ns / 1.0e6,
            "acquisition_boundary_ms": total_ns / 1.0e6,
            "renders": 1,
            "physics_steps": physics_steps,
            "bytes_per_tick": sum(
                frozen[f"observation.images.{role}"].nbytes for role in ROLES
            ),
            "accepted": dict(accepted),
        }
        with samples_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(sample, separators=(",", ":")) + "\n")
        add_nested("live_min60_physics", physics_ns)
        add_nested("live_min60_state_updates", update_ns)
        add_nested("live_min60_synchronization", synchronization_ns)
        add_nested("live_min60_render_app", render_ns)
        add_nested("live_min60_camera_extraction", extraction_ns)
        add_nested("live_min60_rgb_freeze", freeze_ns)

    def advance(repeat: int) -> None:
        # The shared S2 loop requests four canonical 120 Hz steps per control.
        # Replace only that steady-state request. Startup/reset settling keeps
        # its existing lifecycle and is outside benchmark measurement.
        if repeat == 4:
            return control_advance()
        return original_advance(repeat)

    env._advance = advance
    manifest = {
        "candidate": candidate,
        "physics_hz": physics_hz,
        "control_target_hz": 30.0,
        "physics_steps_per_control": physics_steps,
        "renders_per_control": 1,
        "renderer": "MinimalRendering",
        "minimal_mode": 2,
        "xr_scale": 0.4,
        "app_async_rendering": False,
        "replicator_async_rendering": False,
        "renderer_capture_sync": True,
        "renderer_capture_sync_install": "first control boundary after render products exist",
        "camera_implementation": "three independent Isaac Lab Camera products",
        "camera_roles": list(ROLES),
        "camera_shape": [480, 640, 3],
        "camera_dtype": "uint8",
        "preview_panels": False,
        "rgb_owned_freeze": True,
        "bytes_per_tick": 2_764_800,
        "hdf5": False,
        "recorder_manager": False,
        "lerobot_encoding": False,
        "phase_fix": (
            "disable unsupported app async rendering; explicit PhysX/Fabric "
            "forward before one Kit render; synchronous renderer capture"
        ),
        "extra_physics_steps": 0,
        "extra_renders": 0,
    }
    (out / "live_min60_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
