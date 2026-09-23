"""Current record/replay behavioral audit; known defects stay explicit strict xfails."""

from __future__ import annotations

import ast
import asyncio
import copy
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import numpy as np
import pytest
import torch
import yaml

from tools.d0_causal import CausalTransactionValidator
from tools.isaac_vr_capture import ThreeCameraCapture
from tools.isaac_vr_recording import ExplicitFrameSampler, _d0_channels
from test_isaac_vr_decision import ik_fixture
from test_run_vr import module

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def record_loop(monkeypatch):
    """Real loop, processor, solve/apply, validator and sampler; fake XR/physics IO."""
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    from tools.isaac_vr_decision import XrInputReceipt

    events = NS(should_reset=False, is_active=True)
    control = NS(inactive=set(), reconnect=set(), fail_step=None, interrupt_step=None, prime=False)
    rows, decisions, validators, outcomes, repeats = [], [], [], [], []

    class Device:
        session_running = True
        navigation_reset_applied = False

        def __enter__(self):
            self.index = 0
            self.xr_receipt = XrInputReceipt()
            self.session = object()
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
            if self.index == control.interrupt_step:
                raise KeyboardInterrupt
            if self.index in control.reconnect:
                self.session = object()
            receipt = self.xr_receipt
            previous = receipt.update_epoch
            receipt.polled(self.session, self.index)
            receipt.transformed(((), ()), np.eye(4), False)
            self.xr_input = receipt.resolve(
                NS(
                    ran_synchronously=True,
                    worker_exception=None,
                    submitted_frame_id=self.index,
                    returned_frame_id=self.index,
                ),
                previous,
            )
            events.is_active = self.index not in control.inactive
            arm = [0.003, -0.002, 0.001, 0.01, -0.02, 0.03, 1.0, 1.0, 0.0, 0.35, 0.0]
            return torch.tensor([*arm, *arm, 0.0, 0.0, 0.0])

    device = Device()
    module(
        monkeypatch,
        "isaac_s2_upstream",
        DEMO_BACKDROP_BUTTON_INDEX=23,
        DEMO_DISPLAY_BUTTON_INDEX=22,
        DEMO_RECENTER_BUTTON_INDEX=24,
        PIPELINE_ACTION_DIM=22,
        build_piper_x_bimanual_pipeline=lambda **kw: None,
        create_piper_x_teleop_device=lambda *a, **kw: device,
    )
    module(monkeypatch, "isaacteleop.cloudxr.runtime", runtime_version=lambda: "6.2.1")
    module(
        monkeypatch,
        "isaaclab_teleop",
        CLOUDXR_JS_ENV="js",
        CLOUDXR_STANDALONE_ENV="standalone",
        IsaacTeleopCfg=lambda **kw: NS(**kw),
    )
    module(monkeypatch, "isaaclab_teleop.control_events", poll_control_events=lambda d: events)
    module(monkeypatch, "isaaclab_teleop.xr_cfg", XrCfg=lambda **kw: NS(**kw))
    monkeypatch.delitem(sys.modules, "isaac_s2_runtime", raising=False)
    runtime = importlib.import_module("isaac_s2_runtime")
    monkeypatch.setattr(
        runtime.importlib.metadata,
        "version",
        {
            "isaacsim": "6.1.0.0",
            "isaaclab": "17.0.2",
            "isaacteleop": "1.4.98rc1",
            "isaaclab-teleop": "0.9.0",
        }.__getitem__,
    )
    ik, env = ik_fixture()
    for controller in ik.controllers:
        controller.reset = lambda: None
    monkeypatch.setattr(runtime, "_BimanualDifferentialIk", lambda e: ik)
    processor_type = runtime.BimanualS2TeleopProcessor

    class PrimableProcessor(processor_type):
        def reset(self):
            super().reset()
            if control.prime:
                from test_isaac_vr_decision import sample

                self.advance(sample(), sample())

    monkeypatch.setattr(runtime, "BimanualS2TeleopProcessor", PrimableProcessor)
    env.camera = NS(reset_epoch=0)
    env.sim.render_generation = 0
    env.capture_measured_state = lambda: (env.step, (float(env.step),) * 14)

    def reset(seed):
        env.camera.reset_epoch += 1

    def advance(repeat):
        repeats.append(repeat)
        assert repeat == 4
        if env.last_control_decision is not None:
            assert validators[-1].accepted_transactions == len(decisions)
            decisions.append(env.last_control_decision)
        # Failure occurs AFTER the native target has been written.
        if device.index == control.fail_step:
            env.step += 2
            raise RuntimeError("injected successor failure")
        for _ in range(repeat):
            env.step += 1
        env.sim.render_generation += 1

    env.reset, env._advance = reset, advance
    config = yaml.safe_load((ROOT / "configs/isaac61_vr_runtime.yaml").read_text())
    env.vr_runtime = NS(
        profile="dual_cube_to_matching_plates",
        config=config,
        sensitivity=config["teleop_tuning"]["sensitivity"],
        xr_presentation=config["xr_presentation"],
        display_control="left_primary_click",
        backdrop_control="right_secondary_click",
        recenter_control="right_thumbstick_click",
        pipeline_action_dim=25,
        disable_live_rgb=lambda: None,
        close=lambda: None,
    )

    def validator(*a, **kw):
        instance = CausalTransactionValidator(*a, **kw)
        validators.append(instance)
        return instance

    monkeypatch.setattr(runtime, "CausalTransactionValidator", validator)

    class D0:
        group = "d0/transition"
        current = None

        def describe_channels(self):
            return _d0_channels(lambda **kw: NS(**kw))

        def sample(self):
            return self.current

    d0 = D0()
    storage = NS(advanced=0)

    def append(group, row):
        rows.append(copy.deepcopy(row))

    def advance_storage():
        storage.advanced += 1

    storage.append_frame, storage.advance_episode_frame = append, advance_storage
    sampler = ExplicitFrameSampler(storage, [d0])

    def sample(row):
        d0.current = row
        sampler.sample_frame()

    module(
        monkeypatch,
        "isaac_vr_recording",
        start_live_recording=lambda *a, **kw: NS(
            sample=sample, close=lambda **kw: outcomes.append(kw["outcome"])
        ),
    )

    def run(steps=2):
        args = NS(
            s2_config=ROOT / "configs/isaac61_s2_runtime.yaml",
            s2_mode="run",
            s2_record=True,
            s2_recording_dir=Path("unused-fake-storage"),
            s2_cloudxr_profile="standalone",
            xr=False,
            s2_max_control_steps=steps,
            s2_reset_step=0,
            s2_require_session=False,
            s2_require_tracking=False,
            s2_performance_log=None,
            demo_display_toggle_smoke=False,
            demo_backdrop_toggle_smoke=False,
            demo_recenter_smoke=False,
            report=None,
        )
        return runtime.run_s2(env, args, NS(is_running=lambda: True))

    return NS(
        run=run,
        control=control,
        rows=rows,
        decisions=decisions,
        validators=validators,
        outcomes=outcomes,
        repeats=repeats,
        env=env,
        storage=storage,
    )


