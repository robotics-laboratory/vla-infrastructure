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

    def timed(obj, method, name):
        original = getattr(obj, method)

        def call(*a, **kw):
            started = time.perf_counter_ns()
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
        if candidate in ("t1", "t2", "t6-sync-explicit") and render:
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
            state_before = env.capture_measured_state()
            if candidate == "t2":
                import omni.replicator.core as rep

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
            assert before == (env.sim.get_physics_step_count(), counts["native_physics"])
            assert state_before == env.capture_measured_state(), "Render changed native state"
        if probe_count:
            return original_boundary(current_env)
        if level < 2:
            return None
        # Leave the recorder's state-only source profile and lifecycle unchanged.
        capture = rig.capture.capture(1.0 / 30.0, eligible=True)
        if capture is None:
            raise RuntimeError(rig.capture.last_error)
        if level >= 3:
            owned = {}
            for role, buffer in rig.capture._buffers.items():
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
    stream = (out / "mechanisms.jsonl").open("w")
    previous_end = S2PerformanceLogger.end_step
    previous_counts = dict(counts)
    previous_drawables = dict(drawables)
    previous_physics = [env.sim.get_physics_step_count()]
    previous_render = [env.sim.render_generation]

    def end(logger, number, **state):
        nonlocal previous_counts, previous_drawables
        result = previous_end(logger, number, **state)
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
                    "frame": tensor(c.frame).tolist(),
                    "data_generation": c._data_generation,
                }
                for r, c in cameras.items()
            ],
        }
        stream.write(json.dumps(row) + "\n")
        stream.flush()
        previous_counts, previous_drawables = dict(counts), dict(drawables)
        previous_physics[0], previous_render[0] = row["physics"], row["render_generation"]
        flags.clear()
        if number == args.s2_max_control_steps:
            if probe_count:
                from audit_oracle import run

                run(env, out, probe_count, counts, drawables)
            (out / "settings-after.json").write_text(json.dumps(effective(), indent=2))
        return result

    S2PerformanceLogger.end_step = end
    # Retain subscriptions for the process; no global GPU/frame-info polling.
    env._camera_audit_subscriptions = subscriptions
