"""Opt-in selectors for later human Quest A/B through the unchanged RECORD entrypoint.

Set VR_PERF_FOLLOWUP=1 and PYTHONPATH to this directory for one process only.
No measurement or physical action is started by importing this module.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
from pathlib import Path
import sys
from typing import cast


class _Imports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in {
            "isaac_demo_launch",
            "isaaclab_physx.renderers.isaac_rtx_renderer_utils",
            "isaaclab_physx.renderers.isaac_rtx_renderer",
            "isaac_vr_recording",
        }:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None:
            return None
        loader = cast(importlib.abc.Loader, spec.loader)

        class _Loader(importlib.abc.Loader):
            def create_module(self, spec):
                return loader.create_module(spec)

            def exec_module(self, module):
                loader.exec_module(module)
                if fullname == "isaac_demo_launch":
                    original = module.user_environment

                    def environment(*args, **kwargs):
                        result = original(*args, **kwargs)
                        hook_path = str(Path(__file__).resolve().parent)
                        result[0]["PYTHONPATH"] = hook_path + ":" + result[0]["PYTHONPATH"]
                        return result

                    module.user_environment = environment
                elif fullname == "isaaclab_physx.renderers.isaac_rtx_renderer_utils":
                    if renderer == "minimal":
                        original = module.apply_isaac_rtx_determinism_settings

                        def select_minimal(*args, **kwargs):
                            result = original(*args, **kwargs)
                            import carb.settings

                            settings = carb.settings.get_settings()
                            settings.set("/rtx/rendermode", "MinimalRendering")
                            settings.set("/rtx/minimal/mode", 2)
                            return result

                        module.apply_isaac_rtx_determinism_settings = select_minimal
                elif fullname == "isaaclab_physx.renderers.isaac_rtx_renderer":
                    if renderer == "minimal":
                        original = module.IsaacRtxRenderer.__init__

                        def select_before_products(self, *args, **kwargs):
                            result = original(self, *args, **kwargs)
                            import carb.settings

                            settings = carb.settings.get_settings()
                            settings.set("/rtx/rendermode", "MinimalRendering")
                            settings.set("/rtx/minimal/mode", 2)
                            return result

                        module.IsaacRtxRenderer.__init__ = select_before_products
                elif flush_every == 128:
                    original = module.start_live_recording

                    def start_with_explicit_flush(*args, **kwargs):
                        if "flush_every_frames" in kwargs and kwargs["flush_every_frames"] != 128:
                            raise ValueError("physical follow-up flush policy conflict")
                        kwargs["flush_every_frames"] = 128
                        return original(*args, **kwargs)

                    module.start_live_recording = start_with_explicit_flush

        spec.loader = _Loader()
        return spec


if os.environ.get("VR_PERF_FOLLOWUP") == "1":
    renderer = os.environ.get("VR_PERF_RENDERER", "baseline")
    if renderer not in {"baseline", "minimal"}:
        raise ValueError(f"invalid VR_PERF_RENDERER={renderer!r}")
    flush_every = int(os.environ.get("VR_PERF_FLUSH_EVERY", "64"))
    if flush_every not in {64, 128}:
        raise ValueError(f"invalid VR_PERF_FLUSH_EVERY={flush_every}")
    if "--kit_args" in sys.argv:
        index = sys.argv.index("--kit_args") + 1
        sys.argv[index] += " --/persistent/xr/profile/ar/foveation/mode=warped"
        sys.argv[index] += " --/persistent/xr/profile/ar/renderQuality=performance"
        if renderer == "minimal":
            sys.argv[index] += " --/rtx/rendermode=MinimalRendering --/rtx/minimal/mode=2"
    sys.meta_path.insert(0, _Imports())
