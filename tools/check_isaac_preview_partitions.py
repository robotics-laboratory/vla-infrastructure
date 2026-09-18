"""RTX regression for the integrated draw-system policy; bounded image retention.

Diagnostic-only scene. Witness cameras verify visibility; no physical Quest claim.
"""
import argparse
import gc
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import traceback
from types import SimpleNamespace

from isaaclab.app import AppLauncher

p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
p.add_argument('--frames', type=int, default=100)
p.add_argument('--cameras', type=int, choices=(1, 3), default=3)
p.add_argument('--mode', choices=('control', 'partition'), default='partition')
p.add_argument('--motion', action='store_true')
p.add_argument('--live', action='store_true')
p.add_argument('--lifecycle', action='store_true')
p.add_argument('--recreate-cameras', action='store_true', help='Opt in to the known upstream camera teardown risk')
p.add_argument('--activate-xr', action='store_true')
p.add_argument('--restart-xr', action='store_true', help='Opt in to upstream live XR restart diagnostics')
p.add_argument('--epochs', type=int, choices=(1, 2), default=1)
p.add_argument('--reset-policy', choices=('coalesced', 'double'), default='coalesced')
p.add_argument('--width', type=int, default=640)
p.add_argument('--height', type=int, default=480)
AppLauncher.add_app_launcher_args(p)
args = p.parse_args()
args.enable_cameras = True
args.headless = True
args.output.mkdir(parents=True, exist_ok=False)
app = AppLauncher(args).app

import carb.settings
import numpy as np
from PIL import Image
import torch
import warp as wp
import omni.kit.app
import omni.ui.scene as sc
import omni.usd
import usdrt
from pxr import Gf, Usd, UsdGeom
import isaaclab.sim as sim_utils
from isaaclab.sensors import Camera, CameraCfg
from isaaclab_physx.renderers import IsaacRtxRendererCfg
from isaaclab_teleop.camera_feed_kit_scene_ui import _KitSceneUiCameraFeedPresenter

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'tools'))
from isaac_robosyn_vr_demo import _CpuStagedFeedPresenter
from isaac_preview_partitions import PreviewPartitions, PREVIEW, SENSOR
from pxr import Sdf


def inventory(stage, roots, *, enforce):
    result = []
    for path in roots:
        prim = stage.GetPrimAtPath(path)
        if not prim:
            raise RuntimeError(f'Missing panel root: {path}')
        for child in Usd.PrimRange(prim):
            pv = UsdGeom.PrimvarsAPI(child).FindPrimvarWithInheritance('omni:scenePartition')
            token = pv.Get() if pv else None
            if enforce and child.IsA(UsdGeom.Gprim) and token != PREVIEW:
                raise RuntimeError(f'Panel escaped ancestor partition: {child.GetPath()}')
            result.append({'path': str(child.GetPath()), 'type': child.GetTypeName(),
                           'partition': token,
                           'world_matrix': str(UsdGeom.XformCache().GetLocalToWorldTransform(child))})
    return result


def tensor(value):
    if isinstance(value, torch.Tensor):
        return value
    return value.torch if hasattr(value, 'torch') else wp.to_torch(value)


def pixels(value):
    value = tensor(value)
    return value.reshape(args.height, args.width, -1).detach().cpu().contiguous().numpy().copy()


def marker_count(image):
    a = image.astype(np.int16)
    return int(((a[..., 0] > 150) & (a[..., 2] > 150) & (a[..., 1] < 110)
                & (a[..., 0] - a[..., 1] > 60)).sum())


def world_count(image):
    a = image.astype(np.int16)
    return int(((a[..., 1] > 80) & (a[..., 1] - a[..., 0] > 30)
                & (a[..., 1] - a[..., 2] > 30)).sum())


