from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from lerobot_env_piperx_mujoco.teleop import (
    CONTROLLER_TO_SCENE,
    PiperXMujocoQuestIkProcessor,
    QuestIkConfig,
    controller_delta_to_scene,
    configure_quest_gripper_actuators,
)
from lerobot_env_piperx_mujoco.constants import ACTION_REPEAT, JOINT_LIMITS_DEG, PHYSICS_HZ
from tools.isaac_s2_processor import ArmTeleopCommand, BimanualTeleopCommand
from tools.mujoco_quest_control import MujocoQuestTeleopMessageProcessor
from tools.mujoco_quest_upstream import POSITION_DEADBAND_M, ROTATION_DEADBAND_RAD
from tools.run_mujoco_quest import (
    _arm_plant_diagnostics,
    _build_solvers,
    _close_runtime_resources,
    _gripper_plant_diagnostics,
    _head_relative_stage_pose,
    _load_config,
    _missing_controller_tracking,
    _processor_config,
    _wait_for_cloudxr_wss,
)


ROOT = Path(__file__).resolve().parents[1]


def _set_gripper_target(model: object, data: object, side: str, aperture_m: float) -> None:
    data.actuator(f"{side}_gripper_aperture_position").ctrl = aperture_m


def _aperture(data: object, side: str) -> float:
    return float(
        data.joint(f"{side}_gripper_joint1").qpos[0]
        - data.joint(f"{side}_gripper_joint2").qpos[0]
    )


@dataclass
class _FakeSolver:
    solution_offset_deg: float = 0.0

    def forward_kinematics(self, joints: np.ndarray) -> np.ndarray:
        pose = np.eye(4)
        pose[:3, 3] = joints[:3] / 100.0
        return pose

    def inverse_kinematics(
        self,
        current: np.ndarray,
        target: np.ndarray,
        *,
        position_weight: float,
        orientation_weight: float,
    ) -> np.ndarray:
        del target, position_weight, orientation_weight
        return current + self.solution_offset_deg


def _arm(
    delta: np.ndarray,
    *,
    gripper_m: float = 0.05,
    rebased: bool = False,
) -> ArmTeleopCommand:
    return ArmTeleopCommand(
        delta_pose=delta,
        gripper_aperture_m=gripper_m,
        motion_active=bool(np.any(delta)),
        tracking_valid=True,
        clutch_active=False,
        rebased=rebased,
        sensitivity_mode="normal",
        transition="motion",
    )


