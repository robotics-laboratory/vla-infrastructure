"""Concrete S1 wrist/scene presentation using pinned NVIDIA SceneUI manager.

Two policy camera buffers retain their native batched Camera and RGB semantics.
The third, presentation-only scene camera is not a policy observation.
"""
from types import SimpleNamespace
import os
import time
import torch
from isaaclab.sensors import Camera, CameraCfg
from isaaclab_physx.renderers import IsaacRtxRendererCfg
from isaaclab_teleop.camera_feed import _XrCameraFeedManager
from isaaclab_teleop.camera_feed_kit_scene_ui import _KitSceneUiCameraFeedPresenter
from isaaclab_teleop import XrCameraFeedCfg, XrCameraFeedLayoutCfg
import isaaclab.sim as sim_utils
from isaac_preview_partitions import PreviewPartitions
from isaac_robosyn_vr_demo import _CpuStagedFeedPresenter


class _BatchedFeedManager(_XrCameraFeedManager):
    """Only adapt upstream's batch[0]/RGBA assumption at the presentation edge."""
    def _publish_feed(self, feed):
        super()._publish_feed(feed)
        if os.environ.get('VLA_S2_ACCEPTANCE_DIR'):
            if not hasattr(self, 'acceptance_publications'):
                self.acceptance_publications = {}
            name = feed.cfg.camera_name
            previous = self.acceptance_publications.get(name, {})
            frames = feed.camera.frame
            frames = frames if hasattr(frames, 'detach') else frames.torch
            self.acceptance_publications[name] = {
                'count': previous.get('count', 0) + 1,
                'host_publication_timestamp_ns': time.monotonic_ns(),
                'camera_frame': int(frames[
                    1 if name == 'right_wrist' else 0].item()),
            }

    def _image_from_output(self, cfg, output):
        key = 'rgba' if 'rgba' in output else 'rgb'
        image = output[key].torch[1 if cfg.camera_name == 'right_wrist' else 0]
        if image.dtype != torch.uint8 or image.shape != (480, 640, 3 if key == 'rgb' else 4):
            raise RuntimeError(f'Unexpected policy camera buffer for {cfg.camera_name}')
        if image.shape[-1] == 3:
            image = torch.cat((image, torch.full_like(image[..., :1], 255)), dim=-1)
        return image


class _PanelLease:
    """Manager lifetime is shorter than the upstream UiContainer lifetime."""
    def __init__(self, panel, isolation):
        self.panel, self.isolation = panel, isolation

    @property
    def _container(self):
        return self.panel._container

    def upload(self, image):
        self.panel.upload(image)

    def close(self):
        if self.isolation:
            self.isolation.release_panel(self.panel)
        self._container.hide()


class _RetainedPresenter(_CpuStagedFeedPresenter):
    """Pinned UiContainer explicitly requires show/hide instead of churn.

    Fixed three descriptors only, no generic resource cache. Managers may be
    recreated; their SceneViews remain owned by S1Preview until final shutdown.
    """
    def __init__(self, upstream, isolation):
        super().__init__(upstream, isolation)
        self.panels = {}

    def create_panel(self, descriptor, width, height):
        key = (descriptor, width, height)
        if key not in self.panels:
            if len(self.panels) >= 3:
                raise RuntimeError('S1 preview layout changed; restart the scene')
            self.panels[key] = super().create_panel(descriptor, width, height)
        panel = self.panels[key]
        panel._container.show()
        if self._isolation:
            self._isolation.check_panel(panel)
        return _PanelLease(panel, self._isolation)

    def finish(self):
        for panel in self.panels.values():
            panel.close()
        self.panels.clear()


class S1Preview:
    """Lifecycle composition, no camera/render/IK implementation replacement."""
    def __init__(self, env, *, isolation=True, validation_stamp=None):
        self.env = env
        self.isolation = PreviewPartitions(env.sim.stage) if isolation else None
        self.validation_stamp = validation_stamp
        self.scene_camera = self.make_scene_camera('/World/S1PreviewSceneCamera')
        self.manager = None
        self.presenter = _RetainedPresenter(_KitSceneUiCameraFeedPresenter(), self.isolation)
        if self.validation_stamp:
            stage_upload = self.presenter.stage_upload_image
            def stamped(image, upload):
                stage_upload(image, upload)
                self.validation_stamp(upload)
            self.presenter.stage_upload_image = stamped
        self.validation_callback = None
        self.scene_paths = ['/World/S1PreviewSceneCamera0/Camera', '/World/S1PreviewSceneCamera1/Camera']
        self.paths = list(env.camera_prim_paths) + self.scene_paths[:1]
        if self.isolation:
            self.isolation.bind_sensors((), concrete_paths=list(env.camera_prim_paths) + self.scene_paths)
        # Public scene reset initializes the additional upstream Camera before bind.
        env.sim.reset()
        env.reset(0)
        self.scene_camera.set_world_poses_from_view(
            torch.tensor([[1.5, -1.5, 1.5]]*2, device=env.sim.device),
            torch.tensor([[0., 0., .4]]*2, device=env.sim.device))
        env.sim.render()
        self.scene_camera.update(env.sim.get_physics_dt(), force_recompute=True)
        self.open()

    @staticmethod
    def make_scene_camera(path):
        # Pinned RenderContext requires the canonical wrist batch size (two)
        # for every Camera. Second view is presentation-only, never a D0 role.
        stage = sim_utils.SimulationContext.instance().stage
        for index in range(2):
            stage.DefinePrim(f'{path}{index}', 'Xform')
        return Camera(CameraCfg(prim_path=path+'[01]/Camera', update_period=0., width=640, height=480,
            data_types=['rgba'], update_latest_camera_pose=True,
            renderer_cfg=IsaacRtxRendererCfg(enable_scene_partitioning=False),
            spawn=sim_utils.PinholeCameraCfg(focal_length=18., horizontal_aperture=20.955,
                                            clipping_range=(.02, 10.))))

    def open(self):
        if self.manager is not None:
            raise RuntimeError('Preview manager already open')
        cfgs = [XrCameraFeedCfg(camera_name=name, label=label, panel_width_m=.36,
                               max_update_hz=30.) for name, label in (
            ('left_wrist','LEFT WRIST'), ('right_wrist','RIGHT WRIST'), ('scene','SCENE'))]
        layout = XrCameraFeedLayoutCfg(mode='horizontal', placement='world' if self.validation_stamp else 'head_locked',
                                      world_position_m=(0., 0., 0.) if self.validation_stamp else None, distance_m=.75,
                                      center_offset_m=(0., -.2), panel_gap_m=.03)
        scene = SimpleNamespace(sensors={'left_wrist':self.env.camera, 'right_wrist':self.env.camera,
                                         'scene':self.scene_camera})
        self.manager = _BatchedFeedManager(SimpleNamespace(scene=scene), cfgs, layout, self.presenter)
        self.manager.refresh()
        self.assert_valid()

    def assert_valid(self):
        if self.isolation:
            self.isolation.assert_valid()

    def update(self, dt):
        self.scene_camera.update(dt, force_recompute=True)
        if self.manager is not None:
            self.manager.update()
        if self.validation_callback is not None:
            self.validation_callback()

    def refresh(self):
        self.scene_camera.reset()
        if self.manager is not None:
            self.manager.refresh()

    def close_panels(self):
        if self.manager is not None:
            self.manager.close()
            self.manager = None

    def close(self):
        self.close_panels()
        self.presenter.finish()
