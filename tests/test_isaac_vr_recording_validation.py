"""Behavioral regressions for current state-only record/replay correctness."""

from __future__ import annotations

import ast
import asyncio
import copy
import importlib
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace as NS
from typing import Any

import numpy as np
import pytest
import torch
import yaml

from tools.d0_causal import CausalTransactionValidator
from tools.isaac_vr_capture import ThreeCameraCapture
from tools.isaac_vr_camera_rendering import DatasetCameraSuspension, ROLES
from tools.isaac_vr_recording import ExplicitFrameSampler, _d0_channels
from test_isaac_vr_decision import ik_fixture
from test_run_vr import module

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def rendering_resources(monkeypatch):
    class AnnotatorRegistryError(Exception):
        pass
    module(monkeypatch, "omni.replicator.core.scripts.annotators",
           AnnotatorRegistryError=AnnotatorRegistryError)
    observers = []
    def observe(**kwargs):
        handle = NS(active=True)
        handle.reset = lambda: setattr(handle, "active", False)
        observers.append((kwargs, handle))
        return handle
    module(monkeypatch, "carb.eventdispatcher", get_eventdispatcher=lambda: NS(observe_event=observe))
    hydra_module = module(monkeypatch, "omni.hydratexture", GLOBAL_EVENT_DRAWABLE_CHANGED="drawable")
    module(monkeypatch, "omni", hydratexture=hydra_module)
    prims = {}
    cameras = {}
    for role in ROLES:
        prim, product = f"/World/{role}", f"/Render/{role}"
        prims[prim] = NS(IsValid=lambda: True, GetTypeName=lambda: "Camera")
        prims[product] = NS(IsValid=lambda: True)
        texture = NS(updates_enabled=True, frame_number=160)
        texture.get_name = lambda role=role: role
        texture.get_event_key = lambda role=role: {"texture": role}
        def frame_info(result_handle, t=texture):
            assert result_handle != 0  # Kit requires a live drawable event handle.
            return {"frame_number": t.frame_number}
        texture.get_frame_info = frame_info
        annotator = NS(is_attached=True, node_active=True, detaches=[])
        def detach(paths, a=annotator):
            a.detaches.append(paths)
            a.node_active = False  # Pinned is_attached stays stale after detach.
        def get_node(a=annotator):
            if not a.node_active:
                raise AnnotatorRegistryError("detached")
            return NS(is_valid=lambda: True)
        annotator.detach = detach
        annotator.get_node = get_node
        cameras[role] = NS(
            frame=NS(torch=torch.zeros(1, dtype=torch.int64)),
            _render_data=NS(spec=NS(camera_prim_paths=(prim,)),
                            render_product=NS(path=product, hydra_texture=texture),
                            annotators={"rgba": annotator}),
        )
    stage = NS(GetPrimAtPath=lambda p: prims.get(p, NS(IsValid=lambda: False)))
    return NS(cameras=cameras, stage=stage, prims=prims, observers=observers)


def bind_suspension(runtime):
    for name in ("suspend_dataset_camera_rendering", "check_dataset_camera_rendering"):
        method = load_method("tools/isaac_vr_runtime.py", "VRRuntime", name,
                             {"Any": Any, "DatasetCameraSuspension": DatasetCameraSuspension})
        setattr(runtime, name, MethodType(method, runtime))


