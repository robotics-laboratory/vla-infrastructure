"""Join frozen CPU checks, live recordings and bounded background materialization."""

import argparse
import hashlib
import json
from pathlib import Path

from analyze_resource_assay import analyze, overlap, lines, tree


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize_qa(root, output):
    cases = []
    for name in ("qa-only-contention01", "qa-only-contention02"):
        folder = root / name
        telemetry = analyze(folder / "assay", folder / "recording")
        recorder = read(folder / "recording/result.json")
        background = read(folder / "background-qa/workers2.json")
        receipt = read(folder / "assay/receipt.json")
        window = telemetry["steady_window"]
        active = 0
        samples = lines(folder / "assay/samples.jsonl")
        for previous, current in zip(samples, samples[1:]):
            old, new = tree(previous, "background"), tree(current, "background")
            ticks = sum(
                max(
                    0,
                    p["utime_ticks"]
                    + p["stime_ticks"]
                    - old[key]["utime_ticks"]
                    - old[key]["stime_ticks"],
                )
                for key, p in new.items()
                if key in old and p["comm"] == "pt_data_worker"
            )
            if ticks:
                active += overlap(
                    previous["begin_monotonic_ns"],
                    current["begin_monotonic_ns"],
                    window["start_monotonic_ns"],
                    window["end_monotonic_ns"],
                )
        if (
            not recorder["passed"]
            or not background["passed"]
            or not receipt["passed"]
            or not telemetry["telemetry_complete"]
            or active < 20
            or not telemetry["coverage"]["entire_steady_window_bracketed"]
        ):
            raise ValueError("QA contention result incomplete or reader overlap below20s")
        packets = []
        count = recorder["arguments"]["frames"] + recorder["arguments"]["warmup"] + 1
        for role in range(3):
            path = folder / f"recording/mirror/media/role{role}/packets.jsonl"
            ledger = lines(path)
            if len(ledger) != count or [p["submitted_source_tag"] for p in ledger] != list(
                range(count)
            ):
                raise ValueError("QA contention packet/source coverage differs")
            packets.append(dict(role=role, packets=count, ledger_sha256=sha(path)))
        cases.append(
            dict(
                case=name,
                recording_passed=recorder["passed"],
                complete_action_and_camera_hz_with_encode_tail=recorder[
                    "complete_action_and_camera_hz_with_encode_tail"
                ],
                performance=recorder["performance"],
                resource_analysis=telemetry,
                background_qa=background,
                commands=receipt["commands"],
                observed_reader_cpu_overlap_s=active,
                camera_coverage=packets,
                source_pins={
                    str(folder / "recording/result.json"): sha(folder / "recording/result.json"),
                    str(folder / "background-qa/workers2.json"): sha(
                        folder / "background-qa/workers2.json"
                    ),
                },
            )
        )
    summary = dict(
        schema="resource30_qa_contention_results_v1",
        cases=cases,
        source_sha256=sha(Path(__file__)),
        all_passed=True,
        physical=False,
        quest_connected=False,
        dataset_admissible=False,
        gate_bindings=[],
    )
    with output.open("x") as handle:
        handle.write(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(dict(all_passed=True, cases=len(cases))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--matrix", type=Path)
    source.add_argument("--qa-root", type=Path)
    source.add_argument("--single-case", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.qa_root:
        summarize_qa(args.qa_root, args.output)
        return
    root = (args.matrix or args.single_case).parent
    case_rows = (
        read(args.matrix / "matrix.json")
        if args.matrix
        else [
            dict(
                case=args.single_case.name,
                returncode=0 if read(args.single_case / "assay/receipt.json")["passed"] else 1,
            )
        ]
    )
    summary = dict(
        schema="resource30_results_v1",
        preservation_base="38185eb57016cb86786ffbc9846f91af1d629178",
        checkpoint=read(root / "checkpoint/receipt.json"),
        checkpoint_remote=read(root / "checkpoint/remote-push.json"),
        cpu_qa={
            name: read(root / f"cpu-qa/{name}.json")
            for name in ("canonical", "workers0", "workers2", "workers4")
        },
        cases=[],
        physical=False,
        quest_connected=False,
        dataset_admissible=False,
        gate_bindings=[],
        source_sha256=sha(Path(__file__)),
    )
    for row in case_rows:
        directory = args.matrix / row["case"] if args.matrix else args.single_case
        result = read(directory / "recording/result.json")
        telemetry = analyze(directory / "assay", directory / "recording")
        source_count = result["arguments"]["frames"] + result["arguments"]["warmup"] + 1
        camera_coverage = []
        for role in range(3):
            path = directory / f"recording/mirror/media/role{role}/packets.jsonl"
            packets = [json.loads(line) for line in path.read_text().splitlines()]
            raw = directory / f"recording/mirror/media/role{role}/stream.h264"
            offset = 0
            for i, packet in enumerate(packets):
                if (
                    packet["packet_index"],
                    packet["encoder_packet_timestamp"],
                    packet["submitted_source_tag"],
                ) != (i, i, i):
                    raise ValueError("Packet ordinal/source coverage differs")
                if packet["offset"] != offset or packet["length"] <= 0:
                    raise ValueError("Packet byte coverage differs")
                offset += packet["length"]
            if len(packets) != source_count or offset != raw.stat().st_size:
                raise ValueError("Incomplete encoded sources")
            camera_coverage.append(
                dict(
                    role=role,
                    packets=len(packets),
                    bitstream_bytes=offset,
                    ledger_sha256=sha(path),
                    bitstream_sha256=sha(raw),
                )
            )
        config = read(directory / "recording-config.json")
        case = dict(
            case=row["case"],
            recording_passed=result["passed"],
            commands_passed=row["returncode"] == 0,
            recording_config=config,
            recording_result_sha256=sha(directory / "recording/result.json"),
            transitions=result["transitions"],
            camera_coverage=camera_coverage,
            complete_action_and_camera_hz_with_encode_tail=result[
                "complete_action_and_camera_hz_with_encode_tail"
            ],
            performance=result["performance"],
            resource_analysis=telemetry,
        )
        manifest = directory / "dataset/live-materialization.json"
        if manifest.is_file():
            data = read(manifest)
            if (
                data["qa"]["all_frames_read"] != data["frames"]
                or not data["qa"]["rgb_fingerprints_verified"]
            ):
                raise ValueError("Background full-row/pixel QA incomplete")
            phases = data["phase_monotonic_ns"]
            window = telemetry["steady_window"]
            start, end = window["start_monotonic_ns"], window["end_monotonic_ns"]
            boundaries = [
                ("decode_add_frame", "decode_add_frame_begin", "save_episode_begin"),
                ("save_episode", "save_episode_begin", "qa_begin"),
                ("qa", "qa_begin", "qa_end"),
            ]
            case["background_materialization"] = dict(
                manifest_sha256=sha(manifest),
                frames=data["frames"],
                qa=data["qa"],
                qa_workers=data["qa_workers"],
                timings_s=data["timings_s"],
                phase_monotonic_ns=phases,
                phase_overlap_s={
                    name: overlap(phases[a], phases[b], start, end) for name, a, b in boundaries
                },
                dataset_duration_s=data["frames"] / data["fps"],
                export_realtime_factor=data["frames"]
                / data["fps"]
                / data["timings_s"]["before_publish_total_s"],
                warning="One completed previous episode; this does not prove continuous postprocessing keeps up.",
            )
        summary["cases"].append(case)
    summary["recording_sources_unchanged"] = (
        read(args.matrix / "source-unchanged.json")
        if args.matrix
        else dict(passed=read(args.single_case / "assay/receipt.json")["source_bytes_unchanged"])
    )
    summary["all_passed"] = all(
        c["recording_passed"]
        and c["commands_passed"]
        and c["resource_analysis"]["harness_passed"]
        and c["resource_analysis"]["telemetry_complete"]
        and c["resource_analysis"]["coverage"]["entire_steady_window_bracketed"]
        and (
            not c["resource_analysis"]["background"]["requested"]
            or (
                c["resource_analysis"]["background"]["observed_cpu_interval_overlap_ge20s"]
                and "background_materialization" in c
            )
        )
        for c in summary["cases"]
    )
    with args.output.open("x") as handle:
        handle.write(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(dict(all_passed=summary["all_passed"], cases=len(summary["cases"]))))


if __name__ == "__main__":
    main()