def main():
    settings = carb.settings.get_settings()
    sim = sim_utils.SimulationContext(sim_utils.SimulationCfg(device='cuda:0'))
    stage = omni.usd.get_context().get_stage()
    isolation = PreviewPartitions(stage) if args.mode == 'partition' else None
    fabric = usdrt.Usd.Stage.Attach(omni.usd.get_context().get_stage_id())
    light = sim_utils.DistantLightCfg(intensity=2000.)
    light.func('/World/Light', light)
    for i in range(args.cameras):
        box = sim_utils.CuboidCfg(size=(.20 + i*.03, .20, .20),
            visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0., 1., 0.)))
        box.func(f'/World/Reference{i}', box, translation=(i * 4. + .5, 0., 0.))
        for j, x in enumerate((-1., 1.6)):
            box.func(f'/World/ReferenceExtra{i}_{j}', box, translation=(i * 4. + x, .25, 0.))
    def make_camera(path):
        return Camera(CameraCfg(prim_path=path, update_period=0., width=args.width,
            height=args.height, data_types=['rgba'],
            renderer_cfg=IsaacRtxRendererCfg(enable_scene_partitioning=False),
            spawn=sim_utils.PinholeCameraCfg(focal_length=20., horizontal_aperture=20.,
                                           clipping_range=(.01, 100.))))
    sensors = [make_camera(f'/World/Sensor{i}') for i in range(args.cameras)]
    witnesses = [make_camera(f'/World/Witness{i}') for i in range(args.cameras)]
    if isolation:
        isolation.bind_sensors(sensors)
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            for camera in witnesses:
                stage.GetPrimAtPath(camera.cfg.prim_path).CreateAttribute(
                    'omni:scenePartition', Sdf.ValueTypeNames.Token).Set(PREVIEW)
    sim.reset()
    presenter = _CpuStagedFeedPresenter(_KitSceneUiCameraFeedPresenter(), isolation)
    panels = []
    roots = []
    def create_panel(i):
        desc = SimpleNamespace(placement='world', width_m=.7, label=None, offset_m=(0., 0.),
            distance_m=1., world_position_m=(i * 4., 0., .2),
            world_orientation_xyzw=(0., 0., 0., 1.))
        panel = presenter.create_panel(desc, args.width, args.height)
        panel._container.scene_view.run_update()
        root = str(panel._container.scene_view.system_path)
        return panel, root
    yy, xx = np.indices((args.height, args.width))
    checker = np.full((args.height, args.width, 4), 255, dtype=np.uint8)
    checker[..., 1] = ((xx // 24 + yy // 24) % 2) * 255
    for i in range(args.cameras):
        panel, root = create_panel(i)
        panel.upload(torch.from_numpy(checker.copy()))
        panels.append(panel)
        roots.append(root)
    core = None
    if args.activate_xr:
        from omni.kit.xr.core import XRCore
        core = XRCore.get_singleton()
        core.request_enable_profile('ar')
    app_api = omni.kit.app.get_app()
    ext_manager = app_api.get_extension_manager()
    (args.output / 'runtime.json').write_text(json.dumps({
        'kit': app_api.get_kit_version(), 'argv': sys.argv,
        'source_sha256': {str(path.relative_to(project)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (Path(__file__).resolve(), project/'tools/isaac_preview_partitions.py',
                                       project/'tools/isaac_robosyn_vr_demo.py')},
        'extensions': [e for e in ext_manager.get_extensions() if e.get('enabled')],
        'topology': {'world': 'unpartitioned/shared', 'sensors': SENSOR, 'panels': PREVIEW,
                     'witnesses': PREVIEW, 'xr': 'unassigned spectator; actual state recorded'},
        'physical_quest': False}, indent=2, default=str))
    first = None
    witness_frames = [0] * args.cameras
    world_frames = [0] * args.cameras
    durations = []
    panels_visible = True
    with (args.output / 'frames.jsonl').open('w', buffering=1) as log:
        for frame in range(args.frames):
            start = time.monotonic_ns()
            events = []
            reset_due = args.lifecycle and frame > 0 and frame % 600 == 0
            recreate_due = args.recreate_cameras and frame > 0 and frame % 900 == 0
            if args.lifecycle and frame > 0 and frame % 250 == 0:
                i = (frame // 250 - 1) % args.cameras
                panels[i].close()
                panels[i], roots[i] = create_panel(i)
                panels[i].upload(torch.from_numpy(checker.copy()))
                events.append(f'recreate_panel_{i}')
            if reset_due:
                if args.reset_policy == 'double':
                    sim.reset()
                events.append('simulation_reset')
            if recreate_due:
                old_path = sensors[0].cfg.prim_path
                sensors[0] = None
                del sensor  # Drop the previous capture loop's reference too (one-camera epoch).
                gc.collect()  # Camera.__del__ owns render-product/annotator cleanup.
                stage.RemovePrim(old_path)
                parent = f'/World/RecreatedParent{frame}'
                stage.DefinePrim(parent, 'Xform')
                sensors[0] = make_camera(parent + '/Sensor0')
                if isolation:
                    isolation.bind_sensors(sensors)
                events.append('camera0_recreated_under_new_parent')
            if recreate_due or (reset_due and args.reset_policy == 'coalesced'):
                sim.reset()
            if args.lifecycle and frame % 400 in (350, 370):
                visible = frame % 400 == 370
                for panel in panels:
                    if isolation and not visible:
                        isolation.release_panel(panel)
                    panel._container.show() if visible else panel._container.hide()
                panels_visible = visible
                if visible:
                    for i, panel in enumerate(panels):
                        panel._container.scene_view.run_update()
                        roots[i] = str(panel._container.scene_view.system_path)
                        if isolation:
                            isolation.check_panel(panel)
                events.append('preview_show' if visible else 'preview_hide')
            if args.restart_xr and core and frame in (1200, 1240):
                core.request_disable_profile() if frame == 1200 else core.request_enable_profile('ar')
                events.append('xr_disable' if frame == 1200 else 'xr_enable')
            for i, (sensor, witness, panel) in enumerate(zip(sensors, witnesses, panels)):
                phase = frame / 15. + i * .3
                common = 1.2 * math.sin(phase * .3) if args.motion else 0.
                dx = common + .25 * math.sin(phase) if args.motion else 0.
                dy = .12 * math.cos(phase) if args.motion else 0.
                if args.lifecycle and frame % 180 < 3:
                    dx += .3 * (1 if frame % 2 else -1)
                    events.append(f'teleport_parent_{i}')
                panel._container.root.transform = sc.Matrix44.get_translation_matrix(dx, dy, 0.)
                eye = torch.tensor([[i * 4. + common + (.25 * math.sin(phase*.7) if args.motion else 0.), 0., 2.]], device='cuda:0')
                UsdGeom.XformCommonAPI(stage.GetPrimAtPath(f'/World/Reference{i}')).SetTranslate(
                    Gf.Vec3d(float(eye[0, 0]) + .5, 0., 0.))
                angle = .08 * math.sin(phase*.5) if args.motion else 0.
                rotation = torch.tensor([[0., math.sin(angle/2), 0., math.cos(angle/2)]], device='cuda:0')
                for cam in (sensor, witness):
                    cam.set_world_poses(eye, rotation, convention='opengl')
            if isolation:
                isolation.assert_valid()
            sim.step()
            for camera in sensors + witnesses:
                camera.update(sim.get_physics_dt(), force_recompute=True)
            for panel in panels:
                panel._container.scene_view.run_update()
            render_end = time.monotonic_ns()
            record = {'frame_id': frame, 'frame_id_kind': 'harness iteration; camera counters also recorded',
                'monotonic_ns': render_end, 'wall_ns': time.time_ns(), 'events': events,
                'kit_update': app_api.get_update_number(),
                'settings': {key: settings.get(key) for key in (
                    '/renderer/scenePartitioning/enabled', '/rtx/scenePartitioning/showAllPartitionsByDefault',
                    '/app/asyncRendering', '/app/asyncRenderingLowLatency')},
                'preview': inventory(stage, roots if panels_visible else
                    [r for r in roots if stage.GetPrimAtPath(r)], enforce=args.mode == 'partition'),
                'preview_visible_command': panels_visible,
                'hidden_roots': [] if panels_visible else roots[:],
                'head_pose': None, 'controller_poses': None,
                'physical_tracking_status': 'not verified: operator unavailable', 'cameras': []}
            record['fabric'] = {}
            for path in [s.cfg.prim_path for s in sensors] + [r['path'] for r in record['preview']]:
                prim = fabric.GetPrimAtPath(path)
                record['fabric'][path] = {key: str(prim.GetAttribute(key).Get()) for key in (
                    'omni:fabric:worldMatrix', '_worldPosition', '_worldOrientation',
                    'xformOp:transform', 'primvars:omni:scenePartition', 'omni:scenePartition')
                    if prim and prim.GetAttribute(key)}
            if core:
                import omni.kit.xr.system.openxr as oxr
                record['xr_session'] = oxr.get_session_handle()
                record['xr_profile'] = core.get_current_profile_name()
                record['xr_input_devices'] = [
                    {'name': str(d.get_name()), 'type': str(d.get_type()),
                     'raw_poses': {str(name): {'matrix_rows': [list(row) for row in pose.pose_matrix],
                                              'validity_flags': int(pose.validity_flags)}
                                   for name, pose in d.get_all_raw_poses().items()}}
                    for d in core.get_all_input_devices()]
            for i, (sensor, witness, panel) in enumerate(zip(sensors, witnesses, panels)):
                dest = args.output / 'images' / f'{frame:05d}' / str(i)
                images = {'sensor_raw': pixels(sensor._render_data.annotators['rgba'].get_data(do_array_copy=False)),
                          'camera_rgba': pixels(sensor.data.output['rgba']),
                          'preview_input': pixels(panel._retained_image),
                          'witness': pixels(witness.data.output['rgba'])}
                counts = {key: marker_count(image) for key, image in images.items()}
                if max(counts['sensor_raw'], counts['camera_rgba']) > 0 and first is None:
                    first = {'frame': frame, 'camera': i, 'counts': counts}
                witness_frames[i] += counts['witness'] > 0
                world_frames[i] += world_count(images['sensor_raw']) > 0
                if frame in (4, args.frames - 1) or (first and first['frame'] == frame):
                    dest.mkdir(parents=True, exist_ok=True)
                    for key, image in images.items():
                        Image.fromarray(image).save(dest / f'{key}.png', compress_level=1)
                record['cameras'].append({'index': i, 'marker_pixels': counts,
                    'world_pixels': world_count(images['sensor_raw']), 'capture_ns': time.monotonic_ns(),
                    'camera_frame': tensor(sensor.frame).cpu().tolist(),
                    'camera_prim': sensor.cfg.prim_path, 'preview_prim': roots[i],
                    'render_product': str(sensor._render_data.render_product.path),
                    'position': tensor(sensor.data.pos_w).cpu().tolist(),
                    'orientation_xyzw': tensor(sensor.data.quat_w_world).cpu().tolist(),
                    'camera_partition': stage.GetPrimAtPath(sensor.cfg.prim_path).GetAttribute('omni:scenePartition').Get(),
                    'parent_command': str(panel._container.root.transform)})
                image = images['camera_rgba'].copy() if args.live else checker.copy()
                # Sentinel belongs only to the presentation input, not sensor/world.
                if args.live:
                    image[(xx % 64 < 12) & (yy % 64 < 12)] = (255, 0, 255, 255)
                image[0:8, 100:140, :3] = ((frame * 7 + i * 70) % 255)
                panel.upload(torch.from_numpy(image))
            durations.append((render_end-start)/1e6)
            record['render_iteration_ms'] = durations[-1]
            record['capture_and_upload_ms'] = (time.monotonic_ns()-render_end)/1e6
            log.write(json.dumps(record, default=str) + '\n')
            if frame % 100 == 0:
                print('QUALIFICATION', frame, 'first_sensor_marker', first, flush=True)
    guard_checks = {}
    if isolation:
        for label, attr in (
            ('sensor_token', stage.GetPrimAtPath(sensors[0].cfg.prim_path).GetAttribute('omni:scenePartition')),
            ('panel_token', stage.GetPrimAtPath(roots[0]).GetAttribute('primvars:omni:scenePartition')),
        ):
            with Usd.EditContext(stage, stage.GetSessionLayer()):
                original = attr.Get()
                attr.Set('deliberately_invalid')
                try:
                    isolation.assert_valid()
                    guard_checks[label] = False
                except RuntimeError:
                    guard_checks[label] = True
                finally:
                    attr.Set(original)
        setting = '/renderer/scenePartitioning/enabled'
        settings.set_bool(setting, False)
        try:
            isolation.assert_valid()
            guard_checks['global_setting'] = False
        except RuntimeError:
            guard_checks['global_setting'] = True
        finally:
            settings.set_bool(setting, True)
        isolation.assert_valid()
        if not all(guard_checks.values()):
            raise RuntimeError('Fail-closed guard did not reject an invalid topology')
    result = {'frames': args.frames, 'cameras': args.cameras, 'mode': args.mode,
              'first_sensor_marker': first, 'witness_positive_frames': witness_frames,
              'world_positive_frames': world_frames, 'physical_quest_pass': False, 'fail_closed_assertions': guard_checks,
              'render_iteration_ms_p50_p95_p99': np.percentile(durations, [50, 95, 99]).tolist(),
              'performance_note': 'six RPs and synchronous evidence IO; not production FPS qualification'}
    result['integration_topology'] = isolation.report() if isolation else None
    result['passed'] = (first is None if isolation else first is not None) and all(n > 0 for n in witness_frames) and all(n > 0 for n in world_frames)
    (args.output / 'result.json').write_text(json.dumps(result, indent=2))
    stage.GetSessionLayer().Export(str(args.output / 'session.usda'))
    for panel in panels:
        panel.close()
    if core:
        core.request_disable_profile()
        for _ in range(30):
            app.update()
    print(json.dumps(result), flush=True)
    if not result['passed']:
        raise RuntimeError('Preview isolation/witness regression failed; see result.json')


exit_code = 0
try:
    if args.epochs == 1:
        main()
    else:
        output_root = args.output
        for epoch, count in enumerate((1, 3)):
            args.output = output_root / f'epoch_{epoch}'
            args.output.mkdir()
            args.cameras = count
            main()
            sim_utils.SimulationContext.clear_instance()
            gc.collect()
except BaseException:
    exit_code = 1
    error = traceback.format_exc()
    (args.output / 'error.txt').write_text(error)
    print(error, file=sys.stderr, flush=True)
finally:
    app.close(exit_code=exit_code)
raise SystemExit(exit_code)