def test_controller_delta_uses_v39_scene_basis() -> None:
    delta = controller_delta_to_scene([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    np.testing.assert_array_equal(delta, [-3.0, -1.0, 2.0, -6.0, -4.0, 5.0])
    np.testing.assert_allclose(CONTROLLER_TO_SCENE @ CONTROLLER_TO_SCENE.T, np.eye(3))
    assert np.linalg.det(CONTROLLER_TO_SCENE) == pytest.approx(1.0)


def test_controller_human_directions_match_m1_scene_semantics() -> None:
    controller_forward = np.asarray([0.0, 0.0, -1.0, 0.0, 0.0, 0.0])
    controller_right = np.asarray([1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    controller_up = np.asarray([0.0, 1.0, 0.0, 0.0, 0.0, 0.0])

    np.testing.assert_array_equal(controller_delta_to_scene(controller_forward)[:3], [1, 0, 0])
    np.testing.assert_array_equal(controller_delta_to_scene(controller_right)[:3], [0, -1, 0])
    np.testing.assert_array_equal(controller_delta_to_scene(controller_up)[:3], [0, 0, 1])


def test_v39_profile_restores_usable_rotation_bound_and_requires_bimanual_tracking() -> None:
    config = _load_config(ROOT / "configs/mujoco_quest_runtime.yaml")
    processor_config = _processor_config(config)

    assert config["revision"] == "piperx_mujoco_quest_teleop_v39"
    assert config["control"]["lifecycle"]["required_tracking_startup_timeout_s"] == 10.0
    assert config["control"]["controller_to_scene_rotation"]["matrix"] == [
        [0.0, 0.0, -1.0],
        [-1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    assert processor_config.normal_translation_scale == 0.5
    assert processor_config.normal_rotation_scale == 0.5
    assert processor_config.precise_translation_scale == 0.125
    assert processor_config.precise_rotation_scale == 0.125
    assert config["control"]["ik"]["max_gripper_step_mm"] == 10.0
    assert config["control"]["ik"]["max_rotation_delta_rad"] == 0.05
    assert config["control"]["gripper"]["actuator"]["aperture_force_limit_n"] == 8.0
    assert config["control"]["gripper"]["actuator"]["aperture_kv"] == 45.0
    assert config["control"]["gripper"]["actuator"]["center_constraint_timeconst_s"] == 0.02
    assert config["control"]["gripper"]["actuator"]["center_constraint_damping_ratio"] == 1.0
    assert config["control"]["ik"]["orientation_weight"] == 0.01
    assert config["control"]["ik"]["controller_rotation_enabled"] is True
    assert config["control"]["ik"]["rotation_activation_threshold_rad"] == 0.006
    assert config["control"]["ik"]["minimum_translation_alignment"] == 0.5
    assert config["control"]["ik"]["gripper_arm_open_threshold_mm"] == 95.0
    assert config["control"]["ik"]["max_joint_tracking_error_deg"] == 25.0
    assert config["control"]["sensitivity"]["deadband"] == {
        "translation_m": 0.00025,
        "rotation_rad": 0.0025,
    }
    assert POSITION_DEADBAND_M == 0.00025
    assert ROTATION_DEADBAND_RAD == 0.0025


def test_v8_panels_use_transparent_head_relative_placement() -> None:
    config = _load_config(ROOT / "configs/mujoco_quest_runtime.yaml")
    presentation = config["xr_presentation"]
    assert presentation["clear_rgba"] == [0.0, 0.0, 0.0, 0.0]
    assert all("position_head_m" in layer for layer in presentation["layers"].values())
    assert all(
        "position_openxr_m" not in layer for layer in presentation["layers"].values()
    )

    # A 90-degree yaw around OpenXR +Y rotates head-forward (-Z) to stage-left
    # (-X); the screen keeps the same pose relative to the user's initial gaze.
    half = np.sqrt(0.5)
    head = SimpleNamespace(
        position=(2.0, 1.6, 3.0),
        orientation=(half, 0.0, half, 0.0),
    )
    position, orientation = _head_relative_stage_pose(
        head,
        (0.0, -0.2, -1.0),
        (1.0, 0.0, 0.0, 0.0),
    )
    np.testing.assert_allclose(position, [1.0, 1.4, 3.0], atol=1.0e-12)
    np.testing.assert_allclose(orientation, head.orientation, atol=1.0e-12)


def test_direct_file_launcher_can_import_repository_tools(tmp_path: Path) -> None:
    pytest.importorskip("isaacteleop")
    invalid_config = tmp_path / "invalid.yaml"
    invalid_config.write_text("[]\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_mujoco_quest.py"),
            "--config",
            str(invalid_config),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "must contain one YAML mapping" in completed.stderr
    assert "No module named 'tools'" not in completed.stderr


def test_launcher_waits_for_wss_before_blocking_on_openxr(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    class _Connection:
        def __enter__(self) -> "_Connection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def _connect(address: tuple[str, int], *, timeout: float) -> _Connection:
        nonlocal attempts
        assert address == ("127.0.0.1", 48322)
        assert timeout == 0.25
        attempts += 1
        if attempts == 1:
            raise ConnectionRefusedError
        return _Connection()

    monkeypatch.setattr(socket, "create_connection", _connect)
    monkeypatch.setattr("tools.run_mujoco_quest.time.sleep", lambda _seconds: None)

    _wait_for_cloudxr_wss(timeout_s=1.0)

    assert attempts == 2


def test_runtime_releases_mujoco_egl_before_televiz_and_cloudxr() -> None:
    order: list[str] = []

    def resource(name: str, method: str) -> SimpleNamespace:
        return SimpleNamespace(**{method: lambda: order.append(name)})

    failures = _close_runtime_resources(
        resource("panels", "close"),
        resource("env", "close"),
        resource("temporary", "cleanup"),
        resource("cloudxr", "stop"),  # type: ignore[arg-type]
    )

    assert failures == []
    assert order == ["env", "panels", "temporary", "cloudxr"]


def test_teardown_failure_is_recorded_and_does_not_orphan_later_owners() -> None:
    order: list[str] = []

    def broken_env_close() -> None:
        order.append("env")
        raise RuntimeError("EGLError(err=EGL_NOT_INITIALIZED)")

    failures = _close_runtime_resources(
        SimpleNamespace(close=lambda: order.append("panels")),  # type: ignore[arg-type]
        SimpleNamespace(close=broken_env_close),
        SimpleNamespace(cleanup=lambda: order.append("temporary")),
        SimpleNamespace(stop=lambda: order.append("cloudxr")),  # type: ignore[arg-type]
    )

    assert order == ["env", "panels", "temporary", "cloudxr"]
    assert failures == ["env: RuntimeError: EGLError(err=EGL_NOT_INITIALIZED)"]


def test_failed_egl_close_retires_upstream_handles_before_destructors_retry() -> None:
    gl_context = SimpleNamespace(_context=object())
    mjr_context = SimpleNamespace(free=lambda: None)
    renderer = SimpleNamespace(_gl_context=gl_context, _mjr_context=mjr_context)
    native_env = SimpleNamespace(renderer=renderer)

    def broken_close() -> None:
        raise RuntimeError("EGLError(err=EGL_NOT_INITIALIZED)")

    env = SimpleNamespace(close=broken_close, unwrapped=native_env)
    failures = _close_runtime_resources(None, env, None, None)  # type: ignore[arg-type]

    assert failures == ["env: RuntimeError: EGLError(err=EGL_NOT_INITIALIZED)"]
    assert gl_context._context is None
    assert renderer._gl_context is None
    assert renderer._mjr_context is None


def test_gripper_target_is_slew_limited_and_reported() -> None:
    processor = PiperXMujocoQuestIkProcessor({"left": _FakeSolver(), "right": _FakeSolver()})
    state = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])
    release = BimanualTeleopCommand(
        _arm(np.zeros(6), gripper_m=0.1),
        _arm(np.zeros(6), gripper_m=0.1),
        True,
    )
    armed = processor.action(state, release)
    np.testing.assert_array_equal(armed.d0_action, state)
    assert armed.gripper_armed == {"left": True, "right": True}
    command = BimanualTeleopCommand(
        _arm(np.zeros(6), gripper_m=0.025),
        _arm(np.zeros(6), gripper_m=0.075),
        True,
    )
    result = processor.action(state, command)
    np.testing.assert_array_equal(result.d0_action[:6], state[:6])
    np.testing.assert_array_equal(result.d0_action[7:13], state[7:13])
    assert result.d0_action[6] == pytest.approx(40.0)
    assert result.d0_action[13] == pytest.approx(60.0)
    assert result.saturation_mask[[6, 13]].all()
    assert result.saturated


def test_joint_target_accumulates_and_is_held_while_measured_state_lags() -> None:
    processor = PiperXMujocoQuestIkProcessor(
        {"left": _FakeSolver(1.0), "right": _FakeSolver(1.0)},
        QuestIkConfig(iterations_per_tick=1, minimum_translation_alignment=-1.0),
    )
    measured = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])
    moving = BimanualTeleopCommand(
        _arm(np.asarray([0.001, 0, 0, 0, 0, 0])),
        _arm(np.asarray([0.001, 0, 0, 0, 0, 0])),
        True,
    )
    idle = BimanualTeleopCommand(
        _arm(np.zeros(6)),
        _arm(np.zeros(6)),
        True,
    )

    first = processor.action(measured, moving)
    second = processor.action(measured, moving)
    held = processor.action(measured, idle)

    np.testing.assert_allclose(second.d0_action[:6], first.d0_action[:6] + 1.0)
    np.testing.assert_allclose(second.d0_action[7:13], first.d0_action[7:13] + 1.0)
    np.testing.assert_array_equal(held.d0_action, second.d0_action)


def test_gripper_slew_uses_persistent_target_not_lagging_measurement() -> None:
    processor = PiperXMujocoQuestIkProcessor({"left": _FakeSolver(), "right": _FakeSolver()})
    measured = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])
    release = BimanualTeleopCommand(
        _arm(np.zeros(6), gripper_m=0.1),
        _arm(np.zeros(6), gripper_m=0.1),
        True,
    )
    processor.action(measured, release)
    command = BimanualTeleopCommand(
        _arm(np.zeros(6), gripper_m=0.0),
        _arm(np.zeros(6), gripper_m=0.1),
        True,
    )

    first = processor.action(measured, command)
    second = processor.action(measured, command)

    np.testing.assert_allclose(first.d0_action[[6, 13]], [40.0, 60.0])
    np.testing.assert_allclose(second.d0_action[[6, 13]], [30.0, 70.0])
    assert second.gripper_saturated
    assert not second.joint_saturated


def test_gripper_requires_release_after_play_before_accepting_close() -> None:
    processor = PiperXMujocoQuestIkProcessor({"left": _FakeSolver(), "right": _FakeSolver()})
    state = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])
    held_trigger = BimanualTeleopCommand(
        _arm(np.zeros(6), gripper_m=0.0),
        _arm(np.zeros(6), gripper_m=0.0),
        True,
    )
    release = BimanualTeleopCommand(
        _arm(np.zeros(6), gripper_m=0.1),
        _arm(np.zeros(6), gripper_m=0.1),
        True,
    )

    blocked = processor.action(state, held_trigger)
    np.testing.assert_array_equal(blocked.d0_action, state)
    assert blocked.gripper_armed == {"left": False, "right": False}

    arming = processor.action(state, release)
    np.testing.assert_array_equal(arming.d0_action, state)
    assert arming.gripper_armed == {"left": True, "right": True}

    closing = processor.action(state, held_trigger)
    np.testing.assert_allclose(closing.d0_action[[6, 13]], [40.0, 40.0])
    assert closing.gripper_saturated


@pytest.mark.parametrize("goal_m", [0.0, 0.1])
def test_quest_gripper_full_step_response_is_bounded_and_reaches_goal(goal_m: float) -> None:
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(
        str(ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml")
    )
    configure_quest_gripper_actuators(model)
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, 0)
    for _ in range(PHYSICS_HZ):
        mujoco.mj_step(model, data)
    for side in ("left", "right"):
        _set_gripper_target(model, data, side, goal_m)

    apertures = []
    for tick in range(3 * PHYSICS_HZ):
        mujoco.mj_step(model, data)
        if tick % ACTION_REPEAT == ACTION_REPEAT - 1:
            apertures.append([_aperture(data, side) for side in ("left", "right")])
    values = np.asarray(apertures)
    # A deliberately unrealistic instantaneous 50 mm command may cross a soft
    # MuJoCo coordinate limit by less than 5 mm; the pads keep the physical gap
    # bounded and the runtime uses the slew path below.
    assert np.min(values) >= -0.005
    assert np.max(values) <= 0.105
    # The production path below slews by 10 mm/control tick. For this abuse
    # probe only, a direct 100->0 mm jump may settle against the soft joint
    # constraint within 5 mm without being representative of runtime control.
    np.testing.assert_allclose(values[-1], goal_m, atol=0.005)


