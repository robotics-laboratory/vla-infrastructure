"""Reproducible opt-in single4090 live-camera recording diagnostic.

Builds the current shared VR scene and canonical recorder, solves real upstream
DLS decisions against the selected native or standalone physics source. GPU media
uses either the earlier render mirror or experimental main Kit camera products.
Main Kit mode also shares completed frames with SceneUI preview. No robot I/O.
"""

# ruff: noqa: E402
import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "docs/experiments/20261009_live_camera_recording_30hz/deep_research"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(ROOT / "tools"))
p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--output", type=Path, required=True)
p.add_argument("--frames", type=int, default=600)
p.add_argument("--warmup", type=int, default=60)
p.add_argument("--media-warmup", type=int, default=20)
p.add_argument("--media", choices=("none", "gpu", "kit"), default="gpu")
p.add_argument("--physics-source", choices=("standalone", "native"), default="standalone")
p.add_argument("--kit-capture", choices=("pump", "orchestrator", "callback"), default="pump")
p.add_argument("--kit-preview", action=argparse.BooleanOptionalAction, default=True)
p.add_argument("--kit-annotator", choices=("rgb", "LdrColor"), default="rgb")
p.add_argument("--kit-fast", action="store_true")
p.add_argument("--kit-legacy-products", action="store_true", help="Experimental per-camera legacy RTX mode in session layer; keep XR RT2")
p.add_argument("--kit-no-temporal-lighting", action="store_true",
               help="Diagnostic native-RP lighting denoiser ablation; noisier images")
p.add_argument("--kit-rendering", choices=("default", "sync-throughput", "async", "async-latency"),
               default="default", help="Scoped renderer scheduling ablation, after fast settings")
p.add_argument("--kit-viewport", action=argparse.BooleanOptionalAction, default=True,
               help="Diagnostic desktop viewport updates; disabling is not Quest qualification")
p.add_argument("--native-profile", action="store_true", help="Read-only nested stage timing")
p.add_argument("--native-profile-cprofile", action=argparse.BooleanOptionalAction, default=True)
p.add_argument("--native-nsys", action="store_true", help="CUDA profiler capture range + NVTX timings")
p.add_argument("--disable-kit-memorytracking", action="store_true",
               help="Fresh-process diagnostic: disable Kit allocation tracing to probe CUPTI ownership")
p.add_argument("--native-copy-early-subscribe", action="store_true",
               help="Own public CUPTI subscription before Kit startup; requires explicit cuda-event shim")
p.add_argument("--kit-preview-transport", choices=("cuda", "cpu-retained", "cuda-retained", "cuda-event"), default="cuda",
               help="Preview copy lifetime: conservative CUDA fence, retained probes, or bounded copy events")
p.add_argument("--native-source-proof", action="store_true", help="Compare actual rendered body/camera transforms")
p.add_argument("--native-proof-compact", action="store_true", help="Compact diagnostic logs; preserve full geometry checks")
p.add_argument("--native-proof-batch-reads", action="store_true", help="One public DLPack batched native-state host transfer; preserve full geometry checks")
p.add_argument("--native-proof-skip-sync", action="store_true", help="Ablate added per-tick USD/Fabric sync; initial sync and all geometry checks remain")
p.add_argument("--native-proof-clock-only", action="store_true", help="Exact publication stamp and native camera proof; full body comparison remains a separate diagnostic")
p.add_argument("--native-attribute-probe", action="store_true", help="Validate stock at-render FabricReader attribute against semantic publication stamp")
p.add_argument("--native-attribute-only", action="store_true", help="Use native rendered publication attribute and camera matrices; requires clock-only source proof and attribute probe")
p.add_argument("--native-identity-only", action="store_true", help="Exact rendered publication identity; geometry checks run separately; requires attribute-only")
p.add_argument("--native-cache-helpers", action="store_true", help="Reuse public graph port accessors while reading fresh values each callback")
p.add_argument("--native-bind-sources", action="store_true",
               help="Live HDF map of encoded frame ordinals to exact past canonical observations; requires source proof")
