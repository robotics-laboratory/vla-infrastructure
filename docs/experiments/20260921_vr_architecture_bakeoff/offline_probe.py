"""Restore diagnostic Recordable payloads in a fresh process, never play physics."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
import resource
import subprocess
import shutil
import hashlib


def validate(records, frame):
    for r in records:
        expected=r.describe_channels()
        if r.group not in frame or set(frame[r.group]) != set(expected):
            raise ValueError(f'Incomplete state /{r.group}')
        for key,desc in expected.items():
            value=np.asarray(frame[r.group][key])
            if value.shape != desc.shape or not np.isfinite(value).all():
                raise ValueError(f'Malformed state /{r.group}/{key}')

parser = argparse.ArgumentParser()
parser.add_argument('capture', type=Path)
parser.add_argument('--backend', choices=['usd','usdrt','fabric'], default='fabric')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--save-all',action='store_true',help='Write every three-camera state as compressed NPZ')
args, _ = parser.parse_known_args()
context_path=args.capture/'full_offline_manifest.json'
if context_path.exists():
    context=json.loads(context_path.read_text())
    if hashlib.sha256((args.capture/'stage_snapshot.usd').read_bytes()).hexdigest()!=context['stage_sha256']:
        raise ValueError('Stage digest mismatch')
    if context['unresolved_assets']:raise ValueError('Unresolved asset dependencies')
    for name,digest in context['dependencies'].items():
        dependency=(args.capture/'stage_snapshot.usd' if digest==context['stage_sha256']
                    and Path(name).name=='stage_snapshot.usd' else Path(name))
        if not digest or hashlib.sha256(dependency.read_bytes()).hexdigest()!=digest:
            raise ValueError('Asset digest mismatch: '+name)
args.output.mkdir(parents=True, exist_ok=False)
shutil.copy2(__file__,args.output/'executed_source.py')
from isaacsim import SimulationApp
renderer=json.loads((args.capture/'variant.json').read_text())['shaders']
app = SimulationApp({'headless':True, 'renderer':renderer})
import carb.settings
import omni.usd
import omni.timeline
import omni.kit.app
import omni.replicator.core as rep
from pxr import UsdGeom, Usd
settings=carb.settings.get_settings()
settings.set('/app/player/playSimulations', False)
rep.orchestrator.set_capture_on_play(False)
import omni.physx
physics_callbacks=[]
physics_subscription=omni.physx.get_physx_interface().subscribe_physics_step_events(
    lambda dt:physics_callbacks.append(float(dt)))
omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate(
    'isaacsim.replicator.episode_recorder', True)
from isaacsim.replicator.episode_recorder import (
    ArticulationRecordable, RigidBodyRecordable, CameraRecordable, ReplayPolicy)
prepared=Usd.Stage.Open(str(args.capture/'stage_snapshot.usd'))
# The upstream flattened export includes transient SDG graphs from the live run.
# They cannot be resurrected as live Python/OmniGraph objects after restart.
removed=[]
for path in ('/Render','/Replicator'):
    if prepared.GetPrimAtPath(path):
        prepared.RemovePrim(path);removed.append(path)
prepared.GetRootLayer().Export(str(args.output/'replay_scene.usd'))
(args.output/'preparation.json').write_text(json.dumps({'removed_runtime_roots':removed}))
omni.usd.get_context().open_stage(str(args.output/'replay_scene.usd'))
for _ in range(20): app.update()
stage=omni.usd.get_context().get_stage()
classes={r.TYPE_ID:r for r in (ArticulationRecordable,RigidBodyRecordable,CameraRecordable)}
manifest=json.loads((args.capture/'recordables.json').read_text())
records=[classes[r['type']].from_manifest(r) for r in manifest]
for r in records: r.on_session_open(stage)
articulation_links={}
for r in records:
    if isinstance(r,ArticulationRecordable):
        links=[]
        for index,path in sorted(enumerate(r.link_paths),key=lambda item:item[1].count('/')):
            link=RigidBodyRecordable(group=f'{r.group}/{index}',prim_path=path)
            link.on_session_open(stage);links.append((index,link))
        articulation_links[r.group]=links
policy=ReplayPolicy(strictness='strict')
products=[]; annotators={}
for m in manifest:
    if m['type']=='camera':
        rp=rep.create.render_product(m['prim_path'],(640,480))
        ann=rep.AnnotatorRegistry.get_annotator('rgb');ann.attach(rp)
        products.append(rp);annotators[m['group']]=ann
if (args.capture/'states.json').exists():
    rows=json.loads((args.capture/'states.json').read_text())
else:
    rows=[json.loads(line) for line in (args.capture/'state_action.jsonl').read_text().splitlines()]
    manifest_path=args.capture/'full_offline_manifest.json'
    context=json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    identities=set();previous_tick=None
    for row in rows:
        for key in ('tick','physics_step','reset_epoch','state','action','snapshot'):
            if key not in row:raise ValueError('Incomplete tick: '+key)
        identity=(row.get('run_id'),row['reset_epoch'],row['tick'])
        if identity in identities:raise ValueError('Duplicate state identity')
        if previous_tick is not None and row['tick']!=previous_tick+1:raise ValueError('Missing/nonsequential tick')
        previous_tick=row['tick']
        identities.add(identity)
        if context:
            for key in ('run_id','stage_sha256','task','backdrop_visible','articulation_joint_positions',
                        'articulation_joint_velocities','articulation_root_poses','object_velocities'):
                if key not in row:raise ValueError('Incomplete FULL-OFFLINE record: '+key)
            if row['run_id']!=context['run_id'] or row['stage_sha256']!=context['stage_sha256']:
                raise ValueError('State/source identity mismatch')
        row['snapshots']={args.backend:row['snapshot']}
negative=[]
for r in records:
    for key in r.describe_channels():
        bad=json.loads(json.dumps(rows[0]['snapshots'][args.backend]));del bad[r.group][key]
        try: validate(records,bad)
        except ValueError: negative.append({'group':r.group,'missing':key,'rejected':True})
        else: raise AssertionError('Incomplete snapshot admitted')
(args.output/'negative_completeness.json').write_text(json.dumps(negative,indent=2))
metrics=[]
for row in rows:
    tick=row['tick']
    frame=row['snapshots'][args.backend]
    # Recordables can otherwise accept missing intrinsics or best-effort zero fallback.
    validate(records,frame)
    start=time.perf_counter()
    for r in records:
        if r.group in articulation_links:
            # Same parents-first requirement as EpisodeReplayer's ancestry tiers.
            for index,link in articulation_links[r.group]:
                link.apply({'position':np.asarray(frame[r.group]['positions'][index],dtype=np.float32),
                            'orientation':np.asarray(frame[r.group]['orientations'][index],dtype=np.float32)},policy=policy)
        else:
            r.apply({k:np.asarray(v,dtype=np.float32) for k,v in frame[r.group].items()},policy=policy)
    if 'backdrop_visible' in row:
        imageable=UsdGeom.Imageable(stage.GetPrimAtPath('/World/RobosynDemo/Backdrop'))
        if row['backdrop_visible']:imageable.MakeVisible()
        else:imageable.MakeInvisible()
    geometry=[]
    for r in records:
        actual=r.sample()
        key='positions' if 'positions' in actual else 'position'
        geometry.extend(np.linalg.norm(np.asarray(actual[key]).reshape(-1,3)-np.asarray(frame[r.group][key]).reshape(-1,3),axis=1).tolist())
    # Bounded convergence policy, declared as offline-only. No physics/actions.
    rep.orchestrator.step(rt_subframes=4,delta_time=0.0,pause_timeline=True,wait_for_render=True)
    assert not omni.timeline.get_timeline_interface().is_playing()
    assert not physics_callbacks, 'Offline rendering advanced physics'
    images={role:np.array(a.get_data())[...,:3].copy() for role,a in annotators.items()}
    if set(images)!={'left_wrist','right_wrist','scene'}:raise ValueError('Camera role mismatch')
    for role,image in images.items():
        if image.shape!=(480,640,3) or image.dtype!=np.uint8:raise ValueError((role,image.shape,image.dtype))
    if args.save_all:np.savez_compressed(args.output/f'offline_{tick}.npz',**images)
    elapsed=time.perf_counter()-start
    result={'tick':tick,'materialize_ms':elapsed*1000,'max_restored_position_error_m':max(geometry),
            'camera_shapes':{k:list(v.shape) for k,v in images.items()},'roles':{}}
    live_path=args.capture/f'live_{tick}.npz'
    if live_path.exists():
        live=np.load(live_path)
        for role,image in images.items():
            if image.shape != (480,640,3):raise ValueError((role,image.shape))
            reference=live['observation.images.'+role]
            mse=float(np.mean((image.astype(float)-reference.astype(float))**2))
            result['roles'][role]={'equal':bool(np.array_equal(image,reference)),
                                  'psnr_db':None if mse==0 else float(10*np.log10(255**2/mse)),
                                  'mae':float(np.abs(image.astype(float)-reference).mean())}
        np.savez(args.output/f'offline_{tick}.npz',**images)
    metrics.append(result)
    (args.output/'metrics.json').write_text(json.dumps(metrics,indent=2))
(args.output/'metrics.json').write_text(json.dumps(metrics,indent=2))
(args.output/'memory.json').write_text(json.dumps({'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'physics_callbacks':len(physics_callbacks),
    'gpu_memory_end':subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader'],text=True)}))
app.close()
