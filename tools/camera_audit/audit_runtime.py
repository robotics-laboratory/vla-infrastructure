"""Bounded composition of pinned APIs; timers never force CUDA synchronization."""

import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

ROLES = ("left_wrist", "right_wrist", "scene")
SETTINGS = (
    "/app/asyncRendering",
    "/app/asyncRenderingLowLatency",
    "/omni/replicator/asyncRendering",
    "/app/useFabricSceneDelegate",
    "/rtx/hydra/readTransformsFromFabricInRenderDelegate",
    "/rtx/rendermode",
    "/rtx/minimal/mode",
    "/persistent/xr/profile/ar/render/resolutionMultiplier",
    "/physics/updateToUsd",
    "/app/player/playSimulations",
    "/exts/omni.replicator.core/Orchestrator/enabled",
    "/omni/replicator/captureOnPlay",
)


def install(env, args):
    import carb.settings
    import omni.kit.app
    import omni.physx
    from isaac_s2_performance import S2PerformanceLogger
    from isaac_vr_capture import tensor

    out = Path(os.environ["CAMERA_AUDIT_OUTPUT"])
    candidate = os.environ["CAMERA_AUDIT_TEMPORAL"]
    level = int(os.environ["CAMERA_AUDIT_COST"][1:])
    probe_count = int(os.environ["CAMERA_AUDIT_PROBE"])
    rig = env.camera
    cameras = dict(zip(ROLES, (*rig.wrists, rig.scene_camera), strict=True))
    owners = list(
        {id(getattr(c, "owner", c)): getattr(c, "owner", c) for c in cameras.values()}.values()
    )
    for camera in cameras.values():
        if hasattr(camera, "owner"):
            camera._view = SimpleNamespace(prim_paths=[camera.path])
    settings = carb.settings.get_settings()

    def effective():
        return {key: settings.get(key) for key in SETTINGS}

    (out / "settings-before.json").write_text(json.dumps(effective(), indent=2))
    env.render_only_final_substep = True
    counts = {"kit": 0, "native_physics": 0, "forward": 0}
    subscriptions = [
        omni.kit.app.get_app()
        .get_update_event_stream()
        .create_subscription_to_pop(lambda event: counts.__setitem__("kit", counts["kit"] + 1))
    ]
    subscriptions.append(
        omni.physx.get_physx_interface().subscribe_physics_step_events(
            lambda dt: counts.__setitem__("native_physics", counts["native_physics"] + 1)
        )
    )
    drawables = {}
    from carb.eventdispatcher import get_eventdispatcher
    import omni.hydratexture

    for index, camera in enumerate(owners):
        texture = camera._render_data.render_product.hydra_texture
        drawables[str(index)] = 0
        subscriptions.append(
            get_eventdispatcher().observe_event(
                observer_name=f"camera_audit_{index}",
                event_name=omni.hydratexture.GLOBAL_EVENT_DRAWABLE_CHANGED,
                on_event=lambda event, key=str(index): drawables.__setitem__(
                    key, drawables[key] + 1
                ),
                filter=texture.get_event_key(),
            )
        )

    for flag in ("demo_display_toggle_smoke", "demo_backdrop_toggle_smoke", "demo_recenter_smoke"):
        setattr(args, flag, False)

    def timed(obj, method, name):
        if isinstance(obj, str):
            from isaaclab.utils.string import string_to_callable

            obj = string_to_callable(obj)
        original = getattr(obj, method)

        def call(*a, **kw):
            started = time.perf_counter_ns()
            if name == "fabric_forward":
                counts["forward"] += 1
            try:
                return original(*a, **kw)
            finally:
                logger = getattr(env, "performance_logger", None)
                if logger is not None:
                    logger.add_nested(name, time.perf_counter_ns() - started)

        setattr(obj, method, call)

    timed(env.sim.physics_manager, "step", "native_physics_integration")
    timed(env.sim.physics_manager, "forward", "fabric_forward")
    timed(env.sim, "render", "render_app")
    for visualizer in env.sim.visualizers:
        timed(visualizer, "step", "kit_visualizer_app_pump")
    for camera in owners:
        timed(camera, "update", "camera_extraction")
    if rig.capture is not None:
        timed(rig.capture, "_check_current", "camera_binding_validation")
    original_step = env.sim.step
    flags = []
    pending = [False]

    def step(*a, **kw):
        render = kw.get("render", True)
        if (
            candidate in ("t1", "t2", "t6-sync-explicit", "t6-double-render", "t6-prime-extraction")
            and render
        ):
            kw["render"] = False
            pending[0] = True
        flags.append(kw.get("render", True))
        return original_step(*a, **kw)

    env.sim.step = step
    original_boundary = rig.capture_boundary

    def boundary(current_env):
        if pending[0]:
            pending[0] = False
            before = env.sim.get_physics_step_count(), counts["native_physics"]
            validation_started = time.perf_counter_ns()
            state_before = env.capture_measured_state()
            validation_elapsed = time.perf_counter_ns() - validation_started
            if candidate == "t2":
                import omni.replicator.core as rep

                rep.orchestrator.set_capture_on_play(False)
                settings.set("/exts/omni.replicator.core/Orchestrator/enabled", True)
                env.sim.forward()
                previous = settings.get("/app/player/playSimulations")
                settings.set_bool("/app/player/playSimulations", False)
                started = time.perf_counter_ns()
                try:
                    rep.orchestrator.step(
                        delta_time=0.0, pause_timeline=False, rt_subframes=1, wait_for_render=True
                    )
                finally:
                    settings.set("/app/player/playSimulations", previous)
                logger = getattr(env, "performance_logger", None)
                if logger is not None:
                    logger.add_nested("replicator_barrier", time.perf_counter_ns() - started)
            else:
                env.sim.render()
                if candidate == "t6-prime-extraction":
                    for camera in owners:
                        camera.update(0.0, force_recompute=True)
                if candidate in ("t6-double-render", "t6-prime-extraction"):
                    env.sim.render()
            assert before == (env.sim.get_physics_step_count(), counts["native_physics"])
            validation_started = time.perf_counter_ns()
            assert state_before == env.capture_measured_state(), "Render changed native state"
            logger = getattr(env, "performance_logger", None)
            if logger is not None:
                logger.add_nested(
                    "barrier_state_invariance_check",
                    validation_elapsed + time.perf_counter_ns() - validation_started,
                )

        def sync_if_selected():
            if candidate == "t6-cuda-barrier":
                import torch

                started = time.perf_counter_ns()
                torch.cuda.synchronize(env.sim.device)
                logger = getattr(env, "performance_logger", None)
                if logger is not None:
                    logger.add_nested("diagnostic_cuda_barrier", time.perf_counter_ns() - started)

        if candidate == "t6-double-extract":
            for camera in owners:
                camera.update(0.0, force_recompute=True)
        if probe_count or rig.live_rgb_enabled:
            result = original_boundary(current_env)
            sync_if_selected()
            return result
        if level < 2:
            return None
        # Leave the recorder's state-only source profile and lifecycle unchanged.
        capture = rig.capture.capture(1.0 / 30.0, eligible=True)
        if capture is None:
            raise RuntimeError(rig.capture.last_error)
        sync_if_selected()
        if level >= 3:
            owned = {}
            if hasattr(rig.capture, "_buffers"):
                buffers = rig.capture._buffers
            else:
                buffers = {
                    r: rig.capture._buffer[i : i + 1] for r, i in rig.capture._indices.items()
                }
            for role, buffer in buffers.items():
                started = time.perf_counter_ns()
                rgb = tensor(buffer)[0, ..., :3].detach().cpu().numpy()
                env.performance_logger.add_nested(
                    "rgb_device_to_host", time.perf_counter_ns() - started
                )
                started = time.perf_counter_ns()
                owned[role] = rgb.copy()
                env.performance_logger.add_nested(
                    "rgb_numpy_copy", time.perf_counter_ns() - started
                )
            rig.capture.latest()
            if level == 4:
                import numpy as np

                started = time.perf_counter_ns()
                np.savez_compressed(out / "rgb" / f"{capture.capture_cycle:06d}.npz", **owned)
                env.performance_logger.add_nested(
                    "rgb_persistence", time.perf_counter_ns() - started
                )
        return capture

    rig.capture_boundary = boundary
    if not probe_count and level:
        import tools.isaac_vr_camera_rendering as suspension

        # C1 retains annotators/AOV production but makes no intentional get_data call.
        suspension.suspend_dataset_camera_rendering = lambda *a, **kw: None
    if level == 4:
        (out / "rgb").mkdir()
    gpu_stats = None
    if os.environ.get("CAMERA_AUDIT_GPU_SCOPES") == "1":
        omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate(
            "omni.hydra.engine.stats", True
        )
        import omni.hydra.engine.stats

        settings.set("/profiler/enabled", True)
        gpu_stats = omni.hydra.engine.stats.HydraEngineStats()
    stream = (out / "mechanisms.jsonl").open("w")
    previous_end = S2PerformanceLogger.end_step
    previous_counts = dict(counts)
    previous_drawables = dict(drawables)
    previous_physics = [env.sim.get_physics_step_count()]
    previous_render = [env.sim.render_generation]

    xr_cost_started = False
    previous_cpu = time.process_time_ns()
    previous_wall = time.perf_counter_ns()

    def end(logger, number, **state):
        nonlocal previous_counts, previous_drawables, xr_cost_started, previous_cpu, previous_wall
        observer_started = time.perf_counter_ns()
        result = previous_end(logger, number, **state)
        cpu, wall = time.process_time_ns(), time.perf_counter_ns()
        io = {
            key: int(value)
            for key, value in (
                line.split(":") for line in Path("/proc/self/io").read_text().splitlines()
            )
        }
        row = {
            "tick": number,
            "physics": env.sim.get_physics_step_count(),
            "physics_delta": env.sim.get_physics_step_count() - previous_physics[0],
            "render_generation": env.sim.render_generation,
            "render_delta": env.sim.render_generation - previous_render[0],
            "counts": {k: counts[k] - previous_counts[k] for k in counts},
            "drawables": {k: drawables[k] - previous_drawables[k] for k in drawables},
            "render_flags": list(flags),
            "panels_bound": env.vr_runtime._feed_bound,
            "resources": {
                "process_cpu_percent": 100 * (cpu - previous_cpu) / (wall - previous_wall),
                "rss_bytes": int(Path("/proc/self/statm").read_text().split()[1])
                * os.sysconf("SC_PAGE_SIZE"),
                "disk_read_bytes_cumulative": io["read_bytes"],
                "disk_write_bytes_cumulative": io["write_bytes"],
            },
            "products": {
                r: str(getattr(c, "owner", c)._render_data.render_product.path)
                for r, c in cameras.items()
            },
            "products_enabled": [
                bool(c._render_data.render_product.hydra_texture.updates_enabled) for c in owners
            ],
            "cameras": [
                {
                    "role": r,
                    "frame": next(
                        (
                            v.frame
                            for v in getattr(getattr(rig.capture, "_latest", None), "cameras", ())
                            if v.role == r
                        ),
                        "UNMEASURED: no extraction",
                    ),
                    "data_generation": c._data_generation,
                }
                for r, c in cameras.items()
            ],
        }
        if gpu_stats is not None:
            row["gpu_scopes"] = gpu_stats.get_gpu_profiler_result()
        row["observer_before_write_ms"] = (time.perf_counter_ns() - observer_started) / 1e6
        stream.write(json.dumps(row, default=str) + "\n")
        stream.flush()
        previous_counts, previous_drawables = dict(counts), dict(drawables)
        previous_physics[0], previous_render[0] = row["physics"], row["render_generation"]
        flags.clear()
        previous_cpu, previous_wall = cpu, wall
        if number == args.s2_max_control_steps and not xr_cost_started:
            if os.environ.get("CAMERA_AUDIT_XR_COST") == "1":
                xr_cost_started = True
                from xr_cost import run as run_cost

                run_cost(env, args, out)
            if probe_count:
                from audit_oracle import run

                run(env, out, probe_count, counts, drawables)
            (out / "settings-after.json").write_text(json.dumps(effective(), indent=2))
        return result

    def run_probe():
        from audit_oracle import run

        run(env, out, probe_count, counts, drawables)
        (out / "settings-after.json").write_text(json.dumps(effective(), indent=2))

    env._camera_audit_run_probe = run_probe
    S2PerformanceLogger.end_step = end
    # Retain subscriptions for the process; no global GPU/frame-info polling.
    env._camera_audit_subscriptions = subscriptions
