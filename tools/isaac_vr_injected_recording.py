"""Deterministic no-headset integration transitions for the real Kit recorder seam."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Mapping

import numpy as np

from isaac_s1_runtime import NativeBimanualTargets, d0_action_to_native
from isaac_s2_processor import ArmTeleopCommand, BimanualTeleopCommand, PROCESSOR_REVISION
from tools.d0_causal import CausalTransactionValidator
from tools.isaac_vr_decision import (
    ResolvedXrInput,
    SolvedControlDecision,
    commit_recording_transition,
    decision_epoch,
)


def _command(grippers: tuple[float, float]) -> BimanualTeleopCommand:
    arms = tuple(
        ArmTeleopCommand(
            delta_pose=np.zeros(6, dtype=np.float64),
            gripper_aperture_m=gripper,
            motion_active=True,
            tracking_valid=True,
            clutch_active=False,
            rebased=False,
            sensitivity_mode="normal",
            translation_scale=1.0,
            rotation_scale=1.0,
            # The production admission guard accepts motion decisions only;
            # injection provenance is carried by the execution profile, not a
            # processor hold/rebase transition masquerading as an action.
            transition="motion",
        )
        for gripper in grippers
    )
    return BimanualTeleopCommand(
        left=arms[0],
        right=arms[1],
        session_active=True,
        processor_revision=PROCESSOR_REVISION,
        processor_generation=0,
        provenance_revision="deterministic_injected_xr_v1",
    )


def _xr(tick: int) -> ResolvedXrInput:
    return ResolvedXrInput(
        session_epoch=1,
        control_reference_epoch=1,
        deviceio_update_epoch=tick,
        submitted_frame_id=tick,
        returned_frame_id=tick,
        ran_synchronously=True,
        hands=(None, None),
        world_transform=tuple(float(value) for value in np.eye(4, dtype=np.float32).reshape(-1)),
        rebased=False,
        tracking_valid=(True, True),
    )


def _target(observation_state: tuple[float, ...], index: int) -> np.ndarray:
    target = np.asarray(observation_state, dtype=np.float64).copy()
    # Keep the bounded validation sweep away from joint limits. Accumulating
    # increasing deltas from the previous state saturates long benchmark runs.
    magnitude = 0.25 + 0.25 * (index % 1000) / 1000
    target[0] += magnitude
    target[7] -= magnitude
    target[6] = np.clip(target[6] + 2.0 + magnitude, 5.0, 95.0)
    target[13] = np.clip(target[13] - 2.0 - magnitude, 5.0, 95.0)
    return target


def record_injected_transitions(
    recording: Any,
    env: Any,
    *,
    count: int = 3,
    benchmark_logger: Any | None = None,
    resource_sampler: Any | None = None,
    performance_logger: Any | None = None,
) -> dict[str, Any]:
    """Write distinct committed transitions through the production causal/writer APIs."""
    if count < 2:
        raise ValueError("injected integration requires at least two transitions")
    if (benchmark_logger is None) is not (resource_sampler is None):
        raise ValueError("benchmark logger and resource sampler must be supplied together")
    validator = None
    initial_state = None
    actions: list[list[float]] = []
    for index in range(count):
        tick = index + 1
        benchmark_started_ns = time.perf_counter_ns()
        if performance_logger is not None:
            performance_logger.begin_step()
            stage_started_ns = time.perf_counter_ns()
        if benchmark_logger is not None:
            benchmark_logger.begin_step(tick)
            with benchmark_logger.stage("state_sampling_ms"):
                token = recording.capture_observation()
        else:
            token = recording.capture_observation()
        if performance_logger is not None:
            performance_logger.add_stage(
                "observation_capture", time.perf_counter_ns() - stage_started_ns
            )
            stage_started_ns = time.perf_counter_ns()
        xr = _xr(tick)
        if validator is None:
            validator = CausalTransactionValidator(
                "isaac",
                "human_vr",
                decision_epoch(
                    recording.run_id,
                    token.observation,
                    xr,
                    episode_id=recording.episode_id,
                ),
                profile="isaac_human_vr_offline_rgb_v1",
            )
        if initial_state is None:
            initial_state = token.state
        target = d0_action_to_native(_target(initial_state, index))
        native = np.concatenate((target.left_rad_m, target.right_rad_m))
        command = _command((float(target.left_rad_m[6]), float(target.right_rad_m[6])))
        decision = SolvedControlDecision.from_native(
            tick,
            token.observation,
            xr,
            command,
            native,
            native.copy(),
        )
        prepared = decision.prepare(validator)
        env._apply(
            NativeBimanualTargets(
                target.left_rad_m.copy(),
                target.right_rad_m.copy(),
                target.saturated,
            )
        )
        if performance_logger is not None:
            performance_logger.add_stage(
                "injected_decision_apply", time.perf_counter_ns() - stage_started_ns
            )
            stage_started_ns = time.perf_counter_ns()
        env._advance(4)
        if performance_logger is not None:
            performance_logger.add_stage(
                "simulation_advance", time.perf_counter_ns() - stage_started_ns
            )
            stage_started_ns = time.perf_counter_ns()
        if benchmark_logger is not None:
            with benchmark_logger.stage("state_sampling_ms"):
                successor = recording.capture_successor(token)
        else:
            successor = recording.capture_successor(token)
        if performance_logger is not None:
            performance_logger.add_stage(
                "successor_capture", time.perf_counter_ns() - stage_started_ns
            )
            stage_started_ns = time.perf_counter_ns()
        committed = commit_recording_transition(
            validator,
            decision,
            prepared,
            successor.observation,
        )
        from isaac_vr_recording import build_committed_transition_sample

        row = build_committed_transition_sample(
            recording,
            token,
            successor,
            decision,
            committed,
        )
        recording.commit_transition(token, successor, row)
        actions.append([float(value) for value in decision.dataset_action])
        if performance_logger is not None:
            performance_logger.add_stage(
                "causal_commit_and_record", time.perf_counter_ns() - stage_started_ns
            )
        if benchmark_logger is not None:
            rejected = sum(int(value) for value in recording.rejections.values())
            benchmark_logger.end_step(
                resources=resource_sampler.sample(),
                committed=int(recording.committed_frames),
                rejected=rejected,
                dropped=0,
                deadline_missed=(time.perf_counter_ns() - benchmark_started_ns)
                > (1_000_000_000 / float(benchmark_logger.identity["target_hz"])),
            )
        if performance_logger is not None:
            performance_logger.end_step(tick, source="deterministic_injected_xr_v1")
    assert validator is not None
    if validator.accepted_transactions != count or recording.committed_frames != count:
        raise RuntimeError("injected causal commits and HDF frames diverged")
    if len({tuple(action) for action in actions}) != count:
        raise RuntimeError("injected integration actions are not distinct")
    return {
        "actions": actions,
        "accepted_transactions": validator.accepted_transactions,
        "committed_frames": recording.committed_frames,
        "processor_revision": PROCESSOR_REVISION,
        "source": "deterministic_injected_xr_v1",
    }


def validate_injected_recording(
    recording_hdf5: Path,
    *,
    portable_roots: Mapping[str, str | Path],
) -> dict[str, Any]:
    """Read the finalized non-mock HDF with SessionReader and strict project validation."""
    from isaacsim.replicator.episode_recorder import SessionReader
    from isaac_vr_replay import _validate_session, verify_recording_artifact

    artifact = verify_recording_artifact(recording_hdf5, portable_roots=portable_roots)
    with SessionReader(str(recording_hdf5)) as reader:
        session = _validate_session(reader, artifact, 0)
    if session.committed_count != artifact.committed_frames:
        raise RuntimeError("strict SessionReader validation lost committed transitions")
    return {
        "artifact": str(recording_hdf5),
        "artifact_sha256": artifact.hdf5_sha256,
        "committed_frames": session.committed_count,
        "episode": session.episode_name,
        "observation_ids": list(session.observation_ids),
        "tracks": [dict(track) for track in session.tracks],
    }
