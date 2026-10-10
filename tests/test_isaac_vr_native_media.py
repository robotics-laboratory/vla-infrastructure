"""Native media causal/ownership boundaries with CPU fakes; no Kit or CUDA."""

from contextlib import nullcontext
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from isaac_vr_native_media import NativeKitMedia
from isaac_vr_native_preview import SharedCameraPreview


class Image:
    device = SimpleNamespace(type="cuda")
    dtype = "torch.uint8"
    shape = (600, 960, 4)

    def __init__(self, role, events, *, owned=False):
        self.role, self.events, self.owned = role, events, owned

    def reshape(self, *shape):
        assert shape == self.shape
        return self

    def clone(self):
        self.events.append(("clone", self.role))
        return Image(self.role, self.events, owned=True)

    def data_ptr(self):
        return id(self)

    def is_contiguous(self):
        return True

    def numel(self):
        return 600 * 960 * 4


class Record:
    def _capture_new_observation(self):
        return self.source()


@pytest.fixture
def media(tmp_path):
    events, source = [], SimpleNamespace(seq=0, step=100, epoch=7, native=100)
    frames = {"meta/time": {"physics_step": source.step}}
    record = Record()

    def capture_source():
        events.append(("snapshot", source.seq))
        return SimpleNamespace(
            capture_sequence=source.seq,
            physics_step=source.step,
            state_generation=source.step,
            reset_epoch=source.epoch,
            state=tuple(range(14)),
            scene_state_snapshot_id=f"snapshot:{source.seq}",
            scene_state_snapshot_sha256="a" * 64,
        ), frames

    record.source = capture_source
    obj = NativeKitMedia.__new__(NativeKitMedia)
    obj.record, obj.output = record, tmp_path
    obj.env = SimpleNamespace(
        sim=SimpleNamespace(get_physics_step_count=lambda: source.step),
        camera=SimpleNamespace(reset_epoch=source.epoch),
        _state_physics_step=source.step,
        capture_measured_state=lambda: (source.step, tuple(range(14))),
    )
    obj.thread, obj.closed, obj.failed = threading.get_ident(), False, False
    obj.capture_mode, obj.marker = "pump", None
    obj.previous = record._capture_new_observation
    obj.was_owned, obj.saved_instance = False, None
    obj.rows, obj.products, obj.references = [], [], []
    obj.row_file = io.StringIO()
    obj.restored_settings = {}
    obj.partition_specs = []
    obj.consumer, obj.latest_results, obj.last_result_ids = None, {}, None
    obj.orchestrator_restore = None
    obj.initial_native_step = source.native
    obj._native_step = lambda: source.native
    settings = {"/app/player/playSimulations": True}
    obj.settings = SimpleNamespace(
        get=settings.get,
        set=lambda key, value: settings.__setitem__(key, value),
        set_bool=lambda key, value: settings.__setitem__(key, value),
    )
    obj.app = SimpleNamespace(update=lambda: events.append(("pump", settings.copy())))
    obj.rep = SimpleNamespace(
        orchestrator=SimpleNamespace(
            step=lambda **kwargs: events.append(("orchestrator", kwargs)),
        )
    )
    obj.device = SimpleNamespace(context_guard=nullcontext())
    obj.torch = SimpleNamespace(
        uint8="torch.uint8",
        cuda=SimpleNamespace(synchronize=lambda: events.append(("fence",))),
        from_dlpack=lambda data: data,
    )
    obj.annotators, obj.encoders = [], []
    borrowed, encoded, previewed = {}, {}, {}
    for role in ("left_wrist", "right_wrist", "scene"):
        borrowed[role] = Image(role, events)

        def get_data(role=role):
            events.append(("extract", role))
            return {"data": borrowed[role]}

        def submit(frame, tag, role=role):
            events.append(("encode", role, tag))
            encoded[role] = frame

        obj.annotators.append(SimpleNamespace(get_data=get_data, detach=lambda paths: None))
        obj.encoders.append(SimpleNamespace(submit=submit, finish=lambda: {"passed": True}))

    def preview_publish(tag, images):
        events.append(("preview", tag))
        previewed.update(images)

    obj.preview = SimpleNamespace(publish=preview_publish, close=lambda: None, publications=0)
    record._capture_new_observation = obj.capture
    return SimpleNamespace(
        obj=obj,
        source=source,
        events=events,
        borrowed=borrowed,
        encoded=encoded,
        previewed=previewed,
        settings=settings,
        frames=frames,
    )