@pytest.mark.parametrize(("start_m", "goal_m"), [(0.1, 0.0), (0.0, 0.1)])
def test_v8_full_range_gripper_slew_is_monotonic_and_reaches_goal_promptly(
    start_m: float, goal_m: float
) -> None:
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(
        str(ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml")
    )
    configure_quest_gripper_actuators(model)
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, 0)
    for side in ("left", "right"):
        _set_gripper_target(model, data, side, start_m)
    for _ in range(6 * PHYSICS_HZ):
        mujoco.mj_step(model, data)

    target_m = start_m
    apertures = []
    for _ in range(45):
        target_m += float(np.clip(goal_m - target_m, -0.01, 0.01))
        for side in ("left", "right"):
            _set_gripper_target(model, data, side, target_m)
        for _ in range(ACTION_REPEAT):
            mujoco.mj_step(model, data)
        apertures.append(
            [_aperture(data, side) for side in ("left", "right")]
        )

    values = np.asarray(apertures)
    first_within_2_mm = np.flatnonzero(np.max(np.abs(values - goal_m), axis=1) <= 0.002)
    assert first_within_2_mm.size > 0
    reached_index = int(first_within_2_mm[0])
    differences = np.diff(values, axis=0)
    if goal_m == 0.0:
        assert np.max(differences[:reached_index]) <= 1.0e-5
    else:
        assert np.min(differences[:reached_index]) >= -1.0e-5
    assert np.min(values) >= -0.005
    assert np.max(values) <= 0.105
    assert np.max(np.abs(values[reached_index:] - goal_m)) <= 0.005
    assert reached_index + 1 <= 45


