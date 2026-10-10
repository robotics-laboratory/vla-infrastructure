"""Compare existing host tick logs; never launch simulation or mutate inputs."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

CASES = [
    (1, "Native prototype", "live30-deep-20261009/full-cpu-xr-original-ik-enabled"),
    (2, "Kit + OVRTX mirror", "live30-deep-20261009/full-cpu-xr-live-mirror-long"),
    (3, "Standalone + mirror", "live30-meaningful-episode-20261009/reach-demo08"),
    (4, "Mirror + background export", "live30-resource-20261010/matrix01/uncapped-p-isolated/recording"),
    (5, "Main-scene native live", "native-live-20261010/callback-native-final-0821/recording"),
    (6, "Event-ACK preview", "native-deep-20261010/cuda-event-long-01/recording"),
    (7, "Full geometry/source proof", "native-deep-20261010/source-bound-live-01/recording"),
    (8, "Final CPU source-bound soak", "native-deep-20261010/source-bound-identity-soak-12/recording"),
]
STAGES = {
    "simulation_advance": "Advance (includes waits)",
    "injected_decision_apply": "Decision/apply",
    "successor_capture": "Successor capture",
    "causal_commit_and_record": "Commit/record",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = {"schema": "architecture_budget_v1", "new_simulation_runs": 0, "cases": []}
    for iteration, label, relative in CASES:
        path = args.root / relative / "performance.jsonl"
        raw = path.read_bytes()
        rows = [json.loads(line) for line in raw.splitlines()]
        steps = [r for r in rows if r["event"] == "performance_step" and r["post_warmup"]]
        summary = [r for r in rows if r["event"] == "performance_summary"][-1]
        assert all(b["step"] == a["step"] + 1 for a, b in zip(steps, steps[1:]))
        assert all(
            abs(sum(r["stage_ms"].values()) + r["unattributed_ms"] - r["total_ms"]) < 1e-7
            for r in steps
        )
        # Body k belongs to the following start-to-start interval k -> k+1.
        bodies = steps[:-1]
        wall = [r["start_to_start_ms"] for r in steps[1:]]
        assert all(w - b["total_ms"] >= -0.001 for w, b in zip(wall, bodies))
        mean = statistics.mean(wall)
        stages = {k: statistics.mean(r["stage_ms"][k] for r in bodies) for k in STAGES}
        stages["service_residual"] = mean - sum(stages.values())
        assert stages["service_residual"] >= 0
        assert abs(1000 / mean - summary["effective_wall_hz"]) < 1e-8
        result["cases"].append({
            "iteration": iteration, "label": label, "source": str(path),
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "intervals": len(wall), "mean_ms": mean, "hz": 1000 / mean,
            "stages_mean_ms": stages,
            "budget_headroom_ms": {"50hz": 20 - mean, "30hz": 1000 / 30 - mean},
        })
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result["limitations"] = [
        "No new runs; differing scene/physics/settings/warmup scopes are not a causal A/B.",
        "Host elapsed stages contain GPU waits, overlapping workers are not added.",
        "Service/residual includes unlisted work; this is not GPU kernel attribution.",
        "Master whole-session and partial historical profiles are not compatible stage partitions.",
        "Prototype/mirror/sourceproof scopes have different correctness qualifications; see report.",
    ]
    (args.output / "overview_budget.json").write_text(json.dumps(result, indent=2) + "\n")
    fig, ax = plt.subplots(figsize=(12, 6))
    cases = result["cases"]
    left = [0.0] * len(cases)
    for key, label in {**STAGES, "service_residual": "Service/residual"}.items():
        values = [c["stages_mean_ms"][key] for c in cases]
        ax.barh(range(len(cases)), values, left=left, label=label)
        left = [a + b for a, b in zip(left, values)]
    ax.set_yticks(range(len(cases)), [f'{c["iteration"]}. {c["label"]}' for c in cases])
    ax.invert_yaxis()
    ax.axvline(20, color="black", linestyle="--", label="50 Hz budget")
    ax.axvline(1000 / 30, color="gray", linestyle=":", label="30 Hz budget")
    ax.set_xlim(0, 38)
    ax.set_xlabel("Mean host wall milliseconds per control tick")
    ax.set_title("Architecture scopes: existing runs, no Quest; not a causal A/B")
    for i, c in enumerate(cases):
        ax.text(c["mean_ms"] + 0.2, i, f'{c["mean_ms"]:.2f} ms', va="center", fontsize=9)
    ax.legend(loc="upper center", bbox_to_anchor=(0.4, -0.15), ncol=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(args.output / "overview_budget.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