def test_capture_freezes_before_consumers_and_preserves_source_frame(media):
    token, frames = media.obj.capture()
    events = media.events
    names = [event[0] for event in events]
    assert names.index("snapshot") < names.index("pump") < names.index("extract")
    assert max(i for i, name in enumerate(names) if name == "clone") < names.index("encode")
    assert max(i for i, name in enumerate(names) if name == "encode") < names.index("preview")
    assert names.count("pump") == 1
    assert frames is media.frames
    assert token.capture_sequence == 0
    for role, owner in media.previewed.items():
        assert owner.owned
        assert owner is not media.borrowed[role]
        assert media.encoded[role].owner is owner
    row = json.loads(media.obj.row_file.getvalue())
    assert (row["source_id"], row["physics_step"], row["snapshot_id"]) == (0, 100, "snapshot:0")
    assert row["snapshot_sha256"] == token.scene_state_snapshot_sha256
    assert row["optical_alignment_proven"] is False


@pytest.mark.parametrize("bad_source", [0, 2])
def test_repeated_or_skipped_source_never_reaches_media_consumers(media, bad_source):
    media.obj.capture()
    media.source.seq = bad_source
    media.events.clear()
    with pytest.raises(RuntimeError, match="source boundary"):
        media.obj.capture()
    assert [event[0] for event in media.events] == ["snapshot"]
    assert len(media.obj.rows) == 1


@pytest.mark.parametrize("mode", ["pump", "orchestrator"])
def test_camera_pump_holds_physics_and_restores_player_setting(media, mode):
    media.obj.capture_mode = mode
    media.obj._pump()
    assert media.settings["/app/player/playSimulations"] is True
    assert media.source.native == 100
    event, value = media.events[-1]
    if mode == "pump":
        assert event == "pump"
        assert value["/app/player/playSimulations"] is False
    else:
        assert event == "orchestrator"
        assert value == dict(
            delta_time=0.0, pause_timeline=False, rt_subframes=1, wait_for_render=True
        )


def test_physics_advance_inside_pump_rejects_without_encoding(media):
    media.obj.app.update = lambda: setattr(media.source, "native", media.source.native + 1)
    with pytest.raises(RuntimeError, match="physics advanced"):
        media.obj.capture()
    assert media.settings["/app/player/playSimulations"] is True
    assert not media.encoded
    assert not media.previewed
    assert not media.obj.rows


def test_pump_error_restores_player_setting(media):
    def fail():
        raise RuntimeError("render failed")

    media.obj.app.update = fail
    with pytest.raises(RuntimeError, match="render failed"):
        media.obj._pump()
    assert media.settings["/app/player/playSimulations"] is True


def test_source_clock_change_during_capture_is_rejected(media):
    # External CPU clock can change without advancing the main Kit counter.
    media.obj.app.update = lambda: setattr(media.source, "step", media.source.step + 4)
    with pytest.raises(RuntimeError):
        media.obj.capture()
    assert not media.encoded
    assert not media.previewed


def test_wrong_cuda_device_is_rejected_before_encoding(media):
    media.borrowed["left_wrist"].device = SimpleNamespace(type="cuda", index=1)
    with pytest.raises(RuntimeError, match="CUDA RGBA8 producer"):
        media.obj.capture()
    assert not media.encoded


def test_callback_uses_completed_owned_results_without_pumping_or_polling(media):
    media.obj.consumer = SimpleNamespace(raise_if_failed=lambda: None)
    media.obj.latest_results = {
        role: dict(rgba=Image(role, media.events, owned=True), frame_identifier={"frameNumber": 63}, native_format=11)
        for role in media.borrowed
    }
    media.obj.capture()
    assert not any(e[0] in ("pump", "extract", "clone") for e in media.events)
    assert all(frame.owner is media.obj.latest_results[role]["rgba"]
               for role, frame in media.encoded.items())
    media.source.seq = 1
    with pytest.raises(RuntimeError, match="did not advance"):
        media.obj.capture()


def test_callback_roles_with_different_render_result_identities_are_rejected(media):
    media.obj.consumer = SimpleNamespace(raise_if_failed=lambda: None)
    media.obj.latest_results = {
        role: dict(rgba=Image(role, media.events, owned=True), frame_identifier={"frameNumber": i}, native_format=11)
        for i, role in enumerate(media.borrowed)
    }
    with pytest.raises(RuntimeError, match="different result identities"):
        media.obj.capture()
    assert not media.encoded and not media.previewed


@pytest.mark.parametrize("change", ["epoch", "state_generation"])
def test_source_epoch_or_state_generation_change_is_rejected(media, change):
    def mutate():
        if change == "epoch":
            media.obj.env.camera.reset_epoch += 1
        else:
            media.obj.env._state_physics_step += 4

    media.obj.app.update = mutate
    with pytest.raises(RuntimeError):
        media.obj.capture()
    assert not media.encoded
    assert not media.previewed