def test_v8_open_grippers_hold_aperture_during_smooth_multijoint_motion() -> None:
    """Regression for the open-finger wandering reported in physical run 5."""

    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(
        str(ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml")
    )
    configure_quest_gripper_actuators(model)
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    home = {
        side: np.asarray(
            [data.joint(f"{side}_joint{index}").qpos[0] for index in range(1, 7)]
        )
        for side in ("left", "right")
    }
    for side in ("left", "right"):
        _set_gripper_target(model, data, side, 0.1)
    for _ in range(3 * PHYSICS_HZ):
        mujoco.mj_step(model, data)

    minimum_aperture_m = 0.1
    minimum_aperture_detail: dict[str, object] = {}
    maximum_symmetry_error_m = 0.0
    amplitudes = np.deg2rad([10.0, 10.0, 10.0, 8.0, 8.0, 15.0])
    for tick in range(300):
        offset = amplitudes * np.sin(2.0 * np.pi * tick / 300.0)
        for side in ("left", "right"):
            for index in range(1, 7):
                data.actuator(f"{side}_joint{index}_position").ctrl = (
                    home[side][index - 1] + offset[index - 1]
                )
        for _ in range(ACTION_REPEAT):
            mujoco.mj_step(model, data)
        for side in ("left", "right"):
            follower_1 = float(data.joint(f"{side}_gripper_joint1").qpos[0])
            follower_2 = float(data.joint(f"{side}_gripper_joint2").qpos[0])
            aperture_m = follower_1 - follower_2
            if aperture_m < minimum_aperture_m:
                pad_ids = {
                    model.geom(f"{side}_gripper_pad{index}").id
                    for index in (1, 2)
                }
                pad_contacts = []
                for contact_index in range(data.ncon):
                    contact = data.contact[contact_index]
                    pair = {int(contact.geom1), int(contact.geom2)}
                    if not pair & pad_ids:
                        continue
                    pad_contacts.append(
                        [
                            mujoco.mj_id2name(
                                model, mujoco.mjtObj.mjOBJ_GEOM, geom_id
                            )
                            for geom_id in pair
                        ]
                    )
                actuator_id = model.actuator(
                    f"{side}_gripper_aperture_position"
                ).id
                minimum_aperture_m = aperture_m
                minimum_aperture_detail = {
                    "side": side,
                    "tick": tick,
                    "aperture_mm": aperture_m * 1000.0,
                    "center_offset_mm": 0.5 * (follower_1 + follower_2) * 1000.0,
                    "finger_qpos_mm": [follower_1 * 1000.0, follower_2 * 1000.0],
                    "actuator_force_n": float(data.actuator_force[actuator_id]),
                    "pad_contacts": pad_contacts,
                }
            maximum_symmetry_error_m = max(
                maximum_symmetry_error_m, 0.5 * abs(follower_1 + follower_2)
            )

    assert minimum_aperture_m >= 0.095, repr(minimum_aperture_detail)
    assert maximum_symmetry_error_m < 0.003


def test_v26_gripper_plant_reports_aperture_tendon_and_compliant_center() -> None:
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(
        str(ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml")
    )
    configure_quest_gripper_actuators(model)
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    mujoco.mj_forward(model, data)

    diagnostics = _gripper_plant_diagnostics(SimpleNamespace(model=model, data=data))

    assert set(diagnostics) == {"left", "right"}
    for side in ("left", "right"):
        np.testing.assert_allclose(
            model.actuator(f"{side}_gripper_aperture_position").forcerange,
            [-8.0, 8.0],
        )
        assert model.actuator(f"{side}_gripper_aperture_position").biasprm[2] == -45.0
        center = model.tendon(f"{side}_gripper_center")
        assert model.tendon_stiffness[center.id] == 0.0
        constraint = model.equality(f"{side}_gripper_center_constraint")
        np.testing.assert_allclose(model.eq_solref[constraint.id], [0.02, 1.0])
    for values in diagnostics.values():
        assert values["finger_aperture_mm"] == pytest.approx(50.0)
        assert values["aperture_tracking_error_mm"] == pytest.approx(0.0)
        assert values["finger_center_offset_mm"] == pytest.approx(0.0)
        assert values["aperture_target_mm"] == pytest.approx(50.0)
        assert values["aperture_actuator_force_n"] == pytest.approx(0.0)
        assert values["force_limited"] is False


def test_v26_gripper_uses_one_symmetric_aperture_force_limit_per_side() -> None:
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(
        str(ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml")
    )
    configure_quest_gripper_actuators(model)

    for side in ("left", "right"):
        np.testing.assert_allclose(
            model.actuator(f"{side}_gripper_aperture_position").forcerange,
            [-8.0, 8.0],
        )


def test_v8_arm_plant_diagnostics_keep_left_right_joint_identity() -> None:
    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(
        str(ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml")
    )
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    mujoco.mj_forward(model, data)
    measured = np.asarray(
        [-20.0, 90.0, -50.0, 0.0, 0.0, 0.0, 50.0,
         20.0, 90.0, -50.0, 0.0, 0.0, 0.0, 50.0]
    )
    target = measured.copy()
    target[:6] += np.arange(1.0, 7.0)
    target[7:13] -= np.arange(1.0, 7.0)
    saturation = np.zeros(14, dtype=np.bool_)
    saturation[2] = True
    saturation[11] = True
    result = SimpleNamespace(
        saturation_mask=saturation,
        ik_failed={"left": False, "right": True},
    )

    diagnostics = _arm_plant_diagnostics(
        SimpleNamespace(model=model, data=data), measured, target, result
    )

    assert diagnostics["left"]["joint_error_deg"] == pytest.approx([1, 2, 3, 4, 5, 6])
    assert diagnostics["right"]["joint_error_deg"] == pytest.approx([-1, -2, -3, -4, -5, -6])
    assert diagnostics["left"]["joint_saturated"] == [False, False, True, False, False, False]
    assert diagnostics["right"]["joint_saturated"] == [False, False, False, False, True, False]
    assert diagnostics["left"]["ik_failed"] is False
    assert diagnostics["right"]["ik_failed"] is True
    assert len(diagnostics["left"]["actuator_force_nm"]) == 6
    assert len(diagnostics["right"]["actuator_force_nm"]) == 6


def _superseded_free_space_teleport_grasp_probe() -> None:
    """Retained temporarily as a non-collected diagnostic for pose comparison."""

    mujoco = pytest.importorskip("mujoco")
    model = mujoco.MjModel.from_xml_path(
        str(ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml")
    )
    configure_quest_gripper_actuators(model)
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
    mujoco.mj_forward(model, data)
    for side in ("left", "right"):
        _set_gripper_target(model, data, side, 0.1)
    model.opt.gravity[:] = 0.0
    for _ in range(3 * PHYSICS_HZ):
        mujoco.mj_step(model, data)

    # The pad is 56 mm wide around a 40 mm cube, so exercise a 3 mm
    # cross-pad offset inside the declared 8 mm lateral margin.  The previous
    # version accidentally offset 6 mm along the finger-closing axis.
    for side, lateral_offset in (("left", 0.003), ("right", -0.003)):
        base = data.body(f"{side}_gripper_base")
        rotation = base.xmat.reshape(3, 3).copy()
        cube_quaternion = np.zeros(4)
        mujoco.mju_mat2Quat(cube_quaternion, rotation.reshape(-1))
        cube = data.joint(f"{side}_cube_free")
        cube.qpos[:3] = base.xpos + rotation @ np.asarray(
            [lateral_offset, 0.0, 0.108]
        )
        cube.qpos[3:] = cube_quaternion
        cube.qvel[:] = 0.0
    mujoco.mj_forward(model, data)
    target_m = 0.1
    for _ in range(10):
        target_m = max(0.0, target_m - 0.01)
        for side in ("left", "right"):
            _set_gripper_target(model, data, side, target_m)
        for _ in range(ACTION_REPEAT):
            mujoco.mj_step(model, data)
    for _ in range(round((5.0 / 3.0) * PHYSICS_HZ)):
        mujoco.mj_step(model, data)

    for side in ("left", "right"):
        cube_geom = model.geom(f"{side}_cube_geom").id
        pad_ids = {model.geom(f"{side}_gripper_pad{index}").id for index in (1, 2)}
        contacted_pads = set()
        for index in range(data.ncon):
            contact = data.contact[index]
            pair = {int(contact.geom1), int(contact.geom2)}
            if cube_geom in pair:
                contacted_pads.update(pair & pad_ids)
        assert contacted_pads == pad_ids, (side, contacted_pads)

    model.opt.gravity[:] = (0.0, 0.0, -9.81)
    for _ in range(PHYSICS_HZ):
        mujoco.mj_step(model, data)
    initial_relative = {}
    for side in ("left", "right"):
        base = data.body(f"{side}_gripper_base")
        # Compare in the moving gripper frame so the commanded wrist roll is
        # not misclassified as cube translation/slip.
        initial_relative[side] = base.xmat.reshape(3, 3).T @ (
            data.body(f"{side}_cube").xpos - base.xpos
        )
    joint6_home = {
        side: float(data.joint(f"{side}_joint6").qpos[0]) for side in ("left", "right")
    }
    maximum_shift = {side: 0.0 for side in ("left", "right")}
    maximum_shift_detail: dict[str, dict[str, object]] = {}
    maximum_symmetry_error = {side: 0.0 for side in ("left", "right")}

    for tick in range(300):
        offset = np.deg2rad(5.0) * np.sin(2.0 * np.pi * tick / 120.0)
        for side in ("left", "right"):
            data.actuator(f"{side}_joint6_position").ctrl = joint6_home[side] + offset
        for _ in range(ACTION_REPEAT):
            mujoco.mj_step(model, data)
        for side in ("left", "right"):
            cube_geom = model.geom(f"{side}_cube_geom").id
            has_cube_contact = any(
                cube_geom in (data.contact[index].geom1, data.contact[index].geom2)
                for index in range(data.ncon)
            )
            follower_1 = float(data.joint(f"{side}_gripper_joint1").qpos[0])
            follower_2 = float(data.joint(f"{side}_gripper_joint2").qpos[0])
            assert has_cube_contact, (
                f"{side} cube contact lost at tick {tick}; "
                f"aperture_mm={(follower_1 - follower_2) * 1000.0:.3f}, "
                f"symmetry_error_mm={0.5 * abs(follower_1 + follower_2) * 1000.0:.3f}"
            )
            base = data.body(f"{side}_gripper_base")
            relative = base.xmat.reshape(3, 3).T @ (
                data.body(f"{side}_cube").xpos - base.xpos
            )
            relative_delta = relative - initial_relative[side]
            shift = float(np.linalg.norm(relative_delta))
            if shift > maximum_shift[side]:
                cube_contacts = []
                for index in range(data.ncon):
                    contact = data.contact[index]
                    if cube_geom not in (contact.geom1, contact.geom2):
                        continue
                    other_geom = contact.geom2 if contact.geom1 == cube_geom else contact.geom1
                    cube_contacts.append(
                        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, other_geom)
                    )
                maximum_shift[side] = shift
                maximum_shift_detail[side] = {
                    "tick": tick,
                    "shift_mm": shift * 1000.0,
                    "local_delta_mm": (relative_delta * 1000.0).tolist(),
                    "initial_local_mm": (initial_relative[side] * 1000.0).tolist(),
                    "current_local_mm": (relative * 1000.0).tolist(),
                    "cube_contacts": cube_contacts,
                }
            maximum_symmetry_error[side] = max(
                maximum_symmetry_error[side], 0.5 * abs(follower_1 + follower_2)
            )

    assert max(maximum_shift.values()) < 0.02, maximum_shift_detail
    # Independent force-limited fingers may deflect asymmetrically around a
    # contacted cube; continuous contact and bounded cube shift are the grasp
    # criteria. Keep a loose guard only against a runaway finger.
    assert max(maximum_symmetry_error.values()) < 0.01


def _assert_v25_table_grasp_lift_and_optional_wrist_motion(
    lateral_offsets_m: dict[str, float], *, exercise_wrist: bool
) -> None:
    """Acquire supported cubes through IK before testing lift and retention."""

    mujoco = pytest.importorskip("mujoco")
    temporary, solvers = _build_solvers()
    try:
        model = mujoco.MjModel.from_xml_path(
            str(ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml")
        )
        configure_quest_gripper_actuators(model)
        data = mujoco.MjData(model)
        mujoco.mj_resetDataKeyframe(model, data, model.key("home").id)
        for side in ("left", "right"):
            _set_gripper_target(model, data, side, 0.1)
        for _ in range(3 * PHYSICS_HZ):
            mujoco.mj_step(model, data)

        initial_cube_z = {
            side: float(data.body(f"{side}_cube").xpos[2])
            for side in ("left", "right")
        }
        approach: dict[str, np.ndarray] = {}
        lift: dict[str, np.ndarray] = {}
        home: dict[str, np.ndarray] = {}
        for side in ("left", "right"):
            home[side] = np.rad2deg(
                np.asarray(
                    [data.joint(f"{side}_joint{index}").qpos[0] for index in range(1, 7)]
                )
            )
            target = np.asarray(solvers[side].forward_kinematics(home[side])).copy()
            cube_in_base = (
                data.body(f"{side}_cube").xpos
                - data.body(f"{side}_base_link").xpos
            )
            # Preserve the reachable home approach as closely as possible, but
            # align local Y (the finger-closing axis) with a cube face.  Removing
            # only the approach component along Y avoids the unreachable fully
            # vertical wrist pose while keeping both planar pads parallel to
            # opposite cube faces.
            home_rotation = target[:3, :3].copy()
            closing_axis = np.asarray([0.0, 1.0, 0.0])
            if np.dot(home_rotation[:, 1], closing_axis) < 0.0:
                closing_axis = -closing_axis
            approach_axis = home_rotation[:, 2] - np.dot(
                home_rotation[:, 2], closing_axis
            ) * closing_axis
            approach_axis /= np.linalg.norm(approach_axis)
            lateral_axis = np.cross(closing_axis, approach_axis)
            lateral_axis /= np.linalg.norm(lateral_axis)
            target[:3, :3] = np.column_stack(
                (lateral_axis, closing_axis, approach_axis)
            )
            target[:3, 3] = cube_in_base - target[:3, :3] @ np.asarray(
                [lateral_offsets_m[side], 0.0, 0.108]
            )
            solved = home[side].copy()
            for _ in range(24):
                solved = np.asarray(
                    solvers[side].inverse_kinematics(
                        solved,
                        target,
                        position_weight=1.0,
                        orientation_weight=0.01,
                    )
                )
            assert np.all(solved >= JOINT_LIMITS_DEG[:, 0])
            assert np.all(solved <= JOINT_LIMITS_DEG[:, 1])
            reached = np.asarray(solvers[side].forward_kinematics(solved))
            assert np.linalg.norm(reached[:3, 3] - target[:3, 3]) < 0.002
            orientation_error = reached[:3, :3].T @ target[:3, :3]
            orientation_angle = np.arccos(
                np.clip((np.trace(orientation_error) - 1.0) * 0.5, -1.0, 1.0)
            )
            assert orientation_angle < np.deg2rad(3.0), (side, orientation_angle)
            approach[side] = solved

            lift_target = target.copy()
            lift_target[2, 3] += 0.08
            lifted = solved.copy()
            for _ in range(24):
                lifted = np.asarray(
                    solvers[side].inverse_kinematics(
                        lifted,
                        lift_target,
                        position_weight=1.0,
                        orientation_weight=0.01,
                    )
                )
            lift[side] = lifted

        def move(start: dict[str, np.ndarray], end: dict[str, np.ndarray], ticks: int) -> None:
            for tick in range(1, ticks + 1):
                alpha = 0.5 - 0.5 * np.cos(np.pi * tick / ticks)
                for side in ("left", "right"):
                    target_deg = start[side] + alpha * (end[side] - start[side])
                    for index, value in enumerate(target_deg, start=1):
                        data.actuator(f"{side}_joint{index}_position").ctrl = np.deg2rad(value)
                mujoco.mj_step(model, data)

        move(home, approach, 3 * PHYSICS_HZ)
        target_m = 0.1
        for _ in range(10):
            target_m = max(0.0, target_m - 0.01)
            for side in ("left", "right"):
                _set_gripper_target(model, data, side, target_m)
            for _ in range(ACTION_REPEAT):
                mujoco.mj_step(model, data)
        for _ in range(round((5.0 / 3.0) * PHYSICS_HZ)):
            mujoco.mj_step(model, data)
        for side in ("left", "right"):
            cube_geom = model.geom(f"{side}_cube_geom").id
            pad_ids = {
                model.geom(f"{side}_gripper_pad{index}").id for index in (1, 2)
            }
            contacted_pads = set()
            for index in range(data.ncon):
                contact = data.contact[index]
                pair = {int(contact.geom1), int(contact.geom2)}
                if cube_geom in pair:
                    contacted_pads.update(pair & pad_ids)
            follower_1 = float(data.joint(f"{side}_gripper_joint1").qpos[0])
            follower_2 = float(data.joint(f"{side}_gripper_joint2").qpos[0])
            pad_contacts: dict[str, list[str | None]] = {}
            for pad_id in pad_ids:
                pad_name = mujoco.mj_id2name(
                    model, mujoco.mjtObj.mjOBJ_GEOM, pad_id
                )
                others = []
                for contact_index in range(data.ncon):
                    contact = data.contact[contact_index]
                    pair = {int(contact.geom1), int(contact.geom2)}
                    if pad_id not in pair:
                        continue
                    other_id = next(geom_id for geom_id in pair if geom_id != pad_id)
                    others.append(
                        mujoco.mj_id2name(
                            model, mujoco.mjtObj.mjOBJ_GEOM, other_id
                        )
                    )
                pad_contacts[str(pad_name)] = others
            actuator_id = model.actuator(f"{side}_gripper_aperture_position").id
            finger_dofs = [
                model.joint(f"{side}_gripper_joint{index}").id
                for index in (1, 2)
            ]
            finger_dofs = [int(model.jnt_dofadr[joint_id]) for joint_id in finger_dofs]
            dynamics = {
                "qvel_m_s": [float(data.qvel[dof]) for dof in finger_dofs],
                "qfrc_actuator_n": [
                    float(data.qfrc_actuator[dof]) for dof in finger_dofs
                ],
                "qfrc_constraint_n": [
                    float(data.qfrc_constraint[dof]) for dof in finger_dofs
                ],
                "qfrc_passive_n": [
                    float(data.qfrc_passive[dof]) for dof in finger_dofs
                ],
                "qfrc_bias_n": [float(data.qfrc_bias[dof]) for dof in finger_dofs],
            }
            failure_detail = (
                f"{side}: contacted_pads={sorted(contacted_pads)}; "
                + repr(
                    {
                        "aperture_mm": (follower_1 - follower_2) * 1000.0,
                        "center_offset_mm": 0.5
                        * (follower_1 + follower_2)
                        * 1000.0,
                        "finger_qpos_mm": [
                            follower_1 * 1000.0,
                            follower_2 * 1000.0,
                        ],
                        "actuator_force_n": float(data.actuator_force[actuator_id]),
                        "pad_contacts": pad_contacts,
                        "dynamics": dynamics,
                        "cube_position_m": data.body(
                            f"{side}_cube"
                        ).xpos.tolist(),
                        "gripper_position_m": data.body(
                            f"{side}_gripper_base"
                        ).xpos.tolist(),
                    }
                )
            )
            assert contacted_pads == pad_ids, failure_detail

        move(approach, lift, 3 * PHYSICS_HZ)
        for side in ("left", "right"):
            assert data.body(f"{side}_cube").xpos[2] > initial_cube_z[side] + 0.04

        if exercise_wrist:
            initial_relative = {}
            joint6_home = {}
            maximum_shift = {side: 0.0 for side in ("left", "right")}
            contact_history: dict[str, list[dict[str, object]]] = {
                side: [] for side in ("left", "right")
            }
            for side in ("left", "right"):
                base = data.body(f"{side}_gripper_base")
                initial_relative[side] = base.xmat.reshape(3, 3).T @ (
                    data.body(f"{side}_cube").xpos - base.xpos
                )
                # Continue from the accepted actuator target, exactly like the
                # persistent-target Quest processor.  Re-basing this phase on
                # lagging measured qpos creates an artificial wrist-target
                # discontinuity immediately after the loaded lift.
                joint6_actuator_id = model.actuator(
                    f"{side}_joint6_position"
                ).id
                joint6_home[side] = float(data.ctrl[joint6_actuator_id])

            for tick in range(300):
                offset = np.deg2rad(5.0) * np.sin(2.0 * np.pi * tick / 120.0)
                for side in ("left", "right"):
                    data.actuator(f"{side}_joint6_position").ctrl = (
                        joint6_home[side] + offset
                    )
                for _ in range(ACTION_REPEAT):
                    mujoco.mj_step(model, data)
                for side in ("left", "right"):
                    cube_geom = model.geom(f"{side}_cube_geom").id
                    pad_ids = {
                        model.geom(f"{side}_gripper_pad{index}").id
                        for index in (1, 2)
                    }
                    pad_contact_forces = []
                    for contact_index in range(data.ncon):
                        contact = data.contact[contact_index]
                        pair = {int(contact.geom1), int(contact.geom2)}
                        if cube_geom not in pair or not pair & pad_ids:
                            continue
                        force = np.zeros(6)
                        mujoco.mj_contactForce(model, data, contact_index, force)
                        pad_contact_forces.append(
                            {
                                "pad": mujoco.mj_id2name(
                                    model,
                                    mujoco.mjtObj.mjOBJ_GEOM,
                                    next(iter(pair & pad_ids)),
                                ),
                                "distance_mm": float(contact.dist) * 1000.0,
                                "normal_force_n": float(force[0]),
                                "tangent_force_n": [
                                    float(force[1]),
                                    float(force[2]),
                                ],
                            }
                        )
                    has_pad_contact = bool(pad_contact_forces)
                    base = data.body(f"{side}_gripper_base")
                    relative = base.xmat.reshape(3, 3).T @ (
                        data.body(f"{side}_cube").xpos - base.xpos
                    )
                    follower_1 = float(
                        data.joint(f"{side}_gripper_joint1").qpos[0]
                    )
                    follower_2 = float(
                        data.joint(f"{side}_gripper_joint2").qpos[0]
                    )
                    actuator_id = model.actuator(
                        f"{side}_gripper_aperture_position"
                    ).id
                    contact_history[side].append(
                        {
                            "tick": tick,
                            "aperture_mm": (follower_1 - follower_2) * 1000.0,
                            "local_cube_mm": (relative * 1000.0).tolist(),
                            "actuator_force_n": float(
                                data.actuator_force[actuator_id]
                            ),
                            "contacts": pad_contact_forces,
                        }
                    )
                    contact_history[side] = contact_history[side][-8:]
                    if not has_pad_contact:
                        cube_contacts = []
                        for contact_index in range(data.ncon):
                            contact = data.contact[contact_index]
                            if cube_geom not in (contact.geom1, contact.geom2):
                                continue
                            other_geom = (
                                contact.geom2
                                if contact.geom1 == cube_geom
                                else contact.geom1
                            )
                            cube_contacts.append(
                                mujoco.mj_id2name(
                                    model, mujoco.mjtObj.mjOBJ_GEOM, other_geom
                                )
                            )
                        pytest.fail(
                            f"{side} pad contact lost at tick {tick}; "
                            f"aperture_mm={(follower_1 - follower_2) * 1000.0:.3f}; "
                            f"center_offset_mm={0.5 * (follower_1 + follower_2) * 1000.0:.3f}; "
                            f"actuator_force_n={float(data.actuator_force[actuator_id]):.3f}; "
                            f"local_shift_mm={((relative - initial_relative[side]) * 1000.0).tolist()}; "
                            f"cube_contacts={cube_contacts}; "
                            f"contact_history={contact_history[side]!r}"
                        )
                    maximum_shift[side] = max(
                        maximum_shift[side],
                        float(np.linalg.norm(relative - initial_relative[side])),
                    )
            assert max(maximum_shift.values()) < 0.02, maximum_shift
    finally:
        temporary.cleanup()


def test_v26_gripper_acquires_canonical_cubes_from_table_and_lifts_them() -> None:
    _assert_v25_table_grasp_lift_and_optional_wrist_motion(
        {"left": 0.0, "right": 0.0}, exercise_wrist=False
    )


def test_v26_gripper_retains_centered_cubes_during_wrist_motion() -> None:
    _assert_v25_table_grasp_lift_and_optional_wrist_motion(
        {"left": 0.0, "right": 0.0}, exercise_wrist=True
    )


def test_v26_gripper_acquires_off_center_cubes_and_retains_during_wrist_motion() -> None:
    _assert_v25_table_grasp_lift_and_optional_wrist_motion(
        {"left": 0.003, "right": -0.003}, exercise_wrist=True
    )


def test_inactive_menu_input_cannot_move_joints_or_grippers() -> None:
    processor = PiperXMujocoQuestIkProcessor(
        {"left": _FakeSolver(20.0), "right": _FakeSolver(-20.0)}
    )
    state = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])
    command = BimanualTeleopCommand(
        _arm(np.ones(6), gripper_m=0.0),
        _arm(-np.ones(6), gripper_m=0.1),
        False,
    )

    result = processor.action(state, command)

    np.testing.assert_array_equal(result.d0_action, state)
    assert not result.saturated


def test_rebase_frame_holds_grippers_even_if_play_was_clicked_with_trigger() -> None:
    processor = PiperXMujocoQuestIkProcessor({"left": _FakeSolver(), "right": _FakeSolver()})
    state = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])
    command = BimanualTeleopCommand(
        _arm(np.zeros(6), gripper_m=0.0, rebased=True),
        _arm(np.zeros(6), gripper_m=0.1, rebased=True),
        True,
    )

    result = processor.action(state, command)

    np.testing.assert_array_equal(result.d0_action, state)
    assert not result.saturated


class _OutputSlot:
    def __init__(self) -> None:
        self.value: bool | None = None

    def __getitem__(self, _index: int) -> bool | None:
        return self.value

    def __setitem__(self, _index: int, value: bool) -> None:
        self.value = bool(value)


def _control_step(
    processor: MujocoQuestTeleopMessageProcessor,
    payload: bytes | None = None,
) -> dict[str, bool | None]:
    messages = [] if payload is None else [SimpleNamespace(payload=payload)]
    inputs = {processor.INPUT_MESSAGES: [SimpleNamespace(data=messages)]}
    outputs = {name: _OutputSlot() for name in ("run_toggle", "kill", "reset")}
    processor._compute_fn(inputs, outputs, None)
    return {name: slot.value for name, slot in outputs.items()}


def test_webxr_play_stop_and_reset_messages_match_isaac_state_edges() -> None:
    processor = MujocoQuestTeleopMessageProcessor("mujoco_quest_control_test")
    start = b'{"type":"teleop_command","message":{"command":"start teleop"}}'
    stop = b'{"type":"teleop_command","message":{"command":"stop teleop"}}'
    reset = b'{"type":"teleop_command","message":{"command":"reset teleop"}}'

    assert _control_step(processor, start)["run_toggle"] is True
    assert _control_step(processor)["run_toggle"] is False
    assert _control_step(processor)["run_toggle"] is True
    assert processor._shadow_state == "running"

    assert _control_step(processor, stop)["run_toggle"] is False
    assert _control_step(processor)["run_toggle"] is True
    assert processor._shadow_state == "paused"

    result = _control_step(processor, reset)
    assert result == {"run_toggle": False, "kill": False, "reset": True}


def test_real_placo_ik_is_continuous_for_small_bimanual_deltas() -> None:
    temporary, solvers = _build_solvers()
    try:
        processor = PiperXMujocoQuestIkProcessor(solvers)
        state = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])
        command = BimanualTeleopCommand(
            _arm(np.asarray([0.002, 0, 0, 0, 0, 0])),
            _arm(np.asarray([-0.002, 0, 0, 0, 0, 0])),
            True,
        )

        result = processor.action(state, command)

        assert not any(result.ik_failed.values())
        assert not result.saturated
        assert np.max(np.abs(result.d0_action[:6] - state[:6])) < 1.0
        assert np.max(np.abs(result.d0_action[7:13] - state[7:13])) < 1.0
    finally:
        temporary.cleanup()


