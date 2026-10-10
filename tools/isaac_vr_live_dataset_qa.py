"""One-pass experimental LeRobot QA with bounded, optionally spawned CPU readers.

Uses public uint8 video decoding: exact RGB fingerprints need no float rounding,
and IPC carries one byte/channel. CPU affinity is inherited from the launcher.
The caller supplies independently bound source fingerprints and projection.
"""

import hashlib
import os

import numpy as np

try:
    from . import isaac_vr_lerobot_materialize as common
except ImportError:
    import isaac_vr_lerobot_materialize as common


def _worker_init(_worker_id):
    import torch

    torch.set_num_threads(1)


def _check(condition, message):
    if not condition:
        raise common.MaterializationError(message)


def qa_live_dataset(
    root,
    *,
    repo_id,
    arrays,
    task,
    decoded_rgb_sha256,
    workers=0,
    image_shape=common.IMAGE_SHAPE,
):
    """One full DataLoader pass plus at most six default-float sample rows."""
    import torch
    from torch.utils.data import DataLoader, Subset
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    _check(type(workers) is int and workers in (0, 2, 4), "QA workers must be 0, 2 or 4")
    frames = common._validate_projection_arrays(arrays)
    video_keys = [f"observation.images.{role}" for role in common.CAMERA_ROLES]
    _check(set(decoded_rgb_sha256) == set(video_keys), "RGB fingerprint cameras differ")
    for key in video_keys:
        _check(len(decoded_rgb_sha256[key]) == frames, "RGB fingerprint count differs")
        for digest in decoded_rgb_sha256[key]:
            common._require_sha256(digest, field=f"RGB fingerprint {key}")
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        dataset = LeRobotDataset(repo_id, root=root, video_backend="pyav", return_uint8=True)
        _check(len(dataset) == frames, "LeRobot full-read frame count mismatch")
        for key, expected in common.canonical_lerobot_features(image_shape).items():
            actual = dataset.features.get(key, {})
            for field in ("dtype", "shape", "names"):
                value = tuple(actual.get(field, ())) if field == "shape" else actual.get(field)
                wanted = tuple(expected[field]) if field == "shape" else expected[field]
                _check(value == wanted, f"LeRobot feature {key}.{field} differs from schema")
        options = dict(batch_size=1, shuffle=False, num_workers=workers, pin_memory=False)
        if workers:
            options.update(
                multiprocessing_context="spawn",
                prefetch_factor=1,
                worker_init_fn=_worker_init,
                persistent_workers=False,
            )
        loader = DataLoader(dataset, **options)
        samples = sorted(
            {
                i
                for start in (0, frames // 2, max(0, frames - 2))
                for i in range(start, min(start + 2, frames))
            }
        )
        sample_rgb = {}
        visited = 0
        iterator = iter(loader)
        try:
            for index, batch in enumerate(iterator):
                _check(index < frames, "DataLoader returned extra rows")
                for key, source_key in (
                    ("observation.state", "observation_state"),
                    ("action", "action"),
                ):
                    value = batch[key]
                    _check(
                        value.dtype == torch.float32
                        and tuple(value.shape) == (1, *common.VECTOR_SHAPE),
                        f"DataLoader {key} dtype/shape differs",
                    )
                    _check(
                        np.array_equal(value[0].numpy(), arrays[source_key][index]),
                        f"DataLoader {key} changed at row {index}",
                    )
                _check(list(batch["task"]) == [task], f"DataLoader task differs at row {index}")
                for key, wanted in (
                    ("frame_index", index),
                    ("index", index),
                    ("episode_index", 0),
                    ("task_index", 0),
                ):
                    value = batch[key]
                    _check(
                        value.dtype == torch.int64
                        and tuple(value.shape) == (1,)
                        and value.item() == wanted,
                        f"DataLoader {key} differs at row {index}",
                    )
                timestamp = batch["timestamp"]
                _check(
                    timestamp.dtype == torch.float32
                    and tuple(timestamp.shape) == (1,)
                    and timestamp.item() == np.float32(index / common.FPS).item(),
                    f"DataLoader timestamp differs at row {index}",
                )
                for key in video_keys:
                    image = batch[key]
                    _check(
                        image.dtype == torch.uint8
                        and tuple(image.shape) == (1, 3, image_shape[0], image_shape[1]),
                        f"DataLoader {key} decode dtype/shape differs at row {index}",
                    )
                    digest = hashlib.sha256(
                        image[0].numpy().transpose(1, 2, 0).tobytes()
                    ).hexdigest()
                    _check(
                        digest == decoded_rgb_sha256[key][index],
                        f"RGB fingerprint differs for {key} at row {index}",
                    )
                    if index in samples:
                        sample_rgb[index, key] = image[0].clone()
                visited += 1
        finally:
            del iterator
        _check(visited == frames, "DataLoader did not visit every frame")
        float_dataset = LeRobotDataset(repo_id, root=root, video_backend="pyav")
        float_loader = DataLoader(Subset(float_dataset, samples), batch_size=2, num_workers=0)
        float_rows = 0
        for batch in float_loader:
            for position, row in enumerate(batch["frame_index"].tolist()):
                _check(row == samples[float_rows], "Default-float sample index differs")
                for key in video_keys:
                    actual = batch[key][position]
                    expected = sample_rgb[row, key].to(torch.float32) / 255
                    _check(
                        actual.dtype == torch.float32 and torch.equal(actual, expected),
                        f"Default-float RGB conversion differs for {key} at row {row}",
                    )
                float_rows += 1
        _check(float_rows == len(samples), "Default-float samples incomplete")
        return dict(
            all_frames_read=visited,
            all_video_frames_decoded=visited * len(video_keys),
            dataloader_batches=visited,
            dataloader_frames=visited,
            rgb_fingerprints_verified=True,
            passes=1,
            workers=workers,
            prefetch_factor=1 if workers else None,
            multiprocessing_context="spawn" if workers else None,
            torch_threads=1,
            video_dtype="uint8",
            cpu_affinity=sorted(os.sched_getaffinity(0)),
            float_sample_rows=samples,
            float_video_frames_decoded=float_rows * len(video_keys),
        )
    finally:
        torch.set_num_threads(previous_threads)
