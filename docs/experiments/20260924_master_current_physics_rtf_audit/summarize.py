"""Summarize retained 120 Hz samples and render the requested physics plots."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import statistics


def _runs(data, case):
    return [run for run in data["repetitions"] if run["case"] == case]


def _series(run, field):
    samples = run["samples"]
    if field == "z":
        return [sample["cube"]["position_m"][2] for sample in samples]
    if field == "vz":
        return [sample["cube"]["linear_velocity_m_s"][2] for sample in samples]
    if field == "aperture":
        index = sample_index(samples, "gripper")
        return [sample["left_joint_position"][index] for sample in samples]
    if field == "arm":
        index = sample_index(samples, "joint1")
        return [sample["left_joint_position"][index] for sample in samples]
    if field == "tcp_x":
        return [sample["tcp_pose_world"][0] for sample in samples]
    raise ValueError(field)


def sample_index(samples, name):
    names = samples[0]["joint_names"]
    if name in names:
        return names.index(name)
    matches = [index for index, candidate in enumerate(names) if name in candidate]
    if len(matches) != 1:
        raise ValueError(f"Ambiguous joint {name}: {names}")
    return matches[0]


def _crossing(samples, values, threshold, *, descending):
    for index in range(1, len(values)):
        crossed = values[index] <= threshold < values[index - 1] if descending else values[index] >= threshold > values[index - 1]
        if crossed:
            return {"sim_time_s": samples[index]["sim_time_s"],
                    "wall_time_s": samples[index]["wall_time_s"]}
    return None


def _cube_metrics(run):
    samples = run["samples"]
    z = _series(run, "z")
    vz = _series(run, "vz")
    impact_index = next((i for i in range(1, len(samples))
                         if vz[i] - vz[i - 1] > 0.5 and vz[i - 1] < -0.1 and z[i] < 0.86), None)
    impact = ({"sim_time_s": samples[impact_index]["sim_time_s"],
               "wall_time_s": samples[impact_index]["wall_time_s"]}
              if impact_index is not None else None)
    rebound = None
    rebound_count = 0
    if impact_index is not None:
        upward = False
        peaks = []
        for i in range(impact_index + 1, len(vz)):
            if vz[i] > 0.02 and not upward:
                upward = True
                rebound_count += 1
            if upward and vz[i] <= 0:
                peaks.append(max(z[impact_index:i + 1]) - 0.845)
                upward = False
        rebound = peaks[0] if peaks else None
    settle = None
    window = 24
    for i in range((impact_index or 0), len(samples) - window):
        if all(abs(vz[j]) < 0.02 and
               max(abs(v) for v in samples[j]["cube"]["angular_velocity_rad_s"]) < 0.2
               for j in range(i, i + window)):
            settle = {"sim_time_s": samples[i]["sim_time_s"],
                      "wall_time_s": samples[i]["wall_time_s"]}
            break
    return {"first_impact": impact, "impact_velocity_m_s": vz[impact_index - 1] if impact_index is not None else None,
            "first_rebound_height_m": rebound, "rebound_count": rebound_count,
            "settle": settle, "final_pose": samples[-1]["cube"],
            "minimum_z_m": min(z)}


def _free_fall_metrics(run):
    samples = [sample for sample in run["samples"] if sample["sim_time_s"] <= 0.4 + 1e-9]
    z0 = samples[0]["cube"]["position_m"][2]
    last = samples[-1]
    vz = [sample["cube"]["linear_velocity_m_s"][2] for sample in samples]
    acceleration = [(b - a) / (1 / 120) for a, b in zip(vz[:-1], vz[1:], strict=True)]
    return {"initial_z_m": z0, "z_at_0_4_sim_s_m": last["cube"]["position_m"][2],
            "vz_at_0_4_sim_s_m_s": vz[-1],
            "median_acceleration_m_s2": statistics.median(acceleration),
            "wall_time_at_0_4_sim_s_s": last["wall_time_s"],
            "samples_before_any_ground_contact": len(samples)}


def _gripper_metrics(run):
    samples = run["samples"]
    q = _series(run, "aperture")
    start, final = q[0], q[-1]
    span = start - final
    t10 = _crossing(samples, q, start - 0.1 * span, descending=True)
    t90 = _crossing(samples, q, start - 0.9 * span, descending=True)
    index = sample_index(samples, "gripper")
    settle = None
    for i in range(len(samples) - 12):
        if all(abs(q[j]) < 0.001 and abs(samples[j]["left_joint_velocity"][index]) < 0.01
               for j in range(i, i + 12)):
            settle = {"sim_time_s": samples[i]["sim_time_s"],
                      "wall_time_s": samples[i]["wall_time_s"]}
            break
    return {"initial_m": start, "final_m": final, "t10": t10, "t90": t90,
            "closure_10_90_sim_s": t90["sim_time_s"] - t10["sim_time_s"] if t10 and t90 else None,
            "closure_10_90_wall_s": t90["wall_time_s"] - t10["wall_time_s"] if t10 and t90 else None,
            "settle": settle,
            "peak_joint_velocity_m_s": max(abs(s["left_joint_velocity"][index]) for s in samples),
            "overshoot_m": max(0.0, -min(q))}


def _max_diff(a, b):
    if len(a) != len(b):
        raise ValueError("Unequal native sample counts")
    return max(abs(x - y) for x, y in zip(a, b, strict=True))


def _full_state_differences(old, current):
    """Compare every retained native state field except wall-clock measurements."""
    differences = {}
    old_step0 = old["samples"][0]["physics_step"]
    current_step0 = current["samples"][0]["physics_step"]
    for a, b in zip(old["samples"], current["samples"], strict=True):
        differences["sim_time_s"] = max(differences.get("sim_time_s", 0),
                                         abs(a["sim_time_s"] - b["sim_time_s"]))
        differences["relative_physics_step"] = max(
            differences.get("relative_physics_step", 0),
            abs((a["physics_step"] - old_step0) - (b["physics_step"] - current_step0)))
        for field in ("kind", "joint_names", "geometric_table_contact_proxy"):
            if a[field] != b[field]:
                raise ValueError(f"Native state field differs: {field}")
        for field in ("left_joint_position", "left_joint_velocity", "tcp_pose_world", "target_d0"):
            differences[field] = max(differences.get(field, 0),
                                     max(abs(x - y) for x, y in zip(a[field], b[field], strict=True)))
        for field in ("position_m", "linear_velocity_m_s", "angular_velocity_rad_s", "orientation_wxyz"):
            key = f"cube.{field}"
            differences[key] = max(differences.get(key, 0),
                                   max(abs(x - y) for x, y in zip(a["cube"][field],
                                                                    b["cube"][field], strict=True)))
    return differences


def _validate_pair(old, current):
    for run in (old, current):
        samples = run["samples"]
        if len(samples) != 4 * len(run["controls"]) + 1:
            raise ValueError("Native 120 Hz sample count does not match control count")
        for previous, sample in zip(samples[:-1], samples[1:], strict=True):
            if sample["physics_step"] != previous["physics_step"] + 1:
                raise ValueError("Nonconsecutive native physics steps")
            if abs(sample["sim_time_s"] - previous["sim_time_s"] - 1 / 120) > 1e-9:
                raise ValueError("Nonconsecutive simulated time")
    a, b = old["samples"][0], current["samples"][0]
    if a["target_d0"] != b["target_d0"] or a["cube"] != b["cube"]:
        raise ValueError("OLD and CURRENT initial state or command differs")


def _plot(output, title, xlabel, ylabel, curves, name, events=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for label, xs, ys, marks in curves:
        ax.plot(xs, ys, label=label)
        if events:
            hit_x = [x for x, mark in zip(xs, marks, strict=True) if mark]
            hit_y = [y for y, mark in zip(ys, marks, strict=True) if mark]
            ax.scatter(hit_x, hit_y, s=7)
    ax.set(title=title, xlabel=xlabel, ylabel=ylabel)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    _save_svg(fig, output / name)
    plt.close(fig)


def _save_svg(fig, path):
    fig.savefig(path, metadata={"Date": None})
    original = path.read_text()
    path.write_text("\n".join(line.rstrip(" \t") for line in original.split("\n")))


def _plots(output, pair):
    import matplotlib
    matplotlib.rcParams["svg.hashsalt"] = "master-current-physics-rtf-audit"
    for case, field, axis, title, name, ylabel, events in (
        ("free_fall", "z", "sim_time_s", "Cube free fall by simulation time", "cube-z-sim.svg", "z (m)", False),
        ("free_fall", "z", "wall_time_s", "Cube free fall by wall time", "cube-z-wall.svg", "z (m)", False),
        ("free_fall", "vz", "sim_time_s", "Cube vertical velocity by simulation time", "cube-vz-sim.svg", "vz (m/s)", False),
        ("bounce", "z", "sim_time_s", "Cube rebound/contact by simulation time", "bounce-sim.svg", "z (m)", True),
        ("bounce", "z", "wall_time_s", "Cube rebound/contact by wall time", "bounce-wall.svg", "z (m)", True),
        ("gripper", "aperture", "sim_time_s", "Gripper by simulation time", "gripper-sim.svg", "aperture (m)", False),
        ("gripper", "aperture", "wall_time_s", "Gripper by wall time", "gripper-wall.svg", "aperture (m)", False),
        ("arm", "tcp_x", "sim_time_s", "TCP X by simulation time", "tcp-sim.svg", "TCP X (m)", False),
    ):
        curves = []
        for label, data in pair.items():
            run = _runs(data, case)[0]
            samples = run["samples"]
            values = _series(run, field)
            if case == "free_fall":
                pairs = [(sample, value) for sample, value in zip(samples, values, strict=True)
                         if sample["sim_time_s"] <= 0.4 + 1e-9]
                samples = [item[0] for item in pairs]
                values = [item[1] for item in pairs]
            curves.append((label.upper(), [s[axis] for s in samples], values,
                           [s["geometric_table_contact_proxy"] for s in samples]))
        _plot(output, title, "simulation time (s)" if axis == "sim_time_s" else "wall time (s)",
              ylabel, curves, name, events)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4.5))
    labels = list(pair)
    metrics = ("effective_control_hz", "effective_physics_hz", "rtf")
    for i, metric in enumerate(metrics):
        values = [data["rate_repetitions"][0][metric] for data in pair.values()]
        ax.bar([i * 3 + j for j in range(2)], values, label=metric)
    ax.set_xticks([0, 1, 3, 4, 6, 7], [f"{metric}\n{label}" for metric in metrics for label in labels])
    ax.set_title("No-client render-policy assay rates")
    ax.set_ylabel("Hz or ratio")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    _save_svg(fig, output / "rate-comparison.svg")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output
    provenance = json.loads((output / "provenance.json").read_text())
    pair = {}
    for label in ("old", "current"):
        local = output / f"samples-{label}.json"
        if local.exists():
            pair[label] = json.loads(local.read_text())
        else:
            locator = Path(provenance["retained_native_samples"][label]["path"])
            with gzip.open(locator, "rt") as stream:
                pair[label] = json.load(stream)
    result = {"measurement_type": "no_client_native_assay", "thresholds":
              {"cube_z_m": 0.005, "cube_vz_m_s": 0.05, "gripper_m": 0.002,
               "arm_rad": 0.01, "tcp_x_m": 0.005}, "cases": {}, "rates": {}}
    for label, data in pair.items():
        result["rates"][label] = data["rate_repetitions"][0]
    for case, fields in (("free_fall", ("z", "vz")), ("bounce", ("z", "vz")),
                         ("gripper", ("aperture",)), ("arm", ("arm", "tcp_x"))):
        old, current = (_runs(pair[label], case) for label in ("old", "current"))
        for a, b in zip(old, current, strict=True):
            _validate_pair(a, b)
        differences = {field: [_max_diff(_series(a, field)[:49] if case == "free_fall" else _series(a, field),
                                         _series(b, field)[:49] if case == "free_fall" else _series(b, field))
                               for a, b in zip(old, current, strict=True)] for field in fields}
        full_state = [_full_state_differences(a, b) for a, b in zip(old, current, strict=True)]
        result["cases"][case] = {"paired_initial_state_and_command_equal": True,
                                "consecutive_native_120hz_samples": True,
                                "samples_per_repeat": len(old[0]["samples"]),
                                "sim_time_max_abs_differences": differences,
                                "all_native_state_max_abs_differences": full_state,
                                "old": {}, "current": {}}
        for label, runs in (("old", old), ("current", current)):
            metrics = (_free_fall_metrics if case == "free_fall" else
                       _cube_metrics if case == "bounce" else
                       _gripper_metrics if case == "gripper" else
                       lambda run: {"final_tcp_pose_world": run["samples"][-1]["tcp_pose_world"]})
            result["cases"][case][label] = [metrics(run) for run in runs]
    (output / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    _plots(output, pair)


if __name__ == "__main__":
    main()
