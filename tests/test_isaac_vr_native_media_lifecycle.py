"""CPU lifecycle checks: one camera session, independently drained recording episodes."""
from collections import OrderedDict
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from test_isaac_vr_native_media import Image, media as media_fixture

from isaac_vr_native_binding import ROLES
from isaac_vr_native_media import NativeKitMedia

media = media_fixture


@pytest.fixture
def detached(media, monkeypatch):
    obj, events = media.obj, media.events
    record = obj.record
    obj.source_binding = obj.binding_hdf = obj.source_proof = None
    obj.stop_recording()
    obj.source_epoch = media.source.epoch
    obj.bind_sources = False
    obj.binding_options = dict(clock_only=False, attribute_only=False, identity_only=False)
    obj.boundary_count = 0
    obj.episode_receipts = []
    obj.device.context = 123
    obj.stream = SimpleNamespace(cuda_stream=456)
    obj.fences = SimpleNamespace(stream=lambda stream: None)

    class Encoder:
        def __init__(self, output, **kwargs):
            self.output = Path(output)
            self.tags = []
            events.append(("encoder_open", str(output)))

        def submit(self, frame, tag):
            self.tags.append(tag)
            events.append(("encode", tag))

        def finish(self):
            events.append(("drain", str(self.output)))
            return dict(passed=True, tags=list(self.tags))

    import isaac_vr_live_nvenc
    monkeypatch.setattr(isaac_vr_live_nvenc, "PacketEncoder", Encoder)
    media.record = record
    return media


def test_detached_preview_never_samples_snapshot_or_opens_recording(detached):
    obj = detached.obj
    detached.events.clear()
    obj.capture_boundary()
    assert obj.record is None and not obj.encoders
    assert obj.source_binding is None and obj.binding_hdf is None
    assert not any(e[0] in ("snapshot", "encode", "encoder_open") for e in detached.events)
    assert [e[0] for e in detached.events].count("preview") == 1


def test_two_episodes_keep_one_camera_preview_and_restart_packet_ordinals(detached, tmp_path):
    obj = detached.obj
    preview, products = obj.preview, obj.products
    obj.capture_boundary()
    for episode in range(2):
        detached.source.seq = 0
        output = tmp_path / f"episode{episode}"
        obj.start_recording(detached.record, output)
        obj.capture()
        receipt = obj.stop_recording()
        assert receipt["encoded_packets"] == 1
        assert all(e["tags"] == [0] for e in receipt["encoders"])
        assert "_capture_new_observation" not in vars(detached.record)
        assert obj.preview is preview and obj.products is products
        assert not obj.closed and obj.record is None and not obj.encoders
        assert (output / "frames.jsonl").exists()
        obj.capture_boundary()
    tags = [e[1] for e in detached.events if e[0] == "preview"]
    assert tags == sorted(set(tags))
    assert len(obj.episode_receipts) == 2


def test_episode_drain_failure_detaches_and_preserves_camera_until_shutdown(detached, tmp_path):
    obj = detached.obj
    obj.start_recording(detached.record, tmp_path / "bad")
    def fail():
        raise RuntimeError("NVENC drain failed")
    obj.encoders[0].finish = fail
    with pytest.raises(RuntimeError, match="NVENC drain failed"):
        obj.stop_recording()
    assert obj.failed and not obj.closed and obj.record is None
    assert obj.preview is not None
    assert len([e for e in detached.events if e[0] == "drain"]) == 2
    assert obj.row_file.closed
    assert "_capture_new_observation" not in vars(detached.record)
    with pytest.raises(RuntimeError, match="Kit owner"):
        obj.capture_boundary()
    obj.close()
    assert obj.closed


