"""Offline join of exact monotonic recording events; no simulator/GPU imports."""

import argparse
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def stats(values):
    a = np.asarray(values, dtype=float)
    return dict(count=len(a), p50_ms=float(np.percentile(a, 50)),
                p95_ms=float(np.percentile(a, 95)), max_ms=float(a.max()),
                min_ms=float(a.min())) if len(a) else None


def analyze(directory):
    rows = lines(directory / "mirror/worker-rows.jsonl")
    events = lines(directory / "host-events.jsonl")
    result = json.loads((directory / "result.json").read_text())
    n = result["transitions"]["committed_frames"]
    checks = {"run_passed": result["passed"], "source_sequence":
              [r["source_id"] for r in rows] == list(range(n + 1)),
              "source_physics_progression": all(b["physics_step"] == a["physics_step"] + 4
                                               for a, b in zip(rows, rows[1:]))}
    intervals = {}
    pairs = {
        "state_receipt_to_sample": ("state_received_monotonic_ns", "observation_sample_monotonic_ns"),
        "sample_to_enqueue": ("observation_sample_monotonic_ns", "enqueued_ns"),
        "enqueue_to_ipc_receive": ("enqueued_ns", "ipc_received_monotonic_ns"),
        "enqueue_to_triplet_submission": ("enqueued_ns", "worker_render_submitted_monotonic_ns"),
    }
    for name, (start, end) in pairs.items():
        delays = [(r[end] - r[start]) / 1e6 for r in rows]
        intervals[name] = dict(initial_ms=delays[0], steady=stats(delays[1:]))
        checks[name + "_nonnegative"] = min(delays) >= 0
    checks["sample_inside_capture"] = all(
        r["observation_capture_begin_monotonic_ns"] <= r["observation_sample_monotonic_ns"]
        <= r["observation_capture_end_monotonic_ns"] for r in rows)
    with h5py.File(directory / "episode/session.hdf5") as hdf:
        episode = next(iter(hdf["episodes"].values()))
        trans = episode["d0/committed_transition"]
        checks["hdf_sources_exact"] = np.array_equal(trans["observation_capture_sequence"][:], np.arange(n))
        checks["hdf_successors_exact"] = np.array_equal(trans["successor_capture_sequence"][:], np.arange(1, n + 1))
        checks["hdf_physics_exact"] = np.array_equal(episode["meta/time/physics_step"][:],
                                                    [r["physics_step"] for r in rows[:-1]])
        checks["hdf_wall_equals_worker_source_wall"] = max(abs(float(value) * 1e9 - row["source_wall_ns"])
            for value, row in zip(episode["meta/time/wall_time"][:], rows)) < 1024
    by_kind = {name: [e for e in events if e["event"] == name] for name in
               ("capture_observation", "decision_solve", "_apply", "_advance", "capture_successor", "commit_transition")}
    checks["one_event_each_control"] = all(len(v) == n for v in by_kind.values())
    for name, values in by_kind.items():
        intervals[name + "_duration"] = stats([(v["end_monotonic_ns"] - v["begin_monotonic_ns"]) / 1e6
                                               for v in values])
    age_values = {"sample_to_apply": [], "state_receipt_to_apply": [], "sample_to_hdf_commit": []}
    for i in range(n):
        observation, decision, apply, advance, successor, commit = [by_kind[k][i] for k in by_kind]
        checks[f"control_order_{i}"] = (observation["end_monotonic_ns"] <= decision["begin_monotonic_ns"]
            <= decision["end_monotonic_ns"] <= apply["begin_monotonic_ns"]
            <= apply["end_monotonic_ns"] <= advance["begin_monotonic_ns"]
            <= advance["end_monotonic_ns"] <= successor["begin_monotonic_ns"]
            <= successor["end_monotonic_ns"] <= commit["begin_monotonic_ns"]
            <= commit["end_monotonic_ns"])
        checks[f"physics_phases_{i}"] = all(e["physics_step_after"] == rows[i]["physics_step"]
            for e in (observation, decision, apply)) and all(e["physics_step_after"] == rows[i + 1]["physics_step"]
            for e in (advance, successor, commit))
        checks[f"source_token_phases_{i}"] = (observation["source_id"] == commit["source_id"] == i
            and successor["source_id"] == commit["successor_source_id"] == i + 1)
        age_values["sample_to_apply"].append((apply["begin_monotonic_ns"] - rows[i]["observation_sample_monotonic_ns"]) / 1e6)
        age_values["state_receipt_to_apply"].append((apply["begin_monotonic_ns"] - rows[i]["state_received_monotonic_ns"]) / 1e6)
        age_values["sample_to_hdf_commit"].append((commit["end_monotonic_ns"] - rows[i]["observation_sample_monotonic_ns"]) / 1e6)
    for name, values in age_values.items():
        intervals[name] = dict(initial_ms=values[0], steady=stats(values[1:]))
    packets = []
    for role in range(3):
        ledger = lines(directory / f"mirror/media/role{role}/packets.jsonl")
        checks[f"packet_role{role}_sequence"] = [p["submitted_source_tag"] for p in ledger] == list(range(n + 1))
        checks[f"packet_role{role}_write_after_ready"] = all(
            p["packet_write_completed_monotonic_ns"] >= p["packet_ready_monotonic_ns"] for p in ledger)
        entry = dict(role=role, count=len(ledger), flush_packets=sum(p["flush"] for p in ledger))
        for field in ("enqueued_ns", "observation_sample_monotonic_ns", "state_received_monotonic_ns"):
            values = [(p["packet_ready_monotonic_ns"] - rows[p["submitted_source_tag"]][field]) / 1e6
                      for p in ledger]
            entry[field + "_to_packet_ready"] = dict(initial_ms=values[0], steady=stats(values[1:]),
                nonflush_steady=stats([v for v, p in zip(values[1:], ledger[1:]) if not p["flush"]]))
        entry["packet_ready_to_python_write"] = stats([
            (p["packet_write_completed_monotonic_ns"] - p["packet_ready_monotonic_ns"]) / 1e6 for p in ledger])
        packets.append(entry)
    inputs = [directory / "result.json", directory / "host-events.jsonl", directory / "episode/session.hdf5",
              directory / "mirror/worker-rows.jsonl",
              *[directory / f"mirror/media/role{r}/packets.jsonl" for r in range(3)]]
    return dict(schema="recording_exact_host_latency_v1", input=str(directory), checks=checks,
                all_checks_passed=all(checks.values()), intervals=intervals, packets=packets,
                pace_hz=result["arguments"]["pace_hz"], quest_connected=False,
                complete_hz=result["complete_action_and_camera_hz_with_encode_tail"],
                timing_semantics="Host CLOCK_MONOTONIC; packet-ready at Encode return; writes are not durable fsync",
                provenance={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = analyze(args.input)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(passed=report["all_checks_passed"], complete_hz=report["complete_hz"],
                          failed=[k for k, v in report["checks"].items() if not v])))
    raise SystemExit(0 if report["all_checks_passed"] else 1)
