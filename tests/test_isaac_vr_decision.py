"""Exact observation/XR/IK seam and original-native arithmetic regression."""
import ast
from dataclasses import replace
from pathlib import Path
import subprocess
from types import SimpleNamespace as NS
from typing import Any

import numpy as np
import pytest
import torch

from tools.d0_causal import STATE_ONLY_SIM_SOURCES, CausalTransactionValidator
from tools.isaac_s1_runtime import NativeBimanualTargets
from tools.isaac_s2_processor import BimanualS2TeleopProcessor, ControllerDeltaSample, S2ProcessorConfig
from tools.isaac_vr_capture import CameraIdentity, ObservationCapture, ProducerBoundary
from tools.isaac_vr_decision import (
    SolvedControlDecision, StateOnlyObservation, XrInputReceipt, capture_state_only_observation,
    check_observation, complete_recorded_transition, decision_epoch,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = "4423cacfd1ed226bc0169cc55890589e2a5b2a4c"


def capture(step=20, reset=1):
    return ObservationCapture(ProducerBoundary(reset, step, step), step,
                              tuple(CameraIdentity(r, step, step) for r in
                                    ("left_wrist", "right_wrist", "scene")), (0.,) * 14, True)


def sample(trigger=0.0, squeeze=0., valid=True, sensitivity=0., delta=0.003):
    return ControllerDeltaSample(np.full(3, delta), np.full(3, delta), True,
                                 valid, squeeze, trigger, sensitivity)


def xr_receipt():
    r = XrInputReceipt()
    r.polled(object(), 7)
    r.transformed(((), ()), np.eye(4), False)
    info = NS(ran_synchronously=True, worker_exception=None, submitted_frame_id=7,
              returned_frame_id=7)
    return r, info, r.resolve(info, 0)


def load_ik(baseline=False):
    source = (subprocess.check_output(["git", "show", f"{BASE}:tools/isaac_s2_runtime.py"],
                                     cwd=ROOT, text=True) if baseline else
              (ROOT / "tools/isaac_s2_runtime.py").read_text())
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef)
                and n.name == "_BimanualDifferentialIk")
    namespace = dict(np=np, Any=Any, BimanualS2TeleopProcessor=BimanualS2TeleopProcessor,
                     NativeBimanualTargets=NativeBimanualTargets,
                     SolvedControlDecision=SolvedControlDecision, check_observation=check_observation)
    exec(compile(ast.Module([node], []), "actual_ik_wrapper", "exec"), namespace)
    return namespace["_BimanualDifferentialIk"]


def ik_fixture(baseline=False):
    class Controller:
        calls = 0

        def set_command(self, delta, **kwargs):
            self.delta = delta

        def compute(self, pos, quat, jac, joints):
            self.calls += 1
            return joints + self.delta

    robots = [NS(data=NS(
        joint_limits=NS(torch=torch.tensor([[[-0.1, 0.1]] * 6])),
        joint_pos=NS(torch=torch.full((1, 6), .031234567)),
        body_link_pose_w=NS(torch=torch.zeros((1, 2, 7))),
        body_link_jacobian_w=NS(torch=torch.ones((1, 2, 6, 6)))),
        is_fixed_base=True, num_base_dofs=0) for _ in range(2)]
    obs = capture()
    env = NS(robots=robots, wrist_ids=[1, 1], joint_ids=[list(range(6))] * 2,
             sim=NS(device="cpu", get_physics_step_count=lambda: env.step),
             step=20, _state_physics_step=20, observation=obs, applied=[],
             latest_observation_capture=lambda: env.observation)
    env._apply = env.applied.append
    cls = load_ik(baseline)
    ik = cls.__new__(cls)
    ik.env, ik.torch, ik.controllers = env, torch, (Controller(), Controller())
    return ik, env


@pytest.mark.parametrize("field,value", [("ran_synchronously", False),
                                          ("returned_frame_id", 6),
                                          ("submitted_frame_id", 8)])
def test_delayed_or_mismatched_result_rejected(field, value):
    r, info, _ = xr_receipt()
    setattr(info, field, value)
    with pytest.raises(RuntimeError, match="mismatch"):
        r.resolve(info, 0)


