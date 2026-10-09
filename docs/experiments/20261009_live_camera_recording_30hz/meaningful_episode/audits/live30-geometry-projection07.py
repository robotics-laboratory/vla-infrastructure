"""CPU-only independent USD/HDF projection onto retained decoded scene images."""
import os
os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['MPLCONFIGDIR'] = '/tmp/live30-geometry-mpl'
import json, hashlib, pathlib
import numpy as np
import h5py
from pxr import Usd, UsdGeom, Gf
from scipy.spatial import ConvexHull
from scipy.ndimage import binary_erosion
from PIL import Image, ImageDraw
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

base = pathlib.Path('/data/ebulochkin/vla-runtime/live30-meaningful-episode-20261009')
root, preview = base/'reach-demo07', base/'preview07'
manifest = json.loads((root/'mirror/source-manifest.json').read_text())
source = Usd.Stage.Open(str(root/'episode/stage_snapshot.usd'))
cache = UsdGeom.XformCache()
indices = [0,390,690]
images = [np.asarray(Image.open(preview/f'scene-sample-{i+1:02d}.png').convert('RGB')) for i in range(3)]
height,width = images[0].shape[:2]
receipt = dict(schema='live30_sampled_geometry_projection_v1', date='2026-10-09',
               mode='CPU only; no Renderer; no FK; retained USD mesh vertices and recorded HDF world poses',
               source_indices=indices, samples=[], pixel_comparison={},
               limitations=['Three sampled scene frames only; not all-frame optical source verification.',
                            'Projected convex hull is not an occlusion-aware rasterizer or segmentation label.',
                            'Pixel differences include path-tracing/codec noise; thresholds are descriptive.'])
inputs = [pathlib.Path(__file__),root/'episode/stage_snapshot.usd',root/'episode/session.hdf5',
          root/'mirror/source-manifest.json',root/'mirror/worker-rows.jsonl',preview/'export.json']
