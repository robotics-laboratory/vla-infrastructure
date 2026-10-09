"""Standalone OVPhysX screening probe; no Kit, XR, cameras or physical hardware.

Requires a separate environment: ovphysx==0.6.3, ovstage==0.2.0.377349,
warp-lang>=1.16,<2, numpy. Do not run inside the production Kit process.
Deprecated cached tensor bindings are deliberate benchmark candidates; their
public metadata has no current nondeprecated replacement. No dataset admission.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import time


ROOTS = [f"/World/{side}Piper/Geometry/world/base_link" for side in ("Left", "Right")]
NAMES = [f"joint{i}" for i in range(1, 7)] + ["gripper", "gripper_joint1", "gripper_joint2"]
STAGE_SHA = "03453f4d22eedb40c77cee68aabab241d0c0bf58b824f9c72afb59bef27b812b"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--mode", choices=["cpu", "gpu-readback", "gpu-direct"], default="cpu")
    p.add_argument("--threads", type=int, default=0)
    p.add_argument("--steps", type=int, default=3000)
    p.add_argument("--warmup", type=int, default=120)
    p.add_argument("--cadence", choices=["batch", "sync", "async"], default="batch")
    p.add_argument("--observation", choices=["none", "qv", "qv-links-all"], default="qv-links-all")
    args = p.parse_args()
    if args.steps < 1 or args.warmup < 0:
        p.error("positive steps and nonnegative warmup required")
    args.out.mkdir(parents=True, exist_ok=False)
    result = dict(
        schema="live30_ovphysx_screening_v1",
        target_achieved=False,
        gpu_run=args.mode != "cpu",
        dataset_admissible=False,
        physical=False,
        excluded=["XR", "Quest3", "IK", "cameras", "recorder", "contact_qualification"],
        args={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
    )
    result_path = args.out / "result.json"
    physx = stage = None
    attached = False
    bindings = []
    try:
        result["packages"] = {
            n: importlib.metadata.version(n) for n in ("ovphysx", "ovstage", "warp-lang", "numpy")
        }
        if (
            result["packages"]["ovphysx"] != "0.6.3"
            or result["packages"]["ovstage"] != "0.2.0.377349"
        ):
            raise RuntimeError(f"Wrong pinned SDK: {result['packages']}")
        result["stage_sha256"] = hashlib.sha256(args.stage.read_bytes()).hexdigest()
        if result["stage_sha256"] != STAGE_SHA:
            raise RuntimeError(
                "Retained input changed; audit a new stage instead of bypassing this guard"
            )
        import numpy as np
        import ovphysx
        import ovstage
        import warp as wp
        from ovphysx import PhysX, PhysXConfig, TensorType

        if args.mode == "cpu":
            PhysX.set_cpu_mode(True)
        physx = PhysX(
            config=PhysXConfig(
                num_threads=args.threads,
                carbonite_overrides={"/physics/suppressReadback": args.mode == "gpu-direct"},
            ),
            active_cuda_gpus=None if args.mode == "cpu" else "0",
        )
        ovstage.population.register_usd_schemas([str(ovphysx.codeless_schema_root())])
        stage = ovstage.Stage("live30-standalone-physx-screening")
        ovstage.population.open_usd(
            stage, str(args.stage.resolve()), ordinal=1, domains=ovstage.PopulationDomain.ALL
        )
        stage.advance_write_floor(ordinal=1).wait()
        physx.attach_ovstage(stage, read_ordinal=1)
        attached = True
        physx.warmup()  # Native ~1ns initialization, excluded from timing.

        def bind(kind, paths=ROOTS):
            b = physx.create_tensor_binding(prim_paths=paths, tensor_type=kind, raise_if_empty=True)
            bindings.append(b)
            if paths == ROOTS and (list(b.prim_paths) != ROOTS or b.shape[:2] != (2, 9)):
                raise RuntimeError(
                    f"Unexpected articulation topology/order: {b.prim_paths}, {b.shape}"
                )
            return b

        qbind = bind(TensorType.ARTICULATION_DOF_POSITION)
        if qbind.dof_names != NAMES:
            # Explicit mapping supports engine order, while requiring the exact inventory.
            if set(qbind.dof_names) != set(NAMES) or len(qbind.dof_names) != 9:
                raise RuntimeError(f"Unexpected DOF names: {qbind.dof_names}")
        order = [qbind.dof_names.index(n) for n in NAMES]
        result["topology"] = dict(
            roots=list(qbind.prim_paths),
            dof_names=qbind.dof_names,
            body_names=qbind.body_names,
            fixed_base=qbind.is_fixed_base,
        )
        if not qbind.is_fixed_base:
            raise RuntimeError("Expected fixed-base PIPERs")
        vb = bind(TensorType.ARTICULATION_DOF_VELOCITY)
        target = bind(TensorType.ARTICULATION_DOF_POSITION_TARGET)
        q = np.empty(qbind.shape, np.float32)
        v = np.empty(vb.shape, np.float32)
        qbind.read(q)
        result["initial_q"] = q.tolist()

        def engine_order(values):
            out = np.empty((2, 9), np.float32)
            out[:, order] = values
            return out

        # The USD snapshot omits Lab's runtime drive overrides. Apply the exact
        # current effective controls in live simulation; never alter source USD.
        for kind, value in [
            (TensorType.ARTICULATION_DOF_STIFFNESS, [400.0] * 6 + [2000.0] * 3),
            (TensorType.ARTICULATION_DOF_DAMPING, [40.0] * 6 + [100.0] * 3),
            (TensorType.ARTICULATION_DOF_MAX_FORCE, [100.0] * 6 + [10.0] * 3),
            (TensorType.ARTICULATION_DOF_MAX_VELOCITY, [5.0] * 6 + [3.0] * 3),
        ]:
            b = bind(kind)
            data = engine_order(value)
            b.write(data)
            check = np.empty_like(data)
            b.read(check)
            if not np.allclose(check, data, rtol=1e-5, atol=1e-6):
                raise RuntimeError(f"Drive property did not round-trip: {kind}")
        home = engine_order(
            [0.0, math.pi / 6.0, -math.pi / 3.0, 0.0, math.pi / 9.0, 0.0, 0.05, 0.025, -0.025]
        )
        zero = np.zeros_like(home)
        qbind.write(home)
        vb.write(zero)
        target.write(home)
        bind(TensorType.ARTICULATION_DOF_VELOCITY_TARGET).write(zero)
        bind(TensorType.ARTICULATION_DOF_ACTUATION_FORCE).write(zero)
        result["drive_overrides"] = (
            "arm400/40/100/5; gripper2000/100/10/3 in native rad/metre units"
        )

        native = target.native_device
        use_cuda = int(native.device_type.value) == 2
        if args.mode == "gpu-direct" and not use_cuda:
            raise RuntimeError("DirectGPU requested but articulation binding is host-resident")
        command = (
            wp.array(
                home, dtype=wp.float32, device=f"cuda:{native.device_id}" if use_cuda else "cpu"
            )
            if use_cuda
            else home.copy()
        )
        cycle = []
        for i in range(120):
            a = [0.0, math.pi / 6.0, -math.pi / 3.0, 0.0, math.pi / 9.0, 0.0, 0.05, 0.025, -0.025]
            a[0] = 0.12 * math.sin(i * 2 * math.pi / 120)
            a[6] = 0.05 + 0.03 * math.sin(i * 2 * math.pi / 120)
            a[7], a[8] = 0.5 * a[6], -0.5 * a[6]
            data = engine_order(a)
            cycle.append(
                wp.array(data, dtype=wp.float32, device=command.device) if use_cuda else data
            )
        body_binding = body = None
        if args.observation == "qv-links-all":
            body_binding = physx.create_tensor_binding(
                pattern="/World/*", tensor_type=TensorType.RIGID_BODY_POSE, raise_if_empty=True
            )
            bindings.append(body_binding)
            if body_binding.count != 27:
                raise RuntimeError(
                    f"Expected all27 retained rigid bodies, got {body_binding.count}"
                )
            body = np.empty(body_binding.shape, np.float32)
            result["body_paths"] = list(body_binding.prim_paths)

        def tick(i):
            t0 = time.perf_counter_ns()
            if use_cuda:
                wp.copy(command, cycle[i % 120])
                # Cached raw descriptors do not renegotiate DLPack streams.
                # This conservative producer wait is included in measured cost.
                wp.synchronize_stream(wp.get_stream(command.device))
            else:
                np.copyto(command, cycle[i % 120])
            target.write(command)  # Persistent zero-order hold; all9DOFs per arm.
            t1 = time.perf_counter_ns()
            if args.cadence == "batch":
                physx.step_n_sync(4, 1.0 / 120.0)
            else:
                for _ in range(4):
                    if args.cadence == "sync":
                        physx.step_sync(1.0 / 120.0)
                    else:
                        physx.step(1.0 / 120.0)
                if args.cadence == "async":
                    physx.wait_all()
            t2 = time.perf_counter_ns()
            if args.observation != "none":
                qbind.read(q)
                vb.read(v)
                if body_binding is not None:
                    body_binding.read(body)
                if (
                    not np.isfinite(q).all()
                    or not np.isfinite(v).all()
                    or (body is not None and not np.isfinite(body).all())
                ):
                    raise RuntimeError("Nonfinite simulation state")
            t3 = time.perf_counter_ns()
            return [(t1 - t0) / 1e6, (t2 - t1) / 1e6, (t3 - t2) / 1e6, (t3 - t0) / 1e6]

        for i in range(args.warmup):
            tick(i)
        samples, traces = [], []
        start = time.perf_counter_ns()
        for i in range(args.steps):
            samples.append(tick(i + args.warmup))
            if i < 256 and args.observation != "none":
                traces.append(dict(i=i, q=q.tolist(), dq=v.tolist()))
        physx.wait_all()
        elapsed = (time.perf_counter_ns() - start) / 1e9
        a = np.asarray(samples)
        result.update(
            status="completed_screening_only",
            controls=args.steps,
            physics_steps=4 * args.steps,
            wall_seconds=elapsed,
            wall_controls_hz=args.steps / elapsed,
            native_binding_cuda=use_cuda,
            buckets={
                name: dict(
                    mean_ms=float(a[:, j].mean()),
                    p95_ms=float(np.percentile(a[:, j], 95)),
                    p99_ms=float(np.percentile(a[:, j], 99)),
                    max_ms=float(a[:, j].max()),
                )
                for j, name in enumerate(["target", "physics4", "read_state", "tick"])
            },
        )
        (args.out / "samples.json").write_text(
            json.dumps(dict(timings_ms=samples, first256_traces=traces))
        )
    except BaseException as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        result_path.write_text(json.dumps(result, indent=2))
        for b in reversed(bindings):
            b.destroy()
        if physx is not None:
            if stage is not None:
                if attached:
                    physx.detach_ovstage()
                stage.destroy()
            physx.destroy()


if __name__ == "__main__":
    main()
