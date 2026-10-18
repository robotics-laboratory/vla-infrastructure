"""CPU composition checks for human native camera sessions; no Kit, HDF or GPU."""
from collections import deque
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from isaac_vr_native_session import NativeRuntimeSession

ROLES = ('left_wrist', 'right_wrist', 'scene')


class Media:
    def __init__(self, record, env, output, **options):
        assert record is None
        self.env, self.output, self.options = env, output, options
        self.rows = deque(maxlen=3)
        self.active, self.closed, self.writers = None, False, 0
        self.frame, self.epoch, self.captures, self.resets = 1, 0, 0, 0
        self.visibility = []
        self.preview = SimpleNamespace(set_visible=self.visibility.append)
        self.events = []
        self.failure = None

    def capture_boundary(self):
        self.captures += 1
        if self.failure:
            raise RuntimeError(self.failure)
        self.rows.append(dict(reset_epoch=self.epoch, native_result_identifiers={
            role: {'frameNumber': self.frame} for role in ROLES}))

    def start_recording(self, record, output):
        self.events.append(('start', record.episode_id))
        self.active = record
        self.writers += 1
        self.episode_output = output

    def stop_recording(self):
        self.events.append(('stop', self.active.episode_id))
        self.active = None
        self.writers -= 1
        if self.failure:
            raise RuntimeError(self.failure)
        return dict(captures=1, encoded_packets=1, cleanup_errors=[])

    def reset_source_epoch(self):
        self.resets += 1
        self.epoch += 1
        self.frame = 0
        self.rows.clear()

    def close(self):
        self.events.append(('close',))
        self.closed = True
        return dict(passed=True)


@pytest.fixture
def session(tmp_path, monkeypatch):
    import isaac_vr_native_bootstrap
    monkeypatch.setattr(isaac_vr_native_bootstrap, '_OWNED', [])
    args = SimpleNamespace(vr_runtime_variant='native-live', xr=True,
                           demo_hud_on_start=False, native_source_layer=object(),
                           report=tmp_path / 'reports' / 's2.json')
    obj = NativeRuntimeSession(SimpleNamespace(), args, media_type=Media)
    return obj


def episode(tmp_path, number):
    output = tmp_path / f'episode-{number}'
    output.mkdir()
    return SimpleNamespace(output_dir=output, episode_id=f'episode-{number}')


def test_run_session_never_opens_episode_writer_and_retains_one_media(session):
    import isaac_vr_native_bootstrap
    assert session.media.writers == 0
    assert session.media.options['preview'] is True
    assert session.media.visibility == [False]
    assert isaac_vr_native_bootstrap._OWNED == [session.media]
    for frame in range(1, 6):
        session.media.frame = frame
        assert session.capture_boundary()['strictly_advanced'] is True
    assert session.media.writers == 0 and not session.episodes
    assert not session.media.output.exists()
    session.close()
    assert session.media.closed
    assert session.report()['actual_quest_qualified'] is False
    assert session.report()['dataset_admissible'] is False


def test_two_episodes_reuse_media_and_write_exact_receipt_paths(session, tmp_path):
    media = session.media
    for number in range(2):
        record = episode(tmp_path, number)
        session.start_recording(record)
        assert media.episode_output == record.output_dir / 'live_rgb'
        assert media.writers == 1
        media.capture_boundary()  # Canonical recording capture owns acquisition.
        captures = media.captures
        session.capture_boundary()
        assert media.captures == captures
        result = session.stop_recording()
        saved = json.loads((record.output_dir / 'live_rgb_manifest.json').read_text())
        assert saved == result
        assert result['path'] == str(record.output_dir / 'live_rgb')
        assert result['episode_id'] == record.episode_id
        assert media.writers == 0 and session.active is None
        assert session.media is media and not media.closed
        media.frame += 1
    assert len(session.episodes) == 2
    session.close()
    assert media.events == [('start', 'episode-0'), ('stop', 'episode-0'),
                            ('start', 'episode-1'), ('stop', 'episode-1'), ('close',)]
    assert session.close() == session.receipt
    assert media.events.count(('close',)) == 1