def test_real_placo_ik_can_reach_both_cubes_within_joint_limits() -> None:
    """The canonical cubes are reachable; runtime filtering must not hide that workspace."""

    temporary, solvers = _build_solvers()
    try:
        homes = {
            "left": np.asarray([-20.0, 90.0, -50.0, 0.0, 0.0, 0.0]),
            "right": np.asarray([20.0, 90.0, -50.0, 0.0, 0.0, 0.0]),
        }
        cube_in_base = {
            "left": np.asarray([0.287, -0.13, 0.022]),
            "right": np.asarray([0.287, 0.13, 0.022]),
        }
        for side in ("left", "right"):
            target = np.asarray(solvers[side].forward_kinematics(homes[side])).copy()
            target[:3, 3] = cube_in_base[side]
            solved = homes[side].copy()
            for _ in range(20):
                solved = np.asarray(
                    solvers[side].inverse_kinematics(
                        solved,
                        target,
                        position_weight=1.0,
                        orientation_weight=1.0,
                    )
                )
            reached = np.asarray(solvers[side].forward_kinematics(solved))
            assert np.linalg.norm(reached[:3, 3] - cube_in_base[side]) < 1.0e-4
            assert np.all(solved >= JOINT_LIMITS_DEG[:, 0])
            assert np.all(solved <= JOINT_LIMITS_DEG[:, 1])
    finally:
        temporary.cleanup()