@pytest.mark.parametrize("instance_override", [False, True])
def test_close_restores_inherited_or_preexisting_capture_and_is_idempotent(
    media, instance_override
):
    def previous():
        return "observer before native media"

    media.obj.was_owned = instance_override
    media.obj.saved_instance = previous if instance_override else None
    media.obj.restored_settings["diagnostic_setting"] = "original"
    media.settings["diagnostic_setting"] = "changed"
    receipt = media.obj.close()
    assert media.obj.closed
    assert media.settings["diagnostic_setting"] == "original"
    if instance_override:
        assert media.obj.record._capture_new_observation is previous
    else:
        assert "_capture_new_observation" not in vars(media.obj.record)
        assert media.obj.record._capture_new_observation()[0].capture_sequence == 0
    assert receipt["snapshot_renderer_used"] is False
    assert receipt["dataset_admissible"] is False
    assert media.obj.close() == receipt


def test_cleanup_failure_still_releases_other_resources_and_restores_settings(media):
    events = media.events

    def preview_failure():
        events.append(("preview_close",))
        raise RuntimeError("preview release failed")

    media.obj.preview.close = preview_failure
    media.obj.products = [
        SimpleNamespace(
            path=f"/product/{role}", destroy=lambda role=role: events.append(("destroy", role))
        )
        for role in range(3)
    ]
    media.obj.restored_settings["diagnostic_setting"] = "original"
    media.settings["diagnostic_setting"] = "changed"
    with pytest.raises(RuntimeError):
        media.obj.close()
    assert media.obj.closed
    assert media.obj.row_file.closed
    assert media.settings["diagnostic_setting"] == "original"
    assert sum(event[0] == "destroy" for event in events) == 3
    assert "_capture_new_observation" not in vars(media.obj.record)


@pytest.fixture
def preview(monkeypatch):
    from types import ModuleType

    scene = ModuleType("omni.ui.scene")
    scene.Widget = SimpleNamespace(UpdatePolicy=SimpleNamespace(ON_DEMAND="on-demand"))
    monkeypatch.setitem(sys.modules, "omni.ui.scene", scene)
    obj = SharedCameraPreview.__new__(SharedCameraPreview)
    obj.thread = threading.get_ident()
    obj.closed = obj.failed = False
    obj.visible = True
    obj.last_source_id = None
    obj.publications = obj.bytes = 0
    obj.retained, obj.previous, obj.panels = {}, {}, {}
    uploaded, invalidated = {}, []
    for role in ("left_wrist", "right_wrist", "scene"):
        widget = SimpleNamespace(invalidate=lambda role=role: invalidated.append(role))
        obj.panels[role] = SimpleNamespace(
            upload=lambda image, role=role: uploaded.__setitem__(role, image),
            _component=SimpleNamespace(scene_widget=widget),
        )
    obj.sizes = {role: (960, 600) for role in obj.panels}
    images = {role: Image(role, [], owned=True) for role in obj.panels}
    return SimpleNamespace(obj=obj, images=images, uploaded=uploaded, invalidated=invalidated)


def test_preview_uploads_exact_owners_without_acquisition_or_frame_callbacks(preview):
    preview.obj.publish(0, preview.images)
    assert len(preview.invalidated) == 3
    assert preview.obj.publications == 1
    assert preview.obj.bytes == 3 * 960 * 600 * 4
    for role in preview.images:
        assert preview.uploaded[role] is preview.images[role]
        assert preview.obj.retained[role] is preview.images[role]


def test_preview_repeated_source_does_not_upload_twice(preview):
    preview.obj.publish(0, preview.images)
    preview.uploaded.clear()
    with pytest.raises(ValueError, match="strictly increase"):
        preview.obj.publish(0, preview.images)
    assert not preview.uploaded
    assert preview.obj.publications == 1


def test_preview_validates_all_roles_before_uploading_any(preview):
    preview.images["scene"].device = SimpleNamespace(type="cpu")
    with pytest.raises(ValueError, match="CUDA"):
        preview.obj.publish(0, preview.images)
    assert not preview.uploaded
    assert preview.obj.last_source_id is None


def test_hidden_preview_advances_source_without_upload_or_widget_draw(preview):
    preview.obj.visible = False
    preview.obj.publish(0, preview.images)
    assert not preview.uploaded
    assert not preview.invalidated
    assert preview.obj.last_source_id == 0
    assert preview.obj.publications == 0
    assert preview.obj.retained["scene"] is preview.images["scene"]


def test_partial_preview_upload_failure_poisoned_until_close(preview):
    def fail(image):
        raise RuntimeError("provider failed")

    preview.obj.panels["right_wrist"].upload = fail
    with pytest.raises(RuntimeError, match="provider failed"):
        preview.obj.publish(0, preview.images)
    assert preview.obj.failed
    with pytest.raises(RuntimeError, match="healthy"):
        preview.obj.publish(1, preview.images)
