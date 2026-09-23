"""Fail-closed paired benchmark contract for the production VR recorder.

The module is deliberately independent of Isaac imports.  The live S2 loop can
feed it precise timing boundaries and resource observations, while the report
builder and validator remain usable in ordinary unit tests and offline review.

One benchmark *pair* is two runs with the same ``pair_id`` and provenance: a
production run with recording disabled and the matching production HDF run.
The raw JSONL files are evidence; the derived JSON report binds them by SHA-256.
No default performance budget is invented.  With no threshold policy the
qualification state is explicitly ``threshold_pending``.  A supplied policy is
accepted only when it covers every required limit.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time
from typing import Any, Iterator


SCHEMA_VERSION = "piper_x_isaac_vr_recording_benchmark_v1"
THRESHOLD_SCHEMA_VERSION = "piper_x_isaac_vr_recording_benchmark_thresholds_v1"
REPORT_SCHEMA_VERSION = "piper_x_isaac_vr_recording_benchmark_report_v1"

CONDITIONS = frozenset({"baseline", "recording"})
TIMING_METRICS = (
    "control_loop_ms",
    "state_sampling_ms",
    "hdf_append_ms",
    "hdf_flush_ms",
    "render_ms",
    "xr_ms",
)
RESOURCE_METRICS = (
    "process_cpu_percent",
    "rss_bytes",
    "gpu_utilization_percent",
    "gpu_memory_bytes",
    "disk_read_bytes",
    "disk_write_bytes",
)
PAIRING_FIELDS = (
    "git_commit",
    "dirty_status_sha256",
    "environment_sha256",
    "measurement_provenance_sha256",
    "scene_snapshot_sha256",
    "visual_provenance_sha256",
    "source_profile",
    "quest_session_id",
    "target_hz",
    "warmup_steps",
    "measured_steps",
    "headset_connected",
)
PERCENTILES = ("p50", "p95", "p99")


def _required_threshold_paths() -> tuple[str, ...]:
    paths: list[str] = []
    for name in ("control_loop_ms", "state_sampling_ms", "render_ms", "xr_ms"):
        for percentile in PERCENTILES:
            paths.append(f"overhead.timings.{name}.{percentile}_ratio")
    for name in ("hdf_append_ms", "hdf_flush_ms"):
        for percentile in PERCENTILES:
            paths.append(f"recording.timings.{name}.{percentile}_ms")
    for name in ("process_cpu_percent", "gpu_utilization_percent"):
        paths.append(f"overhead.resources.{name}.p95_delta")
    for name in ("rss_bytes", "gpu_memory_bytes"):
        paths.append(f"overhead.resources.{name}.max_delta")
    paths.extend(
        (
            "recording.disk.read_bytes_per_second",
            "recording.disk.write_bytes_per_second",
            "recording.disk.artifact_bytes_per_committed_frame",
            "recording.outcomes.drop_fraction",
            "recording.outcomes.rejection_fraction",
            "recording.outcomes.deadline_miss_fraction",
        )
    )
    return tuple(paths)


REQUIRED_THRESHOLD_PATHS = _required_threshold_paths()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _finite_number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return result


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot summarize an empty sample")
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: Sequence[float], *, suffix: str = "") -> dict[str, float | int]:
    if not values:
        raise ValueError("cannot summarize an empty sample")
    return {
        "samples": len(values),
        f"mean{suffix}": statistics.fmean(values),
        f"p50{suffix}": _percentile(values, 0.50),
        f"p95{suffix}": _percentile(values, 0.95),
        f"p99{suffix}": _percentile(values, 0.99),
        f"max{suffix}": max(values),
    }


def _validate_digest(value: Any, label: str) -> str:
    text = str(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} must be lowercase SHA-256 hex")
    return text


def validate_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize the immutable header for one raw run."""

    required = {
        "pair_id",
        "condition",
        "run_id",
        "git_commit",
        "dirty_status_sha256",
        "environment_sha256",
        "measurement_provenance_sha256",
        "scene_snapshot_sha256",
        "visual_provenance_sha256",
        "source_profile",
        "quest_session_id",
        "target_hz",
        "warmup_steps",
        "measured_steps",
        "headset_connected",
        "pair_order",
    }
    if set(identity) != required:
        raise ValueError(
            f"identity fields {sorted(identity)} != required fields {sorted(required)}"
        )
    result = dict(identity)
    for field in ("pair_id", "run_id", "source_profile", "quest_session_id"):
        if not isinstance(result[field], str) or not result[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    if result["condition"] not in CONDITIONS:
        raise ValueError(f"condition must be one of {sorted(CONDITIONS)}")
    git_commit = str(result["git_commit"])
    if len(git_commit) != 40 or any(
        character not in "0123456789abcdef" for character in git_commit
    ):
        raise ValueError("git_commit must be lowercase 40-character hex")
    for field in (
        "dirty_status_sha256",
        "environment_sha256",
        "measurement_provenance_sha256",
        "scene_snapshot_sha256",
        "visual_provenance_sha256",
    ):
        result[field] = _validate_digest(result[field], field)
    result["target_hz"] = _finite_number(result["target_hz"], "target_hz", minimum=0.001)
    for field, minimum in (("warmup_steps", 0), ("measured_steps", 1)):
        if isinstance(result[field], bool) or not isinstance(result[field], int):
            raise ValueError(f"{field} must be an integer")
        if result[field] < minimum:
            raise ValueError(f"{field} must be >= {minimum}")
    if not isinstance(result["headset_connected"], bool):
        raise ValueError("headset_connected must be boolean")
    if result["pair_order"] not in (1, 2):
        raise ValueError("pair_order must be 1 or 2")
    return result


class BenchmarkRunLogger:
    """Write one append-only benchmark evidence JSONL.

    All stage values are per-control-step host-wall milliseconds.  Repeated
    ``stage`` blocks for one metric are additive.  For baseline runs HDF values
    must remain exactly zero; this distinguishes an explicit no-recording
    observation from a missing measurement.
    """

    def __init__(self, path: Path, identity: Mapping[str, Any]) -> None:
        self.path = path
        self.identity = validate_identity(identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("x", encoding="utf-8")
        self._active_step: int | None = None
        self._started_ns = 0
        self._timings: dict[str, float] = {}
        self._written_steps = 0
        self._last_counters = {"committed": 0, "rejected": 0, "dropped": 0}
        self._closed = False
        self._write(
            {
                "event": "benchmark_run_started",
                "schema": SCHEMA_VERSION,
                "identity": self.identity,
                "clock": "time.perf_counter_ns",
                "timing_semantics": "additive_host_wall_per_control_step",
                "resource_semantics": (
                    "CPU is process CPU over the step interval; RSS/GPU are observations; "
                    "disk read/write are process-I/O byte deltas for that step"
                ),
            }
        )
        self._stream.flush()

    def _write(self, payload: Mapping[str, Any]) -> None:
        self._stream.write(
            json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
        )

    def begin_step(self, step: int) -> None:
        if self._closed:
            raise RuntimeError("benchmark logger is closed")
        if self._active_step is not None:
            raise RuntimeError("previous benchmark step is still active")
        if isinstance(step, bool) or not isinstance(step, int) or step < 1:
            raise ValueError("step must be a positive integer")
        if step != self._written_steps + 1:
            raise ValueError("benchmark steps must be contiguous and one-based")
        self._active_step = step
        self._started_ns = time.perf_counter_ns()
        self._timings = {name: 0.0 for name in TIMING_METRICS if name != "control_loop_ms"}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if self._active_step is None:
            raise RuntimeError("begin_step() must precede stage()")
        if name not in self._timings:
            raise ValueError(f"unknown benchmark stage {name!r}")
        started_ns = time.perf_counter_ns()
        try:
            yield
        finally:
            self.add_stage(name, time.perf_counter_ns() - started_ns)

    def add_stage(self, name: str, elapsed_ns: int) -> None:
        if self._active_step is None:
            raise RuntimeError("begin_step() must precede add_stage()")
        if name not in self._timings:
            raise ValueError(f"unknown benchmark stage {name!r}")
        if isinstance(elapsed_ns, bool) or not isinstance(elapsed_ns, int) or elapsed_ns < 0:
            raise ValueError("elapsed_ns must be a nonnegative integer")
        self._timings[name] += elapsed_ns / 1_000_000.0

    def end_step(
        self,
        *,
        resources: Mapping[str, Any],
        committed: int,
        rejected: int,
        dropped: int,
        deadline_missed: bool,
    ) -> None:
        if self._active_step is None:
            raise RuntimeError("begin_step() must precede end_step()")
        if set(resources) != set(RESOURCE_METRICS):
            raise ValueError("resources must contain exactly the required resource metrics")
        normalized_resources = {
            name: _finite_number(resources[name], f"resources.{name}", minimum=0.0)
            for name in RESOURCE_METRICS
        }
        counters = {"committed": committed, "rejected": rejected, "dropped": dropped}
        for name, value in counters.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < self._last_counters[name]
            ):
                raise ValueError(f"{name} must be a monotonic nonnegative integer")
        if not isinstance(deadline_missed, bool):
            raise ValueError("deadline_missed must be boolean")
        timings = dict(self._timings)
        timings["control_loop_ms"] = (time.perf_counter_ns() - self._started_ns) / 1_000_000.0
        if self.identity["condition"] == "baseline" and (
            timings["hdf_append_ms"] != 0.0 or timings["hdf_flush_ms"] != 0.0
        ):
            raise ValueError("baseline run cannot contain HDF append or flush work")
        step = self._active_step
        self._write(
            {
                "event": "benchmark_step",
                "schema": SCHEMA_VERSION,
                "step": step,
                "post_warmup": step > self.identity["warmup_steps"],
                "monotonic_ns": time.monotonic_ns(),
                "timings_ms": timings,
                "resources": normalized_resources,
                "counters": counters,
                "deadline_missed": deadline_missed,
            }
        )
        self._written_steps += 1
        self._last_counters = counters
        self._active_step = None

    def close(self, *, recording_hdf5: Path | None = None) -> None:
        if self._closed:
            return
        if self._active_step is not None:
            raise RuntimeError("cannot close benchmark logger with an active step")
        total_expected = self.identity["warmup_steps"] + self.identity["measured_steps"]
        if self._written_steps != total_expected:
            raise RuntimeError(f"logged {self._written_steps} steps, expected {total_expected}")
        if self.identity["condition"] == "baseline":
            if recording_hdf5 is not None:
                raise ValueError("baseline must not advertise a recording artifact")
            artifact_path = None
            artifact_bytes = 0
            artifact_sha256 = None
        else:
            if recording_hdf5 is None:
                raise ValueError("recording run requires its finalized HDF5 artifact")
            artifact_path = recording_hdf5.resolve()
            if not artifact_path.is_file() or artifact_path.stat().st_size <= 0:
                raise ValueError("recording HDF5 artifact must be an existing non-empty file")
            artifact_bytes = artifact_path.stat().st_size
            artifact_sha256 = _sha256_file(artifact_path)
        self._write(
            {
                "event": "benchmark_run_completed",
                "schema": SCHEMA_VERSION,
                "steps": self._written_steps,
                "final_counters": self._last_counters,
                "artifact_bytes": artifact_bytes,
                "artifact_path": str(artifact_path) if artifact_path is not None else None,
                "artifact_sha256": artifact_sha256,
            }
        )
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        self._closed = True


@dataclass(frozen=True)
class BenchmarkRun:
    path: Path
    sha256: str
    identity: dict[str, Any]
    samples: tuple[dict[str, Any], ...]
    completion: dict[str, Any]


class ProcessResourceSampler:
    """Low-overhead Linux process resource sampler with an injected GPU probe.

    ``gpu_probe`` must read an already-running NVML/external sampler and return
    ``gpu_utilization_percent`` plus ``gpu_memory_bytes``.  Spawning
    ``nvidia-smi`` in the control loop is intentionally not implemented because
    it would perturb the latency distribution being qualified.
    """

    def __init__(self, gpu_probe: Callable[[], Mapping[str, Any]]) -> None:
        self.pid = os.getpid()
        self.gpu_probe = gpu_probe
        self._last_wall_ns = time.perf_counter_ns()
        self._last_cpu_ns = time.process_time_ns()
        self._last_io = self._read_io()

    def _read_io(self) -> tuple[int, int]:
        fields: dict[str, int] = {}
        for line in Path(f"/proc/{self.pid}/io").read_text().splitlines():
            name, value = line.split(":", 1)
            fields[name] = int(value.strip())
        return fields["read_bytes"], fields["write_bytes"]

    def _read_rss(self) -> int:
        resident_pages = int(Path(f"/proc/{self.pid}/statm").read_text().split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))

    def sample(self) -> dict[str, float | int]:
        now_wall_ns = time.perf_counter_ns()
        now_cpu_ns = time.process_time_ns()
        wall_delta = now_wall_ns - self._last_wall_ns
        cpu_delta = now_cpu_ns - self._last_cpu_ns
        current_io = self._read_io()
        gpu = self.gpu_probe()
        if set(gpu) != {"gpu_utilization_percent", "gpu_memory_bytes"}:
            raise ValueError("GPU probe must return utilization and memory exactly")
        result: dict[str, float | int] = {
            "process_cpu_percent": 100.0 * cpu_delta / wall_delta if wall_delta else 0.0,
            "rss_bytes": self._read_rss(),
            "gpu_utilization_percent": _finite_number(
                gpu["gpu_utilization_percent"], "gpu_utilization_percent", minimum=0.0
            ),
            "gpu_memory_bytes": _finite_number(
                gpu["gpu_memory_bytes"], "gpu_memory_bytes", minimum=0.0
            ),
            "disk_read_bytes": max(0, current_io[0] - self._last_io[0]),
            "disk_write_bytes": max(0, current_io[1] - self._last_io[1]),
        }
        self._last_wall_ns = now_wall_ns
        self._last_cpu_ns = now_cpu_ns
        self._last_io = current_io
        return result


