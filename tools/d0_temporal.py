"""Physical D0 timing validation and the existing LeRobot compatibility facade."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from types import MappingProxyType
import math
import hashlib
import json
from typing import TYPE_CHECKING, Any, Mapping, Protocol

import numpy as np


if TYPE_CHECKING:
    from tools.d0_causal import CausalTransactionValidator, PreparedTransaction


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
        if (
            isinstance(self.source_timestamp, bool)
            or not isinstance(self.source_timestamp, (int, float))
            or not math.isfinite(self.source_timestamp)
        ):
            raise ValueError("source_timestamp must be finite")
        if not self.clock_domain:
            raise ValueError("clock_domain must be non-empty")


@dataclass(frozen=True)
class PreparedTemporalFrame:
    """Validated temporal enrichment awaiting the matching dataset frame."""

    enrichment: Mapping[str, Any]
    accepted: Mapping[str, SourceTiming]
    previous: Mapping[str, SourceTiming]
    generation: int


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

    @classmethod
    def from_resolved_contract(
        cls,
        contract: Mapping[str, Any],
        required_sources: tuple[str, ...],
    ) -> "TemporalLimits":
        """Resolve non-null modality budgets from the canonical contract."""

        timing = contract["timing"]
        source_limit_keys = {
            "observation.state": "max_joint_age_ms",
            "observation.images.left_wrist": "max_camera_age_ms",
            "observation.images.right_wrist": "max_camera_age_ms",
            "observation.images.scene": "max_camera_age_ms",
            "xr.left_pose": "max_xr_age_ms",
            "xr.right_pose": "max_xr_age_ms",
            "source_action": "max_policy_action_age_ms",
        }
        max_age_ms: dict[str, float] = {}
        for source in required_sources:
            key = source_limit_keys.get(source)
            if key is None:
                raise ValueError(f"no temporal limit mapping for required source {source!r}")
            value = timing.get(key)
            if value is None:
                raise ValueError(f"timing.{key} must be resolved before recording starts")
            max_age_ms[source] = float(value)
        skew = timing.get("max_cross_modal_skew_ms")
        if skew is None:
            raise ValueError(
                "timing.max_cross_modal_skew_ms must be resolved before recording starts"
            )
        return cls(max_age_ms=max_age_ms, max_cross_modal_skew_ms=float(skew))


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


class PhysicalTimingValidator:
    """Validate physical source timing independently of any dataset writer."""

    def __init__(
        self,
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

        self.feature_sets = {name: dict(feature_sets[name]) for name in required_sources}
        self.required_sources = required_sources
        self.limits = limits
        self.accepted_clock_domains = frozenset(accepted_clock_domains)
        self.cross_modal_skew_key = cross_modal_skew_key
        self._last_accepted: dict[str, SourceTiming] = {}
        self.accepted_frames = 0
        self._generation = 0
        self.rejected_frames: Counter[str] = Counter()

    def prepare_frame(
        self,
        source_timing: Mapping[str, SourceTiming],
        *,
        selection_timestamp: float,
    ) -> PreparedTemporalFrame:
        """Validate source timing before actuation and retain its exact enrichment."""

        try:
            enrichment, accepted = self._validated_frame(
                {}, source_timing, selection_timestamp=selection_timestamp
            )
        except TemporalContractViolation as exc:
            self.rejected_frames[exc.reason] += 1
            raise
        for value in enrichment.values():
            if isinstance(value, np.ndarray):
                value.setflags(write=False)
        return PreparedTemporalFrame(
            enrichment=MappingProxyType(enrichment),
            accepted=MappingProxyType(accepted),
            previous=MappingProxyType(dict(self._last_accepted)),
            generation=self._generation,
        )

    def accept(self, prepared: PreparedTemporalFrame) -> None:
        if prepared.generation != self._generation or dict(self._last_accepted) != dict(
            prepared.previous
        ):
            self._reject("prepared_frame_order", "physical history changed after preparation")
        self._last_accepted = dict(prepared.accepted)
        self.accepted_frames += 1
        self._generation += 1

    def reset_episode(self) -> None:
        """Reset episode-local sequence/time history without erasing QA counters."""

        self._last_accepted.clear()
        self._generation += 1

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
                "missing_timing_metadata" if missing else "source_set_mismatch",
                f"missing={sorted(missing)} extra={sorted(extra)}",
            )

        for source in self.required_sources:
            sample = source_timing[source]
            if not isinstance(sample, SourceTiming):
                self._reject(
                    "missing_timing_metadata",
                    f"{source} must provide a complete SourceTiming value",
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
                if sample.sequence <= previous.sequence:
                    self._reject(
                        "repeated_sequence"
                        if sample.sequence == previous.sequence
                        else "sequence_regression",
                        f"{source} sequence={sample.sequence} previous={previous.sequence}",
                    )
                if sample.source_timestamp <= previous.source_timestamp:
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


def frame_payloads(frame: Mapping[str, Any]) -> tuple[bytes, bytes]:
    """Bind typed frame content without retaining image bytes in a transaction."""

    def encode(values: Mapping[str, Any]) -> bytes:
        encoded: dict[str, Any] = {}
        for key, value in values.items():
            if isinstance(value, str):
                encoded[key] = ["string", value]
            elif isinstance(value, np.ndarray) and not value.dtype.hasobject:
                encoded[key] = [
                    value.dtype.str,
                    list(value.shape),
                    hashlib.sha256(value.tobytes(order="C")).hexdigest(),
                ]
            else:
                raise ValueError(f"unsupported payload type for {key}")
        return json.dumps(encoded, sort_keys=True, separators=(",", ":")).encode()

    return (
        encode({k: v for k, v in frame.items() if k.startswith("observation.") or k == "task"}),
        encode({"action": frame["action"]}),
    )


class TemporalFrameRecorder(PhysicalTimingValidator):
    """Compatibility facade for the physical LeRobot persistence seam.

    Pre-actuation timing and source identities are frozen; upstream owns the
    observation/label processor pairing. This seam does not attest a successor
    observation or hardware acceptance. Full v4 source admission needs that proof.
    """

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
        super().__init__(
            feature_sets=feature_sets,
            required_sources=required_sources,
            limits=limits,
            accepted_clock_domains=accepted_clock_domains,
            cross_modal_skew_key=cross_modal_skew_key,
        )
        self.dataset = dataset
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
        runtime: str = "real",
        limits: TemporalLimits | None = None,
        accepted_clock_domains: tuple[str, ...] = ("host_monotonic",),
    ) -> "TemporalFrameRecorder":
        if runtime != "real":
            raise ValueError(
                "physical LeRobot compatibility facade is real-only; select the Isaac causal profile"
            )
        timing = contract["dataset"]["temporal_semantics"]["source_timing"]
        source_classes = tuple(contract["taxonomy"]["source_classes"])
        if source_class not in source_classes:
            raise ValueError(
                f"unknown source_class {source_class!r}; expected one of {source_classes}"
            )
        group = "human_vr" if source_class == "human_vr" else "automated"
        required_sources = tuple(timing["required_feature_sets_by_source_class"][group])
        return cls(
            dataset,
            feature_sets=timing["feature_sets"],
            required_sources=required_sources,
            limits=limits or TemporalLimits.from_resolved_contract(contract, required_sources),
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

        prepared = self.prepare_frame(source_timing, selection_timestamp=selection_timestamp)
        self.commit_frame(frame, prepared)

    def commit_transaction_frame(
        self,
        frame: Mapping[str, Any],
        causal: CausalTransactionValidator,
        transaction: PreparedTransaction,
    ) -> None:
        """Persist a real prepared pair now; causal completion still needs obs_t+1."""
        if causal.physical is not self or transaction.physical is None:
            raise ValueError("transaction must use this physical recorder")
        obs, action = frame_payloads(frame)
        causal.validate_persistence(transaction, observation_payload=obs, action_payload=action)
        self.commit_frame(frame, transaction.physical)
        causal.mark_persisted(transaction)

    def commit_frame(
        self,
        frame: Mapping[str, Any],
        prepared: PreparedTemporalFrame,
    ) -> None:
        """Persist the dataset frame only if it matches the pre-actuation validation."""

        try:
            if prepared.generation != self._generation or dict(self._last_accepted) != dict(
                prepared.previous
            ):
                self._reject(
                    "prepared_frame_order",
                    "another temporal frame was committed after this bundle was prepared",
                )
            forbidden = {"timestamp", "frame_index"} & set(frame)
            if forbidden:
                self._reject("logical_time_override", f"LeRobot owns {sorted(forbidden)}")
            overlap = set(frame) & set(prepared.enrichment)
            if overlap:
                self._reject(
                    "temporal_metadata_override",
                    f"frame must not provide recorder-owned fields {sorted(overlap)}",
                )
            enriched = {**dict(frame), **dict(prepared.enrichment)}
            self.dataset.add_frame(enriched)
        except TemporalContractViolation as exc:
            self.rejected_frames[exc.reason] += 1
            raise
        self._last_accepted = dict(prepared.accepted)
        self.accepted_frames += 1
        self._generation += 1
