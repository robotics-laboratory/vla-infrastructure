"""CPU-only source/actual-row microbench; never imports Kit, torch or CUDA.

Use the declared Isaac Python because core has no h5py. Upstream storage.py,
base.py and manifest.py are loaded byte-for-byte into a private package;
only carb.log_warn is stubbed. This does not simulate recording or qualify XR.
"""

from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import types
import numpy as np
import h5py


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1048576), b""):
            h.update(b)
    return h.hexdigest()


def stats(ns):
    a = np.asarray(ns, dtype=np.float64) / 1e6
    return dict(
        samples=len(ns),
        mean_ms=float(a.mean()),
        p50_ms=float(np.quantile(a, 0.5)),
        p99_ms=float(np.quantile(a, 0.99)),
        max_ms=float(a.max()),
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repo", type=Path, default=Path("/home/ebulochkin/vla_infrastructure"))
    p.add_argument(
        "--upstream",
        type=Path,
        default=Path(
            "/data/vla-infrastructure/isaac61_production/env/lib/python3.12/site-packages/isaacsim/exts/isaacsim.replicator.episode_recorder/isaacsim/replicator/episode_recorder"
        ),
    )
    p.add_argument("--repeat", type=int, default=3)
    a = p.parse_args()
    a.output.mkdir(exist_ok=False)
    sys.path.insert(0, str(a.repo))
    from tools.isaac_vr_recording import _captured_frame_sha256, ExplicitFrameSampler

    root = types.ModuleType("_cpu_upstream")
    root.__path__ = [str(a.upstream)]
    sys.modules[root.__name__] = root
    carb = types.ModuleType("carb")
    carb.log_warn = lambda s: None
    sys.modules["carb"] = carb
    mods = {}
    for name in ("base", "manifest", "storage"):
        spec = importlib.util.spec_from_file_location(
            "_cpu_upstream." + name, a.upstream / (name + ".py")
        )
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        mods[name] = m
    schemas = {}
    arrays = {}
    with h5py.File(a.input, "r") as f:
        e = f["episodes"][sorted(f["episodes"])[0]]

        def collect(path, obj):
            if isinstance(obj, h5py.Dataset):
                g, c = path.rsplit("/", 1)
                schemas.setdefault(g, {})[c] = mods["base"].ChannelDescriptor(
                    shape=obj.shape[1:], dtype=obj.dtype.str
                )
                arrays.setdefault(g, {})[c] = obj[:]

        e.visititems(collect)
    n = next(iter(next(iter(arrays.values())).values())).shape[0]
    rows = [
        {
            g: {c: np.asarray(v[i], dtype=v.dtype) for c, v in channels.items()}
            for g, channels in arrays.items()
        }
        for i in range(n)
    ]
    observations = [{g: v for g, v in r.items() if g != "d0/committed_transition"} for r in rows]
    copy_ns = []
    hash_ns = []
    validate_ns = []
    canonical_ns = []
    verify_ns = []
    from tools.isaac_vr_recording import (
        canonical_committed_transition,
        verify_committed_transition_sample,
    )

    validator = object.__new__(ExplicitFrameSampler)
    validator._schemas = schemas
    for _ in range(a.repeat):
        for obs, row in zip(observations, rows):
            t = time.perf_counter_ns()
            frozen = {g: {c: v.copy() for c, v in channels.items()} for g, channels in obs.items()}
            copy_ns.append(time.perf_counter_ns() - t)
            t = time.perf_counter_ns()
            _captured_frame_sha256(frozen)
            hash_ns.append(time.perf_counter_ns() - t)
            t = time.perf_counter_ns()
            for g, v in row.items():
                validator._validate(g, v)
            validate_ns.append(time.perf_counter_ns() - t)
            t = time.perf_counter_ns()
            canonical = canonical_committed_transition(row["d0/committed_transition"])
            canonical_ns.append(time.perf_counter_ns() - t)
            t = time.perf_counter_ns()
            verify_committed_transition_sample(canonical)
            verify_ns.append(time.perf_counter_ns() - t)
    cases = []
    for flush_every in (64, 128, 256):
        path = a.output / ("flush" + str(flush_every) + ".hdf5")
        s = mods["storage"].SessionStorage(str(path), buffer_frames=128)
        s.open()
        s.begin_episode(schemas)
        append = []
        flush = []
        total_start = time.perf_counter_ns()
        for i, row in enumerate(rows):
            t = time.perf_counter_ns()
            for g, v in row.items():
                s.append_frame(g, v)
            s.advance_episode_frame()
            append.append(time.perf_counter_ns() - t)
            if (i + 1) % flush_every == 0:
                t = time.perf_counter_ns()
                s.flush()
                flush.append(time.perf_counter_ns() - t)
        t = time.perf_counter_ns()
        s.close()
        close_ns = time.perf_counter_ns() - t
        elapsed = time.perf_counter_ns() - total_start
        with h5py.File(path, "r") as f:
            e = f["episodes"]["episode_00000"]
            for g, channels in arrays.items():
                for c, v in channels.items():
                    np.testing.assert_array_equal(e[g][c][:], v)
        cases.append(
            dict(
                flush_every=flush_every,
                buffer_frames=128,
                append=stats(append),
                explicit_flush=stats(flush),
                close_ms=close_ns / 1e6,
                total_ms=elapsed / 1e6,
                file_bytes=path.stat().st_size,
                output_sha256=sha(path),
                all_channels_equal=True,
            )
        )
    result = dict(
        schema="live30_cpu_storage_microbench_v1",
        dataset_admissible=False,
        quest_connected=False,
        gpu_execution=False,
        python=sys.executable,
        python_version=sys.version,
        numpy=np.__version__,
        h5py=h5py.__version__,
        hdf5=h5py.version.hdf5_version,
        input=str(a.input),
        input_sha256=sha(a.input),
        script_sha256=sha(__file__),
        source_hashes={str(a.upstream / (n + ".py")): sha(a.upstream / (n + ".py")) for n in mods},
        project_source_sha256=sha(a.repo / "tools/isaac_vr_recording.py"),
        rows=n,
        groups=len(schemas),
        channels=sum(map(len, schemas.values())),
        bytes_per_row=sum(
            v.dtype.itemsize * int(np.prod(v.shape[1:]))
            for c in arrays.values()
            for v in c.values()
        ),
        bytes_per_observation=sum(v.nbytes for c in observations[0].values() for v in c.values()),
        timings=dict(
            copy_observation=stats(copy_ns),
            hash_observation=stats(hash_ns),
            validate_all_groups=stats(validate_ns),
            canonical_transition=stats(canonical_ns),
            verify_transition=stats(verify_ns),
        ),
        cases=cases,
        limitations=[
            "CPU cached actual rows; excludes simulator reads, Fabric pose batch, robot getters, GPU/D2H, render, XR, live causal construction, media and fsync durability",
            "output under /tmp; OS page cache and filesystem differ from persistent data path; hdf flush is not fsync",
            "sequence repeats for compute benchmarks only; storage replays original420rows once each",
            "carb.log_warn stub; upstream base/manifest/storage source unchanged; not a production path",
        ],
    )
    (a.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
