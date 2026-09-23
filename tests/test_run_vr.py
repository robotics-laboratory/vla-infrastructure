"""One-loop regression coverage: mode isolation, provenance and source health."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS

import numpy as np
import pytest
import torch
import yaml

from tools.isaac_vr_camera_guard import CameraGuard
from tools import isaac_vr_config

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launcher(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    return importlib.import_module("launch_isaac_vr")


def test_cli_modes_and_explicit_rollback(launcher):
    run = launcher.parse_args([])
    diag = launcher.parse_args(["diag"])
    assert (run.mode, diag.mode, run.stack) == ("run", "diagnostic", "isaac61")
    assert run.profile == "dual_cube_to_matching_plates"
    assert run.preview_isolation == "scene-partitions" and run.preview_cameras == 3
    assert launcher.parse_args(["--stack", "legacy"]).preview_isolation == "off"
    assert launcher.parse_args(["--hud-on-start"]).mode == "run"
    assert launcher.parse_args(["--smoke"]).mode == "run"
    for flag in (
        ["--capture-preview-evidence"],
        ["--performance-window-steps=10"],
        ["--performance-warmup-steps", "0"],
        ["--scene-preview", "/tmp/out.png"],
        ["--preview-cameras", "2"],
        ["--preview-isolation", "off"],
        ["--profile", "robosyn_asset_lab"],
    ):
        with pytest.raises(SystemExit):
            launcher.parse_args(flag)
        assert launcher.parse_args(["diag", *flag]).mode == "diagnostic"
    record = launcher.parse_args(["record"])
    assert record.mode == "record"
    assert not record.performance_enabled
    for flag in (["--performance-window-steps=300"], ["--performance-warmup-steps", "60"]):
        assert launcher.parse_args(["record", *flag]).performance_enabled
    replay = launcher.parse_args(["replay", "--recording", "/tmp/session.hdf5", "--episode", "0"])
    assert (replay.mode, replay.recording, replay.episode) == (
        "replay",
        Path("/tmp/session.hdf5"),
        0,
    )
    with pytest.raises(SystemExit):
        launcher.parse_args(["record", "--capture-preview-evidence"])
    with pytest.raises(SystemExit):
        launcher.parse_args(["record", "--injected-actions"])
    with pytest.raises(SystemExit):
        launcher.parse_args(["--smoke", "--injected-actions"])
    assert launcher.parse_args(["record", "--smoke", "--injected-actions"]).injected_actions
    with pytest.raises(SystemExit):
        launcher.parse_args(["record", "--smoke", "--recording-benchmark"])
    with pytest.raises(SystemExit):
        launcher.parse_args(["record", "--smoke", "--injected-actions", "--recording-benchmark"])
    benchmark = launcher.parse_args(
        [
            "record",
            "--smoke",
            "--injected-actions",
            "--recording-benchmark",
            "--benchmark-pair-id",
            "pair-1",
        ]
    )
    assert benchmark.recording_benchmark and benchmark.benchmark_measured_steps == 64
    with pytest.raises(SystemExit):
        launcher.parse_args(
            [
                "record",
                "--smoke",
                "--injected-actions",
                "--recording-benchmark",
                "--benchmark-pair-id",
                "pair-1",
                "--benchmark-warmup-steps",
                "1",
                "--benchmark-measured-steps",
                "2",
                "--benchmark-flush-every-frames",
                "4",
            ]
        )
    with pytest.raises(SystemExit):
        launcher.parse_args(["replay"])
    for option in (["--smoke"], ["--xr-smoke"], ["--hud-on-start"], ["--cloudxr-mode", "existing"]):
        with pytest.raises(SystemExit):
            launcher.parse_args(["replay", "--recording", "/tmp/session.hdf5", *option])


def test_default_does_not_read_experimental_assets(monkeypatch):
    monkeypatch.setattr(isaac_vr_config, "ASSET_LAB_CONFIG", Path("/missing/RoboSyn/overlay"))
    monkeypatch.setattr(isaac_vr_config, "git", lambda *a: pytest.fail("external git read"))
    config = isaac_vr_config.load_composition("dual_cube_to_matching_plates")
    assert "asset_lab" not in config and "environment" not in config
    assert config["cameras"]["wrist"]["roles"] == ["left_wrist", "right_wrist"]
    assert config["cameras"]["scene"]["canonical_d0_input"] is True
    with pytest.raises(FileNotFoundError):
        isaac_vr_config.load_composition("robosyn_asset_lab")


def test_experimental_assets_must_be_pinned_and_hashed(tmp_path, monkeypatch):
    asset = tmp_path / "test.obj"
    asset.write_bytes(b"asset")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "source_checkout": str(tmp_path),
                "source_commit": "pin",
                "assets": [
                    {"source_path": "test.obj", "sha256": hashlib.sha256(b"asset").hexdigest()}
                ],
            }
        )
    )
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(
        yaml.safe_dump(
            {"status": "EXPERIMENTAL_TEST_ONLY_NOT_A_GATE", "asset_manifest": str(manifest)}
        )
    )
    monkeypatch.setattr(isaac_vr_config, "ASSET_LAB_CONFIG", overlay)
    monkeypatch.setattr(
        isaac_vr_config, "git", lambda p, *args: "pin" if args[0] == "rev-parse" else ""
    )
    assert isaac_vr_config.load_composition("robosyn_asset_lab")["asset_lab"]
    asset.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="hash mismatch"):
        isaac_vr_config.load_composition("robosyn_asset_lab")
    monkeypatch.setattr(isaac_vr_config, "git", lambda *a: "dirty")
    with pytest.raises(RuntimeError, match="clean/pinned"):
        isaac_vr_config.load_composition("robosyn_asset_lab")


def camera():
    # Metadata-only object: attempting any pixel copy would fail this test.
    return NS(
        data=NS(output={"rgba": NS(shape=(1, 480, 640, 4), dtype=torch.uint8)}),
        frame=torch.tensor([1]),
    )


def test_camera_guard_freeze_regression_reset_and_broken_buffer():
    cameras = [camera() for _ in range(3)]
    env = NS(camera=NS(wrists=cameras[:2], scene_camera=cameras[2]))
    guard = CameraGuard(2)
    assert guard.sample(env)["strictly_advanced"]
    strict = CameraGuard(0)
    strict.sample(env)
    cameras[0].frame += 1
    cameras[1].frame += 1
    with pytest.raises(RuntimeError, match="Frozen required camera: demo_scene"):
        strict.sample(env)
    guard.reset()
    guard.sample(env)
    for _ in range(2):
        assert not guard.sample(env)["strictly_advanced"]
    with pytest.raises(RuntimeError, match="Frozen"):
        guard.sample(env)
    guard.reset()
    assert guard.sample(env)["valid"]
    cameras[2].frame -= 1
    with pytest.raises(RuntimeError, match="regressed"):
        guard.sample(env)
    guard.reset()
    cameras[0].data.output["rgba"].shape = (1, 2, 3, 4)
    with pytest.raises(RuntimeError, match="Broken required camera"):
        guard.sample(env)


def test_manifest_and_child_commands(launcher, tmp_path, monkeypatch):
    stack = launcher.STACKS["isaac61"]
    monkeypatch.setattr(launcher, "verify_stack", lambda _: stack)
    monkeypatch.setattr(
        launcher,
        "_git_output",
        lambda *a: "untracked.txt\0" if a[0] == "ls-files" else " M tracked\n?? untracked.txt",
    )
    manifests = []
    for prefix in ([], ["diag"]):
        assert launcher.main([*prefix, "--dry-run", "--smoke", "--state-root", str(tmp_path)]) == 0
        path = max(
            (tmp_path / "runs").glob("*/run_manifest.json"), key=lambda p: p.stat().st_mtime_ns
        )
        m = json.loads(path.read_text())
        manifests.append(m)
        assert m["repository"]["untracked_files"] == ["untracked.txt"]
        assert "?? untracked.txt" in m["repository"]["full_status"]
        assert m["top_level_invocation"][1:] == [
            *prefix,
            "--dry-run",
            "--smoke",
            "--state-root",
            str(tmp_path),
        ]
        for name in (
            "configs/isaac61_s2_runtime.yaml",
            "configs/isaac61_vr_runtime.yaml",
            "tools/isaac_s2_processor.py",
            "tools/isaac_vr_camera_guard.py",
        ):
            assert (
                m["repository"]["source_sha256"][name]
                == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            )
        assert (
            m["generated_runtime_config_sha256"]
            == hashlib.sha256((path.parent / "runtime.yaml").read_bytes()).hexdigest()
        )
    run, diag = manifests
    assert run["effective_control_config"] == diag["effective_control_config"]
    assert run["generated_runtime_config_sha256"] == diag["generated_runtime_config_sha256"]
    assert "--s2-performance-log" not in run["launch"]["command"]
    assert "--s2-performance-log" in diag["launch"]["command"]


def test_record_and_replay_child_commands(launcher, tmp_path, monkeypatch):
    stack = launcher.STACKS["isaac61"]
    monkeypatch.setattr(launcher, "verify_stack", lambda _: stack)
    monkeypatch.setattr(launcher, "_git_output", lambda *a: "")
    cloudxr_calls = []
    monkeypatch.setattr(
        launcher,
        "configure_cloudxr",
        lambda *args, **kwargs: cloudxr_calls.append((args, kwargs)),
    )
    assert launcher.main(["record", "--dry-run", "--smoke", "--state-root", str(tmp_path)]) == 0
    record_manifest = max(
        (tmp_path / "runs").glob("*/run_manifest.json"), key=lambda p: p.stat().st_mtime_ns
    )
    record_command = json.loads(record_manifest.read_text())["launch"]["command"]
    assert "--s2-record" in record_command and "--s2-teleop" not in record_command
    assert "--xr" not in record_command and "--experience" not in record_command
    assert (tmp_path / "recordings").stat().st_mode & 0o777 == 0o700
    record_kit_args = record_command[record_command.index("--kit_args") + 1]
    assert launcher.EPISODE_RECORDER_EXTENSION in record_kit_args
    assert "omni.kit.scene_view.xr" not in record_kit_args
    assert "scenePartitioning" not in record_kit_args
    assert "--s2-cloudxr-profile" not in record_command
    assert not cloudxr_calls
    hdf5 = tmp_path / "external" / "session.hdf5"
    assert (
        launcher.main(
            [
                "replay",
                "--recording",
                str(hdf5),
                "--render-cameras",
                str(tmp_path / "renders"),
                "--dry-run",
                "--state-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    replay_manifest = max(
        (tmp_path / "runs").glob("*/run_manifest.json"), key=lambda p: p.stat().st_mtime_ns
    )
    replay_command = json.loads(replay_manifest.read_text())["launch"]["command"]
    assert "--s2-replay-hdf5" in replay_command and "--s2-teleop" not in replay_command
    assert "--s2-render-cameras" in replay_command and "--demo-preview-scene" not in replay_command
    replay_kit_args = replay_command[replay_command.index("--kit_args") + 1]
    assert launcher.EPISODE_RECORDER_EXTENSION in replay_kit_args
    assert "omni.kit.scene_view.xr" not in replay_kit_args
    assert "--xr" not in replay_command
    assert "--experience" not in replay_command
    assert "--s2-cloudxr-profile" not in replay_command
    assert not cloudxr_calls


@pytest.mark.parametrize("profile", [False, True])
def test_physical_record_keeps_teleop_and_xr(launcher, tmp_path, monkeypatch, profile):
    stack = launcher.STACKS["isaac61"]
    monkeypatch.setattr(launcher, "verify_stack", lambda _: stack)
    monkeypatch.setattr(launcher, "_git_output", lambda *a: "")
    monkeypatch.setattr(launcher, "configure_cloudxr", lambda *args, **kwargs: None)
    flags = (
        ["--performance-warmup-steps", "60", "--performance-window-steps", "300"] if profile else []
    )
    assert launcher.main(["record", *flags, "--dry-run", "--state-root", str(tmp_path)]) == 0
    manifest = max(
        (tmp_path / "runs").glob("*/run_manifest.json"), key=lambda p: p.stat().st_mtime_ns
    )
    command = json.loads(manifest.read_text())["launch"]["command"]
    assert "--s2-record" in command and "--s2-teleop" in command
    assert "--xr" in command and "--experience" in command
    assert ("--s2-performance-log" in command) == profile
    assert command[command.index("--s2-mode") + 1] == "run"
    if profile:
        assert command[command.index("--s2-performance-log") + 1] == str(
            manifest.parent / "performance.jsonl"
        )
        assert command[command.index("--s2-performance-warmup-steps") + 1] == "60"
        assert command[command.index("--s2-performance-window-steps") + 1] == "300"


def test_injected_recording_smoke_selects_real_writer_without_xr(launcher, tmp_path, monkeypatch):
    stack = launcher.STACKS["isaac61"]
    monkeypatch.setattr(launcher, "verify_stack", lambda _: stack)
    monkeypatch.setattr(launcher, "_git_output", lambda *a: "")
    monkeypatch.setattr(launcher, "configure_cloudxr", lambda *args, **kwargs: None)
    assert (
        launcher.main(
            [
                "record",
                "--smoke",
                "--injected-actions",
                "--dry-run",
                "--state-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    manifest = max(
        (tmp_path / "runs").glob("*/run_manifest.json"), key=lambda p: p.stat().st_mtime_ns
    )
    command = json.loads(manifest.read_text())["launch"]["command"]
    assert "--s2-injected-recording-smoke" in command
    assert "--s2-record" in command and "--s2-teleop" not in command
    assert "--xr" not in command and "--experience" not in command
    assert "--s2-cloudxr-profile" not in command


def test_injected_recording_benchmark_emits_explicit_child_contract(
    launcher, tmp_path, monkeypatch
):
    stack = launcher.STACKS["isaac61"]
    monkeypatch.setattr(launcher, "verify_stack", lambda _: stack)
    monkeypatch.setattr(launcher, "_git_output", lambda *a: "")
    monkeypatch.setattr(launcher, "configure_cloudxr", lambda *args, **kwargs: None)
    assert (
        launcher.main(
            [
                "record",
                "--smoke",
                "--injected-actions",
                "--recording-benchmark",
                "--benchmark-pair-id",
                "no-headset-pair",
                "--benchmark-warmup-steps",
                "1",
                "--benchmark-measured-steps",
                "2",
                "--benchmark-flush-every-frames",
                "1",
                "--dry-run",
                "--state-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    manifest = max(
        (tmp_path / "runs").glob("*/run_manifest.json"), key=lambda p: p.stat().st_mtime_ns
    )
    command = json.loads(manifest.read_text())["launch"]["command"]
    assert command[command.index("--s2-recording-benchmark-pair-id") + 1] == "no-headset-pair"
    assert command[command.index("--s2-recording-benchmark-warmup-steps") + 1] == "1"
    assert command[command.index("--s2-recording-benchmark-measured-steps") + 1] == "2"
    assert "--s2-recording-benchmark-log" in command
    assert "--s2-teleop" not in command and "--xr" not in command


def module(monkeypatch, name, **attrs):
    m = ModuleType(name)
    m.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, m)
    return m


@pytest.mark.parametrize("decision_receipts", [False, True])
def test_actual_loop_processor_and_native_target_parity(tmp_path, monkeypatch, decision_receipts):
    """Execute run_s2 twice, including its native IK boundary; mock vendor IO only."""
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    from isaac_s2_processor import PROCESSOR_REVISION
    from isaac_vr_config import load_composition

    from tools.isaac_vr_decision import XrInputReceipt
    from test_isaac_vr_decision import capture

    config = load_composition("dual_cube_to_matching_plates")
    events = NS(should_reset=False, is_active=True)
    targets, commands, gpu_calls, hash_calls = [], [], [], []
    sensors = [camera() for _ in range(3)]

    class Device:
        session_running = True
        navigation_reset_applied = False

        def __enter__(self):
            self.index = 0
            self.xr_receipt = XrInputReceipt()
            self.xr_input = None
            self.session_token = object()
            return self

        def __exit__(self, *args):
            pass

        def reset(self, **kwargs):
            self.xr_receipt.reference_epoch += 1
            self.xr_input = None

        def validate_xr(self, xr):
            self.xr_receipt.validate(xr)

        def advance(self):
            self.index += 1
            self.xr_input = None
            if decision_receipts:
                previous = self.xr_receipt.update_epoch
                self.xr_receipt.polled(self.session_token, self.index)
                self.xr_receipt.transformed(((), ()), np.eye(4), False)
                self.xr_input = self.xr_receipt.resolve(
                    NS(
                        ran_synchronously=True,
                        worker_exception=None,
                        submitted_frame_id=self.index,
                        returned_frame_id=self.index,
                    ),
                    previous,
                )
            events.should_reset = self.index == 23
            events.is_active = self.index != 26
            if self.index in (14, 15):
                return None
            # The real unpacker expects per-arm delta[6], available, valid, clutch, trigger, slider.
            arm = [0.003, -0.002, 0.001, 0.01, -0.02, 0.03, 1.0, 1.0, 0.0, 0.35, 0.0]
            left, right = arm.copy(), arm.copy()
            left[7] = float(self.index not in (8, 9))
            right[8] = float(self.index in (5, 6))
            left[10], right[10] = (-1 + self.index / 15), (1 - self.index / 15)
            return torch.tensor([*left, *right, 0.0, 0.0, 0.0])

    device = Device()
    module(
        monkeypatch,
        "isaac_s2_upstream",
        DEMO_BACKDROP_BUTTON_INDEX=23,
        DEMO_DISPLAY_BUTTON_INDEX=22,
        DEMO_RECENTER_BUTTON_INDEX=24,
        PIPELINE_ACTION_DIM=22,
        build_piper_x_bimanual_pipeline=lambda **k: None,
        create_piper_x_teleop_device=lambda *a, **k: device,
    )
    module(monkeypatch, "isaacteleop.cloudxr.runtime", runtime_version=lambda: "6.2.1")
    module(
        monkeypatch,
        "isaaclab_teleop",
        CLOUDXR_JS_ENV="js",
        CLOUDXR_STANDALONE_ENV="standalone",
        IsaacTeleopCfg=lambda **k: NS(**k),
    )
    module(monkeypatch, "isaaclab_teleop.control_events", poll_control_events=lambda d: events)
    module(monkeypatch, "isaaclab_teleop.xr_cfg", XrCfg=lambda **k: NS(**k))

    class VendorIK:
        def __init__(self, *a, **kw):
            pass

        def set_joint_pos_limits(self, *a):
            pass

        def reset(self):
            pass

        def set_command(self, delta, **kw):
            commands.append(delta.clone())
            self.delta = delta

        def compute(self, pos, quat, jac, joints):
            return joints + self.delta  # deterministic vendor substitute; native clamp stays real

    module(
        monkeypatch,
        "isaaclab.controllers",
        DifferentialIKController=VendorIK,
        DifferentialIKControllerCfg=lambda **kw: kw,
    )
    module(monkeypatch, "isaaclab.utils.math", subtract_frame_transforms=lambda a, b, c, d: (c, d))
    # Import with vendor acquisition replaced, then exercise the unmodified shared loop.
    monkeypatch.delitem(sys.modules, "isaac_s2_runtime", raising=False)
    runtime = importlib.import_module("isaac_s2_runtime")
    versions = {
        "isaacsim": "6.1.0.0",
        "isaaclab": "17.0.2",
        "isaacteleop": "1.4.98rc1",
        "isaaclab-teleop": "0.9.0",
    }
    monkeypatch.setattr(runtime.importlib.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(runtime, "_gpu_observation", lambda: gpu_calls.append(True) or {})
    sample = runtime._camera_sample
    monkeypatch.setattr(runtime, "_camera_sample", lambda *a: hash_calls.append(True) or sample(*a))
    robots = [
        NS(
            data=NS(
                joint_limits=NS(torch=torch.tensor([[[-0.1, 0.1]] * 6])),
                body_link_pose_w=NS(torch=torch.zeros((1, 2, 7))),
                root_pose_w=NS(torch=torch.zeros((1, 7))),
                joint_pos=NS(torch=torch.zeros((1, 6))),
                body_link_jacobian_w=NS(torch=torch.ones((1, 2, 6, 6))),
            ),
            is_fixed_base=True,
            num_base_dofs=0,
        )
        for _ in range(2)
    ]
    rig = NS(wrists=sensors[:2], scene_camera=sensors[2], frame=torch.ones(2, dtype=torch.int64))

    def unavailable_capture():
        if decision_receipts:
            return env.current_capture
        raise RuntimeError("fixture has no qualified camera capture")

    def advance(repeat):
        assert repeat == 4
        if env.last_control_decision is not None:
            assert env.last_control_decision.observation_identity is env.current_capture
            assert env.prepared_control_transaction is not None
            assert device.index not in (8, 9, 10, 14, 15, 16, 18, 19, 23, 24, 26, 27)
            admitted.append(env.last_control_decision.control_tick_id)
        env.step += repeat
        env._state_physics_step = env.step
        env.current_capture = capture(env.step, env.reset_epoch)
        for c in sensors:
            c.frame += 1
        rig.frame += 1

    def reset(_):
        env.reset_epoch += 1
        env.current_capture = capture(env.step, env.reset_epoch)
        for c in sensors:
            c.frame.fill_(1)
        rig.frame.fill_(1)

    composition = NS(
        config=config,
        profile="dual_cube_to_matching_plates",
        sensitivity=config["teleop_tuning"]["sensitivity"],
        xr_presentation=config["xr_presentation"],
        display_control="left_primary_click",
        backdrop_control="right_secondary_click",
        recenter_control="right_thumbstick_click",
        pipeline_action_dim=25,
        display_visible=False,
        backdrop_visible=True,
        open=lambda e: None,
        close=lambda: None,
        after_reset=lambda: None,
        consume_display_button=lambda *a, **k: None,
        consume_backdrop_button=lambda *a, **k: None,
        consume_recenter_button=lambda *a, **k: False,
        performance_report=lambda *a: {},
    )
    admitted = []
    env = NS(
        step=20,
        _state_physics_step=20,
        reset_epoch=0,
        current_capture=capture(),
        latest_observation_capture=unavailable_capture,
        vr_runtime=composition,
        robots=robots,
        wrist_ids=[1, 1],
        joint_ids=[list(range(6))] * 2,
        sim=NS(device="cpu", get_physics_step_count=lambda: env.step),
        camera=rig,
        reset=reset,
        _advance=advance,
        _apply=lambda t: targets.append(copy.deepcopy(t)),
        observation=lambda: {
            f"observation.images.{r}": np.zeros((480, 640, 3), np.uint8)
            for r in ("left_wrist", "right_wrist")
        },
    )
    outputs = []
    for mode in ("run", "diagnostic"):
        targets.clear()
        commands.clear()
        gpu_calls.clear()
        hash_calls.clear()
        log = tmp_path / f"{mode}.jsonl"
        args = NS(
            s2_config=ROOT / "configs/isaac61_s2_runtime.yaml",
            s2_mode=mode,
            s2_cloudxr_profile="standalone",
            xr=False,
            s2_max_control_steps=30,
            s2_reset_step=18,
            s2_require_session=False,
            s2_require_tracking=True,
            s2_performance_log=log if mode == "diagnostic" else None,
            s2_performance_window_steps=5,
            s2_performance_warmup_steps=0,
            demo_display_toggle_smoke=False,
            demo_backdrop_toggle_smoke=False,
            demo_recenter_smoke=False,
            report=tmp_path / f"{mode}.json",
        )
        assert runtime.run_s2(env, args, NS(is_running=lambda: True)) == 0
        assert bool(gpu_calls) == bool(hash_calls) == log.exists() == (mode == "diagnostic")
        assert (env.performance_logger is not None) == (mode == "diagnostic")
        report = json.loads(args.report.read_text())
        assert report["gate"] == "S2" and report["processor"]["revision"] == PROCESSOR_REVISION
        outputs.append((copy.deepcopy(targets), copy.deepcopy(commands)))
    for run, diag in zip(outputs[0][0], outputs[1][0], strict=True):
        np.testing.assert_array_equal(run.left_rad_m, diag.left_rad_m)
        np.testing.assert_array_equal(run.right_rad_m, diag.right_rad_m)
        assert run.saturated == diag.saturated
    for run, diag in zip(outputs[0][1], outputs[1][1], strict=True):
        assert torch.equal(run, diag)
    assert any(torch.count_nonzero(c) for c in outputs[0][1])
    if decision_receipts:
        half = len(admitted) // 2
        assert admitted[:half] == admitted[half:] == list(range(1, half + 1))
    else:
        # Execute normal RECORD's logger branch without diagnostic observers.
        import isaac_vr_recording

        closed = []
        record = NS(
            committed_frames=0,
            discarded_observations=0,
            rejections={},
            run_id="run",
            session_id="session",
            episode_id="episode_000000",
            source_profile="isaac_human_vr_offline_rgb_v1",
            capture_observation=lambda: NS(observation=env.current_capture),
            discard_observation=lambda *a, **kw: None,
            close=lambda **kw: closed.append(kw),
        )
        monkeypatch.setattr(isaac_vr_recording, "start_live_recording", lambda *a, **kw: record)
        monkeypatch.setattr(runtime, "recording_portable_roots", lambda _: {})
        composition.disable_live_rgb = lambda: None
        args.s2_mode = "run"
        args.s2_record = args.s2_teleop = True
        args.s2_recording_dir = tmp_path / "recording"
        args.s2_max_control_steps = 4
        args.s2_reset_step = 0
        args.s2_performance_log = tmp_path / "record-performance.jsonl"
        args.report = tmp_path / "record-result.json"
        gpu_calls.clear()
        hash_calls.clear()
        assert runtime.run_s2(env, args, NS(is_running=lambda: True)) == 0
        assert not gpu_calls and not hash_calls
        assert env.performance_logger.path == args.s2_performance_log
        result = json.loads(args.report.read_text())
        assert result["execution"]["performance"]["control"]["samples"] == 4
        assert closed and result["recording"]["committed_frames"] == 0


def test_current_doc_sources_and_contract():
    paths = [
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        *(ROOT / "docs").glob("*.md"),
        ROOT / "docs/project/RUN_VR_OPERATIONS.md",
        ROOT / "docs/project/migrations/20260918_isaac1103/OPERATIONS.md",
        ROOT / "docs/project/CORE_ENVIRONMENT_OPERATIONS.md",
        ROOT / "docs/project/GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md",
    ]
    for path in paths:
        text = path.read_text()
        assert "tools/launch_isaac_s2.py" not in text, path
        assert "configs/experiments/robosyn_vr_demo.yaml" not in text, path
        assert "normal 2x / precise 0.5x" not in text, path
    c = yaml.safe_load((ROOT / "configs/resolved_contract.yaml").read_text())
    rules = yaml.safe_load((ROOT / "configs/gate_rules.yaml").read_text())
    assert c["execution_profiles"]["isaac_vr"]["command"] == ["./run-vr"]
    assert c["teleop"]["isaac"]["execution_profile"] == "isaac_vr"
    assert "execution_profiles.isaac_vr.command" in rules["S2"]["required_paths"]
    assert c["gates"]["S2"]["state"] == c["gates"]["D1"]["state"] == "unresolved"
    assert c["simulation"]["isaac"]["recorder"]["execution_profile"] == "isaac_vr_record"
    from tools.validate_resolved_contract import validate_profiles

    c["simulation"]["isaac"]["recorder"]["execution_profile"] = "isaac_vr"
    assert any("must be distinct" in e for e in validate_profiles(c))