def test_active_recording_exercises_real_decision_commit_and_storage(record_loop):
    r = record_loop
    assert r.run() == 0
    initial, rebase, successor = r.rows
    assert initial["observation_id"] == 0
    assert initial["action_valid"] == initial["transition_completed"] == 0
    assert initial["action_from_observation_id"] == initial["action_to_observation_id"] == -1
    assert rebase["action_valid"] == 0
    solution = r.decisions[0]
    assert successor["action_valid"] == successor["transition_completed"] == 1
    assert (successor["action_from_observation_id"], successor["action_to_observation_id"]) == (
        1,
        2,
    )
    assert successor["action_source_physics_step"] == rebase["observation_physics_step"]
    assert successor["observation_physics_step"] - successor["action_source_physics_step"] == 4
    assert np.count_nonzero(successor["dataset_action"]) > 0
    np.testing.assert_array_equal(successor["dataset_action"], solution.dataset_action)
    np.testing.assert_array_equal(successor["native_preclip"], np.float32(solution.native_preclip))
    np.testing.assert_array_equal(successor["native_clipped"], np.float32(solution.native_clipped))
    assert r.validators[0].accepted_transactions == 1 and r.storage.advanced == 3
    assert r.repeats == [4, 4]


def test_inactive_ticks_never_commit(record_loop):
    r = record_loop
    r.control.inactive = {1, 2, 3}
    assert r.run(3) == 0
    assert not r.validators and not any(row["action_valid"] for row in r.rows)