def test_reset_is_explicit_detached_and_does_not_replace_native_clock(detached, tmp_path):
    obj = detached.obj
    history = OrderedDict([(1, {"source": {"reset_epoch": -1}})])
    obj.source_proof = SimpleNamespace(history=history)
    detached.source.epoch += 1
    obj.env.camera.reset_epoch = detached.source.epoch
    with pytest.raises(RuntimeError, match="reset_source_epoch"):
        obj.start_recording(detached.record, tmp_path / "premature")
    obj.latest_results["scene"] = {"stale": True}
    obj.reset_source_epoch()
    assert not history and not obj.latest_results
    assert obj.source_proof.history is history
    obj.start_recording(detached.record, tmp_path / "fresh")
    with pytest.raises(RuntimeError, match="Detach recording"):
        obj.reset_source_epoch()
    obj.stop_recording()


def source_results(media, step, publication, *, epoch=None):
    epoch = media.source.epoch if epoch is None else epoch
    return {role: dict(
        rgba=Image(role, media.events, owned=True),
        frame_identifier={"frameNumber": publication}, native_format=11,
        source_proof=dict(role=role, geometry_matched=True, compared_bodies=1,
                          publication_id=publication, reset_epoch=epoch, physics_step=step,
                          frame_identifier={"frameNumber": publication},
                          failed_paths=[], unresolved=False),
    ) for role in ROLES}


@pytest.fixture
def binding_hdf(monkeypatch):
    import numpy as np
    files = {}
    class Attrs(dict):
        def modify(self, key, value):
            self[key] = value
    class Table:
        def __init__(self, dtype):
            self.dtype, self.rows = dtype, np.empty((0,), dtype=dtype)
        def resize(self, shape):
            previous = self.rows
            self.rows = np.empty(shape, dtype=self.dtype)
            self.rows[:len(previous)] = previous
        def __setitem__(self, index, value):
            self.rows[index] = value
        def __getitem__(self, index):
            return self.rows[index]
    class Hdf:
        def __init__(self, path, *args, **kwargs):
            self.attrs, self.closed = Attrs(), False
            files[Path(path)] = self
        def create_dataset(self, name, *, dtype, **kwargs):
            self.table = Table(dtype)
            return self.table
        def flush(self):
            pass
        def close(self):
            self.closed = True
        def __getitem__(self, name):
            return self.table
    monkeypatch.setitem(sys.modules, "h5py", SimpleNamespace(File=Hdf))
    return files


def test_binding_warmup_skips_only_pre_episode_sources_and_joins_actual_snapshot(detached, tmp_path, binding_hdf):
    obj = detached.obj
    obj.bind_sources = True
    obj.source_proof = SimpleNamespace(history=OrderedDict())
    obj.consumer = SimpleNamespace(raise_if_failed=lambda: None)
    obj.start_recording(detached.record, tmp_path / "bound")
    obj.latest_results = source_results(detached, 96, 1)
    obj.capture()
    assert obj.capture_count == 1 and obj.encoded_count == 0 and obj.warmup_skips == 1
    assert not any(e[0] == "encode" for e in detached.events)
    detached.source.seq, detached.source.step = 1, 104
    obj.env._state_physics_step = 104
    obj.latest_results = source_results(detached, 100, 2)
    obj.capture()
    assert obj.encoded_count == 1
    rows = [json.loads(line) for line in (tmp_path / "bound/frames.jsonl").read_text().splitlines()]
    assert rows[0]["coverage"] == "pre_episode_source_skipped"
    assert rows[1]["camera_source_binding"]["actual_capture_sequence"] == 0
    assert rows[1]["camera_source_binding"]["current_capture_sequence"] == 1
    assert rows[1]["camera_source_binding"]["observed_lag_physics_steps"] == 4
    receipt = obj.stop_recording()
    assert receipt["encoded_packets"] == 1 and receipt["warmup_skips"] == 1
    hdf = binding_hdf[tmp_path / "bound/camera_bindings.hdf5"]
    assert hdf.closed and hdf.attrs["committed_rows"] == 1
    row = hdf["bindings"][0]
    assert row["packet_ordinal"] == row["actual_capture_sequence"] == 0
    assert row["physics_step"] == 100


