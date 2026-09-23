"""Summarize every retained control; never trim tails or substitute missing metrics."""

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np


def distribution(values):
    values = np.asarray(values, dtype=float)
    if not values.size:
        return None
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite measurement")
    mean = float(values.mean())
    return {
        "count": len(values),
        "mean": mean,
        "stddev": float(values.std()),
        "cv": float(values.std() / mean) if mean else None,
        **{f"p{q:g}": float(np.percentile(values, q)) for q in (50, 90, 95, 99, 99.9)},
        "max": float(values.max()),
    }


def run_summary(path):
    launch = json.loads((path / "launch.json").read_text())
    perf = path / "runtime/performance.jsonl"
    if (path / "xr-performance.jsonl").exists():
        perf = path / "xr-performance.jsonl"
    result = {
        "path": str(path),
        "launch_sha256": hashlib.sha256((path / "launch.json").read_bytes()).hexdigest(),
        "head": launch["head"],
        "arguments": launch["arguments"],
        "exit_code": launch.get("exit_code"),
    }
    if perf.exists():
        raw = [json.loads(line) for line in perf.read_text().splitlines()]
        rows = [r for r in raw if r["event"] == "performance_step" and r["post_warmup"]]
        result["control_ms"] = distribution([r["total_ms"] for r in rows])
        if rows:
            result["effective_hz"] = 1000 / result["control_ms"]["mean"]
            result["rtf"] = result["effective_hz"] / 30
            result["deadline_misses"] = sum(r["total_ms"] > 1000 / 30 for r in rows)
            result["deadline_miss_fraction"] = result["deadline_misses"] / len(rows)
            result["wall_hz"] = (
                ((len(rows) - 1) * 1e9 / (rows[-1]["monotonic_ns"] - rows[0]["monotonic_ns"]))
                if len(rows) > 1
                else None
            )
            for category in ("stage_ms", "nested_stage_ms"):
                names = sorted(set().union(*(r[category] for r in rows)))
                result[category] = {
                    name: distribution([r[category].get(name, 0) for r in rows]) for name in names
                }
            result["residual_ms"] = distribution([r["unattributed_ms"] for r in rows])
        result["rows"] = rows
    benchmark = path / "runtime/recording-benchmark.jsonl"
    if benchmark.exists():
        raw = [json.loads(line) for line in benchmark.read_text().splitlines()]
        rows = [r for r in raw if "resources" in r and r.get("post_warmup")]
        if rows:
            result["resources"] = {
                key: distribution([r["resources"][key] for r in rows])
                for key in rows[0]["resources"]
            }
    oracle = path / "oracle-summary.json"
    if oracle.exists():
        result["oracle"] = json.loads(oracle.read_text())
    mechanisms = path / "mechanisms.jsonl"
    if mechanisms.exists():
        rows = [json.loads(line) for line in mechanisms.read_text().splitlines()]
        if (path / "xr-performance.jsonl").exists():
            rows = rows[10:]
        rows = rows[launch["arguments"]["warmup"] :]
        if rows:
            result["mechanisms"] = {
                "count": len(rows),
                "physics_deltas": sorted(set(r["physics_delta"] for r in rows)),
                "native_physics_deltas": sorted(set(r["counts"]["native_physics"] for r in rows)),
                "kit_updates": distribution([r["counts"]["kit"] for r in rows]),
                "products_enabled": rows[-1]["products_enabled"],
                "product_mapping": rows[-1]["products"],
                "panels_ever_bound": any(r["panels_bound"] for r in rows),
                "render_generation_deltas": sorted({r["render_delta"] for r in rows}),
                "render_flag_patterns": sorted({str(r["render_flags"]) for r in rows}),
                "active_products": sum(rows[-1]["products_enabled"]),
                "disk_window_bytes": {
                    k: rows[-1]["resources"][k] - rows[0]["resources"][k]
                    for k in ("disk_read_bytes_cumulative", "disk_write_bytes_cumulative")
                    if k in rows[0].get("resources", {})
                },
                "drawable_events": {
                    k: distribution([r["drawables"][k] for r in rows]) for k in rows[0]["drawables"]
                },
                "observer_before_write_ms": distribution(
                    [r["observer_before_write_ms"] for r in rows]
                )
                if "observer_before_write_ms" in rows[0]
                else None,
                "resources": {
                    k: distribution([r["resources"][k] for r in rows])
                    for k in rows[0].get("resources", {})
                },
            }
    result["artifact_bytes"] = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return result


