"""Concrete, test-only RoboSyn-inspired scene layered on the S2 runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np
import torch
import yaml

import isaaclab.sim as sim_utils  # type: ignore[import-not-found]
from isaaclab.actuators import ImplicitActuatorCfg  # type: ignore[import-not-found]
from isaaclab.assets import Articulation, ArticulationCfg, RigidObject, RigidObjectCfg  # type: ignore[import-not-found]
from isaaclab.sensors import ContactSensor, ContactSensorCfg  # type: ignore[import-not-found]
from isaaclab.sensors.camera import Camera, CameraCfg  # type: ignore[import-not-found]


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs/experiments/robosyn_vr_demo.yaml"
ASSET_MANIFEST_PATH = ROOT / "configs/experiments/robosyn_test_assets.yaml"
ROBOSYN_ROOT = Path("/data/ebulochkin/assets/robosyn_vr_demo/RoboSynChallenge")
CONVERTED_ROOT = Path("/data/ebulochkin/assets/robosyn_vr_demo/converted")
PHYSICS_DT = 1.0 / 120.0
CAMERA_PERIOD = 1.0 / 30.0


def _tensor(value) -> torch.Tensor:
    return value if isinstance(value, torch.Tensor) else value.torch


def _cpu(value) -> np.ndarray:
    return _tensor(value).detach().cpu().numpy()


class _CpuStagedFeedPresenter:
    """Select upstream SceneUI's CPU provider path for CloudXR compatibility.

    The pinned presenter remains responsible for the feed source, panels,
    SceneUI lifecycle, and frame subscription. This adapter only stages its
    unchanged RGBA tensor to a reusable CPU buffer before the upstream panel
    uploads it through ``ByteImageProvider``.
    """

    def __init__(self, upstream_presenter: Any) -> None:
        self._upstream = upstream_presenter

    def create_image_source(self, camera_name: str, camera: Any, cfg: Any = None) -> Any:
        return self._upstream.create_image_source(camera_name, camera, cfg)

    def create_panel(self, descriptor: Any, width: int, height: int) -> Any:
        return self._upstream.create_panel(descriptor, width, height)

    def subscribe_to_frame_updates(self, callback: Callable[[Any], None]) -> Any:
        return self._upstream.subscribe_to_frame_updates(callback)

    @staticmethod
    def prepare_upload_image(
        camera_name: str,
        image: torch.Tensor,
        previous_source: torch.Tensor | None = None,
        previous_upload: torch.Tensor | None = None,
    ) -> torch.Tensor:
        del camera_name, previous_source
        if image.device.type == "cpu":
            return image
        if (
            previous_upload is not None
            and previous_upload.device.type == "cpu"
            and tuple(previous_upload.shape) == tuple(image.shape)
            and previous_upload.dtype == image.dtype
        ):
            return previous_upload
        return torch.empty(tuple(image.shape), dtype=image.dtype, device="cpu")

    @staticmethod
    def stage_upload_image(image: torch.Tensor, upload_image: torch.Tensor) -> None:
        if upload_image is not image:
            upload_image.copy_(image, non_blocking=False)


class _BimanualCameraData:
    def __init__(self, cameras: tuple[Camera, Camera]) -> None:
        self._cameras = cameras

    @property
    def output(self) -> dict[str, torch.Tensor]:
        return {
            "rgb": torch.cat(
                tuple(_tensor(camera.data.output["rgba"])[..., :3] for camera in self._cameras),
                dim=0,
            )
        }

    @property
    def pos_w(self) -> torch.Tensor:
        return torch.cat(tuple(_tensor(camera.data.pos_w) for camera in self._cameras), dim=0)

    @property
    def quat_w_world(self) -> torch.Tensor:
        return torch.cat(
            tuple(_tensor(camera.data.quat_w_world) for camera in self._cameras), dim=0
        )


class DemoCameraRig:
    """Present two named upstream cameras through the unchanged batched D0 edge."""

    def __init__(self, wrists: tuple[Camera, Camera], scene: Camera) -> None:
        self.wrists = wrists
        self.scene_camera = scene
        self.data = _BimanualCameraData(wrists)
        self.num_instances = 2
        self._elapsed = 0.0
        self.capture_cycles_total = 0

    @property
    def frame(self) -> torch.Tensor:
        return torch.cat(tuple(_tensor(camera.frame).reshape(-1) for camera in self.wrists))

    def reset(self) -> None:
        for camera in (*self.wrists, self.scene_camera):
            camera.reset()
        self._elapsed = 0.0

    def update(self, dt: float, *, force_recompute: bool = False) -> None:
        del force_recompute
        self._elapsed += dt
        if self._elapsed + 1.0e-9 < CAMERA_PERIOD:
            return
        elapsed = self._elapsed
        self._elapsed = 0.0
        self.capture_cycles_total += 1
        for camera in (*self.wrists, self.scene_camera):
            camera.update(elapsed, force_recompute=True)


class DemoRuntime:
    """Own only experiment reset, validation, metrics, and upstream PiP binding."""

    def __init__(
        self,
        *,
        config: dict[str, Any],
        profile: str,
        camera_rig: DemoCameraRig,
        camera_cfgs: tuple[CameraCfg, CameraCfg],
        dynamic_assets: list[Any],
        contact_sensors: dict[str, list[ContactSensor]],
        imported_prims: dict[str, str],
        hud_on_start: bool,
    ) -> None:
        from isaaclab_teleop.camera_feed import XrCameraFeedSession  # type: ignore[import-not-found]
        from isaaclab_teleop.isaac_teleop_cfg import (  # type: ignore[import-not-found]
            XrCameraFeedCfg,
            XrCameraFeedLayoutCfg,
        )

        self.config = config
        self.profile = profile
        self.camera_rig = camera_rig
        self.dynamic_assets = dynamic_assets
        self.contact_sensors = contact_sensors
        self.imported_prims = imported_prims
        self.hud_on_start = hud_on_start
        self.display_control = str(config["vr_camera_feeds"]["toggle_control"])
        self.backdrop_control = str(config["scene"]["backdrop"]["toggle_control"])
        self.recenter_control = str(config["xr_presentation"]["recenter"]["toggle_control"])
        self.recenter_view_prim_path = str(
            config["xr_presentation"]["recenter"]["view_prim_path"]
        )
        self.pipeline_action_dim = 25
        self.validation: dict[str, Any] = {}
        self._env = None
        self._display_visible = False
        self._feed_bound = False
        self._feed_bound_ever = False
        self._display_button_pressed = False
        self._display_toggle_count = 0
        self._backdrop_visible = True
        self._backdrop_button_pressed = False
        self._backdrop_toggle_count = 0
        self._recenter_button_pressed = False
        self._recenter_request_count = 0
        self._recenter_scheduled_count = 0
        self._runtime_frames: dict[str, int] = {}
        self._runtime_capture_cycles = 0
        self._validation_complete = False
        layout = config["vr_camera_feeds"]["layout"]
        feed_cfgs = [
            XrCameraFeedCfg(
                camera_name=name,
                panel_width_m=float(layout["panel_width_m"]),
                max_update_hz=float(layout["max_update_hz"]),
                label=label,
            )
            for name, label in (("left_wrist", "LEFT WRIST"), ("right_wrist", "RIGHT WRIST"))
        ]
        layout_cfg = XrCameraFeedLayoutCfg(
            mode=str(layout["mode"]),
            placement=str(layout["placement"]),
            center_offset_m=tuple(layout["center_offset_m"]),
            distance_m=float(layout["distance_m"]),
            panel_gap_m=float(layout["panel_gap_m"]),
        )
        scene_cfg = SimpleNamespace(
            num_envs=1,
            left_wrist=camera_cfgs[0],
            right_wrist=camera_cfgs[1],
        )
        env_cfg = SimpleNamespace(
            scene=scene_cfg,
            isaac_teleop=SimpleNamespace(
                xr_camera_feeds=feed_cfgs,
                xr_camera_feed_layout=layout_cfg,
            ),
        )
        self._feed_session = XrCameraFeedSession.prepare(
            env_cfg, enabled=True, camera_rendering_enabled=True
        )
        self.feed_session_prepared_enabled = bool(self._feed_session.enabled)
        self.feed_upload_path = str(config["vr_camera_feeds"]["upload_path"])
        if self.feed_session_prepared_enabled:
            if self.feed_upload_path != "cpu_staged":
                raise ValueError(
                    f"unsupported demo XR camera upload path: {self.feed_upload_path}"
                )
            presenter = self._feed_session._presenter
            if presenter is None:
                raise RuntimeError("upstream XR camera feed presenter is unavailable")
            self._feed_session._presenter = _CpuStagedFeedPresenter(presenter)

    @property
    def xr_presentation(self) -> dict[str, Any]:
        return self.config["xr_presentation"]

    @property
    def sensitivity(self) -> dict[str, Any]:
        return self.config["teleop_tuning"]["sensitivity"]

    @property
    def display_toggle_count(self) -> int:
        return self._display_toggle_count

    @property
    def backdrop_toggle_count(self) -> int:
        return self._backdrop_toggle_count

    @property
    def recenter_request_count(self) -> int:
        return self._recenter_request_count

    @property
    def recenter_scheduled_count(self) -> int:
        return self._recenter_scheduled_count

    def reset_scene(self) -> None:
        for asset in self.dynamic_assets:
            asset.write_root_pose_to_sim_index(root_pose=asset.data.default_root_pose.torch.clone())
            asset.write_root_velocity_to_sim_index(
                root_velocity=asset.data.default_root_vel.torch.clone()
            )
            asset.reset()
        for sensors in self.contact_sensors.values():
            for sensor in sensors:
                sensor.reset()

    def update(self, dt: float) -> None:
        for asset in self.dynamic_assets:
            asset.update(dt)
        if not self._validation_complete:
            for sensors in self.contact_sensors.values():
                for sensor in sensors:
                    sensor.update(dt, force_recompute=True)
        # Viewer-start panels may be shown again by upstream after an XR
        # reconnect. Reassert display-only OFF without touching capture or the
        # Replicator binding.
        if self._feed_bound and not self._display_visible:
            self._set_upstream_panel_visibility(False)

    def open(self, env) -> None:
        self._env = env
        self._runtime_frames = self._camera_frames()
        self._runtime_capture_cycles = self.camera_rig.capture_cycles_total
        self._set_backdrop_visibility(bool(self.config["scene"]["backdrop"]["initial_visibility"]))
        self._prebind_camera_panels()
        if self.hud_on_start:
            self._set_display(True)

    def _prebind_camera_panels(self) -> None:
        """Complete Candidate B's bind phase before XR session entry."""

        # Candidate B's two-phase lifecycle requires bind(env) before entering
        # the XR teleop session. Build both SceneUI panels now, initially
        # hidden, so X only changes visibility after the headset connects.
        if self.feed_session_prepared_enabled:
            self._feed_session.bind(self._env)
            self._feed_bound = True
            self._feed_bound_ever = True
            self._feed_session.refresh()
            self._set_upstream_panel_visibility(False)
            manager = self._feed_session._manager
            feeds = tuple(manager._feeds) if manager is not None else ()
            diagnostics = []
            for feed in feeds:
                source_image = feed.image
                upload_image = feed.upload_image
                diagnostics.append(
                    {
                        "camera": feed.cfg.camera_name,
                        "rgb_stddev": float(upload_image[..., :3].float().std().item()),
                        "source_alpha_range": [
                            int(source_image[..., 3].min().item()),
                            int(source_image[..., 3].max().item()),
                        ],
                        "source_device": source_image.device.type,
                        "upload_alpha_range": [
                            int(upload_image[..., 3].min().item()),
                            int(upload_image[..., 3].max().item()),
                        ],
                        "upload_device": upload_image.device.type,
                    }
                )
            print(
                json.dumps(
                    {
                        "event": "demo_vr_camera_feed_bound",
                        "feeds": diagnostics,
                        "layout": self.config["vr_camera_feeds"]["layout"]["placement"],
                        "upload_path": self.feed_upload_path,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            print("[DEMO] wrist camera panels prebound hidden before XR session", flush=True)

    def close(self) -> None:
        if self._feed_bound:
            self._feed_session.close()
            self._feed_bound = False
        self._env = None

    def after_reset(self) -> None:
        # Preserve edge state across a scene reset so a physically held X/B
        # cannot be interpreted as a second press in the new reset epoch.
        self._set_backdrop_visibility(self._backdrop_visible)
        if self._feed_bound:
            self._feed_session.refresh()
            self._set_upstream_panel_visibility(self._display_visible)

    def consume_display_button(
        self, value: float, *, event_origin: str = "controller_pipeline"
    ) -> None:
        pressed = bool(value > 0.5)
        if pressed and not self._display_button_pressed:
            self._set_display(not self._display_visible)
            self._display_toggle_count += 1
            print(
                json.dumps(
                    {
                        "capture_continues": True,
                        "control": self.display_control,
                        "display_visible": self._display_visible,
                        "event": "demo_vr_camera_feed_visibility_changed",
                        "event_origin": event_origin,
                        "feed_bound": self._feed_bound,
                        "quest_button": self.config["vr_camera_feeds"]["quest_button"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        self._display_button_pressed = pressed

    def consume_backdrop_button(
        self, value: float, *, event_origin: str = "controller_pipeline"
    ) -> None:
        pressed = bool(value > 0.5)
        if pressed and not self._backdrop_button_pressed:
            self._set_backdrop_visibility(not self._backdrop_visible)
            self._backdrop_toggle_count += 1
            print(
                json.dumps(
                    {
                        "backdrop_visible": self._backdrop_visible,
                        "control": self.backdrop_control,
                        "event": "demo_backdrop_visibility_changed",
                        "event_origin": event_origin,
                        "quest_button": self.config["scene"]["backdrop"]["quest_button"],
                        "visual_only": True,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        self._backdrop_button_pressed = pressed

    def consume_recenter_button(
        self,
        value: float,
        *,
        schedule_recenter: Callable[[], bool],
        event_origin: str = "controller_pipeline",
    ) -> bool:
        """Schedule one XR recenter per R3 press and report whether it ran."""

        pressed = bool(value > 0.5)
        scheduled = False
        if pressed and not self._recenter_button_pressed:
            self._recenter_request_count += 1
            scheduled = bool(schedule_recenter())
            self._recenter_scheduled_count += int(scheduled)
            print(
                json.dumps(
                    {
                        "authoritative_scene_geometry_changed": False,
                        "control": self.recenter_control,
                        "event": "demo_xr_recenter_requested",
                        "event_origin": event_origin,
                        "quest_button": self.config["xr_presentation"]["recenter"][
                            "quest_button"
                        ],
                        "scheduled": scheduled,
                        "session_restart": False,
                        "view_prim_path": self.recenter_view_prim_path,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        self._recenter_button_pressed = pressed
        return scheduled

    def _set_backdrop_visibility(self, visible: bool) -> None:
        """Toggle only the visual USD backdrop; robot/table physics are untouched."""

        import omni.usd  # type: ignore[import-not-found]
        from pxr import UsdGeom  # type: ignore[import-not-found]

        stage = omni.usd.get_context().get_stage()
        prim = stage.GetPrimAtPath("/World/RobosynDemo/Backdrop")
        if not prim.IsValid():
            raise RuntimeError("demo backdrop prim is missing")
        imageable = UsdGeom.Imageable(prim)
        if visible:
            imageable.MakeVisible()
        else:
            imageable.MakeInvisible()
        self._backdrop_visible = visible

    def _set_upstream_panel_visibility(self, visible: bool) -> None:
        """Show/hide pinned upstream SceneUI panels without closing their RGB source."""

        manager = self._feed_session._manager
        if manager is None:
            raise RuntimeError("upstream XR camera feed manager is not bound")
        feeds = tuple(manager._feeds)
        if len(feeds) != 2:
            raise RuntimeError(f"expected two upstream wrist feed panels, got {len(feeds)}")
        for feed in feeds:
            container = feed.panel._container
            if container is None:
                raise RuntimeError("upstream XR camera feed panel has no UiContainer")
            if visible:
                container.show()
            else:
                container.hide()

    def _set_display(self, visible: bool) -> None:
        if visible == self._display_visible:
            return
        if self._env is None:
            raise RuntimeError("demo HUD cannot change before runtime binding")
        if visible:
            if not self.feed_session_prepared_enabled:
                raise RuntimeError(
                    "upstream XR CameraFeedSession is unavailable in this Kit experience"
                )
            if not self._feed_bound:
                raise RuntimeError(
                    "upstream XR camera panels were not bound before the XR session"
                )
            self._set_upstream_panel_visibility(True)
        else:
            # Closing here detaches the pinned Replicator RGB annotator shared
            # with Isaac Lab Camera and makes the next Camera.update() fail.
            # UiContainer visibility is the upstream display-only mechanism;
            # final resource teardown remains in close().
            self._set_upstream_panel_visibility(False)
        self._display_visible = visible
        print(f"[DEMO] wrist camera display {'ON' if visible else 'OFF'}", flush=True)

    def _camera_frames(self) -> dict[str, int]:
        wrist = _cpu(self.camera_rig.frame).astype(np.int64)
        scene = _cpu(self.camera_rig.scene_camera.frame).astype(np.int64)
        return {
            "left_wrist": int(wrist[0]),
            "right_wrist": int(wrist[1]),
            "demo_scene": int(scene[0]),
        }

    def performance_report(self, elapsed: float, camera_observation_frames: int) -> dict[str, Any]:
        final = self._camera_frames()
        cycles = self.camera_rig.capture_cycles_total - self._runtime_capture_cycles
        rates = {name: camera_observation_frames / elapsed for name in final}
        return {
            "profile": self.profile,
            "camera_frames_start": self._runtime_frames,
            "camera_frames_end": final,
            "camera_capture_cycles_including_reset": cycles,
            "camera_effective_hz": rates,
            "camera_configured_simulation_hz": {
                "left_wrist": 30.0,
                "right_wrist": 30.0,
                "demo_scene": 30.0,
            },
            "vr_feed_visibility": {
                "initial": self.hud_on_start,
                "final": self._display_visible,
                "toggle_count": self._display_toggle_count,
                "control": self.display_control,
                "quest_button": self.config["vr_camera_feeds"]["quest_button"],
                "capture_continues_when_hidden": True,
                "feed_bound_ever": self._feed_bound_ever,
                "upstream_session_prepared_enabled": self.feed_session_prepared_enabled,
                "upload_path": self.feed_upload_path,
            },
            "backdrop_visibility": {
                "initial": bool(self.config["scene"]["backdrop"]["initial_visibility"]),
                "final": self._backdrop_visible,
                "toggle_count": self._backdrop_toggle_count,
                "control": self.backdrop_control,
                "quest_button": self.config["scene"]["backdrop"]["quest_button"],
                "visual_only": True,
            },
            "xr_recenter": {
                "request_count": self._recenter_request_count,
                "scheduled_count": self._recenter_scheduled_count,
                "control": self.recenter_control,
                "quest_button": self.config["xr_presentation"]["recenter"]["quest_button"],
                "view_prim_path": self.recenter_view_prim_path,
                "upstream_mechanism": "XRCore.schedule_teleport_to_view",
                "controller_transform_source": (
                    "XRCore.get_physical_to_virtual_world_transform"
                ),
                "authoritative_scene_geometry_changed": False,
            },
            "optional_demo_performance_mode": "not_implemented",
            "validation": self.validation,
        }

    def validate(self, env) -> dict[str, Any]:
        observation = env.observation()
        state = observation["observation.state"]
        home_error = np.abs(state - env.home_d0)
        forces = {}
        for side, sensors in self.contact_sensors.items():
            magnitudes = [
                float(np.linalg.norm(_cpu(sensor.data.net_forces_w), axis=-1).max(initial=0.0))
                for sensor in sensors
            ]
            forces[side] = max(magnitudes, default=0.0)
        scene_image = _cpu(self.camera_rig.scene_camera.data.output["rgb"])[0]
        wrist_shapes = {
            role: list(observation[f"observation.images.{role}"].shape)
            for role in ("left_wrist", "right_wrist")
        }
        import omni.usd  # type: ignore[import-not-found]
        from pxr import UsdPhysics  # type: ignore[import-not-found]

        stage = omni.usd.get_context().get_stage()
        imports = {
            asset_id: bool(stage.GetPrimAtPath(path).IsValid())
            for asset_id, path in self.imported_prims.items()
        }
        required_paths = [
            "/World/RobosynDemo/Table",
            "/World/RobosynDemo/Backdrop",
            "/World/LeftPiper",
            "/World/RightPiper",
            "/World/RobosynDemo/SceneCamera",
        ]
        if self.profile == "dual_cube_to_matching_plates":
            required_paths.extend(
                [
                    "/World/RobosynDemo/LeftCube",
                    "/World/RobosynDemo/RightCube",
                    "/World/RobosynDemo/LeftPlate",
                    "/World/RobosynDemo/RightPlate",
                ]
            )
        required_prims = {
            path: bool(stage.GetPrimAtPath(path).IsValid()) for path in required_paths
        }
        table_collision = any(
            prim.HasAPI(UsdPhysics.CollisionAPI)
            for prim in stage.Traverse()
            if str(prim.GetPath()).startswith("/World/RobosynDemo/Table")
        )
        reset_errors = []
        for asset in self.dynamic_assets:
            actual = _cpu(asset.data.root_pos_w)
            expected = _cpu(asset.data.default_root_pose.torch)[:, :3]
            reset_errors.append(float(np.linalg.norm(actual - expected, axis=-1).max()))
        tcp_positions = [
            _cpu(robot.data.body_link_pose_w)[0, wrist_id, :3].tolist()
            for robot, wrist_id in zip(env.robots, env.wrist_ids, strict=True)
        ]
        contact_free = all(value <= 1.0e-3 for value in forces.values())
        report = {
            "candidate_home_used": True,
            "maximum_home_error_deg_or_mm": float(home_error.max()),
            "finite_state": bool(np.isfinite(state).all()),
            "maximum_arm_contact_force_n": forces,
            "collision_free_at_home": contact_free,
            "home_tcp_world_m": {"left": tcp_positions[0], "right": tcp_positions[1]},
            "home_tcp_separation_m": float(
                np.linalg.norm(np.asarray(tcp_positions[0]) - np.asarray(tcp_positions[1]))
            ),
            "maximum_profile_reset_position_error_m": max(reset_errors, default=0.0),
            "wrist_shapes": wrist_shapes,
            "scene_camera": {
                "shape": list(scene_image.shape),
                "dtype": str(scene_image.dtype),
                "rgb_stddev": float(scene_image.astype(np.float32).std()),
                "frame": int(_cpu(self.camera_rig.scene_camera.frame)[0]),
            },
            "imported_prim_valid": imports,
            "required_prim_valid": required_prims,
            "table_collision_api": bool(table_collision),
        }
        threshold = float(self.config["validation"]["maximum_home_drift_deg"])
        report["passed"] = bool(
            report["finite_state"]
            and report["maximum_home_error_deg_or_mm"] <= threshold
            and report["collision_free_at_home"]
            and report["maximum_profile_reset_position_error_m"]
            <= float(self.config["validation"]["profile_reset_position_tolerance_m"])
            and wrist_shapes == {"left_wrist": [480, 640, 3], "right_wrist": [480, 640, 3]}
            and report["scene_camera"]["shape"] == [480, 640, 3]
            and report["scene_camera"]["dtype"] == "uint8"
            and report["scene_camera"]["rgb_stddev"]
            >= float(self.config["validation"]["minimum_scene_rgb_stddev"])
            and all(imports.values())
            and all(required_prims.values())
            and report["table_collision_api"]
        )
        self.validation = report
        # Contact tensors are a preflight-only check.  Keep their PhysX reporters
        # intact, but stop forcing tensor reads on every physical teleop frame.
        self._validation_complete = True
        return report


def _camera_cfg(prim_path: str, camera: dict[str, Any], *, rgba: bool) -> CameraCfg:
    return CameraCfg(
        prim_path=prim_path,
        update_period=0.0,
        height=int(camera["height"]),
        width=int(camera["width"]),
        # The XR presenter consumes RGBA.  The unchanged D0 facade above exposes
        # its first three channels as RGB, avoiding a duplicate wrist annotator.
        data_types=["rgba"] if rgba else ["rgb"],
        update_latest_camera_pose=True,
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=float(camera["focal_length_mm"]),
            focus_distance=1.0,
            horizontal_aperture=float(camera["horizontal_aperture_mm"]),
            clipping_range=tuple(camera["clipping_range_m"]),
        ),
        offset=CameraCfg.OffsetCfg(
            pos=tuple(camera.get("offset_xyz_m", (0.0, 0.0, 0.0))),
            rot=tuple(camera.get("offset_quat_xyzw", (0.0, 0.0, 0.0, 1.0))),
            convention="world",
        ),
    )


def _spawn_static_scene(config: dict[str, Any]) -> None:
    scene = config["scene"]
    floor = scene["floor"]
    ground = sim_utils.GroundPlaneCfg(size=tuple(floor["size_m"]), color=tuple(floor["color_rgb"]))
    ground.func("/World/Ground", ground)
    table = scene["table"]
    table_cfg = sim_utils.CuboidCfg(
        size=tuple(table["size_m"]),
        collision_props=sim_utils.CollisionPropertiesCfg(),
        physics_material=sim_utils.RigidBodyMaterialCfg(
            static_friction=float(table["static_friction"]),
            dynamic_friction=float(table["dynamic_friction"]),
        ),
        visual_material=sim_utils.PreviewSurfaceCfg(
            diffuse_color=tuple(table["color_rgb"]), roughness=0.72
        ),
    )
    table_cfg.func("/World/RobosynDemo/Table", table_cfg, translation=tuple(table["center_m"]))
    backdrop = scene["backdrop"]
    backdrop_cfg = sim_utils.CuboidCfg(
        size=tuple(backdrop["size_m"]),
        visual_material=sim_utils.PreviewSurfaceCfg(
            diffuse_color=tuple(backdrop["color_rgb"]), roughness=0.85
        ),
    )
    backdrop_cfg.func(
        "/World/RobosynDemo/Backdrop", backdrop_cfg, translation=tuple(backdrop["center_m"])
    )
    dome = scene["lighting"]["dome"]
    dome_cfg = sim_utils.DomeLightCfg(
        intensity=float(dome["intensity"]), color=tuple(dome["color_rgb"])
    )
    dome_cfg.func("/World/RobosynDemo/DomeLight", dome_cfg)
    key = scene["lighting"]["key"]
    key_cfg = sim_utils.DistantLightCfg(
        intensity=float(key["intensity"]),
        color=tuple(key["color_rgb"]),
        angle=float(key["angle_deg"]),
    )
    key_cfg.func(
        "/World/RobosynDemo/KeyLight",
        key_cfg,
        orientation=(0.270598, -0.270598, -0.653281, 0.653281),
    )


def _rigid_cube(path: str, item: dict[str, Any]) -> RigidObject:
    return RigidObject(
        RigidObjectCfg(
            prim_path=path,
            spawn=sim_utils.CuboidCfg(
                size=(float(item["edge_m"]),) * 3,
                rigid_props=sim_utils.RigidBodyPropertiesCfg(max_depenetration_velocity=1.0),
                mass_props=sim_utils.MassPropertiesCfg(mass=0.035),
                collision_props=sim_utils.CollisionPropertiesCfg(),
                physics_material=sim_utils.RigidBodyMaterialCfg(
                    static_friction=0.8, dynamic_friction=0.6
                ),
                visual_material=sim_utils.PreviewSurfaceCfg(
                    diffuse_color=tuple(item["color_rgb"]), roughness=0.42
                ),
            ),
            init_state=RigidObjectCfg.InitialStateCfg(pos=tuple(item["position_m"])),
        )
    )


def _spawn_task_profile(config: dict[str, Any]) -> tuple[list[Any], dict[str, str]]:
    profile = config["profiles"]["dual_cube_to_matching_plates"]
    objects = [
        _rigid_cube("/World/RobosynDemo/LeftCube", profile["left_cube"]),
        _rigid_cube("/World/RobosynDemo/RightCube", profile["right_cube"]),
    ]
    for side in ("left", "right"):
        plate = profile[f"{side}_plate"]
        plate_cfg = sim_utils.CylinderCfg(
            radius=float(plate["diameter_m"]) / 2.0,
            height=float(plate["thickness_m"]),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            visual_material=sim_utils.PreviewSurfaceCfg(
                diffuse_color=tuple(plate["color_rgb"]), roughness=0.5
            ),
        )
        plate_cfg.func(
            f"/World/RobosynDemo/{side.title()}Plate",
            plate_cfg,
            translation=tuple(plate["position_m"]),
        )
    return objects, {}


def _spawn_asset_profile() -> tuple[list[Any], dict[str, str]]:
    button_source = ROBOSYN_ROOT / "assets/button/button.urdf"
    button_hash = hashlib.sha256(button_source.read_bytes()).hexdigest()
    button_converter = sim_utils.UrdfConverter(
        sim_utils.UrdfConverterCfg(
            asset_path=str(button_source),
            usd_dir=str(CONVERTED_ROOT / f"button-{button_hash}"),
            fix_base=True,
            merge_fixed_joints=False,
            self_collision=False,
            run_multi_physics_conversion=False,
            joint_drive=sim_utils.UrdfConverterCfg.JointDriveCfg(
                drive_type="force",
                target_type="position",
                gains=sim_utils.UrdfConverterCfg.JointDriveCfg.PDGainsCfg(
                    stiffness=40.0, damping=2.0
                ),
            ),
        )
    )
    button = Articulation(
        ArticulationCfg(
            prim_path="/World/RobosynDemo/TestAssets/Button",
            spawn=sim_utils.UsdFileCfg(usd_path=button_converter.usd_path),
            init_state=ArticulationCfg.InitialStateCfg(
                pos=(0.88, 0.28, 0.84), joint_pos={"press": 0.0}, joint_vel={"press": 0.0}
            ),
            actuators={
                "press": ImplicitActuatorCfg(
                    joint_names_expr=["press"],
                    effort_limit_sim=1.0,
                    velocity_limit_sim=1.0,
                    stiffness=40.0,
                    damping=2.0,
                )
            },
        )
    )
    pen_source = ROBOSYN_ROOT / "assets/Pen/the_pen.obj"
    pen_hash = hashlib.sha256(pen_source.read_bytes()).hexdigest()
    pen_converter = sim_utils.MeshConverter(
        sim_utils.MeshConverterCfg(
            asset_path=str(pen_source),
            usd_dir=str(CONVERTED_ROOT / f"pen-{pen_hash}"),
            usd_file_name="pen.usd",
            force_usd_conversion=False,
            make_instanceable=True,
            scale=(1.0, 1.6, 1.6),
            mass_props=sim_utils.MassPropertiesCfg(mass=0.005),
            rigid_props=sim_utils.RigidBodyPropertiesCfg(max_depenetration_velocity=1.0),
            collision_props=sim_utils.CollisionPropertiesCfg(),
            mesh_collision_props=sim_utils.ConvexHullPropertiesCfg(),
        )
    )
    pen = RigidObject(
        RigidObjectCfg(
            prim_path="/World/RobosynDemo/TestAssets/Pen",
            spawn=sim_utils.UsdFileCfg(usd_path=pen_converter.usd_path),
            init_state=RigidObjectCfg.InitialStateCfg(pos=(0.88, -0.22, 0.835)),
        )
    )
    beaker_path = "/World/RobosynDemo/TestAssets/Beaker"
    beaker_cfg = sim_utils.UsdFileCfg(
        usd_path=str(ROBOSYN_ROOT / "assets/Beaker/Beaker.usd"), scale=(0.014, 0.014, 0.015)
    )
    beaker_cfg.func(beaker_path, beaker_cfg, translation=(1.02, 0.0, 0.825))
    return [button, pen], {
        "robosyn_button": "/World/RobosynDemo/TestAssets/Button",
        "robosyn_pen": "/World/RobosynDemo/TestAssets/Pen",
        "robosyn_beaker": beaker_path,
    }


def _demo_robot_cfg(
    robot_cfg_factory,
    config: dict[str, Any],
    prim_path: str,
    position: tuple[float, float, float],
    usd_path: str,
    *,
    home_per_arm: np.ndarray,
) -> ArticulationCfg:
    """Keep imported mimic followers passive in this experiment scene."""

    cfg = robot_cfg_factory(
        prim_path,
        position,
        usd_path,
        home_per_arm=home_per_arm,
        enable_self_collisions=True,
        activate_contact_sensors=True,
    )
    gripper = config["demo_physics"]["gripper_contact"]
    leader = gripper["leader_drive"]
    follower = gripper["mimic_follower_drive"]
    cfg.actuators["gripper_position_drives"] = ImplicitActuatorCfg(
        joint_names_expr=[str(gripper["leader_joint"])],
        effort_limit_sim=float(leader["effort_limit_n"]),
        velocity_limit_sim=float(leader["velocity_limit_m_s"]),
        stiffness=float(leader["stiffness_n_m"]),
        damping=float(leader["damping_n_s_m"]),
    )
    cfg.actuators["gripper_mimic_followers"] = ImplicitActuatorCfg(
        joint_names_expr=[str(gripper["mimic_follower_joint_expr"])],
        effort_limit_sim=float(follower["effort_limit_n"]),
        velocity_limit_sim=float(follower["velocity_limit_m_s"]),
        stiffness=float(follower["stiffness_n_m"]),
        damping=float(follower["damping_n_s_m"]),
    )
    return cfg


def _physics_probe() -> RigidObject:
    return RigidObject(
        RigidObjectCfg(
            prim_path="/World/RobosynDemo/ValidationProbe",
            spawn=sim_utils.CuboidCfg(
                size=(0.02, 0.02, 0.02),
                rigid_props=sim_utils.RigidBodyPropertiesCfg(),
                mass_props=sim_utils.MassPropertiesCfg(mass=0.01),
                collision_props=sim_utils.CollisionPropertiesCfg(),
                visual_material=sim_utils.PreviewSurfaceCfg(
                    diffuse_color=(0.25, 0.25, 0.25), opacity=0.0
                ),
            ),
            init_state=RigidObjectCfg.InitialStateCfg(pos=(2.0, 2.0, 0.5)),
        )
    )


def _arm_contact_sensors(sim, arm_path: str) -> list[ContactSensor]:
    from pxr import Usd, UsdPhysics  # type: ignore[import-not-found]

    body_paths = [
        str(prim.GetPath())
        for prim in Usd.PrimRange(sim.stage.GetPrimAtPath(arm_path))
        if prim.HasAPI(UsdPhysics.RigidBodyAPI) and prim.GetName() != "base_link"
    ]
    if not body_paths:
        raise RuntimeError(f"no articulated arm bodies found for contact smoke: {arm_path}")
    return [
        ContactSensor(
            ContactSensorCfg(
                prim_path=path,
                update_period=0.0,
                history_length=1,
                debug_vis=False,
            )
        )
        for path in body_paths
    ]


def run_robosyn_vr_demo(
    args_cli,
    simulation_app,
    *,
    urdf_path: Path,
    urdf_sha: str,
    robot_cfg_factory,
    wrist_path_resolver,
    environment_type,
) -> int:
    """Build the fixed experiment scene, validate it, then enter the existing S2 loop."""

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    print(f"[DEMO] profile={args_cli.demo_profile} TEST_ONLY / NOT_APPROVED_FOR_PRODUCTION")
    sim = sim_utils.SimulationContext(
        sim_utils.SimulationCfg(
            dt=PHYSICS_DT, render_interval=1, device=args_cli.device, use_fabric=True
        )
    )
    _spawn_static_scene(config)
    dynamic_assets, imported_prims = (
        _spawn_task_profile(config)
        if args_cli.demo_profile == "dual_cube_to_matching_plates"
        else _spawn_asset_profile()
    )
    probe = _physics_probe()
    converter = sim_utils.UrdfConverter(
        sim_utils.UrdfConverterCfg(
            asset_path=str(urdf_path),
            usd_dir=f"/data/ebulochkin/assets/isaac_s1/converted/{urdf_sha}",
            fix_base=True,
            merge_fixed_joints=False,
            self_collision=False,
            robot_type="Manipulator",
            run_multi_physics_conversion=False,
            ros_package_paths=[{"name": "agx_arm_description", "path": "/data/ebulochkin/assets"}],
            joint_drive=sim_utils.UrdfConverterCfg.JointDriveCfg(
                drive_type="force",
                target_type="position",
                gains=sim_utils.UrdfConverterCfg.JointDriveCfg.PDGainsCfg(
                    stiffness=400.0, damping=40.0
                ),
            ),
        )
    )
    homes = config["scene"]["candidate_home_d0_per_arm"]
    home_left = np.asarray(homes["left"], dtype=np.float64)
    home_right = np.asarray(homes["right"], dtype=np.float64)
    bases = config["scene"]["robot_bases_m"]
    left = Articulation(
        _demo_robot_cfg(
            robot_cfg_factory,
            config,
            "/World/LeftPiper",
            tuple(bases["left"]),
            converter.usd_path,
            home_per_arm=home_left,
        )
    )
    right = Articulation(
        _demo_robot_cfg(
            robot_cfg_factory,
            config,
            "/World/RightPiper",
            tuple(bases["right"]),
            converter.usd_path,
            home_per_arm=home_right,
        )
    )
    wrist_paths = tuple(
        wrist_path_resolver(sim, arm) for arm in ("/World/LeftPiper", "/World/RightPiper")
    )
    wrist_cfg = config["cameras"]["wrist"]
    wrist_camera_cfgs = tuple(
        _camera_cfg(f"{path}/S1WristCamera", wrist_cfg, rgba=True) for path in wrist_paths
    )
    wrist_cameras = tuple(Camera(cfg) for cfg in wrist_camera_cfgs)
    scene_cfg = _camera_cfg(
        "/World/RobosynDemo/SceneCamera", config["cameras"]["scene"], rgba=False
    )
    scene_camera = Camera(scene_cfg)
    camera_rig = DemoCameraRig(wrist_cameras, scene_camera)
    contacts = {
        side.lower(): _arm_contact_sensors(sim, f"/World/{side.title()}Piper")
        for side in ("left", "right")
    }
    runtime = DemoRuntime(
        config=config,
        profile=args_cli.demo_profile,
        camera_rig=camera_rig,
        camera_cfgs=wrist_camera_cfgs,
        dynamic_assets=dynamic_assets,
        contact_sensors=contacts,
        imported_prims=imported_prims,
        hud_on_start=bool(args_cli.demo_hud_on_start),
    )
    sim.reset()
    scene_camera.set_world_poses_from_view(
        torch.tensor([config["cameras"]["scene"]["eye_m"]], device=sim.device),
        torch.tensor([config["cameras"]["scene"]["target_m"]], device=sim.device),
    )
    env = environment_type(
        sim,
        left,
        right,
        camera_rig,
        wrist_paths,
        "two_named_demo_wrist_cameras",
        probe,
        home_d0=np.concatenate((home_left, home_right)),
        experiment_runtime=runtime,
    )
    env.scene = SimpleNamespace(
        sensors={"left_wrist": wrist_cameras[0], "right_wrist": wrist_cameras[1]}
    )
    env.reset(0)
    env._advance(int(config["validation"]["settle_physics_steps"]) - 25)
    validation = runtime.validate(env)
    print(f"[DEMO] validation={validation}", flush=True)
    if not validation["passed"]:
        raise RuntimeError(f"RoboSyn demo preflight failed: {validation}")
    if args_cli.demo_scene_preview is not None:
        from PIL import Image

        preview = _cpu(scene_camera.data.output["rgb"])[0]
        args_cli.demo_scene_preview.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(preview).save(args_cli.demo_scene_preview)
        print(f"[DEMO] scene preview={args_cli.demo_scene_preview}", flush=True)
    from isaac_s2_runtime import run_s2

    return run_s2(env, args_cli, simulation_app)
