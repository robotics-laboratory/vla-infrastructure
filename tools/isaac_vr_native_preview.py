"""Experimental existing SceneUI panels; caller owns completed immutable CUDA frames.

No Camera sensors, render products, app pumps, recorder, or frame subscription.
The provider API copies GPU memory but exposes no stream/completion fence here.
Caller must retain source allocations through provider consumption; references
below retain current/previous images, not a proof of asynchronous copy completion.
"""
import os
import threading

class SharedCameraPreview:
    def __init__(self, config, *, isolation=None, visible=True, transport="cuda", max_publications=None):
        from isaaclab_teleop.camera_feed import _layout_feed_cfgs, _panel_descriptor
        from isaaclab_teleop.camera_feed_kit_scene_ui import _KitSceneUiCameraFeedPresenter
        from isaaclab_teleop.isaac_teleop_cfg import XrCameraFeedCfg, XrCameraFeedLayoutCfg

        self.thread, self.isolation = threading.get_ident(), isolation
        self.closed = self.failed = False
        self.last_source_id, self.publications, self.bytes = None, 0, 0
        self.retained, self.previous, self.panels = {}, {}, {}
        self.presenter = _KitSceneUiCameraFeedPresenter()
        self.transport, self.cpu_probe, self.copy_queue = transport, None, None
        self.gpu_retained, self.max_publications = [], max_publications
        if transport not in ("cuda", "cpu-retained", "cuda-retained", "cuda-event"):
            raise ValueError("Unknown preview transport")
        if transport == "cuda-retained" and (type(max_publications) is not int or max_publications < 1):
            raise ValueError("Retained GPU preview requires a finite publication budget")
        feeds, layout = config["vr_camera_feeds"], config["vr_camera_feeds"]["layout"]
        self.roles = {"left_wrist": "left_wrist", "demo_scene": "scene", "right_wrist": "right_wrist"}
        order = tuple(feeds["order"])
        if set(order) != set(self.roles) or len(order) != 3:
            raise ValueError("Expected the three canonical selected preview feeds")
        layout_cfg = XrCameraFeedLayoutCfg(**{k: v for k, v in layout.items()
                                             if k not in ("panel_width_m", "max_update_hz")})
        cfgs = [XrCameraFeedCfg(camera_name=name, panel_width_m=float(layout["panel_width_m"]),
                               max_update_hz=float(layout["max_update_hz"]),
                               label={"left_wrist": "LEFT WRIST", "demo_scene": "SCENE",
                                      "right_wrist": "RIGHT WRIST"}[name]) for name in order]
        self.sizes = {role: (int(config["cameras"]["scene" if role == "scene" else "wrist"]["width"]),
                             int(config["cameras"]["scene" if role == "scene" else "wrist"]["height"]))
                      for role in self.roles.values()}
        sizes = [self.sizes[self.roles[name]] for name in order]
        try:
            for cfg, (width, height) in zip(_layout_feed_cfgs(cfgs, sizes, layout_cfg), sizes, strict=True):
                panel = self.presenter.create_panel(_panel_descriptor(cfg, layout_cfg), width, height)
                self.panels[self.roles[cfg.camera_name]] = panel
                # Preserve the selected repair for camera-resolution child layout.
                panel._component.resolution_scale = 1.0
                panel._component.unit_to_pixel_scale = float(width) / panel._component.width
            self.set_visible(visible)
            if transport == "cuda-event":
                from isaac_vr_native_copy_queue import ProviderCopyQueue
                self.copy_queue = ProviderCopyQueue(max_pending=12, shim_path=os.environ.get("VLA_NATIVE_COPY_SHIM"))
            if transport == "cpu-retained":
                from isaac_vr_native_cpu_preview import CpuPreviewProbe
                self.cpu_probe = CpuPreviewProbe({role: panel._provider for role, panel in self.panels.items()},
                                                cuda_device="cuda:0", max_publications=max_publications)
        except BaseException:
            self.close()
            raise
    def _guard(self):
        if self.closed or self.failed or threading.get_ident() != self.thread:
            raise RuntimeError("Preview requires its healthy Kit owner thread")
    def set_visible(self, visible):
        self._guard()
        for panel in self.panels.values():
            if visible:
                panel._container.show()
                if self.isolation is not None:
                    self.isolation.check_panel(panel)
            else:
                panel._container.hide()
                if self.isolation is not None:
                    self.isolation.release_panel(panel)
        self.visible = bool(visible)
    def publish(self, source_id, images):
        self._guard()
        if type(source_id) is not int or source_id < 0 or (self.last_source_id is not None and source_id <= self.last_source_id):
            raise ValueError("Preview source ID must strictly increase")
        if set(images) != set(self.panels):
            raise ValueError("One completed three-role frame is required")
        for role, image in images.items():
            width, height = self.sizes[role]
            if image.device.type != "cuda" or str(image.dtype) != "torch.uint8" or tuple(image.shape) != (height, width, 4) or not image.is_contiguous():
                raise ValueError("Preview requires owned contiguous CUDA HWC RGBA8")
        if len({str(image.device) for image in images.values()}) != 1:
            raise ValueError("Preview triplet must use one CUDA device")
        if getattr(self, "copy_queue", None) is not None:
            self.copy_queue.poll()  # Acknowledge older uploads; never block this tick.
        if getattr(self, "transport", None) == "cuda-retained":
            if len(self.gpu_retained) >= self.max_publications:
                raise RuntimeError("Retained GPU preview allocation budget exhausted")
            # Keep every immutable producer-complete source through Kit shutdown.
            # The runner owns this presenter until SimulationApp.close returns.
            self.gpu_retained.append(dict(images))
        # Own every submitted allocation even if a later provider upload fails.
        self.previous, self.retained = self.retained, dict(images)
        if self.visible:
            from omni.ui.scene import Widget
            try:
                if getattr(self, "cpu_probe", None) is not None:
                    self.cpu_probe.publish_producer_complete(images)
                for role, image in images.items():
                    panel = self.panels[role]
                    if getattr(self, "cpu_probe", None) is None:
                        if getattr(self, "copy_queue", None) is not None:
                            self.copy_queue.upload(image, lambda panel=panel, image=image: panel.upload(image))
                        else:
                            panel.upload(image)
                    widget = panel._component.scene_widget
                    if widget is not None:
                        widget.update_policy = Widget.UpdatePolicy.ON_DEMAND
                        widget.invalidate()
                    self.bytes += image.numel()
                self.publications += 1
            except BaseException:
                self.failed = True
                raise
        self.last_source_id = source_id
    def close(self):
        if self.closed:
            return
        errors = []
        for panel in reversed(tuple(self.panels.values())):
            for release in ([lambda panel=panel: self.isolation.release_panel(panel)]
                            if self.isolation is not None else []) + [panel.close]:
                try:
                    release()
                except BaseException as exc:
                    errors.append(str(exc))
        if getattr(self, "copy_queue", None) is not None:
            self.copy_queue.close()  # Pending/orphan GPU owners stay anchored until Kit shutdown.
        self.panels.clear()
        self.previous.clear()
        self.retained.clear()
        self.closed = True
        if errors:
            raise RuntimeError("Preview cleanup failed: " + str(errors))
