"""Pinned standalone CPU PhysX worker; inherited private Connection fd only.

Distinct diagnostic profile; no Kit imports, GPU, D1 or physical actuation.
Caller creates socketpair, passes child fd via Popen(pass_fds=(fd,)), then uses
multiprocessing.connection.Connection(parent_fd) for plain-dict messages.
"""

from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
from multiprocessing.connection import Connection
from pathlib import Path
import time


def validate_seed(seed):
    """Reject malformed native-unit state before constructing the physics runtime."""
    import numpy as np

    if not isinstance(seed, dict) or seed.get("schema") != "standalone_cpu_physx_seed_v1":
        raise ValueError("Unsupported seed schema")
    required = (
        "profile",
        "files",
        "stage_overlay",
        "articulation_roots",
        "rigid_body_paths",
        "dynamic_body_paths",
        "dof_names",
        "body_names",
        "drive_type",
        "dof_properties",
        "initial",
        "mimic_config",
    )
    missing = [name for name in required if name not in seed]
    if missing:
        raise ValueError(f"Missing seed fields: {missing}")
    if seed.get("dof_units", ["rad"] * 6 + ["m"] * 3) != ["rad"] * 6 + ["m"] * 3:
        raise ValueError("Native DOF units must be six radians and three metres")
    values = [(seed["initial"].get(name), (2, 9), name) for name in ("q", "dq")]
    values += [
        (seed["dof_properties"].get(name), (2, 9, 2) if name == "limits" else (2, 9), name)
        for name in ("stiffness", "damping", "max_force", "max_velocity", "limits")
    ]
    values += [
        (seed["initial"].get("dynamic_body_pose"), (3, 7), "dynamic_body_pose"),
        (seed["initial"].get("dynamic_body_velocity"), (3, 6), "dynamic_body_velocity"),
    ]
    for value, shape, name in values:
        data = np.asarray(value, np.float32)
        if data.shape != shape or not np.isfinite(data).all():
            raise ValueError(f"Malformed seed {name}: expected finite native array{shape}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fd", type=int, required=True)
    p.add_argument("--seed", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    a = p.parse_args()
    connection = Connection(a.fd)
    receipt = dict(
        schema="standalone_cpu_physx_worker_receipt_v1",
        status="starting",
        physical=False,
        dataset_admissible=False,
        gpu_execution=False,
        controls=0,
        physics_steps=0,
        worker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        seed_sha256=hashlib.sha256(a.seed.read_bytes()).hexdigest(),
    )
    physx = stage = None
    attached = False
    bindings = []
    try:
        import numpy as np

        seed = json.loads(a.seed.read_text())
        validate_seed(seed)
        import ovphysx
        import ovstage
        from ovphysx import PhysX, PhysXConfig, TensorType

        receipt["profile"] = seed["profile"]
        versions = {
            n: importlib.metadata.version(n) for n in ("ovphysx", "ovstage", "warp-lang", "numpy")
        }
        receipt["packages"] = versions
        if versions["ovphysx"] != "0.6.3" or versions["ovstage"] != "0.2.0.377349":
            raise RuntimeError(f"Pinned physics packages differ: {versions}")
        for item in seed["files"]:
            if hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError(f"Input provenance changed: {item['path']}")
        stage_path = str(Path(seed["stage_overlay"]).resolve())
        if stage_path not in [str(Path(f["path"]).resolve()) for f in seed["files"]]:
            raise ValueError("stage_overlay must be included in pinned files")
        roots, paths = seed["articulation_roots"], seed["rigid_body_paths"]
        if len(roots) != 2 or len(paths) != 27 or len(set(paths)) != 27:
            raise ValueError("Require two articulation roots and27 unique body paths")
        PhysX.set_cpu_mode(True)
        physx = PhysX(
            config=PhysXConfig(num_threads=int(seed.get("num_threads", 0))), active_cuda_gpus=None
        )
        ovstage.population.register_usd_schemas([str(ovphysx.codeless_schema_root())])
        stage = ovstage.Stage("standalone-cpu-piper-diagnostic")
        ovstage.population.open_usd(
            stage, stage_path, ordinal=1, domains=ovstage.PopulationDomain.ALL
        )
        stage.advance_write_floor(1).wait()
        physx.attach_ovstage(stage, read_ordinal=1)
        attached = True
        physx.warmup()  # initialization only, excluded from logical physics_steps

        def bind(tensor, prim_paths):
            b = physx.create_tensor_binding(
                prim_paths=prim_paths, tensor_type=getattr(TensorType, tensor), raise_if_empty=True
            )
            bindings.append(b)
            if list(b.prim_paths) != prim_paths or int(b.native_device.device_type.value) != 1:
                raise RuntimeError(f"CPU path/order guard failed: {tensor}")
            return b

        def read(b, dtype=np.float32):
            x = np.empty(b.shape, dtype)
            b.read(x)
            if np.issubdtype(x.dtype, np.floating) and not np.isfinite(x).all():
                raise RuntimeError("Nonfinite native state")
            return x.copy()

        def array(value, shape):
            x = np.asarray(value, np.float32)
            if x.shape != shape or not np.isfinite(x).all():
                raise ValueError(f"Expected finite float32 array{shape}, got{x.shape}")
            return np.ascontiguousarray(x)

        q = bind("ARTICULATION_DOF_POSITION", roots)
        if (
            q.shape != (2, 9)
            or q.dof_names != seed["dof_names"]
            or q.body_names != seed["body_names"]
            or not q.is_fixed_base
        ):
            raise RuntimeError("Fixed-base articulation topology differs from seed")
        dq = bind("ARTICULATION_DOF_VELOCITY", roots)
        target = bind("ARTICULATION_DOF_POSITION_TARGET", roots)
        velocity_target = bind("ARTICULATION_DOF_VELOCITY_TARGET", roots)
        external_effort = bind("ARTICULATION_DOF_ACTUATION_FORCE", roots)
        root_pose = bind("ARTICULATION_ROOT_POSE", roots)
        body_pose = bind("RIGID_BODY_POSE", paths)
        com_pose = bind("ARTICULATION_BODY_COM_POSE", roots)
        jacobian = bind("ARTICULATION_JACOBIAN", roots)
        if (
            body_pose.shape != (27, 7)
            or com_pose.shape != (2, 12, 7)
            or jacobian.shape != (2, 66, 9)
        ):
            raise RuntimeError("Piper body/COM/Jacobian shape differs")
        drive_types = read(bind("ARTICULATION_DOF_DRIVE_TYPE", roots), np.uint8)
        expected_types = np.asarray(seed["drive_type"], np.uint8)
        if expected_types.shape != (2, 9) or not np.array_equal(drive_types, expected_types):
            raise RuntimeError("Native drive types differ from seed")
        properties = {}
        for name, enum in [
            ("stiffness", "ARTICULATION_DOF_STIFFNESS"),
            ("damping", "ARTICULATION_DOF_DAMPING"),
            ("max_force", "ARTICULATION_DOF_MAX_FORCE"),
            ("max_velocity", "ARTICULATION_DOF_MAX_VELOCITY"),
            ("limits", "ARTICULATION_DOF_LIMIT"),
        ]:
            b = bind(enum, roots)
            data = array(seed["dof_properties"][name], (2, 9, 2) if name == "limits" else (2, 9))
            b.write(data)
            native = read(b)
            if not np.allclose(native, data, rtol=1e-5, atol=1e-6):
                raise RuntimeError(f"Native property roundtrip failed: {name}")
            properties[name] = native
        initial = seed["initial"]
        q.write(array(initial["q"], (2, 9)))
        dq.write(array(initial["dq"], (2, 9)))
        target.write(array(initial.get("position_target", initial["q"]), (2, 9)))
        velocity_target.write(array(initial.get("velocity_target", np.zeros((2, 9))), (2, 9)))
        external_effort.write(array(initial.get("external_effort", np.zeros((2, 9))), (2, 9)))
        dynamic_paths = seed["dynamic_body_paths"]
        if (
            len(dynamic_paths) != 3
            or len(set(dynamic_paths)) != 3
            or not set(dynamic_paths).issubset(paths)
        ):
            raise ValueError("Require exact three standalone dynamic body paths")
        dynamic_pose = bind("RIGID_BODY_POSE", dynamic_paths)
        dynamic_velocity = bind("RIGID_BODY_VELOCITY", dynamic_paths)
        dynamic_pose.write(array(initial["dynamic_body_pose"], (3, 7)))
        dynamic_velocity.write(array(initial["dynamic_body_velocity"], (3, 6)))
        physx.update_articulations_kinematic()
        root_reference = read(root_pose)
        if "root_pose" in initial and not np.allclose(
            root_reference, array(initial["root_pose"], (2, 7)), rtol=0.0, atol=2e-5
        ):
            raise RuntimeError("Fixed root seed pose differs")
        com_local = read(com_pose)
        current_seq = -1
        diagnostics, diagnostic_properties, contact = {}, {}, None
        if seed.get("capture_diagnostics", False):
            # Opt-in observer: native reads only; default live profile unchanged.
            for name in ("ARTICULATION_LINK_VELOCITY", "RIGID_BODY_VELOCITY"):
                diagnostics[name] = bind(name, roots if name.startswith("ARTICULATION") else dynamic_paths)
            for name in ("ARTICULATION_BODY_MASS", "ARTICULATION_BODY_INERTIA",
                    "ARTICULATION_BODY_COM_POSE", "ARTICULATION_DOF_ARMATURE",
                    "ARTICULATION_DOF_FRICTION_PROPERTIES", "RIGID_BODY_MASS",
                    "RIGID_BODY_INERTIA", "RIGID_BODY_COM_POSE"):
                diagnostic_properties[name] = read(bind(name,
                    roots if name.startswith("ARTICULATION") else dynamic_paths))
            contact = physx.create_contact_binding(sensor_patterns=paths)
            bindings.append(contact)
            diagnostic_properties["contact_sensor_paths"] = contact.sensor_paths
            diagnostic_properties["contact_unavailable_paths"] = [p for p in paths if p not in contact.sensor_paths]

        def capture(seq):
            rp = read(root_pose)
            if not q.is_fixed_base or not np.allclose(rp, root_reference, rtol=0.0, atol=1e-6):
                raise RuntimeError("Fixed root native flag/world pose changed")
            q_now = read(q)
            snapshot = dict(
                seq=seq,
                physics_steps=receipt["physics_steps"],
                sim_time_s=receipt["physics_steps"] / 120.0,
                q=q_now,
                dq=read(dq),
                rigid_body_world_pose=read(body_pose),
                articulation_body_com_local_pose=com_local.copy(),
                jacobian=read(jacobian),
                root_pose=rp,
                fixed_base=True,
                mimic_residual=np.stack(
                    [q_now[:, 7] - 0.5 * q_now[:, 6], q_now[:, 8] + 0.5 * q_now[:, 6]], axis=-1
                ),
            )
            if diagnostics:
                snapshot["articulation_link_velocity"] = read(diagnostics["ARTICULATION_LINK_VELOCITY"])
                snapshot["dynamic_body_velocity"] = read(diagnostics["RIGID_BODY_VELOCITY"])
                forces = np.empty((contact.sensor_count, 3), np.float32)
                contact.read_net_forces(forces)
                snapshot["contact_sensor_force"] = forces.copy()
            return snapshot

        initial_snapshot = capture(-1)
        # Exact initial q/dq is checked after FK and all seed state writes.
        if not np.allclose(initial_snapshot["q"], array(initial["q"], (2, 9)), rtol=0.0, atol=2e-5):
            raise RuntimeError("Native initial joint position differs")
        if not np.allclose(
            initial_snapshot["dq"], array(initial["dq"], (2, 9)), rtol=0.0, atol=2e-5
        ):
            raise RuntimeError("Native initial joint velocity differs")
        connection.send(
            dict(
                op="ready",
                schema="standalone_cpu_physx_worker_v1",
                profile=seed["profile"],
                packages=versions,
                seed_sha256=receipt["seed_sha256"],
                dof_names=q.dof_names,
                body_names=q.body_names,
                articulation_roots=list(q.prim_paths),
                rigid_body_paths=list(body_pose.prim_paths),
                dof_properties=properties,
                drive_type=drive_types,
                diagnostic_properties=diagnostic_properties,
                mimic_config=seed["mimic_config"],
                mimic_native_runtime_verified=False,
                quaternion_order="xyzw",
                dof_units=["rad"] * 6 + ["m"] * 3,
                snapshot=initial_snapshot,
                dataset_admissible=False,
                physical=False,
            )
        )
        receipt["status"] = "ready"
        while True:
            message = connection.recv()
            op = message.get("op")
            if op in ("close", "abort"):
                receipt["status"] = "aborted" if op == "abort" else "completed_diagnostic"
                receipt["reason"] = str(message.get("reason", ""))
                connection.send(
                    dict(
                        op="closed",
                        controls=receipt["controls"],
                        physics_steps=receipt["physics_steps"],
                    )
                )
                break
            if (
                op != "step"
                or type(message.get("seq")) is not int
                or message["seq"] != current_seq + 1
            ):
                raise ValueError("Require monotonically consecutive integer step seq starting0")
            targets = array(message["native_targets"], (2, 9))
            seq = current_seq + 1
            begin = time.perf_counter_ns()
            target.write(targets)
            applied = time.perf_counter_ns()
            physx.step_n_sync(4, 1.0 / 120.0)
            completed = time.perf_counter_ns()
            receipt["physics_steps"] += 4
            receipt["controls"] += 1
            current_seq = seq
            snapshot = capture(seq)
            captured = time.perf_counter_ns()
            connection.send(
                dict(
                    op="captured",
                    snapshot=snapshot,
                    native_targets=targets.copy(),
                    timings_ns=dict(
                        target=applied - begin,
                        physics4=completed - applied,
                        capture=captured - completed,
                        total=captured - begin,
                    ),
                )
            )
    except EOFError:
        receipt.update(status="aborted", reason="parent_connection_closed")
    except BaseException as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        try:
            connection.send(dict(op="error", **receipt))
        except (OSError, EOFError):
            pass
        raise
    finally:
        cleanup_errors = []
        for b in reversed(bindings):
            try:
                b.destroy()
            except Exception as exc:
                cleanup_errors.append(repr(exc))
        cleanup = []
        if physx is not None and attached:
            cleanup.append(physx.detach_ovstage)
        if stage is not None:
            cleanup.append(stage.destroy)
        if physx is not None:
            cleanup.append(physx.destroy)
        for release in cleanup:
            try:
                release()
            except Exception as exc:
                cleanup_errors.append(repr(exc))
        receipt["cleanup_errors"] = cleanup_errors
        a.receipt.parent.mkdir(parents=True, exist_ok=True)
        a.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
        connection.close()


if __name__ == "__main__":
    main()
