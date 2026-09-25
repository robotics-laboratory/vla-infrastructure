"""Print the existing S2 logger's final aggregate, excluding its warmup controls."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def summarize(path: Path) -> str:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not records or any(not isinstance(row, dict) for row in records):
        raise ValueError("Expected performance JSONL objects")
    if records[0].get("event") != "performance_log_started":
        raise ValueError("Missing performance header")
    if records[-1].get("event") != "performance_summary":
        raise ValueError("Incomplete log: missing final performance summary")
    if any(row.get("schema") != "piper_x_isaac_s2_performance_v1" for row in records):
        raise ValueError("Unsupported performance schema")
    if any(row.get("event") == "performance_summary" for row in records[1:-1]):
        raise ValueError("Unexpected data after final summary")
    summary = records[-1]
    measured = [
        row for row in records if row.get("event") == "performance_step" and row["post_warmup"]
    ]
    control = summary["control"]
    if not measured or control["samples"] != len(measured):
        raise ValueError("Incomplete log or no measured samples")

    def number(value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError("Expected numeric performance measurement")
        if not math.isfinite(value) or value < 0:
            raise ValueError("Invalid performance measurement")
        return f"{value:.6f}"

    lines = [f"performance: {path}", f"samples: {len(measured)}"]
    lines.append(f"effective_hz: {number(summary['effective_hz'])}")
    wall = summary.get("wall_control")
    if wall is not None:
        lines.append(f"wall_effective_hz: {number(summary['effective_wall_hz'])}")
        lines.append(f"wall_rtf: {number(summary['wall_rtf'])}")
        lines.append(
            f"wall_deadline_miss_fraction: {number(summary['wall_deadline_miss_fraction'])}"
        )
        for field in ("mean_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "p99_9_ms", "max_ms"):
            lines.append(f"wall_{field}: {number(wall[field])}")
    for field in ("mean_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms"):
        lines.append(f"{field}: {number(control[field])}")
    lines.append(f"deadline_miss_fraction: {number(summary['deadline_miss_fraction'])}")
    for label, stages in (
        ("stages (mean_ms / p95_ms)", summary["stages"]),
        ("nested stages NON-ADDITIVE (mean_ms / p95_ms)", summary["nested_stages_not_additive"]),
    ):
        lines.append(label + ":")
        for name, values in sorted(stages.items()):
            lines.append(f"  {name}: {number(values['mean_ms'])} / {number(values['p95_ms'])}")
    for name in ("unattributed", "instrumentation_write"):
        values = summary.get(name)
        lines.append(
            f"{name} mean_ms / p95_ms: {number(values['mean_ms'])} / {number(values['p95_ms'])}"
            if values
            else f"{name}: not_measured"
        )
    lines.append(
        "Body timings exclude log writes and inter-control work. Wall timings are "
        "start-to-start and exclude the interval crossing warmup. Nested stages "
        "are non-additive. Unlisted measurements are not_measured."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Completed performance.jsonl")
    args = parser.parse_args(argv)
    try:
        print(summarize(args.path))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