def test_failure_after_native_write_never_publishes_transition(record_loop):
    r = record_loop
    r.control.fail_step = 2
    with pytest.raises(RuntimeError, match="successor failure"):
        r.run()
    assert len(r.env.applied) == 2
    assert r.validators[0].accepted_transactions == 0
    assert len(r.rows) == 2 and not any(row["action_valid"] for row in r.rows)
    assert r.outcomes == ["unclassified"]  # Current failure classification, not success.


def test_ctrl_c_finalizes_without_inventing_successor(record_loop):
    r = record_loop
    r.control.interrupt_step = 3
    assert r.run(3) == 130
    assert len(r.rows) == 3 and r.outcomes == ["operator_stopped"]
    assert r.validators[0].accepted_transactions == 1


@pytest.mark.xfail(
    strict=True, reason="139a065: same-epoch inactive gap retains stale expected successor"
)
def test_resume_after_inactive_gap_can_record_again(record_loop):
    r = record_loop
    r.control.inactive = {3}
    assert r.run(5) == 0
    assert r.validators[0].accepted_transactions == 2


def test_session_change_is_spliced_into_same_episode(record_loop):
    r = record_loop
    r.control.reconnect = {3}
    assert r.run(3) == 0
    assert [row["session_epoch"] for row in r.rows if row["action_valid"]] == [1, 2]
    assert len(r.validators) == 1 and r.validators[0].accepted_transactions == 2
    assert r.storage.advanced == 4


def load_method(path, class_name, method, namespace):
    """Execute the real Kit-bound method with fake IO, rather than AST assertions."""
    tree = ast.parse((ROOT / path).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method)
    exec(compile(ast.Module([node], []), str(path), "exec"), namespace)
    return namespace[method]


@pytest.mark.xfail(
    strict=True, raises=RuntimeError, reason="139a065: reset requires capture disabled by RECORD"
)
def test_record_reset_does_not_require_rgb(monkeypatch):
    from test_isaac_vr_capture import environment

    env, cameras = environment(monkeypatch)
    env.reset(0)
    env.camera.live_rgb_enabled = False
    env.camera.capture.invalidate()
    env.reset(0)


@pytest.mark.xfail(
    strict=True,
    raises=asyncio.InvalidStateError,
    reason="139a065: asyncio Task.result called before Kit can pump it",
)
def test_optional_render_waits_for_async_capture(monkeypatch, tmp_path):
    from tools.isaac_vr_replay import _render_frame

    loop = asyncio.new_event_loop()
    tasks = []

    async def step():
        await asyncio.sleep(0)

    def schedule(coro):
        task = loop.create_task(coro)
        tasks.append(task)
        return task

    rep = module(
        monkeypatch,
        "omni.replicator.core",
        create=NS(render_product=lambda *a, **kw: NS(destroy=lambda: None)),
        AnnotatorRegistry=NS(
            get_annotator=lambda name: NS(
                attach=lambda p: None,
                detach=lambda: None,
                get_data=lambda: np.zeros((480, 640, 4), dtype=np.uint8),
            )
        ),
        orchestrator=NS(step_async=step),
    )
    engine = module(monkeypatch, "omni.kit.async_engine", run_coroutine=schedule)
    kit = module(monkeypatch, "omni.kit", async_engine=engine)
    replicator = module(monkeypatch, "omni.replicator", core=rep)
    module(monkeypatch, "omni", kit=kit, replicator=replicator)
    try:
        images = _render_frame(
            {r: f"/World/{r}" for r in ("left_wrist", "right_wrist", "scene")}, tmp_path, 0
        )
        assert len(images) == 3
    finally:
        for task in tasks:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        loop.close()


def test_injected_eligible_a0_maps_zero_to_one(record_loop):
    r = record_loop
    r.control.prime = True  # Inject an already-rebased processor, before sampling O0.
    assert r.run(1) == 0
    initial, successor = r.rows
    assert initial["observation_id"] == 0 and initial["action_valid"] == 0
    assert initial["action_from_observation_id"] == initial["action_to_observation_id"] == -1
    assert successor["action_from_observation_id"] == 0
    assert successor["action_to_observation_id"] == successor["observation_id"] == 1
    assert successor["action_valid"] == successor["transition_completed"] == 1
    assert successor["observation_physics_step"] - initial["observation_physics_step"] == 4
    solution = r.decisions[0]
    assert np.count_nonzero(solution.dataset_action)
    np.testing.assert_array_equal(successor["dataset_action"], solution.dataset_action)
    np.testing.assert_array_equal(successor["native_clipped"], np.float32(solution.native_clipped))
    np.testing.assert_array_equal(r.env.applied[-1].left_rad_m, solution.native_clipped[:7])
    assert r.validators[0].accepted_transactions == 1 and r.storage.advanced == 2