def read_benchmark_run(path: Path) -> BenchmarkRun:
    """Read a complete raw log, rejecting partial or semantically incomplete input."""

    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict) or record.get("schema") != SCHEMA_VERSION:
                raise ValueError(f"{path}:{line_number}: wrong benchmark schema")
            records.append(record)
    if len(records) < 3:
        raise ValueError(f"{path}: incomplete benchmark log")
    if records[0].get("event") != "benchmark_run_started":
        raise ValueError(f"{path}: first record must be benchmark_run_started")
    if records[-1].get("event") != "benchmark_run_completed":
        raise ValueError(f"{path}: last record must be benchmark_run_completed")
    identity = validate_identity(records[0].get("identity", {}))
    samples = records[1:-1]
    expected_steps = identity["warmup_steps"] + identity["measured_steps"]
    if len(samples) != expected_steps:
        raise ValueError(f"{path}: sample count does not match identity")
    prior_counters = {"committed": 0, "rejected": 0, "dropped": 0}
    prior_monotonic_ns = -1
    for index, sample in enumerate(samples, 1):
        if sample.get("event") != "benchmark_step" or sample.get("step") != index:
            raise ValueError(f"{path}: benchmark steps must be contiguous")
        if sample.get("post_warmup") is not (index > identity["warmup_steps"]):
            raise ValueError(f"{path}: incorrect post_warmup marker at step {index}")
        monotonic_ns = sample.get("monotonic_ns")
        if isinstance(monotonic_ns, bool) or not isinstance(monotonic_ns, int):
            raise ValueError(f"{path}: invalid monotonic timestamp")
        if monotonic_ns <= prior_monotonic_ns:
            raise ValueError(f"{path}: timestamps are not strictly increasing")
        prior_monotonic_ns = monotonic_ns
        timings = sample.get("timings_ms")
        resources = sample.get("resources")
        counters = sample.get("counters")
        if not isinstance(timings, dict) or set(timings) != set(TIMING_METRICS):
            raise ValueError(f"{path}: incomplete timing sample")
        if not isinstance(resources, dict) or set(resources) != set(RESOURCE_METRICS):
            raise ValueError(f"{path}: incomplete resource sample")
        if not isinstance(counters, dict) or set(counters) != set(prior_counters):
            raise ValueError(f"{path}: incomplete counter sample")
        for name in TIMING_METRICS:
            _finite_number(timings[name], f"{path}:{index}:{name}", minimum=0.0)
        for name in RESOURCE_METRICS:
            _finite_number(resources[name], f"{path}:{index}:{name}", minimum=0.0)
        for name, value in counters.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < prior_counters[name]
            ):
                raise ValueError(f"{path}: non-monotonic counter {name}")
        if not isinstance(sample.get("deadline_missed"), bool):
            raise ValueError(f"{path}: deadline_missed must be boolean")
        if identity["condition"] == "baseline" and (
            timings["hdf_append_ms"] != 0.0 or timings["hdf_flush_ms"] != 0.0
        ):
            raise ValueError(f"{path}: baseline contains HDF work")
        prior_counters = counters
    completion = records[-1]
    if (
        completion.get("steps") != expected_steps
        or completion.get("final_counters") != prior_counters
    ):
        raise ValueError(f"{path}: completion counters do not match samples")
    artifact_bytes = completion.get("artifact_bytes")
    artifact_path = completion.get("artifact_path")
    artifact_sha256 = completion.get("artifact_sha256")
    if identity["condition"] == "baseline":
        if artifact_bytes != 0 or artifact_path is not None or artifact_sha256 is not None:
            raise ValueError(f"{path}: baseline advertises a recording artifact")
    else:
        if (
            isinstance(artifact_bytes, bool)
            or not isinstance(artifact_bytes, int)
            or artifact_bytes <= 0
        ):
            raise ValueError(f"{path}: recording artifact size is missing")
        _validate_digest(artifact_sha256, f"{path}:artifact_sha256")
        bound_artifact = Path(str(artifact_path))
        if not bound_artifact.is_absolute() or not bound_artifact.is_file():
            raise ValueError(f"{path}: bound recording artifact is missing")
        if bound_artifact.stat().st_size != artifact_bytes:
            raise ValueError(f"{path}: bound recording artifact size changed")
        if _sha256_file(bound_artifact) != artifact_sha256:
            raise ValueError(f"{path}: bound recording artifact hash mismatch")
    return BenchmarkRun(
        path=path.resolve(),
        sha256=_sha256_file(path),
        identity=identity,
        samples=tuple(samples),
        completion=completion,
    )