def test_reuse_new_session_and_reference_invalidation():
    r, info, xr = xr_receipt()
    r.validate(xr)
    r.last_consumed = xr.deviceio_update_epoch
    with pytest.raises(RuntimeError, match="reused"):
        r.validate(xr)
    r.polled(object(), 0)
    assert r.session_epoch == 2 and r.update_epoch == 2
    with pytest.raises(RuntimeError):
        r.validate(xr)
    r, _, xr = xr_receipt()
    r.reference_epoch += 1
    with pytest.raises(RuntimeError):
        r.validate(xr)


@pytest.mark.parametrize("mutation", ["advance", "reset", "old_observation", "state_generation"])
def test_observation_mismatch_before_solve_and_apply(mutation):
    ik, env = ik_fixture()
    proc = BimanualS2TeleopProcessor()
    command = proc.advance(sample(), sample())
    obs = env.observation
    solution = ik.solve(command, obs)
    if mutation == "advance":
        env.step += 1
    elif mutation == "state_generation":
        env._state_physics_step += 1
    else:
        env.observation = capture(19 if mutation == "old_observation" else 20, reset=2)
    with pytest.raises(RuntimeError, match="generation mismatch"):
        ik.solve(command, obs)
    with pytest.raises(RuntimeError, match="generation mismatch"):
        ik.apply(solution)
    assert not env.applied


def test_both_arms_validate_before_either_is_applied():
    ik, env = ik_fixture()
    env.robots[1].data.joint_pos.torch[:] = float("nan")
    proc = BimanualS2TeleopProcessor()
    with pytest.raises(RuntimeError, match="Non-finite"):
        ik.solve(proc.advance(sample(), sample()))
    assert not env.applied


@pytest.mark.parametrize("sensitivity", [-1., 0., 1.])
@pytest.mark.parametrize("trigger", [0., .25, .5, .75, 1.])
def test_original_native_parity_and_preclip_precision(sensitivity, trigger):
    cfg = S2ProcessorConfig(sensitivity_control_mode="slider",
                           slider_min_translation_scale=2., slider_min_rotation_scale=2.,
                           slider_center_translation_scale=4., slider_center_rotation_scale=4.,
                           slider_max_translation_scale=6., slider_max_rotation_scale=6.)
    proc = BimanualS2TeleopProcessor(cfg)
    old, old_env = ik_fixture(True)
    new, env = ik_fixture()
    cases = [sample(trigger=trigger, sensitivity=sensitivity, **kw) for kw in (
        {}, {}, {"delta": 0.}, {"squeeze": 1.}, {"squeeze": 1.}, {},
        {"valid": False}, {"valid": False}, {}, {}, {"delta": 3.})]
    for tick, s in enumerate(cases):
        command = proc.advance(s, s)
        saturated = old.apply(command)
        solution = new.solve(command, env.observation, tick=tick)
        assert new.apply(solution) == saturated
        for side in ("left_rad_m", "right_rad_m"):
            # Native->tuple->native preserves the old concatenate(float32, float64) values.
            assert getattr(env.applied[-1], side).tobytes() == getattr(old_env.applied[-1], side).tobytes()
        desired = np.asarray(solution.native_preclip).reshape(2, 7)
        label = np.frombuffer(solution.canonical_d0_action, dtype="<f4").reshape(2, 7)
        expected = desired.copy()
        expected[:, :6] = np.rad2deg(expected[:, :6])
        expected[:, 6] *= 1000
        np.testing.assert_array_equal(label, expected.astype(np.float32))
        assert np.max(abs(np.deg2rad(label[:, :6].astype(float)) - desired[:, :6])) < 2e-6
        assert not command.left.delta_pose.flags.writeable
        with pytest.raises(ValueError):
            command.left.delta_pose.setflags(write=True)
        if tick == len(cases) - 1:
            assert solution.saturated and any(solution.residual)
            assert label[0, 0] > np.rad2deg(env.applied[-1].left_rad_m[0])
    assert [c.calls for c in new.controllers] == [len(cases)] * 2


