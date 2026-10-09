"""Compare paired native traces; structural checks do not accept physics parity.

Each NPZ has a companion <stem>.meta.json with schema physics_pair_trace_v1.
Required arrays: physics_step[T],sim_time_s[T],wall_time_s[T],q/dq/targets[T,2,9],
body_pose[T,27,7] (xyz+xyzw),action_seq[T]. Optional arrays: body_velocity[T,27,6]
(world COM), jacobian[T,2,11,6,9] (world COM),contact_net_force[T,27,3],
contact_impulse[T,27,3],cartesian_intents[T,2,6]. Metadata declares names,
physics_dt_s,input_kind,case,seed_sha256 and all unavailable observables.
The comparison never launches a simulator, renders, installs or changes state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def load(path):
    metadata = json.loads(path.with_suffix(".meta.json").read_text())
    with np.load(path, allow_pickle=False) as source:
        arrays = {name: source[name].copy() for name in source.files}
    return arrays, metadata


def structural(left, lm, right, rm):
    errors = []
    for key in (
        "schema",
        "case",
        "input_kind",
        "seed_sha256",
        "physics_dt_s",
        "body_paths",
        "dof_names",
        "body_names",
        "pose_quaternion_order",
    ):
        if key not in lm or key not in rm or lm[key] != rm[key]:
            errors.append(f"metadata differs/missing: {key}")
    if lm.get("schema") != "physics_pair_trace_v1" or lm.get("pose_quaternion_order") != "xyzw":
        errors.append("unsupported schema/quaternion order")
    shapes = {
        "q": (2, 9),
        "dq": (2, 9),
        "body_pose": (27, 7),
        "native_targets": (2, 9),
        "physics_step": (),
        "sim_time_s": (),
        "wall_time_s": (),
        "action_seq": (),
    }
    optional_shapes = {
        "body_velocity": (27, 6),
        "jacobian": (2, 11, 6, 9),
        "contact_net_force": (27, 3),
        "contact_impulse": (27, 3),
        "cartesian_intents": (2, 6),
    }
    for label, data, meta in [("left", left, lm), ("right", right, rm)]:
        count = len(data.get("physics_step", []))
        for name, tail in shapes.items():
            value = data.get(name)
            if value is None or value.shape != (count,) + tail or not np.isfinite(value).all():
                errors.append(f"{label}: invalid/missing {name}")
        for name, tail in optional_shapes.items():
            if name in data:
                observed = np.asarray(meta.get("contact_observed_body_mask", [True] * 27), bool)
                value = (
                    data[name][:, observed]
                    if name.startswith("contact_") and observed.shape == (27,)
                    else data[name]
                )
                if data[name].shape != (count,) + tail or not np.isfinite(value).all():
                    errors.append(f"{label}: malformed optional {name}")
        if (
            len(meta.get("body_paths", [])) != 27
            or len(meta.get("dof_names", [])) != 9
            or len(meta.get("body_names", [])) != 12
        ):
            errors.append(f"{label}: unexpected name/path inventory")
        if "body_velocity" in data and meta.get("velocity_reference") != "COM":
            errors.append(f"{label}: body velocity reference must be COM")
        if "jacobian" in data and meta.get("jacobian_reference") != "COM":
            errors.append(f"{label}: Jacobian reference must be COM")
        if any(k in data for k in ("contact_net_force", "contact_impulse")) and not meta.get(
            "contact_sample_scope"
        ):
            errors.append(f"{label}: contact sample scope missing")
        if any(e.startswith(label + ": invalid/missing") for e in errors):
            continue
        if count < 2:
            errors.append(f"{label}: fewer than two samples")
            continue
        steps = data["physics_step"]
        if (
            not np.issubdtype(steps.dtype, np.integer)
            or steps[0] != 0
            or (np.diff(steps) <= 0).any()
        ):
            errors.append(f"{label}: step order must start0 and increase")
        if not np.allclose(
            data["sim_time_s"], steps * meta.get("physics_dt_s", np.nan), atol=1e-10, rtol=0
        ):
            errors.append(f"{label}: simulation clock differs from step count")
        if (np.diff(data["wall_time_s"]) < 0).any():
            errors.append(f"{label}: wall clock reverses")
        if not np.allclose(
            np.linalg.norm(data["body_pose"][..., 3:], axis=-1), 1, atol=1e-4, rtol=0
        ):
            errors.append(f"{label}: body quaternion is nonunit")
    for key in ("physics_step", "action_seq"):
        if key not in left or key not in right or not np.array_equal(left[key], right[key]):
            errors.append(f"paired {key} differs")
    if any(k in left and k in right for k in ("contact_net_force", "contact_impulse")) and lm.get(
        "contact_sample_scope"
    ) != rm.get("contact_sample_scope"):
        errors.append("contact sample scopes differ")
    input_field = (
        "native_targets" if lm.get("input_kind") == "native_targets" else "cartesian_intents"
    )
    if (
        input_field not in left
        or input_field not in right
        or not np.array_equal(left[input_field], right[input_field])
    ):
        errors.append(f"paired input {input_field} differs")
    return errors


def differences(a, b):
    delta = np.asarray(a, np.float64) - np.asarray(b, np.float64)
    return dict(max_abs=float(np.abs(delta).max()), rms=float(np.sqrt(np.mean(delta * delta))))


def first_event(mask, trace):
    indices = np.flatnonzero(mask)
    if not len(indices):
        return None
    i = int(indices[0])
    return dict(
        sample=i,
        physics_step=int(trace["physics_step"][i]),
        sim_time_s=float(trace["sim_time_s"][i]),
        wall_time_s=float(trace["wall_time_s"][i]),
    )


def quaternion_rotate(q, v):
    t = 2 * np.cross(q[..., :3], v)
    return v + q[..., 3:] * t + np.cross(q[..., :3], t)


def step_response(data):
    """First target-change segment per joint; detector thresholds are reported."""
    result = []
    q, target, time = data["q"], data["native_targets"], data["sim_time_s"]
    for arm in range(2):
        for joint in range(9):
            changes = np.flatnonzero(np.abs(np.diff(target[:, arm, joint])) > 1e-8) + 1
            if not len(changes):
                continue
            start = int(changes[0])
            stop = int(changes[1]) if len(changes) > 1 else len(q)
            baseline = float(q[start - 1, arm, joint])
            goal = float(target[start, arm, joint])
            amplitude = goal - baseline
            if abs(amplitude) < 1e-8:
                continue
            progress = (q[start:stop, arm, joint] - baseline) / amplitude

            def crossing(level):
                return next(
                    (float(time[start + i]) for i, v in enumerate(progress) if v >= level), None
                )

            t10, t90 = crossing(0.1), crossing(0.9)
            band = max(1e-6, 0.02 * abs(amplitude))
            settle = None
            for i in range(start, stop):
                end = int(np.searchsorted(time, time[i] + 0.2, side="left"))
                if end < stop and np.abs(q[i : end + 1, arm, joint] - goal).max() <= band:
                    settle = float(time[i])
                    break
            result.append(
                dict(
                    arm=arm,
                    joint=joint,
                    unit="rad" if joint < 6 else "m",
                    command_sim_s=float(time[start - 1]),
                    first_postcommand_sample_sim_s=float(time[start]),
                    segment_end_sim_s=float(time[stop - 1]),
                    target=goal,
                    baseline=baseline,
                    t10_sim_s=t10,
                    t90_sim_s=t90,
                    rise10_90_s=None if t10 is None or t90 is None else t90 - t10,
                    overshoot_fraction=float(max(0, progress.max() - 1)),
                    settle_sim_s=settle,
                    settling_detector=dict(position_band=band, continuous_window_s=0.2),
                )
            )
    return result


def motion(data, meta):
    t = np.asarray(data["sim_time_s"], np.float64)
    q = np.asarray(data["q"], np.float64)
    poses = np.asarray(data["body_pose"], np.float64)
    position = poses[..., :3]
    result = dict(
        elapsed_sim_s=float(t[-1] - t[0]),
        elapsed_wall_s=float(data["wall_time_s"][-1] - data["wall_time_s"][0]),
        joint_travel=np.abs(np.diff(q, axis=0)).sum(axis=0).tolist(),
        joint_excursion=np.ptp(q, axis=0).tolist(),
        peak_joint_speed=np.abs(data["dq"]).max(axis=0).tolist(),
        peak_joint_acceleration_control_window=(
            np.abs(np.diff(data["dq"], axis=0) / np.diff(t)[:, None, None])
        )
        .max(axis=0)
        .tolist(),
        body_translation_path_m=np.linalg.norm(np.diff(position, axis=0), axis=-1)
        .sum(axis=0)
        .tolist(),
        body_displacement_m=np.linalg.norm(position[-1] - position[0], axis=-1).tolist(),
        body_peak_drift_from_initial_m=np.linalg.norm(position - position[0], axis=-1)
        .max(axis=0)
        .tolist(),
        mimic_residual_m=float(
            np.abs(
                np.stack([q[:, :, 7] - 0.5 * q[:, :, 6], q[:, :, 8] + 0.5 * q[:, :, 6]], axis=-1)
            ).max()
        ),
    )
    targets = np.asarray(data["native_targets"], np.float64)
    result["target_tracking"] = dict(
        arm_rad=differences(q[:, :, :6], targets[:, :, :6]),
        aperture_m=differences(q[:, :, 6], targets[:, :, 6]),
    )
    command_changes = np.abs(np.diff(targets, axis=0)) > 1e-8
    result["first_command_change"] = first_event(
        command_changes.any(axis=(1, 2)), {key: value[1:] for key, value in data.items()}
    )
    # This detector reports a declared threshold, not a parity acceptance limit.
    result["response_detector"] = dict(displacement_threshold_rad_or_m=1e-6)
    result["first_joint_motion"] = first_event((np.abs(q - q[0]) > 1e-6).any(axis=(1, 2)), data)
    result["first_step_response_per_joint"] = step_response(data)
    result["body_events"] = []
    velocity = data.get("body_velocity")
    for body, path in enumerate(meta["body_paths"]):
        entry = dict(
            path=path,
            min_z_m=float(position[:, body, 2].min()),
            max_z_m=float(position[:, body, 2].max()),
        )
        if velocity is not None:
            vz = velocity[:, body, 2]
            acceleration = np.diff(vz) / np.diff(t)
            entry.update(
                peak_speed_m_s=float(np.linalg.norm(velocity[:, body, :3], axis=-1).max()),
                median_vertical_acceleration_m_s2=float(np.median(acceleration)),
                first_upward_velocity_jump=first_event(np.r_[False, np.diff(vz) > 0.1], data),
                velocity_jump_detector_m_s=0.1,
            )
        for field, unit in [("contact_net_force", "N"), ("contact_impulse", "N_s")]:
            if field in data:
                if not meta.get("contact_observed_body_mask", [True] * 27)[body]:
                    entry[field] = dict(unavailable="No native contact sensor for this body")
                    continue
                magnitude = np.linalg.norm(data[field][:, body], axis=-1)
                entry[field] = dict(
                    peak=float(magnitude.max()),
                    unit=unit,
                    onset=first_event(magnitude > 1e-6, data),
                    onset_threshold=1e-6,
                    scope=meta.get("contact_sample_scope", "undeclared"),
                )
                if field == "contact_impulse":
                    entry[field]["sum_vector"] = data[field][:, body].sum(axis=0).tolist()
        result["body_events"].append(entry)
    masses = meta.get("body_mass")
    if velocity is not None and masses is not None:
        masses = np.asarray(masses, np.float64)
        linear = 0.5 * masses[None, :] * np.sum(velocity[..., :3] ** 2, axis=-1)
        # Translation of COM, rather than link origin, owns potential energy.
        com = np.asarray(meta.get("body_com_local_pose", []), np.float64)
        gravity = np.asarray(meta.get("gravity_m_s2", [0, 0, -9.81]), np.float64)
        if com.shape == (27, 7) and masses.shape == (27,):
            com_position = position + quaternion_rotate(poses[..., 3:], com[None, :, :3])
            potential = -masses[None, :] * np.sum(com_position * gravity, axis=-1)
            energy = dict(
                linear_kinetic_J=linear.tolist(),
                potential_J=potential.tolist(),
                caveat="Gravity-disabled bodies and driven joints are not an isolated energy-conserving system.",
            )
            inertia = np.asarray(meta.get("body_inertia_local", []), np.float64)
            if inertia.shape == (27, 3, 3):
                # Inertia axes are declared as the body COM principal/local frame.
                lq, cq = poses[..., 3:], com[None, :, 3:]
                world_com = np.concatenate(
                    [
                        lq[..., 3:] * cq[..., :3]
                        + cq[..., 3:] * lq[..., :3]
                        + np.cross(lq[..., :3], cq[..., :3]),
                        lq[..., 3:] * cq[..., 3:]
                        - np.sum(lq[..., :3] * cq[..., :3], axis=-1, keepdims=True),
                    ],
                    axis=-1,
                )
                inverse = world_com.copy()
                inverse[..., :3] *= -1
                omega = quaternion_rotate(inverse, velocity[..., 3:])
                rotational = 0.5 * np.einsum("tbi,bij,tbj->tb", omega, inertia, omega)
                energy["rotational_kinetic_J"] = rotational.tolist()
                energy["total_J"] = (linear + rotational + potential).sum(axis=1).tolist()
            result["energy"] = energy
    return result


def compare(left_path, right_path):
    left, lm = load(left_path)
    right, rm = load(right_path)
    errors = structural(left, lm, right, rm)
    report = dict(
        schema="physics_pair_comparison_v1",
        structural_status="FAIL" if errors else "PASS",
        structural_errors=errors,
        physics_parity_accepted=False,
        numerical_tolerances_for_acceptance=None,
        physical=False,
        dataset_admissible=False,
        inputs=[
            dict(
                path=str(p.resolve()),
                sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
                metadata_sha256=hashlib.sha256(
                    p.with_suffix(".meta.json").read_bytes()
                ).hexdigest(),
            )
            for p in (left_path, right_path)
        ],
    )
    if errors:
        return report
    numerical = {}
    for key in (
        "q",
        "dq",
        "native_targets",
        "body_velocity",
        "jacobian",
        "contact_net_force",
        "contact_impulse",
    ):
        if key in left and key in right:
            a, b = left[key], right[key]
            if key.startswith("contact_"):
                observed = np.asarray(
                    lm.get("contact_observed_body_mask", [True] * 27), bool
                ) & np.asarray(rm.get("contact_observed_body_mask", [True] * 27), bool)
                a, b = a[:, observed], b[:, observed]
            if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
                report["structural_errors"].append(f"optional {key} malformed/differs shape")
            else:
                numerical[key] = differences(a, b)
    numerical["body_position_m"] = differences(
        left["body_pose"][..., :3], right["body_pose"][..., :3]
    )
    lquat = np.asarray(left["body_pose"][..., 3:], np.float64)
    rquat = np.asarray(right["body_pose"][..., 3:], np.float64)
    lquat /= np.linalg.norm(lquat, axis=-1, keepdims=True)
    rquat /= np.linalg.norm(rquat, axis=-1, keepdims=True)
    dot = np.abs(np.sum(lquat * rquat, axis=-1))
    angle = 2 * np.arccos(np.clip(dot, 0, 1))
    numerical["body_orientation_rad"] = dict(
        max_abs=float(angle.max()), rms=float(np.sqrt(np.mean(angle**2)))
    )
    numerical["q_arm_rad"] = differences(left["q"][..., :6], right["q"][..., :6])
    numerical["q_prismatic_m"] = differences(left["q"][..., 6:], right["q"][..., 6:])
    report.update(
        numerical_differences=numerical,
        left=motion(left, lm),
        right=motion(right, rm),
        unavailable={"left": lm.get("unavailable", []), "right": rm.get("unavailable", [])},
    )
    if report["structural_errors"]:
        report["structural_status"] = "FAIL"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.left, args.right)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(report["structural_status"] + " structural; physics parity remains unaccepted")
    return int(report["structural_status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
