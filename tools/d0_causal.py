"""D0 transaction identities; no simulator, dataset, or physical-clock dependency."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from tools.d0_temporal import PhysicalTimingValidator, PreparedTemporalFrame, SourceTiming
from tools.d0_temporal import TemporalContractViolation


CAMERAS = ("left_wrist", "right_wrist", "scene")
SIM_SOURCES = ("simulation.state_generation", *(f"camera.{role}" for role in CAMERAS))
# Recording does not acquire RGB frames. Its state boundary is nevertheless a
# first-class source identity, rather than an implicit side effect of a camera capture.
STATE_ONLY_SIM_SOURCES = ("simulation.state_generation", "recording.measured_state")
XR_SOURCES = ("xr.device_io_update", "xr.submitted_frame", "xr.returned_frame", "xr.resolved_input")
AUTOMATED = frozenset(("scripted_expert", "planner", "datagen", "policy_generated"))


def select_temporal_profile(runtime: str, source_class: str) -> str:
    if runtime == "isaac" and source_class in AUTOMATED:
        return "isaac_automated_v4"
    if source_class == "human_vr" and runtime in ("isaac", "real"):
        return "isaac_human_vr_v4" if runtime == "isaac" else "real_human_vr_physical_v4"
    raise ValueError(f"no admitted temporal profile for {runtime}/{source_class}")


@dataclass(frozen=True)
class Epoch:
    run_id: str
    episode_id: str
    source_id: str
    reset_epoch: int
    control_reference_epoch: int
    source_epoch: str  # XR session epoch or generator/source lifecycle epoch.

    def __post_init__(self) -> None:
        if not all(
            isinstance(v, str) and v
            for v in (self.run_id, self.episode_id, self.source_id, self.source_epoch)
        ) or any(
            type(v) is not int or v < 0 for v in (self.reset_epoch, self.control_reference_epoch)
        ):
            raise ValueError("invalid epoch identity")


@dataclass(frozen=True)
class PayloadIdentity:
    epoch: Epoch
    control_tick_id: int
    payload_id: str
    sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.control_tick_id) is not int
            or self.control_tick_id < 0
            or not self.payload_id
            or len(self.sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise ValueError("invalid payload identity")

    @classmethod
    def bind(cls, epoch: Epoch, tick: int, payload_id: str, payload: bytes) -> PayloadIdentity:
        return cls(epoch, tick, payload_id, sha256(payload).hexdigest())


@dataclass(frozen=True)
class SourceIdentity:
    name: str
    sample: PayloadIdentity
    sequence: int

    def __post_init__(self) -> None:
        if not self.name or type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("invalid source identity")


@dataclass(frozen=True)
class PreparedTransaction:
    observation: PayloadIdentity
    dataset_action: PayloadIdentity
    sources: tuple[SourceIdentity, ...]
    physical: PreparedTemporalFrame | None
    generator: tuple[str | None, str | None, int | None]


@dataclass(frozen=True)
class CompletedTransition:
    native_command: PayloadIdentity
    transition_id: str
    successor: PayloadIdentity


class CausalTransactionValidator:
    """One pending transaction; identities retained for the lifetime of one run.

    Bytes are an edge-owned canonical serialization (including dtype/shape/role),
    or immutable content-addressed references. Images are never retained here.
    Real persistence at send-return remains a separate compatibility seam; full
    transition proof requires a subsequent observation and does not prove motion.
    """

    def __init__(
        self,
        runtime: str,
        source_class: str,
        epoch: Epoch,
        *,
        physical: PhysicalTimingValidator | None = None,
        sim_sources: tuple[str, ...] = SIM_SOURCES,
    ) -> None:
        self.profile = select_temporal_profile(runtime, source_class)
        if (physical is not None) != (runtime == "real"):
            raise ValueError("only the real profile requires a physical timing validator")
        if physical is not None and set(physical.required_sources) != {
            "observation.state",
            *(f"observation.images.{role}" for role in CAMERAS),
            "xr.left_pose",
            "xr.right_pose",
            "source_action",
        }:
            raise ValueError("real profile requires all seven physical source streams")
        self.epoch = epoch
        self.physical = physical
        if (not sim_sources or len(sim_sources) != len(set(sim_sources))
                or "simulation.state_generation" not in sim_sources):
            raise ValueError("invalid simulator source set")
        self.sim_sources = sim_sources
        self._epochs = {epoch}
        self._expected_observation: PayloadIdentity | None = None
        self._pending: PreparedTransaction | None = None
        self._completion: CompletedTransition | None = None
        self._persisted = False
        self._ticks: dict[Epoch, int] = {}
        self._sequences: dict[tuple[Epoch, str], int] = {}
        self._ids: set[tuple[str, str]] = set()
        self.accepted_transactions = 0
        self.rejected: Counter[str] = Counter()

    def _reject(self, reason: str) -> None:
        self.rejected[reason] += 1
        raise TemporalContractViolation(reason, "causal transaction rejected")

    def begin_epoch(self, epoch: Epoch) -> None:
        if epoch in self._epochs or epoch.run_id != self.epoch.run_id:
            self._reject("epoch_reuse")
        self.abort()
        self.epoch = epoch
        self._expected_observation = None
        self._epochs.add(epoch)
        if self.physical:
            self.physical.reset_episode()

    def _at(self, item: PayloadIdentity, tick: int) -> None:
        if item.epoch != self.epoch:
            self._reject("epoch_crossing")
        if item.control_tick_id != tick:
            self._reject("tick_mismatch")

    def prepare(
        self,
        observation: PayloadIdentity,
        dataset_action: PayloadIdentity,
        sources: tuple[SourceIdentity, ...],
        *,
        observation_payload: bytes,
        action_payload: bytes,
        tracking_valid: bool | None = None,
        generator_revision: str | None = None,
        generator_state: str | None = None,
        generator_seed: int | None = None,
        source_timing: Mapping[str, SourceTiming] | None = None,
        selection_timestamp: float | None = None,
    ) -> PreparedTransaction:
        if self._pending is not None:
            self._reject("transaction_pending")
        tick = observation.control_tick_id
        self._at(observation, tick)
        self._at(dataset_action, tick)
        if self._expected_observation is not None and observation != self._expected_observation:
            self._reject("successor_pairing_mismatch")
        if tick <= self._ticks.get(self.epoch, -1):
            self._reject("tick_reuse")
        self.verify_payload(observation, observation_payload)
        self.verify_payload(dataset_action, action_payload)
        if "human_vr" in self.profile and tracking_valid is not True:
            self._reject("tracking_invalid")
        names = tuple(source.name for source in sources)
        expected = self.sim_sources
        if self.profile == "isaac_human_vr_v4":
            expected += XR_SOURCES
            if tracking_valid is not True:
                self._reject("tracking_invalid")
        elif self.profile == "isaac_automated_v4":
            expected += ("generator.decision",)
            if not generator_revision or not generator_state:
                self._reject("generator_provenance_missing")
            if tracking_valid is not None or any(n.startswith("xr.") for n in names):
                self._reject("unexpected_xr")
        else:
            assert self.physical is not None
            expected = self.physical.required_sources
        if set(names) != set(expected) or len(names) != len(set(names)):
            self._reject("source_identity_set")
        for source in sources:
            self._at(source.sample, tick)
            if (source.name, source.sample.payload_id) in self._ids:
                self._reject("source_identity_reuse")
            key = (self.epoch, source.name)
            if source.sequence <= self._sequences.get(key, -1):
                self._reject("source_identity_reuse")
        physical = None
        if self.physical:
            if source_timing is None or selection_timestamp is None:
                self._reject("missing_timing_metadata")
            assert source_timing is not None and selection_timestamp is not None
            physical = self.physical.prepare_frame(
                source_timing, selection_timestamp=selection_timestamp
            )
            if any(s.sequence != source_timing[s.name].sequence for s in sources):
                self._reject("physical_identity_mismatch")
        elif source_timing is not None or selection_timestamp is not None:
            self._reject("unexpected_physical_timing")
        # Provenance values are immutable and bound into the decision identity by the edge.
        if generator_seed is not None and type(generator_seed) is not int:
            self._reject("invalid_generator_seed")
        for role, item in (("observation", observation), ("action", dataset_action)):
            if (role, item.payload_id) in self._ids:
                self._reject("payload_identity_reuse")
        prepared = PreparedTransaction(
            observation,
            dataset_action,
            tuple(sources),
            physical,
            (generator_revision, generator_state, generator_seed),
        )
        self._pending = prepared
        self._ticks[self.epoch] = tick
        for role, item in (("observation", observation), ("action", dataset_action)):
            self._ids.add((role, item.payload_id))
        for source in sources:
            self._ids.add((source.name, source.sample.payload_id))
            self._sequences[(self.epoch, source.name)] = source.sequence
        return prepared

    def _require_pending(self, prepared: PreparedTransaction) -> None:
        if prepared is not self._pending:
            self._reject("transaction_not_pending")
        self._at(prepared.observation, prepared.observation.control_tick_id)

    def complete_transition(
        self,
        prepared: PreparedTransaction,
        native_command: PayloadIdentity,
        transition_id: str,
        successor: PayloadIdentity,
        *,
        successful: bool,
    ) -> CompletedTransition:
        self._require_pending(prepared)
        tick = prepared.observation.control_tick_id
        self._at(native_command, tick)
        self._at(successor, tick + 1)
        if self._completion is not None or successful is not True or not transition_id:
            self._reject("transition_incomplete_or_repeated")
        for role, identity in (
            ("native", native_command.payload_id),
            ("transition", transition_id),
        ):
            if (role, identity) in self._ids:
                self._reject("transition_reuse")
        if ("observation", successor.payload_id) in self._ids:
            self._reject("successor_reuse")
        self._ids.update((("native", native_command.payload_id), ("transition", transition_id)))
        self._completion = CompletedTransition(native_command, transition_id, successor)
        return self._completion

    def verify_payload(self, identity: PayloadIdentity, payload: bytes) -> None:
        if sha256(payload).hexdigest() != identity.sha256:
            self._reject("payload_substitution")

    def validate_persistence(
        self, prepared: PreparedTransaction, *, observation_payload: bytes, action_payload: bytes
    ) -> None:
        """Real-only pre-successor write seam; this is not a causal commit."""
        self._require_pending(prepared)
        if self.physical is None or self._persisted:
            self._reject("invalid_persistence_phase")
        self.verify_payload(prepared.observation, observation_payload)
        self.verify_payload(prepared.dataset_action, action_payload)

    def mark_persisted(self, prepared: PreparedTransaction) -> None:
        """Called by the compatibility facade only after its writer succeeds."""
        self._require_pending(prepared)
        self._persisted = True

    def commit(
        self, prepared: PreparedTransaction, *, observation_payload: bytes, action_payload: bytes
    ) -> CompletedTransition:
        self._require_pending(prepared)
        if self._completion is None:
            self._reject("transition_not_completed")
        self.verify_payload(prepared.observation, observation_payload)
        self.verify_payload(prepared.dataset_action, action_payload)
        assert self._completion is not None
        result = self._completion
        if self.physical and not self._persisted:
            assert prepared.physical is not None
            self.physical.accept(prepared.physical)
        self._expected_observation = result.successor
        self.accepted_transactions += 1
        self.abort()
        return result

    def break_observation_chain(self) -> None:
        """End an unrecorded interval without forgetting consumed identities or ticks."""
        self.abort()
        self._expected_observation = None

    def abort(self) -> None:
        self._pending = None
        self._completion = None
        self._persisted = False
