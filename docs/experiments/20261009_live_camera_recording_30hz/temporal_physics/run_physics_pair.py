"""Diagnostic same-input Kit GPU PhysX / standalone CPU PhysX paired assay.

Reuse canonical run-vr scene and existing CPU worker; no physical actuation.
One Kit child runs cases; all snapshots are copied at completed four-step edges.
"""

from __future__ import annotations
import argparse
import hashlib
import json
from multiprocessing.connection import Connection
import os
from pathlib import Path
import socket
import subprocess
import time

import numpy as np

REPO = Path(__file__).resolve().parents[4]
MASTER = "beaedfd1116577fd4d8026232cfb96cba0b030fa"
CORE = (
    "configs/isaac61_vr_runtime.yaml",
    "configs/isaac61_s2_runtime.yaml",
    "tools/run_isaac_s1.py",
    "tools/isaac_s1_runtime.py",
    "tools/isaac_vr_runtime.py",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def host(value):
    value = value.torch if hasattr(value, "torch") else value
    return (
        value.detach().cpu().numpy()
        if hasattr(value, "detach")
        else np.asarray(value.numpy() if hasattr(value, "numpy") else value)
    ).copy()


def jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def save_json(path, value):
    Path(path).write_text(json.dumps(jsonable(value), indent=2, allow_nan=False) + "\n")


def persist_results(out, canonical_report, result):
    save_json(Path(out) / "result.json", result)
    if canonical_report is not None:
        save_json(Path(canonical_report), result)


def command9(command7):
    values = np.asarray(command7, np.float32).reshape(2, 7)
    return np.concatenate((values, 0.5 * values[:, 6:7], -0.5 * values[:, 6:7]), axis=1)


def gpu_snapshot(env, contact):
    views = [r.root_view for r in env.robots]
    props = [*env.vr_runtime.dynamic_assets, env.physics_probe]
    poses = np.concatenate(
        [host(v.get_link_transforms()).reshape(12, 7) for v in views]
        + [host(p.root_view.get_transforms()).reshape(1, 7) for p in props]
    )
    velocity = np.concatenate(
        [host(v.get_link_velocities()).reshape(12, 6) for v in views]
        + [host(p.root_view.get_velocities()).reshape(1, 6) for p in props]
    )
    jac = []
    for v in views:
        raw = host(v.get_jacobians())
        if v.shared_metatype.fixed_base:
            jac.append(raw.reshape(11, 6, 9))
        else:
            jac.append(raw.reshape(12, 6, 15)[1:, :, 6:])
    return dict(
        q=np.stack([host(v.get_dof_positions()).reshape(9) for v in views]),
        dq=np.stack([host(v.get_dof_velocities()).reshape(9) for v in views]),
        body_pose=poses,
        body_velocity=velocity,
        jacobian=np.stack(jac),
        contact_sensor_force=host(contact.get_net_contact_forces(1 / 120)),
    )


def cpu_snapshot(snapshot):
    return dict(
        q=snapshot["q"].copy(),
        dq=snapshot["dq"].copy(),
        body_pose=snapshot["rigid_body_world_pose"].copy(),
        jacobian=snapshot["jacobian"].reshape(2, 11, 6, 9).copy(),
        body_velocity=np.concatenate(
            (
                snapshot["articulation_link_velocity"].reshape(24, 6),
                snapshot["dynamic_body_velocity"],
            )
        ),
        contact_sensor_force=snapshot["contact_sensor_force"].copy(),
    )


def properties_gpu(env):
    views = [r.root_view for r in env.robots]
    props = [*env.vr_runtime.dynamic_assets, env.physics_probe]
    return {
        name: np.concatenate(
            [host(getattr(v, getter)()).reshape(shape) for v in views]
            + [host(getattr(p.root_view, getter)()).reshape((1,) + shape[1:]) for p in props]
        )
        for name, getter, shape in [
            ("body_mass", "get_masses", (12,)),
            ("body_com_local_pose", "get_coms", (12, 7)),
            ("body_inertia_local", "get_inertias", (12, 3, 3)),
        ]
    }


def properties_cpu(values):
    return {
        name: np.concatenate((values[a].reshape(shape), values[b].reshape((3,) + shape[1:])))
        for name, a, b, shape in [
            ("body_mass", "ARTICULATION_BODY_MASS", "RIGID_BODY_MASS", (24,)),
            ("body_com_local_pose", "ARTICULATION_BODY_COM_POSE", "RIGID_BODY_COM_POSE", (24, 7)),
            ("body_inertia_local", "ARTICULATION_BODY_INERTIA", "RIGID_BODY_INERTIA", (24, 3, 3)),
        ]
    }


def capture(trace, snapshot, step, seq, target, started, paths, sensors, intent=None):
    force = np.full((27, 3), np.nan, np.float32)
    for i, path in enumerate(sensors):
        force[paths.index(path)] = snapshot["contact_sensor_force"][i]
    row = {k: v for k, v in snapshot.items() if k != "contact_sensor_force"}
    row.update(
        physics_step=step,
        sim_time_s=step / 120,
        wall_time_s=time.perf_counter() - started,
        action_seq=seq,
        native_targets=target.copy(),
        contact_net_force=force,
    )
    if intent is not None:
        row["cartesian_intents"] = intent.copy()
    trace.append(row)


def solve(controller, state, intents, aperture, device):
    import torch

    values = []
    for arm, c in enumerate(controller):
        pos = torch.as_tensor(state["tcp_pose_w"][arm : arm + 1, :3].copy(), device=device)
        quat = torch.as_tensor(state["tcp_pose_w"][arm : arm + 1, 3:].copy(), device=device)
        q = torch.as_tensor(state["q"][arm : arm + 1].copy(), device=device)
        jac = torch.as_tensor(state["jacobian"][arm : arm + 1].copy(), device=device)
        c.set_command(
            torch.as_tensor(intents[arm : arm + 1].copy(), device=device), ee_pos=pos, ee_quat=quat
        )
        desired = c.compute(pos, quat, jac, q)[0]
        limits = torch.as_tensor(state["limits"][arm].copy(), device=device)
        values.append(np.r_[host(desired.clamp(limits[:, 0], limits[:, 1])), aperture])
    return command9(values)


def run(env, args, app, **kwargs):
    canonical_report = args.report
    del args, app, kwargs
    import torch
    import warp as wp
    import h5py
    import omni.physics.tensors as tensors
    from pxr import UsdGeom, UsdPhysics
    from isaaclab.controllers import DifferentialIKController, DifferentialIKControllerCfg
    from isaac_s1_runtime import NativeBimanualTargets
    from isaac_vr_standalone_scene import build_seed
    from isaac_vr_standalone_ik import piper_ik_state
    from compare_physics import compare

    out = Path(os.environ["PHYSICS_PAIR_OUTPUT"])
    out.mkdir(parents=True, exist_ok=True)
    result = dict(
        schema="physics_pair_assay_v1",
        physical=False,
        dataset_admissible=False,
        physics_parity_accepted=False,
        master_source=MASTER,
        source_head=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        cases=[],
    )
    save_json(out / "result.json", result)
    try:
        for rel in CORE:
            expected = subprocess.check_output(["git", "show", f"{MASTER}:{rel}"], cwd=REPO)
            if (REPO / rel).read_bytes() != expected:
                raise RuntimeError(f"Master core changed: {rel}")
        result["source_pins"] = {str(REPO / rel): sha(REPO / rel) for rel in CORE}
        result["source_pins"].update(
            {
                str(p): sha(p)
                for p in (
                    *Path(__file__).parent.glob("*.py"),
                    REPO / "tools/isaac_vr_standalone_worker.py",
                    REPO / "tools/isaac_vr_standalone_scene.py",
                    REPO / "tools/isaac_vr_standalone_ik.py",
                )
            }
        )
        replay = Path(os.environ["PHYSICS_PAIR_REPLAY"])
        with h5py.File(replay) as f:
            group = f["episodes/episode_00000/d0/committed_transition"]
            if not np.all(group["committed"][...]):
                raise RuntimeError("Replay includes uncommitted input")
            recorded = np.asarray([command9(x) for x in group["native_clipped"][...]], np.float32)
        result["replay_input"] = dict(
            path=str(replay), sha256=sha(replay), rows=len(recorded), field="native_clipped"
        )
        sim_view = tensors.create_simulation_view("torch")
        rigid_paths = [
            str(p.GetPath()) for p in env.sim.stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)
        ]
        contact = sim_view.create_rigid_contact_view(rigid_paths)
        gpu_sensors = list(contact.sensor_paths)
        selected = os.environ.get(
            "PHYSICS_PAIR_CASES",
            "home_hold,joint_plus5,joint_minus5,gripper_open_close,drop,blocked_gripper,recorded08,closedloop_reach",
        ).split(",")
        allowed = {
            "home_hold",
            "joint_plus5",
            "joint_minus5",
            "gripper_open_close",
            "drop",
            "blocked_gripper",
            "recorded08",
            "closedloop_reach",
        }
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= allowed:
            raise ValueError("Unknown or duplicate physics assay case")
        for case in selected:
            print("[PAIR] start " + case, flush=True)
            folder = out / case
            folder.mkdir(exist_ok=False)
            env.reset(0)
            # Diagnostic fixture placement; native state writes do not advance time.
            if case in ("drop", "blocked_gripper"):
                cube = env.vr_runtime.dynamic_assets[0]
                pose = host(cube.root_view.get_transforms())
                if case == "drop":
                    pose[0, :3] = [1.10, 0.40, 1.12]
                else:
                    opened = np.asarray(env.home_d0, np.float32).reshape(2, 7)
                    opened[:, :6] *= np.pi / 180
                    opened[:, 6] = 0.08
                    env._set_state(NativeBimanualTargets(opened[0], opened[1], False))
                    env._advance(8)
                    link = host(env.robots[0].root_view.get_link_transforms())[0]
                    # Collision-bound center transformed by authoritative link pose.
                    centers = []
                    cache = UsdGeom.BBoxCache(0, [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
                    for index in (10, 11):
                        path = str(env.robots[0].root_view.link_paths[0][index])
                        prim = env.sim.stage.GetPrimAtPath(path)
                        collider = (
                            next(p for p in prim.GetChildren() if p.HasAPI(UsdPhysics.CollisionAPI))
                            if any(p.HasAPI(UsdPhysics.CollisionAPI) for p in prim.GetChildren())
                            else prim
                        )
                        local = np.asarray(
                            cache.ComputeRelativeBound(collider, prim).ComputeCentroid(), np.float32
                        )
                        from compare_physics import quaternion_rotate

                        centers.append(link[index, :3] + quaternion_rotate(link[index, 3:], local))
                    pose[0, :3] = np.mean(centers, axis=0)
                    pose[0, 3:] = link[8, 3:]
                index = wp.array([0], device=env.sim.device, dtype=wp.uint32)
                cube.root_view.set_transforms(
                    wp.array(pose, dtype=wp.float32, device=env.sim.device), index
                )
                cube.root_view.set_velocities(
                    wp.zeros((1, 6), dtype=wp.float32, device=env.sim.device), index
                )
            snapshot = folder / "stage_snapshot.usd"
            env.sim.stage.Export(str(snapshot))
            seed = build_seed(env, snapshot, folder / "physics")
            seed["capture_diagnostics"] = True
            save_json(folder / "physics/seed.json", seed)
            seed_file = folder / "physics/seed.json"
            initial_target = np.asarray(seed["initial"]["position_target"], np.float32)
            controls = 960 if case == "recorded08" else 240 if case == "closedloop_reach" else 120
            targets = np.tile(initial_target, (controls, 1, 1))
            if case.startswith("joint_"):
                targets[10:, :, 0] += (1 if case == "joint_plus5" else -1) * np.pi / 36
            if case == "gripper_open_close":
                targets[10:60, :, 6] = 0.08
                targets[60:, :, 6] = 0.02
            if case == "blocked_gripper":
                targets[5:, :, 6] = 0
            if case == "recorded08":
                targets = recorded.copy()
            targets[:, :, 7] = 0.5 * targets[:, :, 6]
            targets[:, :, 8] = -0.5 * targets[:, :, 6]
            intents = np.zeros((controls, 2, 6), np.float32)
            if case == "closedloop_reach":
                for start, axis, value in [
                    (10, 2, -0.0005),
                    (60, 0, 0.0005),
                    (110, 2, 0.0005),
                    (160, 0, -0.0005),
                ]:
                    intents[start : start + 40, :, axis] = value
            np.savez(folder / "inputs.npz", native_targets=targets, cartesian_intents=intents)
            parent, child = socket.socketpair()
            log = (folder / "physics/worker.log").open("w")
            process = subprocess.Popen(
                [
                    os.environ["PHYSICS_PAIR_WORKER_PYTHON"],
                    str(REPO / "tools/isaac_vr_standalone_worker.py"),
                    "--fd",
                    str(child.fileno()),
                    "--seed",
                    str(seed_file),
                    "--receipt",
                    str(folder / "physics/worker.json"),
                ],
                pass_fds=(child.fileno(),),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            child.close()
            conn = Connection(parent.detach())

            def receive():
                if not conn.poll(30):
                    raise RuntimeError("CPU worker timeout")
                reply = conn.recv()
                if reply["op"] == "error":
                    raise RuntimeError(reply)
                return reply

            try:
                ready = receive()
                if ready["op"] != "ready":
                    raise RuntimeError(ready)
                cpu_sensors = ready["diagnostic_properties"]["contact_sensor_paths"]
                gpu_props = properties_gpu(env)
                cpu_props = properties_cpu(ready["diagnostic_properties"])
                save_json(
                    folder / "initial_native_metadata.json",
                    dict(
                        seed=seed,
                        gpu_properties=gpu_props,
                        cpu_properties=cpu_props,
                        cpu_ready={k: v for k, v in ready.items() if k != "snapshot"},
                        gpu_sensor_paths=gpu_sensors,
                    ),
                )
                initial_gpu = gpu_snapshot(env, contact)
                initial_cpu = cpu_snapshot(ready["snapshot"])
                if not np.allclose(initial_gpu["q"], initial_cpu["q"], atol=2e-5, rtol=0):
                    raise RuntimeError("Initial q differs")
                if not np.allclose(initial_gpu["dq"], initial_cpu["dq"], atol=2e-5, rtol=0):
                    raise RuntimeError("Initial dq differs")
                for backend in ("gpu", "cpu"):
                    trace = []
                    started = time.perf_counter()
                    state = initial_gpu if backend == "gpu" else initial_cpu
                    gpu_start_step = int(env.sim.get_physics_step_count())
                    sensors = gpu_sensors if backend == "gpu" else cpu_sensors
                    props = gpu_props if backend == "gpu" else cpu_props
                    capture(
                        trace,
                        state,
                        0,
                        -1,
                        initial_target,
                        started,
                        seed["rigid_body_paths"],
                        sensors,
                        intents[0] if case == "closedloop_reach" else None,
                    )
                    controllers = [
                        DifferentialIKController(
                            DifferentialIKControllerCfg(
                                command_type="pose", use_relative_mode=True, ik_method="dls"
                            ),
                            num_envs=1,
                            device=env.sim.device,
                        )
                        for _ in range(2)
                    ]
                    limits = np.asarray(seed["dof_properties"]["limits"], np.float32)
                    for arm, c in enumerate(controllers):
                        c.set_joint_pos_limits(
                            torch.as_tensor(limits[arm, :6, 0], device=env.sim.device),
                            torch.as_tensor(limits[arm, :6, 1], device=env.sim.device),
                        )
                    for seq in range(controls):
                        target = targets[seq].copy()
                        if case == "closedloop_reach":
                            com = (
                                ready["snapshot"]["articulation_body_com_local_pose"]
                                if backend == "cpu"
                                else np.stack([host(r.root_view.get_coms())[0] for r in env.robots])
                            )
                            ik = piper_ik_state(
                                q=state["q"],
                                link_poses_xyzw=state["body_pose"][:24].reshape(2, 12, 7),
                                com_poses_xyzw=com,
                                jacobian_com=state["jacobian"].reshape(2, 66, 9),
                                limits=limits,
                                body_names=seed["body_names"],
                                dof_names=seed["dof_names"],
                                fixed_base=True,
                            )
                            target = solve(controllers, ik, intents[seq], 0.05, env.sim.device)
                        if backend == "gpu":
                            env._apply(NativeBimanualTargets(target[0, :7], target[1, :7], False))
                            env._advance(4)
                            if (
                                int(env.sim.get_physics_step_count()) - gpu_start_step
                                != (seq + 1) * 4
                            ):
                                raise RuntimeError("GPU native causal steps differ")
                            state = gpu_snapshot(env, contact)
                        else:
                            conn.send(dict(op="step", seq=seq, native_targets=target))
                            reply = receive()
                            if (
                                reply["op"] != "captured"
                                or reply["snapshot"]["physics_steps"] != (seq + 1) * 4
                            ):
                                raise RuntimeError("CPU causal steps differ")
                            state = cpu_snapshot(reply["snapshot"])
                        capture(
                            trace,
                            state,
                            (seq + 1) * 4,
                            seq,
                            target,
                            started,
                            seed["rigid_body_paths"],
                            sensors,
                            intents[seq] if case == "closedloop_reach" else None,
                        )
                    arrays = {name: np.asarray([row[name] for row in trace]) for name in trace[0]}
                    np.savez(folder / (backend + ".npz"), **arrays)
                    meta = dict(
                        schema="physics_pair_trace_v1",
                        case=case,
                        input_kind="cartesian_intents"
                        if case == "closedloop_reach"
                        else "native_targets",
                        seed_sha256=sha(seed_file),
                        physics_dt_s=1 / 120,
                        body_paths=seed["rigid_body_paths"],
                        dof_names=seed["dof_names"],
                        body_names=seed["body_names"],
                        pose_quaternion_order="xyzw",
                        velocity_reference="COM",
                        jacobian_reference="COM",
                        contact_sample_scope="last_1_120_substep_of_each_four_step_control",
                        contact_observed_body_mask=[p in sensors for p in seed["rigid_body_paths"]],
                        unavailable=[
                            "direct prop contact sensors",
                            "per-substep intermediate transitions",
                            "measured solver PD efforts",
                        ],
                        backend=backend,
                        source_pins=result["source_pins"],
                        inputs_sha256=sha(folder / "inputs.npz"),
                        **props,
                    )
                    meta["physics_step_count_verified_natively"] = True
                    meta["closedloop_controller_device"] = (
                        str(env.sim.device) if case == "closedloop_reach" else None
                    )
                    save_json(folder / (backend + ".meta.json"), meta)
                conn.send(dict(op="close"))
                receive()
                process.wait(timeout=10)
                comparison = compare(folder / "gpu.npz", folder / "cpu.npz")
                save_json(folder / "comparison.json", comparison)
                if comparison["structural_status"] != "PASS":
                    raise RuntimeError(comparison["structural_errors"])
                result["cases"].append(
                    dict(
                        case=case,
                        controls=controls,
                        comparison=str(folder / "comparison.json"),
                        numerical_differences=comparison["numerical_differences"],
                    )
                )
                save_json(out / "result.json", result)
                print("[PAIR] completed " + case, flush=True)
            finally:
                conn.close()
                if process.poll() is None:
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        process.wait(timeout=10)
                log.close()
        result["completed"] = True
        return 0
    except BaseException as exc:
        result["error"] = repr(exc)
        raise
    finally:
        # Canonical launcher treats a missing child report as launch failure.
        # This is a diagnostic receipt, never a task/physics qualification.
        persist_results(out, canonical_report, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument(
        "--cases",
        default="home_hold,joint_plus5,joint_minus5,gripper_open_close,drop,blocked_gripper,recorded08,closedloop_reach",
    )
    args = parser.parse_args()
    environment = os.environ.copy()
    # Preserve virtualenv interpreter path: resolving its symlink loses the venv.
    environment.update(
        PHYSICS_PAIR_OUTPUT=str(args.output.resolve()),
        PHYSICS_PAIR_WORKER_PYTHON=str(args.worker_python.absolute()),
        PHYSICS_PAIR_REPLAY=str(args.replay.resolve()),
        PHYSICS_PAIR_CASES=args.cases,
        PYTHONPATH=str(Path(__file__).parent),
        DISPLAY=environment.get("DISPLAY", ":0"),
    )
    command = [
        "./run-vr",
        "--smoke",
        "--max-control-steps",
        "1",
        "--state-root",
        str(args.state_root or args.output / "state"),
    ]
    return subprocess.run(command, cwd=REPO, env=environment, check=False, timeout=850).returncode


if __name__ == "__main__":
    raise SystemExit(main())
