"""Opt-in experiment hooks; never imported by the canonical launcher by default."""
import importlib.abc
import importlib.machinery
import os
import sys
from pathlib import Path


class Imports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in ('isaac_demo_launch', 'isaac_s2_runtime', 'isaac_vr_runtime'):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None:
            return None
        loader = spec.loader

        class Loader(importlib.abc.Loader):
            def create_module(self, spec):
                return loader.create_module(spec)

            def exec_module(self, module):
                loader.exec_module(module)
                if fullname == 'isaac_demo_launch':
                    original = module.user_environment
                    def environment(*args, **kwargs):
                        result = original(*args, **kwargs)
                        result[0]['PYTHONPATH'] = str(Path(__file__).parent) + ':' + result[0]['PYTHONPATH']
                        return result
                    module.user_environment = environment
                elif fullname == 'isaac_vr_runtime':
                    if os.environ['VR_BAKEOFF_CANDIDATE'] in ('H-cpu','H-cpu-capture','F-minimal','LIVE-MIN60-NONTILED'):
                        original = module.run_vr
                        def run_vr(args, *a, **kw):
                            candidate = os.environ['VR_BAKEOFF_CANDIDATE']
                            if candidate.startswith('H-cpu'):
                                args.device = 'cpu'
                            else:
                                import carb.settings
                                settings=carb.settings.get_settings()
                                settings.set('/rtx/rendermode','MinimalRendering')
                                settings.set('/rtx/minimal/mode',2)
                            if candidate == 'LIVE-MIN60-NONTILED':
                                main = sys.modules['__main__']
                                main.PHYSICS_DT = 1.0 / 60.0
                                main.ACTION_REPEAT = 2
                                module.PHYSICS_DT = 1.0 / 60.0
                            return original(args, *a, **kw)
                        module.run_vr = run_vr
                else:
                    original = module.run_s2
                    def run(env, args, app):
                        from variants import install
                        install(env, args)
                        candidate = os.environ['VR_BAKEOFF_CANDIDATE']
                        if candidate == 'LIVE-MIN60-NONTILED':
                            from live_min60 import install as install_live_min60
                            install_live_min60(env, args)
                            if os.environ.get('VR_LIVE_MIN60_PHASE') == '1':
                                from phase_probe import install as install_phase
                                install_phase(env, args, Path(os.environ['VR_BAKEOFF_OUTPUT']))
                        if candidate in ('B1-FULL-OFFLINE', 'B1-FULL-OFFLINE-D','B1-cost','C1-640','C1-320','C2-320','C2-256','G-tiled640'):
                            from live_state_cost import run as state_cost
                            return state_cost(original,env,args,app)
                        if candidate == 'phase':
                            from phase_probe import install as install_phase
                            install_phase(env, args, Path(os.environ['VR_BAKEOFF_OUTPUT']))
                        if candidate in ('render-assay','G-assay'):
                            from render_assay import install as install_assay
                            install_assay(env, args)
                        if candidate in ('B1-capture','H-cpu-capture'):
                            from state_probe import capture
                            result = capture(env, args, app)
                            import json
                            args.report.write_text(json.dumps(dict(experiment=candidate,
                                completed=result == 0, qualified=False, recording=False)))
                            return result
                        return original(env, args, app)
                    module.run_s2 = run
        spec.loader = Loader()
        return spec


if os.environ.get('VR_BAKEOFF_CANDIDATE') == 'LIVE-MIN60-NONTILED' and '--kit_args' in sys.argv:
    # Apply synchronous rendering before Kit starts. Toggling app async mode
    # after RTX/annotator initialization can leave camera products stale.
    index = sys.argv.index('--kit_args') + 1
    sys.argv[index] += ' --/app/asyncRendering=false --/app/asyncRenderingLowLatency=false --/omni/replicator/asyncRendering=false'

if os.environ.get('VR_BAKEOFF_CANDIDATE'):
    sys.meta_path.insert(0, Imports())