@pytest.mark.parametrize("corruption", ["epoch", "role", "future", "unresolved", "no_exact_snapshot"])
def test_rendered_mismatch_never_encodes(detached, tmp_path, corruption, binding_hdf):
    obj = detached.obj
    obj.bind_sources = True
    obj.source_proof = SimpleNamespace(history=OrderedDict())
    obj.consumer = SimpleNamespace(raise_if_failed=lambda: None)
    obj.start_recording(detached.record, tmp_path / corruption)
    obj.latest_results = source_results(detached, 100, 1)
    if corruption == "epoch":
        for result in obj.latest_results.values():
            result["source_proof"]["reset_epoch"] += 1
    elif corruption == "role":
        obj.latest_results["scene"]["source_proof"]["publication_id"] += 1
    elif corruption == "future":
        for result in obj.latest_results.values():
            result["source_proof"]["physics_step"] = 104
    elif corruption == "unresolved":
        obj.latest_results["scene"]["source_proof"]["unresolved"] = True
    else:
        # Retain observations at 100 and 108, but no observation at rendered 104.
        obj.latest_results = source_results(detached, 96, 1)
        obj.capture()
        detached.source.seq, detached.source.step = 1, 108
        obj.env._state_physics_step = 108
        obj.latest_results = source_results(detached, 104, 2)
    with pytest.raises((RuntimeError, ValueError)):
        obj.capture()
    assert not any(e[0] == "encode" for e in detached.events)
    assert obj.failed


