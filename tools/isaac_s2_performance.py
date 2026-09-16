"""Bounded, low-overhead timing log for the concrete Isaac S2 control loop."""

from __future__ import annotations

from contextlib import contextmanager
import json
import math
from pathlib import Path
import statistics
import time
from typing import Any, Iterator


SCHEMA_VERSION = "piper_x_isaac_s2_performance_v1"


def _percentile(values: list[float], percentile: float) -> float:
    """Return a linearly interpolated percentile without a third-party dependency."""

    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _distribution(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {
            "samples": 0,
            "mean_ms": 0.0,
            "p50_ms": 0.0,
            "p90_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "max_ms": 0.0,
        }
    return {
        "samples": len(values),
        "mean_ms": statistics.fmean(values),
        "p50_ms": _percentile(values, 0.50),
        "p90_ms": _percentile(values, 0.90),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "max_ms": max(values),
    }


class S2PerformanceLogger:
    """Write per-step JSONL plus periodic and final host-timing summaries.

    No CUDA synchronization is added. Timings include a GPU synchronization
    only where the pinned runtime already performs one.
    """

    def __init__(
        self,
        path: Path,
        *,
        window_steps: int,
        warmup_steps: int,
        target_hz: float,
    ) -> None:
        if window_steps <= 0:
            raise ValueError("performance window must be positive")
        if warmup_steps < 0:
            raise ValueError("performance warmup cannot be negative")
        if target_hz <= 0.0:
            raise ValueError("performance target Hz must be positive")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.window_steps = window_steps
        self.warmup_steps = warmup_steps
        self.target_hz = target_hz
        self.target_period_ms = 1000.0 / target_hz
        self._stream = path.open("w", encoding="utf-8")
        self._step_started_ns: int | None = None
        self._stage_ms: dict[str, float] = {}
        self._nested_ms: dict[str, float] = {}
        self._all_steps: list[dict[str, Any]] = []
        self._window_steps: list[dict[str, Any]] = []
        self._closed = False
        self._final_summary: dict[str, Any] | None = None
        self._write(
            {
                "event": "performance_log_started",
                "schema": SCHEMA_VERSION,
                "monotonic_ns": time.monotonic_ns(),
                "target_hz": target_hz,
                "target_period_ms": self.target_period_ms,
                "warmup_steps": warmup_steps,
                "window_steps": window_steps,
            }
        )
        self._stream.flush()

    def _write(self, record: dict[str, Any]) -> None:
        self._stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")

    def begin_step(self) -> None:
        self._step_started_ns = time.perf_counter_ns()
        self._stage_ms = {}
        self._nested_ms = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started_ns = time.perf_counter_ns()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
            self._stage_ms[name] = self._stage_ms.get(name, 0.0) + elapsed_ms

    def add_stage(self, name: str, elapsed_ns: int) -> None:
        elapsed_ms = elapsed_ns / 1_000_000.0
        self._stage_ms[name] = self._stage_ms.get(name, 0.0) + elapsed_ms

    def add_nested(self, name: str, elapsed_ns: int) -> None:
        elapsed_ms = elapsed_ns / 1_000_000.0
        self._nested_ms[name] = self._nested_ms.get(name, 0.0) + elapsed_ms

    def end_step(self, step: int, **state: Any) -> dict[str, Any] | None:
        if self._step_started_ns is None:
            raise RuntimeError("begin_step() must be called before end_step()")
        total_ms = (time.perf_counter_ns() - self._step_started_ns) / 1_000_000.0
        record = {
            "event": "performance_step",
            "schema": SCHEMA_VERSION,
            "step": step,
            "monotonic_ns": time.monotonic_ns(),
            "total_ms": total_ms,
            "stage_ms": dict(self._stage_ms),
            "nested_stage_ms": dict(self._nested_ms),
            "unattributed_ms": max(0.0, total_ms - sum(self._stage_ms.values())),
            "deadline_missed": total_ms > self.target_period_ms,
            "post_warmup": step > self.warmup_steps,
            **state,
        }
        write_started_ns = time.perf_counter_ns()
        self._write(record)
        record["instrumentation_write_ms"] = (
            time.perf_counter_ns() - write_started_ns
        ) / 1_000_000.0
        if record["post_warmup"]:
            self._all_steps.append(record)
            self._window_steps.append(record)
        self._step_started_ns = None
        if len(self._window_steps) < self.window_steps:
            return None
        summary = self._summarize(self._window_steps, event="performance_window")
        self._write(summary)
        self._stream.flush()
        self._window_steps = []
        return summary

    def _summarize(self, records: list[dict[str, Any]], *, event: str) -> dict[str, Any]:
        stage_names = sorted({name for row in records for name in row["stage_ms"]})
        nested_names = sorted({name for row in records for name in row["nested_stage_ms"]})
        total_ms = [float(row["total_ms"]) for row in records]
        misses = sum(bool(row["deadline_missed"]) for row in records)
        return {
            "event": event,
            "schema": SCHEMA_VERSION,
            "monotonic_ns": time.monotonic_ns(),
            "step_first": int(records[0]["step"]) if records else None,
            "step_last": int(records[-1]["step"]) if records else None,
            "control": _distribution(total_ms),
            "effective_hz": (1000.0 / statistics.fmean(total_ms)) if total_ms else 0.0,
            "deadline_ms": self.target_period_ms,
            "deadline_misses": misses,
            "deadline_miss_fraction": misses / len(records) if records else 0.0,
            "stages": {
                name: _distribution([float(row["stage_ms"].get(name, 0.0)) for row in records])
                for name in stage_names
            },
            "nested_stages_not_additive": {
                name: _distribution(
                    [float(row["nested_stage_ms"].get(name, 0.0)) for row in records]
                )
                for name in nested_names
            },
            "instrumentation_write": _distribution(
                [float(row["instrumentation_write_ms"]) for row in records]
            ),
        }

    def close(self) -> dict[str, Any]:
        if self._closed:
            assert self._final_summary is not None
            return self._final_summary
        self._final_summary = self._summarize(self._all_steps, event="performance_summary")
        self._final_summary.update(
            {
                "log_path": str(self.path),
                "warmup_steps_excluded": self.warmup_steps,
                "total_logged_steps": len(self._all_steps),
                "host_timing_only_no_added_cuda_synchronization": True,
            }
        )
        self._write(self._final_summary)
        self._stream.flush()
        self._stream.close()
        self._closed = True
        return self._final_summary
