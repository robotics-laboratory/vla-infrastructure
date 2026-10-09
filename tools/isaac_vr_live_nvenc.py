"""Exact PyNvVideoCodec 2.2.3 H264/bf=0 adapter; no GPU import at module load.

Output timestamp is an encoder-local ordinal, never a source time or pixel proof.
The optional underscore arguments exist only for CPU fake-codec tests.
"""

from pathlib import Path
import json
import threading

_QUARANTINE = []  # Failed fences must retain owners even if caller loses self.


class CudaRGBAFrame:
    def __init__(self, owner, ptr, width, height, pitch=None):
        if owner is None or int(ptr) <= 0 or width <= 0 or height <= 0:
            raise ValueError("Require an owned positive CUDA allocation and dimensions")
        pitch = width * 4 if pitch is None else pitch
        if pitch < width * 4:
            raise ValueError("RGBA pitch is smaller than one row")
        self.owner = owner
        self.cai = dict(
            shape=(height, width, 4),
            strides=(pitch, 4, 1),
            data=(int(ptr), False),
            typestr="|u1",
            version=3,
        )

    def cuda(self):
        return self

    @property
    def __cuda_array_interface__(self):
        return self.cai


class PacketEncoder:
    def __init__(
        self,
        directory,
        width=960,
        height=600,
        cpu=True,
        cuda_context=0,
        cuda_stream=0,
        gpu=0,
        gop=50,
        fps=50,
        capacity=8,
        release_owner=None,
        synchronize=None,
        *,
        _nvc=None,
    ):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("Require positive integer owner capacity")
        if not cpu and (release_owner is None or synchronize is None):
            raise ValueError("GPU ownership requires ACK release and cleanup fence callbacks")
        if _nvc is None:
            import PyNvVideoCodec as _nvc
        if getattr(_nvc, "__version__", None) != "2.2.3":
            raise RuntimeError("Requires audited PyNvVideoCodec 2.2.3")
        self.nvc, self.cpu = _nvc, cpu
        self.width, self.height, self.capacity = width, height, capacity
        self.thread = threading.get_ident()
        self.release_owner, self.synchronize = release_owner, synchronize
        self.encoder = self.bitstream = self.sidecar = None
        self.inputs = self.packets = self.max_pending = 0
        self.pending, self.input_tags = {}, {}
        self.last_tag = None
        self.closed = self.failed = False
        self.errors = []
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        try:
            self.bitstream = (self.directory / "stream.h264").open("xb")
            self.sidecar = (self.directory / "packets.jsonl").open("x")
            self.encoder = _nvc.CreateEncoder(
                width,
                height,
                "ABGR",
                cpu,
                cudacontext=int(cuda_context),
                cudastream=int(cuda_stream),
                gpu_id=gpu,
                codec="h264",
                preset="P1",
                tuning_info="ultra_low_latency",
                bf=0,
                lookahead=0,
                gop=gop,
                fps=fps,
                bitrate=16000000,
                rc="vbr",
            )
        except BaseException as error:
            self._fail(error)
            self._close_files()
            self.closed = True
            self._receipt()
            raise

    def _guard(self):
        if self.closed or self.failed or threading.get_ident() != self.thread:
            raise RuntimeError("Encoder needs its healthy owner thread")

    def _fail(self, error):
        self.failed = True
        self.errors.append(f"{type(error).__name__}: {error}")

    def _write(self, packets, flushing=False):
        for packet in packets:
            ordinal = packet["timestamp"]
            if type(ordinal) is not int or ordinal != self.packets or ordinal not in self.pending:
                raise RuntimeError(
                    f"Unknown/duplicate/nonconsecutive packet ordinal {ordinal!r}; expected {self.packets}"
                )
            payload = bytes(packet["data"])
            if not payload:
                raise RuntimeError("Empty encoded packet")
            picture_type = str(packet["picture_type"])
            offset = self.bitstream.tell()
            if self.bitstream.write(payload) != len(payload):
                raise RuntimeError("Short bitstream write")
            row = dict(
                packet_index=self.packets,
                encoder_packet_timestamp=ordinal,
                submitted_source_tag=self.input_tags[ordinal],
                offset=offset,
                picture_type=picture_type,
                length=len(payload),
                flush=flushing,
                source_tag_mapping="exact local ordinal ledger; pixel proof independent",
                pixel_alignment_proven=False,
            )
            line = json.dumps(row) + "\n"
            if self.sidecar.write(line) != len(line):
                raise RuntimeError("Short packet sidecar write")
            # A returned exact-codec packet follows completed output lock/unmap.
            # GPU callback additionally confirms the clone fence before owner release.
            if self.release_owner is not None:
                self.release_owner(self.pending[ordinal])
            del self.pending[ordinal]
            del self.input_tags[ordinal]
            self.packets += 1

    def submit(self, frame, input_tag):
        self._guard()
        if (
            type(input_tag) is not int
            or input_tag < 0
            or (self.last_tag is not None and input_tag <= self.last_tag)
        ):
            raise ValueError("Source tag must be a strictly increasing nonnegative int")
        if len(self.pending) >= self.capacity:
            raise RuntimeError("Owner capacity full before Encode; no overwrite/drop")
        if self.cpu:
            if (
                frame.shape != (self.height, self.width, 4)
                or frame.dtype.name != "uint8"
                or not frame.flags.c_contiguous
            ):
                raise ValueError("CPU input must be contiguous HWC RGBA8")
            frame = frame.reshape(-1)
        ordinal = self.inputs
        picture = self.nvc.NV_ENC_PIC_PARAMS()
        picture.inputTimeStamp = input_tag
        self.pending[ordinal], self.input_tags[ordinal] = frame, input_tag
        self.max_pending = max(self.max_pending, len(self.pending))
        try:
            packets = self.encoder.Encode(frame, picture)
            self.inputs += 1
            self.last_tag = input_tag
            self._write(packets)
        except BaseException as error:
            # Native timestamp advances before driver encode; never retry this instance.
            self._fail(error)
            raise
        return ordinal

    def _close_files(self):
        for handle in (self.bitstream, self.sidecar):
            if handle is not None and not handle.closed:
                try:
                    handle.close()
                except BaseException as error:
                    self._fail(error)

    def _receipt(self):
        self.receipt = dict(
            schema="live30_strict_packet_encoder_v1",
            passed=not self.failed,
            inputs=self.inputs,
            packets=self.packets,
            max_pending=self.max_pending,
            capacity=self.capacity,
            unacknowledged_ordinals=sorted(self.pending),
            owners_retained=len(self.pending),
            errors=list(self.errors),
            cpu=self.cpu,
            dataset_admissible=False,
            pixel_alignment_proven=False,
        )
        (self.directory / "encoder.json").write_text(json.dumps(self.receipt, indent=2) + "\n")
        return self.receipt

    def finish(self):
        if threading.get_ident() != self.thread:
            raise RuntimeError("Drain on encoder owner thread")
        if self.closed:
            if self.failed:
                raise RuntimeError("Encoder already failed; inspect encoder.json")
            return self.receipt
        try:
            try:
                self._write(self.encoder.EndEncode(), flushing=True)
                if self.pending or self.inputs != self.packets:
                    raise RuntimeError("Missing packet ordinals after EndEncode")
            except BaseException as error:
                self._fail(error)
            # Always reach the fence before destroying encoder or unresolved owners.
            safe = not self.pending
            if self.synchronize is not None:
                safe = False
                try:
                    self.synchronize()
                    safe = True
                except BaseException as error:
                    self._fail(error)
            missing = sorted(self.pending)
            if safe:
                self.encoder = None
                self.pending.clear()
                self.input_tags.clear()
            else:
                _QUARANTINE.append(self)
            # On failed synchronization keep owners AND encoder quarantined until process exit.
            self.unacknowledged_at_drain = missing
        finally:
            self.closed = True
            self._close_files()
            self._receipt()
            self.receipt["unacknowledged_at_drain"] = getattr(self, "unacknowledged_at_drain", [])
            (self.directory / "encoder.json").write_text(json.dumps(self.receipt, indent=2) + "\n")
        if self.failed:
            raise RuntimeError("; ".join(self.errors))
        return self.receipt