def test_quest_ik_and_native_actuator_joint_order_matches_gate_c() -> None:
    """Audit the complete named joint seam suspected by physical run 3."""

    mujoco = pytest.importorskip("mujoco")
    from lerobot_env_piperx_mujoco.processors import PiperXMujocoActionProcessor

    temporary, solvers = _build_solvers()
    try:
        expected_solver_names = [f"joint{index}" for index in range(1, 7)]
        assert solvers["left"].joint_names == expected_solver_names
        assert solvers["right"].joint_names == expected_solver_names

        model = mujoco.MjModel.from_xml_path(
            str(ROOT / "assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml")
        )
        expected_actuators = []
        for side in ("left", "right"):
            expected_actuators.extend(
                [
                    *[f"{side}_joint{index}_position" for index in range(1, 7)],
                    f"{side}_gripper_aperture_position",
                ]
            )
        assert [model.actuator(index).name for index in range(model.nu)] == expected_actuators

        d0 = np.asarray(
            [-20, 30, -40, 10, -15, 25, 35, 20, 40, -60, -10, 15, -25, 65.0]
        )
        native = PiperXMujocoActionProcessor().action(d0)
        np.testing.assert_allclose(native[:6], np.deg2rad(d0[:6]))
        np.testing.assert_allclose(native[7:13], np.deg2rad(d0[7:13]))
        np.testing.assert_allclose(native[[6, 13]], d0[[6, 13]] / 1000.0)
    finally:
        temporary.cleanup()


