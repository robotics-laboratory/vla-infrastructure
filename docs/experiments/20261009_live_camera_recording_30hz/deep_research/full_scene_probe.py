"""Compose the current Piper builder/causal recorder with optional native media.

No physical devices or teleop input. Synthetic joint targets; optional upstream
IK is measured as an additional workload, not used as training-label replacement.
All outputs are diagnostic and dataset_admissible=False.
"""

# ruff: noqa: E402
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
p = argparse.ArgumentParser()
p.add_argument("--output", type=Path, required=True)
p.add_argument("--frames", type=int, default=300)
p.add_argument("--warmup", type=int, default=60)
p.add_argument("--media", choices=("none", "poll", "writer", "atlas", "mirror"), default="poll")
p.add_argument("--physics-variant", default="baseline")
p.add_argument("--render-mode", choices=("original", "minimal"), default="minimal")
p.add_argument("--async-render", action="store_true")
p.add_argument("--wait-idle", choices=("original", "true", "false"), default="original")
p.add_argument("--texture-streaming-off", action="store_true")
p.add_argument("--xr", action="store_true")
p.add_argument("--device", default="cuda:0")
p.add_argument("--ik-workload", action="store_true")
p.add_argument("--witness", action="store_true")
p.add_argument("--profile", action="store_true")
p.add_argument("--fabric-boundary", action="store_true")
p.add_argument("--torch-threads", type=int, default=0)
args = p.parse_args()
args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
args.output.chmod(0o700)
receipt = {
    "dataset_admissible": False,
    "quest_connected": False,
    "source": "deterministic_injected_xr_v1",
    "synthetic_joint_targets": True,
    "camera_source_alignment_proven": False,
    "arguments": vars(args).copy(),
    "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "base": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "passed": False,
}
receipt["arguments"]["output"] = str(args.output)
ns = None