@pytest.fixture
def record_loop(monkeypatch, rendering_resources):
    """Real loop, processor, solve/apply, validator and sampler; fake XR/physics IO."""
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    from tools.isaac_vr_decision import XrInputReceipt

    events = NS(should_reset=False, is_active=True)
    control = NS(inactive=set(), reconnect=set(), fail_step=None, interrupt_step=None, prime=False, reset_step=0, reference=set(), disconnected=set())
    rows, decisions, validators, outcomes, repeats = [], [], [], [], []
    segments = [[]]
    failures = []

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
            self.session_running = self.index not in control.disconnected
            if self.index == control.interrupt_step:
                raise KeyboardInterrupt
            if self.index in control.reconnect:
                self.session = object()
            receipt = self.xr_receipt
            if self.index in control.reference:
                receipt.reference_epoch += 1
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
    cameras = rendering_resources.cameras
    env.camera = NS(reset_epoch=0, wrists=(cameras["left_wrist"], cameras["right_wrist"]),
                    scene_camera=cameras["scene"], live_rgb_enabled=False)
    env.sim.stage = rendering_resources.stage
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
        camera_rig=env.camera, dataset_camera_suspension=None,
        _feed_bound=False, _display_visible=False,
        close=lambda: None,
    )
    bind_suspension(env.vr_runtime)

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

    def segment(**kwargs):
        segments.append([])

    def write_sample(row):
        sample(row)
        segments[-1].append(copy.deepcopy(row))

    def close(**kwargs):
        outcomes.append(kwargs["outcome"])
        failures.append(kwargs.get("failure"))

    module(
        monkeypatch,
        "isaac_vr_recording",
        start_live_recording=lambda *a, **kw: NS(
            sample=write_sample, close=close, segment=segment
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
            s2_reset_step=control.reset_step,
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
        segments=segments,
        failures=failures,
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
    assert r.outcomes == ["runtime_failed"]
    assert r.failures == [{"exception_type": "RuntimeError", "message": "injected successor failure"}]


def test_ctrl_c_finalizes_without_inventing_successor(record_loop):
    r = record_loop
    r.control.interrupt_step = 3
    assert r.run(3) == 130
    assert len(r.rows) == 3 and r.outcomes == ["operator_stopped"]
    assert r.validators[0].accepted_transactions == 1


def test_resume_after_inactive_gap_can_record_again(record_loop):
    r = record_loop
    r.control.inactive = {3}
    assert r.run(5) == 0
    assert r.validators[0].accepted_transactions == 2


@pytest.mark.parametrize("boundary", ["session", "reference", "reset"])
def test_epoch_change_segments_native_episode(record_loop, boundary):
    r = record_loop
    if boundary == "session":
        r.control.reconnect = {3}
    elif boundary == "reference":
        r.control.reference = {3}
    else:
        r.control.reset_step = 3
    assert r.run(5) == 0
    assert len(r.segments) == 2
    new = r.segments[1]
    assert new[0]["observation_id"] == 0 and not new[0]["action_valid"]
    for key in ("reset_epoch", "session_epoch", "control_reference_epoch"):
        assert len({int(row[key]) for row in new}) == 1
    assert any(row["action_valid"] for row in new[1:])
    assert len(r.validators) == 1
    assert r.outcomes == ["completed"]


def load_method(path, class_name, method, namespace):
    """Execute the real Kit-bound method with fake IO, rather than AST assertions."""
    tree = ast.parse((ROOT / path).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method)
    exec(compile(ast.Module([node], []), str(path), "exec"), namespace)
    return namespace[method]


def test_record_reset_does_not_require_rgb(monkeypatch):
    from test_isaac_vr_capture import environment

    env, cameras = environment(monkeypatch)
    env.reset(0)
    env.camera.live_rgb_enabled = False
    env.camera.capture.invalidate()
    state = env.reset(0)
    assert state["observation.state"].shape == (14,)
    assert env.camera.reset_epoch == 2


def test_optional_render_waits_for_async_capture(monkeypatch, tmp_path):
    from tools.isaac_vr_replay import _render_frame

    emit_capture = fake_capture_events(monkeypatch)
    loop = asyncio.new_event_loop()
    tasks = []
    reads = []

    def pixels():
        reads.append(True)
        return np.zeros((0,) if len(reads) <= 3 else (480, 640, 4), dtype=np.uint8)

    async def step(**kwargs):
        assert kwargs == {"delta_time": 0.0, "pause_timeline": True, "wait_for_render": True}
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
                get_data=pixels,
            )
        ),
        orchestrator=NS(step_async=step),
    )
    engine = module(monkeypatch, "omni.kit.async_engine", run_coroutine=schedule)
    def pump():
        emit_capture()
        loop.call_soon(loop.stop)
        loop.run_forever()

    app = module(monkeypatch, "omni.kit.app", get_app=lambda: NS(update=pump))
    kit = module(monkeypatch, "omni.kit", async_engine=engine, app=app)
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
        "outcome": "completed",
    }
    (tmp_path / "manifest.json").write_text(json.dumps(sidecar))
    rows = [_empty_d0_sample() for _ in range(3)]
    for i, row in enumerate(rows):
        row.update(
            observation_id=np.int64(i),
            observation_physics_step=np.int64(20 + i * 4),
            reset_epoch=np.int64(1),
            session_epoch=np.int64(1),
            control_reference_epoch=np.int64(1),
            observation_render_generation=np.int64(i),
        )
    rows[1].update(
        action_valid=np.uint8(1),
        transition_completed=np.uint8(1),
        action_from_observation_id=np.int64(0),
        action_to_observation_id=np.int64(1),
        action_source_physics_step=np.int64(20),
        action_source_render_generation=np.int64(0),
        control_tick_id=np.int64(1), deviceio_update_epoch=np.int64(1),
        submitted_frame_id=np.int64(1), returned_frame_id=np.int64(1),
        tracking_valid=np.ones(2, dtype=np.uint8),
    )
    groups = [
        "state/left_robot",
        "state/right_robot", "state/object_0", "state/object_1", "meta/time",
        *(f"state/camera/{r}" for r in roles),
        "d0/transition",
    ]
    events, renders = [], []
    types = {g: ("articulation" if "robot" in g else "rigid_body" if "object" in g else
                 "camera" if "camera" in g else "sim_time" if g == "meta/time" else
                 "piper_x_d0_transition_v1") for g in groups}
    tracks = [{"group": g, "type": types[g], "prim_path": f"/World/{g.replace('/', '_')}",
               "link_paths": ["/World/link"]} for g in groups]
    for track in tracks:
        if track["group"].startswith("state/camera/"):
            track["prim_path"] = roles[track["group"].split("/")[-1]]
    sidecar["recordables"] = tracks
    (tmp_path / "manifest.json").write_text(json.dumps(sidecar))
    schemas = {g: (_d0_channels(lambda **kw: NS(**kw)) if g == "d0/transition" else
                   {"marker": NS(shape=(), dtype="f4")}) for g in groups}
    track_values = {g: {"marker": np.zeros(3, np.float32)} for g in groups if g != "d0/transition"}
    module(monkeypatch, "isaacsim.replicator.episode_recorder.registry",
           rehydrate=lambda track: NS(describe_channels=lambda: schemas[track["group"]]))

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
            return NS(tracks=[t for t in tracks if t["group"] in groups])

        def episode_attrs(self, episode):
            return {"user_metadata": {"outcome": "completed"}}

        def read_group_all_frames(self, episode, group):
            if group != "d0/transition":
                return track_values[group]
            return {k: np.asarray([r[k] for r in rows]) for k in rows[0]}

    class Replayer:
        def __init__(self, path, *, pose_backend, policy):
            assert policy.strictness == "strict"
            self.prepared_recordables = [NS(group=g) for g in groups]
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
        ReplayPolicy=lambda **kw: NS(**kw),
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
        monkeypatch, "omni.replicator.core", orchestrator=NS(set_capture_on_play=lambda v: None),
        create=NS(render_product=lambda path, *a, **kw: NS(path=path, destroy=lambda: events.append("destroy"))),
        AnnotatorRegistry=NS(get_annotator=lambda name: NS(
            attach=lambda product: events.append(("attach", product.path)),
            detach=lambda: events.append("detach"))),
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

    def materialize(paths, directory, frame, **kwargs):
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
        tracks=tracks,
        track_values=track_values,
        manifest_path=tmp_path / "manifest.json",
    )


