"""Bounded native geometry assay for the production offline RGB materializer.

Run only in the pinned Isaac environment with a GPU.  The input HDF is a
previously recorded native scene; assay copies it to a private output directory
and changes only diagnostic state-track rows.  Copies are never admissible
recordings.  The public EpisodeReplayer applies those rows and the unchanged
ReplayCameraMaterializer writes the tested RGB.  Instance-ID masks are diagnostic
only and are attached to the very same render products.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any

import h5py
import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.isaac_vr_rgb_alignment import (
    CENTER_TOLERANCE_PX,
    MIN_BOX_IOU,
    compare_geometry,
    mask_bounds,
    project_cube,
)


ROLES = ("left_wrist", "right_wrist", "scene")
# Deliberately nonperiodic and separated in 3D.  S3 puts A on its target plate;
# S5 moves all camera poses as well as both objects.  The reset is a new HDF
# replay session with a first state far from the preceding terminal state.
PRIMARY_STATES = (
    ((0.82, 0.13, 0.86), (0.87, -0.13, 0.87)),
    ((0.94, -0.04, 0.90), (0.83, 0.16, 0.88)),
    ((0.83, -0.11, 0.89), (0.95, 0.07, 0.87)),
    ((0.72, 0.17, 0.855), (0.90, -0.10, 0.87)),
    ((0.91, 0.13, 0.88), (0.82, -0.14, 0.88)),
    ((0.86, -0.06, 0.90), (0.94, 0.15, 0.88)),
    ((0.95, -0.12, 0.89), (0.85, 0.14, 0.88)),
)
RESET_STATE = ((0.80, -0.16, 0.88), (0.95, 0.12, 0.89))
WITNESS_PATHS = ("/World/RobosynDemo/LeftCube", "/World/RobosynDemo/RightCube")


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_assay_hdf(source: Path, output: Path) -> tuple[Path, Path]:
    """Create two clearly marked synthetic HDF state streams from real tracks."""
    output.mkdir(parents=True, exist_ok=False)
    result = []
    for name, states in (("primary", PRIMARY_STATES), ("reset", (RESET_STATE,))):
        target = output / f"synthetic_{name}.hdf5"
        shutil.copyfile(source, target)
        with h5py.File(target, "r+") as handle:
            # The available archived fixture predates the committed V3 row.
            # D0 is provenance-only on replay; map its no-op type to the current
            # registered type in this explicitly synthetic, inadmissible copy.
            tracks = json.loads(handle["manifest/tracks"][()].decode("utf-8"))
            for track in tracks:
                if track["group"] == "d0/committed_transition":
                    track["type"] = "piper_x_committed_transition_v3"
                    track["schema"] = "piper_x_committed_transition_v3"
            handle["manifest/tracks"][()] = json.dumps(tracks)
            episode = next(iter(handle["episodes"].values()))
            if name == "reset":
                session = json.loads(handle["manifest/session"][()].decode("utf-8"))
                session["episode_id"] = "alignment_reset_episode_000001"
                session["session_id"] = "alignment_reset_session"
                handle["manifest/session"][()] = json.dumps(session)
                episode.attrs["episode_index"] = 1
                episode_metadata = json.loads(episode.attrs["user_metadata"])
                episode_metadata["episode_id"] = session["episode_id"]
                episode.attrs["user_metadata"] = json.dumps(episode_metadata)
                episode["d0/committed_transition/episode_id"][0] = session["episode_id"]
            for frame, (left, right) in enumerate(states):
                episode["state/object_0/position"][frame] = left
                episode["state/object_1/position"][frame] = right
                if name == "primary" and frame == 2:
                    episode["state/object_0/orientation"][frame] = (
                        np.cos(np.pi / 8), 0, 0, np.sin(np.pi / 8)
                    )
                if name == "primary" and frame == 5:
                    for role, offset in (
                        ("left_wrist", (0, 0.09, 0)),
                        ("right_wrist", (0, -0.09, 0)),
                        ("scene", (0.08, 0, 0)),
                    ):
                        key = f"state/camera/{role}/position"
                        episode[key][frame] = episode[key][frame] + np.asarray(offset)
        result.append(target)
    return result[0], result[1]


def _recorded_state(hdf_path: Path, frame: int) -> dict[str, Any]:
    with h5py.File(hdf_path) as handle:
        episode = next(iter(handle["episodes"].values()))
        objects = [
            {
                "path": WITNESS_PATHS[index],
                "position_m": episode[f"state/object_{index}/position"][frame].tolist(),
                "orientation_wxyz": episode[f"state/object_{index}/orientation"][frame].tolist(),
            }
            for index in range(2)
        ]
        cameras = {
            role: {
                field: np.asarray(episode[f"state/camera/{role}/{field}"][frame]).tolist()
                for field in (
                    "position", "orientation", "focal_length", "horizontal_aperture",
                    "vertical_aperture", "clipping_range",
                )
            }
            for role in ROLES
        }
    return {"objects": objects, "cameras": cameras}


def _mask_for_path(data: dict[str, Any], path: str) -> np.ndarray:
    labels = data.get("info", {}).get("idToLabels", {})
    if not isinstance(labels, dict):
        raise RuntimeError("instance_id_segmentation lacks public idToLabels mapping")
    ids = [int(key) for key, label in labels.items() if path in str(label)]
    if not ids:
        return np.zeros((480, 640), dtype=bool)
    values = np.asarray(data["data"])
    if values.shape == (480, 640, 1):
        values = values[..., 0]
    if values.shape != (480, 640):
        raise RuntimeError(f"instance_id_segmentation shape {values.shape} is unsupported")
    return np.isin(values, ids)


def _rgb_color_fraction(path: Path, mask: np.ndarray, object_index: int) -> float | None:
    from PIL import Image

    if mask.sum() < 12:
        return None
    rgb = np.asarray(Image.open(path), dtype=np.int16)
    pixels = rgb[mask]
    if object_index == 0:
        matching = (pixels[:, 2] - pixels[:, 0] > 18) & (pixels[:, 2] - pixels[:, 1] > 9)
    else:
        matching = (pixels[:, 0] - pixels[:, 2] > 18) & (pixels[:, 0] - pixels[:, 1] > 9)
    return round(float(np.mean(matching)), 4)


def _evaluate_frame(
    state: dict[str, Any], renders: list[dict[str, Any]], annotators: dict[str, Any],
    *, label: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = []
    evidence: dict[str, dict[str, Any]] = {}
    for render in renders:
        role = render["role"]
        camera = state["cameras"][role]
        data = annotators[role].get_data()
        if not isinstance(data, dict):
            raise RuntimeError("instance_id_segmentation did not return data and info")
        evidence[role] = {}
        for index, obj in enumerate(state["objects"]):
            expected = project_cube(
                np.asarray(obj["position_m"]), np.asarray(obj["orientation_wxyz"]),
                np.asarray(camera["position"]), np.asarray(camera["orientation"]),
                float(camera["focal_length"]), float(camera["horizontal_aperture"]),
                float(camera["vertical_aperture"]),
            )
            mask = _mask_for_path(data, obj["path"])
            observed = mask_bounds(mask)
            comparison = compare_geometry(expected, observed)
            color_fraction = _rgb_color_fraction(Path(render["path"]), mask, index)
            # Diagnostic mask alone could be current while saved RGB is stale.
            rgb_pass = color_fraction is None or color_fraction >= 0.30
            row = {
                "state": label, "role": role, "object": obj["path"],
                "expected_visibility": expected.visibility,
                "expected_bounds_px": expected.bounds,
                "observed_bounds_px": observed,
                "mask_pixels": int(mask.sum()),
                "center_error_px": comparison["center_error_px"],
                "iou": comparison["iou"],
                "rgb_color_fraction_in_mask": color_fraction,
                "pass": bool(comparison["pass"] and rgb_pass),
                "reason": comparison["reason"] if rgb_pass else "rgb_mask_color_disagreement",
                "rgb_sha256": render["sha256"],
            }
            rows.append(row)
            evidence[role][obj["path"]] = {"expected": expected, "observed": observed}
    return rows, evidence


def run_native(args: argparse.Namespace, app: Any) -> dict[str, Any]:
    import omni.replicator.core as rep

    from isaacsim.replicator.episode_recorder import EpisodeReplayer, ReplayPolicy
    from tools.isaac_vr_recording import ensure_d0_recordable
    from tools.isaac_vr_replay import (
        ReplayCameraMaterializer, ReplayRuntimeGuard, _open_verified_snapshot,
        verify_recording_artifact,
    )

    source = args.recording.resolve()
    print("ASSAY_STAGE=verify_source", flush=True)
    artifact = verify_recording_artifact(
        source,
        portable_roots={
            "recording": source.parent,
            "isaac61_production": Path("/data/vla-infrastructure/isaac61_production"),
            "project_assets": Path("/data/vla-infrastructure/assets"),
        },
    )
    primary, reset = prepare_assay_hdf(source, args.output / "synthetic_inputs") if not args.restart else (
        args.output / "synthetic_inputs/synthetic_primary.hdf5",
        args.output / "synthetic_inputs/synthetic_reset.hdf5",
    )
    print("ASSAY_STAGE=open_stage", flush=True)
    guard = ReplayRuntimeGuard()
    guard.configure()
    _open_verified_snapshot(artifact, app)
    print("ASSAY_STAGE=stage_open", flush=True)
    guard.start_monitoring()
    ensure_d0_recordable()
    materializer = ReplayCameraMaterializer(artifact.camera_paths, args.output / ("restart_rgb" if args.restart else "rgb"))
    replayer = None
    annotators = {}
    rows: list[dict[str, Any]] = []
    controls: dict[str, bool] = {}
    try:
        materializer.open()
        print("ASSAY_STAGE=materializer_open", flush=True)
        for role, product in materializer.products.items():
            annotator = rep.AnnotatorRegistry.get_annotator(
                "instance_id_segmentation", init_params={"colorize": False}
            )
            annotator.attach(product)
            annotators[role] = annotator
        plans = (("primary", primary, (0, 6) if args.restart else tuple(range(7))),)
        if not args.restart:
            plans += (("reset_first", reset, (0,)),)
        prior_evidence = None
        for session_name, hdf_path, frames in plans:
            replayer = EpisodeReplayer(str(hdf_path), policy=ReplayPolicy(strictness="strict"), pose_backend="usd")
            replayer.prepare_episode(0)
            print(f"ASSAY_STAGE=session_ready:{session_name}", flush=True)
            for frame in frames:
                print(f"ASSAY_STAGE=frame:{session_name}:{frame}", flush=True)
                replayer.apply_frame(frame)
                app.update()  # production replay pump, before materializer.render()
                image_index = len(rows) // 6
                renders = materializer.render(image_index)  # unchanged production RGB producer
                state = _recorded_state(hdf_path, frame)
                frame_rows, evidence = _evaluate_frame(
                    state, renders, annotators, label=f"{session_name}:{frame}"
                )
                rows.extend(frame_rows)
                guard.assert_quiescent()
                if prior_evidence is not None and "lagged_identity" not in controls:
                    # A genuinely moving, visible witness must reject N-1.
                    for role in ROLES:
                        for obj in state["objects"]:
                            name = obj["path"]
                            old = prior_evidence[role][name]["expected"]
                            now = evidence[role][name]["observed"]
                            if old.visibility == "in_frame" and now is not None and not compare_geometry(old, now)["pass"]:
                                controls["lagged_identity"] = True
                                break
                        if controls.get("lagged_identity"):
                            break
                if "wrong_camera_role" not in controls:
                    for obj in state["objects"]:
                        name = obj["path"]
                        expected = evidence["scene"][name]["expected"]
                        wrong = evidence["left_wrist"][name]["observed"]
                        if expected.visibility == "in_frame" and wrong is not None and not compare_geometry(expected, wrong)["pass"]:
                            controls["wrong_camera_role"] = True
                            break
                if "wrong_transform" not in controls:
                    obj = state["objects"][0]
                    camera = state["cameras"]["scene"]
                    shifted = project_cube(
                        np.asarray(obj["position_m"]) + np.array([0, 0.35, 0]),
                        np.asarray(obj["orientation_wxyz"]),
                        np.asarray(camera["position"]), np.asarray(camera["orientation"]),
                        float(camera["focal_length"]), float(camera["horizontal_aperture"]),
                        float(camera["vertical_aperture"]),
                    )
                    observed = evidence["scene"][obj["path"]]["observed"]
                    controls["wrong_transform"] = bool(observed is not None and not compare_geometry(shifted, observed)["pass"])
                prior_evidence = evidence
            replayer.close()
            replayer = None
        guard.assert_quiescent()
    finally:
        for annotator in annotators.values():
            annotator.detach()
        materializer.close()
        if replayer is not None:
            replayer.close()
        guard.close()
    return {
        "schema": "piper_x_offline_rgb_state_alignment_assay_v1",
        "source_recording": str(source), "source_recording_sha256": _digest(source),
        "source_profile": artifact.manifest["session_metadata"]["source_profile"],
        "stage_snapshot_sha256": artifact.snapshot_sha256,
        "renderer_configuration_sha256": artifact.visual_provenance["renderer"]["renderer_configuration_sha256"],
        "visual_provenance_sha256": artifact.visual_provenance_sha256,
        "camera_roles": dict(artifact.camera_paths),
        "states": ["primary:0", "primary:6"] if args.restart else [*(f"primary:{n}" for n in range(7)), "reset_first:0"],
        "thresholds": {"center_px": CENTER_TOLERANCE_PX, "minimum_iou": MIN_BOX_IOU, "minimum_rgb_color_fraction": 0.30},
        "rows": rows, "positive_controls": controls,
        "physics_callbacks": len(guard.physics_callbacks),
        "pass": all(row["pass"] for row in rows) and all(controls.values()) and len(controls) == 3 and not guard.physics_callbacks,
        "restart": args.restart,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    if args.restart and not (args.output / "synthetic_inputs/synthetic_primary.hdf5").is_file():
        parser.error("restart requires a previous primary assay in --output")
    from isaaclab.app import AppLauncher

    print("ASSAY_STAGE=launch_kit", flush=True)
    app = AppLauncher({"headless": True, "enable_cameras": True, "kit_args": "--enable isaacsim.replicator.episode_recorder"}).app
    status = 1
    try:
        try:
            result = run_native(args, app)
        except Exception as exc:
            args.output.mkdir(parents=True, exist_ok=True)
            failure = {"pass": False, "error_type": type(exc).__name__, "error": str(exc), "stage": "native_assay"}
            (args.output / ("restart_failure.json" if args.restart else "failure.json")).write_text(
                json.dumps(failure, indent=2, sort_keys=True) + "\n"
            )
            raise
        destination = args.output / ("restart_summary.json" if args.restart else "summary.json")
        destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print("ALIGNMENT_RESULT=" + json.dumps({"pass": result["pass"], "physics_callbacks": result["physics_callbacks"], "rows": len(result["rows"]), "summary": str(destination)}), flush=True)
        status = 0 if result["pass"] else 1
        return status
    finally:
        app.close(exit_code=status)


if __name__ == "__main__":
    raise SystemExit(main())