def test_start_and_reset_reject_attached_episode_without_second_writer(session, tmp_path):
    session.start_recording(episode(tmp_path, 0))
    with pytest.raises(RuntimeError, match='still attached'):
        session.start_recording(episode(tmp_path, 1))
    with pytest.raises(RuntimeError, match='Stop recording'):
        session.reset()
    assert session.media.writers == 1 and session.media.resets == 0
    session.close()
    assert session.media.writers == 0


def test_staleness_tolerance_and_regression_fail_closed(session):
    session.capture_boundary()
    assert session.capture_boundary()['strictly_advanced'] is False
    assert session.capture_boundary()['strictly_advanced'] is False
    with pytest.raises(RuntimeError, match='Frozen native camera'):
        session.capture_boundary()
    assert session.last_sample['valid'] is False


def test_reset_accepts_new_epoch_lower_frame_and_invalidates_old_sample(session):
    session.media.frame = 500
    session.capture_boundary()
    session.reset()
    assert session.media.resets == 1 and not session.previous and not session.stale
    assert session.last_sample['valid'] is False
    assert session.capture_boundary()['strictly_advanced'] is True
    assert session.previous == dict.fromkeys(ROLES, 0)


@pytest.mark.parametrize('failure', ['missing_roles', 'regressed', 'missing_triplet', 'media_error'])
def test_camera_guard_errors_invalidate_previous_success(session, failure):
    session.capture_boundary()
    session.active = object()  # Inspect the row produced by the recording wrapper.
    if failure == 'missing_roles':
        del session.media.rows[-1]['native_result_identifiers']['scene']
    elif failure == 'regressed':
        session.media.rows[-1]['native_result_identifiers']['scene']['frameNumber'] = 0
    elif failure == 'missing_triplet':
        session.media.rows.clear()
    else:
        session.active = None
        session.media.failure = 'native producer failed'
    with pytest.raises(RuntimeError):
        session.capture_boundary()
    assert session.last_sample['valid'] is False


def test_close_drains_camera_after_episode_failure_and_does_not_write_success_manifest(session, tmp_path):
    record = episode(tmp_path, 0)
    session.start_recording(record)
    session.media.failure = 'encoder drain failed'
    with pytest.raises(RuntimeError, match='encoder drain failed'):
        session.close()
    assert session.active is None and session.media.closed and session.closed
    assert session.media.writers == 0
    assert not (record.output_dir / 'live_rgb_manifest.json').exists()


def test_guard_failure_does_not_partially_advance_role_history(session):
    session.capture_boundary()
    previous, stale = dict(session.previous), dict(session.stale)
    session.active = object()
    identities = session.media.rows[-1]['native_result_identifiers']
    identities['left_wrist']['frameNumber'] = 2
    identities['scene']['frameNumber'] = 0
    with pytest.raises(RuntimeError, match='regressed'):
        session.capture_boundary()
    assert session.previous == previous and session.stale == stale
    assert session.last_sample['valid'] is False


def test_tcp_pose_only_reads_no_jacobian_joints_or_limits():
    """Run the actual CPU-independent method while making extra native reads fail."""
    import ast
    import numpy as np
    source = (Path(__file__).resolve().parents[1] / 'tools/isaac_s2_runtime.py').read_text()
    cls = next(node for node in ast.parse(source).body
               if isinstance(node, ast.ClassDef) and node.name == '_BimanualDifferentialIk')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == '_state')
    namespace = {}
    exec(compile(ast.Module([method], []), 'actual_native_state_reader', 'exec'), namespace)
    reads = []
    poses = np.arange(21).reshape(1, 3, 7)
    root = np.arange(7).reshape(1, 7)
    class Data:
        def __getattr__(self, name):
            reads.append(name)
            if name == 'body_link_pose_w':
                return SimpleNamespace(torch=poses)
            if name == 'root_pose_w':
                return SimpleNamespace(torch=root)
            pytest.fail(f'Unrequested native state property: {name}')
    robot = SimpleNamespace(data=Data())
    owner = SimpleNamespace(env=SimpleNamespace())
    result = namespace['_state'](owner, 0, robot, 2, [], pose_only=True)
    assert reads == ['body_link_pose_w', 'root_pose_w']
    np.testing.assert_array_equal(result['tcp_pose_w'], poses[:, 2])
    assert result['root_pose_w'] is root
