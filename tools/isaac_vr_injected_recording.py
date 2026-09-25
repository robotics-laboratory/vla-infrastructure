"""Deterministic no-headset integration transitions for the real Kit recorder seam."""

from __future__ import annotations

from pathlib import Path
import hashlib
import time
from typing import Any, Callable, Mapping

import numpy as np

from isaac_s1_runtime import NativeBimanualTargets, d0_action_to_native
from isaac_s2_processor import ArmTeleopCommand, BimanualTeleopCommand, PROCESSOR_REVISION
from tools.d0_causal import CausalTransactionValidator
from tools.isaac_vr_decision import (
    ResolvedXrInput,
    SolvedControlDecision,
    commit_recording_transition,
    decision_epoch,
    capture_state_snapshot,
)


def _command(
    grippers: tuple[float, float], *, left_clutch: bool = False,
    left_transition: str | None = None,
) -> BimanualTeleopCommand:
    transition = left_transition or ("clutch_held" if left_clutch else "motion")
    arms = tuple(
        ArmTeleopCommand(
            delta_pose=np.zeros(6, dtype=np.float64),
            gripper_aperture_m=gripper,
            motion_active=not (transition != "motion" and index == 0),
            tracking_valid=True,
            clutch_active=transition in {"clutch_engaged", "clutch_held"} and index == 0,
            rebased=transition == "clutch_release_rebased" and index == 0,
            sensitivity_mode="normal",
            translation_scale=1.0,
            rotation_scale=1.0,
            transition=transition if index == 0 else "motion",
        )
        for index, gripper in enumerate(grippers)
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


def _audit_reference_state(env: Any) -> tuple[float, ...]:
    """Use the selected reset targets so paired input bytes do not depend on capture noise."""
    home = env.vr_runtime.config["scene"]["candidate_home_d0_per_arm"]
    return tuple(float(value) for side in ("left", "right") for value in home[side])


def _clutch_transition(index: int) -> str:
    phase = index % 300
    if phase == 100:
        return "clutch_engaged"
    if 101 <= phase <= 104:
        return "clutch_held"
    if phase == 105:
        return "clutch_release_rebased"
    return "motion"


def record_injected_transitions(
    recording: Any,
    env: Any,
    *,
    count: int = 3,
    benchmark_logger: Any | None = None,
    resource_sampler: Any | None = None,
    performance_logger: Any | None = None,
    require_distinct_actions: bool = True,
    rgb_e2e_assay: bool = False,
    input_pump: Callable[[], Any] | None = None,
    fixed_input: bool = False,
    clutch_pattern: bool = False,
    start_tick: int = 1,
    target_index_offset: int = 0,
    first_commit_callback: Callable[[], None] | None = None,
    pre_step_callback: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Write distinct committed transitions through the production causal/writer APIs."""
    if count < 2:
        raise ValueError("injected integration requires at least two transitions")
    if rgb_e2e_assay and count != 6:
        raise ValueError("RGB end-to-end assay requires exactly six transitions")
    if (benchmark_logger is None) is not (resource_sampler is None):
        raise ValueError("benchmark logger and resource sampler must be supplied together")
    validator = None
    initial_state = _audit_reference_state(env) if fixed_input else None
    actions: list[list[float]] = []
    input_digest = hashlib.sha256()
    transition_counts: dict[str, int] = {}
    for index in range(count):
        if pre_step_callback is not None:
            pre_step_callback()
        tick = start_tick + index
        benchmark_started_ns = time.perf_counter_ns()
        if performance_logger is not None:
            performance_logger.begin_step()
            stage_started_ns = time.perf_counter_ns()
        if input_pump is not None:
            input_pump()
        if performance_logger is not None:
            performance_logger.add_stage(
                "teleop_advance", time.perf_counter_ns() - stage_started_ns
            )
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
                profile="isaac_human_vr_offline_rgb_v2",
            )
        if initial_state is None:
            initial_state = token.state
        target_index = index + target_index_offset
        left_transition = _clutch_transition(target_index) if clutch_pattern else "motion"
        if rgb_e2e_assay:
            # Deliberately separated wrist-camera poses, generated by native
            # actuation before recorder capture. No HDF state is edited.
            action = np.asarray(initial_state, dtype=np.float64).copy()
            action[0] += (0, 22, -18, 24, -22, 12)[index]
            action[7] += (0, -20, 20, -24, 22, -12)[index]
            if index == 2:
                action[:7] = np.asarray(token.state[:7], dtype=np.float64)
            target = d0_action_to_native(action)
        else:
            action = _target(initial_state, target_index)
            if left_transition != "motion":
                action[:7] = np.asarray(token.state[:7], dtype=np.float64)
            target = d0_action_to_native(action)
        native = np.concatenate((target.left_rad_m, target.right_rad_m))
        input_digest.update(np.asarray(native, dtype="<f8").tobytes())
        command = _command(
            (float(target.left_rad_m[6]), float(target.right_rad_m[6])),
            left_clutch=rgb_e2e_assay and index == 2,
            left_transition=left_transition if clutch_pattern else None,
        )
        transition_counts[command.left.transition] = (
            transition_counts.get(command.left.transition, 0) + 1
        )
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
        if index == 0 and first_commit_callback is not None:
            first_commit_callback()
        if performance_logger is not None:
            performance_logger.add_stage(
                "causal_commit_and_record", time.perf_counter_ns() - stage_started_ns
            )
            stage_started_ns = time.perf_counter_ns()
        actions.append([float(value) for value in decision.dataset_action])
        if performance_logger is not None:
            performance_logger.add_stage(
                "runtime_bookkeeping", time.perf_counter_ns() - stage_started_ns
            )
        if benchmark_logger is not None:
            rejected = sum(int(value) for value in recording.rejections.values())
            assert resource_sampler is not None
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
    # Long experiments may retain the original bounded sweep beyond its
    # 1000-control period; repeated actions still require distinct causal rows.
    if require_distinct_actions and len({tuple(action) for action in actions}) != count:
        raise RuntimeError("injected integration actions are not distinct")
    return {
        "actions": actions,
        "accepted_transactions": validator.accepted_transactions,
        "committed_frames": recording.committed_frames,
        "processor_revision": PROCESSOR_REVISION,
        "source": "deterministic_injected_xr_v1",
        "rgb_e2e_assay": rgb_e2e_assay,
        "input_targets_sha256": input_digest.hexdigest(),
        "left_transition_counts": transition_counts,
    }


def run_injected_controls(
    env: Any, *, count: int, performance_logger: Any,
    input_pump: Callable[[], Any] | None = None, start_tick: int = 1,
) -> dict[str, Any]:
    """Matched native-target RUN control loop without recorder side effects."""
    reference = _audit_reference_state(env)
    digest = hashlib.sha256()
    for index in range(count):
        tick = start_tick + index
        performance_logger.begin_step()
        started_ns = time.perf_counter_ns()
        if input_pump is not None:
            input_pump()
        performance_logger.add_stage("teleop_advance", time.perf_counter_ns() - started_ns)
        started_ns = time.perf_counter_ns()
        capture_state_snapshot(env)
        performance_logger.add_stage("observation_capture", time.perf_counter_ns() - started_ns)
        started_ns = time.perf_counter_ns()
        target = d0_action_to_native(_target(reference, index))
        native = np.concatenate((target.left_rad_m, target.right_rad_m))
        digest.update(np.asarray(native, dtype="<f8").tobytes())
        env._apply(NativeBimanualTargets(
            target.left_rad_m.copy(), target.right_rad_m.copy(), target.saturated
        ))
        performance_logger.add_stage("injected_decision_apply", time.perf_counter_ns() - started_ns)
        started_ns = time.perf_counter_ns()
        env._advance(4)
        performance_logger.add_stage("simulation_advance", time.perf_counter_ns() - started_ns)
        performance_logger.add_stage("runtime_bookkeeping", 0)
        performance_logger.end_step(tick, source="deterministic_injected_native_v1")
    return {"control_steps": count, "input_targets_sha256": digest.hexdigest()}


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
