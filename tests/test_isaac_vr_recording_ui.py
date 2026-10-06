"""Operator feedback follows accepted events, including synchronous publication/reset."""

from pathlib import Path
from contextlib import nullcontext
import sys
from types import ModuleType, SimpleNamespace as NS

import pytest
import yaml

from tools.isaac_vr_episode_lifecycle import RecordingLifecycle, RecordingState
from tools.isaac_vr_recording_ui import (
    RecordingUi,
    RecordingUiModel,
    OUTCOME_CHOICES,
    REVIEW_CHOICES,
)


@pytest.fixture
def operator():
    now = [0.0]
    calls = []
    lifecycle = RecordingLifecycle(
        seal=lambda reason: calls.append(("seal", reason)),
        publish=lambda demo, outcome: calls.append(("publish", demo, outcome)),
        reset=lambda: calls.append(("reset",)),
        discard=lambda demo: calls.append(("discard", demo)),
        identity=lambda: "demo",
    )
    model = RecordingUiModel(1.2, clock=lambda: now[0])

    def tick(button=None):
        values = {name: name == button for name in ("x", "y", "b")}
        event = lifecycle.buttons(**values)
        return model.update(
            lifecycle.state,
            event=event,
            pressed=(button.upper(),) if button else (),
        )

    return lifecycle, model, now, calls, tick


def stop(operator):
    lifecycle, model, now, calls, tick = operator
    assert "[ready]" in tick().status
    assert "[recording]" in tick("x").status
    tick()
    view = tick("y")
    assert lifecycle.state is RecordingState.REVIEW
    assert view.choices == REVIEW_CHOICES and view.pressed == ("Y",)
    assert calls == [("seal", "explicit_stop")]
    tick()


def test_save_shows_accepted_choice_without_classifying_held_x(operator):
    stop(operator)
    lifecycle, model, now, calls, tick = operator
    view = tick("x")
    assert lifecycle.state is RecordingState.CLASSIFY_OUTCOME
    assert "Selected: [X] Save" in view.detail
    assert view.choices == OUTCOME_CHOICES
    for _ in range(5):
        view = tick("x")
        assert view.selected is None
        assert view.pressed == ("X",)
    assert calls == [("seal", "explicit_stop")]


@pytest.mark.parametrize(
    ("button", "outcome"), [("x", "success"), ("y", "failure"), ("b", "incomplete")]
)
def test_outcome_highlight_survives_reset_and_expires_without_blocking(operator, button, outcome):
    stop(operator)
    lifecycle, model, now, calls, tick = operator
    tick("x")
    tick()
    view = tick(button)
    assert lifecycle.state is RecordingState.WAITING and lifecycle.demo_id is None
    assert calls[-2:] == [("publish", "demo", outcome), ("reset",)]
    assert view.title == "Demonstration saved"
    assert view.selected == button.upper() and view.choices == OUTCOME_CHOICES
    now[0] = 1.19
    assert tick().title == "Demonstration saved"
    now[0] = 1.2
    assert tick().title == ""


def test_discard_highlights_b_and_new_start_supersedes_confirmation(operator):
    stop(operator)
    lifecycle, model, now, calls, tick = operator
    view = tick("b")
    assert view.title == "Demonstration discarded"
    assert view.selected == "B" and view.choices == REVIEW_CHOICES
    assert calls[-2:] == [("discard", "demo"), ("reset",)]
    tick()
    view = tick("x")
    assert "[recording]" in view.status and not view.title


def test_input_gap_changes_only_status_and_does_not_open_review(operator):
    lifecycle, model, now, calls, tick = operator
    tick("x")
    view = model.update(lifecycle.state, gap=True)
    assert "[recording]" in view.status and "no sample" in view.status
    assert not view.title and not view.choices
    assert lifecycle.admits_recording and calls == []
    assert "no sample" not in model.update(lifecycle.state, gap=False).status


def test_publication_failure_never_reports_saved(operator):
    stop(operator)
    lifecycle, model, now, calls, tick = operator
    tick("x")
    tick()

    def fail(*args):
        raise OSError("disk full")

    lifecycle.publish = fail
    with pytest.raises(OSError, match="disk full"):
        tick("y")
    view = model.update(lifecycle.state, error=lifecycle.error)
    assert view.title == "Recording failed" and "disk full" in view.detail
    assert not view.selected and not view.choices
    assert calls == [("seal", "explicit_stop")]


def test_reset_clears_confirmation_and_interrupt_clears_pending_save(operator):
    stop(operator)
    lifecycle, model, now, calls, tick = operator
    tick("b")
    assert not model.update(lifecycle.state, event="reset").title
    tick()
    tick("x")
    tick()
    tick("y")
    tick()
    tick("x")
    lifecycle.disconnect()
    view = model.update(lifecycle.state)
    assert view.status == "[interrupted]" and "not saved" in view.detail


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
def test_feedback_duration_is_bounded(seconds):
    with pytest.raises(ValueError):
        RecordingUiModel(seconds)


