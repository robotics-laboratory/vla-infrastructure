"""Rebuild the small report summary and plots from retained per-control raw runs.

Run with the declared Isaac environment Python. Cohort membership is explicit in
cohorts.json; no slow controls are removed.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import csv
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "tools" / "camera_audit"))
from summarize import distribution, run_summary  # noqa: E402

DEADLINE = 1000 / 30
RAW = Path("/data/ebulochkin/vla-runtime/evidence/20260924_vr_record_runtime_optimization_audit")


def _plot(path: str) -> None:
    plt.grid(axis="y", color="#d9dde4", linewidth=0.7)
    plt.tight_layout()
    plt.savefig(HERE / path, dpi=170)
    plt.close()


def _performance_rows(run: dict) -> list[dict]:
    return run.get("rows", [])


def _gpu_window(path: Path, run: dict) -> dict:
    launch = json.loads((path / "launch.json").read_text())
    rows = _performance_rows(run)
    gpu = path / "gpu.csv"
    if not rows or not gpu.is_file():
        return {}
    offset = launch["started_unix"] - launch["started_monotonic_ns"] / 1e9
    first = offset + rows[0]["monotonic_ns"] / 1e9 - rows[0]["total_ms"] / 1000
    last = offset + rows[-1]["monotonic_ns"] / 1e9
    samples = []
    for record in list(csv.reader(gpu.read_text().splitlines()))[1:]:
        try:
            timestamp = (
                datetime.strptime(record[0], "%Y/%m/%d %H:%M:%S.%f")
                .replace(tzinfo=timezone.utc).timestamp()
                + launch["timezone_seconds_west"]
            )
            if first <= timestamp <= last:
                samples.append([float(value.split()[0]) for value in record[1:]])
        except (ValueError, IndexError):
            continue
    return {
        key: distribution([sample[index] for sample in samples])
        for index, key in enumerate(("gpu_utilization_percent", "vram_mib", "gpu_power_w"))
    }


def main() -> None:
    selected = json.loads((HERE / "cohorts.json").read_text())
    all_runs = {
        p.parent.name: run_summary(p.parent) for p in sorted(RAW.glob("*/launch.json"))
    }
    groups = []
    for definition in selected["groups"]:
        names = definition["runs"]
        rows = [row for name in names for row in _performance_rows(all_runs[name])]
        if not rows:
            raise ValueError(f"empty selected cohort: {definition['id']}")
        for name in names:
            run = all_runs[name]
            expected = run["arguments"]["measured"]
            if run["exit_code"] != 0 or len(_performance_rows(run)) != expected:
                raise ValueError(f"invalid selected run {name}")
        control = distribution([row["total_ms"] for row in rows])
        top_names = sorted({key for row in rows for key in row["stage_ms"]})
        nested_names = sorted({key for row in rows for key in row["nested_stage_ms"]})
        flush = [row for row in rows if row["nested_stage_ms"].get("hdf_flush_ms", 0) > 0]
        nonflush = [row for row in rows if row["nested_stage_ms"].get("hdf_flush_ms", 0) == 0]
        groups.append(
            {
                **definition,
                "count": len(rows),
                "control_ms": control,
                "effective_hz": 1000 / control["mean"],
                "deadline_misses": sum(row["total_ms"] > DEADLINE for row in rows),
                "mean_headroom_ms": DEADLINE - control["mean"],
                "p99_headroom_ms": DEADLINE - control["p99"],
                "stage_ms": {
                    key: distribution([row["stage_ms"].get(key, 0) for row in rows])
                    for key in top_names
                },
                "nested_stage_ms": {
                    key: distribution([row["nested_stage_ms"].get(key, 0) for row in rows])
                    for key in nested_names
                },
                "flush_controls": len(flush),
                "flush_control_ms": distribution([row["total_ms"] for row in flush]),
                "nonflush_control_ms": distribution([row["total_ms"] for row in nonflush]),
                "conditional_flush_ms": distribution(
                    [row["nested_stage_ms"]["hdf_flush_ms"] for row in flush]
                ),
            }
        )
    run_output = []
    for name, run in all_runs.items():
        summary = {key: value for key, value in run.items() if key != "rows"}
        summary["run"] = name
        summary["gpu_measured_window"] = _gpu_window(RAW / name, run)
        summary["artifact_hdf_bytes"] = sum(
            path.stat().st_size for path in (RAW / name).rglob("*.hdf5")
        )
        summary["classification"] = selected.get("run_classification", {}).get(
            name, "retained_unselected"
        )
        run_output.append(summary)
    (HERE / "results.json").write_text(
        json.dumps(
            {"schema": "vr_record_runtime_optimization_results_v1", "deadline_ms": DEADLINE,
             "selection": selected, "groups": groups, "runs": run_output},
            indent=2,
        ) + "\n"
    )

    labels = [group["label"] for group in groups]
    x = np.arange(len(groups))
    plt.figure(figsize=(max(8, len(groups) * 1.25), 4.5))
    plt.bar(x, [group["effective_hz"] for group in groups], color="#2463a6")
    plt.axhline(30, color="#ba3f40", linestyle="--", label="30 Hz")
    plt.xticks(x, labels, rotation=25, ha="right")
    plt.ylabel("Effective logical controls / s")
    plt.legend()
    _plot("effective-hz.png")

    plt.figure(figsize=(max(8, len(groups) * 1.35), 4.5))
    for offset, metric, color in [(-0.25, "mean", "#2463a6"), (0, "p95", "#58a8b4"),
                                  (0.25, "p99", "#d28a3b")]:
        plt.bar(x + offset, [group["control_ms"][metric] for group in groups],
                width=0.24, color=color, label=metric)
    plt.axhline(DEADLINE, color="#ba3f40", linestyle="--", label="33.333 ms")
    plt.xticks(x, labels, rotation=25, ha="right")
    plt.ylabel("ms / control")
    plt.legend()
    _plot("latency-by-candidate.png")

    plt.figure(figsize=(max(8, len(groups) * 1.25), 4.5))
    plt.bar(x - 0.18, [group["mean_headroom_ms"] for group in groups], width=0.35,
            label="Mean", color="#2d877c")
    plt.bar(x + 0.18, [group["p99_headroom_ms"] for group in groups], width=0.35,
            label="p99", color="#a64e55")
    plt.axhline(0, color="black", linewidth=1)
    plt.xticks(x, labels, rotation=25, ha="right")
    plt.ylabel("Headroom to 33.333 ms (ms)")
    plt.legend()
    _plot("headroom.png")

    plt.figure(figsize=(max(8, len(groups) * 1.25), 4.7))
    bottom = np.zeros(len(groups))
    stage_names = sorted({key for group in groups for key in group["stage_ms"]})
    for stage in stage_names:
        values = np.array([group["stage_ms"].get(stage, {}).get("mean", 0) for group in groups])
        plt.bar(x, values, bottom=bottom, label=stage)
        bottom += values
    plt.xticks(x, labels, rotation=25, ha="right")
    plt.ylabel("Disjoint top-level wall stages (ms/control)")
    plt.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1))
    _plot("stage-time.png")

    flush_groups = [group for group in groups if group["id"] in {
        "H0", "H128", "CPU-P", "OPT-COMBINED"
    }]
    fx = np.arange(len(flush_groups))
    plt.figure(figsize=(max(7, len(flush_groups) * 1.4), 4.5))
    plt.bar(fx - 0.2, [group["control_ms"]["p99"] for group in flush_groups],
            width=0.4, label="All controls p99", color="#2463a6")
    plt.bar(fx + 0.2, [group["nonflush_control_ms"]["p99"] for group in flush_groups],
            width=0.4, label="Nonflush controls p99", color="#58a8b4")
    plt.axhline(DEADLINE, color="#ba3f40", linestyle="--")
    plt.xticks(fx, [f"{g['label']}\n{g['flush_controls']} flushes" for g in flush_groups])
    plt.ylabel("p99 ms/control")
    plt.legend()
    _plot("flush-tail.png")

    render_groups = [group for group in groups if group["id"] in {"R0-render-screen", "R1"}]
    rx = np.arange(len(render_groups))
    plt.figure(figsize=(6.5, 4.5))
    for offset, key, color in [(-0.24, "render_app", "#2463a6"),
                               (0, "kit_visualizer_app_pump", "#58a8b4"),
                               (0.24, "native_physics_integration", "#d28a3b")]:
        plt.bar(rx + offset, [g["nested_stage_ms"].get(key, {}).get("mean", 0)
                              for g in render_groups], width=0.23, label=key, color=color)
    plt.xticks(rx, [g["label"] for g in render_groups])
    plt.ylabel("Nested diagnostic ms/control (nonadditive)")
    plt.legend(fontsize=8)
    _plot("renderer-comparison.png")

    baseline = next(group for group in groups if group["id"] == "R0")
    final_id = selected["final_id"]
    final = next(group for group in groups if group["id"] == final_id)
    saved = baseline["control_ms"]["mean"] - final["control_ms"]["mean"]
    plt.figure(figsize=(6.5, 4.5))
    plt.bar([0, 2], [baseline["control_ms"]["mean"], final["control_ms"]["mean"]],
            color=["#2463a6", "#2d877c"])
    plt.bar(1, abs(saved), bottom=min(baseline["control_ms"]["mean"],
                                  final["control_ms"]["mean"]),
            color="#6a9c56" if saved >= 0 else "#a64e55")
    plt.text(1, max(baseline["control_ms"]["mean"], final["control_ms"]["mean"]) + .2,
             f"{saved:+.3f} ms saved", ha="center")
    plt.axhline(DEADLINE, color="#ba3f40", linestyle="--", label="30 Hz deadline")
    plt.xticks([0, 1, 2], [baseline["label"], "Measured change", final["label"]])
    plt.ylabel("Mean ms/control; measured final, no additive assumption")
    plt.legend()
    _plot("optimization-waterfall.png")


if __name__ == "__main__":
    main()
