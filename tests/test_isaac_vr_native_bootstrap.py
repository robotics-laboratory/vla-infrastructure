"""Native dependency bootstrap boundary tests with mocked compiler/CUPTI calls."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import isaac_vr_native_bootstrap as bootstrap
from isaac_vr_runtime_profiles import load_runtime_profile


@pytest.fixture(autouse=True)
def isolate_process_state(monkeypatch):
    monkeypatch.setattr(bootstrap, '_OWNED', [])
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.delenv('VLA_NATIVE_COPY_SHIM', raising=False)
    monkeypatch.delenv('VLA_CUPTI_LIBRARY', raising=False)


def codec_target(tmp_path, monkeypatch, version='2.2.3'):
    target = tmp_path / 'codec'
    metadata = target / f'PyNvVideoCodec-{version}.dist-info'
    metadata.mkdir(parents=True)
    (metadata / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: PyNvVideoCodec\nVersion: {version}\n')
    monkeypatch.setenv('VLA_NATIVE_CODEC_ROOT', str(target))
    return target


def shim_target(tmp_path, monkeypatch):
    shim = tmp_path / 'provider_copy_cupti.so'
    shim.write_bytes(b'fake shared library; never loaded')
    cupti = tmp_path / 'libcupti.so.12'
    cupti.write_bytes(b'fake pinned CUPTI; never loaded')
    monkeypatch.setattr(bootstrap, 'CUPTI', cupti)
    monkeypatch.setattr(bootstrap, 'CUPTI_SHA256', bootstrap._sha(cupti))
    build = {'source_sha256': bootstrap._sha(bootstrap.SOURCE), 'returncode': 0}
    monkeypatch.setattr(bootstrap, 'build_copy_shim', lambda output: (shim, build))
    return shim, build


def test_selected_and_master_prepare_are_pure_noops(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('selected profile touched native prerequisites')
    monkeypatch.setattr(bootstrap.importlib.metadata, 'distributions', unexpected)
    for name in ('selected', 'master'):
        output = tmp_path / name
        assert bootstrap.prepare(load_runtime_profile(name), output, library_loader=unexpected) == {}
        assert not output.exists()


@pytest.mark.parametrize('version', ['2.2.2', '2.2.4', '3.0.0'])
def test_wrong_codec_version_fails_with_dependency_receipt(tmp_path, monkeypatch, version):
    target = codec_target(tmp_path, monkeypatch, version)
    output = tmp_path / 'receipt'
    with pytest.raises(RuntimeError, match='2.2.3'):
        bootstrap.prepare(load_runtime_profile('native-sync'), output)
    receipt = json.loads((output / 'native_dependencies.json').read_text())
    assert receipt['passed'] is False and '2.2.3' in receipt['error']
    assert str(target) not in sys.path


def test_missing_codec_target_fails_without_installing_or_mutating_sys_path(tmp_path, monkeypatch):
    target = tmp_path / 'absent'
    monkeypatch.setenv('VLA_NATIVE_CODEC_ROOT', str(target))
    before = list(sys.path)
    with pytest.raises(RuntimeError, match='target missing'):
        bootstrap.prepare(load_runtime_profile('native-live'), tmp_path / 'receipt')
    assert before == sys.path and not target.exists()
    receipt = json.loads((tmp_path / 'receipt/native_dependencies.json').read_text())
    assert receipt['passed'] is False


def test_sync_preparation_uses_tested_codec_without_loading_cupti(tmp_path, monkeypatch):
    target = codec_target(tmp_path, monkeypatch)
    loader = Mock(side_effect=AssertionError('CUPTI requested for sync preview'))
    receipt = bootstrap.prepare(load_runtime_profile('native-sync'), tmp_path / 'receipt', library_loader=loader)
    assert receipt['passed'] is True
    assert receipt['codec'] == {'root': str(target), 'version': '2.2.3'}
    assert sys.path[0] == str(target)
    loader.assert_not_called()


def test_early_owned_subscription_is_retained_and_receipted(tmp_path, monkeypatch):
    codec_target(tmp_path, monkeypatch)
    shim, build = shim_target(tmp_path, monkeypatch)
    library = SimpleNamespace(vla_copy_probe_init=Mock(return_value=0))
    loader = Mock(return_value=library)
    receipt = bootstrap.prepare(load_runtime_profile('native-event'), tmp_path / 'receipt', library_loader=loader)
    loader.assert_called_once_with(str(shim))
    library.vla_copy_probe_init.assert_called_once_with()
    assert bootstrap._OWNED == [library]
    assert receipt['copy_shim']['subscription_status'] == 0
    assert receipt['copy_shim']['sha256'] == bootstrap._sha(shim)
    assert receipt['copy_shim']['build'] == build
    assert receipt['passed'] is True


def test_foreign_cupti_subscription_failure_is_retained_without_unsubscribe(tmp_path, monkeypatch):
    codec_target(tmp_path, monkeypatch)
    shim_target(tmp_path, monkeypatch)
    foreign = object()
    bootstrap._OWNED.append(foreign)
    library = SimpleNamespace(vla_copy_probe_init=Mock(return_value=-1039),
                              cuptiUnsubscribe=Mock(side_effect=AssertionError('foreign subscriber removed')))
    with pytest.raises(RuntimeError, match='-1039'):
        bootstrap.prepare(load_runtime_profile('native-live'), tmp_path / 'receipt',
                          library_loader=Mock(return_value=library))
    library.cuptiUnsubscribe.assert_not_called()
    assert bootstrap._OWNED == [foreign]
    receipt = json.loads((tmp_path / 'receipt/native_dependencies.json').read_text())
    assert receipt['passed'] is False and receipt['copy_shim']['subscription_status'] == -1039


@pytest.fixture
def headers(tmp_path, monkeypatch):
    isaac = tmp_path / 'isaac'
    include = isaac / 'lib/python3.12/site-packages/isaacsim/extscache/omni.rtx.spg-1.0/deps/cuda/include'
    include.mkdir(parents=True)
    for name in ('cuda.h', 'cuda_runtime_api.h', 'cupti.h'):
        (include / name).write_text(f'// fake {name}\n')
    monkeypatch.setattr(bootstrap, 'ISAAC', isaac)
    return include


@pytest.mark.parametrize('returncode', [0, 2])
def test_copy_shim_build_preserves_command_input_hashes_and_compiler_failure(tmp_path, monkeypatch, headers, returncode):
    def run(command, *, capture_output, text):
        assert capture_output and text
        assert command[0] == 'g++' and '-Werror' in command
        if returncode == 0:
            Path(command[command.index('-o') + 1]).write_bytes(b'fake compiler output')
        return SimpleNamespace(returncode=returncode, stdout='compiler stdout', stderr='compiler stderr')
    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    output = tmp_path / 'build'
    if returncode:
        with pytest.raises(RuntimeError, match='build failed'):
            bootstrap.build_copy_shim(output)
    else:
        binary, receipt = bootstrap.build_copy_shim(output)
        assert binary.exists() and binary.parent == output
    receipt = json.loads((output / 'build.json').read_text())
    assert receipt['returncode'] == returncode
    assert receipt['source_sha256'] == bootstrap._sha(bootstrap.SOURCE)
    assert receipt['headers'] == {name: bootstrap._sha(headers / name)
                                  for name in ('cuda.h', 'cuda_runtime_api.h', 'cupti.h')}
    assert receipt['stdout'] == 'compiler stdout' and receipt['stderr'] == 'compiler stderr'


def test_copy_shim_source_is_byte_identical_to_retained_audit():
    audited = bootstrap.ROOT / 'docs/experiments/20261009_live_camera_recording_30hz/native_deep/provider_copy_cupti.cpp'
    assert hashlib.sha256(bootstrap.SOURCE.read_bytes()).digest() == hashlib.sha256(audited.read_bytes()).digest()


def test_stage_preparation_only_runs_for_source_proof_and_retains_layer(monkeypatch):
    import isaac_vr_native_source_proof
    prepare = Mock(return_value=object())
    monkeypatch.setattr(isaac_vr_native_source_proof, 'prepare_source_proof_stage', prepare)
    sim = object()
    for name in ('selected', 'native-sync', 'native-event'):
        assert bootstrap.prepare_stage(load_runtime_profile(name), sim) is None
    prepare.assert_not_called()
    layer = bootstrap.prepare_stage(load_runtime_profile('native-live'), sim)
    prepare.assert_called_once_with(sim, clock_only=True, attribute_probe=True, attribute_only=True, identity_only=True)
    assert bootstrap._OWNED == [layer]


@pytest.mark.parametrize('failure', ['missing', 'changed'])
def test_unpinned_cupti_fails_before_build_or_subscription(tmp_path, monkeypatch, failure):
    codec_target(tmp_path, monkeypatch)
    shim_target(tmp_path, monkeypatch)
    if failure == 'missing':
        bootstrap.CUPTI.unlink()
    else:
        bootstrap.CUPTI.write_bytes(b'changed CUPTI bytes')
    build = Mock(side_effect=AssertionError('building before CUPTI identity validation'))
    monkeypatch.setattr(bootstrap, 'build_copy_shim', build)
    loader = Mock(side_effect=AssertionError('loading unpinned CUPTI'))
    with pytest.raises(RuntimeError, match='Pinned CUPTI library missing or changed'):
        bootstrap.prepare(load_runtime_profile('native-event'), tmp_path / 'receipt', library_loader=loader)
    build.assert_not_called()
    loader.assert_not_called()
    assert json.loads((tmp_path / 'receipt/native_dependencies.json').read_text())['passed'] is False


@pytest.mark.parametrize('tree_count', [0, 2])
def test_header_tree_ambiguity_fails_before_compilation(tmp_path, monkeypatch, tree_count):
    isaac = tmp_path / 'isaac'
    for index in range(tree_count):
        (isaac / f'lib/python3.12/site-packages/isaacsim/extscache/omni.rtx.spg-{index}/deps/cuda/include').mkdir(parents=True)
    monkeypatch.setattr(bootstrap, 'ISAAC', isaac)
    compiler = Mock(side_effect=AssertionError('ambiguous SDK headers used'))
    monkeypatch.setattr(bootstrap.subprocess, 'run', compiler)
    with pytest.raises(RuntimeError, match='Expected one pinned CUDA header tree'):
        bootstrap.build_copy_shim(tmp_path / 'build')
    compiler.assert_not_called()