def analyze(root, out):
    out.mkdir(parents=True, exist_ok=True)
    results = [run_summary(p.parent) for p in sorted(root.glob("*/launch.json"))]
    for result in results:
        path = Path(result["path"])
        launch = json.loads((path / "launch.json").read_text())
        result["dirty_at_launch"] = launch["dirty"]
        result["artifact_hdf_bytes"] = sum(p.stat().st_size for p in path.rglob("*.hdf5"))
        result["rgb_persist_bytes"] = sum(
            p.stat().st_size for p in (path / "rgb").glob("*") if p.is_file()
        )
        rows = result.get("rows", [])
        if len(rows) == 3000:
            result["predeclared_first_300_ms"] = distribution([r["total_ms"] for r in rows[:300]])
        gpu_path = path / "gpu.csv"
        if rows and gpu_path.exists() and "started_monotonic_ns" in launch:
            offset = launch["started_unix"] - launch["started_monotonic_ns"] / 1e9
            first = offset + rows[0]["monotonic_ns"] / 1e9 - rows[0]["total_ms"] / 1000
            last = offset + rows[-1]["monotonic_ns"] / 1e9
            samples = []
            for line in list(csv.reader(gpu_path.read_text().splitlines()))[1:]:
                try:
                    timestamp = (
                        datetime.strptime(line[0], "%Y/%m/%d %H:%M:%S.%f")
                        .replace(tzinfo=timezone.utc)
                        .timestamp()
                        + launch["timezone_seconds_west"]
                    )
                    if first <= timestamp <= last:
                        samples.append([float(value.split()[0]) for value in line[1:]])
                except (ValueError, IndexError):
                    continue
            result["gpu_measured_window"] = {
                key: distribution([r[i] for r in samples])
                for i, key in enumerate(("utilization_percent", "vram_mib", "power_w"))
            }
        mechanism_file = path / "mechanisms.jsonl"
        if mechanism_file.exists() and launch["arguments"].get("gpu_scopes"):
            records = [json.loads(line) for line in mechanism_file.read_text().splitlines()][
                10 + launch["arguments"]["warmup"] :
            ]
            passes, tiles = [], []
            for record in records:
                scopes = [scope for group in record.get("gpu_scopes", []) for scope in group]
                values = [
                    s["duration"]
                    for s in scopes
                    if s["name"] == "RTX Rendering" and s["indent"] == 0
                ]
                if len(values) == 1:
                    passes.append(values[0])
                    tiles.append(sum(s["name"] == "RTX Render Tile" for s in scopes))
            result["latest_published_gpu_pass"] = {
                "rtx_ms": distribution(passes),
                "tile_count": distribution(tiles),
            }

    qualified = [
        r
        for r in results
        if Path(r["path"]).name.startswith("cost-") and r.get("exit_code") == 0 and r.get("rows")
    ]
    groups = defaultdict(list)
    for result in qualified:
        a = result["arguments"]
        key = "/".join(
            (
                a["mode"],
                a["temporal"],
                a["cost"] + ("-batch" if a["batch"] else ""),
                f"w{a['warmup']}-m{a['measured']}",
            )
        )
        groups[key].append(result)
    pooled = {}
    for key, runs in groups.items():
        rows = [row for run in runs for row in run["rows"]]
        d = distribution([r["total_ms"] for r in rows])
        pooled[key] = {
            "runs": [Path(r["path"]).name for r in runs],
            "heads": sorted({r["head"] for r in runs}),
            "control_ms": d,
            "effective_hz": 1000 / d["mean"],
            "rtf": 1000 / d["mean"] / 30,
            "deadline_misses": sum(r["total_ms"] > 1000 / 30 for r in rows),
            "deadline_miss_fraction": sum(r["total_ms"] > 1000 / 30 for r in rows) / len(rows),
            "run_mean_range_ms": [
                min(r["control_ms"]["mean"] for r in runs),
                max(r["control_ms"]["mean"] for r in runs),
            ],
            "run_wall_hz": [r["wall_hz"] for r in runs],
            "stages": {
                name: distribution([r["stage_ms"].get(name, 0) for r in rows])
                for name in sorted(set().union(*(r["stage_ms"] for r in rows)))
            },
            "nested_nonadditive": {
                name: distribution([r["nested_stage_ms"].get(name, 0) for r in rows])
                for name in sorted(set().union(*(r["nested_stage_ms"] for r in rows)))
            },
            "residual_ms": distribution([r["unattributed_ms"] for r in rows]),
            "first_300_matched_ms": distribution(
                [r["total_ms"] for run in runs for r in run["rows"][:300]]
            ),
        }
    (out / "results.json").write_text(
        json.dumps([{k: v for k, v in r.items() if k != "rows"} for r in results], indent=2) + "\n"
    )
    (out / "pooled.json").write_text(json.dumps(pooled, indent=2) + "\n")
    with (out / "control-distributions.csv").open("w") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["group", "run", "measured_index", "control_ms"])
        for key, runs in groups.items():
            for run in runs:
                writer.writerows(
                    (key, Path(run["path"]).name, i + 1, r["total_ms"])
                    for i, r in enumerate(run["rows"])
                )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    short = [f"xr-smoke/t0/c{i}/w300-m300" for i in range(4)]
    if all(k in pooled for k in short):
        fig, ax = plt.subplots(figsize=(8, 4))
        for i, key in enumerate(short):
            v = np.sort([r["total_ms"] for run in groups[key] for r in run["rows"]])
            ax.plot(v, np.arange(1, len(v) + 1) / len(v), label=f"C{i} (n={len(v)})")
        ax.axvline(1000 / 30, linestyle="--", color="black", label="33.333 ms")
        ax.set(
            xlabel="Control latency (ms), all retained samples",
            ylabel="Cumulative probability",
            title="Current FFFT, active XR, preview off — diagnostic timing",
        )
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / "latency-cdf.png", dpi=150)
        plt.close(fig)
        means = [pooled[k]["control_ms"]["mean"] for k in short]
        increments = [means[0], *np.diff(means)]
        labels = ["C0 baseline", "+ products/AOVs", "+ extraction", "+ ownership"]
        persist = "xr-smoke/t0/c4/w300-m300"
        if persist in pooled:
            increments.append(pooled[persist]["control_ms"]["mean"] - means[-1])
            labels.append("+ NPZ (1 run)")
        fig, ax = plt.subplots(figsize=(8, 4))
        running = 0
        for i, delta in enumerate(increments):
            ax.bar(
                i,
                delta,
                bottom=running,
                color=["#64748b", "#3b82f6", "#eab308", "#f97316", "#a855f7"][i],
            )
            ax.text(
                i,
                running + delta,
                f"{delta:+.2f}" if i else f"{delta:.2f}",
                ha="center",
                va="bottom",
            )
            running += delta
        ax.set(
            xticks=range(len(labels)),
            xticklabels=labels,
            ylabel="ms/control",
            title="Measured level differences; overlapping internal scopes are not summed",
        )
        ax.axhline(1000 / 30, linestyle="--", color="black")
        fig.tight_layout()
        fig.savefig(out / "camera-waterfall.png", dpi=150)
        plt.close(fig)

    longkeys = [k for k in pooled if k.endswith("m3000") and k.startswith("xr-smoke/")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, keys, title in [
        (
            axes[0],
            [k for k in pooled if k.endswith("m300") and "/c4/" not in k],
            "Short diagnostic runs",
        ),
        (axes[1], longkeys, "3000-control windows"),
    ]:
        labels = [k.split("/")[1] + "\n" + k.split("/")[2] for k in keys]
        ax.bar(range(len(keys)), [pooled[k]["effective_hz"] for k in keys], color="#2563eb")
        ax.set(
            xticks=range(len(keys)), xticklabels=labels, ylabel="Effective control Hz", title=title
        )
        ax.tick_params(axis="x", rotation=55)
        ax.axhline(30, color="black", linestyle="--")
    fig.suptitle("Active XR, injected committed RECORD — not headset FPS")
    fig.tight_layout()
    fig.savefig(out / "effective-hz.png", dpi=150)
    plt.close(fig)
    if longkeys:
        fig, ax = plt.subplots(figsize=(9, 4))
        bottom = np.zeros(len(longkeys))
        names = sorted(set().union(*(pooled[k]["stages"] for k in longkeys)))
        for name in names + ["unattributed"]:
            vals = [
                pooled[k]["residual_ms"]["mean"]
                if name == "unattributed"
                else pooled[k]["stages"].get(name, {"mean": 0})["mean"]
                for k in longkeys
            ]
            ax.bar(range(len(longkeys)), vals, bottom=bottom, label=name)
            bottom += vals
        ax.axhline(1000 / 30, color="black", linestyle="--")
        ax.set(
            xticks=range(len(longkeys)),
            xticklabels=[k.split("/")[1] + "\n" + k.split("/")[2] for k in longkeys],
            ylabel="ms/control",
            title="33.333 ms budget — disjoint top-level stages only",
        )
        ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1, 1))
        fig.tight_layout()
        fig.savefig(out / "control-budget.png", dpi=150)
        plt.close(fig)
    gpu_results = [
        r
        for r in results
        if Path(r["path"]).name.startswith("gpu-")
        and r.get("latest_published_gpu_pass", {}).get("rtx_ms")
    ]
    if gpu_results:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(
            [Path(r["path"]).name for r in gpu_results],
            [r["latest_published_gpu_pass"]["rtx_ms"]["mean"] for r in gpu_results],
            color="#22c55e",
        )
        ax.set(
            ylabel="RTX GPU ms / latest published pass",
            title="Separate profiler runs; not additive host control cost",
        )
        fig.tight_layout()
        fig.savefig(out / "rtx-pass.png", dpi=150)
        plt.close(fig)

    selected = {}
    for label, names in {
        "T0": [f"temporal-t0-r{i}" for i in range(1, 4)],
        "T1": ["temporal-t1"],
        "T2": [f"temporal-t2-r{i}" for i in range(1, 4)],
        "T3 app OFF": ["temporal-t3"],
        "T3 low latency OFF": ["temporal-t3-low-latency-off"],
        "T4 FSD OFF": ["temporal-t4"],
        "T5 tiled": ["temporal-t5"],
        "T6 two renders": ["temporal-t6-double"],
        "T2 tiled": ["temporal-t2-batch"],
        "T6 prime (moving)": [f"temporal-prime-moving-r{i}" for i in range(1, 4)],
        "T6 prime tiled": [
            "temporal-prime-batch-moving",
            "temporal-prime-batch-moving-r2",
            "temporal-prime-batch-moving-r3",
        ],
    }.items():
        runs = [r for r in results if Path(r["path"]).name in names and r.get("oracle")]
        if runs:
            selected[label] = {
                "runs": [Path(r["path"]).name for r in runs],
                "count": sum(r["oracle"]["count"] for r in runs),
                "histograms": {
                    role: {
                        off: sum(r["oracle"]["histograms"].get(role, {}).get(off, 0) for r in runs)
                        for off in ["0", "-1", "-2", "-3", "unresolved"]
                    }
                    for role in ["left_wrist", "right_wrist", "scene"]
                },
                **{
                    key: sum(r["oracle"].get(key, 0) for r in runs)
                    for key in [
                        "all_N",
                        "all_N_minus_1",
                        "any_N_minus_2_or_3",
                        "unresolved",
                        "cross_view_disagreement",
                    ]
                },
            }
    (out / "temporal-results.json").write_text(json.dumps(selected, indent=2) + "\n")
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharey=True)
    for ax, role in zip(axes, ["left_wrist", "right_wrist", "scene"]):
        bottom = np.zeros(len(selected))
        for off, color in zip(
            ["0", "-1", "-2", "-3", "unresolved"],
            ["#16a34a", "#ef4444", "#f97316", "#8b5cf6", "#94a3b8"],
        ):
            vals = [100 * v["histograms"][role][off] / v["count"] for v in selected.values()]
            ax.bar(range(len(selected)), vals, bottom=bottom, color=color, label=off)
            bottom += vals
        ax.set(title=role, xticks=range(len(selected)), xticklabels=list(selected), ylim=(0, 100))
        ax.tick_params(axis="x", rotation=80)
    axes[0].set_ylabel("Boundary classification (%)")
    axes[-1].legend(title="Offset", bbox_to_anchor=(1, 1))
    fig.tight_layout()
    fig.savefig(out / "temporal-offsets.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 3))
    for i, (label, v) in enumerate(selected.items()):
        if v["unresolved"] == v["count"]:
            ax.text(i, 1, "unresolved", rotation=90, ha="center")
        else:
            ax.scatter(i, 100 * v["cross_view_disagreement"] / v["count"], color="#dc2626")
    ax.set(
        xticks=range(len(selected)),
        xticklabels=list(selected),
        ylabel="Disagreeing bundles (%)",
        ylim=(-1, 10),
        title="Observed disagreement; all-unresolved results are not zero disagreement",
    )
    ax.tick_params(axis="x", rotation=60)
    fig.tight_layout()
    fig.savefig(out / "cross-view-disagreement.png", dpi=150)
    plt.close(fig)
    points = [
        ("Current", "xr-smoke/t0/c3/w300-m300", "T0"),
        ("Tiled current", "xr-smoke/t0/c3-batch/w300-m300", "T5 tiled"),
        ("Replicator", "xr-smoke/t2/c3/w300-m300", "T2"),
        ("Prime extraction", "xr-smoke/t6-prime-extraction/c3/w300-m3000", "T6 prime (moving)"),
        ("Prime tiled", "xr-smoke/t6-prime-extraction/c3-batch/w300-m3000", "T6 prime tiled"),
    ]
    fig, ax = plt.subplots(figsize=(8, 4))
    for label, key, temporal in points:
        if key in pooled and temporal in selected:
            x = pooled[key]["first_300_matched_ms"]["mean"]
            y = 100 * selected[temporal]["all_N"] / selected[temporal]["count"]
            ax.scatter(x, y)
            ax.annotate(
                label,
                (x, y),
                xytext=(3, -15 if label == "Tiled current" else 5),
                textcoords="offset points",
            )
    ax.axvline(1000 / 30, color="black", linestyle="--")
    ax.set(
        xlabel="Mean committed RECORD ms/control (300-control comparison)",
        ylabel="Fully current bundles in separate content assay (%)",
        ylim=(-10, 115),
        title="Correctness versus cost — matched configuration, separate stimuli",
    )
    fig.tight_layout()
    fig.savefig(out / "correctness-cost.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    analyze(args.root, args.output)


if __name__ == "__main__":
    main()