p.add_argument("--native-managed-probe", action="store_true", help="Bounded native Hydra managed-resource/event diagnostic")
p.add_argument("--native-optical-proof", action="store_true", help="Diagnostic publication optical meshes; requires source proof, no old witness")
p.add_argument("--xr", action="store_true")
p.add_argument("--runtime-device", choices=("cpu", "cuda:0"), default="cpu",
               help="Native PhysX/control device; camera rendering and NVENC use GPU in both profiles")
p.add_argument("--view-mode", choices=("original", "minimal"), default="original")
p.add_argument("--motion", choices=("benchmark", "reach-demo"), default="benchmark")
p.add_argument("--witness", action=argparse.BooleanOptionalAction, default=True)
p.add_argument("--witness-depth-scale", type=float, choices=(0.5, 1.0), default=1.0)
p.add_argument("--pace-hz", type=float, choices=(0.0, 30.0), default=0.0,
               help="Diagnostic wall-clock pacing; zero measures maximum throughput")
p.add_argument("--audit-host-events", action="store_true",
               help="Retain read-only monotonic capture, apply, step and commit events")
p.add_argument("--mesh-freshness", action="store_true",
               help="Diagnostic moving Mesh marker; changes derived rendering only")
p.add_argument("--source-queue-capacity", type=int, choices=(1, 8), default=8,
               help="Pending renderer snapshots; NVENC owners remain independently bounded at8")
p.add_argument(
    "--physics-python",
    type=Path,
    default=Path("/data/ebulochkin/vla-runtime/live30-deep-20261009/optional-ovphysx/bin/python"),
)
args = p.parse_args()
if args.frames < 2 or args.warmup < 0:
    p.error("frames must be>=2 and warmup>=0")
if args.native_attribute_only and not (
        args.native_source_proof and args.native_proof_clock_only and args.native_attribute_probe):
    p.error("attribute-only requires source proof, clock-only coverage and native attribute probe")
if args.native_identity_only and not args.native_attribute_only:
    p.error("identity-only requires native attribute-only mode")
