"""Export an already-recorded live triplet; never simulates or renders a source.

Retains commands, probes, decoded sample frames, motion metrics and SHA identities.
Video playback uses the recorded 30 Hz simulation clock, not wall capture speed.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    receipt = dict(
        schema="live_episode_preview_export_v1",
        passed=False,
        input=str(args.input),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        commands=[],
        playback_fps=30,
        source_re_rendered=False,
        preview_processing_excluded_from_recording_hz=True,
    )

    def run(command):
        started = time.monotonic()
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        receipt["commands"].append(
            dict(
                command=command,
                returncode=result.returncode,
                elapsed_s=time.monotonic() - started,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        )
        if result.returncode:
            raise RuntimeError(f"Export failed: {result.stderr[-1500:]}")
        return result.stdout

    def probe(path):
        return json.loads(
            run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-count_frames",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height,nb_read_frames,r_frame_rate,duration",
                    "-of",
                    "json",
                    str(path),
                ]
            )
        )["streams"][0]

    try:
        source = json.loads((args.input / "result.json").read_text())
        expected = source["transitions"]["committed_frames"] + 1
        streams = [args.input / f"mirror/media/role{role}/stream.h264" for role in range(3)]
        receipt["source_probes"] = [probe(stream) for stream in streams]
        if any(
            int(row["nb_read_frames"]) != expected or row["width"] != 960 or row["height"] != 600
            for row in receipt["source_probes"]
        ):
            raise RuntimeError("Recorded video count/geometry differs from source receipt")
        caption = (
            "drawtext=text='{text}':x=10:y=10:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.65"
        )
        graph = (
            "[0:v]" + caption.format(text="SCENE - live recorded RGB") + "[scene];"
            "[1:v]scale=480:300," + caption.format(text="LEFT WRIST") + "[left];"
            "[2:v]scale=480:300," + caption.format(text="RIGHT WRIST") + "[right];"
            "[left][right]hstack=inputs=2[wrists];[scene][wrists]vstack=inputs=2[out]"
        )
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        for stream in (streams[2], streams[0], streams[1]):
            command += ["-r", "30", "-i", str(stream)]
        command += [
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "22",
            "-threads",
            "4",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(args.output / "episode-three-views.mp4"),
        ]
        run(command)
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-r",
                "30",
                "-i",
                str(streams[2]),
                "-c:v",
                "copy",
                "-movflags",
                "+faststart",
                str(args.output / "episode-scene.mp4"),
            ]
        )
        receipt["preview_probe"] = probe(args.output / "episode-three-views.mp4")
        if int(receipt["preview_probe"]["nb_read_frames"]) != expected:
            raise RuntimeError("Preview dropped/duplicated a frame")
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(streams[2]),
                "-vf",
                "select=eq(n\\,0)+eq(n\\,390)+eq(n\\,690)",
                "-vsync",
                "0",
                "-frames:v",
                "3",
                str(args.output / "scene-sample-%02d.png"),
            ]
        )
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                "13",
                "-i",
                str(args.output / "episode-three-views.mp4"),
                "-frames:v",
                "1",
                str(args.output / "preview.png"),
            ]
        )
        rows = [
            json.loads(line)
            for line in (args.input / "motion-trace.jsonl").read_text().splitlines()
        ]
        home = rows[0]["actual_tcp_world_m"]

        def norm(vector):
            return math.sqrt(sum(x * x for x in vector))

        receipt["motion_metrics"] = dict(
            maximum_tcp_displacement_m=[
                max(
                    norm([p - h for p, h in zip(row["actual_tcp_world_m"][arm], home[arm])])
                    for row in rows
                )
                for arm in range(2)
            ],
            actual_aperture_range_m=[
                [
                    min(row["actual_aperture_m"][arm] for row in rows),
                    max(row["actual_aperture_m"][arm] for row in rows),
                ]
                for arm in range(2)
            ],
            maximum_cartesian_tracking_error_m=max(max(row["position_error_m"]) for row in rows),
            final_home_error_m=[
                norm([p - h for p, h in zip(rows[-1]["actual_tcp_world_m"][arm], home[arm])])
                for arm in range(2)
            ],
            object_grasp_claimed=False,
        )
        receipt["files"] = [
            dict(
                path=str(path),
                bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in sorted(args.output.iterdir())
        ]
        receipt["passed"] = True
    finally:
        (args.output / "export.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