inputs += [preview/f'scene-sample-{i+1:02d}.png' for i in range(3)]
receipt['input_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}

def pose(p,q):
    q=np.asarray(q,dtype=float);q/=np.linalg.norm(q)
    m=Gf.Matrix4d(1);m.SetRotate(Gf.Quatd(float(q[0]),Gf.Vec3d(*q[1:])))
    m.SetTranslateOnly(Gf.Vec3d(*np.asarray(p,dtype=float)))
    return np.asarray(m)

geometry=[]
for role in ['left','right']:
    entry=next(x for x in manifest['recordables'] if x.get('group')==f'state/{role}_robot')
    for body_index,body in enumerate(entry['link_paths']):
        if body.rsplit('/',1)[-1] not in ['gripper_link1','gripper_link2']:continue
        world=np.asarray(cache.GetLocalToWorldTransform(source.GetPrimAtPath(body)))
        for prim in Usd.PrimRange(source.GetPrimAtPath(body),Usd.TraverseInstanceProxies()):
            if not prim.IsA(UsdGeom.Mesh):continue
            img=UsdGeom.Imageable(prim)
            if img.ComputeVisibility()==UsdGeom.Tokens.invisible:continue
            if img.ComputePurpose()==UsdGeom.Tokens.guide:continue
            points=np.asarray(prim.GetAttribute('points').Get(),dtype=float)
            if not len(points):continue
            mesh=np.asarray(cache.GetLocalToWorldTransform(prim))
            local=np.c_[points,np.ones(len(points))] @ mesh @ np.linalg.inv(world)
            geometry.append(dict(role=role,body=body,index=body_index,path=str(prim.GetPath()),local=local))

all_hulls=[]
with h5py.File(root/'episode/session.hdf5','r') as h:
    ep=h['episodes/episode_00000']
    for idx,img in zip(indices,images):
        camera=ep['state/camera/scene'];cam=pose(camera['position'][idx],camera['orientation'][idx])
        f=float(camera['focal_length'][idx]);ha=float(camera['horizontal_aperture'][idx]);va=float(camera['vertical_aperture'][idx])
        fx,fy=width*f/ha,height*f/va
        sample=dict(source_index=idx,camera_world=cam.tolist(),intrinsics=dict(fx=fx,fy=fy,cx=width/2,cy=height/2),meshes=[],fingers=[])
        uv_by_role={'left':[],'right':[]}
        for g in geometry:
            state=ep[f'state/{g["role"]}_robot'];world=pose(state['positions'][idx,g['index']],state['orientations'][idx,g['index']])
            view=g['local'] @ world @ np.linalg.inv(cam)
            view=view[view[:,2]<-1e-6]
            if not len(view):continue
            uv=np.stack([width/2+fx*view[:,0]/-view[:,2],height/2-fy*view[:,1]/-view[:,2]],axis=-1)
            uv_by_role[g['role']].append(uv)
            sample['meshes'].append(dict(path=g['path'],body=g['body'],vertices=len(uv),bbox=[uv.min(0).tolist(),uv.max(0).tolist()],centroid=uv.mean(0).tolist()))
        hulls={}
        for role,parts in uv_by_role.items():
            points=np.concatenate(parts);hull=points[ConvexHull(points).vertices];hulls[role]=hull
            sample['fingers'].append(dict(role=role,hull=hull.tolist(),bbox=[points.min(0).tolist(),points.max(0).tolist()],centroid=points.mean(0).tolist()))
        all_hulls.append(hulls);receipt['samples'].append(sample)

fig,axes=plt.subplots(1,3,figsize=(18,4),dpi=150)
for ax,img,idx,hulls in zip(axes,images,indices,all_hulls):
    ax.imshow(img)
    for role,color in [('left','lime'),('right','cyan')]:
        h=hulls[role];h=np.vstack([h,h[:1]]);ax.plot(h[:,0],h[:,1],color=color,lw=1.2,label=role+' projected fingers')
    ax.set_title(f'Recorded source {idx}: USD/HDF projected fingers');ax.set_xlim(0,width);ax.set_ylim(height,0);ax.axis('off')
axes[0].legend(fontsize=6,loc='upper left')
fig.tight_layout();output=pathlib.Path('/tmp/live30-geometry-projection07.png');fig.savefig(output,bbox_inches='tight');plt.close(fig)

diff=np.abs(images[1].astype(np.int16)-images[2].astype(np.int16)).max(2)
for role in ['left','right']:
    canvas=Image.new('1',(width,height));draw=ImageDraw.Draw(canvas)
    for hulls in all_hulls[1:]:draw.polygon([tuple(v) for v in hulls[role]],fill=1)
    mask=np.asarray(canvas,dtype=bool)
    before=next(x for x in receipt['samples'][1]['fingers'] if x['role']==role)
    after=next(x for x in receipt['samples'][2]['fingers'] if x['role']==role)
    receipt['pixel_comparison'][role]=dict(roi_pixels=int(mask.sum()),max_channel_mean_abs_delta=float(diff[mask].mean()),
        fraction_pixels_delta_gt20=float((diff[mask]>20).mean()),fraction_pixels_delta_gt50=float((diff[mask]>50).mean()),
        projected_centroid_delta_px=float(np.linalg.norm(np.array(before['centroid'])-after['centroid'])),
        projected_centroid_before=before['centroid'],projected_centroid_after=after['centroid'])
    occupancy=[]
    for sample_i,opposite_i in [(1,2),(2,1)]:
        canvas=Image.new('1',(width,height));draw=ImageDraw.Draw(canvas)
        draw.polygon([tuple(v) for v in all_hulls[sample_i][role]],fill=1)
        core=binary_erosion(np.asarray(canvas,dtype=bool),iterations=2)
        current=images[sample_i].astype(float).mean(2)
        opposite=images[opposite_i].astype(float).mean(2)
        occupancy.append(dict(projected_source=indices[sample_i],opposite_source=indices[opposite_i],
                              core_roi_pixels=int(core.sum()),threshold_mean_rgb_lt100=100,
                              matching_frame_dark_fraction=float((current[core]<100).mean()),
                              opposite_frame_dark_fraction=float((opposite[core]<100).mean())))
    receipt['pixel_comparison'][role]['projected_hull_dark_occupancy']=occupancy
receipt['overlay']=dict(path=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest())
pathlib.Path('/tmp/live30-geometry-projection07.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt['pixel_comparison'],indent=2))
