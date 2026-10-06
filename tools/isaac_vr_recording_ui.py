"""Display-only recording HUD using pinned Kit SceneUI; no camera or input owner."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from types import SimpleNamespace

from tools.isaac_vr_episode_lifecycle import RecordingState


REVIEW_CHOICES = (("X", "Save"), ("B", "Discard"))
OUTCOME_CHOICES = (("X", "Success"), ("Y", "Failure"), ("B", "Incomplete"))
OUTCOME_BUTTONS = {"success": "X", "failure": "Y", "incomplete": "B"}


@dataclass(frozen=True)
class RecordingUiView:
    status: str
    title: str = ""
    detail: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    selected: str | None = None
    pressed: tuple[str, ...] = ()


class RecordingUiModel:
    """Observe accepted lifecycle events; retain confirmation across scene reset."""

    def __init__(self, feedback_seconds: float, *, clock=time.monotonic):
        if not math.isfinite(feedback_seconds) or feedback_seconds <= 0:
            raise ValueError("recording UI feedback_seconds must be finite and positive")
        self.feedback_seconds, self.clock = feedback_seconds, clock
        self._confirmation: RecordingUiView | None = None
        self._confirmation_until = 0.0

    def update(
        self,
        state: RecordingState | str,
        *,
        event: str | None = None,
        pressed: tuple[str, ...] = (),
        gap: bool = False,
        error: str | None = None,
    ) -> RecordingUiView:
        # Isaac's filename imports and core's tools.* imports must agree by
        # serialized state value, even when Python loads two enum classes.
        state = RecordingState(state)
        now = self.clock()
        if state is not RecordingState.WAITING or event == "reset":
            self._confirmation = None
        if state is RecordingState.WAITING:
            if event == "discard" or event in OUTCOME_BUTTONS:
                assert event is not None
                discarded = event == "discard"
                self._confirmation = RecordingUiView(
                    "[ready]  X - Start",
                    "Demonstration discarded" if discarded else "Demonstration saved",
                    "Selected: Discard" if discarded else f"Selected: {event.title()}",
                    REVIEW_CHOICES if discarded else OUTCOME_CHOICES,
                    "B" if discarded else OUTCOME_BUTTONS[event],
                )
                self._confirmation_until = now + self.feedback_seconds
            if self._confirmation is not None and now < self._confirmation_until:
                return self._confirmation
            self._confirmation = None
            return RecordingUiView("[ready]  X - Start")
        if state is RecordingState.RECORDING:
            suffix = "  |  Input gap: no sample" if gap else ""
            return RecordingUiView(f"[recording]  Y - Stop{suffix}")
        if state is RecordingState.REVIEW:
            return RecordingUiView(
                "[stopped]",
                "Recording stopped",
                "Keep or discard this demonstration?",
                REVIEW_CHOICES,
                pressed=pressed,
            )
        if state is RecordingState.CLASSIFY_OUTCOME:
            return RecordingUiView(
                "[stopped]",
                "Task outcome",
                "Selected: [X] Save - choose the task result",
                OUTCOME_CHOICES,
                pressed=pressed,
            )
        if state is RecordingState.FAILED:
            return RecordingUiView("[error]", "Recording failed", error or "See the host log")
        if state is RecordingState.INTERRUPTED:
            return RecordingUiView(
                "[interrupted]", "Recording interrupted", "Demonstration was not saved"
            )
        return RecordingUiView("[busy]", "Finishing recording")


class RecordingUi:
    """Two retained head-locked panels, excluded from dataset sensor rendering."""

    def __init__(self, config, *, isolation=None):
        import omni.ui as ui  # type: ignore[import-not-found]
        from omni.kit.scene_view.xr import XRSceneView  # type: ignore[import-not-found]
        from omni.kit.scene_view.xr_utils import (  # type: ignore[import-not-found]
            SpatialSource,
            UiContainer,
            UpdatePolicy,
            WidgetComponent,
        )
        from omni.kit.xr.core import XRCore  # type: ignore[import-not-found]
        from pxr import Gf  # type: ignore[import-not-found]

        self.model = RecordingUiModel(float(config["feedback_seconds"]))
        self.view = self.model.update(RecordingState.WAITING)
        self.isolation = isolation
        self.panels = {}
        self._visible = {"status": False, "review": False}
        if config["placement"] != "head_locked":
            raise ValueError("recording UI requires head_locked placement")
        meters_per_unit = float(XRCore.get_singleton().get_coordinate_system().meters_per_unit)
        if not math.isfinite(meters_per_unit) or meters_per_unit <= 0:
            raise RuntimeError("Invalid XR coordinate-system scale for recording UI")
        distance = float(config["distance_m"])
        if not math.isfinite(distance) or distance <= 0:
            raise ValueError("recording UI distance_m must be finite and positive")

        def make_panel(role):
            layout = config["layout"][role]

            class PanelWidget(ui.Widget):
                def __init__(widget_self, **kwargs):
                    super().__init__(**kwargs)
                    self._draw(role, ui)

            component = WidgetComponent(
                PanelWidget,
                width=float(layout["width_m"]) / meters_per_unit,
                height=float(layout["height_m"]) / meters_per_unit,
                # Text needs pixel-sized layout coordinates, unlike an image
                # provider that can fill a sub-pixel UI layout. Resolution scale
                # supersamples that layout; it does not enlarge its usable area.
                resolution_scale=1.0,
                unit_to_pixel_scale=float(config["pixels_per_m"]) * meters_per_unit,
                update_policy=UpdatePolicy.ON_DEMAND,
            )
            container = UiContainer(
                XRSceneView,
                component,
                space_stack=[
                    SpatialSource.new_prim_path_source("/_xr/stage/xrCamera"),
                    SpatialSource.new_translation_source(
                        Gf.Vec3f(
                            0.0,
                            float(layout["offset_y_m"]) / meters_per_unit,
                            -distance / meters_per_unit,
                        )
                    ),
                    SpatialSource.new_look_at_camera_source(),
                ],
            )
            container.hide()
            return SimpleNamespace(_container=container, component=component)

        try:
            for role in ("status", "review"):
                self.panels[role] = make_panel(role)
            self._present()
        except Exception:
            self.close()
            raise

    def _draw(self, role, ui):
        view = self.view
        with ui.ZStack():
            ui.Rectangle(style={"background_color": 0xF0201814, "border_radius": 8})
            with ui.VStack(spacing=10):
                if role == "status":
                    ui.Label(
                        view.status,
                        alignment=ui.Alignment.CENTER,
                        style={"font_size": 22, "color": 0xFFEEEEEE},
                    )
                    return
                ui.Label(
                    view.title, height=40, alignment=ui.Alignment.CENTER, style={"font_size": 28}
                )
                ui.Label(
                    view.detail,
                    height=40,
                    alignment=ui.Alignment.CENTER,
                    style={"font_size": 20, "color": 0xFFB8EFB8},
                )
                for button, label in view.choices:
                    selected = button == view.selected
                    ui.Label(
                        f"{'SELECTED  ' if selected else ''}[{button}]  {label}",
                        height=34,
                        alignment=ui.Alignment.CENTER,
                        style={"font_size": 24, "color": 0xFF70ED70 if selected else 0xFFEEEEEE},
                    )
                hint = "X/Y: left controller   B: right controller"
                if view.pressed:
                    hint = f"Pressed: {' / '.join(view.pressed)} - release before the next choice"
                ui.Label(
                    hint,
                    height=32,
                    alignment=ui.Alignment.CENTER,
                    style={"font_size": 17, "color": 0xFFB8B8B8},
                )

    def update(self, state: RecordingState | str, **kwargs) -> None:
        view = self.model.update(state, **kwargs)
        if view == self.view:
            return
        self.view = view
        self._present()

    def _present(self) -> None:
        for role, panel in self.panels.items():
            visible = role == "status" or bool(self.view.title)
            container = panel._container
            if visible != self._visible[role]:
                if visible:
                    container.show()
                else:
                    if self.isolation is not None:
                        self.isolation.release_panel(panel)
                    container.hide()
                self._visible[role] = visible
            if visible:
                container.scene_view.run_update()
                if panel.component.scene_widget is not None:
                    panel.component.scene_widget.invalidate()
                # Invalidation may replace the draw system. Reapply its sensor
                # exclusion before the existing simulation loop renders again.
                if self.isolation is not None:
                    self.isolation.check_panel(panel)

    def close(self) -> None:
        for role, panel in self.panels.items():
            if self.isolation is not None:
                self.isolation.release_panel(panel)
            panel._container.hide()
            self._visible[role] = False