def benchmark(env, cli, app, **unused):
    import carb.settings
    import omni.replicator.core as rep
    import yaml
    from isaac_vr_recording import start_live_recording
    from isaac_vr_recording_smoke import recording_session_metadata
    from isaac_vr_injected_recording import record_injected_transitions, _command
    from isaac_s2_performance import S2PerformanceLogger

    if args.torch_threads:
        import torch

        receipt["torch_threads_before"] = torch.get_num_threads()
        torch.set_num_threads(args.torch_threads)
    physics = importlib.util.spec_from_file_location("deep_physics", HERE / "physics_probe.py")
    adapter = importlib.util.module_from_spec(physics)
    physics.loader.exec_module(adapter)
    adapter.MANIFEST = HERE / "physics_preimages.json"
    handle = adapter.install(env, variant=args.physics_variant)
    fabric_restore = None
    if args.fabric_boundary:
        from fabric_boundary import install

        receipt["fabric_boundary"], fabric_restore = install(env)
    perf = S2PerformanceLogger(
        args.output / "performance.jsonl", window_steps=60, warmup_steps=args.warmup, target_hz=50
    )
    env.performance_logger = perf
    settings = carb.settings.get_settings()
    receipt["settings"] = {
        k: settings.get(k)
        for k in (
            "/app/asyncRendering",
            "/app/asyncRenderingLowLatency",
            "/app/omni.usd/asyncHandshake",
            "/omni/replicator/asyncRendering",
            "/app/hydraEngine/waitIdle",
            "/rtx/rendermode",
            "/rtx-transient/resourcemanager/enableTextureStreaming",
        )
    }
    if args.xr:
        from omni.kit.xr.core import XRCore

        receipt["xr_status"] = {
            "enabled": XRCore.get_singleton().is_xr_enabled(),
            "active_profile": settings.get("/persistent/xr/activeProfile"),
            "client_connected": False,
            "live_device_input_pumped": False,
        }
    cfg = yaml.safe_load(cli.config.read_text())
    record = None
    clock = observer = None
    writer = atlas = mirror = None
    streams, annotators, products, rows = [], [], [], []
    counts, empty = [0, 0, 0], [0, 0, 0]
    try:
        if args.witness and args.media != "mirror":
            from kit_witness_probe import KitWitness

            clock = KitWitness(env.sim.stage, env.camera.camera_prim_paths.values())
        record = start_live_recording(
            args.output / "episode",
            env,
            session_metadata=recording_session_metadata(
                config_path=cli.config,
                environment_pins=cfg["environment"],
                run_id=args.output.name,
                session_id=args.output.name,
                episode_id="episode_000000",
                execution_profile="isaac_vr_record_injected_no_client_audit",
                processor_revision="piper_x_isaac_s2_bimanual_relative_v3",
            ),
            portable_roots={
                "recording": args.output / "episode",
                "isaac61_production": Path("/data/vla-infrastructure/isaac61_production"),
                "project_assets": Path("/data/vla-infrastructure/assets"),
                "runtime_assets": state / "assets",
            },
        )
        if args.media == "mirror":
            from live_mirror import LiveMirror

            mirror = LiveMirror(record, args.output / "mirror", witness=True)
        if args.media == "atlas":
            from atlas_media import AtlasMedia

            atlas = AtlasMedia(
                env, args.output, warmup=args.warmup, helper_path=HERE / "tiled_probe.py"
            )
        for index, camera in enumerate(env.camera.camera_prim_paths.values()):
            if args.media in ("none", "atlas", "mirror"):
                break
            product = rep.create.render_product(camera, (960, 600))
            products.append(product)
            if args.media == "poll":
                annotator = rep.AnnotatorRegistry.get_annotator(
                    "LdrColor", device="cpu", init_params={"compression": "h264"}
                )
                annotator.attach(product)
                annotators.append(annotator)
                streams.append((args.output / f"view_{index}.h264").open("xb"))
        if args.media == "writer":
            spec = importlib.util.spec_from_file_location(
                "packet_writer", HERE.parent / "native_packet_writer.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            writer = module.NativePacketWriter(
                dict(
                    zip(
                        ("left_wrist", "right_wrist", "scene"),
                        [product.path for product in products],
                        strict=True,
                    )
                ),
                args.output / "writer",
            )
            writer.attach_existing()
        original_advance = env._advance
        tick = 0

        def advance(repeat):
            nonlocal tick
            if clock:
                clock.set_row(tick)
            before = env.sim.get_physics_step_count()
            original_advance(repeat)
            if repeat != 4:
                raise RuntimeError("Unexpected control span")
            if env.sim.get_physics_step_count() - before != 4:
                raise RuntimeError("Control did not advance four physics steps")
            tick += 1
            sizes = []
            for index, annotator in enumerate(annotators):
                value = annotator.get_data(do_array_copy=True)
                if value is None or not value.size:
                    empty[index] += 1
                    if tick > args.warmup:
                        raise RuntimeError(f"Empty packet tick{tick} view{index}")
                    sizes.append(0)
                    continue
                data = value.tobytes()
                streams[index].write(data)
                counts[index] += 1
                sizes.append(len(data))
            if writer:
                writer.check()
            if atlas:
                rows.append(atlas.after(tick))
                return
            rows.append(
                {
                    "control_tick": tick,
                    "source_state_after_physics": env.sim.get_physics_step_count(),
                    "packet_bytes": sizes,
                    "renderer_source_generation": None,
                }
            )

        env._advance = advance
        ik = None
        if args.ik_workload:
            from isaac_s2_runtime import _BimanualDifferentialIk

            ik = _BimanualDifferentialIk(env)
        if args.profile:
            from profiler_probe import install

            observer = install(env, perf, warmup=args.warmup, frames=args.frames, ik=ik)

        def pre_step():
            if ik:
                ik.solve(_command((0.05, 0.05)))

        start = time.perf_counter()
        transitions = record_injected_transitions(
            record,
            env,
            count=args.warmup + args.frames,
            performance_logger=perf,
            require_distinct_actions=False,
            fixed_input=True,
            pre_step_callback=pre_step,
        )
        working_end = time.perf_counter()
        summary = perf.close()
        for stream in streams:
            stream.flush()
            os.fsync(stream.fileno())
        if mirror:
            receipt["mirror"] = mirror.finish()
        if atlas:
            receipt["atlas"] = atlas.finish()
            counts, empty = atlas.counts, atlas.empty
        record.close(outcome="operator_stopped", reason="research_diagnostic_only")
        record = None
        receipt.update(
            passed=True,
            transitions={k: v for k, v in transitions.items() if k != "actions"},
            performance=summary,
            packet_counts=counts,
            empty_packets=empty,
            whole_working_s=working_end - start,
            drain_s=time.perf_counter() - working_end,
            physics_ablation=handle.receipt(),
        )
        if writer:
            receipt["writer_complete_rows"] = writer.complete_rows
            receipt["writer_callbacks"] = writer.callbacks
            if writer.complete_rows < args.frames:
                raise RuntimeError("Writer dispatch delivered insufficient packet rows")
        return 0
    finally:
        if observer:
            receipt["profiler"] = observer.receipt()
            observer.restore()
        receipt["physics_ablation"] = handle.receipt()
        if fabric_restore:
            fabric_restore()
        handle.restore()
        if mirror:
            mirror.abort()
        if atlas:
            atlas.close()
        if writer:
            writer.detach()
        for annotator, product in zip(annotators, products):
            annotator.detach(product)
        for stream in streams:
            stream.close()
        if clock:
            clock.close()
        if record is not None:
            record.close(outcome="failure", reason="research_probe_failed")
        if not perf._closed:
            receipt["partial_performance"] = perf.close()
        (args.output / "packets.json").write_text(json.dumps(rows, indent=2) + "\n")