def test_prepared_only_validator_and_processor_generation():
    ik, env = ik_fixture()
    proc = BimanualS2TeleopProcessor()
    first = proc.advance(sample(), sample())
    r, _, xr = xr_receipt()
    epoch = decision_epoch("test_run", env.observation, xr)
    v = CausalTransactionValidator("isaac", "human_vr", epoch)
    with pytest.raises(RuntimeError, match="Tracking/rebase"):
        ik.solve(first, env.observation, xr, 1).prepare(v)
    command = proc.advance(sample(), sample())
    solution = ik.solve(command, env.observation, xr, 2)
    prepared = solution.prepare(v)
    assert prepared.physical is None and len(prepared.sources) == 8
    assert v.accepted_transactions == 0
    assert command.processor_generation > first.processor_generation
    proc.reset()
    assert proc.generation > command.processor_generation
    with pytest.raises(ValueError, match="transition_not_completed"):
        v.commit(prepared, observation_payload=b"", action_payload=b"")
    v.abort()
    with pytest.raises(ValueError, match="tick_reuse"):
        solution.prepare(v)
    with pytest.raises(RuntimeError, match="eligible"):
        replace(solution, xr_identity=replace(xr, rebased=True)).prepare(v)


@pytest.mark.parametrize("mutation", ["reset_reference", "old_xr", "processor", "replay"])
def test_apply_rechecks_xr_and_processor_before_native_write(mutation):
    ik, env = ik_fixture()
    r, _, xr = xr_receipt()
    proc = BimanualS2TeleopProcessor()
    proc.advance(sample(), sample())
    command = proc.advance(sample(), sample())
    ik.device = NS(validate_xr=r.validate, xr_receipt=r)
    ik.processor = proc
    solution = ik.solve(command, env.observation, xr, 1)
    if mutation == 'reset_reference':
        r.reference_epoch += 1
    elif mutation == 'old_xr':
        r.polled(r.session, 8)
    elif mutation == 'processor':
        proc.reset()
    else:
        ik.apply(solution)
        env.applied.clear()
    with pytest.raises(RuntimeError):
        ik.apply(solution)
    assert not env.applied


def test_mimic_mapping_and_four_step_schedule_unchanged():
    current = (ROOT / 'tools/run_isaac_s1.py').read_text()
    baseline = subprocess.check_output(['git', 'show', f'{BASE}:tools/run_isaac_s1.py'],
                                       cwd=ROOT, text=True)
    def method(source, name):
        cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef)
                   and n.name == 'BimanualPiperXIsaacEnvironment')
        return ast.dump(next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name))
    for name in ('_with_mimics', '_apply', '_advance'):
        assert method(current, name) == method(baseline, name)
    # Actual loop test also asserts each invoked repeat below; no extra substep is added.


def test_float32_label_overflow_rejects_before_application():
    with pytest.raises(RuntimeError, match="float32 D0"):
        SolvedControlDecision.from_native(1, None, None, None, [3e38] * 14, [0.] * 14)


def test_noneligible_run_solution_has_no_control_tick_identity():
    ik, _ = ik_fixture()
    proc = BimanualS2TeleopProcessor()
    solution = ik.solve(proc.session_inactive())
    assert solution.control_tick_id is None


def test_state_only_observation_never_reads_camera_and_commits_successor():
    state = (0.0,) * 14
    env = NS(
        step=20, camera=NS(reset_epoch=3),
        sim=NS(render_generation=9, get_physics_step_count=lambda: env.step),
        capture_measured_state=lambda: (env.step, state),
    )
    observation = capture_state_only_observation(env)
    assert isinstance(observation, StateOnlyObservation)
    check_observation(env, observation)
    receipt, _, xr = xr_receipt()
    command = NS(
        session_active=True,
        left=NS(tracking_valid=True, rebased=False),
        right=NS(tracking_valid=True, rebased=False),
    )
    solution = SolvedControlDecision.from_native(
        1, observation, xr, command, np.zeros(14), np.zeros(14)
    )
    validator = CausalTransactionValidator(
        "isaac", "human_vr", decision_epoch("test", observation, xr),
        sim_sources=STATE_ONLY_SIM_SOURCES,
    )
    prepared = solution.prepare(validator)
    env.step = 24
    complete_recorded_transition(solution, validator, prepared, capture_state_only_observation(env))
    assert validator.accepted_transactions == 1
