"""Explicitly opted-in, process-local camera investigation; no canonical imports."""

import importlib.abc
import importlib.machinery
import os
from pathlib import Path
import sys


class Imports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in (
            "isaac_demo_launch",
            "isaac_s2_runtime",
            "isaac_vr_runtime",
            "isaac_vr_injected_recording",
        ):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None:
            return None
        from typing import cast

        loader = cast(importlib.abc.Loader, spec.loader)

        class Loader(importlib.abc.Loader):
            def create_module(self, spec):
                return loader.create_module(spec)

            def exec_module(self, module):
                loader.exec_module(module)
                if fullname == "isaac_demo_launch":
                    original = module.user_environment

                    def environment(*args, **kwargs):
                        result = original(*args, **kwargs)
                        result[0]["PYTHONPATH"] = (
                            os.environ["PYTHONPATH"] + ":" + result[0]["PYTHONPATH"]
                        )
                        return result

                    module.user_environment = environment
                elif fullname == "isaac_vr_runtime":
                    # No SceneUI panels are even constructed, including during startup.
                    module.VRRuntime._prebind_camera_panels = lambda self: None
                    if os.environ.get("CAMERA_AUDIT_BATCH") == "1":
                        from batched_camera import install_construction

                        install_construction(module, None)
                elif fullname == "isaac_vr_injected_recording":
                    original = module.record_injected_transitions

                    def record(*args, **kwargs):
                        return original(*args, require_distinct_actions=False, **kwargs)

                    module.record_injected_transitions = record
                else:
                    original = module.run_s2

                    def run(env, args, app):
                        from audit_runtime import install

                        install(env, args)
                        if int(os.environ["CAMERA_AUDIT_PROBE"]) and not args.xr:
                            import json

                            env._camera_audit_run_probe()
                            args.report.write_text(
                                json.dumps({"experiment": True, "physical": False})
                            )
                            return 0
                        return original(env, args, app)

                    module.run_s2 = run

        spec.loader = Loader()
        return spec


if os.environ.get("CAMERA_AUDIT_OUTPUT"):
    root = Path(__file__).resolve().parents[2]
    sys.path.append(str(root / "docs/experiments/20260921_vr_architecture_bakeoff"))
    if "--kit_args" in sys.argv:
        index = sys.argv.index("--kit_args") + 1
        sys.argv[index] += " --/persistent/xr/profile/ar/render/resolutionMultiplier=0.4"
        if os.environ.get("CAMERA_AUDIT_XR_COST") == "1":
            sys.argv[index] += " --enable isaacsim.replicator.episode_recorder"
        candidate = os.environ["CAMERA_AUDIT_TEMPORAL"]
        if candidate in ("t3", "t6-sync-explicit"):
            sys.argv[index] += " --/app/asyncRendering=false"
        if candidate == "t3-low-latency-off":
            sys.argv[index] += " --/app/asyncRenderingLowLatency=false"
        if candidate == "t4":
            sys.argv[index] += " --/app/useFabricSceneDelegate=false"
    sys.meta_path.insert(0, Imports())