def _post_warmup(run: BenchmarkRun) -> tuple[dict[str, Any], ...]:
    samples = tuple(sample for sample in run.samples if sample["post_warmup"])
    if len(samples) != run.identity["measured_steps"]:
        raise ValueError(f"{run.path}: post-warmup sample count changed")
    return samples


def _condition_summary(runs: Sequence[BenchmarkRun]) -> dict[str, Any]:
    samples = tuple(sample for run in runs for sample in _post_warmup(run))
    condition = runs[0].identity["condition"]
    timings: dict[str, Any] = {}
    for name in TIMING_METRICS:
        values = [float(sample["timings_ms"][name]) for sample in samples]
        # HDF latency is an operation latency, not a zero-padded control-step
        # average.  Per-step disk growth is reported separately below.
        if condition == "recording" and name in {"hdf_append_ms", "hdf_flush_ms"}:
            values = [value for value in values if value > 0.0]
            if not values:
                raise ValueError(f"recording evidence has no measured {name} operation")
        timings[name] = _distribution(values, suffix="_ms")
    resources = {
        name: _distribution([float(sample["resources"][name]) for sample in samples])
        for name in RESOURCE_METRICS
    }
    counter_deltas: list[dict[str, int]] = []
    for run in runs:
        warmup_steps = int(run.identity["warmup_steps"])
        before = (
            run.samples[warmup_steps - 1]["counters"]
            if warmup_steps
            else {"committed": 0, "rejected": 0, "dropped": 0}
        )
        final = run.completion["final_counters"]
        counter_deltas.append({name: int(final[name]) - int(before[name]) for name in before})
    attempts = sum(
        int(row["committed"]) + int(row["rejected"]) + int(row["dropped"]) for row in counter_deltas
    )
    rejected = sum(int(row["rejected"]) for row in counter_deltas)
    dropped = sum(int(row["dropped"]) for row in counter_deltas)
    committed = sum(int(row["committed"]) for row in counter_deltas)
    if attempts == 0:
        raise ValueError(f"{condition} evidence has no measured control-boundary attempts")
    if condition == "recording" and committed == 0:
        raise ValueError("recording evidence has no committed HDF frames")
    deadline_misses = sum(bool(sample["deadline_missed"]) for sample in samples)
    elapsed_seconds = sum(
        float(sample["timings_ms"]["control_loop_ms"]) / 1000.0 for sample in samples
    )
    disk_read_bytes = sum(float(sample["resources"]["disk_read_bytes"]) for sample in samples)
    disk_write_bytes = sum(float(sample["resources"]["disk_write_bytes"]) for sample in samples)
    artifact_bytes = sum(int(run.completion["artifact_bytes"]) for run in runs)
    return {
        "run_count": len(runs),
        "sample_count": len(samples),
        "timings": timings,
        "resources": resources,
        "disk": {
            "read_bytes": disk_read_bytes,
            "write_bytes": disk_write_bytes,
            "read_bytes_per_second": disk_read_bytes / elapsed_seconds if elapsed_seconds else 0.0,
            "write_bytes_per_second": disk_write_bytes / elapsed_seconds
            if elapsed_seconds
            else 0.0,
            "artifact_bytes": artifact_bytes,
            "artifact_bytes_per_committed_frame": (
                artifact_bytes / committed if committed else math.inf
            ),
        },
        "outcomes": {
            "attempts": attempts,
            "committed": committed,
            "rejected": rejected,
            "dropped": dropped,
            "rejection_fraction": rejected / attempts if attempts else 0.0,
            "drop_fraction": dropped / attempts if attempts else 0.0,
            "deadline_misses": deadline_misses,
            "deadline_miss_fraction": deadline_misses / len(samples),
        },
    }


