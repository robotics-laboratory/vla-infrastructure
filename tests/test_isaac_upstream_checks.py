"""Fail-closed native validation and the isolated core/SDK command boundary."""
from pathlib import Path
from types import SimpleNamespace
import unittest

import pytest

from tools import check_isaac_upstream as checks


@pytest.mark.parametrize('body, expected', [
    ('pass', 0),
    ('self.fail("regression")', 1),
    ('raise RuntimeError("broken import/API")', 1),
    ('self.skipTest("missing SDK")', 1),
])
def test_real_discovery_requires_success_without_skips(tmp_path, body, expected):
    # Discover actual modules rather than fabricating a runner's result object.
    name = 'test_probe_' + tmp_path.name.replace('-', '_') + '.py'
    (tmp_path / name).write_text(
        'import unittest\nclass NativeProbe(unittest.TestCase):\n'
        f'    def test_probe(self):\n        {body}\n'
    )
    suite = unittest.TestLoader().discover(str(tmp_path), pattern=name)
    assert checks.run_suite(suite) == expected


def test_import_failure_does_not_become_empty_success(tmp_path):
    name = 'test_import_probe_' + tmp_path.name.replace('-', '_') + '.py'
    (tmp_path / name).write_text('raise ImportError("required upstream module unavailable")\n')
    assert checks.run_suite(unittest.TestLoader().discover(str(tmp_path), pattern=name)) == 1


def test_empty_discovery_fails(tmp_path):
    assert checks.run_suite(unittest.TestLoader().discover(str(tmp_path))) == 1


def test_class_setup_skip_fails_even_when_no_test_body_runs():
    class MissingSDK(unittest.TestCase):
        @classmethod
        def setUpClass(cls):
            raise unittest.SkipTest('SDK unavailable')

        def test_body(self):
            raise AssertionError('must not run')

    assert checks.run_suite(unittest.TestLoader().loadTestsFromTestCase(MissingSDK)) == 1


def test_expected_failure_is_not_validation_success():
    class KnownFailure(unittest.TestCase):
        @unittest.expectedFailure
        def test_body(self):
            self.fail('API drift remains')

    assert checks.run_suite(unittest.TestLoader().loadTestsFromTestCase(KnownFailure)) == 1


def test_native_command_uses_only_explicit_checkout_and_sdk(monkeypatch):
    monkeypatch.setenv('PYTHONPATH', '/some/other/branch')
    monkeypatch.setenv('PYTHONHOME', '/some/other/sdk')
    monkeypatch.setenv('VIRTUAL_ENV', '/some/other/env')
    monkeypatch.setenv('HF_HOME', '/tmp/preserve-cache-selection')
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(checks.subprocess, 'run', run)
    assert checks.main([]) == 0
    command, kwargs = calls[0]
    assert command == [str(checks.ISAAC_ENV / 'bin/python'), '-I', '-B',
                       str(Path(checks.__file__).resolve()), '--worker']
    assert kwargs['cwd'] == checks.ROOT
    assert not {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'} & kwargs['env'].keys()
    assert kwargs['env']['HF_HOME'] == '/tmp/preserve-cache-selection'


@pytest.mark.parametrize('core_exit, native_exit, expected, call_count', [
    (0, 0, 0, 2), (1, 0, 1, 1), (0, 1, 1, 2),
])
def test_all_requires_both_suites_in_their_own_interpreters(
    monkeypatch, core_exit, native_exit, expected, call_count,
):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=core_exit if len(calls) == 1 else native_exit)

    monkeypatch.setattr(checks.subprocess, 'run', run)
    assert checks.main(['--all']) == expected
    assert len(calls) == call_count
    assert calls[0] == [checks.sys.executable, '-B', '-m', 'pytest', '-q',
                        '-m', 'not isaac_upstream']
    if call_count == 2:
        assert calls[1][0] == str(checks.ISAAC_ENV / 'bin/python')


def test_missing_sdk_is_failure(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError('SDK interpreter unavailable')

    monkeypatch.setattr(checks.subprocess, 'run', missing)
    assert checks.main([]) == 1


def test_worker_rejects_wrong_sdk_before_loading_upstream(monkeypatch):
    monkeypatch.setattr(checks.sys, 'prefix', '/tmp/wrong-sdk')
    assert checks.main(['--worker']) == 1
