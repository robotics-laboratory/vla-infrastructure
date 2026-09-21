"""Exact producer-boundary tests without Isaac, RTX, or image entropy assumptions."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import time
import subprocess
import json

import numpy as np
import pytest
import torch

from tools.isaac_s1_runtime import native_state_to_d0
from tools.isaac_vr_capture import ProducerBoundary, ROLES, ThreeCameraCapture

ROOT = Path(__file__).resolve().parents[1]


class Camera:
    def __init__(self):
        self.frame = np.array([0])
        self._data_generation = self._data_generation_last_update = 0
        self.data = NS(output={"rgba": np.zeros((1, 480, 640, 4), dtype=np.uint8)})
        self.updates = 0
        self.fault = None
        self.clock = lambda: 0
        self.producer_step = None

    def update(self, dt, force_recompute=False):
        self.updates += 1
        self._data_generation += 1
        if self.fault:
            self.fault(self)
            return
        self.frame += 1
        self.producer_step = self.clock()
        self._data_generation_last_update = self._data_generation

    def reset(self):
        self.frame[:] = 0
        self._data_generation += 1


def bundle():
    source = NS(epoch=1, step=25, render=25, state_step=25)
    cameras = {role: Camera() for role in ROLES}
    capture = ThreeCameraCapture(
        cameras,
        lambda: ProducerBoundary(source.epoch, source.step, source.render),
        lambda: (source.state_step, (float(source.state_step),) * 14),
    )
    return source, cameras, capture


def test_alignment_identical_pixels_and_owned_freeze_without_acquisition():
    source, cameras, capture = bundle()
    for step in (25, 29, 33):
        source.step = source.state_step = source.render = step
        snapshot = capture.capture(1 / 30)
        assert snapshot.state[0] == snapshot.producer.physics_step == step
        assert tuple(x.role for x in snapshot.cameras) == ROLES
        assert capture.latest() is capture.latest() is snapshot
        frozen = capture.freeze()
        assert list(frozen) == ["observation.state", *(f"observation.images.{r}" for r in ROLES)]
        for role in ROLES:
            assert frozen[f"observation.images.{role}"].shape == (480, 640, 3)
            assert not np.shares_memory(frozen[f"observation.images.{role}"], cameras[role].data.output["rgba"])
        assert {c.updates for c in cameras.values()} == {snapshot.capture_cycle}
        assert source.render == step


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("fault", ["raise", "frozen", "old_receipt", "empty", "dtype"])
def test_no_partial_publication(role, fault):
    _, cameras, capture = bundle()
    assert capture.capture(1 / 30)
    def fail(camera):
        if fault == "raise":
            raise RuntimeError("extraction failed")
        if fault == "frozen":
            return
        camera.frame += 1
        if fault == "old_receipt":
            return  # A retained old source buffer has no new completed generation.
        camera._data_generation_last_update = camera._data_generation
        camera.data.output["rgba"] = np.zeros((0,) if fault == "empty" else (1, 480, 640, 4), dtype=np.float32)
    cameras[role].fault = fail
    assert capture.capture(1 / 30) is None
    assert capture.successful_capture_cycle == 1 and capture.failed_attempts == 1
    with pytest.raises(RuntimeError):
        capture.latest()


@pytest.mark.parametrize("field", ["step", "render", "epoch"])
def test_changed_producer_mid_extraction(field):
    source, cameras, capture = bundle()
    def change(camera):
        camera.frame += 1
        camera._data_generation_last_update = camera._data_generation
        setattr(source, field, getattr(source, field) + 1)
    cameras["right_wrist"].fault = change
    assert capture.capture(1 / 30) is None
    assert capture.successful_capture_cycle == 0


def test_epoch_reset_and_stale_buffer_consumer():
    source, cameras, capture = bundle()
    first = capture.capture(1 / 30)
    source.epoch += 1
    for camera in cameras.values():
        camera.reset()
    second = capture.capture(1 / 30)
    assert first.cameras[0].frame == second.cameras[0].frame == 1
    assert first.producer != second.producer
    cameras["scene"].data.output["rgba"] = cameras["scene"].data.output["rgba"].copy()
    with pytest.raises(RuntimeError, match="buffer replaced"):
        capture.freeze()


def test_state_binding_and_startup_admission():
    source, _, capture = bundle()
    source.state_step += 1
    assert capture.capture(1 / 30) is None
    source.state_step = source.step
    assert capture.capture(1 / 30, eligible=False)
    with pytest.raises(RuntimeError, match="Startup"):
        capture.latest()
    capture.latest(require_eligible=False)
    assert capture.capture(1 / 30)
    source.step += 1
    with pytest.raises(RuntimeError, match="boundary"):
        capture.freeze()


def load_class(path, name, namespace, baseline=False):
    source = subprocess.check_output(["git", "show", f"b3577b4613d0669efcee72493b66e4148de745c3:{path}"], cwd=ROOT, text=True) if baseline else (ROOT / path).read_text()
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def environment(monkeypatch, baseline=False):
    # Execute production methods, replacing only external physics/renderer objects.
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    namespace = {"Camera": Camera, "Any": object, "torch": torch, "_tensor": lambda x: x,
                 "_BimanualCameraData": lambda x: NS(),
                 "ThreeCameraCapture": ThreeCameraCapture, "ProducerBoundary": ProducerBoundary, "CAMERA_PERIOD": 1 / 30}
    Rig = load_class("tools/isaac_vr_runtime.py", "VRCameraRig", namespace, baseline)
    env_namespace = {"torch": torch, "np": np, "Any": object, "NativeBimanualTargets": object,
                     "time": time, "PHYSICS_DT": 1 / 120, "seed_reset": lambda x: None,
                     "d0_action_to_native": lambda x: x, "_cpu": lambda x: x,
                     "native_state_to_d0": native_state_to_d0}
    Env = load_class("tools/run_isaac_s1.py", "BimanualPiperXIsaacEnvironment", env_namespace, baseline)
    env = object.__new__(Env)
    env.sim = NS(step_count=0, render_generation=0,
                 visualizers=[NS(pumps_app_update=lambda: True, _app_pumped_this_step=True)])
    env.sim.get_physics_step_count = lambda: env.sim.step_count
    def step():
        env.sim.step_count += 1
        env.sim.render_generation += 1
    env.sim.step = step
    def robot():
        obj = NS(data=NS(joint_pos=np.zeros((1, 7)), default_root_pose=NS(torch=torch.zeros((1, 7))),
                         default_root_vel=NS(torch=torch.zeros((1, 6)))),
                 write_data_to_sim=lambda: None, reset=lambda: None,
                 write_root_pose_to_sim_index=lambda **kw: None, write_root_velocity_to_sim_index=lambda **kw: None)
        def update(dt):
            obj.data.joint_pos[:] = env.sim.step_count / 1000
        obj.update = update
        return obj
    env.robots = [robot(), robot()]
    env.joint_ids = [list(range(7)), list(range(7))]
    env.physics_probe = robot()
    env.vr_runtime = NS(before_render=lambda: None, update=lambda dt: None, reset_scene=lambda: None,
                        _validation_complete=False)
    cameras = [Camera() for _ in ROLES]
    env.camera = Rig(tuple(cameras[:2]), cameras[2])
    env.home_d0 = np.zeros(14)
    env._set_state = lambda x: None
    env.observation = lambda: {}
    for camera in cameras:
        camera.clock = env.sim.get_physics_step_count
    return env, cameras


def test_actual_environment_advance_reset_and_startup_sequence(monkeypatch):
    env, cameras = environment(monkeypatch)
    env.reset(0)
    assert env.sim.step_count == 25
    first = env.camera.capture.latest(require_eligible=False)
    assert first.producer.physics_step == 25 and first.state[6] == 25
    with pytest.raises(RuntimeError, match="Startup"):
        env.latest_observation_capture()
    env._advance(95)  # canonical run_vr preflight to 120
    assert env.camera.capture.latest(require_eligible=False).producer.physics_step == 120
    env.vr_runtime._validation_complete = True
    env.reset(0)  # run_s2 really performs another reset before the first decision
    assert env.latest_observation_capture().producer.physics_step == 145
    for target in (149, 153):
        env._advance(4)
        snapshot = env.latest_observation_capture()
        assert snapshot.producer.physics_step == target
        assert snapshot.state[6] == pytest.approx(target)
        assert env.sim.render_generation == target
    assert {camera.updates for camera in cameras} == {5}


def test_baseline_phase_reproduction_and_bounded_synthetic_cost(monkeypatch):
    results = {}
    for baseline in (True, False):
        env, cameras = environment(monkeypatch, baseline)
        env.vr_runtime._validation_complete = True
        env.reset(0)
        alignment = [(env.sim.step_count, cameras[0].producer_step)]
        for _ in range(2):
            env._advance(4)
            alignment.append((env.sim.step_count, cameras[0].producer_step))
        expected = [(25, 24), (29, 28), (33, 32)] if baseline else [(25, 25), (29, 29), (33, 33)]
        assert alignment == expected
        before_renders = env.sim.render_generation
        before_updates = sum(c.updates for c in cameras)
        started = time.perf_counter_ns()
        for _ in range(300):
            env._advance(4)
        elapsed = time.perf_counter_ns() - started
        assert env.sim.render_generation - before_renders == 1200
        assert sum(c.updates for c in cameras) - before_updates == 900
        results["before" if baseline else "after"] = {
            "alignment": alignment, "synthetic_control_mean_us": elapsed / 300 / 1000,
            "physics_and_render_steps": 1200, "camera_updates": 900,
            "mandatory_rgb_cpu_copies": 0,
        }
    print("SYNTHETIC_CAPTURE_COMPARISON=" + json.dumps(results, sort_keys=True))


def test_scene_first_success_then_wrist_failure_still_all_or_none():
    _, cameras, capture = bundle()
    capture.cameras = {r: cameras[r] for r in ("scene", "left_wrist", "right_wrist")}
    def fail(camera):
        raise RuntimeError("wrist fails after scene completed")
    cameras["left_wrist"].fault = fail
    assert capture.capture(1 / 30) is None
    assert cameras["scene"].frame[0] == 1
    assert capture.successful_capture_cycle == 0


def test_plain_s1_scheduler_retains_per_substep_camera_updates(monkeypatch):
    env, _ = environment(monkeypatch)
    env.vr_runtime = None
    env.camera = Camera()
    env.reset(0)
    assert env.sim.step_count == env.camera.updates == 25
    env._advance(4)
    assert env.sim.step_count == env.camera.updates == 29


def test_state_changes_during_read_is_rejected(monkeypatch):
    env, _ = environment(monkeypatch)
    env.reset(0)
    class Changed:
        @property
        def joint_pos(self):
            env.sim.step_count += 1
            return np.zeros((1, 7))
    env.robots[0].data = Changed()
    with pytest.raises(RuntimeError, match="state generation"):
        env.capture_measured_state()


def test_headless_kit_claim_without_real_pump_rejected(monkeypatch):
    env, cameras = environment(monkeypatch)
    env.sim.visualizers[0]._app_pumped_this_step = False
    with pytest.raises(RuntimeError, match="No completed Kit RTX pump"):
        env.reset(0)
    assert env.camera.capture_cycles_total == 0
    assert not any(camera.updates for camera in cameras)