args.output.mkdir(parents=True, exist_ok=False, mode=0o700)
receipt = dict(
    schema="single_gpu_live_recording_diagnostic_v1",
    passed=False,
    dataset_admissible=False,
    physical=False,
    quest_connected=False,
    input_source="deterministic_injected_xr_v1",
    upstream_dls_used_for_actuation=True,
    arguments={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
    started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    sources={
        str(f): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in [Path(__file__), *(ROOT / "tools").glob("isaac_vr_standalone*.py")]
    },
)
ns = None
owned_native_media = []
prepared_proof_layers = []
proof_reset_restore = None
native_copy_library = None  # Keep our subscriber/DSO alive through Kit shutdown.


def benchmark(env, cli, app, **unused):
    import numpy as np
    import torch
    import yaml
    from isaac_s2_performance import S2PerformanceLogger
    from isaac_s2_runtime import _BimanualDifferentialIk
    from isaac_vr_injected_recording import record_injected_transitions
    from isaac_vr_recording import start_live_recording
    from isaac_vr_recording_smoke import recording_session_metadata
    from isaac_vr_standalone import StandaloneState
    from live_mirror import LiveMirror, ROLES, sha

    torch.set_num_threads(1)
    perf = S2PerformanceLogger(
        args.output / "performance.jsonl", window_steps=60, warmup_steps=args.warmup,
        target_hz=args.pace_hz or 50,
    )
    cfg = yaml.safe_load(cli.config.read_text())
    owner = record = mirror = native_media = profiler = None
    host_events, restores = [], []

    def observe(target, name, *, token_argument=False):
        previous = getattr(target, name)
        owned = name in vars(target)

        def call(*values, **keywords):
            begin = time.monotonic_ns()
            result = previous(*values, **keywords)
            end = time.monotonic_ns()
            token = values[0] if token_argument else result
            row = dict(event=name, begin_monotonic_ns=begin, end_monotonic_ns=end,
                       physics_step_after=env.sim.get_physics_step_count())
            if hasattr(token, "capture_sequence"):
                row.update(source_id=token.capture_sequence,
                           source_physics_step=token.physics_step)
            if name == "commit_transition":
                row["successor_source_id"] = values[1].capture_sequence
            host_events.append(row)
            return result

        setattr(target, name, call)
        restores.append((target, name, previous, owned))
    try:
        if args.physics_source == "standalone":
            owner = StandaloneState(env, args.output / "physics", python=args.physics_python)
        metadata = recording_session_metadata(
            config_path=cli.config,
            environment_pins=cfg["environment"],
            run_id="single_gpu_" + hashlib.sha256(str(args.output.resolve()).encode()).hexdigest()[:24],
            session_id="single_gpu_" + hashlib.sha256(str(args.output.resolve()).encode()).hexdigest()[:24],
            episode_id="single_gpu_episode",
            execution_profile="isaac_vr_record_injected_no_client_audit",
            processor_revision="piper_x_isaac_s2_bimanual_relative_v3",
        )
        record = start_live_recording(
            args.output / "episode",
            env,
            session_metadata=metadata,
            portable_roots={
                "recording": args.output,
                "isaac61_production": Path(cfg["environment"]["materialized_path"]).parent,
                "project_assets": Path(cfg["asset"]["source_checkout"]).parent,
                "runtime_assets": state / "assets",
            },
            standalone_state=owner,
        )
        if owner:
            owner.start(record.snapshot)
        if args.media == "kit":
            from isaac_vr_native_media import NativeKitMedia

            native_media = NativeKitMedia(record, env, args.output / "native-camera",
                                          capture=args.kit_capture, preview=args.kit_preview,
                                          witness=args.witness, annotator_name=args.kit_annotator,
                                          fast=args.kit_fast, rendering=args.kit_rendering,
                                          viewport=args.kit_viewport,
                                          preview_transport=args.kit_preview_transport,
                                          max_publications=args.warmup + args.frames + 1,
                                          source_proof=args.native_source_proof, optical_proof=args.native_optical_proof,
                                          managed_probe=args.native_managed_probe,
                                          prepared_source_layer=prepared_proof_layers[0][1] if prepared_proof_layers else None,
                                          no_temporal_lighting=args.kit_no_temporal_lighting,
                                          bind_sources=args.native_bind_sources,
                                          proof_compact=args.native_proof_compact,
                                          legacy_products=args.kit_legacy_products,
                                          proof_batch_reads=args.native_proof_batch_reads,
                                          proof_skip_sync=args.native_proof_skip_sync,
                                          proof_clock_only=args.native_proof_clock_only,
                                          attribute_probe=args.native_attribute_probe,
                                          attribute_only=args.native_attribute_only,
                                          identity_only=args.native_identity_only,
                                          cache_helpers=args.native_cache_helpers)
            from carb.settings import get_settings
            physics_prim = env.sim.stage.GetPrimAtPath(env.sim.cfg.physics_prim_path)
            receipt["resolved_physics_device"] = dict(
                simulation_device=str(env.sim.device),
                physics_prim_path=env.sim.cfg.physics_prim_path,
                scene_attributes={name: physics_prim.GetAttribute(name).Get() for name in (
                    "physxScene:enableGPUDynamics", "physxScene:broadphaseType",
                    "physxScene:solverType", "physxScene:enableCCD")},
                physics_settings={name: get_settings().get(name) for name in (
                    "/physics/cudaDevice", "/physics/suppressReadback")},
            )
            if native_media.source_proof:
                view = native_media.source_proof.views[0]
                receipt["resolved_physics_device"]["native_dof_array_device"] = str(view.get_dof_positions().device)
                receipt["resolved_physics_device"]["native_link_pose_array_device"] = str(view.get_link_transforms().device)
            owned_native_media.append(native_media)
        if args.audit_host_events:
            observe(env, "_apply")
            observe(env, "_advance")
            observe(record, "capture_observation")
            observe(record, "capture_successor")
            observe(record, "commit_transition", token_argument=True)

            def append_event(name, duration_ns):
                end = time.monotonic_ns()
                host_events.append(dict(event=name, begin_monotonic_ns=end-duration_ns,
                                        end_monotonic_ns=end,
                                        timing_semantics="existing duration; end at observer invocation",
                                        physics_step_after=env.sim.get_physics_step_count()))
                if previous_timing_observer is not None:
                    previous_timing_observer(name, duration_ns)

            previous_timing_observer = record._timing_observer
            record._timing_observer = append_event
            restores.append((record, "_timing_observer", previous_timing_observer, True))
        if args.xr:
            from omni.kit.xr.core import XRCore

            receipt["xr_enabled_at_admission"] = XRCore.get_singleton().is_xr_enabled()
        ik = _BimanualDifferentialIk(env)
        motion_rows = []
        def tcp_positions():
            if owner:
                return owner.snapshot["rigid_body_world_pose"][[8, 20], :3].copy()
            return np.stack([
                ik._state(arm, robot, wrist, ids)["tcp_pose_w"][0, :3].detach().cpu().numpy()
                for arm, (robot, wrist, ids) in enumerate(zip(
                    env.robots, env.wrist_ids, env.joint_ids, strict=True))
            ])

        home = tcp_positions()
        # World Cartesian intent only: existing upstream DLS and native physics
        # still own targets, joint limits, articulation motion and contacts.
        # This is an approach/transfer gesture, with no claimed cube grasp.
        waypoints = np.array(
            [
                [0, 0, 0, 0, 0.05],
                [2, 0, 0, 0, 0.09],
                [6, -0.14, 0.028, 0, 0.09],
                [9, -0.14, 0.028, -0.05, 0.09],
                [11, -0.14, 0.028, -0.05, 0.015],
                [15, -0.14, 0.028, 0.07, 0.015],
                [19, 0.04, 0.028, 0.07, 0.015],
                [21, 0.04, 0.028, 0.07, 0.09],
                [26, 0, 0, 0, 0.05],
                [28, 0, 0, 0, 0.05],
            ]
        )
        if args.motion == "reach-demo":
            (args.output / "motion-plan.json").write_text(
                json.dumps(
                    dict(
                        schema="bimanual_cartesian_reach_demo_v1",
                        home_tcp_world_m=home.tolist(),
                        waypoint_columns=["time_s", "dx_m", "outward_dy_m", "dz_m", "aperture_m"],
                        waypoints=waypoints.tolist(),
                        warmup_hold_steps=args.warmup,
                        control_period_sim_s=1 / 30,
                        maximum_cartesian_delta_per_step_m=0.003,
                        orientation_delta_rad=[0, 0, 0],
                        task="open, approach above cubes, lower, close, lift, reach toward plates, open, return",
                        object_grasp_claimed=False,
                    ),
                    indent=2,
                )
                + "\n"
            )
        if args.media == "gpu":
            if owner is None:
                raise ValueError("Mirror comparison requires standalone source; use --media kit for native physics")
            guard = args.output / "mirror-source-preimages.json"
            protected = [
                ROOT / "tools/isaac_vr_recording.py",
                Path(__file__),
                HELPERS / "live_mirror.py",
                ROOT / "tools/isaac_vr_live_worker.py",
            ]
            guard.write_text(json.dumps({str(f): sha(f) for f in protected}, indent=2) + "\n")
            gpu_guard = args.output / "gpu-preimages.json"
            from isaac_vr_live_gpu import write_preimages

            write_preimages(gpu_guard)
            from ovrtx_live_probe import pose_matrices

            frames = record.sampler.capture_frame()
            matrices = []
            for r in record.recordables:
                e = r.to_manifest()
                if e["type"] not in ("articulation", "rigid_body", "camera"):
                    continue
                f = frames[e["group"]]
                plural = e["type"] == "articulation"
                m = pose_matrices(
                    f["positions" if plural else "position"],
                    f["orientations" if plural else "orientation"],
                )
                matrices.append(m if plural else m[None])
            initial = dict(
                matrix_bytes_hex=np.concatenate(matrices).astype("<f8").tobytes().hex(),
                intrinsics=[
                    [
                        float(frames["state/camera/" + role][k])
                        for k in ("focal_length", "horizontal_aperture", "vertical_aperture")
                    ]
                    for role in ROLES
                ],
                sim_time_s=owner.clock.physics_step / 120,
                reset_epoch=owner.clock.epoch,
                state_generation=owner.clock.physics_step,
                snapshot_id="warmup_only",
                snapshot_sha256="0" * 64,
            )
            mirror = LiveMirror(
                record,
                args.output / "mirror",
                witness=args.witness,
                worker=ROOT / "tools/isaac_vr_live_worker.py",
                guard_path=guard,
                source_clock=owner.clock,
                mesh_freshness=args.mesh_freshness,
                source_queue_capacity=args.source_queue_capacity,
                extra_seed={
                    "single_gpu": dict(
                        initial_payload=initial,
                        warmup_frames=args.media_warmup,
                        source_minimum_time=initial["sim_time_s"],
                        gpu_preimage_path=str(gpu_guard.resolve()),
                        witness_depth_scale=args.witness_depth_scale,
                    )
                },
            )

        def solve(command, observation, xr, tick):
            if args.motion == "reach-demo":
                sim_s = max(0, tick - 1 - args.warmup) / 30
                index = min(
                    np.searchsorted(waypoints[:, 0], sim_s, side="right") - 1, len(waypoints) - 2
                )
                first, last = waypoints[index : index + 2]
                fraction = np.clip((sim_s - first[0]) / (last[0] - first[0]), 0, 1)
                smooth = fraction * fraction * (3 - 2 * fraction)
                point = first + smooth * (last - first)
                target = home + point[1:4] * np.array([[1, 1, 1], [1, -1, 1]])
                actual = tcp_positions()
                error = target - actual
                delta = (
                    error
                    * np.minimum(1, 0.003 / np.maximum(np.linalg.norm(error, axis=1), 1e-12))[
                        :, None
                    ]
                )
                aperture = float(point[4])
                command = replace(
                    command,
                    left=replace(
                        command.left,
                        delta_pose=np.r_[delta[0], [0, 0, 0]],
                        gripper_aperture_m=aperture,
                    ),
                    right=replace(
                        command.right,
                        delta_pose=np.r_[delta[1], [0, 0, 0]],
                        gripper_aperture_m=aperture,
                    ),
                )
                motion_rows.append(
                    dict(
                        tick=tick,
                        motion_time_s=sim_s,
                        target_tcp_world_m=target.tolist(),
                        actual_tcp_world_m=actual.tolist(),
                        position_error_m=np.linalg.norm(error, axis=1).tolist(),
                        desired_aperture_m=aperture,
                        actual_aperture_m=(owner.snapshot["q"][:, 6].tolist() if owner else
                            [float(state) / 1000 for state in env.capture_measured_state()[1][6::7]]),
                    )
                )
                return ik.solve(command, observation, xr, tick)
            # Bounded periodic Cartesian intent, solved against the same O_t.
            phase = tick * 2 * np.pi / 120
            delta = np.array([0, 0.00015 * np.cos(phase), 0.0001 * np.sin(phase), 0, 0, 0])
            command = replace(
                command,
                left=replace(
                    command.left, delta_pose=delta, gripper_aperture_m=0.04 + 0.01 * np.sin(phase)
                ),
                right=replace(
                    command.right, delta_pose=-delta, gripper_aperture_m=0.04 - 0.01 * np.sin(phase)
                ),
            )
            return ik.solve(command, observation, xr, tick)

        if args.audit_host_events:
            original_solve = solve

            def solve(command, observation, xr, tick):
                begin = time.monotonic_ns()
                result = original_solve(command, observation, xr, tick)
                host_events.append(dict(event="decision_solve", tick=tick,
                                        physics_step_after=env.sim.get_physics_step_count(),
                                        begin_monotonic_ns=begin,
                                        end_monotonic_ns=time.monotonic_ns()))
                return result

        paced_steps = 0
        pacing_started_ns = time.monotonic_ns()

        def pace():
            nonlocal paced_steps
            deadline = pacing_started_ns + int(paced_steps * 1e9 / args.pace_hz)
            remaining = (deadline - time.monotonic_ns()) / 1e9
            if remaining > 0:
                time.sleep(remaining)
            paced_steps += 1

        if args.native_profile or args.native_nsys:
            from isaac_vr_native_profile import NativeProfile
            profiler = NativeProfile(env=env, record=record, media=native_media,
                                     performance_logger=perf, output=args.output / "native-profile.json",
                                     cprofile=args.native_profile_cprofile and not args.native_nsys,
                                     nvtx=args.native_nsys).__enter__()
        if args.native_nsys:
            torch.cuda.profiler.start()
        started_ns = time.perf_counter_ns()
        started = started_ns / 1e9
        transitions = record_injected_transitions(
            record,
            env,
            count=args.warmup + args.frames,
            performance_logger=perf,
            require_distinct_actions=False,
            decision_solver=solve,
            pre_step_callback=pace if args.pace_hz else None,
        )
        working_end = time.perf_counter()
        if args.native_nsys:
            torch.cuda.profiler.stop()
        if profiler:
            profiler.close()
        if motion_rows:
            # Persist outside the measured loop; HDF5 remains the source record.
            (args.output / "motion-trace.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in motion_rows)
            )
        summary = perf.close()
        if mirror:
            receipt["mirror"] = mirror.finish()
            encode_done = max(int(working_end * 1e9), receipt["mirror"]["worker"]["encode_done_ns"])
            receipt["complete_action_and_camera_hz_with_encode_tail"] = (
                (args.warmup + args.frames) * 1e9 / (encode_done - started_ns)
            )
        if native_media:
            receipt["native_camera"] = native_media.close()
            receipt["complete_action_and_camera_hz_with_encode_tail"] = (
                (args.warmup + args.frames) * 1e9 /
                (receipt["native_camera"]["encode_done_ns"] - started_ns)
            )
        completed_end = time.perf_counter()
        receipt.update(
            transitions={k: v for k, v in transitions.items() if k != "actions"},
            performance=summary,
            working_s=working_end - started,
            drain_and_optical_decode_s=completed_end - working_end,
            complete_hz_including_drain=(args.warmup + args.frames) / (completed_end - started),
            source_owner=owner.receipt if owner else {"source": "original_native_kit_physics"},
            camera_source_alignment_proven=False,
        )
        if args.xr:
            receipt["xr_enabled_at_stop"] = XRCore.get_singleton().is_xr_enabled()
        record.close(outcome="operator_stopped", reason="single_gpu_experimental_diagnostic")
        record = None
        if mirror:
            run = subprocess.run(
                [
                    sys.executable,
                    str(HELPERS / "verify_live_source.py"),
                    "--input",
                    str(args.output),
                    "--output",
                    str(args.output / "source-join.json"),
                ],
                capture_output=True,
                text=True,
            )
            (args.output / "source-join.log").write_text(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError("persisted state/media source join failed")
            receipt["camera_source_alignment_proven"] = True
            receipt["independent_pixel_source_id_check"] = bool(args.witness)
        receipt["passed"] = True
        return 0
    finally:
        # Remove the observer while the standalone owner still owns env methods.
        # Otherwise owner.close() restores master methods, then this observer
        # would accidentally reinstall the already-closed standalone methods.
        for target, name, previous, owned in reversed(restores):
            if owned:
                setattr(target, name, previous)
            else:
                vars(target).pop(name, None)
        errors = []
        cleanup = [
            profiler.close if profiler else None,
            native_media.close if native_media else None,
            mirror.abort if mirror else None,
            (
                lambda: record.close(
                    outcome="failure", reason="single_gpu_experimental_diagnostic_failed"
                )
            )
            if record
            else None,
            owner.close if owner else None,
            perf.close if not perf._closed else None,
        ]
        for release in cleanup:
            if release is not None:
                try:
                    release()
                except BaseException:
                    errors.append(traceback.format_exc())
        if owner:
            receipt["source_owner"] = owner.receipt
            receipt["source_owner_restoration_verified"] = all(
                vars(env).get(name) is previous if existed else name not in vars(env)
                for name, (existed, previous) in owner.saved.items()
            )
            if not receipt["source_owner_restoration_verified"]:
                errors.append("Standalone methods were not restored after diagnostic observers")
        if args.audit_host_events:
            (args.output / "host-events.jsonl").write_text(
                "".join(json.dumps(row) + "\n" for row in host_events)
            )
        receipt["cleanup_errors"] = errors
        if errors:
            receipt["passed"] = False
            raise RuntimeError("single-GPU cleanup failed; inspect retained cleanup_errors")


try:
    if args.native_copy_early_subscribe:
        import ctypes
        if args.kit_preview_transport != "cuda-event":
            raise ValueError("Early CUPTI subscription requires cuda-event transport")
        shim = Path(os.environ["VLA_NATIVE_COPY_SHIM"]).resolve(strict=True)
        native_copy_library = ctypes.CDLL(str(shim))
        initialize = native_copy_library.vla_copy_probe_init
        initialize.argtypes, initialize.restype = [], ctypes.c_int
        status = initialize()
        receipt["native_copy_early_subscription"] = dict(
            status=status, shim=str(shim), sha256=hashlib.sha256(shim.read_bytes()).hexdigest(),
            owns_subscriber=True, unknown_subscriber_removed=False,
        )
        if status:
            raise RuntimeError(f"Early own CUPTI subscription failed: {status}")
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
    if args.disable_kit_memorytracking:
        kit += ["--/plugins/carb.memorytracking.plugin/enabled=false"]
    if args.kit_legacy_products:
        kit += ["--/persistent/rtx/modes/rt/enabled=true", "--/persistent/rtx/modes/rt2/enabled=true"]
    if args.kit_rendering != "default":
        asynchronous = args.kit_rendering.startswith("async")
        kit += [
            "--/app/asyncRendering=" + str(asynchronous).lower(),
            "--/app/asyncRenderingLowLatency=" + str(args.kit_rendering == "async-latency").lower(),
            "--/app/omni.usd/asyncHandshake=" + str(asynchronous).lower(),
            "--/omni/replicator/asyncRendering=" + str(asynchronous).lower(),
            "--/exts/isaacsim.core.throttling/enable_async=false",
        ]
    if args.xr:
        kit += ["--enable", "omni.kit.scene_view.xr", "--enable", "omni.kit.scene_view.xr_utils"]
        os.environ["VLA_CLOUDXR_INSTALL_DIR"] = str(state / "cloudxr")
        configure_cloudxr(os.environ, mode="auto", dry_run=False)
    sys.argv = [
        str(ROOT / "tools/run_isaac_s1.py"),
        "--config",
        str(config),
        "--device",
        args.runtime_device,
        "--vr-runtime",
        "--s2-record",
        "--viz",
        "kit",
        "--kit_args",
        shlex.join(kit),
    ]
    if args.xr:
        sys.argv += ["--xr"]
    receipt["base_command"] = sys.argv.copy()
    ns = runpy.run_path(str(ROOT / "tools/run_isaac_s1.py"), run_name="single_gpu_shared_base")
    if args.xr:
        from isaaclab_teleop.isaac_teleop_device import _enable_teleop_bridge
        from omni.kit.xr.core import XRCore

        _enable_teleop_bridge()
        XRCore.get_singleton().request_enable_profile("ar")
        receipt["xr_profile_enabled"] = XRCore.get_singleton().is_xr_enabled()
    import isaac_s2_runtime

    if args.view_mode == "minimal":
        import carb.settings

        settings = carb.settings.get_settings()
        receipt["view_settings_before"] = {
            key: settings.get(key) for key in ("/rtx/rendermode", "/rtx/minimal/mode")
        }
        settings.set("/rtx/rendermode", "MinimalRendering")
        settings.set("/rtx/minimal/mode", 2)
    if args.native_source_proof:
        from isaac_vr_native_source_proof import prepare_source_proof_stage
        from isaaclab.sim import SimulationContext

        saved_reset = vars(SimulationContext)["reset"]
        proof_reset_restore = (SimulationContext, saved_reset)
        def first_proof_reset(sim, *pos, **kw):
            # Restore before entering the one ordinary reset, even if it fails.
            SimulationContext.reset = saved_reset
            layer = prepare_source_proof_stage(sim, clock_only=args.native_proof_clock_only,
                                               attribute_probe=args.native_attribute_probe,
                                               attribute_only=args.native_attribute_only,
                                               identity_only=args.native_identity_only)
            prepared_proof_layers.append((sim.stage, layer))
            receipt["source_proof_prepared_before_first_reset"] = True
            return saved_reset(sim, *pos, **kw)
        SimulationContext.reset = first_proof_reset
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
                raise RuntimeError("owned XR profile did not stop; server retained")
            owned.stop()
        ns["simulation_app"].close()
        owned_native_media.clear()
        for stage, layer in prepared_proof_layers:
            session = stage.GetSessionLayer()
            session.subLayerPaths = [p for p in session.subLayerPaths if p != layer.identifier]
        prepared_proof_layers.clear()
    if proof_reset_restore:
        cls, original_reset = proof_reset_restore
        cls.reset = original_reset
raise SystemExit(0 if receipt["passed"] else 1)