def test_snapshot_is_opened_before_replayer_and_materialization(snapshot_replay):
    r = snapshot_replay
    assert r.run() == 0
    assert (
        r.events.index("active_stage_open") < r.events.index("replayer") < r.events.index("prepare")
    )
    assert ("/exts/omni.replicator.core/Orchestrator/enabled", True) in r.events
    assert ("/omni/replicator/asyncRendering", True) in r.events
    assert r.events.count("pump") == 20
    assert [("apply", i) for i in range(3)] == [
        e for e in r.events if isinstance(e, tuple) and e[0] == "apply"
    ]
    assert [("remove", "/Render"), ("remove", "/Replicator")] == [
        e for e in r.events if isinstance(e, tuple) and e[0] == "remove"
    ]
    assert [frame for frame, paths in r.renders] == [0, 1, 2]
    assert sum(len(paths) for frame, paths in r.renders) == 9
    assert len([e for e in r.events if isinstance(e, tuple) and e[0] == "attach"]) == 3
    assert r.events.count("detach") == r.events.count("destroy") == 3


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


def test_suspension_exact_roles_prims_idempotence_and_xr_isolation(rendering_resources):
    r = rendering_resources
    xr = NS(updates_enabled=True, camera="/_xr/stage/xrCamera", quality="unchanged")
    rig = NS(wrists=(r.cameras["left_wrist"], r.cameras["right_wrist"]),
             scene_camera=r.cameras["scene"], reset_epoch=1, live_rgb_enabled=False)
    runtime = NS(camera_rig=rig, dataset_camera_suspension=None,
                 _feed_bound=False, _display_visible=False, xr=xr)
    bind_suspension(runtime)
    prims = dict(r.prims)
    first = copy.deepcopy(runtime.suspend_dataset_camera_rendering(r.stage))
    runtime.check_dataset_camera_rendering(330)
    second = runtime.suspend_dataset_camera_rendering(r.stage)
    assert second["control_steps_checked"] == 330
    assert set(second["roles"]) == set(ROLES)
    assert r.prims == prims
    for role in ROLES:
        assert first["roles"][role]["before"]["updates_enabled"]
        state = second["roles"][role]["latest"]
        assert state["camera_prim_exists"] and state["render_product_exists"]
        assert not state["updates_enabled"] and state["annotators"] == {"rgba": False}
        assert state["camera_frame"] == [0]
        assert r.cameras[role]._render_data.annotators["rgba"].detaches == [[f"/Render/{role}"]]
    assert len(r.observers) == 3
    assert {o[0]["filter"]["texture"] for o in r.observers} == set(ROLES)
    assert vars(xr) == dict(updates_enabled=True, camera="/_xr/stage/xrCamera", quality="unchanged")
    runtime.dataset_camera_suspension.close()
    assert all(not handle.active for _, handle in r.observers)
    assert all(not c._render_data.render_product.hydra_texture.updates_enabled
               for c in r.cameras.values())


