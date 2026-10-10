"""Scoped LeRobot 0.6.1 import of already verified, preencoded episode videos.

Call after add_frame, then save_episode(parallel_encoding=False) inside the
context. The caller owns pixel/source joins and remux PTS validation. Upstream
still computes stats from real staging images and writes all dataset metadata.
No installed files or class methods are changed; one dataset, one episode only.
"""

from contextlib import contextmanager
import hashlib
from importlib.metadata import version
import inspect
from pathlib import Path
import shutil
import tempfile
from types import MethodType


WRITER_SHA256 = "319f4efb53e892ceeb439aae6d25209d14564e3dc91134c7cc2c6c0b5e71ebc5"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def existing_videos(dataset_or_writer, mapping):
    """Yield an import receipt; require one complete, serial save inside context.

    Mapping keys are the writer's video feature keys; values are immutable MP4
    paths containing exactly the pending action-row count (no terminal frame).
    In-flight writers, streaming, batching, depth and repeated episodes fail.
    """
    import av
    from lerobot.datasets.dataset_writer import DatasetWriter

    writer = getattr(dataset_or_writer, "writer", dataset_or_writer)
    if version("lerobot") != "0.6.1" or _sha(inspect.getfile(DatasetWriter)) != WRITER_SHA256:
        raise RuntimeError("Unaudited LeRobot writer version/source")
    if type(writer) is not DatasetWriter:
        raise TypeError("Require the exact audited DatasetWriter instance")
    count = writer.episode_buffer["size"]
    if (
        writer._meta.total_episodes != 0
        or writer.episode_buffer["episode_index"] != 0
        or count < 1
        or writer._streaming_encoder is not None
        or writer._batch_encoding_size != 1
        or writer._meta.depth_keys
        or writer._finalized
    ):
        raise ValueError("Require one pending, nonstreaming RGB episode zero")
    paths = {key: Path(value).resolve(strict=True) for key, value in mapping.items()}
    if not paths or set(paths) != set(writer._meta.video_keys):
        raise ValueError("Missing or unexpected video cameras")
    if len(set(paths.values())) != len(paths) or len(
        {p.stat().st_ino for p in paths.values()}
    ) != len(paths):
        raise ValueError("Duplicate camera video sources")
    source_hashes = {}
    for key, path in paths.items():
        with av.open(str(path)) as container:
            if len(container.streams) != 1 or len(container.streams.video) != 1:
                raise ValueError("Require one video-only MP4 stream")
            stream = container.streams.video[0]
            shape = tuple(writer._meta.features[key]["shape"])
            if (
                path.suffix.lower() != ".mp4"
                or stream.frames != count
                or stream.average_rate != writer._meta.fps
                or (stream.height, stream.width, 3) != shape
            ):
                raise ValueError("Video count/FPS/shape differs from pending episode")
        source_hashes[key] = _sha(path)
    names = ("_encode_temporary_episode_video", "save_episode", "_rgb_encoder")
    absent = object()
    saved = {name: writer.__dict__.get(name, absent) for name in names}
    if saved[names[0]] is not absent or saved[names[1]] is not absent:
        raise ValueError("Writer already has instance method overrides")
    original_save = writer.save_episode
    receipt = dict(
        writer_sha256=WRITER_SHA256,
        frames=count,
        imported=[],
        source_sha256=source_hashes,
        reencoded=False,
    )
    disposable = []

    def imported_video(self, video_key, episode_index):
        if episode_index != 0 or video_key not in paths or video_key in receipt["imported"]:
            raise ValueError("Unexpected or duplicate video import")
        directory = Path(tempfile.mkdtemp(prefix="preencoded-", dir=self._root))
        disposable.append(directory)
        target = directory / "episode.mp4"
        shutil.copyfile(paths[video_key], target)
        if _sha(target) != source_hashes[video_key]:
            raise RuntimeError("Source video changed during import")
        receipt["imported"].append(video_key)
        return target

    def serial_save(self, episode_data=None, parallel_encoding=True):
        if parallel_encoding or episode_data is not None:
            raise ValueError(
                "Import requires save_episode(parallel_encoding=False), no episode_data"
            )
        if self._meta.total_episodes != 0 or self.episode_buffer["size"] != count:
            raise ValueError("Pending episode changed during import")
        return original_save(parallel_encoding=False)

    try:
        writer._encode_temporary_episode_video = MethodType(imported_video, writer)
        writer.save_episode = MethodType(serial_save, writer)
        writer._rgb_encoder = None  # Derive metadata from stream, never invented encoder settings.
        yield receipt
        if set(receipt["imported"]) != set(paths) or writer._meta.total_episodes != 1:
            raise RuntimeError("Context ended without importing the complete episode")
        if any(_sha(path) != source_hashes[key] for key, path in paths.items()):
            raise RuntimeError("Source video changed during import")
    finally:
        for name, value in saved.items():
            if value is absent:
                writer.__dict__.pop(name, None)
            else:
                setattr(writer, name, value)
        for directory in disposable:
            shutil.rmtree(directory, ignore_errors=True)
