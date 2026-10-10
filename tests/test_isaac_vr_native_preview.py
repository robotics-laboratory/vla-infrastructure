"""CPU-only boundary tests: exact image ownership and upstream panel lifecycle."""

import gc
import sys
import threading
from types import ModuleType, SimpleNamespace
import weakref

import pytest

from tools.isaac_vr_native_preview import SharedCameraPreview


class FakeImage:
    def __init__(
        self, *, device="cuda", index=0, dtype="torch.uint8", shape=(600, 960, 4), contiguous=True
    ):
        self.device = SimpleNamespace(type=device, index=index)
        self.dtype, self.shape, self.contiguous = dtype, shape, contiguous

    def is_contiguous(self):
        return self.contiguous

    def numel(self):
        return 600 * 960 * 4


@pytest.fixture
def api(monkeypatch):
    state = SimpleNamespace(events=[], panels=[], create_error_at=None, upload_error_role=None)

    class Config(SimpleNamespace):
        pass

    class Panel:
        def __init__(self, descriptor):
            self.role = descriptor.camera_name
            self.closed = False
            self._container = SimpleNamespace(
                show=lambda: state.events.append(("show", self.role)),
                hide=lambda: state.events.append(("hide", self.role)),
            )
            self._component = SimpleNamespace(
                width=0.36,
                scene_widget=SimpleNamespace(
                    update_policy=None,
                    invalidate=lambda: state.events.append(("invalidate", self.role)),
                ),
            )

        def upload(self, image):
            # Store identity without owning the source so retention tests are real.
            state.events.append(("upload", self.role, id(image)))
            if self.role == state.upload_error_role:
                raise RuntimeError("provider upload failed")

        def close(self):
            state.events.append(("close", self.role))
            self.closed = True

    class Presenter:
        def create_panel(self, descriptor, width, height):
            if len(state.panels) == state.create_error_at:
                raise RuntimeError("panel creation failed")
            panel = Panel(descriptor)
            state.panels.append(panel)
            state.events.append(("create", descriptor.camera_name, width, height))
            return panel

    modules = {
        "isaaclab_teleop.camera_feed": {
            "_layout_feed_cfgs": lambda configs, sizes, layout: configs,
            "_panel_descriptor": lambda config, layout: config,
        },
        "isaaclab_teleop.camera_feed_kit_scene_ui": {"_KitSceneUiCameraFeedPresenter": Presenter},
        "isaaclab_teleop.isaac_teleop_cfg": {
            "XrCameraFeedCfg": Config,
            "XrCameraFeedLayoutCfg": Config,
        },
        "omni.ui.scene": {
            "Widget": SimpleNamespace(UpdatePolicy=SimpleNamespace(ON_DEMAND="on_demand"))
        },
    }
    for name, attributes in modules.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)
    state.isolation = SimpleNamespace(
        check_panel=lambda panel: state.events.append(("check", panel.role)),
        release_panel=lambda panel: state.events.append(("release", panel.role)),
    )
    return state


@pytest.fixture
def config():
    return {
        "vr_camera_feeds": {
            "order": ["left_wrist", "demo_scene", "right_wrist"],
            "layout": {
                "mode": "horizontal",
                "placement": "head_locked",
                "center_offset_m": [0.0, 0.1],
                "distance_m": 0.65,
                "panel_width_m": 0.36,
                "panel_gap_m": 0.035,
                "max_update_hz": 30.0,
            },
        },
        "cameras": {role: {"width": 960, "height": 600} for role in ("wrist", "scene")},
    }


def triplet(**overrides):
    return {role: FakeImage(**overrides) for role in ("left_wrist", "scene", "right_wrist")}


def uploads(api):
    return [event for event in api.events if event[0] == "upload"]


def test_upstream_panels_receive_exact_completed_owned_images(api, config):
    owner = SharedCameraPreview(config, isolation=api.isolation)
    images = triplet()
    owner.publish(5, images)
    assert uploads(api) == [
        ("upload", name, id(images[role]))
        for role, name in (
            ("left_wrist", "left_wrist"),
            ("scene", "demo_scene"),
            ("right_wrist", "right_wrist"),
        )
    ]
    assert owner.last_source_id == 5
    assert owner.publications == 1 and owner.bytes == 6_912_000
    assert owner.retained == images
    assert all(panel._component.resolution_scale == 1.0 for panel in api.panels)
    assert all(panel._component.unit_to_pixel_scale == 960 / 0.36 for panel in api.panels)
    assert all(panel._component.scene_widget.update_policy == "on_demand" for panel in api.panels)
    owner.close()


def test_source_allocations_retained_across_replacement_then_released(api, config):
    owner = SharedCameraPreview(config)
    first = triplet()
    refs = [weakref.ref(image) for image in first.values()]
    owner.publish(0, first)
    first.clear()
    gc.collect()
    assert all(ref() is not None for ref in refs)
    owner.publish(1, triplet())
    gc.collect()
    assert all(ref() is not None for ref in refs)
    owner.publish(2, triplet())
    gc.collect()
    assert all(ref() is None for ref in refs)
    current = [weakref.ref(image) for image in owner.retained.values()]
    owner.close()
    gc.collect()
    assert all(ref() is None for ref in current)