def _ratio(recording: float, baseline: float) -> float | None:
    if baseline == 0.0:
        return 1.0 if recording == 0.0 else None
    return recording / baseline


def _overhead(baseline: Mapping[str, Any], recording: Mapping[str, Any]) -> dict[str, Any]:
    timings: dict[str, Any] = {}
    for name in ("control_loop_ms", "state_sampling_ms", "render_ms", "xr_ms"):
        timings[name] = {}
        for percentile in PERCENTILES:
            key = f"{percentile}_ms"
            base = float(baseline["timings"][name][key])
            recorded = float(recording["timings"][name][key])
            timings[name][f"{percentile}_baseline_ms"] = base
            timings[name][f"{percentile}_recording_ms"] = recorded
            timings[name][f"{percentile}_delta_ms"] = recorded - base
            timings[name][f"{percentile}_ratio"] = _ratio(recorded, base)
    resources: dict[str, Any] = {}
    for name in RESOURCE_METRICS:
        resources[name] = {}
        percentiles = (
            ("p95",)
            if name
            in (
                "process_cpu_percent",
                "gpu_utilization_percent",
            )
            else ("max",)
        )
        for percentile in percentiles:
            base = float(baseline["resources"][name][percentile])
            recorded = float(recording["resources"][name][percentile])
            resources[name][f"{percentile}_baseline"] = base
            resources[name][f"{percentile}_recording"] = recorded
            resources[name][f"{percentile}_delta"] = recorded - base
            resources[name][f"{percentile}_ratio"] = _ratio(recorded, base)
    return {"timings": timings, "resources": resources}


