"""Opt-in import hook for the OLD/CURRENT native physics assay."""

import importlib.abc
import importlib.machinery
import os
import sys


class _AssayImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in {"isaac_demo_launch", "isaac_s2_runtime"}:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        original_loader = spec.loader

        class _Loader(importlib.abc.Loader):
            def create_module(self, spec):
                return original_loader.create_module(spec) if hasattr(original_loader, "create_module") else None

            def exec_module(self, module):
                original_loader.exec_module(module)
                if fullname == "isaac_demo_launch":
                    original = module.user_environment

                    def user_environment(*args, **kwargs):
                        environment, state = original(*args, **kwargs)
                        directory = os.path.dirname(__file__)
                        environment["PYTHONPATH"] = directory + os.pathsep + environment.get("PYTHONPATH", "")
                        environment["PHYSICS_AUDIT_OUTPUT"] = os.environ["PHYSICS_AUDIT_OUTPUT"]
                        environment["PHYSICS_AUDIT_CHECKPOINT"] = os.environ["PHYSICS_AUDIT_CHECKPOINT"]
                        return environment, state

                    module.user_environment = user_environment
                else:
                    def run_s2(env, args, app):
                        from physics_assay import run

                        return run(env, args, app)

                    module.run_s2 = run_s2

        spec.loader = _Loader()
        return spec


if os.environ.get("PHYSICS_AUDIT_OUTPUT"):
    sys.meta_path.insert(0, _AssayImports())