@pytest.mark.parametrize("mutation", ["physics", "state", "reset"])
def test_state_only_solution_rejects_changed_generation(mutation):
    from test_isaac_vr_decision import sample, xr_receipt
    from tools.isaac_s2_processor import BimanualS2TeleopProcessor
    from tools.isaac_vr_decision import capture_state_only_observation

    ik, env = ik_fixture()
    env.camera = NS(reset_epoch=1)
    env.sim.render_generation = 1
    env.measured = (0.0,) * 14
    env.capture_measured_state = lambda: (env.step, env.measured)
    observation = capture_state_only_observation(env)
    receipt, _, xr = xr_receipt()
    processor = BimanualS2TeleopProcessor()
    processor.advance(sample(), sample())
    command = processor.advance(sample(), sample())
    ik.device, ik.processor = NS(validate_xr=receipt.validate, xr_receipt=receipt), processor
    solution = ik.solve(command, observation, xr, 1)
    if mutation == "physics":
        env.step += 1
    elif mutation == "state":
        env.measured = (1.0,) * 14
    else:
        env.camera.reset_epoch += 1
    with pytest.raises(RuntimeError, match="generation mismatch"):
        ik.solve(command, observation, xr, 2)
    with pytest.raises(RuntimeError, match="generation mismatch"):
        ik.apply(solution)
    assert not env.applied


def prepared_state_decision():
    from test_isaac_vr_decision import sample, xr_receipt
    from tools.d0_causal import STATE_ONLY_SIM_SOURCES
    from tools.isaac_s2_processor import BimanualS2TeleopProcessor
    from tools.isaac_vr_capture import ProducerBoundary
    from tools.isaac_vr_decision import SolvedControlDecision, StateOnlyObservation, decision_epoch

    observation = StateOnlyObservation(ProducerBoundary(1, 20, 5), (0.0,) * 14)
    _, _, xr = xr_receipt()
    processor = BimanualS2TeleopProcessor()
    processor.advance(sample(), sample())
    command = processor.advance(sample(), sample())
    solution = SolvedControlDecision.from_native(
        1, observation, xr, command, [0.123456789] * 14, [0.1] * 14
    )
    validator = CausalTransactionValidator(
        "isaac",
        "human_vr",
        decision_epoch("test", observation, xr),
        sim_sources=STATE_ONLY_SIM_SOURCES,
    )
    return solution, validator, solution.prepare(validator)


def test_reset_crossing_and_reused_prepared_transaction_rejected():
    from dataclasses import replace
    from tools.isaac_vr_decision import complete_recorded_transition

    solution, validator, prepared = prepared_state_decision()
    source = solution.observation_identity
    wrong = replace(source, producer=replace(source.producer, physics_step=24, reset_epoch=2))
    with pytest.raises(RuntimeError, match="reset epoch"):
        complete_recorded_transition(solution, validator, prepared, wrong)
    assert validator.accepted_transactions == 0
    successor = replace(source, producer=replace(source.producer, physics_step=24))
    complete_recorded_transition(solution, validator, prepared, successor)
    with pytest.raises(ValueError, match="transaction_not_pending"):
        complete_recorded_transition(solution, validator, prepared, successor)
    assert validator.accepted_transactions == 1


@pytest.mark.parametrize("substeps", [0, 3, 5])
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="139a065: completion helper trusts caller; it never enforces four substeps",
)
def test_completion_rejects_wrong_physics_distance(substeps):
    from dataclasses import replace
    from tools.isaac_vr_decision import complete_recorded_transition

    solution, validator, prepared = prepared_state_decision()
    source = solution.observation_identity
    successor = replace(source, producer=replace(source.producer, physics_step=20 + substeps))
    try:
        complete_recorded_transition(solution, validator, prepared, successor)
    except RuntimeError:
        return
    assert validator.accepted_transactions == 0