def test_hidden_preview_skips_provider_and_invalidation_then_resumes(api, config):
    owner = SharedCameraPreview(config, isolation=api.isolation, visible=False)
    owner.publish(0, triplet())
    assert not uploads(api) and owner.publications == owner.bytes == 0
    assert not any(event[0] == "invalidate" for event in api.events)
    owner.set_visible(True)
    owner.publish(1, triplet())
    assert len(uploads(api)) == 3 and owner.publications == 1
    for panel in api.panels:
        assert ("hide", panel.role) in api.events
        assert ("release", panel.role) in api.events
        assert api.events.index(("show", panel.role)) < api.events.index(("check", panel.role))
    owner.close()


@pytest.mark.parametrize("source_id", [1, 0, -1, True, 2.0])
def test_invalid_duplicate_and_regressing_sources_do_not_upload(api, config, source_id):
    owner = SharedCameraPreview(config)
    owner.publish(1, triplet())
    with pytest.raises(ValueError, match="source ID"):
        owner.publish(source_id, triplet())
    assert len(uploads(api)) == 3 and owner.last_source_id == 1
    owner.close()


@pytest.mark.parametrize(
    "bad_image",
    [
        {"device": "cpu"},
        {"dtype": "torch.float32"},
        {"shape": (600, 960, 3)},
        {"shape": (1, 600, 960, 4)},
        {"contiguous": False},
    ],
)
def test_invalid_role_is_rejected_before_any_partial_triplet_upload(api, config, bad_image):
    owner = SharedCameraPreview(config)
    images = triplet()
    images["right_wrist"] = FakeImage(**bad_image)
    with pytest.raises(ValueError, match="RGBA8"):
        owner.publish(0, images)
    assert not uploads(api) and owner.last_source_id is None
    owner.close()


def test_mixed_cuda_devices_are_rejected_before_provider_calls(api, config):
    owner = SharedCameraPreview(config)
    images = triplet()
    images["right_wrist"] = FakeImage(index=1)
    with pytest.raises(ValueError, match="device|GPU|CUDA"):
        owner.publish(0, images)
    assert not uploads(api)
    owner.close()


def test_missing_role_does_not_partially_publish(api, config):
    owner = SharedCameraPreview(config)
    images = triplet()
    del images["scene"]
    with pytest.raises(ValueError, match="three-role"):
        owner.publish(0, images)
    assert not uploads(api)
    owner.close()


def test_upload_failure_fails_closed_and_keeps_potentially_borrowed_images(api, config):
    owner = SharedCameraPreview(config)
    images = triplet()
    refs = [weakref.ref(image) for image in images.values()]
    api.upload_error_role = "demo_scene"
    with pytest.raises(RuntimeError, match="provider upload"):
        owner.publish(0, images)
    assert owner.failed and owner.publications == 0
    images.clear()
    gc.collect()
    assert all(ref() is not None for ref in refs)
    with pytest.raises(RuntimeError, match="healthy"):
        owner.publish(1, triplet())
    owner.close()
    gc.collect()
    assert all(ref() is None for ref in refs)


def test_partial_panel_creation_cleans_already_created_panels(api, config):
    api.create_error_at = 1
    with pytest.raises(RuntimeError, match="panel creation"):
        SharedCameraPreview(config, isolation=api.isolation)
    assert len(api.panels) == 1 and api.panels[0].closed
    assert ("release", "left_wrist") in api.events


def test_close_is_idempotent_releases_isolation_and_rejects_later_publish(api, config):
    owner = SharedCameraPreview(config, isolation=api.isolation)
    owner.publish(0, triplet())
    owner.close()
    owner.close()
    assert [event for event in api.events if event[0] == "close"] == [
        ("close", "right_wrist"),
        ("close", "demo_scene"),
        ("close", "left_wrist"),
    ]
    assert not owner.panels and not owner.retained and not owner.previous
    with pytest.raises(RuntimeError, match="healthy"):
        owner.publish(1, triplet())


def test_wrong_thread_cannot_publish(api, config):
    owner = SharedCameraPreview(config)
    errors = []

    def publish():
        try:
            owner.publish(0, triplet())
        except RuntimeError as error:
            errors.append(str(error))

    worker = threading.Thread(target=publish)
    worker.start()
    worker.join()
    assert errors == ["Preview requires its healthy Kit owner thread"]
    assert not uploads(api)
    owner.close()


def test_panel_close_failure_still_releases_other_panels_and_image_owners(api, config):
    owner = SharedCameraPreview(config, isolation=api.isolation)
    owner.publish(0, triplet())
    def fail():
        raise RuntimeError("provider teardown")
    owner.panels["right_wrist"].close = fail
    with pytest.raises(RuntimeError, match="provider teardown"):
        owner.close()
    assert owner.closed and not owner.retained and not owner.panels
    assert all(panel.closed for panel in api.panels[:2])
    owner.close()
