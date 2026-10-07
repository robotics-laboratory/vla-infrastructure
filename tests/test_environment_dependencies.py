"""Environment checks must reject drift, including conflicts with unchanged counts."""

from copy import deepcopy
import json
import subprocess

import pytest

from tools import check_environment_dependencies as checker


@pytest.fixture
def core(tmp_path):
    (tmp_path / "pyproject.toml").write_text("""[project]
dependencies = ["lerobot-robot-piperx", "lerobot==0.6.1"]
[dependency-groups]
dev = ["pytest==9.1.1"]
isaac-teleop = ["isaacteleop==1.3.131"]
""")
    names = {
        "lerobot-robot-piperx": "0.1.0",
        "lerobot": "0.6.1",
        "pytest": "9.1.1",
        "numpy": "2.2.6",
        "torch": "2.7.1",
        "torchcodec": "0.5.0",
        "isaacteleop": "1.3.131",
    }
    packages = []
    for name, version in names.items():
        source = (
            'editable = "packages/plugin"'
            if name == "lerobot-robot-piperx"
            else 'registry = "https://pypi.org/simple"'
        )
        packages.append(
            f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {{{source}}}\n'
        )
    (tmp_path / "uv.lock").write_text("\n".join(packages))
    probe = {
        "python": "3.12.13",
        "platform": "linux",
        "machine": "x86_64",
        "prefix": str(tmp_path / "env"),
        "packages": names,
        "decoder": {"passed": True},
        "origins": {
            "lerobot-robot-piperx": {
                "url": (tmp_path / "packages/plugin").as_uri(),
                "dir_info": {"editable": True},
            }
        },
    }
    return tmp_path, probe


def test_correct_core_scope_accepts_current_checkout_without_commit_pin(core):
    root, probe = core
    assert checker.check_core_versions(root, probe, True) == []


@pytest.mark.parametrize("name", ["torchcodec", "isaacteleop", "lerobot"])
def test_changed_version_fails_even_with_working_import(core, name):
    root, probe = core
    probe["packages"][name] = "9.9.9"
    assert any(name in error for error in checker.check_core_versions(root, probe, True))


def test_wrong_editable_checkout_fails(core, tmp_path):
    root, probe = core
    probe["origins"]["lerobot-robot-piperx"]["url"] = (tmp_path / "other-checkout").as_uri()
    assert any(
        "editable origin" in error for error in checker.check_core_versions(root, probe, True)
    )


def test_unloadable_native_decoder_fails_despite_matching_versions(core):
    root, probe = core
    probe["decoder"] = {"passed": False, "error": "libtorchcodec cannot load"}
    assert "torchcodec.decoders import failed" in checker.check_core_versions(root, probe, True)


def test_linux_marker_selects_actual_branch(core):
    root, probe = core
    with (root / "uv.lock").open("a") as stream:
        stream.write("""[[package]]
name = "torch"
version = "9.9.9"
source = {registry = "https://pypi.org/simple"}
resolution-markers = ["sys_platform == 'win32'"]
""")
    assert checker.check_core_versions(root, probe, True) == []


def test_retained_conflicts_require_full_set_not_count():
    expected = checker.EXPECTED_CONFLICTS["isaac61"]
    assert checker.check_conflicts("isaac61", expected) == []
    changed = set(expected)
    changed.remove(next(iter(changed)))
    changed.add("new-owner requires broken==1, but 2 is installed")
    assert len(changed) == len(expected)
    errors = checker.check_conflicts("isaac61", changed)
    assert len(errors) == 2


def test_uv_failure_is_not_treated_as_empty_compatible_environment():
    with pytest.raises(RuntimeError, match="without dependency diagnostics"):
        checker.parse_conflicts(subprocess.CompletedProcess([], 1, "", "error: Python not found"))


def test_changed_python_or_sdk_prefix_fails(core):
    root, probe = core
    assert checker.check_identity(probe, root / "env") == []
    changed = deepcopy(probe)
    changed["python"] = "3.12.12"
    changed["prefix"] = str(root / "foreign-env")
    assert len(checker.check_identity(changed, root / "env")) == 2


@pytest.mark.parametrize("failed_command", ["lock", "sync"])
def test_upstream_spec_or_transitive_closure_drift_fails_without_install(
    core, monkeypatch, failed_command
):
    root, probe = core
    commands = []

    def run(arguments, *, environment):
        commands.append(arguments)
        if arguments[1] == "-I":
            return subprocess.CompletedProcess(arguments, 0, json.dumps(probe), "")
        if arguments[1] == "lock":
            return subprocess.CompletedProcess(
                arguments,
                int(failed_command == "lock"),
                "",
                "lock needs refresh" if failed_command == "lock" else "",
            )
        if arguments[1] == "sync":
            assert "--dry-run" in arguments and "--offline" in arguments
            return subprocess.CompletedProcess(
                arguments,
                0,
                "",
                "Would install missing-transitive"
                if failed_command == "sync"
                else "Would make no changes",
            )
        return subprocess.CompletedProcess(arguments, 0, "", "Checked packages")

    monkeypatch.setattr(checker, "run", run)
    report = checker.check("core", "/fake/python", True, root)
    assert not report["passed"]
    assert any("spec" in error for error in report["errors"])
    assert len(commands) == 4


def test_native_cpu_decoder_and_lerobot_timestamps_preserve_three_frames(tmp_path):
    """Exercise native libraries and LeRobot's explicit backend, rather than version strings."""
    from fractions import Fraction

    import av
    import numpy as np
    import torch
    from lerobot.datasets.video_utils import decode_video_frames
    from torchcodec.decoders import VideoDecoder

    video = tmp_path / "three-colors.mp4"
    with av.open(str(video), "w") as container:
        stream = container.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = 32, 24, "yuv420p"
        stream.options = {"crf": "0"}
        for index in range(3):
            rgb = np.zeros((24, 32, 3), dtype=np.uint8)
            rgb[..., index] = 255
            frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            frame.pts, frame.time_base = index, Fraction(1, 30)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)

    decoder = VideoDecoder(str(video), device="cpu")
    direct = decoder.get_frames_at(indices=[0, 1, 2])
    timestamps = [0.0, 1 / 30, 2 / 30]
    frames = decode_video_frames(
        video, timestamps, tolerance_s=1e-4, backend="torchcodec", return_uint8=True
    )
    assert len(decoder) == 3
    assert frames.shape == (3, 3, 24, 32)
    assert frames.dtype == torch.uint8 and frames.device.type == "cpu"
    torch.testing.assert_close(direct.data, frames, rtol=0, atol=0)
    torch.testing.assert_close(
        direct.pts_seconds, torch.tensor(timestamps, dtype=torch.float64), rtol=0, atol=1e-6
    )
    for index in range(3):
        means = frames[index].float().mean(dim=(1, 2))
        assert means[index] > 200
        assert means[[other for other in range(3) if other != index]].max() < 50