@pytest.fixture
def snapshot_replay(monkeypatch, tmp_path):
    import hashlib
    import json
    from tools.isaac_vr_recording import _empty_d0_sample
    from tools.isaac_vr_replay import replay_snapshot

    recording = tmp_path / "session.hdf5"
    recording.touch()
    snapshot = tmp_path / "stage_snapshot.usd"
    snapshot.write_bytes(b"fake USD; stage IO is mocked")
    roles = {r: f"/World/{r}" for r in ("left_wrist", "right_wrist", "scene")}
    sidecar = {
        "stage_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "camera_roles": roles,
    }
    (tmp_path / "manifest.json").write_text(json.dumps(sidecar))
    rows = [_empty_d0_sample() for _ in range(3)]
    for i, row in enumerate(rows):
        row.update(
            observation_id=np.int64(i),
            observation_physics_step=np.int64(20 + i * 4),
            reset_epoch=np.int64(1),
            observation_render_generation=np.int64(i),
        )
    rows[1].update(
        action_valid=np.uint8(1),
        transition_completed=np.uint8(1),
        action_from_observation_id=np.int64(0),
        action_to_observation_id=np.int64(1),
        action_source_physics_step=np.int64(20),
        action_source_render_generation=np.int64(0),
    )
    groups = [
        "state/left_robot",
        "state/right_robot",
        *(f"state/camera/{r}" for r in roles),
        "d0/transition",
    ]
    events, renders = [], []

    class Reader:
        def __init__(self, path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def list_episodes(self):
            return ["episode_00000"]

        def normalize_episode(self, i):
            assert i == 0
            return "episode_00000"

        def num_frames(self, episode):
            return 3

        def manifest(self):
            return NS(tracks=[{"group": g, "type": "fake"} for g in groups])

        def read_group_all_frames(self, *a):
            return {k: np.asarray([r[k] for r in rows]) for k in rows[0]}

    class Replayer:
        def __init__(self, path, *, pose_backend):
            assert pose_backend == "usd" and "active_stage_open" in events
            events.append("replayer")

        def prepare_episode(self, episode):
            events.append("prepare")

        def apply_frame(self, frame):
            events.append(("apply", frame))

        def close(self):
            events.append("close")

    module(
        monkeypatch,
        "isaac_vr_recording",
        ensure_d0_recordable=lambda: None,
        ensure_episode_recorder_enabled=lambda: events.append("enable"),
    )
    module(
        monkeypatch,
        "isaacsim.replicator.episode_recorder",
        SessionReader=Reader,
        EpisodeReplayer=Replayer,
    )
    prepared = NS(
        GetPrimAtPath=lambda path: True,
        RemovePrim=lambda path: events.append(("remove", path)),
        GetRootLayer=lambda: NS(Export=lambda path: events.append("export")),
    )
    context = NS(
        open_stage=lambda path: events.append("active_stage_open"), get_stage=lambda: prepared
    )
    usd = module(monkeypatch, "omni.usd", get_context=lambda: context)
    physx = module(
        monkeypatch,
        "omni.physx",
        get_physx_interface=lambda: NS(subscribe_physics_step_events=lambda cb: object()),
    )
    rep = module(
        monkeypatch, "omni.replicator.core", orchestrator=NS(set_capture_on_play=lambda v: None)
    )
    module(
        monkeypatch,
        "omni",
        usd=usd,
        physx=physx,
        replicator=module(monkeypatch, "omni.replicator", core=rep),
    )
    settings = module(
        monkeypatch,
        "carb.settings",
        get_settings=lambda: NS(set=lambda name, value: events.append((name, value))),
    )
    module(monkeypatch, "carb", settings=settings)
    module(monkeypatch, "pxr", Usd=NS(Stage=NS(Open=lambda path: prepared)))

    def materialize(paths, directory, frame):
        renders.append((frame, paths))
        return [{"role": role, "frame": frame} for role in paths]

    monkeypatch.setattr("tools.isaac_vr_replay._render_frame", materialize)
    report = tmp_path / "report.json"

    def run():
        return replay_snapshot(
            NS(update=lambda: events.append("pump")),
            recording=recording,
            episode=0,
            render_cameras=tmp_path / "renders",
            report_path=report,
        )

    return NS(
        run=run,
        events=events,
        renders=renders,
        rows=rows,
        report=report,
        snapshot=snapshot,
        groups=groups,
    )


def test_snapshot_is_opened_before_replayer_and_materialization(snapshot_replay):
    r = snapshot_replay
    assert r.run() == 0
    assert (
        r.events.index("active_stage_open") < r.events.index("replayer") < r.events.index("prepare")
    )
    assert r.events.count("pump") == 20
    assert [("apply", i) for i in range(3)] == [
        e for e in r.events if isinstance(e, tuple) and e[0] == "apply"
    ]
    assert [("remove", "/Render"), ("remove", "/Replicator")] == [
        e for e in r.events if isinstance(e, tuple) and e[0] == "remove"
    ]
    assert [frame for frame, paths in r.renders] == [0, 1, 2]
    assert sum(len(paths) for frame, paths in r.renders) == 9


def test_snapshot_hash_mismatch_rejects_before_stage_open(snapshot_replay):
    r = snapshot_replay
    r.snapshot.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="hash"):
        r.run()
    assert "active_stage_open" not in r.events


