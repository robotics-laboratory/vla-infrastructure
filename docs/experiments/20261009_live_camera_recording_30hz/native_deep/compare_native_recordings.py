"""Offline same-action native HDF comparison; diagnostic, never qualification.

Reuse canonical D0/snapshot verifiers. Compare every retained source and terminal
pose, never wall-time identities or independently feedback-generated actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[4]
MASTER = "beaedfd1116577fd4d8026232cfb96cba0b030fa"
CORE = ("configs/isaac61_vr_runtime.yaml", "configs/isaac61_s2_runtime.yaml",
        "tools/run_isaac_s1.py", "tools/isaac_s1_runtime.py", "tools/isaac_vr_runtime.py")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def current_master_pins(repo):
    result = {}
    for name in CORE:
        current = (repo / name).read_bytes()
        original = subprocess.check_output(["git", "show", f"{MASTER}:{name}"], cwd=repo)
        result[name] = dict(current_sha256=hashlib.sha256(current).hexdigest(),
                            master_sha256=hashlib.sha256(original).hexdigest(),
                            byte_identical=current == original)
    require(all(row["byte_identical"] for row in result.values()), "Current master core/config bytes differ")
    return result


def append_terminal(tracks, terminal_frames):
    for name, row in tracks.items():
        require(set(row) == set(terminal_frames[name]), "Terminal track channels differ")
        for key, value in row.items():
            # Recorder scalars retain a one-item array; HDF scalar channels do not.
            terminal = np.asarray(terminal_frames[name][key]).reshape(value.shape[1:])
            row[key] = np.concatenate([value, terminal[None]], axis=0)


def load_recording(root, repo):
    import h5py

    sys.path.insert(0, str(repo))
    from tools.isaac_vr_recording import (
        _captured_frame_sha256, canonical_committed_transition,
        verify_committed_transition_sample, verify_terminal_successor_snapshot,
    )

    episode = root if (root / "session.hdf5").is_file() else root / "episode"
    manifest_path, hdf_path = episode / "manifest.json", episode / "session.hdf5"
    manifest = json.loads(manifest_path.read_text())
    require(manifest["artifact_state"] == "finalized", f"{root}: episode not finalized")
    require(digest(hdf_path) == manifest["hdf5_sha256"], f"{root}: HDF digest mismatch")
    finalization = json.loads((episode / "recording_state.json").read_text())
    require(finalization["artifact_state"] == "finalized" and
            finalization["committed_frames"] == manifest["committed_frames"],
            f"{root}: finalization marker mismatch")
    result_path = episode.parent / "result.json"
    result = json.loads(result_path.read_text())
    require(result.get("arguments", {}).get("physics_source") == "native",
            f"{root}: native physics not declared by runner")
    require(result.get("passed") is True, f"{root}: runner did not pass lifecycle")
    specs = [r for r in manifest["recordables"] if r["group"] != "d0/committed_transition"]
    require(len({r["group"] for r in specs}) == len(specs), "Duplicate Recordable groups")
    state_specs = [r for r in specs if r["group"] != "meta/time"]
    require({r["group"] for r in state_specs} == {
        "state/left_robot", "state/right_robot", "state/object_0", "state/object_1",
        "state/camera/left_wrist", "state/camera/right_wrist", "state/camera/scene"},
        "Unsupported/missing complete recorded scene inventory")
    with h5py.File(hdf_path, "r") as hdf:
        require(len(hdf["episodes"]) == 1, "Expected one technical episode")
        ep = next(iter(hdf["episodes"].values()))
        d0 = {name: value[...] for name, value in ep["d0/committed_transition"].items()}
        count = len(d0["frame_index"])
        require(count > 0 and count == manifest["committed_frames"], "Committed row count mismatch")
        require(all(len(v) == count for v in d0.values()), "D0 channel length mismatch")
        tracks = {r["group"]: {k: v[...] for k, v in ep[r["group"]].items()} for r in specs}
        require(all(len(v) == count for row in tracks.values() for v in row.values()),
                "Recordable channel length mismatch")
        previous = None
        for i in range(count):
            sample = canonical_committed_transition({k: v[i] for k, v in d0.items()})
            verify_committed_transition_sample(sample)
            require(int(sample["frame_index"]) == i, "Nonconsecutive committed frame")
            require(int(sample["observation_capture_sequence"]) == i and
                    int(sample["successor_capture_sequence"]) == i + 1,
                    "Nonconsecutive capture sequence")
            if previous is not None:
                for next_key, key in (("next_obs_id", "obs_id"),
                                      ("successor_observation_state", "observation_state"),
                                      ("successor_payload_sha256", "observation_payload_sha256"),
                                      ("next_scene_state_snapshot_id", "scene_state_snapshot_id"),
                                      ("next_scene_state_snapshot_sha256", "scene_state_snapshot_sha256")):
                    require(np.array_equal(previous[next_key], sample[key]), "Successor promotion mismatch")
            captured = {name: {k: v[i] for k, v in row.items()} for name, row in tracks.items()}
            require(_captured_frame_sha256(captured) ==
                    np.asarray(sample["scene_state_snapshot_sha256"], np.uint8).tobytes().hex(),
                    f"Recordable snapshot digest mismatch at row {i}")
            previous = sample
        terminal_path = episode / "terminal_successor.npz"
        terminal = verify_terminal_successor_snapshot(
            terminal_path, expected_artifact_sha256=manifest["terminal_successor"]["sha256"],
            committed_transition=previous)
        require(terminal.token.capture_sequence == count, "Terminal sequence mismatch")
        append_terminal(tracks, terminal.frames)
        require(json.loads(hdf["manifest/sampling"][()])["pose_backend"] == "fabric",
                "Native Fabric snapshot backend required")
        conventions = json.loads(hdf["manifest/coord_conventions"][()])
        require(conventions.get("quaternion_order") == "wxyz" and
                conventions.get("position_units") == "meters", "Unsupported pose conventions")
    steps = np.r_[d0["observation_physics_step"], terminal.token.physics_step]
    require(np.array_equal(np.diff(steps), np.full(count, 4)), "Not completed four-step boundaries")
    recorded_steps = tracks["meta/time"]["physics_step"].reshape(-1)
    sim_time = tracks["meta/time"]["sim_time"].reshape(-1)
    wall_time = tracks["meta/time"]["wall_time"].reshape(-1)
    require(np.isfinite(sim_time).all() and np.isfinite(wall_time).all(), "Nonfinite clock")
    require(np.array_equal(recorded_steps - recorded_steps[0], steps - steps[0]), "Clock counter offset changed")
    require(np.allclose(sim_time - sim_time[0], (steps - steps[0]) / 120, atol=1e-8, rtol=0),
            "Simulation time deltas disagree with completed native steps")
    require((np.diff(wall_time) >= 0).all(), "Recordable wall clock reverses")
    provenance = dict(root=str(root), rows=count, files={str(p): digest(p) for p in
        (manifest_path, hdf_path, terminal_path, result_path, episode / "recording_state.json")},
        session=manifest["session_metadata"], runner_source_pins=result.get("sources", {}),
        absolute_native_step=int(steps[0]), recorded_step_offset=int(recorded_steps[0] - steps[0]),
        absolute_sim_time_s=float(sim_time[0]), runner_arguments=result.get("arguments", {}))
    return dict(d0=d0, tracks={k: v for k, v in tracks.items() if k != "meta/time"},
                specs=state_specs, relative_steps=steps - steps[0], provenance=provenance)


def metric(left, right, tolerance, unit, *, quaternion=False):
    left, right = np.asarray(left), np.asarray(right)
    require(left.shape == right.shape and left.size > 0, "Compared channel shape differs/empty")
    require(np.isfinite(left).all() and np.isfinite(right).all(), "Nonfinite compared channel")
    if quaternion:
        require(left.shape[-1] == 4, "Invalid quaternion shape")
        ln, rn = np.linalg.norm(left, axis=-1), np.linalg.norm(right, axis=-1)
        require(np.allclose(ln, 1, atol=1e-4, rtol=0) and
                np.allclose(rn, 1, atol=1e-4, rtol=0), "Nonunit pose quaternion")
        dot = np.abs(np.sum((left.astype(np.float64) / ln[..., None]) *
                            (right.astype(np.float64) / rn[..., None]), axis=-1))
        # atan2 of signed-equivalent chord is stable near identity.
        lq, rq = left.astype(np.float64) / ln[..., None], right.astype(np.float64) / rn[..., None]
        rq = np.where((np.sum(lq * rq, axis=-1) < 0)[..., None], -rq, rq)
        delta = 4 * np.arctan2(np.linalg.norm(lq-rq, axis=-1), np.linalg.norm(lq+rq, axis=-1))
        require(np.isfinite(dot).all(), "Nonfinite quaternion dot")
    else:
        delta = np.abs(left.astype(np.float64) - right.astype(np.float64))
    bad = delta > tolerance
    failed_rows = np.flatnonzero(bad.reshape(len(left), -1).any(axis=1))
    return dict(passed=not bool(bad.any()), bit_exact=left.dtype == right.dtype and
                left.tobytes() == right.tobytes(), tolerance=tolerance, unit=unit,
                max_abs=float(delta.max()), rms=float(np.sqrt(np.mean(delta**2))),
                first_failed_sample=int(failed_rows[0]) if len(failed_rows) else None,
                failed_samples=len(failed_rows),
                per_component_max=np.max(delta, axis=0).tolist())


def compare_loaded(left, right, *, joint_tol=1e-5, gripper_tol=1e-5,
                   position_tol=1e-6, orientation_tol=1e-5, intrinsics_tol=1e-6):
    require(all(np.isfinite(v) and v >= 0 for v in
                (joint_tol, gripper_tol, position_tol, orientation_tol, intrinsics_tol)), "Invalid tolerances")
    require(left["specs"] == right["specs"], "Recordable paths/inventories differ")
    require(np.array_equal(left["relative_steps"], right["relative_steps"]), "Completed native steps differ")
    require(set(left["tracks"]) == set(right["tracks"]), "Recordable groups differ")
    comparisons, inputs, errors = {}, {}, []
    for key in ("dataset_action", "native_clipped"):
        a, b = left["d0"][key], right["d0"][key]
        require(a.ndim == 2 and a.shape[1] == 14 and a.shape == b.shape and np.isfinite(a).all()
                and np.isfinite(b).all(), f"Invalid paired {key}")
        changed = np.flatnonzero(np.any(a != b, axis=1))
        inputs[key] = dict(exact_equal=np.array_equal(a, b), rows=len(a),
                           bit_exact=a.dtype == b.dtype and a.tobytes() == b.tobytes(),
                           differing_rows=len(changed),
                           first_differing_row=int(changed[0]) if len(changed) else None,
                           per_component_max_abs=np.abs(a.astype(np.float64)-b).max(axis=0).tolist(),
                           units="degrees/millimetres" if key == "dataset_action" else "radians/meters",
                           left_sha256=hashlib.sha256(a.tobytes()).hexdigest(),
                           right_sha256=hashlib.sha256(b.tobytes()).hexdigest())
        if not inputs[key]["exact_equal"]:
            errors.append(f"Paired {key} differs: feedback runs are not same-input parity")
    for field in ("observation_state", "successor_observation_state"):
        a, b = left["d0"][field], right["d0"][field]
        require(a.ndim == 2 and a.shape[1] == 14, f"Invalid {field} shape")
        a, b = a.reshape(-1, 2, 7), b.reshape(-1, 2, 7)
        for channels, unit, tol in ((slice(0, 6), "degrees", joint_tol), (slice(6, 7), "millimetres", gripper_tol)):
            name = f"{field}/{unit}"
            comparisons[name] = metric(a[..., channels], b[..., channels], tol, unit)
            if field == "observation_state":
                comparisons[f"initial_state/{unit}"] = metric(a[:1, ..., channels], b[:1, ..., channels], tol, unit)
    for group, channels in left["tracks"].items():
        require(set(channels) == set(right["tracks"][group]), f"Track channels differ: {group}")
        required = ({"positions", "orientations"} if group.endswith("_robot") else
                    {"position", "orientation"})
        if "/camera/" in group:
            required |= {"focal_length", "horizontal_aperture", "vertical_aperture", "clipping_range"}
        require(required <= set(channels), f"Missing required pose/intrinsics: {group}")
        for key, a in channels.items():
            b = right["tracks"][group][key]
            orient = key in ("orientation", "orientations")
            pose = key in ("position", "positions", "clipping_range")
            tol, unit = ((orientation_tol, "radians") if orient else
                         (position_tol, "meters") if pose else (intrinsics_tol, "recorded_camera_units"))
            name = f"{group}/{key}"
            comparisons[name] = metric(a, b, tol, unit, quaternion=orient)
            comparisons[f"initial/{name}"] = metric(a[:1], b[:1], tol, unit, quaternion=orient)
    eligible = not errors
    return dict(passed=eligible and all(v["passed"] for v in comparisons.values()), errors=errors,
                same_input_parity_eligible=eligible,
                numeric_differences_are_descriptive_only=not eligible,
                same_inputs=inputs, comparisons=comparisons,
                initial_state_matched=all(v["passed"] for k, v in comparisons.items() if k.startswith("initial")),
                all_compared_channels_bit_exact=all(v["bit_exact"] for v in comparisons.values()),
                observations_including_terminal=len(left["relative_steps"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for side in ("left", "right"):
        parser.add_argument(f"--{side}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for name, default in (("joint", 1e-5), ("gripper", 1e-5), ("position", 1e-6),
                          ("orientation", 1e-5), ("intrinsics", 1e-6)):
        parser.add_argument(f"--{name}-tol", type=float, default=default)
    args = parser.parse_args()
    report = dict(schema="native_recording_same_action_comparison_v1", passed=False,
                  scope="Controlled same-command HDF state/snapshot comparison only",
                  physical=False, physics_qualified=False, dataset_admissible=False,
                  optical_alignment_proven=False, master=MASTER, command=sys.argv,
                  helper_sha256=digest(Path(__file__)), errors=[],
                  incomparable=["Cross-run wall clocks, run IDs and payload hashes retained as provenance",
                                "Unrecorded physics_probe native body pose; native velocities, Jacobians, contacts",
                                "Renderer pixel origin and optical appearance",
                                "Physics solver/mass/inertia settings absent from canonical HDF",
                                "Current core byte equality does not prove unretained capture-time core hashes"])
    try:
        report["current_master_core"] = current_master_pins(REPO)
        left, right = load_recording(args.left.resolve(), REPO), load_recording(args.right.resolve(), REPO)
        report["input_provenance"] = [left["provenance"], right["provenance"]]
        for key in ("d0_revision", "task", "environment_pins"):
            require(left["provenance"]["session"].get(key) == right["provenance"]["session"].get(key),
                    f"Session semantic/environment metadata differs: {key}")
        report.update(compare_loaded(left, right, **{f"{name}_tol": getattr(args, f"{name}_tol")
                       for name in ("joint", "gripper", "position", "orientation", "intrinsics")}))
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "scope", "errors")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
