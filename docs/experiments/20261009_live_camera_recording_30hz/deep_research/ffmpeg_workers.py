"""CPU RGBA triplets -> three existing FFmpeg NVENC processes; probe only.

No subprocess starts on import. Instantiate in an explicitly scheduled GPU probe.
submit() owns CPU copies. Sidecar describes INPUT admission, not decoded output.
"""

from pathlib import Path
import json
import queue
import subprocess
import threading
import time


class FFmpegTripleEncoder:
    ROLES = ("left_wrist", "right_wrist", "scene")

    def __init__(
        self,
        directory,
        width=960,
        height=600,
        fps=50,
        gpu=0,
        gop=50,
        capacity=8,
        bitrate="16M",
        packed_rgb=True,
    ):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.width, self.height = width, height
        self.pending = queue.Queue(maxsize=capacity)
        self.error = None
        self.submitted = self.written = 0
        self.closed = False
        self.processes, self.logs = {}, []
        self.sidecar = (self.directory / "input.jsonl").open("w")
        self.config = dict(
            width=width,
            height=height,
            fps=fps,
            gpu=gpu,
            gop=gop,
            capacity=capacity,
            bitrate=bitrate,
            packed_rgb=packed_rgb,
        )
        try:
            for role in self.ROLES:
                logfile = (self.directory / f"{role}.stderr").open("wb")
                self.logs.append(logfile)
                # rgb0 consumes the same four byte RGBA layout and ignores alpha.
                # This avoids CPU RGBA -> planar YUV conversion before NVENC.
                source_format = "rgb0" if packed_rgb else "rgba"
                target_format = "rgb0" if packed_rgb else "yuv420p"
                command = [
                    "/usr/bin/ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "warning",
                    "-nostdin",
                    "-n",
                    "-f",
                    "rawvideo",
                    "-pixel_format",
                    source_format,
                    "-video_size",
                    f"{width}x{height}",
                    "-framerate",
                    str(fps),
                    "-i",
                    "pipe:0",
                    "-an",
                    "-c:v",
                    "h264_nvenc",
                    "-gpu",
                    str(gpu),
                    "-preset",
                    "p1",
                    "-tune",
                    "ull",
                    "-bf",
                    "0",
                    "-g",
                    str(gop),
                    "-rc-lookahead",
                    "0",
                    "-multipass",
                    "disabled",
                    "-zerolatency",
                    "1",
                    "-delay",
                    "0",
                    "-rc",
                    "vbr",
                    "-b:v",
                    bitrate,
                    "-pix_fmt",
                    target_format,
                    "-f",
                    "h264",
                    str(self.directory / f"{role}.h264"),
                ]
                self.processes[role] = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=logfile,
                    bufsize=0,
                )
            (self.directory / "config.json").write_text(json.dumps(self.config, indent=2))
        except BaseException:
            self._terminate()
            self.sidecar.close()
            raise
        self.worker = threading.Thread(target=self._feed, name="ffmpeg-triple-feeder", daemon=True)
        self.worker.start()

    def check(self):
        if self.error is not None:
            raise RuntimeError("FFmpeg feeder failed") from self.error
        for role, proc in self.processes.items():
            if not self.closed and proc.poll() is not None:
                raise RuntimeError(f"{role} exited early: {proc.returncode}")

    def submit(self, frames, metadata):
        if self.closed:
            raise RuntimeError("encoder is closed")
        self.check()
        if set(frames) != set(self.ROLES):
            raise ValueError("exactly three declared camera roles required")
        owned = {}
        for role in self.ROLES:
            array = frames[role]
            if array.shape != (self.height, self.width, 4) or array.dtype.name != "uint8":
                raise ValueError(f"invalid RGBA8 frame for {role}")
            owned[role] = array.tobytes(order="C")
        record = json.loads(json.dumps(metadata))
        record.update(
            input_index=self.submitted,
            admit_wall_ns=time.monotonic_ns(),
            output_alignment_proven=False,
        )
        try:
            self.pending.put_nowait((owned, record))
        except queue.Full as exc:
            raise RuntimeError("encoding backlog exceeded bounded ring; probe failed") from exc
        self.submitted += 1

    def _feed(self):
        try:
            while True:
                item = self.pending.get()
                if item is None:
                    break
                frames, record = item
                for role in self.ROLES:
                    view = memoryview(frames[role])
                    while view:
                        count = self.processes[role].stdin.write(view)
                        if not count:
                            raise RuntimeError(f"short pipe write: {role}")
                        view = view[count:]
                record["pipes_written_wall_ns"] = time.monotonic_ns()
                self.sidecar.write(json.dumps(record, separators=(",", ":")) + "\n")
                self.written += 1
        except BaseException as exc:
            self.error = exc

    def _terminate(self):
        for proc in self.processes.values():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        for log in self.logs:
            log.close()

    def finish(self, timeout=30):
        if self.closed:
            raise RuntimeError("finish called twice")
        try:
            self.check()
            self.pending.put(None, timeout=timeout)
            self.worker.join(timeout=timeout)
            if self.worker.is_alive():
                raise RuntimeError("feeder failed to drain")
            self.check()
            for proc in self.processes.values():
                proc.stdin.close()
            for role, proc in self.processes.items():
                if proc.wait(timeout=timeout) != 0:
                    raise RuntimeError(f"{role} failed to flush: {proc.returncode}")
            if self.written != self.submitted:
                raise RuntimeError("input triplets were lost")
        finally:
            self.closed = True
            self._terminate()
            self.sidecar.flush()
            self.sidecar.close()