def _value_at_path(payload: Mapping[str, Any], path: str) -> Any:
    value: Any = payload
    for component in path.split("."):
        if not isinstance(value, Mapping) or component not in value:
            raise ValueError(f"report has no threshold metric {path!r}")
        value = value[component]
    return value


def _evaluate_thresholds(report: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema") != THRESHOLD_SCHEMA_VERSION:
        raise ValueError("wrong benchmark threshold schema")
    if set(policy) != {"schema", "minimum_pairs", "minimum_steps_per_run", "limits"}:
        raise ValueError("threshold policy has unexpected or missing fields")
    minimum_pairs = policy["minimum_pairs"]
    minimum_steps = policy["minimum_steps_per_run"]
    if isinstance(minimum_pairs, bool) or not isinstance(minimum_pairs, int) or minimum_pairs < 1:
        raise ValueError("minimum_pairs must be a positive integer")
    if isinstance(minimum_steps, bool) or not isinstance(minimum_steps, int) or minimum_steps < 1:
        raise ValueError("minimum_steps_per_run must be a positive integer")
    limits = policy["limits"]
    if not isinstance(limits, Mapping) or set(limits) != set(REQUIRED_THRESHOLD_PATHS):
        missing = sorted(set(REQUIRED_THRESHOLD_PATHS).difference(limits or {}))
        extra = sorted(set(limits or {}).difference(REQUIRED_THRESHOLD_PATHS))
        raise ValueError(f"threshold coverage must be exact; missing={missing}, extra={extra}")
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "metric": "pair_count",
            "observed": report["pair_count"],
            "operator": ">=",
            "limit": minimum_pairs,
            "passed": report["pair_count"] >= minimum_pairs,
        }
    )
    steps = min(
        int(report[condition]["sample_count"] / report[condition]["run_count"])
        for condition in CONDITIONS
    )
    checks.append(
        {
            "metric": "minimum_steps_per_run",
            "observed": steps,
            "operator": ">=",
            "limit": minimum_steps,
            "passed": steps >= minimum_steps,
        }
    )
    for path in REQUIRED_THRESHOLD_PATHS:
        limit = _finite_number(limits[path], f"limits.{path}", minimum=0.0)
        observed = _finite_number(_value_at_path(report, path), path, minimum=0.0)
        checks.append(
            {
                "metric": path,
                "observed": observed,
                "operator": "<=",
                "limit": limit,
                "passed": observed <= limit,
            }
        )
    passed = all(check["passed"] for check in checks)
    return {
        "status": "passed" if passed else "failed",
        "threshold_policy_sha256": _canonical_sha256(policy),
        "checks": checks,
    }


