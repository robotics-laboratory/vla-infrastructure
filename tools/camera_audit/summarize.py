"""Summarize every retained control; never trim tails or substitute missing metrics."""

import argparse
from collections import defaultdict
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    results = [run_summary(p.parent) for p in sorted(args.root.glob("*/launch.json"))]
    args.output.mkdir(exist_ok=True)
    (args.output / "results.json").write_text(
        json.dumps([{k: v for k, v in r.items() if k != "rows"} for r in results], indent=2) + "\n"
    )
    groups = defaultdict(list)
    for result in results:
        if result["path"].split("/")[-1].startswith("cost-") and result.get("exit_code") == 0:
            a = result["arguments"]
            key = f"{a['mode']}/{a['temporal']}/{a['cost']}" + ("-batch" if a["batch"] else "")
            groups[key].extend(result.get("rows", []))
    pooled = {
        key: {
            "control_ms": distribution([r["total_ms"] for r in rows]),
            "stages": {
                name: distribution([r["nested_stage_ms"].get(name, 0) for r in rows])
                for name in sorted(set().union(*(r["nested_stage_ms"] for r in rows)))
            },
        }
        for key, rows in groups.items()
    }
    (args.output / "pooled.json").write_text(json.dumps(pooled, indent=2) + "\n")
    if groups:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        for key, rows in sorted(groups.items()):
            values = np.sort([r["total_ms"] for r in rows])
            axes[0].plot(values, np.arange(1, len(values) + 1) / len(values), label=key)
        axes[0].axvline(1000 / 30, color="black", linestyle="--")
        axes[0].set(xlabel="Control latency (ms), every sample", ylabel="Cumulative probability")
        axes[0].legend()
        keys = sorted(pooled)
        axes[1].bar(keys, [1000 / pooled[k]["control_ms"]["mean"] for k in keys])
        axes[1].axhline(30, color="black", linestyle="--")
        axes[1].set(ylabel="Effective control Hz", title="Matched no-client RECORD; preview off")
        fig.tight_layout()
        fig.savefig(args.output / "cost-distributions.png", dpi=150)


if __name__ == "__main__":
    main()
