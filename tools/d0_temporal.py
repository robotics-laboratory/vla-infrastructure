"""Fail-closed D0 source-time validation at the LeRobot ``add_frame`` seam."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from typing import Any, Mapping, Protocol

import numpy as np


CROSS_MODAL_SKEW_KEY = "temporal.cross_modal_skew_ms"


class DatasetWriter(Protocol):
    """The narrow upstream LeRobotDataset surface used by this adapter."""

    @property
    def features(self) -> Mapping[str, Mapping[str, Any]]: ...

    def add_frame(self, frame: dict[str, Any]) -> None: ...


class TemporalContractViolation(ValueError):
    """A frame was rejected before it reached ``LeRobotDataset.add_frame``."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class SourceTiming:
    """Physical acquisition identity for one source sample."""

    sequence: int
    source_timestamp: float
    clock_domain: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ValueError("sequence must be a non-negative integer")
        if not math.isfinite(self.source_timestamp):
            raise ValueError("source_timestamp must be finite")
        if not self.clock_domain:
            raise ValueError("clock_domain must be non-empty")


@dataclass(frozen=True)
class TemporalLimits:
    """Per-source age limits and the bundle-wide skew limit, in milliseconds."""

    max_age_ms: Mapping[str, float]
    max_cross_modal_skew_ms: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_cross_modal_skew_ms) or self.max_cross_modal_skew_ms < 0:
            raise ValueError("max_cross_modal_skew_ms must be finite and non-negative")
        for source, value in self.max_age_ms.items():
            if not source or not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid max age for {source!r}: {value!r}")


def temporal_feature_specs(
    feature_sets: Mapping[str, Mapping[str, str]],
    required_sources: tuple[str, ...],
    *,
    cross_modal_skew_key: str = CROSS_MODAL_SKEW_KEY,
) -> dict[str, dict[str, Any]]:
    """Build LeRobot v3 feature declarations for persisted source timing."""

    specs: dict[str, dict[str, Any]] = {}
    for source in required_sources:
        keys = feature_sets[source]
        specs[keys["sequence"]] = {"dtype": "int64", "shape": (1,)}
        specs[keys["source_timestamp"]] = {"dtype": "float64", "shape": (1,)}
        specs[keys["clock_domain"]] = {"dtype": "string", "shape": (1,)}
        specs[keys["age_ms"]] = {"dtype": "float64", "shape": (1,)}
    specs[cross_modal_skew_key] = {"dtype": "float64", "shape": (1,)}
    return specs


