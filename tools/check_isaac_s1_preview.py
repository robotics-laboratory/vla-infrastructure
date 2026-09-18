"""Combined validation on the canonical S1 robot, sensors and production preview.

Diagnostic watermark/witnesses only; uses no replacement sensor or presenter.
Every captured frame, including reset settling frames, is checked for leakage.
"""
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
import warp as wp
from PIL import Image
from pxr import Gf, Sdf, Usd, UsdGeom
import omni.ui.scene as sc
from omni.kit.xr.core import XRCore
import omni.kit.xr.system.openxr as oxr
from isaac_s1_preview import S1Preview
from isaac_preview_partitions import PREVIEW


def array(value):
    if not isinstance(value, torch.Tensor):
        value = value.torch if hasattr(value, 'torch') else wp.to_torch(value)
    return value.detach().cpu().contiguous().numpy().copy()


def marker(image):
    rgb = image[..., :3].astype(np.int16)
    return int(((rgb[..., 0] > 160) & (rgb[..., 2] > 160) & (rgb[..., 1] < 95)
                & (rgb[..., 0] - rgb[..., 1] > 80)).sum())


def raw_images(camera):
    data = camera._render_data
    raw = array(data.annotators['rgba'].get_data(do_array_copy=False))
    count = camera.num_instances
    cols = math.ceil(math.sqrt(count)); rows = math.ceil(count / cols)
    raw = raw.reshape(rows * 480, cols * 640, 4)
    return [raw[(i//cols)*480:(i//cols+1)*480, (i%cols)*640:(i%cols+1)*640] for i in range(count)]


def validate_combined(env, args, app, urdf_sha):
    output = args.report.parent
    capture = {'frame':0, 'phase':'warmup', 'step':-1, 'event':None}
    counts = {'leaked_frames':0, 'witness_frames':[0,0,0], 'valid_frames':[0,0,0],
              'preview_updates':[0,0,0], 'normal_frames':0}
    first_leak = None
    def stamp(upload):
        # Test-only dense magenta grid also detects a partially occluded panel.
        # Live RGB remains in the cells; no sensor/native buffer is modified.
        upload[::24, :, :] = torch.tensor([255, 0, 255, 255], dtype=upload.dtype)
        upload[:, ::24, :] = torch.tensor([255, 0, 255, 255], dtype=upload.dtype)
        upload[:64, :, 0] = 255
        upload[:64, :, 1] = 0
        upload[:64, :, 2:] = 255
        upload[:64, :32, 1] = (capture['frame'] % 2) * 255
    preview = S1Preview(env, isolation=not args.preview_control, validation_stamp=stamp)
    env.preview = preview
    stage = env.sim.stage
    witnesses = [S1Preview.make_scene_camera(f'/World/PreviewWitness{i}') for i in range(3)]
    for i in range(3):
        for j in range(2):
            stage.GetPrimAtPath(f'/World/PreviewWitness{i}{j}/Camera').CreateAttribute(
                'omni:scenePartition', Sdf.ValueTypeNames.Token).Set(PREVIEW)
    env.sim.reset(); env.reset(0)
    core = XRCore.get_singleton()
    core.request_enable_profile('ar')
    log = (output/'preview-frames.jsonl').open('w',buffering=1)
    previous_upload = [None]*3
    durations = []
    events = []
    last_images = None

    def pose_and_aim(step):
        cameras = [(env.camera,0),(env.camera,1),(preview.scene_camera,0)]
        scene_pos = torch.tensor([[1.2+.1*math.sin(step*.04), -1.3, 1.2]]*2,device=env.sim.device)
        preview.scene_camera.set_world_poses_from_view(scene_pos,torch.tensor([[0.,0.,.4]]*2,device=env.sim.device))
        for i,((camera,index),feed,witness) in enumerate(zip(cameras,preview.manager._feeds,witnesses)):
            position = array(camera.data.pos_w)[index]
            quat = array(camera.data.quat_w_opengl)[index]
            rotation = Gf.Rotation(Gf.Quatd(float(quat[3]),Gf.Vec3d(*map(float,quat[:3]))))
            offset = Gf.Vec3d(.02*math.sin(step*.1+i), .02*math.cos(step*.07+i), -.5)
            position = Gf.Vec3d(*map(float,position))
            matrix = Gf.Matrix4d(rotation, position+rotation.TransformDir(offset))
            feed.panel._container.root.transform = sc.Matrix44(*[v for row in matrix for v in row])
            feed.panel._container.scene_view.run_update()
            witness.set_world_poses(torch.tensor([list(position)]*2,device=env.sim.device),
                torch.tensor([quat.tolist()]*2,device=env.sim.device),convention='opengl')
        preview.assert_valid()

    def save(frame, images):
        dest=output/'representative'/f'{frame:06d}';dest.mkdir(parents=True,exist_ok=True)
        for i,item in enumerate(images):
            for key,value in item.items():Image.fromarray(value).save(dest/f'{i}_{key}.png')

    def observe():
        nonlocal first_leak,last_images
        raw = raw_images(env.camera)+raw_images(preview.scene_camera)[:1]
        cache = list(array(env.camera.data.output['rgba']))+[array(preview.scene_camera.data.output['rgba'])[0]]
        record={'frame_id':capture['frame'],'step':capture['step'],'phase':capture['phase'],
                'event':capture['event'],'timestamp_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns(),
                'xr_session':oxr.get_session_handle(),'physical_quest':False,'cameras':[],
                'topology':preview.isolation.report() if preview.isolation else {'enabled':False}}
        record['head_controller_poses']=[{'name':str(d.get_name()),'poses':{
            str(k):{'matrix':[list(row) for row in p.pose_matrix],'validity_flags':int(p.validity_flags)}
            for k,p in d.get_all_raw_poses().items()}} for d in core.get_all_input_devices()]
        images=[]
        for i,(feed,witness) in enumerate(zip(preview.manager._feeds,witnesses)):
            witness.update(env.sim.get_physics_dt(),force_recompute=True)
            upload=array(feed.upload_image)
            witness_image=array(witness.data.output['rgba'])[0]
            images.append({'sensor_raw':raw[i],'camera_rgba':cache[i],'preview_input':upload,'witness':witness_image})
            detected={k:marker(v) for k,v in images[-1].items()}
            if detected['sensor_raw'] or detected['camera_rgba']:
                counts['leaked_frames']+=1
                if first_leak is None:first_leak={'frame':capture['frame'],'camera':i,'counts':detected}
            normal=capture['phase']=='normal'
            counts['witness_frames'][i]+=int(normal and detected['witness']>50)
            counts['valid_frames'][i]+=int(normal and float(raw[i][...,:3].std())>3.)
            digest=hashlib.sha256(upload.tobytes()).hexdigest()
            counts['preview_updates'][i]+=int(digest!=previous_upload[i]);previous_upload[i]=digest
            owner,index=(env.camera,i) if i<2 else (preview.scene_camera,0)
            record['cameras'].append({'camera_prim':preview.paths[i],
                'render_product':str(owner._render_data.render_product.path),
                'camera_frame':int(array(owner.frame).reshape(-1)[index]),
                'position':array(owner.data.pos_w)[index].tolist(),
                'orientation_xyzw':array(owner.data.quat_w_opengl)[index].tolist(),
                'preview_prim':str(feed.panel._container.scene_view.system_path),
                'preview_transform':str(feed.panel._container.root.transform),
                'counts':detected,'upload_sha256':digest})
        counts['normal_frames']+=int(capture['phase']=='normal')
        log.write(json.dumps(record,default=str)+'\n')
        if capture['frame']==30 or (first_leak and first_leak['frame']==capture['frame']):save(capture['frame'],images)
        last_images=images;capture['frame']+=1

    # No frame sampling: hook runs on every env._advance physics/render tick,
    # including the25 ticks within each canonical env.reset.
    preview.validation_callback=observe
    try:
        for step in range(args.combined_preview_test+30):
            begin=time.perf_counter();capture.update(step=step,event=None,phase='warmup' if step<30 else 'normal')
            if step>30 and step%600==0:
                capture.update(phase='reset',event='canonical_env_reset');events.append({'step':step,'event':'reset'})
                env.reset(0);capture.update(phase='normal',event=None)
            if step>30 and step%250==0:
                preview.close_panels();preview.open()
                events.append({'step':step,'event':'preview_manager_recreated_retained_ui'})
            action=env.home_d0.copy();action[0]+=8*math.sin(step*.04);action[7]-=8*math.sin(step*.037)
            from isaac_s1_runtime import d0_action_to_native
            env._apply(d0_action_to_native(action))
            pose_and_aim(step)
            env._advance(1)
            durations.append(time.perf_counter()-begin)
            if step%250==0:print(f'[COMBINED] {step}/{args.combined_preview_test} leakage={counts["leaked_frames"]} witness={counts["witness_frames"]}',flush=True)
        save(capture['frame']-1,last_images)
        normal=counts['normal_frames']
        passed=(normal==args.combined_preview_test and all(n==normal for n in counts['valid_frames'])
                and all(n>=.95*normal for n in counts['witness_frames'])
                and all(n>=.5*normal for n in counts['preview_updates'])
                and bool(oxr.get_session_handle())
                and (counts['leaked_frames']>0 if args.preview_control else counts['leaked_frames']==0))
        result={'gate':'combined_production_preview','passed':passed,'physical_quest':False,'cloudxr_profile':'standalone automated',
                'xr_session':oxr.get_session_handle(),
                'asset_sha256':urdf_sha,'canonical_scene':True,'policy_roles':['left_wrist','right_wrist'],
                'third_camera':'presentation only','counts':counts,'total_observed_frames':capture['frame'],
                'first_leak':first_leak,'events':events,'control':args.preview_control,
                'camera_recreation':'Full process restart recreates all cameras. In-process deletion excluded: pinned Camera exposes no public close; reset is exercised.',
                'seconds_per_frame_mean':float(np.mean(durations)),
                'topology':preview.isolation.report() if preview.isolation else {'enabled':False}}
        args.report.write_text(json.dumps(result,indent=2)+'\n')
        return 0 if passed else 1
    finally:
        preview.validation_callback=None
        preview.close();env.preview=None;log.close()
        core.request_disable_profile()
        for _ in range(10):app.update()