@pytest.mark.parametrize("fault", ["updates", "annotator", "camera_frame",
                                   "hydra_event", "prim", "resources"])
def test_suspension_fails_closed_on_activity_or_lost_identity(rendering_resources, fault):
    r = rendering_resources
    guard = DatasetCameraSuspension(r.cameras, r.stage, reset_epoch=1)
    camera = r.cameras["scene"]
    data = camera._render_data
    if fault == "updates":
        data.render_product.hydra_texture.updates_enabled = True
    elif fault == "annotator":
        data.annotators["rgba"].node_active = True
    elif fault == "camera_frame":
        camera.frame.torch += 1
    elif fault == "hydra_event":
        r.observers[-1][0]["on_event"]({"result_handle": 99})
    elif fault == "prim":
        del r.prims["/World/scene"]
    else:
        camera._render_data = copy.copy(data)
    with pytest.raises(RuntimeError):
        guard.check(control_steps=1, reset_epoch=1)


def test_global_renderer_frame_advances_without_dataset_drawables(rendering_resources):
    r = rendering_resources
    guard = DatasetCameraSuspension(r.cameras, r.stage, reset_epoch=1)
    for camera in r.cameras.values():
        camera._render_data.render_product.hydra_texture.frame_number += 100
    report = guard.check(control_steps=25, reset_epoch=1)
    assert report["hydra_drawable_events_after_suspension"] == dict.fromkeys(ROLES, 0)