class TemporalFrameRecorder:
    """Validate and persist physical source time before delegating to LeRobot."""

    def __init__(
        self,
        dataset: DatasetWriter,
        *,
        feature_sets: Mapping[str, Mapping[str, str]],
        required_sources: tuple[str, ...],
        limits: TemporalLimits,
        accepted_clock_domains: tuple[str, ...],
        cross_modal_skew_key: str = CROSS_MODAL_SKEW_KEY,
    ) -> None:
        if not required_sources:
            raise ValueError("required_sources must not be empty")
        if set(required_sources) != set(limits.max_age_ms):
            raise ValueError("max_age_ms keys must exactly match required_sources")
        missing_sets = set(required_sources) - set(feature_sets)
        if missing_sets:
            raise ValueError(f"missing temporal feature sets: {sorted(missing_sets)}")
        if not accepted_clock_domains or any(not domain for domain in accepted_clock_domains):
            raise ValueError("accepted_clock_domains must contain non-empty names")

        self.dataset = dataset
        self.feature_sets = {name: dict(feature_sets[name]) for name in required_sources}
        self.required_sources = required_sources
        self.limits = limits
        self.accepted_clock_domains = frozenset(accepted_clock_domains)
        self.cross_modal_skew_key = cross_modal_skew_key
        self._last_accepted: dict[str, SourceTiming] = {}
        self.accepted_frames = 0
        self.rejected_frames: Counter[str] = Counter()

        expected = temporal_feature_specs(
            self.feature_sets,
            required_sources,
            cross_modal_skew_key=cross_modal_skew_key,
        )
        missing = set(expected) - set(dataset.features)
        if missing:
            raise ValueError(f"dataset is missing temporal features: {sorted(missing)}")

    @classmethod
    def from_resolved_contract(
        cls,
        dataset: DatasetWriter,
        contract: Mapping[str, Any],
        *,
        source_class: str,
        limits: TemporalLimits,
        accepted_clock_domains: tuple[str, ...],
    ) -> "TemporalFrameRecorder":
        timing = contract["dataset"]["temporal_semantics"]["source_timing"]
        group = "human_vr" if source_class == "human_vr" else "automated"
        return cls(
            dataset,
            feature_sets=timing["feature_sets"],
            required_sources=tuple(timing["required_feature_sets_by_source_class"][group]),
            limits=limits,
            accepted_clock_domains=accepted_clock_domains,
            cross_modal_skew_key=timing["cross_modal_skew_feature_key"],
        )

    def add_frame(
        self,
        frame: Mapping[str, Any],
        source_timing: Mapping[str, SourceTiming],
        *,
        selection_timestamp: float,
    ) -> None:
        """Add one accepted frame, or reject it without calling upstream."""

        try:
            enriched, accepted = self._validated_frame(
                frame, source_timing, selection_timestamp=selection_timestamp
            )
            self.dataset.add_frame(enriched)
        except TemporalContractViolation as exc:
            self.rejected_frames[exc.reason] += 1
            raise
        self._last_accepted = accepted
        self.accepted_frames += 1

    def qa_summary(self) -> dict[str, Any]:
        return {
            "accepted_frames": self.accepted_frames,
            "rejected_frames": sum(self.rejected_frames.values()),
            "rejected_by_reason": dict(sorted(self.rejected_frames.items())),
        }

    def _reject(self, reason: str, detail: str) -> None:
        raise TemporalContractViolation(reason, detail)

    def _validated_frame(
        self,
        frame: Mapping[str, Any],
        source_timing: Mapping[str, SourceTiming],
        *,
        selection_timestamp: float,
    ) -> tuple[dict[str, Any], dict[str, SourceTiming]]:
        if not math.isfinite(selection_timestamp):
            self._reject("invalid_selection_timestamp", "selection timestamp must be finite")
        forbidden = {"timestamp", "frame_index"} & set(frame)
        if forbidden:
            self._reject("logical_time_override", f"LeRobot owns {sorted(forbidden)}")
        missing = set(self.required_sources) - set(source_timing)
        extra = set(source_timing) - set(self.required_sources)
        if missing or extra:
            self._reject(
                "source_set_mismatch",
                f"missing={sorted(missing)} extra={sorted(extra)}",
            )

        domains = {sample.clock_domain for sample in source_timing.values()}
        if len(domains) != 1:
            self._reject("clock_domain_mismatch", f"domains={sorted(domains)}")
        if not domains <= self.accepted_clock_domains:
            self._reject(
                "undeclared_clock_domain",
                f"domains={sorted(domains)} accepted={sorted(self.accepted_clock_domains)}",
            )

        ages: dict[str, float] = {}
        for source in self.required_sources:
            sample = source_timing[source]
            age_ms = (selection_timestamp - sample.source_timestamp) * 1000.0
            if age_ms < 0:
                self._reject("future_source_sample", f"{source} age_ms={age_ms}")
            if age_ms > self.limits.max_age_ms[source]:
                self._reject(
                    "stale_source_sample",
                    f"{source} age_ms={age_ms} limit={self.limits.max_age_ms[source]}",
                )
            previous = self._last_accepted.get(source)
            if previous is not None:
                if sample.sequence < previous.sequence:
                    self._reject(
                        "sequence_regression",
                        f"{source} sequence={sample.sequence} previous={previous.sequence}",
                    )
                if sample.sequence == previous.sequence and sample != previous:
                    self._reject(
                        "sequence_identity_changed",
                        f"{source} reused sequence {sample.sequence} with different timing",
                    )
                if (
                    sample.sequence > previous.sequence
                    and sample.source_timestamp < previous.source_timestamp
                ):
                    self._reject(
                        "source_time_regression",
                        f"{source} timestamp={sample.source_timestamp} previous={previous.source_timestamp}",
                    )
            ages[source] = age_ms

        timestamps = [source_timing[source].source_timestamp for source in self.required_sources]
        skew_ms = (max(timestamps) - min(timestamps)) * 1000.0
        if skew_ms > self.limits.max_cross_modal_skew_ms:
            self._reject(
                "cross_modal_skew",
                f"skew_ms={skew_ms} limit={self.limits.max_cross_modal_skew_ms}",
            )

        enriched = dict(frame)
        for source in self.required_sources:
            sample = source_timing[source]
            keys = self.feature_sets[source]
            enriched[keys["sequence"]] = np.asarray([sample.sequence], dtype=np.int64)
            enriched[keys["source_timestamp"]] = np.asarray(
                [sample.source_timestamp], dtype=np.float64
            )
            enriched[keys["clock_domain"]] = sample.clock_domain
            enriched[keys["age_ms"]] = np.asarray([ages[source]], dtype=np.float64)
        enriched[self.cross_modal_skew_key] = np.asarray([skew_ms], dtype=np.float64)
        return enriched, dict(source_timing)
