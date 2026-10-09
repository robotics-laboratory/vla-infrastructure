"""Recorded HDF rigid-world snapshot replay into isolated OVRTX; NOT live XR proof.
Preparation is CPU-only in a separate process (pxr must never share OVRTX process).
--prepare-only --episode DIR --output NEWDIR; then --prepared DIR --output NEWDIR.
Uses ovrtx_snapshot.py from research bundle and optical_witness.py beside script.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time
import numpy as np

DEFAULT_HELPER = Path(
    "/home/ebulochkin/vla_infrastructure/docs/experiments/20261009_live_camera_recording_30hz/deep_research/ovrtx_snapshot.py"
)
ROLES = ["left_wrist", "right_wrist", "scene"]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pose_matrices(pos, quat):
    norm = np.linalg.norm(quat, axis=-1)
    if (
        not np.isfinite(pos).all()
        or not np.isfinite(quat).all()
        or not np.allclose(norm, 1, atol=1e-4)
    ):
        raise ValueError("Invalid HDF world poses/quaternion norms")
    w, x, y, z = np.moveaxis(quat / norm[..., None], -1, 0)
    r = np.stack(
        [
            1 - 2 * (y * y + z * z),
            2 * (x * y - z * w),
            2 * (x * z + y * w),
            2 * (x * y + z * w),
            1 - 2 * (x * x + z * z),
            2 * (y * z - x * w),
            2 * (x * z - y * w),
            2 * (y * z + x * w),
            1 - 2 * (x * x + y * y),
        ],
        -1,
    ).reshape(pos.shape[:-1] + (3, 3))
    matrices = np.broadcast_to(np.eye(4), pos.shape[:-1] + (4, 4)).copy()
    matrices[..., :3, :3] = np.swapaxes(r, -1, -2)
    matrices[..., 3, :3] = pos
    return matrices


def prepare(args, witness):
    import h5py
    from pxr import Usd, UsdGeom, UsdPhysics

    root, out = Path(args.episode), Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((root / "manifest.json").read_text())
    stage_path, hdf_path = root / manifest["stage_snapshot"], root / manifest["hdf5"]
    for path, key in [(stage_path, "stage_snapshot_sha256"), (hdf_path, "hdf5_sha256")]:
        if sha(path) != manifest[key]:
            raise ValueError(f"Manifest hash mismatch: {path}")
    paths, arrays = [], []
    cameras = [manifest["camera_roles"][role] for role in ROLES]
    with h5py.File(hdf_path, "r") as hdf:
        if len(hdf["episodes"]) != 1:
            raise ValueError("Probe supports one HDF episode")
        episode = next(iter(hdf["episodes"].values()))
        times = episode["meta/time/sim_time"][:]
        wall = episode["meta/time/wall_time"][:]
        transitions = episode["d0/committed_transition"]
        sequences = transitions["observation_capture_sequence"][:]
        if not np.all(np.diff(sequences) == 1) or not np.all(np.diff(times) > 0):
            raise ValueError("Noncontiguous source observations")
        if len(np.unique(transitions["reset_epoch"][:])) != 1:
            raise ValueError("Multiple reset epochs require distinct mirror lifecycles")
        intrinsics = []
        for entry in manifest["recordables"]:
            if entry["type"] not in ["articulation", "rigid_body", "camera"]:
                continue
            group = episode[entry["group"]]
            plural = entry["type"] == "articulation"
            names = entry["link_paths"] if plural else [entry["prim_path"]]
            p, q = (
                group["positions" if plural else "position"],
                group["orientations" if plural else "orientation"],
            )
            if q.attrs.get("quaternion_order") != "wxyz" or p.attrs.get("space") != "world":
                raise ValueError("Unexpected recorded pose convention")
            a = pose_matrices(p[:], q[:])
            arrays.append(a if plural else a[:, None])
            paths.extend(names)
            if entry["type"] == "camera":
                for key in [
                    "focal_length",
                    "horizontal_aperture",
                    "vertical_aperture",
                    "clipping_range",
                ]:
                    if not np.all(group[key][:] == group[key][0]):
                        raise ValueError("Changing intrinsics unsupported")
        intrinsics = np.array(
            [
                [
                    episode["state/camera/" + r][k][0]
                    for k in ["focal_length", "horizontal_aperture", "vertical_aperture"]
                ]
                for r in ROLES
            ]
        )
        ids = [
            str(x.decode() if isinstance(x, bytes) else x)
            for x in transitions["scene_state_snapshot_id"][:]
        ]
        source_hashes = [bytes(x).hex() for x in transitions["scene_state_snapshot_sha256"][:]]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate snapshot paths")
    usd_stage = Usd.Stage.Open(str(stage_path.resolve()))
    for path in paths:
        prim = usd_stage.GetPrimAtPath(path)
        if not prim:
            raise ValueError(f"Source USD lacks {path}")
        world = np.array(
            UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        )
        if not np.allclose(np.linalg.norm(world[:3, :3], axis=1), 1, atol=1e-5):
            raise ValueError(f"Pose-only mirror loses authored nonunit scale: {path}")
    rigid = [str(p.GetPath()) for p in usd_stage.Traverse() if p.HasAPI(UsdPhysics.RigidBodyAPI)]
    exclusions = sorted(set(rigid) - set(paths))
    if exclusions != ["/World/RobosynDemo/ValidationProbe"]:
        raise ValueError(f"Unreviewed dynamic-body coverage gap: {exclusions}")
    specs = []
    for role, camera in enumerate(cameras):
        specs.append(f"""def RenderProduct "Camera{role}" (prepend apiSchemas = ["OmniRtxSettingsCommonAdvancedAPI_1"]) {{
 rel camera = <{camera}>
 uint[] deviceIds = [{args.device}]
 uniform int2 resolution = (960, 600)
 token omni:rtx:rendermode = "RealTimePathTracing"
 token[] omni:rtx:waitForEvents = ["AllLoadingFinished", "OnlyOnFirstRequest"]
 rel orderedVars = </Live30/LdrColor>
}}""")
    overlay = "#usda 1.0\n( subLayers = [@" + str(stage_path.resolve()) + "@]\n"
    overlay += f' metersPerUnit = {UsdGeom.GetStageMetersPerUnit(usd_stage)}\n upAxis = "{UsdGeom.GetStageUpAxis(usd_stage)}"\n)\n'
    overlay += 'over "World" {\n over "RobosynDemo" {\n over "ValidationProbe" (active = false) {}\n }\n}\n'
    overlay += (
        'def Scope "Live30" {\n'
        + "\n".join(specs)
        + '\ndef RenderVar "LdrColor" {\n uniform string sourceName = "LdrColor"\n}\n}\n'
    )
    overlay += witness.usd() if args.witness else ""
    (out / "mirror.usda").write_text(overlay)
    parsed = Usd.Stage.Open(str(out / "mirror.usda"))
    if not parsed or parsed.GetPrimAtPath(exclusions[0]).IsActive():
        raise ValueError("Overlay invalid or exclusion ineffective")
    np.savez(
        out / "snapshots.npz",
        matrices=np.concatenate(arrays, axis=1),
        times=times,
        wall=wall,
        sequences=sequences,
        intrinsics=intrinsics,
    )
    metadata = dict(
        dataset_admissible=False,
        source_hdf=str(hdf_path.resolve()),
        source_hdf_sha256=sha(hdf_path),
        source_stage_sha256=sha(stage_path),
        source_manifest_sha256=sha(root / "manifest.json"),
        paths=paths,
        cameras=cameras,
        roles=ROLES,
        rigid_bodies=rigid,
        excluded_dynamic_bodies=exclusions,
        snapshot_ids=ids,
        snapshot_hashes=source_hashes,
        episode_id=manifest["session_metadata"]["episode_id"],
        witness=args.witness,
        witness_helper_sha256=sha(args.witness_helper),
        snapshot_helper_sha256=sha(args.snapshot_helper),
        count=len(times),
        scene_generation=sha(out / "mirror.usda"),
    )
    metadata["snapshots_sha256"] = sha(out / "snapshots.npz")
    (out / "prepared.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in metadata.items() if k not in ["snapshot_ids", "snapshot_hashes"]},
            indent=2,
        )
    )


def render(args, witness):
    prepared, out = Path(args.prepared), Path(args.output)
    meta = json.loads((prepared / "prepared.json").read_text())
    for path, expected in [
        (prepared / "snapshots.npz", meta["snapshots_sha256"]),
        (prepared / "mirror.usda", meta["scene_generation"]),
        (args.witness_helper, meta["witness_helper_sha256"]),
        (args.snapshot_helper, meta["snapshot_helper_sha256"]),
    ]:
        if sha(path) != expected:
            raise ValueError(f"Prepared input changed: {path}")
    with np.load(prepared / "snapshots.npz", allow_pickle=False) as archive:
        data = {name: archive[name] for name in archive.files}
    total = min(args.frames or meta["count"], meta["count"])
    if total <= args.warmup or total > 4096:
        raise ValueError("Need warmup < total <=4096")
    out.mkdir(parents=True, exist_ok=False)
    helper = load(args.snapshot_helper, "live30_snapshot")
    import ovrtx
    import ovstage

    stage = renderer = mirror = consumer = None
    rows, timings, mismatch = [], [], []
    paths = meta["paths"] + (
        [p for r in range(3) for p in witness.paths(r)] if meta["witness"] else []
    )
    camera_indices = [meta["paths"].index(c) for c in meta["cameras"]]
    receipt = dict(
        dataset_admissible=False,
        live_xr_qualified=False,
        mode="HDF replay standalone dynamic mirror",
        input=str(prepared),
        source_hdf_sha256=meta["source_hdf_sha256"],
        witness=meta["witness"],
        excluded_dynamic_bodies=meta["excluded_dynamic_bodies"],
        paths=paths,
        source_rows=total,
    )
    try:
        renderer = ovrtx.Renderer()
        stage = ovstage.Stage("live30.dynamic.mirror")
        renderer.attach_ovstage(stage)
        ovstage.population.open_usd(stage, str(prepared / "mirror.usda"), ordinal=1)
        stage.advance_write_floor(1, ovstage.Scope.ALL).wait()
        if args.gpu_encode:
            from ovrtx_gpu_consumer import GPUConsumer

            consumer = GPUConsumer(out, gpu=args.device)
        mirror = helper.SnapshotRenderer(
            stage,
            renderer,
            paths=paths,
            cameras=meta["cameras"],
            products=[f"/Live30/Camera{r}" for r in range(3)],
            episode_id=meta["episode_id"],
            scene_generation=meta["scene_generation"],
            initial_delta_s=float(np.diff(data["times"])[0]),
            consumer=consumer,
        )
        for i in range(total):
            start = time.perf_counter_ns()
            matrices = data["matrices"][i]
            if meta["witness"]:
                boards = [
                    witness.matrices(matrices[c], data["intrinsics"][r], i, r)
                    for r, c in enumerate(camera_indices)
                ]
                matrices = np.concatenate([matrices, *boards])
            snapshot = helper.Snapshot.freeze(
                source_id=int(data["sequences"][i]),
                episode_id=meta["episode_id"],
                scene_generation=meta["scene_generation"],
                sim_time_s=float(data["times"][i]),
                source_wall_ns=int(data["wall"][i] * 1e9),
                matrices=matrices,
            )
            images, row = mirror.capture(snapshot)
            row.update(
                hdf_row=i,
                recorded_snapshot_id=meta["snapshot_ids"][i],
                recorded_snapshot_sha256=meta["snapshot_hashes"][i],
            )
            if meta["witness"] and not consumer:
                decoded = [witness.decode(image) for image in images]
                row["witness"] = decoded
                row["optical_phase_verified"] = all(
                    d["confident"] and d["row"] == i and d["role"] == r
                    for r, d in enumerate(decoded)
                )
                if not row["optical_phase_verified"]:
                    mismatch.append(i)
            elapsed = (time.perf_counter_ns() - start) / 1e6
            row["worker_total_ms"] = elapsed
            rows.append(row)
            if i >= args.warmup:
                timings.append(elapsed)
            if images and (
                i in [0, args.warmup, total - 1]
                or (meta["witness"] and not row["optical_phase_verified"] and len(mismatch) <= 3)
            ):
                for role, image in enumerate(images):
                    np.save(out / f"row{i:04d}-role{role}.npy", image)
        receipt.update(
            mean_ms=statistics.mean(timings),
            wall_hz=1000 / statistics.mean(timings),
            p95_ms=float(np.percentile(timings, 95)),
            measured_frames=len(timings),
            witness_mismatch_rows=mismatch,
            optical_phase_all_pass=meta["witness"] and not mismatch and not consumer,
            output_path="owned GPU NVENC; offline optical verification required"
            if consumer
            else "CPU pixels with inline optical verification",
            notes="Worker timing includes snapshot freezing, transforms, render and output consumption; excludes startup/artifact saves/drain; no live producer/XR.",
        )
        if consumer:
            receipt["gpu_consumer"] = consumer.finish()
            receipt["including_drain_hz"] = len(timings) / (
                sum(timings) / 1000 + receipt["gpu_consumer"]["drain_ms"] / 1000
            )
    except BaseException as error:
        receipt["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        (out / "rows.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        if consumer and not consumer.closed:
            consumer.finish()
        if mirror is not None:
            mirror.close()
        if renderer is not None:
            renderer.detach_ovstage()
        if stage is not None:
            stage.destroy()
        if renderer is not None:
            renderer.destroy()
    print(json.dumps(receipt, indent=2))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prepare-only", action="store_true")
    p.add_argument("--episode")
    p.add_argument("--prepared")
    p.add_argument("--output", required=True)
    p.add_argument("--witness", action="store_true")
    p.add_argument("--gpu-encode", action="store_true")
    p.add_argument("--device", type=int, default=0)
    p.add_argument("--warmup", type=int, default=30)
    p.add_argument("--frames", type=int, default=0)
    p.add_argument("--snapshot-helper", type=Path, default=DEFAULT_HELPER)
    p.add_argument(
        "--witness-helper", type=Path, default=Path(__file__).with_name("optical_witness.py")
    )
    args = p.parse_args()
    witness = load(args.witness_helper, "live30_witness")
    if args.prepare_only:
        if not args.episode:
            p.error("--episode required for preparation")
        prepare(args, witness)
    else:
        if not args.prepared:
            p.error("--prepared required for rendering")
        render(args, witness)


if __name__ == "__main__":
    main()
