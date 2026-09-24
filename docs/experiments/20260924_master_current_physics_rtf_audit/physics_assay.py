"""Bounded native-state assay; imported only by sitecustomize in an Isaac child."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time

import numpy as np


DT = 1.0 / 120.0
TABLE_TOP = 0.825
CUBE_HALF_EDGE = 0.02


def _host(value):
    if isinstance(value, np.ndarray):
        return value
    if hasattr(value, "numpy"):
        return np.asarray(value.numpy())
    tensor = value.torch if hasattr(value, "torch") else value
    return tensor.detach().cpu().numpy()


def _plain(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    try:
        return [_plain(item) for item in value]
    except TypeError:
        return str(value)


def _usd_prim(prim):
    if not prim or not prim.IsValid():
        return None
    attributes = {}
    for attr in prim.GetAttributes():
        name = attr.GetName()
        if name.startswith(("physics:", "physx")):
            try:
                attributes[name] = _plain(attr.Get())
            except Exception as exc:
                attributes[name] = {"read_error": str(exc)}
    relationships = {}
    for rel in prim.GetRelationships():
        name = rel.GetName()
        if name.startswith(("physics:", "physx", "material:")):
            relationships[name] = [str(item) for item in rel.GetTargets()]
    return {"path": str(prim.GetPath()), "type": prim.GetTypeName(), "attributes": attributes,
            "relationships": relationships, "api_schemas": list(prim.GetAppliedSchemas())}


def _runtime_snapshot(env):
    stage = env.sim.stage
    selected = {}
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if path.startswith(("/World/RobosynDemo/LeftCube", "/World/RobosynDemo/RightCube",
                            "/World/RobosynDemo/Table", "/World/LeftPiper", "/World/RightPiper")):
            snap = _usd_prim(prim)
            if snap and (snap["attributes"] or snap["relationships"] or "Joint" in snap["type"]):
                selected[path] = snap
    physics_scenes = [_usd_prim(prim) for prim in stage.Traverse()
                      if prim.GetTypeName() == "PhysicsScene"]
    materials = [_usd_prim(prim) for prim in stage.Traverse()
                 if "Material" in prim.GetTypeName() and
                 any(a.GetName().startswith(("physics:", "physx")) for a in prim.GetAttributes())]
    def view_properties(view, names):
        properties = {}
        for name in names:
            method = getattr(view, name, None)
            if method is None:
                properties[name] = {"availability": "not_exposed"}
                continue
            try:
                properties[name] = _plain(_host(method()))
            except Exception as exc:
                properties[name] = {"read_error": str(exc)}
        return properties

    rigid_names = ("get_masses", "get_inertias", "get_coms", "get_linear_dampings",
                   "get_angular_dampings", "get_sleep_thresholds",
                   "get_max_depenetration_velocities", "get_contact_offsets", "get_rest_offsets")
    articulation_names = ("get_dof_stiffnesses", "get_dof_dampings", "get_dof_max_forces",
                          "get_dof_max_velocities", "get_dof_friction_coefficients",
                          "get_dof_armatures", "get_max_efforts", "get_dof_masses")
    views = {"cubes": [view_properties(asset.root_physx_view, rigid_names)
                       for asset in env.vr_runtime.dynamic_assets[:2]],
             "robots": [view_properties(robot.root_physx_view, articulation_names)
                        for robot in env.robots]}
    return {"physics_dt_s": env.sim.get_physics_dt(), "physics_scenes": physics_scenes,
            "physics_prims": selected, "physics_materials": materials,
            "physx_tensor_views": views,
            "robot_joint_names": [list(robot.joint_names) for robot in env.robots]}


def _root_state(asset):
    data = asset.data
    result = {"position_m": _host(data.root_pos_w)[0].tolist(),
              "linear_velocity_m_s": _host(data.root_lin_vel_w)[0].tolist(),
              "angular_velocity_rad_s": _host(data.root_ang_vel_w)[0].tolist()}
    if hasattr(data, "root_quat_w"):
        result["orientation_wxyz"] = _host(data.root_quat_w)[0].tolist()
    return result


def _set_cube(cube, xyz):
    pose = cube.data.default_root_pose.torch.clone()
    velocity = cube.data.default_root_vel.torch.clone()
    pose[0, :3] = pose.new_tensor(xyz)
    velocity.zero_()
    cube.write_root_pose_to_sim_index(root_pose=pose)
    cube.write_root_velocity_to_sim_index(root_velocity=velocity)
    cube.reset()
    cube.update(0.0)


def _sample(env, kind, sim_s, wall_s, target):
    cube = env.vr_runtime.dynamic_assets[0]
    robot = env.robots[0]
    joints = _host(robot.data.joint_pos)[0]
    velocities = _host(robot.data.joint_vel)[0]
    body_ids, names = robot.find_bodies("gripper_base", preserve_order=True)
    if names != ["gripper_base"]:
        raise RuntimeError(f"Expected gripper_base, found {names}")
    tcp = _host(robot.data.body_link_pose_w)[0, body_ids[0]].tolist()
    state = _root_state(cube)
    z = state["position_m"][2]
    return {"kind": kind, "sim_time_s": sim_s, "wall_time_s": wall_s,
            "physics_step": env.sim.get_physics_step_count(), "cube": state,
            "geometric_table_contact_proxy": bool(z <= TABLE_TOP + CUBE_HALF_EDGE + 0.001),
            "left_joint_position": joints.tolist(), "left_joint_velocity": velocities.tolist(),
            "joint_names": list(robot.joint_names), "tcp_pose_world": tcp,
            "target_d0": target.tolist()}


def _run_case(env, kind, repeat):
    from isaac_s1_runtime import d0_action_to_native

    env.reset(0)
    cube = env.vr_runtime.dynamic_assets[0]
    if kind == "free_fall":
        _set_cube(cube, (2.0, 0.0, 1.2))
        controls = 24
    elif kind == "bounce":
        # Table corner away from both grippers and the matching plates.
        _set_cube(cube, (1.10, 0.40, 1.12))
        controls = 90
    else:
        _set_cube(cube, (2.0, 0.0, 1.2))
        controls = 45
    target = env.home_d0.copy()
    if kind == "gripper":
        opened = target.copy()
        opened[[6, 13]] = 100.0
        env._set_state(d0_action_to_native(opened))
        env._advance(8)
        target[[6, 13]] = 0.0
    elif kind == "arm":
        target[0] += 10.0
    env._apply(d0_action_to_native(target))
    samples = []
    controls_log = []
    old_update = env.vr_runtime.update
    start_ns = time.perf_counter_ns()
    samples.append(_sample(env, kind, 0.0, 0.0, target))

    def capture(dt):
        old_update(dt)
        number = len(samples)
        samples.append(_sample(env, kind, number * DT,
                               (time.perf_counter_ns() - start_ns) / 1e9, target))

    env.vr_runtime.update = capture
    try:
        for control in range(controls):
            before = time.perf_counter_ns()
            env._advance(4)
            controls_log.append({"control": control + 1, "sim_time_s": (control + 1) / 30,
                                 "wall_time_s": (time.perf_counter_ns() - start_ns) / 1e9,
                                 "duration_s": (time.perf_counter_ns() - before) / 1e9})
    finally:
        env.vr_runtime.update = old_update
    if len(samples) != controls * 4 + 1:
        raise RuntimeError(f"Missing native physics samples: {kind} {len(samples)}")
    elapsed = controls_log[-1]["wall_time_s"]
    return {"case": kind, "repeat": repeat, "controls": controls_log, "samples": samples,
            "effective_control_hz": controls / elapsed,
            "effective_physics_hz": controls * 4 / elapsed,
            "rtf": controls / 30 / elapsed}


def _run_rate(env, repeat):
    """Measure cadence without per-substep GPU readback from the trajectory probe."""
    from isaac_s1_runtime import d0_action_to_native

    env.reset(0)
    env._apply(d0_action_to_native(env.home_d0))
    for _ in range(30):
        env._advance(4)
    started = time.perf_counter_ns()
    controls = []
    for control in range(300):
        env._advance(4)
        controls.append((time.perf_counter_ns() - started) / 1e9)
    elapsed = controls[-1]
    return {"repeat": repeat, "warmup_controls": 30, "measured_controls": 300,
            "control_boundary_wall_s": controls, "elapsed_wall_s": elapsed,
            "effective_control_hz": 300 / elapsed,
            "effective_physics_hz": 1200 / elapsed, "rtf": 10 / elapsed}


def run(env, args, app):
    output = Path(os.environ["PHYSICS_AUDIT_OUTPUT"])
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = os.environ["PHYSICS_AUDIT_CHECKPOINT"]
    if checkpoint == "current":
        from isaac_vr_camera_rendering import suspend_dataset_camera_rendering

        runtime = env.vr_runtime
        runtime.prepare_recording_view()
        cameras = dict(zip(("left_wrist", "right_wrist", "scene"),
                           (*runtime.camera_rig.wrists, runtime.camera_rig.scene_camera)))
        paths = {role: str(camera._view.prim_paths[0]) for role, camera in cameras.items()}
        suspend_dataset_camera_rendering(cameras, env.sim.stage, paths)
        env.render_only_final_substep = True
    elif checkpoint != "old":
        raise ValueError(checkpoint)
    snapshot = _runtime_snapshot(env)
    (output / f"runtime-{checkpoint}.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    if os.environ.get("PHYSICS_AUDIT_SNAPSHOT_ONLY") == "1":
        args.report.write_text(json.dumps({"experiment": True, "physical": False,
                                           "checkpoint": checkpoint, "snapshot_only": True}) + "\n")
        return 0
    result = {"checkpoint": checkpoint, "mode": "no_client_native_assay",
              "render_policy": "FFFT" if checkpoint == "current" else "TTTT",
              "repetitions": [], "rate_repetitions": []}
    kinds = os.environ.get("PHYSICS_AUDIT_CASES", "free_fall,bounce,gripper,arm").split(",")
    for kind in kinds:
        if kind not in {"free_fall", "bounce", "gripper", "arm"}:
            raise ValueError(f"Unknown assay: {kind}")
        for repeat in range(3):
            result["repetitions"].append(_run_case(env, kind, repeat))
            (output / f"samples-{checkpoint}.json").write_text(
                json.dumps(result, separators=(",", ":")) + "\n")
    if os.environ.get("PHYSICS_AUDIT_SKIP_RATE") != "1":
        result["rate_repetitions"].append(_run_rate(env, 0))
        (output / f"samples-{checkpoint}.json").write_text(
            json.dumps(result, separators=(",", ":")) + "\n")
    args.report.write_text(json.dumps({"experiment": True, "physical": False,
                                       "checkpoint": checkpoint, "assays_complete": True}) + "\n")
    return 0
