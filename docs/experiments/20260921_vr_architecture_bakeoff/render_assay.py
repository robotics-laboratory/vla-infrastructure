"""Static product-cost assay. No control-rate or dataset qualification claim."""
import json
import os
import time
from pathlib import Path
import numpy as np


def install(env,args):
    from isaac_s2_performance import S2PerformanceLogger
    previous=S2PerformanceLogger.end_step
    def end(log,number,**state):
        result=previous(log,number,**state)
        if number==args.s2_max_control_steps:
            run(env)
        return result
    S2PerformanceLogger.end_step=end


def run(env):
    import carb.settings
    import omni.kit.app
    import omni.replicator.core as rep
    from omni.kit.viewport.utility import get_active_viewport
    from omni.kit.xr.core import XRSettings, XRCore
    app=omni.kit.app.get_app()
    app.get_extension_manager().set_extension_enabled_immediate('omni.hydra.engine.stats',True)
    import omni.hydra.engine.stats as stats
    settings=carb.settings.get_settings();settings.set('/profiler/enabled',True)
    hd=stats.HydraEngineStats()
    out=Path(os.environ['VR_BAKEOFF_OUTPUT'])
    cameras=env.camera.capture.cameras
    textures=[c._render_data.render_product.hydra_texture for c in cameras.values()]
    paths=[c._view.prim_paths[0] for c in cameras.values()]
    viewport=get_active_viewport()
    original_mode=settings.get('/rtx/rendermode')
    xr=XRSettings.get_singleton();original_scale=xr.get_setting('profile/persistent/render/resolutionMultiplier')
    cases=[('A0',None),('B1-no-sensors',None),('C1-640',(1,640,480)),
           ('C1-320',(1,320,240)),('C2-320',(3,320,240)),('C2-256',(3,256,192)),
           ('G-tiled640',(3,640,480)),('D-desktop-off',None),
           ('E08',None),('E06',None),('A0-restored',None)]
    if os.environ['VR_BAKEOFF_CANDIDATE']=='G-assay':
        cases=[('A0',None),('G-tiled640',(3,640,480))]
    results=[]
    try:
        for name,preview in cases:
            for tex in textures:tex.updates_enabled=name not in ('B1-no-sensors','C1-640','C1-320','C2-320','C2-256','G-tiled640')
            viewport.updates_enabled=name!='D-desktop-off'
            settings.set('/rtx/rendermode','MinimalRendering' if name=='F-minimal' else original_mode)
            if name=='F-minimal':settings.set('/rtx/minimal/mode',2)
            xr.set_setting('profile/persistent/render/resolutionMultiplier',{'E08':.8,'E06':.6}.get(name,original_scale or 1.0))
            product=None;ann=None
            if preview:
                count,width,height=preview
                product=rep.create.render_product_tiled(cameras=paths[:count],tile_resolution=(width,height),force_new=True)
                ann=rep.AnnotatorRegistry.get_annotator('rgb');ann.attach(product)
            samples=[]
            for i in range(150):
                start=time.perf_counter_ns();env.sim.render();duration=(time.perf_counter_ns()-start)/1e6
                if i>=50:samples.append(dict(render_host_ms=duration,gpu=hd.get_gpu_profiler_result()))
            sample_shape=None
            if ann:
                data=ann.get_data()
                if isinstance(data,dict):data=data['data']
                image=np.asarray(data);sample_shape=list(image.shape)
                np.save(out/(name+'.npy'),image)
            if name in ('A0','F-minimal','A0-restored'):
                env.camera.capture_boundary(env)
                images=env.camera.capture.freeze()
                np.savez(out/(name+'.npz'),**{k:v for k,v in images.items() if 'images' in k})
            core=XRCore.get_singleton()
            results.append(dict(case=name,preview=preview,shape=sample_shape,
                physics_step=env.sim.get_physics_step_count(),samples=samples,
                xr=dict(enabled=core.is_xr_enabled(),display=core.is_xr_display_enabled(),viewport=core.is_xr_viewport_enabled()),
                mode=settings.get('/rtx/rendermode'),scale=xr.get_setting('profile/persistent/render/resolutionMultiplier')))
            (out/'render_assay.json').write_text(json.dumps(results,default=str))
            if ann:ann.detach()
            if product:product.destroy()
    finally:
        for tex in textures:tex.updates_enabled=True
        viewport.updates_enabled=True
        settings.set('/rtx/rendermode',original_mode)
        xr.set_setting('profile/persistent/render/resolutionMultiplier',original_scale or 1.0)
    return 0