@pytest.mark.parametrize("rotation_axis", range(3))
def test_v39_subthreshold_rotation_is_ignored(rotation_axis: int) -> None:
    temporary, solvers = _build_solvers()
    try:
        processor = PiperXMujocoQuestIkProcessor(solvers)
        state = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])
        rotation = np.zeros(6)
        rotation[3 + rotation_axis] = 0.0055

        result = processor.action(
            state, BimanualTeleopCommand(_arm(rotation), _arm(rotation), True)
        )

        assert not any(result.ik_failed.values())
        np.testing.assert_allclose(result.d0_action[:6], state[:6], atol=1.0e-8)
        np.testing.assert_allclose(result.d0_action[7:13], state[7:13], atol=1.0e-8)
        assert result.cartesian_delta_clipped == {"left": False, "right": False}
    finally:
        temporary.cleanup()


@pytest.mark.parametrize("rotation_axis", range(3))
def test_v39_deliberate_rotation_moves_distal_joints_without_tiny_v38_clip(
    rotation_axis: int,
) -> None:
    temporary, solvers = _build_solvers()
    try:
        processor = PiperXMujocoQuestIkProcessor(solvers)
        state = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])
        rotation = np.zeros(6)
        rotation[3 + rotation_axis] = 0.02

        result = processor.action(
            state, BimanualTeleopCommand(_arm(rotation), _arm(rotation), True)
        )

        assert not any(result.ik_failed.values())
        for start in (0, 7):
            joint_delta = result.d0_action[start : start + 6] - state[start : start + 6]
            assert np.linalg.norm(joint_delta[3:]) > 1.0e-6
            assert np.max(np.abs(joint_delta)) <= 8.0
        assert result.cartesian_delta_clipped == {"left": False, "right": False}
    finally:
        temporary.cleanup()


def test_v39_translation_holds_orientation_without_deliberate_rotation() -> None:
    """Equal controller-down intent must stay down on both arms."""

    temporary, solvers = _build_solvers()
    try:
        processor = PiperXMujocoQuestIkProcessor(solvers)
        state = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])
        # Controller -Y maps to scene -Z while wrist orientation is held.
        left = np.asarray([0.0, -0.01, 0.0, 0.0, 0.0, 0.0])
        right = left.copy()

        result = processor.action(
            state, BimanualTeleopCommand(_arm(left), _arm(right), True)
        )

        assert not any(result.ik_failed.values())
        assert result.cartesian_delta_clipped == {"left": False, "right": False}
        for side, start in (("left", 0), ("right", 7)):
            achieved = np.asarray(result.achieved_translation_m[side])
            assert achieved[2] < 0.0, (side, achieved)
            assert np.linalg.norm(achieved[:2]) < abs(achieved[2]), (side, achieved)
            assert result.translation_alignment[side] is not None
            assert result.translation_alignment[side] >= 0.5
            initial_pose = np.asarray(solvers[side].forward_kinematics(state[start : start + 6]))
            reached_pose = np.asarray(
                solvers[side].forward_kinematics(result.d0_action[start : start + 6])
            )
            np.testing.assert_allclose(
                reached_pose[:3, :3], initial_pose[:3, :3], atol=2.0e-3
            )
            assert np.linalg.norm(
                result.d0_action[start + 3 : start + 6] - state[start + 3 : start + 6]
            ) > 1.0e-6
    finally:
        temporary.cleanup()


def test_ik_joint_step_and_gate_c_limits_are_reported() -> None:
    processor = PiperXMujocoQuestIkProcessor(
        {"left": _FakeSolver(20.0), "right": _FakeSolver(-20.0)},
        QuestIkConfig(
            iterations_per_tick=1,
            max_joint_step_deg=8.0,
            minimum_translation_alignment=-1.0,
        ),
    )
    state = np.asarray([145, 175, -5, 85, 85, 115, 50, -145, 5, -165, -85, -85, -115, 50.0])
    command = BimanualTeleopCommand(
        _arm(np.asarray([0.001, 0, 0, 0, 0, 0])),
        _arm(np.asarray([0.001, 0, 0, 0, 0, 0])),
        True,
    )
    result = processor.action(state, command)
    np.testing.assert_array_less(result.d0_action[:6] - state[:6], 8.000001)
    np.testing.assert_array_less(state[7:13] - result.d0_action[7:13], 8.000001)
    assert result.saturation_mask[:6].all()
    assert result.saturation_mask[7:13].all()
    assert result.saturated


def test_cartesian_jump_is_bounded_and_reported() -> None:
    processor = PiperXMujocoQuestIkProcessor(
        {"left": _FakeSolver(), "right": _FakeSolver()},
        QuestIkConfig(max_translation_delta_m=0.01, max_rotation_delta_rad=0.1),
    )
    state = np.zeros(14)
    command = BimanualTeleopCommand(
        _arm(np.ones(6)),
        _arm(np.zeros(6)),
        True,
    )
    result = processor.action(state, command)
    assert result.cartesian_delta_clipped == {"left": True, "right": False}
    assert result.saturated


def test_v39_rotation_above_restored_bound_is_clipped_symmetrically() -> None:
    processor = PiperXMujocoQuestIkProcessor(
        {"left": _FakeSolver(), "right": _FakeSolver()}
    )
    state = np.zeros(14)
    spike = np.asarray([0.001, 0.0, 0.0, 0.0, 0.0, 0.08])

    result = processor.action(
        state, BimanualTeleopCommand(_arm(spike), _arm(spike), True)
    )

    assert result.cartesian_delta_clipped == {"left": True, "right": True}
    assert result.saturated


def test_required_tracking_identifies_the_unavailable_controller() -> None:
    sample = SimpleNamespace(
        left=SimpleNamespace(available=True, grip_pose_valid=True),
        right=SimpleNamespace(available=False, grip_pose_valid=False),
    )

    assert _missing_controller_tracking(sample) == ("right",)
    sample.right.available = True
    sample.right.grip_pose_valid = True
    assert _missing_controller_tracking(sample) == ()


def test_optional_upstream_graph_has_one_shared_controller_source() -> None:
    pytest.importorskip("isaacteleop")
    from tools.mujoco_quest_upstream import build_mujoco_quest_pipeline

    pipeline = build_mujoco_quest_pipeline()
    leaves = pipeline.graph.get_leaf_nodes()
    assert leaves == [pipeline.controllers]
    assert set(pipeline.graph.output_types()) == {
        "left_delta",
        "left_state",
        "right_delta",
        "right_state",
    }
    control_leaves = pipeline.control_graph.get_leaf_nodes()
    assert control_leaves == [pipeline.control_source]
    assert set(pipeline.control_graph.output_types()) == {"teleop_state", "reset_event"}


def test_optional_upstream_tracking_loss_clears_relative_history() -> None:
    pytest.importorskip("isaacteleop")
    from isaacteleop.retargeters import Se3RetargeterConfig
    from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
    from isaacteleop.retargeting_engine.interface.tensor_group import OptionalTensorGroup
    from isaacteleop.retargeting_engine.tensor_types import ControllerInputIndex
    from tools.mujoco_quest_upstream import TrackingSafeSe3RelRetargeter

    side = ControllersSource.LEFT
    retargeter = TrackingSafeSe3RelRetargeter(
        Se3RetargeterConfig(
            input_device=side,
            delta_pos_scale_factor=1.0,
            delta_rot_scale_factor=1.0,
        ),
        "mujoco_quest_tracking_safe_test",
    )

    def controller(position: list[float]) -> OptionalTensorGroup:
        group = OptionalTensorGroup(retargeter.input_spec()[side])
        group[ControllerInputIndex.GRIP_IS_VALID] = True
        group[ControllerInputIndex.GRIP_POSITION] = np.asarray(position, dtype=np.float32)
        group[ControllerInputIndex.GRIP_ORIENTATION] = np.asarray(
            [0.0, 0.0, 0.0, 1.0], dtype=np.float32
        )
        return group

    def delta(group: OptionalTensorGroup) -> np.ndarray:
        return np.asarray(retargeter({side: group})["ee_delta"][0])

    np.testing.assert_array_equal(delta(controller([0.0, 0.0, 0.0])), np.zeros(6))
    np.testing.assert_allclose(delta(controller([0.1, 0.0, 0.0])), [0.05, 0, 0, 0, 0, 0])
    absent = OptionalTensorGroup(retargeter.input_spec()[side])
    np.testing.assert_array_equal(delta(absent), np.zeros(6))
    np.testing.assert_array_equal(delta(controller([50.0, 0.0, 0.0])), np.zeros(6))


