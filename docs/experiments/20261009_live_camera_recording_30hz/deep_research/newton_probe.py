"""Opt-in standalone full-USD Newton/MuJoCo screening; no Kit, XR or dataset claims.

Run with the declared Isaac production interpreter; parent owns GPU serialization.
Each run uses a fresh process/output directory. This file itself was only AST checked.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--backend", choices=["cpu", "cpu-direct", "cuda-eager", "cuda-graph"], default="cpu"
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--ticks", type=int, default=180)
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--expect-mimic", type=int, default=4)
    parser.add_argument("--stage-audit", required=True, type=Path)
    parser.add_argument("--effective-actuators", choices=["runtime", "usd"], default="runtime")
    parser.add_argument("--require-joint", action="append", default=[])
    parser.add_argument("--midphase", choices=["disabled", "native"], default="disabled")
    parser.add_argument("--readback", choices=["body-and-joint", "none"], default="body-and-joint")
    parser.add_argument("--allow-execute", action="store_true")
    args = parser.parse_args()
    if not args.allow_execute:
        parser.error("Explicit --allow-execute required; the parent serializes GPU work.")
    if not args.stage.is_file() or args.ticks < 1 or args.warmup < 1:
        parser.error("Require an existing local USD and positive ticks/warmup.")
    args.out.mkdir(parents=True, exist_ok=False)
    receipt = dict(
        schema="piper_x_newton_screen_v1",
        status="started",
        dataset_admissible=False,
        source_phase_verified=False,
        full_scene_fidelity_verified=False,
        xr_active=False,
        cameras=0,
        robot_hardware_access=False,
        physics_dt_s=1.0 / 120.0,
        physics_steps_per_tick=4,
        backend=args.backend,
        midphase=args.midphase,
        readback=args.readback,
        stage=str(args.stage.resolve()),
        stage_sha256=hashlib.sha256(args.stage.read_bytes()).hexdigest(),
    )
    try:
        pins = {
            p: importlib.metadata.version(p)
            for p in ["newton", "warp-lang", "mujoco", "mujoco-warp"]
        }
        if pins != {
            "newton": "1.5.2",
            "warp-lang": "1.16.0",
            "mujoco": "3.11.0",
            "mujoco-warp": "3.11.0",
        }:
            raise RuntimeError(f"Unexpected installed packages: {pins}")
        receipt["packages"] = pins
        preimages = json.loads(Path(__file__).with_name("newton_preimages.json").read_text())
        for path, expected in preimages.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Source preimage changed: {path}")
        receipt["source_sha256"] = preimages
        import numpy as np
        import warp as wp
        import newton
        import mujoco
        from newton.solvers import SolverMuJoCo

        device = "cpu" if args.backend.startswith("cpu") else args.device
        wp.config.kernel_cache_dir = str(args.out / "warp-cache")
        wp.init()
        wp.set_device(device)
        build_start = time.perf_counter()
        builder = newton.ModelBuilder()
        SolverMuJoCo.register_custom_attributes(builder)
        # No roots, shapes or fixed links are intentionally removed. All import
        # defaults/unsupported USD semantics still require a separate fidelity audit.
        builder.add_usd(
            str(args.stage.resolve()),
            collapse_fixed_joints=False,
            load_visual_shapes=True,
            load_static_visual_shapes=True,
        )
        stage_audit = json.loads(args.stage_audit.read_text())
        if stage_audit["sha256"] != receipt["stage_sha256"]:
            raise RuntimeError("Stage audit does not bind this exact input USD")
        expected_paths = {x["path"] for x in stage_audit["joints"]}
        if not expected_paths.issubset(set(builder.joint_label)):
            raise RuntimeError("Full source joint inventory was not preserved by importer")
        receipt["stage_audit_sha256"] = hashlib.sha256(args.stage_audit.read_bytes()).hexdigest()
        overlays = []
        if args.effective_actuators == "runtime":
            for j, label in enumerate(builder.joint_label):
                if label not in expected_paths:
                    continue
                dof = builder.joint_qd_start[j]
                leaf = str(label).rsplit("/", 1)[-1]
                gains = (
                    (400.0, 40.0, 100.0, 5.0)
                    if leaf.startswith("joint")
                    else (2000.0, 100.0, 10.0, 3.0)
                )
                builder.joint_target_ke[dof], builder.joint_target_kd[dof] = gains[:2]
                builder.joint_effort_limit[dof], builder.joint_velocity_limit[dof] = gains[2:]
                overlays.append(
                    dict(
                        path=label,
                        dof=dof,
                        stiffness=gains[0],
                        damping=gains[1],
                        effort_limit=gains[2],
                        velocity_limit=gains[3],
                    )
                )
        receipt["effective_actuator_overlay"] = overlays
        receipt["effective_actuators"] = args.effective_actuators
        model = builder.finalize(device=device)
        receipt["model"] = dict(
            body_count=model.body_count,
            shape_count=model.shape_count,
            joint_count=model.joint_count,
            mimic_count=model.constraint_mimic_count,
            body_labels=list(model.body_label),
            joint_labels=list(model.joint_label),
            shape_labels=list(model.shape_label),
        )
        receipt["imported_mimics"] = [
            dict(
                label=label,
                joint0=model.joint_label[int(j0)],
                joint1=model.joint_label[int(j1)],
                coef0=float(c0),
                coef1=float(c1),
            )
            for label, j0, j1, c0, c1 in zip(
                model.constraint_mimic_label,
                model.constraint_mimic_joint0.numpy(),
                model.constraint_mimic_joint1.numpy(),
                model.constraint_mimic_coef0.numpy(),
                model.constraint_mimic_coef1.numpy(),
                strict=True,
            )
        ]
        expected_mimics = [
            dict(
                label=f"/World/{side}Piper/Physics/gripper_joint{i}",
                joint0=f"/World/{side}Piper/Physics/gripper_joint{i}",
                joint1=f"/World/{side}Piper/Physics/gripper",
                coef0=0.0,
                coef1=(0.5 if i == 1 else -0.5),
            )
            for side in ["Left", "Right"]
            for i in [1, 2]
        ]
        if receipt["imported_mimics"] != expected_mimics:
            raise RuntimeError(
                "Mimic references/coefs differ from authored NewtonMimicAPI inventory"
            )
        if model.constraint_mimic_count != args.expect_mimic:
            raise RuntimeError("Imported mimic inventory differs from the exact source contract")
        for suffix in args.require_joint:
            if not any(str(label).endswith(suffix) for label in model.joint_label):
                raise RuntimeError(f"Required joint label missing: {suffix}")
        solver = SolverMuJoCo(
            model,
            use_mujoco_cpu=args.backend.startswith("cpu"),
            use_mujoco_contacts=True,
            update_data_interval=1,
            save_to_mjcf=str(args.out / "imported.xml"),
        )
        if args.backend.startswith("cpu") and args.midphase == "disabled":
            # Recorded workaround for upstream #3805; this removes an unsafe
            # acceleration structure, without disabling narrow-phase contacts.
            solver.mj_model.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_MIDPHASE)
        state = model.state()
        control = model.control()
        newton.eval_fk(model, state.joint_q, state.joint_qd, state)
        receipt["build_wall_s"] = time.perf_counter() - build_start
        receipt["control_semantics"] = (
            "Fixed authored/imported targets; no canonical D0 actions or robot commands"
        )
        receipt["initial_joint_q"] = state.joint_q.numpy().tolist()

        def group():
            for _ in range(4):
                state.clear_forces()
                solver.step(state, state, control, None, 1.0 / 120.0)

        group()  # Allocates scratch and binds native CPU controls before direct path.
        graph = None
        if args.backend == "cuda-graph":
            wp.synchronize_device(device)
            was_enabled = gc.isenabled()
            gc.disable()
            try:
                with wp.ScopedCapture(device=device) as capture:
                    group()
                graph = capture.graph
            finally:
                if was_enabled:
                    gc.enable()

        def step():
            if args.backend == "cpu-direct":
                # Lower bound: exactly the compiled model/contact/actuator system,
                # held initial controls; bypass Newton output conversion entirely.
                solver.mj_model.opt.timestep = 1.0 / 120.0
                for _ in range(4):
                    mujoco.mj_step(solver.mj_model, solver.mj_data)
            elif graph is not None:
                wp.capture_launch(graph)
            else:
                group()
            if device != "cpu":
                wp.synchronize_stream(wp.get_stream(device))
            if args.readback == "body-and-joint":
                if args.backend == "cpu-direct":
                    solver.mj_data.xpos.copy()
                    solver.mj_data.qpos.copy()
                else:
                    state.body_q.numpy()
                    state.joint_q.numpy()

        for _ in range(args.warmup):
            step()
        spans = []
        for _ in range(args.ticks):
            start = time.perf_counter_ns()
            step()
            spans.append((time.perf_counter_ns() - start) / 1e6)
        final_q = (
            solver.mj_data.qpos.copy() if args.backend == "cpu-direct" else state.joint_q.numpy()
        )
        if not np.isfinite(final_q).all():
            raise RuntimeError("Non-finite final joint state")
        receipt.update(
            status="completed",
            ticks=args.ticks,
            warmup=args.warmup,
            tick_ms=spans,
            mean_ms=float(np.mean(spans)),
            p95_ms=float(np.percentile(spans, 95)),
            mean_tick_hz=1000.0 / float(np.mean(spans)),
            final_joint_q=final_q.tolist(),
            graph_captured=graph is not None,
        )
        if args.backend.startswith("cpu"):
            receipt["final_contacts"] = int(solver.mj_data.ncon)
        print(
            json.dumps(
                {k: receipt[k] for k in ["status", "backend", "mean_ms", "p95_ms", "mean_tick_hz"]}
            )
        )
    except BaseException:
        receipt.update(status="failed", error=traceback.format_exc())
        raise
    finally:
        (args.out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