def test_selected_layout_matches_installed_head_locked_panel_contract():
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "configs/isaac61_vr_runtime.yaml").read_text())["recording_ui"]
    assert config["enabled"] and config["placement"] == "head_locked"
    assert config["status"] == "HUMAN_ACCEPTED_S2_20261006"
    assert config["distance_m"] > 0.1
    for role in ("status", "review"):
        layout = config["layout"][role]
        assert layout["width_m"] * config["pixels_per_m"] >= 640
        assert layout["height_m"] > 0


def test_filename_imported_enum_uses_the_same_presentation(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "tools"))
    from isaac_vr_episode_lifecycle import RecordingState as RuntimeState

    model = RecordingUiModel(1.2)
    assert "[recording]" in model.update(RuntimeState.RECORDING).status
    assert model.update(RuntimeState.REVIEW).choices == REVIEW_CHOICES


def test_presenter_retains_panels_and_excludes_them_before_render(monkeypatch):
    """Exercise the lazy Kit boundary without importing GPU or XR runtimes."""
    labels, containers, events = [], [], []

    def install(name, **attributes):
        module = ModuleType(name)
        for key, value in attributes.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    class Component:
        def __init__(self, widget_type, **kwargs):
            self.widget_type, self.config = widget_type, kwargs
            self.scene_widget = NS(invalidate=self.invalidate)

        def invalidate(self):
            events.append("invalidate")
            self.widget_type()

    class Container:
        def __init__(self, scene_type, component, **kwargs):
            self.component, self.config = component, kwargs
            self.scene_view = NS(run_update=lambda: events.append("scene_update"))
            self.visible = True
            containers.append(self)

        def show(self):
            self.visible = True

        def hide(self):
            self.visible = False

    class Isolation:
        def __init__(self):
            self.panels = set()

        def check_panel(self, panel):
            assert panel._container.visible
            self.panels.add(panel._container)
            events.append("exclude_sensor")

        def release_panel(self, panel):
            self.panels.discard(panel._container)

    ui = install(
        "omni.ui",
        Widget=type("Widget", (), {"__init__": lambda self, **k: None}),
        ZStack=nullcontext,
        VStack=lambda **k: nullcontext(),
        Rectangle=lambda **k: None,
        Label=lambda text, **k: labels.append((text, k)),
        Alignment=NS(CENTER=0),
    )
    install("omni", ui=ui)
    install("omni.kit")
    install("omni.kit.scene_view")
    install("omni.kit.scene_view.xr", XRSceneView=object)
    install(
        "omni.kit.scene_view.xr_utils",
        UiContainer=Container,
        WidgetComponent=Component,
        UpdatePolicy=NS(ON_DEMAND="on_demand"),
        SpatialSource=NS(
            new_prim_path_source=lambda path: path,
            new_translation_source=lambda vector: vector,
            new_look_at_camera_source=lambda: "look_at",
        ),
    )
    install("omni.kit.xr")
    install(
        "omni.kit.xr.core",
        XRCore=NS(
            get_singleton=lambda: NS(
                get_coordinate_system=lambda: NS(meters_per_unit=0.01),
            )
        ),
    )
    install("pxr", Gf=NS(Vec3f=lambda *args: args))
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "configs/isaac61_vr_runtime.yaml").read_text())["recording_ui"]
    isolation = Isolation()
    presenter = RecordingUi(config, isolation=isolation)
    assert len(containers) == 2 and len(isolation.panels) == 1
    assert containers[0].config["space_stack"] == ["/_xr/stage/xrCamera", (0, 23, -75), "look_at"]
    component = containers[0].component.config
    assert component["unit_to_pixel_scale"] == 12.0
    assert component["resolution_scale"] == 1.0
    # A 22px label must fit in the 72px status layout, not a 0.06px layout.
    assert component["height"] * component["unit_to_pixel_scale"] == pytest.approx(72)
    assert containers[0].component.config["update_policy"] == "on_demand"
    events.clear()
    presenter.update(RecordingState.WAITING)
    assert events == []  # No texture capture on unchanged input/status ticks.
    for _ in range(3):
        presenter.update(RecordingState.RECORDING)
        presenter.update(RecordingState.REVIEW)
        assert len(isolation.panels) == 2
        assert events[-1] == "exclude_sensor"
        presenter.update(RecordingState.CLASSIFY_OUTCOME, event="save", pressed=("X",))
        assert any("Selected: [X] Save" in text for text, _ in labels)
        presenter.update(RecordingState.WAITING, event="failure")
        assert any(text == "SELECTED  [Y]  Failure" for text, _ in labels)
        presenter.update(RecordingState.WAITING, event="reset")
        assert len(isolation.panels) == 1
    assert len(containers) == 2
    presenter.close()
    assert not isolation.panels and not any(panel.visible for panel in containers)