def test_paused_controller_motion_cannot_leave_a_smoothed_delta_after_play() -> None:
    pytest.importorskip("isaacteleop")
    from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
    from isaacteleop.retargeting_engine.interface.tensor_group import OptionalTensorGroup
    from isaacteleop.retargeting_engine.tensor_types import ControllerInputIndex
    from tools.mujoco_quest_upstream import build_mujoco_quest_pose_retargeter

    side = ControllersSource.LEFT
    retargeter = build_mujoco_quest_pose_retargeter(side, "paused_history_test")

    def controller(position: list[float]) -> OptionalTensorGroup:
        group = OptionalTensorGroup(retargeter.input_spec()[side])
        group[ControllerInputIndex.GRIP_IS_VALID] = True
        group[ControllerInputIndex.GRIP_POSITION] = np.asarray(position, dtype=np.float32)
        group[ControllerInputIndex.GRIP_ORIENTATION] = np.asarray(
            [0.0, 0.0, 0.0, 1.0], dtype=np.float32
        )
        return group

    def delta(position: list[float]) -> np.ndarray:
        return np.asarray(retargeter({side: controller(position)})["ee_delta"][0])

    delta([0.0, 0.0, 0.0])
    delta([0.1, 0.0, 0.0])
    retargeter.reset_relative_reference()

    np.testing.assert_array_equal(delta([0.1, 0.0, 0.0]), np.zeros(6))
    np.testing.assert_array_equal(delta([0.1, 0.0, 0.0]), np.zeros(6))


@pytest.mark.parametrize("mode", ["normal", "precise"])
def test_synthetic_end_to_end_gain_equals_configured_scale(mode: str) -> None:
    """Pin controller motion to TCP motion across the whole control chain.

    Drives the pinned upstream ``Se3RelRetargeter`` with a synthetic controller
    trajectory, then the production S2 processor, the production IK edge and
    LeRobot forward kinematics. The operator reported residual sensitivity at
    unit gain, so this measures the actual accumulated DC gain instead of
    assuming it: v3 amplified it two times and that must not return.
    """
    pytest.importorskip("isaacteleop")
    from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
    from isaacteleop.retargeting_engine.interface.tensor_group import OptionalTensorGroup
    from isaacteleop.retargeting_engine.tensor_types import ControllerInputIndex
    from tools.isaac_s2_processor import BimanualS2TeleopProcessor, ControllerDeltaSample
    from tools.mujoco_quest_upstream import build_mujoco_quest_pose_retargeter

    config = _load_config(ROOT / "configs/mujoco_quest_runtime.yaml")
    s2_config = replace(_processor_config(config), initial_sensitivity_mode=mode)
    expected_scale = float(
        s2_config.precise_translation_scale
        if mode == "precise"
        else s2_config.normal_translation_scale
    )

    side = ControllersSource.LEFT
    retargeter = build_mujoco_quest_pose_retargeter(side, f"mujoco_quest_gain_{mode}")
    processor = BimanualS2TeleopProcessor(s2_config)
    temporary, solvers = _build_solvers()
    try:
        ik = PiperXMujocoQuestIkProcessor(solvers)
        home = np.asarray([-20, 90, -50, 0, 0, 0, 50, 20, 90, -50, 0, 0, 0, 50.0])

        def controller(position: np.ndarray) -> OptionalTensorGroup:
            group = OptionalTensorGroup(retargeter.input_spec()[side])
            group[ControllerInputIndex.GRIP_IS_VALID] = True
            group[ControllerInputIndex.GRIP_POSITION] = np.asarray(position, dtype=np.float32)
            group[ControllerInputIndex.GRIP_ORIENTATION] = np.asarray(
                [0.0, 0.0, 0.0, 1.0], dtype=np.float32
            )
            return group

        def sample(delta: np.ndarray) -> ControllerDeltaSample:
            return ControllerDeltaSample(
                delta_position_m=delta[:3],
                delta_rotation_rotvec_rad=delta[3:],
                available=True,
                grip_pose_valid=True,
                squeeze_value=0.0,
                trigger_value=0.0,
                sensitivity_button_value=0.0,
            )

        idle = np.zeros(6, dtype=np.float64)
        # One stationary frame sets the upstream pose baseline and clears the
        # initial rebase, so no displacement is spent on either warm-up edge.
        processor.advance(sample(idle), sample(idle))

        travel_m, frames = 0.12, 40
        # Controller forward is -Z and maps to M1 +X.
        forward = np.asarray([0.0, 0.0, -1.0])
        measured = home.copy()
        position = np.zeros(3)
        for index in range(frames + 10):
            if index <= frames:
                position = forward * (travel_m * index / frames)
            # Frames past `frames` keep the controller still so the upstream
            # alpha-0.5 smoothing tail is emitted and counted too.
            delta = np.asarray(
                retargeter({side: controller(position)})["ee_delta"][0], dtype=np.float64
            )
            if index == 0:
                continue  # baseline frame only, no displacement to integrate
            result = ik.action(measured, processor.advance(sample(delta), sample(idle)))
            assert not any(result.ik_failed.values())
            assert not any(result.cartesian_delta_clipped.values())
            joints = result.saturation_mask.copy()
            joints[[6, 13]] = False
            assert not joints.any()
            measured = result.d0_action

        start = np.asarray(solvers["left"].forward_kinematics(home[:6]))[:3, 3]
        end = np.asarray(solvers["left"].forward_kinematics(measured[:6]))[:3, 3]
        achieved_m = float(np.linalg.norm(end - start))
        expected_m = expected_scale * travel_m
        print(
            f"\n{mode}: controller={travel_m:.4f} m, scale={expected_scale}, "
            f"expected={expected_m:.4f} m, achieved={achieved_m:.4f} m, "
            f"gain={achieved_m / travel_m:.4f}"
        )
        assert achieved_m == pytest.approx(expected_m, rel=0.05)
    finally:
        temporary.cleanup()


def test_v8_slow_controller_motion_survives_reduced_frame_deadband() -> None:
    """The v8 adapter keeps upstream filtering but admits deliberate slow reach."""
    pytest.importorskip("isaacteleop")
    from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
    from isaacteleop.retargeting_engine.interface.tensor_group import OptionalTensorGroup
    from isaacteleop.retargeting_engine.tensor_types import ControllerInputIndex
    from tools.mujoco_quest_upstream import build_mujoco_quest_pose_retargeter

    side = ControllersSource.LEFT

    def sweep(step_m: float) -> float:
        # A fresh retargeter per pass: moving the pose baseline backwards would
        # otherwise feed a large raw delta into the alpha-0.5 smoother.
        retargeter = build_mujoco_quest_pose_retargeter(side, f"mujoco_quest_{step_m}")

        def delta(position: np.ndarray) -> np.ndarray:
            group = OptionalTensorGroup(retargeter.input_spec()[side])
            group[ControllerInputIndex.GRIP_IS_VALID] = True
            group[ControllerInputIndex.GRIP_POSITION] = np.asarray(position, dtype=np.float32)
            group[ControllerInputIndex.GRIP_ORIENTATION] = np.asarray(
                [0.0, 0.0, 0.0, 1.0], dtype=np.float32
            )
            return np.asarray(retargeter({side: group})["ee_delta"][0], dtype=np.float64)

        delta(np.zeros(3))  # baseline
        total = np.zeros(6)
        for index in range(1, 41):
            total += delta(np.asarray([0.0, 0.0, -1.0 * step_m * index]))
        return float(np.linalg.norm(total[:3]))

    below_m = sweep(0.0002)
    slow_m = sweep(0.0006)

    assert below_m == 0.0
    assert slow_m == pytest.approx(0.024, rel=0.05)