@pytest.mark.parametrize("mutation", ["extra_xr", "missing", "same_camera", "same_product"])
def test_suspension_rejects_wrong_camera_ownership(rendering_resources, mutation):
    r = rendering_resources
    if mutation == "extra_xr":
        r.cameras["xr"] = NS()
    elif mutation == "missing":
        del r.cameras["scene"]
    elif mutation == "same_camera":
        r.cameras["scene"] = r.cameras["left_wrist"]
    else:
        r.cameras["scene"]._render_data.render_product.path = "/Render/left_wrist"
    with pytest.raises(RuntimeError):
        DatasetCameraSuspension(r.cameras, r.stage, reset_epoch=0)


def test_actual_state_only_reset_after_suspension(monkeypatch, rendering_resources):
    from test_isaac_vr_capture import environment
    from tools.isaac_vr_decision import capture_state_only_observation

    env, _ = environment(monkeypatch)
    r = rendering_resources
    env.camera.wrists = (r.cameras["left_wrist"], r.cameras["right_wrist"])
    env.camera.scene_camera = r.cameras["scene"]
    for c in r.cameras.values():
        c.reset = lambda c=c: c.frame.torch.zero_()
    env.camera.live_rgb_enabled = False
    env.reset(0)
    guard = DatasetCameraSuspension(r.cameras, r.stage, reset_epoch=env.camera.reset_epoch)
    state = env.reset(0)
    assert state["observation.state"].shape == (14,)
    initial = capture_state_only_observation(env)
    guard.check(control_steps=0, reset_epoch=env.camera.reset_epoch)
    env._advance(4)
    successor = capture_state_only_observation(env)
    guard.check(control_steps=1, reset_epoch=env.camera.reset_epoch)
    assert successor.producer.physics_step - initial.producer.physics_step == 4


