"""Opt-in hook reaches canonical Isaac child after shared scene construction."""

import importlib.abc
import importlib.machinery
import os
from pathlib import Path
import sys


class PairImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in ("isaac_demo_launch", "isaac_s2_runtime"):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        original = spec.loader

        class Loader(importlib.abc.Loader):
            def create_module(self, spec):
                return original.create_module(spec) if hasattr(original, "create_module") else None

            def exec_module(self, module):
                original.exec_module(module)
                if fullname == "isaac_demo_launch":
                    previous = module.user_environment

                    def user_environment(*a, **kw):
                        env, state = previous(*a, **kw)
                        env["PYTHONPATH"] = (
                            str(Path(__file__).parent) + os.pathsep + env.get("PYTHONPATH", "")
                        )
                        for key in (
                            "PHYSICS_PAIR_OUTPUT",
                            "PHYSICS_PAIR_WORKER_PYTHON",
                            "PHYSICS_PAIR_REPLAY",
                            "PHYSICS_PAIR_CASES",
                        ):
                            env[key] = os.environ[key]
                        return env, state

                    module.user_environment = user_environment
                else:
                    from run_physics_pair import run

                    module.run_s2 = run

        spec.loader = Loader()
        return spec


if os.environ.get("PHYSICS_PAIR_OUTPUT"):
    sys.meta_path.insert(0, PairImports())