def build_paired_report(
    paths: Iterable[Path], *, threshold_policy: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Build a paired report from complete raw logs.

    Inputs are matched by ``pair_id`` rather than CLI order.  Every provenance
    field in :data:`PAIRING_FIELDS` must match within the pair.  Multiple pairs
    may have different Quest session IDs, but each individual pair may not.
    """

    runs = [read_benchmark_run(path) for path in paths]
    if not runs:
        raise ValueError("at least one baseline/recording pair is required")
    by_pair: dict[str, dict[str, BenchmarkRun]] = {}
    for run in runs:
        pair = by_pair.setdefault(run.identity["pair_id"], {})
        condition = run.identity["condition"]
        if condition in pair:
            raise ValueError(f"duplicate {condition} run for pair {run.identity['pair_id']}")
        pair[condition] = run
    for pair_id, pair in by_pair.items():
        if set(pair) != set(CONDITIONS):
            raise ValueError(f"pair {pair_id!r} lacks baseline or recording run")
        for field in PAIRING_FIELDS:
            baseline = pair["baseline"].identity[field]
            recording = pair["recording"].identity[field]
            if baseline != recording:
                raise ValueError(f"pair {pair_id!r} provenance mismatch: {field}")
        orders = {pair[condition].identity["pair_order"] for condition in CONDITIONS}
        if orders != {1, 2}:
            raise ValueError(f"pair {pair_id!r} must retain complementary pair_order values")
    baseline_runs = [pair["baseline"] for pair in by_pair.values()]
    recording_runs = [pair["recording"] for pair in by_pair.values()]
    baseline = _condition_summary(baseline_runs)
    recording = _condition_summary(recording_runs)
    pair_results: list[dict[str, Any]] = []
    for pair_id, pair in sorted(by_pair.items()):
        pair_baseline = _condition_summary([pair["baseline"]])
        pair_recording = _condition_summary([pair["recording"]])
        pair_results.append(
            {
                "pair_id": pair_id,
                "baseline": pair_baseline,
                "recording": pair_recording,
                "overhead": _overhead(pair_baseline, pair_recording),
            }
        )
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA_VERSION,
        "pair_count": len(by_pair),
        "physical_quest_pair_count": sum(
            bool(pair["baseline"].identity["headset_connected"]) for pair in by_pair.values()
        ),
        "inputs": [
            {
                "path": str(run.path),
                "sha256": run.sha256,
                "pair_id": run.identity["pair_id"],
                "condition": run.identity["condition"],
                "run_id": run.identity["run_id"],
            }
            for run in sorted(
                runs, key=lambda item: (item.identity["pair_id"], item.identity["condition"])
            )
        ],
        "pairing": [
            {
                "pair_id": pair_id,
                "provenance": {field: pair["baseline"].identity[field] for field in PAIRING_FIELDS},
                "order": {
                    condition: pair[condition].identity["pair_order"]
                    for condition in sorted(CONDITIONS)
                },
            }
            for pair_id, pair in sorted(by_pair.items())
        ],
        "pair_results": pair_results,
        "baseline": baseline,
        "recording": recording,
        "overhead": _overhead(baseline, recording),
    }
    evaluated_thresholds = (
        _evaluate_thresholds(report, threshold_policy) if threshold_policy is not None else None
    )
    if report["physical_quest_pair_count"] != report["pair_count"]:
        report["qualification"] = {
            "status": "failed",
            "reason": "one or more pairs lack a connected physical Quest session",
            "threshold_status": "threshold_pending" if threshold_policy is None else "supplied",
            "required_threshold_paths": list(REQUIRED_THRESHOLD_PATHS),
            **({"threshold_evaluation": evaluated_thresholds} if evaluated_thresholds else {}),
        }
    else:
        report["qualification"] = (
            {
                "status": "threshold_pending",
                "reason": "no complete reviewed VRR-070 threshold policy was supplied",
                "required_threshold_paths": list(REQUIRED_THRESHOLD_PATHS),
            }
            if threshold_policy is None
            else evaluated_thresholds
        )
    report["report_sha256"] = _canonical_sha256(report)
    return report


def validate_paired_report(report: Mapping[str, Any]) -> None:
    """Verify the derived report self-hash and its bound raw evidence files."""

    if report.get("schema") != REPORT_SCHEMA_VERSION:
        raise ValueError("wrong paired benchmark report schema")
    digest = report.get("report_sha256")
    unsigned = dict(report)
    unsigned.pop("report_sha256", None)
    if digest != _canonical_sha256(unsigned):
        raise ValueError("paired benchmark report self-hash mismatch")
    inputs = report.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("paired benchmark report has no inputs")
    for entry in inputs:
        path = Path(entry["path"])
        if _sha256_file(path) != entry["sha256"]:
            raise ValueError(f"raw benchmark evidence hash mismatch: {path}")
    rebuilt = build_paired_report([Path(entry["path"]) for entry in inputs])
    for field in (
        "pair_count",
        "physical_quest_pair_count",
        "inputs",
        "pairing",
        "pair_results",
        "baseline",
        "recording",
        "overhead",
    ):
        if report.get(field) != rebuilt[field]:
            raise ValueError(f"paired benchmark derived field mismatch: {field}")
    qualification = report.get("qualification", {})
    if qualification.get("status") not in {"threshold_pending", "passed", "failed"}:
        raise ValueError("unknown benchmark qualification status")
    checks = qualification.get("checks")
    if checks is not None:
        if not isinstance(checks, list):
            raise ValueError("benchmark qualification checks must be a list")
        expected_metrics = {
            "pair_count",
            "minimum_steps_per_run",
            *REQUIRED_THRESHOLD_PATHS,
        }
        if {check.get("metric") for check in checks} != expected_metrics:
            raise ValueError("benchmark qualification check coverage changed")
        for check in checks:
            metric = check.get("metric")
            if metric in REQUIRED_THRESHOLD_PATHS:
                observed = _value_at_path(report, metric)
                if check.get("observed") != observed:
                    raise ValueError(f"threshold check observation changed: {metric}")
            if check.get("operator") == "<=":
                passed = check.get("observed") <= check.get("limit")
            elif check.get("operator") == ">=":
                passed = check.get("observed") >= check.get("limit")
            else:
                raise ValueError(f"unknown threshold operator for {metric}")
            if check.get("passed") is not passed:
                raise ValueError(f"threshold check result changed: {metric}")
        expected_status = "passed" if all(check["passed"] for check in checks) else "failed"
        if qualification.get("status") != expected_status:
            raise ValueError("benchmark qualification aggregate status changed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path, help="Raw baseline/recording JSONL logs")
    parser.add_argument("--thresholds", type=Path, help="Reviewed complete threshold policy JSON")
    parser.add_argument("--output", required=True, type=Path, help="Derived paired report JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    thresholds = json.loads(args.thresholds.read_text()) if args.thresholds else None
    report = build_paired_report(args.logs, threshold_policy=thresholds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    validate_paired_report(report)
    print(json.dumps({"output": str(args.output), "qualification": report["qualification"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