def test_detached_constructor_allocates_no_encoder_or_recording_hdf(monkeypatch, tmp_path):
    """Exercise the public constructor with SDK-shaped CPU fakes."""
    events = []
    settings_values = {}
    settings = SimpleNamespace(get=settings_values.get, set=settings_values.__setitem__)
    def product(path, size, name):
        return SimpleNamespace(path=f"/Render/{name}", destroy=lambda: None)
    rep = SimpleNamespace(create=SimpleNamespace(render_product=product),
        AnnotatorRegistry=SimpleNamespace(get_annotator=lambda *a, **k: SimpleNamespace(
            attach=lambda paths: None, detach=lambda paths: None)))
    stage = SimpleNamespace(GetRootLayer=lambda: SimpleNamespace(identifier="stage"),
        GetPrimAtPath=lambda path: SimpleNamespace(GetAppliedSchemas=lambda: [], GetAttributes=lambda: []))
    app = SimpleNamespace(update=lambda: events.append("pump"))
    kit_app = SimpleNamespace(get_app=lambda: app)
    usd = SimpleNamespace(get_context=lambda: SimpleNamespace(get_stage=lambda: stage))
    for name, module in {
        "carb": SimpleNamespace(settings=SimpleNamespace(get_settings=lambda: settings)),
        "omni": SimpleNamespace(kit=SimpleNamespace(app=kit_app),
                                replicator=SimpleNamespace(core=rep), usd=usd),
        "omni.kit": SimpleNamespace(app=kit_app), "omni.kit.app": kit_app,
        "omni.replicator": SimpleNamespace(core=rep), "omni.replicator.core": rep,
        "omni.usd": usd, "torch": SimpleNamespace(),
        "warp": SimpleNamespace(get_device=lambda device: SimpleNamespace(context_guard=nullcontext()),
                                Stream=lambda device: SimpleNamespace()),
        "isaac_vr_live_gpu": SimpleNamespace(_CheckedCudaFences=lambda: SimpleNamespace()),
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(NativeKitMedia, "_native_step", lambda self: 0)
    monkeypatch.setattr(NativeKitMedia, "_pump", lambda self: events.append("setup_pump"))
    import isaac_vr_live_nvenc
    monkeypatch.setattr(isaac_vr_live_nvenc, "PacketEncoder", lambda *a, **k: pytest.fail("encoder opened"))
    env = SimpleNamespace(camera=SimpleNamespace(reset_epoch=0,
        camera_prim_paths=dict(zip(ROLES, ("/left", "/right", "/scene")))))
    obj = NativeKitMedia(None, env, tmp_path / "session", preview=False)
    assert obj.record is None and not obj.encoders and obj.binding_hdf is None
    assert not (obj.output / "frames.jsonl").exists()
    assert not list(obj.output.glob("*.hdf5"))
    obj.close()


def test_partial_attach_failure_restores_capture_and_drains_every_opened_encoder(detached, tmp_path, monkeypatch):
    def fail():
        raise RuntimeError("binding table creation failed")
    monkeypatch.setattr(detached.obj, "_open_bindings", fail)
    with pytest.raises(RuntimeError, match="binding table creation failed"):
        detached.obj.start_recording(detached.record, tmp_path / "partial")
    assert detached.obj.failed and detached.obj.record is None
    assert "_capture_new_observation" not in vars(detached.record)
    assert len([e for e in detached.events if e[0] == "drain"]) == 3
    assert detached.obj.row_file.closed


def test_capture_hook_interference_is_retained_reported_and_episode_drained(detached, tmp_path):
    obj = detached.obj
    obj.start_recording(detached.record, tmp_path / "ownership")
    def foreign():
        return "another observer"
    detached.record._capture_new_observation = foreign
    with pytest.raises(RuntimeError, match="Another owner"):
        obj.stop_recording()
    assert detached.record._capture_new_observation is foreign
    assert len([e for e in detached.events if e[0] == "drain"]) == 3
    assert obj.record is None and obj.failed


def test_reset_preserves_already_rendered_new_epoch_settling_publications(detached):
    obj = detached.obj
    old = source_results(detached, 100, 1)["scene"]
    detached.source.epoch += 1
    obj.env.camera.reset_epoch = detached.source.epoch
    current = source_results(detached, 120, 2)["left_wrist"]
    obj.latest_results = {"scene": old, "left_wrist": current}
    history = OrderedDict((i, dict(source=dict(reset_epoch=epoch)))
                          for i, epoch in [(1, detached.source.epoch - 1), (2, detached.source.epoch)])
    obj.source_proof = SimpleNamespace(history=history)
    obj.reset_source_epoch()
    assert list(history) == [2]
    assert obj.latest_results == {"left_wrist": current}


def test_detached_callback_preview_does_not_pump_or_resample(detached):
    obj = detached.obj
    obj.consumer = SimpleNamespace(raise_if_failed=lambda: None)
    obj.latest_results = source_results(detached, 100, 1)
    detached.events.clear()
    obj.capture_boundary()
    obj.capture_boundary()  # Same completed render cannot publish twice.
    assert [e[0] for e in detached.events] == ["preview", "fence"]
    assert obj.boundary_count == 1
    assert not obj.encoders and obj.record is None


@pytest.mark.parametrize('bind_sources', [False, True])
@pytest.mark.parametrize('source_step', [96, 100])
def test_initial_observation_can_reuse_preview_triplet_across_two_episodes(detached, tmp_path, binding_hdf, bind_sources, source_step):
    obj = detached.obj
    obj.consumer = SimpleNamespace(raise_if_failed=lambda: None)
    obj.bind_sources = bind_sources
    if bind_sources:
        obj.source_proof = SimpleNamespace(history=OrderedDict())
    # Last ordinary RUN boundary has already consumed these completed results.
    obj.latest_results = source_results(detached, source_step, 42)
    obj.capture_boundary()
    identifiers = obj.last_result_ids
    for index in range(2):
        detached.source.seq = 0
        obj.start_recording(detached.record, tmp_path / f'reuse-{index}')
        assert obj.last_result_ids == identifiers
        detached.events.clear()
        token, _ = obj.capture()
        assert token.capture_sequence == 0
        assert obj.capture_count == 1
        assert not any(event[0] in ('pump', 'orchestrator', 'extract', 'clone')
                       for event in detached.events)
        assert obj.rows[-1]['native_result_identifiers'] == identifiers
        if bind_sources and source_step < 100:
            assert obj.rows[-1]['coverage'] == 'pre_episode_source_skipped'
            assert obj.rows[-1]['camera_source_binding'] is None
            assert obj.encoded_count == 0 and obj.warmup_skips == 1
            assert not any(event[0] == 'encode' for event in detached.events)
        else:
            assert obj.encoded_count == 1
            assert [event for event in detached.events if event[0] == 'encode'] == [('encode', 0)] * 3
        if bind_sources and source_step == 100:
            binding = obj.rows[-1]['camera_source_binding']
            assert binding['actual_capture_sequence'] == binding['packet_ordinal'] == 0
            assert binding['physics_step'] == 100
        obj.stop_recording()
    assert not obj.closed and not obj.failed


@pytest.mark.parametrize('bind_sources', [False, True])
def test_noninitial_episode_observation_still_rejects_same_completed_result(detached, tmp_path, binding_hdf, bind_sources):
    obj = detached.obj
    obj.consumer = SimpleNamespace(raise_if_failed=lambda: None)
    obj.bind_sources = bind_sources
    if bind_sources:
        obj.source_proof = SimpleNamespace(history=OrderedDict())
    obj.latest_results = source_results(detached, 96, 42)
    obj.capture_boundary()
    obj.start_recording(detached.record, tmp_path / 'noninitial')
    obj.capture()
    detached.source.seq, detached.source.step = 1, 104
    obj.env._state_physics_step = 104
    detached.events.clear()
    with pytest.raises(RuntimeError, match='did not advance'):
        obj.capture()
    assert not any(event[0] in ('encode', 'preview', 'pump') for event in detached.events)
    assert obj.failed


def test_initial_episode_capture_cannot_regress_lifetime_render_identity(detached, tmp_path):
    obj = detached.obj
    obj.consumer = SimpleNamespace(raise_if_failed=lambda: None)
    obj.latest_results = source_results(detached, 100, 42)
    obj.capture_boundary()
    obj.start_recording(detached.record, tmp_path / 'regressed')
    obj.latest_results = source_results(detached, 100, 41)
    detached.events.clear()
    with pytest.raises(RuntimeError, match='identity regressed'):
        obj.capture()
    assert not any(event[0] in ('encode', 'preview', 'pump') for event in detached.events)


def test_no_proof_reset_keeps_completed_settling_triplet_without_claiming_source_identity(detached, tmp_path):
    obj = detached.obj
    obj.consumer = SimpleNamespace(raise_if_failed=lambda: None)
    obj.latest_results = source_results(detached, 100, 42)
    for result in obj.latest_results.values():
        del result['source_proof']
    obj.capture_boundary()
    settled = obj.latest_results
    # The canonical env.reset has already settled/rendered before acknowledgment.
    detached.source.epoch += 1
    obj.env.camera.reset_epoch = detached.source.epoch
    obj.reset_source_epoch()
    assert obj.latest_results is settled and obj.last_result_ids is None
    assert obj.source_epoch == detached.source.epoch
    obj.start_recording(detached.record, tmp_path / 'unproven-settled')
    obj.capture()
    row = obj.rows[-1]
    assert row['camera_source_binding'] is None
    assert all(value is None for value in row['rendered_source_proof'].values())
    assert row['optical_alignment_proven'] is False
    assert obj.source_binding is None and obj.encoded_count == 1


def test_no_proof_epoch_change_without_acknowledgment_still_rejects_capture(detached):
    obj = detached.obj
    obj.consumer = SimpleNamespace(raise_if_failed=lambda: None)
    obj.latest_results = source_results(detached, 100, 42)
    for result in obj.latest_results.values():
        del result['source_proof']
    detached.source.epoch += 1
    obj.env.camera.reset_epoch = detached.source.epoch
    detached.events.clear()
    with pytest.raises(RuntimeError, match='reset_source_epoch'):
        obj.capture_boundary()
    assert not detached.events
    assert obj.failed
