"""CPU integration against the pinned upstream writer; encoding is forbidden at import."""

import hashlib
from pathlib import Path

import numpy as np
import pytest

from tools import isaac_vr_live_video_import as importer

av = pytest.importorskip("av")
dataset_writer = pytest.importorskip("lerobot.datasets.dataset_writer")
LeRobotDataset = pytest.importorskip("lerobot.datasets.lerobot_dataset").LeRobotDataset


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def episode(tmp_path):
    paths, decoded = {}, {}
    for role in ("left_wrist", "right_wrist", "scene"):
        key = f"observation.images.{role}"
        path = tmp_path / f"{role}.mp4"
        with av.open(str(path), "w") as container:
            stream = container.add_stream("libx264", rate=30)
            stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
            stream.codec_context.max_b_frames = 0
            stream.codec_context.thread_count = 1
            for i in range(4):
                pixels = np.full((48, 64, 3), 20 + i * 30, dtype=np.uint8)
                for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        paths[key] = path
        with av.open(str(path)) as container:
            decoded[key] = [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]
    features = {
        "observation.state": {"dtype": "float32", "shape": (2,), "names": ["a", "b"]},
        "action": {"dtype": "float32", "shape": (2,), "names": ["a", "b"]},
        **{
            key: {"dtype": "video", "shape": (48, 64, 3), "names": ["height", "width", "channels"]}
            for key in paths
        },
    }
    dataset = LeRobotDataset.create(
        "audit/import",
        fps=30,
        features=features,
        root=tmp_path / "dataset",
        use_videos=True,
        video_backend="pyav",
    )
    for i in range(4):
        dataset.add_frame(
            {
                "observation.state": np.array([i, i + 1], np.float32),
                "action": np.array([i + 2, i + 3], np.float32),
                "task": "Synthetic CPU test",
                **{key: images[i] for key, images in decoded.items()},
            }
        )
    yield dataset, paths, decoded
    dataset.finalize()


def test_upstream_import_is_byte_exact_and_readable_without_encoding(episode, monkeypatch):
    dataset, paths, decoded = episode
    hashes = {key: _hash(path) for key, path in paths.items()}

    def forbidden(*args, **kwargs):
        raise AssertionError("Import attempted video encoding")

    monkeypatch.setattr(dataset_writer, "encode_video_frames", forbidden)
    monkeypatch.setattr(dataset_writer, "_encode_video_worker", forbidden)
    before_encoder = dataset.writer._rgb_encoder
    with importer.existing_videos(dataset, paths) as receipt:
        dataset.save_episode(parallel_encoding=False)
    dataset.finalize()
    assert len(receipt["imported"]) == 3 and receipt["reencoded"] is False
    assert "_encode_temporary_episode_video" not in dataset.writer.__dict__
    assert "save_episode" not in dataset.writer.__dict__
    assert dataset.writer._rgb_encoder is before_encoder
    loaded = LeRobotDataset(
        "audit/import", root=dataset.root, video_backend="pyav", return_uint8=True
    )
    assert len(loaded) == 4
    for key, path in paths.items():
        destination = dataset.root / loaded.meta.get_video_file_path(0, key)
        assert _hash(destination) == hashes[key] == _hash(path)
        assert "video.crf" not in loaded.features[key]["info"]
    for i in range(4):
        frame = loaded[i]
        np.testing.assert_array_equal(frame["observation.state"].numpy(), [i, i + 1])
        np.testing.assert_array_equal(frame["action"].numpy(), [i + 2, i + 3])
        for key in paths:
            np.testing.assert_array_equal(frame[key].numpy().transpose(1, 2, 0), decoded[key][i])


@pytest.mark.parametrize(
    "invalid", ["missing", "unexpected", "duplicate", "count", "episode", "pin"]
)
def test_fail_closed_before_import(episode, monkeypatch, invalid):
    dataset, paths, _ = episode
    paths = dict(paths)
    if invalid == "missing":
        paths.pop(next(iter(paths)))
    elif invalid == "unexpected":
        paths["unknown"] = next(iter(paths.values()))
    elif invalid == "duplicate":
        paths[list(paths)[1]] = next(iter(paths.values()))
    elif invalid == "count":
        dataset.writer.episode_buffer["size"] += 1
    elif invalid == "episode":
        dataset.writer.episode_buffer["episode_index"] = 1
    elif invalid == "pin":
        monkeypatch.setattr(importer, "WRITER_SHA256", "0" * 64)
    with pytest.raises((ValueError, RuntimeError)):
        with importer.existing_videos(dataset, paths):
            pytest.fail("Invalid source was accepted")
    assert "save_episode" not in dataset.writer.__dict__


@pytest.mark.parametrize("mode", ["parallel", "exception", "no_save"])
def test_restore_on_failure_and_reject_parallel_encoding(episode, mode):
    dataset, paths, _ = episode
    original = dataset.writer._rgb_encoder
    with pytest.raises((ValueError, RuntimeError)):
        with importer.existing_videos(dataset.writer, paths):
            if mode == "parallel":
                dataset.save_episode()  # Must reject before upstream starts subprocess encoders.
            elif mode == "exception":
                raise RuntimeError("caller failure")
    assert "save_episode" not in dataset.writer.__dict__
    assert "_encode_temporary_episode_video" not in dataset.writer.__dict__
    assert dataset.writer._rgb_encoder is original
    assert all(path.is_file() for path in paths.values())
