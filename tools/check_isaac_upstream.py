"""Run pinned native unit tests without Kit/XR; optionally require core tests too."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
ISAAC_ENV = Path('/data/vla-infrastructure/isaac61_production/env')
NATIVE_TEST = 'test_isaac_s2_upstream.py'


def clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE',
                 'VIRTUAL_ENV', 'CONDA_PREFIX'):
        environment.pop(name, None)
    return environment


def run_suite(suite: unittest.TestSuite) -> int:
    if suite.countTestCases() == 0:
        print('ISAAC UPSTREAM: FAIL (no tests discovered)', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = (result.wasSuccessful() and result.testsRun > 0
              and not result.skipped and not result.expectedFailures)
    print(f'ISAAC UPSTREAM: {"PASS" if passed else "FAIL"} '
          f'({result.testsRun} run, {len(result.skipped)} skipped)')
    return 0 if passed else 1


def worker() -> int:
    if Path(sys.prefix).resolve() != ISAAC_ENV.resolve():
        raise RuntimeError(f'Requires pinned Isaac environment {ISAAC_ENV}, got {sys.prefix}')
    # -I excludes cwd and ambient PYTHONPATH. Only the assigned source checkout
    # is added; upstream editable packages remain owned by the pinned SDK.
    sys.path.insert(0, str(ROOT))
    from tools.isaac_demo_launch import verify_stack

    stack = verify_stack('isaac61')
    if Path(stack['environment']).resolve() != Path(sys.prefix).resolve():
        raise RuntimeError('Runner interpreter differs from verified SDK')
    suite = unittest.TestLoader().discover(str(ROOT / 'tests'), pattern=NATIVE_TEST)
    return run_suite(suite)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='Require core pytest and native tests')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            if args.all:
                raise RuntimeError('--worker cannot run the core suite')
            return worker()
        environment = clean_environment()
        if args.all:
            core = subprocess.run(
                [sys.executable, '-B', '-m', 'pytest', '-q', '-m', 'not isaac_upstream'],
                cwd=ROOT, env=environment, check=False,
            )
            if core.returncode:
                return core.returncode
        native = subprocess.run(
            [str(ISAAC_ENV / 'bin/python'), '-I', '-B', str(Path(__file__).resolve()), '--worker'],
            cwd=ROOT, env=environment, check=False,
        )
        return native.returncode
    except (OSError, RuntimeError, ImportError, subprocess.SubprocessError) as exc:
        print(f'ISAAC UPSTREAM: FAIL ({exc})', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
