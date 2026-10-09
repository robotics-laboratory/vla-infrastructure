import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

parser = argparse.ArgumentParser(description="Read-only paired trace root/TCP/prop decomposition")
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--empty-close", type=Path, help="Optional retained CPU control directory")
args = parser.parse_args()
root = args.input


def angle(a, b):
    a = a.astype(float)
    b = b.astype(float)
    a /= np.linalg.norm(a, axis=-1, keepdims=True)
    b /= np.linalg.norm(b, axis=-1, keepdims=True)
    return (
        2
        * np.arctan2(
            np.linalg.norm(a - np.where(np.sum(a * b, axis=-1, keepdims=True) < 0, -b, b), axis=-1),
            np.linalg.norm(a + np.where(np.sum(a * b, axis=-1, keepdims=True) < 0, -b, b), axis=-1),
        )
        * 2
    )


output = {}
for folder in root.iterdir():
    if not (folder / "gpu.npz").exists():
        continue
    data = {b: dict(np.load(folder / (b + ".npz"))) for b in ("gpu", "cpu")}
    names = json.loads((folder / "gpu.meta.json").read_text())["body_paths"]
    case = {}
    for i in (0, 8, 10, 11, 12, 20, 24, 25, 26):
        g, c = (data[b]["body_pose"][:, i] for b in ("gpu", "cpu"))
        row = {
            "path": names[i],
            "paired_peak_position_error_m": float(
                np.linalg.norm(g[:, :3] - c[:, :3], axis=-1).max()
            ),
            "paired_peak_angle_rad": float(angle(g[:, 3:], c[:, 3:]).max()),
        }
        for b in ("gpu", "cpu"):
            p = data[b]["body_pose"][:, i]
            row[b] = {
                "peak_position_drift_m": float(np.linalg.norm(p[:, :3] - p[0, :3], axis=-1).max()),
                "peak_rotation_drift_rad": float(
                    angle(p[:, 3:], np.broadcast_to(p[0, 3:], p[:, 3:].shape)).max()
                ),
                "initial_xyz": p[0, :3].tolist(),
                "final_xyz": p[-1, :3].tolist(),
                "z_min_m": float(p[:, 2].min()),
                "z_max_m": float(p[:, 2].max()),
            }
        case[str(i)] = row
    for b in ("gpu", "cpu"):
        d = data[b]
        mask = json.loads((folder / (b + ".meta.json")).read_text())["contact_observed_body_mask"]
        force = np.linalg.norm(d["contact_net_force"], axis=-1)
        aperture = d["q"][:, 0, 6]
        case[b] = {
            "left_aperture_initial_m": float(aperture[0]),
            "left_aperture_final_m": float(aperture[-1]),
            "left_aperture_min_m": float(aperture.min()),
            "finger10_peak_netforce_n": float(force[:, 10].max()),
            "finger11_peak_netforce_n": float(force[:, 11].max()),
            "finger10_contact_samples_above_1mN": int((force[:, 10] > 1e-3).sum()),
            "finger11_contact_samples_above_1mN": int((force[:, 11] > 1e-3).sum()),
            "contact_mask": mask,
            "max_arm_qtracking_error_rad": float(
                np.abs(d["q"][:, :, :6] - d["native_targets"][:, :, :6]).max()
            ),
            "max_mimic_residual_m": float(
                np.abs(d["q"][:, :, 7:] - d["q"][:, :, 6, None] * np.array([0.5, -0.5])).max()
            ),
            "control_wall_s": float(d["wall_time_s"][-1] - d["wall_time_s"][0]),
        }
    comparison = json.loads((folder / "comparison.json").read_text())
    case.update(
        structural_status=comparison["structural_status"],
        physics_parity_accepted=False,
        numerical_differences=comparison["numerical_differences"],
    )
    for label, side in [("gpu", "left"), ("cpu", "right")]:
        case[label]["step_response"] = comparison[side]["first_step_response_per_joint"]
        case[label]["mimic_residual_report_m"] = comparison[side]["mimic_residual_m"]
    case["trace_pins"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            folder / "gpu.npz",
            folder / "cpu.npz",
            folder / "gpu.meta.json",
            folder / "cpu.meta.json",
        )
    }
    output[folder.name] = case
process_path = root.parent / (root.name.removesuffix("-output") + ".process.json")
launch_returncode = (
    json.loads(process_path.read_text()).get("returncode") if process_path.exists() else None
)
assay_completed = json.loads((root / "result.json").read_text()).get("completed", False)
result = dict(
    schema="physics_pair_decomposition_v1",
    physical=False,
    dataset_admissible=False,
    physics_parity_accepted=False,
    launch_returncode=launch_returncode,
    assay_completed=assay_completed,
    blocked_cube_fixture_validated=False,
    scope="One paired trajectory per case; 4 physics ticks per observation; no numerical acceptance tolerances",
    cases=output,
)
if args.empty_close is not None:
    control = json.loads((args.empty_close / "result.json").read_text())
    mutation = json.loads((args.empty_close / "mutation.json").read_text())
    cleanup = json.loads(Path(control["worker_receipt"]).read_text())
    result["cpu_empty_close_control"] = dict(
        result=control, mutation=mutation, worker_receipt=cleanup
    )
args.output.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(dict(cases=len(output), output=str(args.output))))