try:
    from isaac_demo_launch import (
        verify_stack,
        user_environment,
        write_runtime_config,
        configure_cloudxr,
    )

    stack = verify_stack("isaac61")
    environment, state = user_environment(stack, "isaac61")
    os.environ.update(environment)
    config = write_runtime_config(ROOT, stack, state, args.output)
    kit = [
        "--portable-root",
        str(state / "kit"),
        "--enable",
        "isaacsim.replicator.episode_recorder",
    ]
    if args.profile:
        kit += ["--/app/profilerBackend=nvtx", "--/app/profileFromStart=true"]
    if args.xr:
        kit += ["--enable", "omni.kit.scene_view.xr", "--enable", "omni.kit.scene_view.xr_utils"]
    if args.async_render:
        for key in (
            "/app/asyncRendering",
            "/app/asyncRenderingLowLatency",
            "/app/omni.usd/asyncHandshake",
            "/omni/replicator/asyncRendering",
        ):
            kit += [f"--{key}=true"]
    if args.texture_streaming_off:
        kit += ["--/rtx-transient/resourcemanager/enableTextureStreaming=false"]
    sys.argv = [
        str(ROOT / "tools/run_isaac_s1.py"),
        "--config",
        str(config),
        "--device",
        args.device,
        "--vr-runtime",
        "--s2-record",
        "--viz",
        "kit",
        "--kit_args",
        shlex.join(kit),
    ]
    if args.xr:
        os.environ["VLA_CLOUDXR_INSTALL_DIR"] = str(state / "cloudxr")
        configure_cloudxr(os.environ, mode="auto", dry_run=False)
        sys.argv += ["--xr"]
    receipt["base_command"] = list(sys.argv)
    ns = runpy.run_path(str(ROOT / "tools/run_isaac_s1.py"), run_name="deep_shared_base")
    if args.xr:
        from isaaclab_teleop.isaac_teleop_device import _enable_teleop_bridge

        _enable_teleop_bridge()
        from omni.kit.xr.core import XRCore

        XRCore.get_singleton().request_enable_profile("ar")
    import carb.settings

    settings = carb.settings.get_settings()
    if args.render_mode == "minimal":
        settings.set("/rtx/rendermode", "MinimalRendering")
        settings.set("/rtx/minimal/mode", 2)
    if args.wait_idle != "original":
        settings.set("/app/hydraEngine/waitIdle", args.wait_idle == "true")
    import isaac_s2_runtime

    isaac_s2_runtime.run_s2 = benchmark
    ns["main"]()
except BaseException:
    receipt["passed"] = False
    receipt["error"] = traceback.format_exc()
    print(receipt["error"], flush=True)
finally:
    receipt["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (args.output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")
    if ns:
        owned = ns.get("owned_cloudxr")
        if owned is not None:
            from omni.kit.xr.core import XRCore

            xr = XRCore.get_singleton()
            xr.request_disable_profile()
            for _ in range(120):
                ns["simulation_app"].update()
                if not xr.is_xr_enabled():
                    break
            else:
                raise RuntimeError("Experiment XR did not stop; owned server retained")
            owned.stop()
        ns["simulation_app"].close()
raise SystemExit(0 if receipt["passed"] else 1)
