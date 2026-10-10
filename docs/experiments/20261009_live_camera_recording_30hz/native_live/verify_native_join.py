"""Offline native-camera source/HDF/packet ledger join; never optical proof.

Uses the project's canonical D0 and terminal-snapshot verifiers. HDF inspection
needs existing numpy/h5py; importing this helper or --help needs only stdlib.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time


ROLES = ("left_wrist", "right_wrist", "scene")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def exact_int(value, label):
    require(type(value) is int and value >= 0, f"{label}: expected nonnegative integer")
    return value


def verify_clock_samples(samples, physics_dt=1.0 / 120.0, tolerance=1e-8):
    """Join clock deltas while retaining the recorded native clock origin.

    Native SimTimeRecordable and IsaacLab completed-state tokens use separate
    counters. Their initial offset is evidence to report, not a zero-origin
    invariant. Every subsequent counter and time delta, including terminal,
    must still match the source's four-step control boundaries.
    """
    require(len(samples) >= 2, "Expected observation and terminal clock samples")
    anchor = samples[0]
    initial_source = exact_int(anchor["source_physics_step"], "source_physics_step")
    initial_recorded = exact_int(anchor["recorded_physics_step"], "recorded_physics_step")
    initial_time = anchor["sim_time"]
    require(math.isfinite(initial_time), "Nonfinite initial simulation time")
    maximum_error = 0.0
    for index, sample in enumerate(samples):
        source_step = exact_int(sample["source_physics_step"], "source_physics_step")
        recorded_step = exact_int(sample["recorded_physics_step"], "recorded_physics_step")
        require(source_step == initial_source + 4 * index, "Source clock boundary discontinuity")
        source_delta = source_step - initial_source
        require(
            recorded_step - initial_recorded == source_delta,
            "Recordable clock/source step offset changed",
        )
        sim_time = sample["sim_time"]
        require(math.isfinite(sim_time), "Nonfinite recorded simulation time")
        require(math.isfinite(sample["wall_time"]), "Nonfinite recorded wall time")
        error = abs((sim_time - initial_time) - source_delta * physics_dt)
        maximum_error = max(maximum_error, error)
        require(error <= tolerance, "HDF simulation time delta differs from completed source steps")
    return dict(
        policy="Initial HDF clock anchor retained; source and Recordable step/time deltas checked through terminal",
        sample_count=len(samples),
        source_anchor_physics_step=initial_source,
        recordable_anchor_physics_step=initial_recorded,
        recorded_minus_source_step_offset=initial_recorded - initial_source,
        anchor_sim_time=initial_time,
        sim_time_minus_source_step_dt_offset=initial_time - initial_source * physics_dt,
        physics_dt=physics_dt,
        max_delta_error_seconds=maximum_error,
        tolerance_seconds=tolerance,
        terminal=samples[-1],
    )


def verify_packets(directory, sources):
    """Verify ordinal/tag ledger and every byte extent, without decoding pixels."""
    directory = Path(directory)
    packets = read_rows(directory / "packets.jsonl")
    encoder = read_json(directory / "encoder.json")
    require(encoder["passed"] is True, f"{directory}: encoder failed")
    require(
        encoder["inputs"] == encoder["packets"] == len(sources) == len(packets),
        f"{directory}: input/packet/source counts differ",
    )
    require(
        not encoder["unacknowledged_ordinals"] and encoder["owners_retained"] == 0,
        f"{directory}: undrained encoder owners",
    )
    offset, results = 0, []
    with (directory / "stream.h264").open("rb") as stream:
        for ordinal, (packet, source) in enumerate(zip(packets, sources, strict=True)):
            require(
                exact_int(packet["packet_index"], "packet_index") == ordinal,
                f"{directory}: duplicate/skipped packet ordinal {ordinal}",
            )
            require(
                exact_int(packet["encoder_packet_timestamp"], "timestamp") == ordinal,
                f"{directory}: unexpected encoder-local timestamp",
            )
            require(
                exact_int(packet["submitted_source_tag"], "tag") == source["source_id"],
                f"{directory}: wrong packet/source tag at {ordinal}",
            )
            require(
                exact_int(packet["offset"], "offset") == offset,
                f"{directory}: discontinuous bitstream offset",
            )
            length = exact_int(packet["length"], "length")
            require(length > 0, f"{directory}: empty packet")
            payload = stream.read(length)
            require(len(payload) == length, f"{directory}: truncated bitstream")
            ready = exact_int(packet["packet_ready_monotonic_ns"], "packet_ready")
            written = exact_int(packet["packet_write_completed_monotonic_ns"], "packet_written")
            require(
                source["pixels_owned_ns"] <= ready <= written,
                f"{directory}: packet precedes owned input or write precedes ready",
            )
            results.append(
                dict(
                    source_id=source["source_id"],
                    packet_index=ordinal,
                    packet_sha256=hashlib.sha256(payload).hexdigest(),
                    offset=offset,
                    length=length,
                    ready_monotonic_ns=ready,
                    write_completed_monotonic_ns=written,
                    flush=packet["flush"],
                )
            )
            offset += length
        require(stream.read(1) == b"", f"{directory}: unledgered trailing stream bytes")
    return results


def verify_native_result_identifiers(frames):
    """Check renderer ledger continuity without equating its clock with physics."""
    previous = None
    callback_rows = 0
    for frame in frames:
        identities = frame.get("native_result_identifiers", {})
        if not identities:
            require(callback_rows == 0, "Missing callback identity inside renderer ledger")
            continue
        require(set(identities) == set(ROLES), "Incomplete callback role identity triplet")
        values = list(identities.values())
        require(all(value == values[0] for value in values), "Mixed native result identities")
        current = exact_int(values[0]["frameNumber"], "native frameNumber")
        if previous is not None:
            require(current == previous + 1, "Skipped or duplicated native result identifier")
        previous = current
        callback_rows += 1
    require(callback_rows in (0, len(frames)), "Partial callback identity coverage")
    return dict(rows=callback_rows, consecutive=True if callback_rows else None,
                physics_clock_equality_inferred=False, pixel_alignment_proven=False)


def verify(input_dir, repo, report):
    import h5py
    import numpy as np

    sys.path.insert(0, str(repo))
    from tools.isaac_vr_recording import (
        _captured_frame_sha256,
        canonical_committed_transition,
        verify_committed_transition_sample,
        verify_terminal_successor_snapshot,
    )

    def text(value):
        return bytes(value).rstrip(b"\0").decode("utf-8")

    def hexhash(value):
        return np.asarray(value, dtype=np.uint8).tobytes().hex()

    episode_dir = input_dir / "episode"
    media_dir = input_dir / "native-camera"
    manifest = read_json(episode_dir / "manifest.json")
    setup_path = media_dir / "setup.json"
    setup = read_json(setup_path) if setup_path.is_file() else None
    receipt = read_json(media_dir / "receipt.json")
    frames = read_rows(media_dir / "frames.jsonl")
    files = [
        episode_dir / name for name in ("manifest.json", "session.hdf5", "terminal_successor.npz")
    ]
    files += [media_dir / name for name in ("receipt.json", "frames.jsonl")]
    if setup is not None:
        files.append(setup_path)
    report["source_provenance"] = dict(
        setup_present=setup is not None,
        status="declared_setup_matches_hdf"
        if setup is not None
        else "unknown_missing_early_version_setup",
        camera_paths_checked=setup is not None,
        product_uniqueness_checked=setup is not None,
        live_stage_identity_independently_proven=False,
    )
    require(manifest["artifact_state"] == "finalized", "Episode is not finalized")
    require(
        digest(episode_dir / "session.hdf5") == manifest["hdf5_sha256"], "HDF file digest mismatch"
    )
    require(receipt["source"] == "main_kit_stage_rgb", "Wrong declared media source")
    require(
        receipt["snapshot_renderer_used"] is False and not receipt["cleanup_errors"],
        "Native media declares snapshot renderer or cleanup errors",
    )
    if setup is not None:
        require(setup["source"] == receipt["source"], "Setup/receipt media source differs")
        require(
            setup["camera_paths"] == manifest["camera_roles"],
            "Camera prim paths differ from HDF provenance",
        )
        require(
            len(setup["products"]) == len(set(setup["products"])) == 3,
            "Expected three distinct products",
        )
    require(len(frames) == receipt["captures"], "Native frame/receipt count differs")
    require(len(frames) >= 2, "Expected at least a transition and terminal frame")
    for index, frame in enumerate(frames):
        require(
            exact_int(frame["source_id"], "source_id") == index, "Duplicate/skipped source sequence"
        )
        require(frame["source"] == "main_kit_stage_rgb", "Mixed native media source")
        require(
            exact_int(frame["reset_epoch"], "reset_epoch") == frames[0]["reset_epoch"],
            "Reset-crossing media",
        )
        require(
            exact_int(frame["physics_step"], "physics_step")
            == frames[0]["physics_step"] + 4 * index,
            "Native media source physics steps are not consecutive four-step boundaries",
        )
        require(
            frame["capture_begin_ns"] <= frame["pixels_owned_ns"] <= frame["write_submitted_ns"],
            "Native capture/owned/submission event ordering differs",
        )

    report["native_result_ledger"] = verify_native_result_identifiers(frames)
    report["rows"] = []
    with h5py.File(episode_dir / "session.hdf5", "r") as hdf:
        require(len(hdf["episodes"]) == 1, "Expected one technical episode")
        episode = next(iter(hdf["episodes"].values()))
        group = episode["d0/committed_transition"]
        count = len(group["frame_index"])
        require(
            count > 0 and len(frames) == count + 1 == manifest["committed_frames"] + 1,
            "N committed rows must have exactly N+1 native triplets",
        )
        require(
            all(len(channel) == count for channel in group.values()), "D0 channel lengths differ"
        )
        recordable_groups = [
            entry["group"]
            for entry in manifest["recordables"]
            if entry["group"] != "d0/committed_transition"
        ]
        require(
            all(
                len(channel) == count
                for name in recordable_groups
                for channel in episode[name].values()
            ),
            "Source Recordable channel lengths differ from committed rows",
        )
        clocks = []
        previous = None
        for index in range(count):
            sample = canonical_committed_transition(
                {name: channel[index] for name, channel in group.items()}
            )
            verify_committed_transition_sample(sample)
            require(
                int(sample["frame_index"]) == index, "HDF frame index is not dense commit order"
            )
            if previous is not None:
                for successor, current in (
                    ("next_obs_id", "obs_id"),
                    ("successor_observation_state", "observation_state"),
                    ("successor_payload_sha256", "observation_payload_sha256"),
                    ("next_scene_state_snapshot_id", "scene_state_snapshot_id"),
                    ("next_scene_state_snapshot_sha256", "scene_state_snapshot_sha256"),
                ):
                    require(
                        np.array_equal(previous[successor], sample[current]),
                        "Promoted successor differs from next observation",
                    )
            captured = {
                name: {channel: dataset[index] for channel, dataset in episode[name].items()}
                for name in recordable_groups
            }
            expected_sha = _captured_frame_sha256(captured)
            require(
                expected_sha == hexhash(sample["scene_state_snapshot_sha256"]),
                f"HDF source Recordable digest mismatch at row {index}",
            )
            for frame, prefix in ((frames[index], "observation"), (frames[index + 1], "successor")):
                successor = prefix == "successor"
                require(
                    frame["source_id"] == int(sample[f"{prefix}_capture_sequence"]),
                    "Media/HDF source sequence mismatch",
                )
                require(
                    frame["physics_step"] == int(sample[f"{prefix}_physics_step"]),
                    "Media/HDF physics step mismatch",
                )
                require(
                    frame["state_generation"] == int(sample[
                        "successor_state_generation" if successor else "simulation_state_generation"]),
                    "Media/HDF state generation mismatch",
                )
                require(
                    frame["reset_epoch"]
                    == int(sample["successor_reset_epoch" if successor else "reset_epoch"]),
                    "Media/HDF reset epoch mismatch",
                )
                require(
                    frame["snapshot_id"]
                    == text(
                        sample[
                            "next_scene_state_snapshot_id"
                            if successor
                            else "scene_state_snapshot_id"
                        ]
                    ),
                    "Media/HDF scene snapshot ID mismatch",
                )
                require(
                    frame["snapshot_sha256"]
                    == hexhash(
                        sample[
                            "next_scene_state_snapshot_sha256"
                            if successor
                            else "scene_state_snapshot_sha256"
                        ]
                    ),
                    "Media/HDF scene snapshot digest mismatch",
                )
            clocks.append(
                dict(
                    source_physics_step=int(sample["observation_physics_step"]),
                    recorded_physics_step=int(
                        np.asarray(captured["meta/time"]["physics_step"]).item()
                    ),
                    sim_time=float(np.asarray(captured["meta/time"]["sim_time"]).item()),
                    wall_time=float(np.asarray(captured["meta/time"]["wall_time"]).item()),
                )
            )
            report["rows"].append(
                dict(
                    frame_index=index,
                    source_id=frames[index]["source_id"],
                    successor_source_id=frames[index + 1]["source_id"],
                    snapshot_sha256=expected_sha,
                    observation_payload_sha256=hexhash(sample["observation_payload_sha256"]),
                    action_payload_sha256=hexhash(sample["action_payload_sha256"]),
                    native_command_sha256=hexhash(sample["native_command_sha256"]),
                    transition_payload_sha256=hexhash(sample["transition_payload_sha256"]),
                    state=sample["observation_state"].tolist(),
                    action=sample["dataset_action"].tolist(),
                )
            )
            previous = sample
        terminal = verify_terminal_successor_snapshot(
            episode_dir / "terminal_successor.npz",
            expected_artifact_sha256=manifest["terminal_successor"]["sha256"],
            committed_transition=previous,
        )
        require(
            terminal.token.capture_sequence == frames[-1]["source_id"] == count,
            "Final media frame is not last committed terminal successor",
        )
        clocks.append(
            dict(
                source_physics_step=terminal.token.physics_step,
                recorded_physics_step=int(
                    np.asarray(terminal.frames["meta/time"]["physics_step"]).item()
                ),
                sim_time=float(np.asarray(terminal.frames["meta/time"]["sim_time"]).item()),
                wall_time=float(np.asarray(terminal.frames["meta/time"]["wall_time"]).item()),
            )
        )
        report["clock_join"] = verify_clock_samples(clocks)
        report["committed_transitions"], report["native_triplets"] = count, len(frames)
        report["terminal_snapshot_sha256"] = terminal.token.scene_state_snapshot_sha256
    report["packets"] = {}
    for ordinal, role in enumerate(ROLES):
        directory = media_dir / "media" / f"role{ordinal}"
        report["packets"][role] = verify_packets(directory, frames)
        files += [directory / name for name in ("packets.jsonl", "encoder.json", "stream.h264")]
    report["file_sha256"] = {str(path): digest(path) for path in files}
    report["canonical_verifier_source_sha256"] = {
        str(repo / "tools" / name): digest(repo / "tools" / name)
        for name in ("isaac_vr_recording.py", "isaac_vr_decision.py", "d0_causal.py")
    }
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="Closed native recording output root"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("/home/ebulochkin/vla_infrastructure"))
    args = parser.parse_args()
    result = dict(
        schema="native_kit_offline_source_hdf_packet_join_v1",
        passed=False,
        input=str(args.input),
        command=sys.argv,
        started_unix_ns=time.time_ns(),
        errors=[],
        dataset_admissible=False,
        optical_alignment_proven=False,
        decoded_output_checked=False,
        scope="Exact source IDs/snapshot and D0 payload digests, successor promotion, terminal snapshot and packet-byte ledger; no pixel source/preview visibility/physics qualification claim",
        helper_sha256=digest(Path(__file__)),
    )
    try:
        candidates = [
            args.input / "episode" / name
            for name in ("manifest.json", "session.hdf5", "terminal_successor.npz")
        ]
        candidates += [
            args.input / "native-camera" / name
            for name in ("setup.json", "receipt.json", "frames.jsonl")
        ]
        candidates += [
            args.input / "native-camera" / "media" / f"role{role}" / name
            for role in range(3)
            for name in ("packets.jsonl", "encoder.json", "stream.h264")
        ]
        result["input_file_sha256"] = {
            str(path): digest(path) for path in candidates if path.is_file()
        }
        verify(args.input.resolve(), args.repo.resolve(), result)
    except Exception as error:
        result["errors"].append(f"{type(error).__name__}: {error}")
    result["finished_unix_ns"] = time.time_ns()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key not in ("rows", "packets")},
            indent=2,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