@pytest.mark.parametrize(
    "mutation", ["missing_track", "initial_action", "wrong_index", "incomplete"]
)
def test_replay_rejects_invalid_track_or_d0_index(snapshot_replay, mutation):
    r = snapshot_replay
    if mutation == "missing_track":
        r.groups.pop()
    elif mutation == "initial_action":
        r.rows[0]["action_valid"] = np.uint8(1)
    elif mutation == "wrong_index":
        r.rows[1]["action_from_observation_id"] = np.int64(1)
    else:
        r.rows[1]["transition_completed"] = np.uint8(0)
    with pytest.raises(RuntimeError):
        r.run()
    assert "active_stage_open" not in r.events


@pytest.mark.parametrize("mutation", ["three_steps", "reset_splice"])
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="139a065: replay validates ordering but not exact physics distance or epoch continuity",
)
def test_replay_rejects_invalid_physics_or_epoch(snapshot_replay, mutation):
    r = snapshot_replay
    if mutation == "three_steps":
        r.rows[1]["action_source_physics_step"] = np.int64(21)
    else:
        r.rows[1]["reset_epoch"] = np.int64(2)
    try:
        r.run()
    except RuntimeError:
        return
    assert not r.report.exists(), "invalid transition was accepted and reported"


def test_record_disable_bypasses_capture_but_does_not_disable_products():
    capture = ThreeCameraCapture(
        dict.fromkeys(("left_wrist", "right_wrist", "scene")),
        lambda: pytest.fail("capture must not run"),
        lambda: pytest.fail("state read from capture"),
    )
    products = [NS(updates_enabled=True, annotator_attached=True) for _ in range(3)]
    rig = NS(live_rgb_enabled=True, capture=capture, products=products)
    runtime = NS(camera_rig=rig)
    disable = load_method("tools/isaac_vr_runtime.py", "VRRuntime", "disable_live_rgb", {})
    update = load_method("tools/isaac_vr_runtime.py", "VRCameraRig", "update", {})
    boundary = load_method("tools/isaac_vr_runtime.py", "VRCameraRig", "capture_boundary", {})
    disable(runtime)
    update(rig, 1 / 120)
    boundary(rig, None)
    assert rig.live_rgb_enabled is False
    assert all(p.updates_enabled and p.annotator_attached for p in products)
    assert capture.successful_capture_cycle == 0


@pytest.mark.parametrize(
    "args",
    [
        ["run", "--recording-dir", "/tmp/unused"],
        ["record", "--recording", "/tmp/unused"],
        ["record", "--render-cameras", "/tmp/unused"],
        ["record", "--replay-report", "/tmp/unused"],
    ],
)
def test_record_replay_flags_reject_wrong_modes(monkeypatch, args):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    from launch_isaac_vr import parse_args

    with pytest.raises(SystemExit):
        parse_args(args)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="139a065: --episode is accepted and ignored outside replay",
)
def test_episode_flag_rejects_record_mode(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    from launch_isaac_vr import parse_args

    try:
        parse_args(["record", "--episode", "2"])
    except SystemExit:
        return
    assert False, "replay-only flag accepted in record mode"


def test_actual_record_advance_is_four_substeps_without_camera_reads(monkeypatch):
    from test_isaac_vr_capture import environment
    from tools.isaac_vr_decision import capture_state_only_observation

    env, cameras = environment(monkeypatch)
    env.reset(0)
    env.camera.live_rgb_enabled = False
    env.camera.capture.invalidate()
    camera_updates = [camera.updates for camera in cameras]
    source = capture_state_only_observation(env)
    env._advance(4)
    successor = capture_state_only_observation(env)
    assert successor.producer.physics_step - source.producer.physics_step == 4
    assert [camera.updates for camera in cameras] == camera_updates
