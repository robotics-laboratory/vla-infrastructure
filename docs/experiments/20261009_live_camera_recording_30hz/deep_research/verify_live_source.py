"""CPU post-run join: persisted canonical observations -> rendered snapshot matrix hashes."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import h5py
import numpy as np
import optical_witness as witness
from ovrtx_live_probe import pose_matrices

p = argparse.ArgumentParser()
p.add_argument("--input", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
p.add_argument("--retained-helper", type=Path)
a = p.parse_args()
manifest = json.loads((a.input / "mirror/source-manifest.json").read_text())
seed = json.loads((a.input / "mirror/seed.json").read_text())
rows = [json.loads(x) for x in (a.input / "mirror/worker-rows.jsonl").read_text().splitlines()]
worker = json.loads((a.input / "mirror/worker.json").read_text())
entries = [
    e for e in manifest["recordables"] if e["type"] in ["articulation", "rigid_body", "camera"]
]
camera_indices = [seed["paths"].index(c) for c in seed["cameras"]]
temporal_mesh = None
if seed.get("mesh_freshness"):
    pinned_path = seed["mesh_freshness"]["helper_path"]
    helper_path = a.retained_helper or Path(pinned_path)
    if hashlib.sha256(Path(helper_path).read_bytes()).hexdigest() != seed["helper_hashes"][pinned_path]:
        raise RuntimeError("Temporal Mesh source helper hash mismatch")
    spec = importlib.util.spec_from_file_location("verified_temporal_mesh", helper_path)
    temporal_mesh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(temporal_mesh)
errors = []
with h5py.File(a.input / "episode/session.hdf5", "r") as hdf:
    episode = next(iter(hdf["episodes"].values()))
    transitions = episode["d0/committed_transition"]
    n = len(transitions["observation_capture_sequence"])
    for i in range(n):
        row = rows[i]
        seq = int(transitions["observation_capture_sequence"][i])
        snapshot_id = transitions["scene_state_snapshot_id"][i].decode()
        snapshot_sha = bytes(transitions["scene_state_snapshot_sha256"][i]).hex()
        matrices = []
        for e in entries:
            frame = episode[e["group"]]
            plural = e["type"] == "articulation"
            m = pose_matrices(
                frame["positions" if plural else "position"][i],
                frame["orientations" if plural else "orientation"][i],
            )
            matrices.append(m if plural else m[None])
        matrices = np.concatenate(matrices)
        source_intrinsics = np.asarray([
            [float(episode["state/camera/" + role][key][i])
             for key in ["focal_length", "horizontal_aperture", "vertical_aperture"]]
            for role in ["left_wrist", "right_wrist", "scene"]
        ])
        descendants = seed.get("render_descendants", [])
        if descendants:
            local = np.array([item["mesh_to_body"] for item in descendants], dtype="<f8")
            if temporal_mesh is not None:
                local = temporal_mesh.update_locals(descendants, local, source_intrinsics, seq)
            parents = np.array([item["parent_index"] for item in descendants], dtype=np.int64)
            matrices = np.concatenate([matrices, local @ matrices[parents]])
        intrinsics = (
            [
                [
                    float(episode["state/camera/" + r][k][i])
                    for k in ["focal_length", "horizontal_aperture", "vertical_aperture"]
                ]
                for r in seed["roles"]
            ]
            if "roles" in seed
            else [
                [
                    float(episode["state/camera/" + r][k][i])
                    for k in ["focal_length", "horizontal_aperture", "vertical_aperture"]
                ]
                for r in ["left_wrist", "right_wrist", "scene"]
            ]
        )
        boards = [
            witness.matrices(
                matrices[c],
                intrinsics[r],
                seq,
                r,
                depth_scale=seed.get("single_gpu", {}).get("witness_depth_scale", 1.0),
            )
            for r, c in enumerate(camera_indices)
        ]
        full = np.concatenate([matrices, *boards]) if seed["witness"] else matrices
        digest = hashlib.sha256(full.astype("<f8").tobytes()).hexdigest()
        if (
            seq != row["source_id"]
            or snapshot_id != row["snapshot_id"]
            or snapshot_sha != row["snapshot_sha256"]
            or digest != row["transform_sha256"]
        ):
            errors.append(
                dict(
                    hdf_row=i,
                    source_sequence=seq,
                    matrix_hash_expected=digest,
                    matrix_hash_observed=row["transform_sha256"],
                )
            )
result = dict(
    schema="live30_persisted_source_join_v1",
    dataset_admissible=False,
    input=str(a.input),
    committed_observations=n,
    rendered_observations=len(rows),
    terminal_observation_separately_rendered=len(rows) == n + 1,
    source_identity_and_matrix_hash_equal=not errors,
    errors=errors,
    full_optical_guard_passed=worker["passed"],
    scope="Joins persisted source observation to matrices actually submitted to renderer; no independent silhouette/contact/photometric parity claim",
    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    hdf_sha256=hashlib.sha256((a.input / "episode/session.hdf5").read_bytes()).hexdigest(),
    worker_rows_sha256=hashlib.sha256(
        (a.input / "mirror/worker-rows.jsonl").read_bytes()
    ).hexdigest(),
)
a.output.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
raise SystemExit(0 if not errors and len(rows) == n + 1 else 1)