def test_record_performance_flags_are_admitted_without_preview_flags(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    from launch_isaac_vr import parse_args
    args = parse_args(["record", "--performance-warmup-steps", "30",
                       "--performance-window-steps", "300"])
    assert (args.performance_warmup_steps, args.performance_window_steps) == (30, 300)
    with pytest.raises(SystemExit):
        parse_args(["record", "--preview-cameras", "2"])


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


@pytest.mark.parametrize("mutation", ["missing_hash", "hdf5_hash", "failed", "aborted", "missing_manifest",
                                      "wrong_type", "short_track", "nan_world", "session_splice", "reference_splice",
                                      "five_steps", "wrong_source", "unordered_ids"])
def test_replay_fails_closed_before_stage_open(snapshot_replay, mutation):
    import json
    r = snapshot_replay
    manifest = json.loads(r.manifest_path.read_text())
    if mutation == "missing_hash":
        del manifest["stage_snapshot_sha256"]
    elif mutation == "hdf5_hash":
        manifest["hdf5_sha256"] = "0" * 64
    elif mutation in {"failed", "aborted"}:
        manifest["outcome"] = "runtime_failed" if mutation == "failed" else "aborted"
    elif mutation == "wrong_type":
        r.tracks[0]["type"] = "camera"
    elif mutation == "short_track":
        r.track_values["state/right_robot"]["marker"] = np.zeros(2, np.float32)
    elif mutation == "nan_world":
        r.track_values["state/object_0"]["marker"][1] = np.nan
    elif mutation == "session_splice":
        r.rows[1]["session_epoch"] = np.int64(2)
    elif mutation == "reference_splice":
        r.rows[1]["control_reference_epoch"] = np.int64(2)
    elif mutation == "five_steps":
        r.rows[1]["action_source_physics_step"] = np.int64(19)
    elif mutation == "wrong_source":
        r.rows[0]["observation_physics_step"] = np.int64(19)
    elif mutation == "unordered_ids":
        r.rows[2]["observation_id"] = np.int64(1)
    r.manifest_path.write_text(json.dumps(manifest))
    if mutation == "missing_manifest":
        r.manifest_path.unlink()
    with pytest.raises((RuntimeError, FileNotFoundError)):
        r.run()
    assert "active_stage_open" not in r.events


@pytest.mark.parametrize("fault", ["timeout", "exception", "physics", "no_capture"])
def test_optional_render_failure_never_reads_annotators(monkeypatch, tmp_path, fault):
    from tools import isaac_vr_replay as replay

    emit_capture = fake_capture_events(monkeypatch)
    state = NS(done=False, physics=0, cancelled=False)
    async def step(**kwargs):
        assert kwargs == {"delta_time": 0.0, "pause_timeline": True, "wait_for_render": True}
        pass

    def schedule(coro):
        coro.close()
        return NS(done=lambda: state.done, cancel=lambda: setattr(state, "cancelled", True),
                  result=lambda: (_ for _ in ()).throw(RuntimeError("render failed")) if fault == "exception" else None)

    def pump():
        if fault != "no_capture":
            emit_capture()
        if fault != "timeout":
            state.done = True
        if fault == "physics":
            state.physics += 1

    rep = module(monkeypatch, "omni.replicator.core",
                 create=NS(render_product=lambda *a, **kw: NS(destroy=lambda: None)),
                 AnnotatorRegistry=NS(get_annotator=lambda name: NS(
                     attach=lambda p: None, detach=lambda: None,
                     get_data=lambda: pytest.fail("untrusted render read"))),
                 orchestrator=NS(step_async=step))
    engine = module(monkeypatch, "omni.kit.async_engine", run_coroutine=schedule)
    app = module(monkeypatch, "omni.kit.app", get_app=lambda: NS(update=pump))
    kit = module(monkeypatch, "omni.kit", app=app, async_engine=engine)
    module(monkeypatch, "omni", kit=kit,
           replicator=module(monkeypatch, "omni.replicator", core=rep))
    times = iter([0, 1, 31])
    monkeypatch.setattr(replay.time, "monotonic", lambda: next(times))
    with pytest.raises((TimeoutError, RuntimeError)):
        replay._render_frame({"scene": "/World/camera"}, tmp_path, 0, physics_steps=lambda: state.physics)
    assert state.cancelled == (fault == "timeout")


def fake_capture_events(monkeypatch):
    callbacks = []
    dispatcher = module(monkeypatch, "carb.eventdispatcher", get_eventdispatcher=lambda: NS(
        observe_event=lambda **kw: callbacks.append(kw["on_event"]) or NS(reset=lambda: None)))
    module(monkeypatch, "carb", eventdispatcher=dispatcher)
    return lambda: [callback({"capture_id": 0}) for callback in callbacks]


def test_disconnect_reconnect_requires_new_episode_baselines(record_loop):
    r = record_loop
    r.control.disconnected = {3}
    assert r.run(6) == 0
    assert len(r.segments) == 3
    for segment in r.segments:
        assert segment[0]["observation_id"] == 0
        assert segment[0]["action_valid"] == 0
        for key in ("reset_epoch", "session_epoch", "control_reference_epoch"):
            assert len({int(row[key]) for row in segment}) == 1
    assert not any(row["action_valid"] for row in r.segments[1])
    assert any(row["action_valid"] for row in r.segments[2])
