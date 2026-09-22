"""Content-sensitive LIVE-MIN deferred-camera qualification."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import statistics
import time

import numpy as np

from deferred_binding import (
    CameraExtractionIdentity,
    OneTickDeferredBinder,
    RenderSourceIdentity,
    ROLES,
)


def _host(value):
    value = getattr(value, "torch", value)
    return value.detach().cpu().numpy().copy()


def _material(stage, path, color):
    from pxr import Gf, Sdf, UsdShade

    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, path + "/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
        Gf.Vec3f(*(min(1.0, float(value)) for value in color))
    )
    shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return material


def _percentiles(values):
    return {
        "samples": len(values),
        "mean_ms": statistics.mean(values),
        "stddev_ms": statistics.stdev(values) if len(values) > 1 else 0.0,
        "cv": statistics.stdev(values) / statistics.mean(values) if len(values) > 1 else 0.0,
        **{f"p{label}_ms": float(np.percentile(values, q)) for label, q in
           (("50", 50), ("90", 90), ("95", 95), ("99", 99), ("99_9", 99.9))},
        "max_ms": max(values),
    }


def qualify(
    env,
    out: Path,
    boundaries: int,
    *,
    characterize: bool = False,
    priming_renders: int = 2,
) -> None:
    from pxr import UsdGeom, UsdPhysics, UsdShade
    import omni.kit.app
    import torch
    from isaac_s1_runtime import quaternion_xyzw_to_matrix

    if boundaries < 1:
        raise ValueError("deferred qualification requires at least one boundary")
    if priming_renders not in range(5):
        raise ValueError("priming renders must be in [0, 4]")
    out.mkdir(parents=True, exist_ok=True)
    stage = env.sim.stage
    physics_hz = int(round(1.0 / float(env.sim.cfg.dt)))
    physics_steps = physics_hz // 30
    state_slots = 4 if characterize else 3
    candidate = os.environ["VR_BAKEOFF_CANDIDATE"]
    batched = candidate == "LIVE-MIN120-BATCHED"
    if (physics_hz, physics_steps) not in ((60, 2), (120, 4)):
        raise RuntimeError(f"Unsupported deferred runtime {physics_hz} Hz/{physics_steps} steps")
    cameras = env.camera.capture.cameras
    robots = env.robots
    cubes = env.vr_runtime.dynamic_assets
    if len(robots) != 2 or len(cubes) < 2 or tuple(cameras) != ROLES:
        raise RuntimeError("Deferred probe requires the selected bimanual/two-cube/three-camera scene")
    batched_ownership = None
    if batched:
        from batched_camera import ownership

        batched_ownership = ownership(env)
        (out / "batched-ownership.json").write_text(
            json.dumps(batched_ownership, indent=2) + "\n"
        )

    # Native witnesses: one existing moving finger mesh and both existing PhysX cubes.
    links = [
        prim for prim in stage.Traverse()
        if prim.GetName() == "gripper_link1" and prim.HasAPI(UsdPhysics.RigidBodyAPI)
        and str(prim.GetPath()).startswith(robots[0].cfg.prim_path)
    ]
    if len(links) != 1:
        raise RuntimeError("Cannot resolve the left robot articulation witness")
    link = links[0]
    visual = next(
        prim for prim in stage.Traverse()
        if prim.GetName() == "gripper_link1"
        and prim != link
        and prim.GetPath().HasPrefix(link.GetPath())
    )
    articulation_body_id = robots[0].find_bodies("gripper_link1")[0][0]
    bounds = UsdGeom.BBoxCache(0, [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    articulation_offset = np.asarray(bounds.ComputeRelativeBound(visual, link).ComputeCentroid(), dtype=float)
    UsdShade.MaterialBindingAPI.Apply(visual).Bind(
        _material(stage, "/World/DeferredArticulationMaterial", (8, 0, 8)),
        UsdShade.Tokens.strongerThanDescendants,
    )
    left_cube_prim = stage.GetPrimAtPath(cubes[0].cfg.prim_path)
    if characterize:
        UsdPhysics.RigidBodyAPI(left_cube_prim).CreateKinematicEnabledAttr().Set(True)
    UsdShade.MaterialBindingAPI.Apply(left_cube_prim).Bind(
        _material(stage, "/World/DeferredLeftCubeMaterial", (0, 8, 8)),
        UsdShade.Tokens.strongerThanDescendants,
    )
    right_cube_prim = stage.GetPrimAtPath(cubes[1].cfg.prim_path)
    if characterize:
        UsdPhysics.RigidBodyAPI(right_cube_prim).CreateKinematicEnabledAttr().Set(True)
    UsdShade.MaterialBindingAPI.Apply(right_cube_prim).Bind(
        _material(stage, "/World/DeferredRightCubeMaterial", (8, 8, 0)),
        UsdShade.Tokens.strongerThanDescendants,
    )

    initial_q = [_host(robot.data.joint_pos) for robot in robots]
    initial_cube = [_host(cube.data.root_link_pose_w) for cube in cubes[:2]]
    requested_state = 0

    def apply_state(state_id: int) -> None:
        apertures = (0.0, 0.033, 0.067, 0.10) if characterize else (0.0, 0.05, 0.10)
        state_slot = state_id % state_slots
        aperture = apertures[state_slot]
        for side, (robot, q0) in enumerate(zip(robots, initial_q, strict=True)):
            q = q0.copy()
            arm_deg = (-40.0, 90.0, -50.0, 0.0, 0.0, 0.0)
            if side == 1:
                arm_deg = (40.0, 90.0, -50.0, 0.0, 0.0, 0.0)
            q[0, env.joint_ids[side][:-1]] = np.deg2rad(arm_deg)
            q[0, env.joint_ids[side][-1]] = aperture
            q[0, env.actuated_joint_ids[side][-2]] = 0.5 * aperture
            q[0, env.actuated_joint_ids[side][-1]] = -0.5 * aperture
            target = torch.as_tensor(q, device=env.sim.device)
            robot.write_joint_position_to_sim_index(position=target)
            robot.write_joint_velocity_to_sim_index(velocity=torch.zeros_like(target))
            robot.actuators.target_command.set_position_index(value=target)
            robot.write_data_to_sim()
        if characterize:
            # These kinematic PhysX witness poses are deliberately separated in
            # both wrist products. Kinematic mode prevents contact/gravity from
            # changing the commanded visual identity before it is rendered.
            cube_paths = (
                ((0.62, 0.17, 0.96), (0.62, 0.17, 1.01),
                 (0.62, 0.10, 1.01), (0.62, 0.10, 0.94)),
                ((0.62, -0.17, 0.92), (0.62, -0.17, 0.96),
                 (0.62, -0.10, 1.00), (0.62, -0.10, 0.93)),
            )
        else:
            cube_paths = (
                ((0.62, 0.17, 0.96), (0.62, 0.17, 1.01), (0.62, 0.10, 1.01)),
                ((0.62, -0.17, 0.92), (0.62, -0.17, 0.96), (0.62, -0.10, 1.00)),
            )
        for side, (cube, pose0) in enumerate(zip(cubes[:2], initial_cube, strict=True)):
            cube_x, cube_y, cube_z = cube_paths[side][state_slot]
            pose = pose0.copy()
            pose[0, :3] = [cube_x, cube_y, cube_z]
            cube.write_root_pose_to_sim_index(root_pose=torch.as_tensor(pose, device=env.sim.device))
            cube.write_root_velocity_to_sim_index(
                root_velocity=torch.zeros((1, 6), device=env.sim.device)
            )

    def witness_state(state_id: int, render_request_generation: int) -> dict:
        step, state = env.capture_measured_state()
        robot_pose = _host(robots[0].data.body_link_pose_w)[0, articulation_body_id]
        articulation = robot_pose[:3] + quaternion_xyzw_to_matrix(robot_pose[3:]) @ articulation_offset
        camera_poses = {}
        for role, camera in cameras.items():
            camera_poses[role] = {
                "position": _host(camera.data.pos_w)[0].tolist(),
                "quaternion_xyzw": _host(camera.data.quat_w_opengl)[0].tolist(),
                "intrinsic": _host(camera.data.intrinsic_matrices)[0].tolist(),
            }
        source = RenderSourceIdentity(
            state_id,
            state_id,
            env.camera.reset_epoch,
            0,
            0,
            step,
            step,
            render_request_generation,
        )
        return {
            "source": source,
            "state": tuple(state),
            "state_sha256": sha256(np.asarray(state, dtype="<f4").tobytes()).hexdigest(),
            "articulation": articulation.tolist(),
            "left_cube": _host(cubes[0].data.root_link_pose_w)[0, :3].tolist(),
            "right_cube": _host(cubes[1].data.root_link_pose_w)[0, :3].tolist(),
            "camera_poses": camera_poses,
        }

    def project(point, pose):
        position = np.asarray(pose["position"])
        rotation = quaternion_xyzw_to_matrix(np.asarray(pose["quaternion_xyzw"]))
        local = rotation.T @ (np.asarray(point) - position)
        intrinsic = np.asarray(pose["intrinsic"])
        if local[2] >= -1.0e-5:
            return None
        return [
            float(intrinsic[0, 0] * local[0] / -local[2] + intrinsic[0, 2]),
            float(intrinsic[1, 1] * -local[1] / -local[2] + intrinsic[1, 2]),
        ]

    primary_witness = {
        "left_wrist": "right_cube",
        "right_wrist": "left_cube",
        # The four-state characterization uses the always-visible left cube;
        # the existing qualification path retains its articulation witness.
        "scene": "left_cube" if characterize else "articulation",
    }
    area_references: dict[str, dict[int, int]] = {
        "left_wrist": {},
        "right_wrist": {},
        "scene": {},
    }
    center_references: dict[str, dict[int, list[float]]] = {
        "left_wrist": {},
        "right_wrist": {},
    }

    def classify_views(availability_state_id: int, owned_rgb: dict[str, np.ndarray]) -> tuple[dict, dict]:
        views = {}
        resolved_offsets = {}
        candidate_offsets = tuple(
            offset
            for offset in ((0, -1, -2, -3) if characterize else (0, -1, -2))
            if availability_state_id + offset >= 0
        )
        for role in ROLES:
            rgb = owned_rgb[role]
            array = rgb.astype(float)
            masks = {
                "articulation": (
                    (array[:, :, 0] > 170)
                    & (array[:, :, 2] > 170)
                    & (array[:, :, 1] < 120)
                ),
                "left_cube": (
                    (array[:, :, 1] > 170)
                    & (array[:, :, 2] > 170)
                    & (array[:, :, 0] < 120)
                ),
                "right_cube": (
                    (array[:, :, 0] > 170)
                    & (array[:, :, 1] > 170)
                    & (array[:, :, 2] < 120)
                ),
            }
            native = {}
            for kind, mask in masks.items():
                yy, xx = np.where(mask)
                minimum_pixels = 20 if characterize else 50
                observed = (
                    [float(xx.mean()), float(yy.mean())]
                    if len(xx) > minimum_pixels
                    else None
                )
                predictions = {}
                errors = {}
                for candidate_offset in candidate_offsets:
                    candidate = history[availability_state_id + candidate_offset]
                    # A moving wrist camera's depicted pose belongs to the same
                    # retained source boundary as its visible object content.
                    predicted = project(candidate[kind], candidate["camera_poses"][role])
                    predictions[str(candidate_offset)] = predicted
                    if observed is not None and predicted is not None:
                        errors[candidate_offset] = float(
                            np.linalg.norm(np.asarray(predicted) - observed)
                        )
                ordered = sorted(errors, key=errors.get)
                margin = (
                    errors[ordered[1]] - errors[ordered[0]] if len(ordered) > 1 else None
                )
                native[kind] = {
                    "pixels": int(mask.sum()),
                    "observed_center": observed,
                    "predicted_centers": predictions,
                    "errors_px": {str(key): value for key, value in errors.items()},
                    "best_offset": ordered[0] if ordered else None,
                    "separation_margin_px": margin,
                }
            witness = primary_witness[role]
            primary = native[witness]
            # A source association is accepted only when the expected native object
            # is visible and its nearest retained state is separated by >=5 px.
            resolved = primary["best_offset"]
            if primary["pixels"] <= 50 or (
                primary["separation_margin_px"] is not None
                and primary["separation_margin_px"] < 5.0
            ):
                resolved = "other"
            if role != "scene" and len(area_references[role]) == state_slots:
                reference_errors = {}
                if primary["observed_center"] is not None:
                    for offset in candidate_offsets:
                        source_mod = (availability_state_id + offset) % state_slots
                        center_error = np.linalg.norm(
                            np.asarray(primary["observed_center"])
                            - np.asarray(center_references[role][source_mod])
                        )
                        area_error = (
                            primary["pixels"] - area_references[role][source_mod]
                        ) / 100.0
                        reference_errors[offset] = float(
                            np.hypot(center_error, area_error)
                        )
                reference_order = sorted(reference_errors, key=reference_errors.get)
                reference_margin = (
                    reference_errors[reference_order[1]]
                    - reference_errors[reference_order[0]]
                    if len(reference_order) > 1
                    else None
                )
                primary["reference_feature_errors"] = {
                    str(key): value for key, value in reference_errors.items()
                }
                primary["reference_feature_separation"] = reference_margin
                resolved = reference_order[0] if reference_order else "other"
                if primary["pixels"] <= 50 or (
                    reference_margin is not None and reference_margin < 5.0
                ):
                    resolved = "other"
            elif role == "scene" and len(area_references[role]) == state_slots:
                reference_errors = {
                    offset: abs(
                        primary["pixels"]
                        - area_references[role][
                            (availability_state_id + offset) % state_slots
                        ]
                    )
                    for offset in candidate_offsets
                }
                reference_order = sorted(reference_errors, key=reference_errors.get)
                reference_margin = (
                    reference_errors[reference_order[1]]
                    - reference_errors[reference_order[0]]
                    if len(reference_order) > 1
                    else None
                )
                primary["reference_area_errors_px"] = {
                    str(key): value for key, value in reference_errors.items()
                }
                primary["reference_area_separation_px"] = reference_margin
                resolved = reference_order[0] if reference_order else "other"
                if primary["pixels"] <= 50 or (
                    reference_margin is not None and reference_margin < 25
                ):
                    resolved = "other"
            resolved_offsets[role] = resolved
            views[role] = {
                "source_witness": witness,
                "offset": resolved,
                "rgb_sha256": sha256(rgb.tobytes()).hexdigest(),
                "native": native,
            }
        return views, resolved_offsets

    def render_extract():
        before = env.sim.render_generation
        app_before = app_updates[0]
        env.vr_runtime.before_render()
        env.sim.render()
        render_after = env.sim.render_generation
        env.camera.capture_boundary(env)
        capture = env.latest_observation_capture()
        frozen = env.camera.capture.freeze()
        rgb = {role: frozen[f"observation.images.{role}"] for role in ROLES}
        identities = tuple(
            CameraExtractionIdentity(item.role, item.frame, item.data_generation, capture.capture_cycle)
            for item in capture.cameras
        )
        return {
            "render_before": before,
            "render_after": render_after,
            "app_updates": app_updates[0] - app_before,
            "capture": capture,
            "rgb": rgb,
            "camera_identities": identities,
        }

    app_updates = [0]
    subscription = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(
        lambda _event: app_updates.__setitem__(0, app_updates[0] + 1)
    )
    binder = OneTickDeferredBinder()
    original_step = env.sim.step
    rows = []
    calibration_rows = []
    history = {}
    control_ms = []
    binding_ms = []
    failure = None
    prime_started = time.perf_counter_ns()
    prime_physics = env.sim.get_physics_step_count()
    dynamic_role_support = None
    if batched:
        def apply_dynamic_arms(left_joint1: float, right_joint1: float) -> None:
            for side, (robot, q0, joint1) in enumerate(
                zip(robots, initial_q, (left_joint1, right_joint1), strict=True)
            ):
                q = q0.copy()
                arm_deg = (joint1, 90.0, -50.0, 0.0, 0.0, 0.0)
                q[0, env.joint_ids[side][:-1]] = np.deg2rad(arm_deg)
                q[0, env.joint_ids[side][-1]] = 0.05
                q[0, env.actuated_joint_ids[side][-2]] = 0.025
                q[0, env.actuated_joint_ids[side][-1]] = -0.025
                target = torch.as_tensor(q, device=env.sim.device)
                robot.write_joint_position_to_sim_index(position=target)
                robot.write_joint_velocity_to_sim_index(velocity=torch.zeros_like(target))
                robot.actuators.target_command.set_position_index(value=target)
                robot.write_data_to_sim()
            env.sim.forward()
            for robot in robots:
                robot.update(0.0)

        def dynamic_sample(left_joint1: float, right_joint1: float) -> dict:
            apply_dynamic_arms(left_joint1, right_joint1)
            rendered = None
            for _ in range(2):
                rendered = render_extract()
            return {
                "poses": {
                    role: {
                        "position": _host(camera.data.pos_w)[0].tolist(),
                        "quaternion_xyzw": _host(camera.data.quat_w_opengl)[0].tolist(),
                    }
                    for role, camera in cameras.items()
                },
                "rgb": rendered["rgb"],
            }

        dynamic_physics = env.sim.get_physics_step_count()
        dynamic_samples = {
            "baseline": dynamic_sample(-40.0, 40.0),
            "left_only": dynamic_sample(-34.0, 40.0),
            "right_only": dynamic_sample(-40.0, 34.0),
            "both": dynamic_sample(-34.0, 34.0),
        }
        baseline = dynamic_samples["baseline"]
        dynamic_role_support = {
            "physics_before": dynamic_physics,
            "physics_after": env.sim.get_physics_step_count(),
            "renders_per_pose": 2,
            "role_paths": {role: camera.path for role, camera in cameras.items()},
            "phases": {},
        }
        for phase in ("left_only", "right_only", "both"):
            sample = dynamic_samples[phase]
            dynamic_role_support["phases"][phase] = {
                role: {
                    "camera_position_delta_m": float(np.linalg.norm(
                        np.asarray(sample["poses"][role]["position"])
                        - np.asarray(baseline["poses"][role]["position"])
                    )),
                    "rgb_mean_absolute_delta": float(np.abs(
                        sample["rgb"][role].astype(np.float32)
                        - baseline["rgb"][role].astype(np.float32)
                    ).mean()),
                }
                for role in ROLES
            }
        phases = dynamic_role_support["phases"]
        dynamic_role_support["passed"] = bool(
            dynamic_role_support["physics_before"] == dynamic_role_support["physics_after"]
            and phases["left_only"]["left_wrist"]["camera_position_delta_m"] > 1.0e-3
            and phases["left_only"]["right_wrist"]["camera_position_delta_m"] < 1.0e-5
            and phases["right_only"]["right_wrist"]["camera_position_delta_m"] > 1.0e-3
            and phases["right_only"]["left_wrist"]["camera_position_delta_m"] < 1.0e-5
            and phases["both"]["left_wrist"]["camera_position_delta_m"] > 1.0e-3
            and phases["both"]["right_wrist"]["camera_position_delta_m"] > 1.0e-3
            and max(
                phases[phase]["scene"]["camera_position_delta_m"]
                for phase in phases
            ) < 1.0e-6
            and all(
                phases[phase][role]["rgb_mean_absolute_delta"] > 0.01
                for phase in phases
                for role in ROLES
            )
        )
        if not dynamic_role_support["passed"]:
            failure = "batched_dynamic_role_semantics_failed"
    apply_state(0)
    env.sim.forward()
    for robot in robots:
        robot.update(0.0)
    for cube in cubes[:2]:
        cube.update(0.0)
    prime_frames = [render_extract() for _ in range(priming_renders)]
    history[0] = witness_state(0, env.sim.render_generation)
    if not characterize:
        binder.prepare(history[0]["source"], history[0]["state"])
    prime_result = {
        "renders": priming_renders,
        "discarded_frame_bundles": priming_renders,
        "physics_before": prime_physics,
        "physics_after": env.sim.get_physics_step_count(),
        "cost_ms": (time.perf_counter_ns() - prime_started) / 1.0e6,
        "discarded_rgb_sha256": {
            role: [sha256(frame["rgb"][role].tobytes()).hexdigest() for frame in prime_frames]
            for role in ROLES
        },
    }

    def step(*args, **kwargs):
        apply_state(requested_state)
        return original_step(*args, **kwargs)

    env.sim.step = step
    calibration_boundaries = 0 if characterize else 30
    try:
        for state_id in range(1, boundaries + calibration_boundaries + 1):
            requested_state = state_id
            started = time.perf_counter_ns()
            before_physics = env.sim.get_physics_step_count()
            before_render = env.sim.render_generation
            before_app = app_updates[0]
            env._advance(4)
            extracted = {
                "render_after": env.sim.render_generation,
                "app_updates": None,
                "capture": env.latest_observation_capture(),
                "rgb": env.camera.capture.freeze(),
            }
            elapsed_ms = (time.perf_counter_ns() - started) / 1.0e6
            if env.sim.get_physics_step_count() - before_physics != physics_steps:
                raise RuntimeError(
                    f"{candidate} qualification did not advance exactly {physics_steps} physics steps"
                )
            current = witness_state(state_id, env.sim.render_generation)
            history[state_id] = current
            camera_identities = tuple(
                CameraExtractionIdentity(item.role, item.frame, item.data_generation,
                                         extracted["capture"].capture_cycle)
                for item in extracted["capture"].cameras
            )
            owned_rgb = {
                role: extracted["rgb"][f"observation.images.{role}"] for role in ROLES
            }
            views, resolved_offsets = classify_views(state_id, owned_rgb)
            calibrating = state_id <= calibration_boundaries
            if calibrating:
                if state_id <= 2 and resolved_offsets["scene"] != -1:
                    failure = "calibration_scene_offset_unstable"
                source_mod = (state_id - 1) % state_slots
                for role in area_references:
                    witness = primary_witness[role]
                    native_witness = views[role]["native"][witness]
                    pixels = native_witness["pixels"]
                    area_references[role][source_mod] = pixels
                    if role in center_references:
                        if native_witness["observed_center"] is not None:
                            center_references[role][source_mod] = native_witness[
                                "observed_center"
                            ]
                if state_id == calibration_boundaries and failure is None:
                    if any(
                        len(references) != state_slots or min(references.values()) <= 50
                        for references in area_references.values()
                    ):
                        failure = "calibration_witness_not_visible"
                    if any(
                        len(references) != state_slots
                        for references in center_references.values()
                    ):
                        failure = failure or "calibration_witness_center_missing"
                    scene_areas = area_references["scene"]
                    if not all(
                        scene_areas[index] < scene_areas[index + 1]
                        for index in range(state_slots - 1)
                    ):
                        failure = "calibration_robot_area_nonmonotonic"
                    for role, references in center_references.items():
                        separations = [
                            float(np.hypot(
                                np.linalg.norm(
                                    np.asarray(references[left]) - np.asarray(references[right])
                                ),
                                (
                                    area_references[role][left]
                                    - area_references[role][right]
                                ) / 100.0,
                            ))
                            for left in range(state_slots)
                            for right in range(left + 1, state_slots)
                        ]
                        if min(separations) < 10:
                            failure = (
                                f"calibration_witness_features_ambiguous:{role}"
                            )
                observed_offset = -1
            elif characterize:
                observed_offset = None
            else:
                if len(set(resolved_offsets.values())) != 1:
                    failure = "camera_source_disagreement"
                observed_offset = (
                    next(iter(resolved_offsets.values())) if not failure else "other"
                )
                if observed_offset != -1:
                    failure = failure or "offset_unstable"
            bind_started = time.perf_counter_ns()
            if failure is None and not characterize:
                binder.complete(
                    observed_source=history[state_id - 1]["source"],
                    availability_control_tick=state_id,
                    availability_render_generation=env.sim.render_generation,
                    camera_identities=camera_identities,
                    rgb=owned_rgb,
                )
                binder.prepare(current["source"], current["state"])
            binding_elapsed_ms = (time.perf_counter_ns() - bind_started) / 1.0e6
            if not calibrating:
                control_ms.append(elapsed_ms)
                binding_ms.append(binding_elapsed_ms)
            row = {
                "availability_control_tick": state_id,
                "availability_physics_step": env.sim.get_physics_step_count(),
                "state_generation": current["source"].state_generation,
                "render_generation": env.sim.render_generation,
                "render_delta": env.sim.render_generation - before_render,
                "kit_update_delta": app_updates[0] - before_app,
                "capture_cycle": extracted["capture"].capture_cycle,
                "camera_identities": [asdict(item) for item in camera_identities],
                "resolved_offsets": resolved_offsets,
                "views": views,
                "control_ms": elapsed_ms,
                "binding_ms": binding_elapsed_ms,
                "calibration": calibrating,
            }
            (calibration_rows if calibrating else rows).append(row)
            if failure and not characterize:
                break
    finally:
        env.sim.step = original_step

    characterization = None
    if characterize and failure is None:
        reference_features = {role: {} for role in ROLES}
        reference_samples = {role: {} for role in ROLES}

        def feature(native, role):
            center = native[primary_witness[role]]["observed_center"]
            pixels = native[primary_witness[role]]["pixels"]
            minimum_pixels = 20 if role == "scene" else 50
            if center is None or pixels <= minimum_pixels:
                return None
            area_scale = 10.0 if role == "scene" else 100.0
            return np.asarray([center[0], center[1], pixels / area_scale], dtype=float)

        reference_physics = env.sim.get_physics_step_count()
        for slot in range(4):
            apply_state(slot)
            env.sim.forward()
            for robot in robots:
                robot.update(0.0)
            for cube in cubes[:2]:
                cube.update(0.0)
            samples = []
            for _ in range(4):
                rendered = render_extract()
                reference_views, _ = classify_views(slot, rendered["rgb"])
                samples.append(reference_views)
            for role in ROLES:
                values = [feature(sample[role]["native"], role) for sample in samples[-2:]]
                if any(value is None for value in values):
                    failure = f"reference_witness_not_visible:{role}:{slot}"
                    continue
                reference_samples[role][str(slot)] = [value.tolist() for value in values]
                reference_features[role][slot] = np.mean(values, axis=0)

        for row in rows:
            tick = row["availability_control_tick"]
            resolved = {}
            for role in ROLES:
                observed = feature(row["views"][role]["native"], role)
                errors = {}
                if observed is not None and len(reference_features[role]) == 4:
                    errors = {
                        offset: float(np.linalg.norm(
                            observed - reference_features[role][(tick + offset) % 4]
                        ))
                        for offset in (0, -1, -2, -3)
                        if tick + offset >= 0
                    }
                ordered = sorted(errors, key=errors.get)
                margin = errors[ordered[1]] - errors[ordered[0]] if len(ordered) > 1 else None
                offset = ordered[0] if ordered and margin is not None and margin >= 3.0 else "other"
                resolved[role] = offset
                row["views"][role]["offset"] = offset
                row["views"][role]["characterization_errors"] = {
                    str(key): value for key, value in errors.items()
                }
                row["views"][role]["characterization_separation"] = margin
            row["resolved_offsets"] = resolved

        timelines = {}
        stable_suffixes = {}
        first_stable = {}
        for role in ROLES:
            segments = []
            for row in rows:
                tick = row["availability_control_tick"]
                offset = row["resolved_offsets"][role]
                if segments and segments[-1]["offset"] == offset:
                    segments[-1]["end"] = tick
                    segments[-1]["count"] += 1
                else:
                    segments.append({"start": tick, "end": tick, "count": 1, "offset": offset})
            timelines[role] = segments
            suffix = segments[-1]["count"] if segments else 0
            stable_suffixes[role] = suffix
            first_stable[role] = segments[-1]["start"] if segments else None
        characterization = {
            "reference_render_count_per_state": 4,
            "reference_physics_before": reference_physics,
            "reference_physics_after": env.sim.get_physics_step_count(),
            "reference_features": {
                role: {str(slot): value.tolist() for slot, value in values.items()}
                for role, values in reference_features.items()
            },
            "reference_samples": reference_samples,
            "transition_timelines": timelines,
            "first_stable_boundary": first_stable,
            "longest_stable_suffix": stable_suffixes,
            "first_30_offsets": {
                role: [row["resolved_offsets"][role] for row in rows[:30]] for role in ROLES
            },
        }

        if batched and failure is None:
            disagreements = [
                row["availability_control_tick"]
                for row in rows
                if len(set(row["resolved_offsets"].values())) != 1
            ]
            common = [
                next(iter(row["resolved_offsets"].values()))
                for row in rows
                if len(set(row["resolved_offsets"].values())) == 1
            ]
            expected_offsets = set(common)
            if disagreements:
                failure = f"batched_camera_source_disagreement:{disagreements[0]}"
            elif len(common) != len(rows) or "other" in expected_offsets:
                failure = "batched_camera_unresolved_source"
            elif len(expected_offsets) != 1:
                failure = f"batched_camera_offset_unstable:{sorted(expected_offsets)}"
            characterization["batched_temporal_classification"] = {
                "common_offset": common[0] if common and len(expected_offsets) == 1 else None,
                "disagreement_ticks": disagreements,
                "all_boundaries_common": len(common) == len(rows),
                "stable_common_offset": len(expected_offsets) == 1 and "other" not in expected_offsets,
            }

            characterization["dynamic_role_support"] = dynamic_role_support

    drain = None
    if failure is None and (not characterize or batched):
        terminal_state = boundaries + calibration_boundaries
        drain_started = time.perf_counter_ns()
        drain_physics = env.sim.get_physics_step_count()
        apply_state(terminal_state)
        env.sim.forward()
        for robot in robots:
            robot.update(0.0)
        for cube in cubes[:2]:
            cube.update(0.0)
        drain_attempts = []
        drained = None
        drain_views = None
        drain_offsets = None
        for render_number in range(1, 5):
            drained = render_extract()
            drain_views, drain_offsets = classify_views(terminal_state, drained["rgb"])
            if characterize:
                resolved = {}
                for role in ROLES:
                    observed = feature(drain_views[role]["native"], role)
                    errors = {
                        offset: float(np.linalg.norm(
                            observed - reference_features[role][(terminal_state + offset) % 4]
                        ))
                        for offset in (0, -1, -2, -3)
                        if terminal_state + offset >= 0 and observed is not None
                    }
                    ordered = sorted(errors, key=errors.get)
                    margin = errors[ordered[1]] - errors[ordered[0]] if len(ordered) > 1 else None
                    resolved[role] = (
                        ordered[0] if ordered and margin is not None and margin >= 3.0 else "other"
                    )
                drain_offsets = resolved
            drain_attempts.append({"render": render_number, "resolved_offsets": drain_offsets})
            if all(offset == 0 for offset in drain_offsets.values()):
                break
        drain = {
            "renders": len(drain_attempts),
            "attempts": drain_attempts,
            "physics_before": drain_physics,
            "physics_after": env.sim.get_physics_step_count(),
            "state_preserved": env.sim.get_physics_step_count() == drain_physics,
            "resolved_offsets": drain_offsets,
            "views": drain_views,
            "all_cameras_match": all(offset == 0 for offset in drain_offsets.values()),
            "cost_ms": (time.perf_counter_ns() - drain_started) / 1.0e6,
        }
        if not drain["state_preserved"] or not drain["all_cameras_match"]:
            failure = "terminal_drain_unsafe"
        elif not characterize:
            binder.complete(
                observed_source=history[terminal_state]["source"],
                availability_control_tick=terminal_state,
                availability_render_generation=drained["render_after"],
                camera_identities=drained["camera_identities"],
                rgb=drained["rgb"],
                drain=True,
            )

    histograms = {
        role: dict(Counter(str(row["resolved_offsets"][role]) for row in rows)) for role in ROLES
    }
    native_summary = {}
    for kind in ("articulation", "left_cube", "right_cube"):
        native_summary[kind] = {}
        for role in ROLES:
            samples = [row["views"][role]["native"][kind] for row in rows]
            native_summary[kind][role] = {
                "minimum_visible_pixels": min((sample["pixels"] for sample in samples), default=0),
                "best_offset_counts": dict(Counter(sample["best_offset"] for sample in samples)),
            }
    result = {
        "schema": "piper_x_live_min_deferred_phase_v1",
        "requested_boundaries": boundaries,
        "checked_boundaries": len(rows),
        "calibration_boundaries": len(calibration_rows),
        "area_references": area_references,
        "center_references": center_references,
        "candidate": candidate,
        "batched_ownership": batched_ownership,
        "dynamic_role_support": dynamic_role_support,
        "runtime": {
            "physics_hz": physics_hz,
            "control_target_hz": 30,
            "physics_steps_per_control": physics_steps,
            "renders_per_control": 1,
            "renderer": "RTX Minimal mode 2",
            "xr_scale": 0.4,
            "camera_roles": list(ROLES),
            "camera_shape": [480, 640, 3],
            "preview_panels": False,
            "owned_rgb_freeze": True,
        },
        "priming": prime_result,
        "characterization": characterization,
        "offset_histograms": histograms,
        "native_witnesses": native_summary,
        "primary_witnesses": primary_witness,
        "usd_witness": "disabled: camera-child marker was absent in both wrist products",
        "control_timing": _percentiles(control_ms) if control_ms else None,
        "binding_timing": (
            None if characterize else (_percentiles(binding_ms) if binding_ms else None)
        ),
        "terminal_drain": drain,
        "failure": failure,
        "verdict": (
            "CHARACTERIZED"
            if characterize and failure is None
            else "STABLE ONE-CONTROL PIPELINE"
            if failure is None
            else "UNSTABLE / UNSAFE"
        ),
        "upstream_identity_limit": (
            "Camera frame/data generations identify extraction, not depicted simulation state; "
            "the content-sensitive native robot/cube witnesses supply source proof."
        ),
    }
    (out / "deferred-phase.json").write_text(
        json.dumps(
            {"result": result, "calibration_rows": calibration_rows, "rows": rows},
            indent=2,
        )
        + "\n"
    )
    (out / "deferred-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    del subscription
    if failure:
        raise RuntimeError(f"Deferred binding qualification failed: {failure}")


def install(env, args, out) -> None:
    """Run after the requested diagnostic controls while the Kit scene is alive."""
    from isaac_s2_performance import S2PerformanceLogger

    output = Path(out)
    characterization_boundaries = int(os.environ.get("VR_DEFERRED_CHARACTERIZE", "0"))
    characterize = characterization_boundaries > 0
    boundaries = (
        characterization_boundaries
        if characterize
        else int(os.environ.get("VR_DEFERRED_BOUNDARIES", "300"))
    )
    priming_renders = int(os.environ.get("VR_DEFERRED_PRIMES", "2"))
    previous_end = S2PerformanceLogger.end_step

    def end(log, number, **state):
        result = previous_end(log, number, **state)
        if number == args.s2_max_control_steps:
            S2PerformanceLogger.end_step = previous_end
            qualify(
                env,
                output,
                boundaries,
                characterize=characterize,
                priming_renders=priming_renders,
            )
        return result

    S2PerformanceLogger.end_step = end


def install_performance(env, args, out: Path) -> None:
    """Measure one-deep finalization inside the unchanged live control boundary."""
    import atexit

    output = Path(out)
    binder = OneTickDeferredBinder()
    previous_advance = env._advance
    control_tick = 0
    finalized = 0
    discarded = 0
    epoch_invalidations = []
    binding_ns = []
    previous_epoch = None
    session_epoch = 0
    previous_session_running = None

    def epoch() -> tuple[int, int, int]:
        nonlocal previous_session_running, session_epoch
        runtime = env.vr_runtime
        device = getattr(env, "_deferred_session_device", None)
        session_running = bool(device is not None and device.session_running)
        if previous_session_running is None:
            previous_session_running = session_running
        elif session_running != previous_session_running:
            session_epoch += 1
            previous_session_running = session_running
        return (
            int(env.camera.reset_epoch),
            int(runtime.recenter_scheduled_count),
            session_epoch,
        )

    def advance(repeat: int) -> None:
        nonlocal control_tick, discarded, finalized, previous_epoch
        if repeat != 4:
            return previous_advance(repeat)
        current_epoch = epoch()
        if previous_epoch is not None and current_epoch != previous_epoch and binder.pending is not None:
            binder.invalidate_epoch(
                "epoch_changed:"
                f"reset={previous_epoch[0]}->{current_epoch[0]},"
                f"reference={previous_epoch[1]}->{current_epoch[1]},"
                f"session={previous_epoch[2]}->{current_epoch[2]}"
            )
            epoch_invalidations.append(
                {"control_tick": control_tick + 1, "before": previous_epoch, "after": current_epoch}
            )
        previous_advance(repeat)
        control_tick += 1
        capture = env.latest_observation_capture()
        owned = env.camera.capture.freeze()
        rgb = {role: owned[f"observation.images.{role}"] for role in ROLES}
        camera_identities = tuple(
            CameraExtractionIdentity(
                item.role, item.frame, item.data_generation, capture.capture_cycle
            )
            for item in capture.cameras
        )
        started = time.perf_counter_ns()
        if binder.pending is None:
            discarded += 1
        else:
            binder.complete(
                observed_source=binder.pending.source,
                availability_control_tick=control_tick,
                availability_render_generation=env.sim.render_generation,
                camera_identities=camera_identities,
                rgb=rgb,
            )
            finalized += 1
        step, state = env.capture_measured_state()
        current_epoch = epoch()
        binder.prepare(
            RenderSourceIdentity(
                control_tick,
                control_tick,
                current_epoch[0],
                current_epoch[1],
                current_epoch[2],
                step,
                step,
                env.sim.render_generation,
            ),
            tuple(state),
        )
        elapsed = time.perf_counter_ns() - started
        binding_ns.append(elapsed)
        logger = getattr(env, "performance_logger", None)
        if logger is not None:
            logger.add_nested("deferred_binding_finalization", elapsed)
        previous_epoch = current_epoch
        if control_tick == args.s2_max_control_steps:
            write_result()

    def write_result() -> None:
        values = [value / 1.0e6 for value in binding_ns]
        result = {
            "schema": "piper_x_live_min60_deferred_performance_v1",
            "controls": control_tick,
            "finalized_observations": finalized,
            "discarded_pipeline_slots": discarded,
            "pending_at_shutdown": binder.pending.source.obs_id if binder.pending else None,
            "epoch_invalidations": epoch_invalidations,
            "binding_timing": _percentiles(values) if values else None,
            "bytes_per_finalized_observation": 2_764_800,
        }
        (output / "deferred-performance.json").write_text(json.dumps(result, indent=2) + "\n")

    env._advance = advance
    atexit.register(write_result)
