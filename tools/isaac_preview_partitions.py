"""Explicit RTX topology for shared-world SceneUI, Kit >=110.3 only."""
from __future__ import annotations

PREVIEW = "vla_xr_preview"
SENSOR = "vla_sensor_world"


class PreviewPartitions:
    def __init__(self, stage):
        import carb.settings
        import omni.kit.app
        from omni.kit.scene_view.xr import XRSceneView
        from pxr import Sdf

        version = omni.kit.app.get_app().get_kit_version()
        if tuple(int(n) for n in version.split('+')[0].split('.')[:2]) < (110, 3):
            raise RuntimeError(f"Preview isolation requires Kit >=110.3, got {version}")
        self.stage = stage
        self.settings = carb.settings.get_settings()
        self.base = str(XRSceneView.get_base_path())
        path = Sdf.Path(self.base)
        if not path.IsAbsolutePath() or path == Sdf.Path('/') or path.HasPrefix(Sdf.Path('/World')):
            raise RuntimeError(f"Unsafe XR UI partition root: {self.base}")
        self.camera_paths = []
        self.panel_paths = set()
        self.authored_panel_paths = set()

    def bind_sensors(self, cameras):
        from pxr import Sdf, Usd, UsdGeom
        for prim in self.stage.Traverse():
            if prim.GetPath().HasPrefix(Sdf.Path('/World')) and prim.IsA(UsdGeom.Gprim):
                pv = UsdGeom.PrimvarsAPI(prim).FindPrimvarWithInheritance('omni:scenePartition')
                if pv and pv.Get():
                    raise RuntimeError(f"Expected unpartitioned demo world: {prim.GetPath()}")
        self.camera_paths = [camera.cfg.prim_path for camera in cameras]
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            for path in self.camera_paths:
                prim = self.stage.GetPrimAtPath(path)
                if not prim or not prim.IsA(UsdGeom.Camera):
                    raise RuntimeError(f"Missing sensor camera: {path}")
                old = prim.GetAttribute('omni:scenePartition')
                if old and old.Get() not in (None, '', SENSOR):
                    raise RuntimeError(f"Conflicting sensor partition: {path}")
                prim.CreateAttribute('omni:scenePartition', Sdf.ValueTypeNames.Token).Set(SENSOR)
        self.assert_valid()

    def assert_valid(self):
        from pxr import UsdGeom
        for setting in ('/renderer/scenePartitioning/enabled',
                        '/rtx/scenePartitioning/showAllPartitionsByDefault'):
            if self.settings.get(setting) is not True:
                raise RuntimeError(f"Preview isolation setting lost: {setting}")
        for path in self.panel_paths:
            root = self.stage.GetPrimAtPath(path)
            if not root or UsdGeom.PrimvarsAPI(root).GetPrimvar('omni:scenePartition').Get() != PREVIEW:
                raise RuntimeError(f'Preview isolation lost: {path}; rebind before rendering')
        for path in self.camera_paths:
            prim = self.stage.GetPrimAtPath(path)
            if not prim or prim.GetAttribute('omni:scenePartition').Get() != SENSOR:
                raise RuntimeError(f"Sensor isolation lost: {path}; rebind before rendering")
        xr_camera = self.stage.GetPrimAtPath('/_xr/stage/xrCamera')
        if xr_camera:
            token = xr_camera.GetAttribute('omni:scenePartition')
            if token and token.Get() not in (None, '', PREVIEW):
                raise RuntimeError('XR camera partition cannot see preview UI')

    def check_panel(self, panel):
        from pxr import Sdf, Usd, UsdGeom
        view = panel._container.scene_view
        # Public scene-to-USD update, NOT an app/render tick. Bind the concrete
        # draw system before the first render and every time it is shown again.
        # Tagging /ui once was empirically insufficient for dynamic SceneUI.
        view.run_update()
        path = Sdf.Path(str(view.system_path))
        if not path.HasPrefix(Sdf.Path(self.base)) or path == Sdf.Path(self.base):
            raise RuntimeError(f'Unexpected preview draw system: {path}')
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            root = self.stage.OverridePrim(path)
            UsdGeom.PrimvarsAPI(root).CreatePrimvar('omni:scenePartition',
                Sdf.ValueTypeNames.Token, UsdGeom.Tokens.constant).Set(PREVIEW)
        self.panel_paths.add(str(path))
        self.authored_panel_paths.add(str(path))
        self.assert_valid()

    def release_panel(self, panel):
        # Closing/hiding destroys the draw system. A future show must bind it
        # again before rendering; do not keep asserting a removed resource.
        self.panel_paths.discard(str(panel._container.scene_view.system_path))

    def report(self):
        return {'enabled': True, 'ui_base': self.base, 'panel_roots': sorted(self.authored_panel_paths),
                'active_panel_roots': sorted(self.panel_paths), 'preview_token': PREVIEW,
                'sensor_token': SENSOR, 'sensor_paths': self.camera_paths,
                'world': 'unpartitioned/shared', 'xr': 'unassigned spectator, showAllPartitionsByDefault=true'}
