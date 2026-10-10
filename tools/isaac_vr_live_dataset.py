"""Experimental single-episode bridge: snapshot HDF + live NVENC -> LeRobot v3.

Isaac owns verified HDF extraction; core owns public LeRobot recording/QA.
Preencoded video import is a narrowly pinned, reversible instance hook.
No offline replay identities or human/task qualification are fabricated.
"""

import argparse
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

import numpy as np

try:
    from . import isaac_vr_lerobot_materialize as common
    from .isaac_vr_recording import verify_terminal_successor_snapshot
except ImportError:
    import isaac_vr_lerobot_materialize as common
    from isaac_vr_recording import verify_terminal_successor_snapshot

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "docs/experiments/20261009_live_camera_recording_30hz/deep_research"
SCHEMA = "experimental_single_gpu_live_dataset_v1"


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def check(condition, message):
    if not condition:
        raise ValueError(message)


def hash_files(paths):
    return {str(Path(p).resolve()): common._sha256_stable(Path(p)) for p in paths}


def verify_hashes(hashes):
    check(hash_files(hashes) == hashes, "Bound source files changed")


def load_pose_helper():
    spec = importlib.util.spec_from_file_location(
        "live_dataset_pose", HELPERS / "ovrtx_live_probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.pose_matrices


def validate_packets(packets, sources, bitstream):
    """Reject missing/reordered packets, reused IDs and unindexed bitstream bytes."""
    check(len(packets) == sources, "Missing terminal packet or extra media")
    offset = 0
    for i, packet in enumerate(packets):
        check(
            all(
                packet[k] == i
                for k in ("packet_index", "encoder_packet_timestamp", "submitted_source_tag")
            ),
            "Packet/source ordinals differ",
        )
        check(packet["offset"] == offset and packet["length"] > 0, "Packet byte coverage differs")
        offset += packet["length"]
    check(offset == bitstream.stat().st_size, "Unindexed or truncated bitstream bytes")


def extract_standalone_projection(
    *,
    recording: Path,
    output: Path,
    portable_roots: dict[str, Path],
    episode: str | None = None,
) -> dict[str, Any]:
    try:
        from .isaac_vr_replay import verify_experimental_standalone_recording_artifact
    except ImportError:
        from isaac_vr_replay import verify_experimental_standalone_recording_artifact

    recording = recording.expanduser().resolve()
    artifact = verify_experimental_standalone_recording_artifact(
        recording, portable_roots=portable_roots
    )
    selected, rows = common._extract_hdf_rows(recording, episode)
    arrays = common._validate_native_rows(rows)
    if len(rows) != artifact.committed_frames:
        raise common.MaterializationError(
            "native D0 count disagrees with finalized recording manifest"
        )
    try:
        verify_terminal_successor_snapshot(
            artifact.terminal_successor_path,
            expected_artifact_sha256=artifact.terminal_successor_sha256,
            committed_transition=rows[-1],
        )
    except (OSError, TypeError, ValueError) as exc:
        raise common.MaterializationError(f"terminal successor verification failed: {exc}") from exc
    if common._sha256_stable(recording) != artifact.hdf5_sha256:
        raise common.MaterializationError("native recording changed during extraction")
    session = artifact.manifest.get("session_metadata")
    if not isinstance(session, dict):
        raise common.MaterializationError("native recording has no session metadata")
    row_episode_id = common._decode_text(rows[0]["episode_id"])
    if session.get("episode_id") != row_episode_id:
        raise common.MaterializationError(
            "native row episode identity disagrees with recording manifest"
        )
    source = {
        "experimental_pose_backend": artifact.manifest["pose_backend_effective"],
        "dataset_admissible": False,
        "recording": str(recording),
        "recording_sha256": artifact.hdf5_sha256,
        "episode": selected,
        "episode_id": row_episode_id,
        "run_id": common._decode_text(rows[0]["run_id"]),
        "session_id": common._decode_text(rows[0]["session_id"]),
        "source_profile": session.get("source_profile"),
        "task": session.get("task"),
        "execution_profile": session.get("execution_profile"),
        "outcome": artifact.outcome,
        "stage_snapshot_sha256": artifact.snapshot_sha256,
        "asset_closure_sha256": artifact.asset_closure_sha256,
        "visual_provenance_sha256": artifact.visual_provenance_sha256,
        "terminal_successor_sha256": artifact.terminal_successor_sha256,
        "visual_identity": {
            "camera_roles": {
                str(camera["role"]): {
                    "prim_path": camera["prim_path"],
                    "camera_configuration_sha256": camera["camera_configuration_sha256"],
                    "resolution": camera["resolution"],
                }
                for camera in artifact.visual_provenance["camera_roles"]
            },
            "renderer_configuration_sha256": artifact.visual_provenance["renderer"][
                "renderer_configuration_sha256"
            ],
            "materialization_revision": artifact.visual_provenance["materialization"][
                "materialization_revision"
            ],
        },
    }
    return common._write_projection_bundle(output, arrays, source)


def prepare(input_path, output, portable_roots):
    run = input_path.resolve()
    result, seed = read(run / "result.json"), read(run / "mirror/seed.json")
    check(result["passed"] and result["arguments"]["media"] == "gpu", "Unfinished live recording")
    check(result["arguments"]["pace_hz"] == 30, "Require the tested 30Hz wall pacing mode")
    check(
        not seed["witness"] and not seed.get("mesh_freshness"),
        "Diagnostic markers are not training RGB",
    )
    check(not seed["excluded_dynamic_bodies"], "Missing dynamic bodies in live mirror")
    temporary = common._atomic_directory(output)
    try:
        manifest = extract_standalone_projection(
            recording=run / "episode/session.hdf5",
            output=temporary / "projection",
            portable_roots=portable_roots,
        )
        _, arrays = common.verify_projection_bundle(temporary / "projection")
        n = len(arrays["frame_index"])
        rows = lines(run / "mirror/worker-rows.jsonl")
        check(
            [r["source_id"] for r in rows] == list(range(n + 1)),
            "Source sequence/terminal count differs",
        )
        source_paths = [
            run / p
            for p in [
                "result.json",
                "episode/manifest.json",
                "episode/recording_state.json",
                "episode/terminal_successor.npz",
                "mirror/seed.json",
                "mirror/source-manifest.json",
                "mirror/worker.json",
                "mirror/worker-rows.jsonl",
                "mirror/mirror.usda",
            ]
        ]
        source_paths += [run / "episode/session.hdf5"]
        bound = hash_files(source_paths)
        join = subprocess.run(
            [
                sys.executable,
                str(HELPERS / "verify_live_source.py"),
                "--input",
                str(run),
                "--output",
                str(temporary / "source-join.json"),
            ],
            capture_output=True,
            text=True,
        )
        (temporary / "source-join.log").write_text(join.stdout + join.stderr)
        check(join.returncode == 0, "Native state/live transform join failed")
        for i in range(n):
            check(
                rows[i]["snapshot_id"] == str(arrays["scene_state_snapshot_id"][i])
                and rows[i]["snapshot_sha256"] == str(arrays["scene_state_snapshot_sha256"][i]),
                "Native observation identity differs from rendered source",
            )
        terminal = verify_terminal_successor_snapshot(
            run / "episode/terminal_successor.npz",
            expected_artifact_sha256=manifest["source"]["terminal_successor_sha256"],
        )
        check(
            (
                rows[-1]["snapshot_id"],
                rows[-1]["snapshot_sha256"],
                rows[-1]["source_id"],
                rows[-1]["physics_step"],
            )
            == (
                terminal.token.scene_state_snapshot_id,
                terminal.token.scene_state_snapshot_sha256,
                terminal.token.capture_sequence,
                terminal.token.physics_step,
            ),
            "Terminal rendered identity differs",
        )
        pose = load_pose_helper()
        entries = [
            e
            for e in read(run / "mirror/source-manifest.json")["recordables"]
            if e["type"] in ("articulation", "rigid_body", "camera")
        ]
        matrices = []
        for entry in entries:
            frame, plural = terminal.frames[entry["group"]], entry["type"] == "articulation"
            matrix = pose(
                frame["positions" if plural else "position"],
                frame["orientations" if plural else "orientation"],
            )
            matrices.append(matrix if plural else matrix[None])
        matrices = np.concatenate(matrices)
        descendants = seed["render_descendants"]
        if descendants:
            local = np.asarray([d["mesh_to_body"] for d in descendants], dtype="<f8")
            matrices = np.concatenate(
                [matrices, local @ matrices[[d["parent_index"] for d in descendants]]]
            )
        check(
            hashlib.sha256(matrices.astype("<f8").tobytes()).hexdigest()
            == rows[-1]["transform_sha256"],
            "Terminal rendered matrices differ from retained successor",
        )
        worker = read(run / "mirror/worker.json")
        check(
            worker["encoder"]["passed"] and not worker["cleanup_errors"],
            "Encoder drain/cleanup failed",
        )
        media = {}
        for role_index, role in enumerate(common.CAMERA_ROLES):
            directory = run / f"mirror/media/role{role_index}"
            packets = lines(directory / "packets.jsonl")
            validate_packets(packets, n + 1, directory / "stream.h264")
            encoder = read(directory / "encoder.json")
            check(
                encoder["passed"]
                and encoder["packets"] == n + 1
                and not encoder["owners_retained"],
                "Encoder did not retire all frames",
            )
            media[role] = str(directory / "stream.h264")
            bound.update(
                hash_files(
                    [
                        directory / "stream.h264",
                        directory / "packets.jsonl",
                        directory / "encoder.json",
                    ]
                )
            )
        verify_hashes(bound)
        ledger = [
            dict(
                frame_index=i,
                obs_id=str(arrays["obs_id"][i]),
                snapshot_id=rows[i]["snapshot_id"],
                snapshot_sha256=rows[i]["snapshot_sha256"],
                transition_id=str(arrays["transition_id"][i]),
                physics_step=rows[i]["physics_step"],
                state_received_monotonic_ns=rows[i]["state_received_monotonic_ns"],
                observation_sample_monotonic_ns=rows[i]["observation_sample_monotonic_ns"],
                source_wall_ns=rows[i]["source_wall_ns"],
            )
            for i in range(n)
        ]
        (temporary / "source-ledger.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in ledger)
        )
        evidence = dict(
            schema=SCHEMA,
            frames=n,
            fps=30,
            media=media,
            bound_sources=bound,
            source_ledger_sha256=common._sha256_stable(temporary / "source-ledger.jsonl"),
            terminal_source=rows[-1],
            native_row_schema_profile=manifest["source"]["source_profile"],
            experimental_pose_backend=manifest["source"]["experimental_pose_backend"],
            pixel_profile="experimental_ovrtx_live_nvenc_v1",
            input_source=result["input_source"],
            quest_connected=False,
            dataset_admissible=False,
            physical=False,
            task_success_claimed=False,
            optical_pixel_alignment_proven=False,
            terminal_identity_and_matrix_join=True,
            stage_geometry_scope="Explicit leaf-mesh mirror; physics and pixels are not qualified master parity",
        )
        evidence["manifest_sha256"] = common._canonical_sha256(evidence)
        common._write_json(temporary / "live-media.json", evidence)
        common._publish_directory(temporary, output)
        return dict(passed=True, frames=n, rendered_sources=n + 1, output=str(output))
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def remux(raw, output, frames):
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-r",
        "30",
        "-f",
        "h264",
        "-i",
        str(raw),
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-frames:v",
        str(frames),
        "-video_track_timescale",
        "15360",
        str(output),
    ]
    proc = subprocess.run(command, capture_output=True, text=True)
    check(proc.returncode == 0, f"Stream-copy remux failed: {proc.stderr}")
    return dict(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def decoded_frames(path):
    import av

    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            yield frame


def materialize(prepared, output, repo_id, qa_workers=None):
    import torch
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    try:
        from .isaac_vr_live_video_import import existing_videos
    except ImportError:
        from isaac_vr_live_video_import import existing_videos
    started = time.monotonic()
    timings = {}
    phases = {"start": time.monotonic_ns()}
    torch.set_num_threads(1)
    manifest, arrays = common.verify_projection_bundle(prepared / "projection")
    evidence = read(prepared / "live-media.json")
    media_payload = dict(evidence)
    media_declared = media_payload.pop("manifest_sha256")
    check(common._canonical_sha256(media_payload) == media_declared, "Live media manifest changed")
    check(
        all(path in evidence["bound_sources"] for path in evidence["media"].values()),
        "Unbound encoded source",
    )
    check(
        evidence["schema"] == SCHEMA and evidence["fps"] == common.FPS,
        "Unsupported live media binding",
    )
    verify_hashes(evidence["bound_sources"])
    check(
        common._sha256_stable(prepared / "source-ledger.jsonl") == evidence["source_ledger_sha256"],
        "Source ledger changed",
    )
    n = common._validate_projection_arrays(arrays)
    check(
        n == evidence["frames"] and set(evidence["media"]) == set(common.CAMERA_ROLES),
        "Media/row coverage differs",
    )
    task = common.TASK_LABELS[manifest["source"]["task"]]
    temporary = common._atomic_directory(output)
    try:
        remux_dir = temporary / "remux"
        remux_dir.mkdir()
        mp4s, commands = {}, {}
        phase = time.monotonic()
        for role, raw in evidence["media"].items():
            path = remux_dir / f"{role}.mp4"
            commands[role] = remux(Path(raw), path, n)
            mp4s[f"observation.images.{role}"] = path
        timings["remux_s"] = time.monotonic() - phase
        dataset_root = temporary / "dataset"
        dataset = LeRobotDataset.create(
            repo_id,
            fps=common.FPS,
            features=common.canonical_lerobot_features(),
            root=dataset_root,
            use_videos=True,
            video_backend="pyav",
        )
        generators = {key: decoded_frames(path) for key, path in mp4s.items()}
        pixel_hashes = {key: [] for key in mp4s}
        try:
            phases["decode_add_frame_begin"] = time.monotonic_ns()
            phase = time.monotonic()
            for i in range(n):
                frame = dict(
                    task=task,
                    **{
                        "observation.state": arrays["observation_state"][i].copy(),
                        "action": arrays["action"][i].copy(),
                    },
                )
                for key, generator in generators.items():
                    image = next(generator)
                    check(
                        Fraction(image.pts) * image.time_base == Fraction(i, 30),
                        "Nonexact i/30 MP4 PTS",
                    )
                    rgb = image.to_ndarray(format="rgb24")
                    check(rgb.shape == common.IMAGE_SHAPE, "Video shape changed")
                    pixel_hashes[key].append(hashlib.sha256(rgb.tobytes()).hexdigest())
                    frame[key] = rgb
                dataset.add_frame(frame)
            check(
                all(next(g, None) is None for g in generators.values()),
                "Terminal leaked into BC video",
            )
            timings["decode_add_frame_s"] = time.monotonic() - phase
            phases["save_episode_begin"] = time.monotonic_ns()
            phase = time.monotonic()
            with existing_videos(dataset, mp4s) as imported:
                dataset.save_episode(parallel_encoding=False)
            dataset.finalize()
            timings["save_episode_s"] = time.monotonic() - phase
        finally:
            for generator in generators.values():
                generator.close()
            dataset.finalize()
        for key in mp4s:
            final = dataset_root / dataset.meta.get_video_file_path(0, key)
            check(
                common._sha256_stable(final) == imported["source_sha256"][key],
                "Upstream changed imported video bytes",
            )
        phases["qa_begin"] = time.monotonic_ns()
        phase = time.monotonic()
        if qa_workers is None:
            qa = common._qa_lerobot_dataset(dataset_root, repo_id=repo_id, arrays=arrays, task=task)
        else:
            try:
                from .isaac_vr_live_dataset_qa import qa_live_dataset
            except ImportError:
                from isaac_vr_live_dataset_qa import qa_live_dataset
            qa = qa_live_dataset(
                dataset_root,
                repo_id=repo_id,
                arrays=arrays,
                task=task,
                decoded_rgb_sha256=pixel_hashes,
                workers=qa_workers,
            )
        timings["qa_s"] = time.monotonic() - phase
        phases["qa_end"] = time.monotonic_ns()
        verify_hashes(evidence["bound_sources"])
        # Own staging images were read by upstream statistics; video rows reference MP4 only.
        shutil.rmtree(dataset_root / "images", ignore_errors=True)
        shutil.copyfile(prepared / "source-ledger.jsonl", dataset_root / "live-source-ledger.jsonl")
        receipt = dict(
            schema=SCHEMA,
            frames=n,
            fps=30,
            repo_id=repo_id,
            dataset_admissible=False,
            source=evidence,
            prepared_sha256=hash_files(
                [prepared / "live-media.json", prepared / "projection/manifest.json"]
            ),
            remux=commands,
            import_receipt=imported,
            decoded_rgb_sha256=pixel_hashes,
            qa=qa,
            qa_workers=qa_workers,
            timings_s={**timings, "before_publish_total_s": time.monotonic() - started},
            phase_monotonic_ns=phases,
            terminal_excluded_from_bc_rows=True,
            source_terminal_retained=True,
            source_png_staging_removed=True,
            files=common._dataset_file_digests(dataset_root),
        )
        receipt["manifest_sha256"] = common._canonical_sha256(receipt)
        common._write_json(dataset_root / "live-materialization.json", receipt)
        common._publish_directory(dataset_root, output)
        return dict(passed=True, frames=n, output=str(output), qa=qa, reencoded=False)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def verify_manifest(output):
    receipt = read(output / "live-materialization.json")
    payload = dict(receipt)
    declared = payload.pop("manifest_sha256")
    check(
        receipt["schema"] == SCHEMA and common._canonical_sha256(payload) == declared,
        "Live dataset manifest self-hash differs",
    )
    actual = [
        f for f in common._dataset_file_digests(output) if f["path"] != "live-materialization.json"
    ]
    check(actual == receipt["files"], "Dataset files/labels/video changed")
    verify_hashes(receipt["source"]["bound_sources"])
    verify_hashes(receipt["prepared_sha256"])
    return dict(passed=True, frames=receipt["frames"], dataset_admissible=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("prepare", "materialize", "orchestrate", "verify"))
    p.add_argument("--input", type=Path)
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--repo-id")
    p.add_argument(
        "--qa-workers",
        type=int,
        choices=(0, 2, 4),
        default=None,
        help="Opt in to one-pass uint8 QA; default retains canonical QA",
    )
    p.add_argument("--extract-python", type=Path)
    p.add_argument("--portable-root", action="append", default=[])
    a = p.parse_args()
    if a.mode == "verify":
        check(a.output is not None, "Specify dataset output")
        print(json.dumps(verify_manifest(a.output)))
        return
    if a.mode == "orchestrate":
        check(a.extract_python is not None, "Specify pinned Isaac extraction interpreter")
        command = [
            str(a.extract_python),
            str(Path(__file__).resolve()),
            "prepare",
            "--input",
            str(a.input),
            "--prepared",
            str(a.prepared),
        ]
        for root in a.portable_root:
            command.extend(["--portable-root", root])
        subprocess.run(command, check=True)
    elif a.mode == "prepare":
        roots = dict(common._portable_root(root) for root in a.portable_root)
        print(json.dumps(prepare(a.input, a.prepared, roots)))
        return
    check(
        a.output is not None and a.repo_id and "/" in a.repo_id,
        "Specify new dataset output and namespace/name repo-id",
    )
    print(json.dumps(materialize(a.prepared, a.output, a.repo_id, qa_workers=a.qa_workers)))


if __name__ == "__main__":
    main()
