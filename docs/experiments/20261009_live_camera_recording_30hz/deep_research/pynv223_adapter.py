"""Probe adapter for exact PyNvVideoCodec 2.2.3 wheel API; no GPU on import.

Callers must keep owned CUDA frames alive and establish producer completion.
GPU submission requires the encoder's CUDA context current on that thread.
Packet timestamps are encoder input tags, not independently observed pixels.
"""

from pathlib import Path
import json


class CudaRGBAFrame:
    """Matches 2.2.3 samples/utils/Utils.py AppFrame.cuda() protocol.

    Byte layout is R,G,B,A, represented as NVENC packed ABGR on little-endian.
    owner retains a Warp/Torch allocation; ptr must refer to that owned buffer.
    """

    def __init__(self, owner, ptr, width, height, pitch=None):
        self.owner = owner
        self.cai = {
            "shape": (height, width, 4),
            "strides": (pitch or width * 4, 4, 1),
            "data": (int(ptr), False),
            "typestr": "|u1",
            "version": 3,
        }

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
    ):
        import PyNvVideoCodec as nvc

        if getattr(nvc, "__version__", None) != "2.2.3":
            raise RuntimeError("adapter audited against PyNvVideoCodec 2.2.3 only")
        self.nvc = nvc
        self.cpu = cpu
        self.width, self.height = width, height
        self.encoder = nvc.CreateEncoder(
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
            gop=gop,
            fps=fps,
            bitrate=16000000,
            rc="vbr",
        )
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.bitstream = (self.directory / "stream.h264").open("wb")
        self.sidecar = (self.directory / "packets.jsonl").open("w")
        self.inputs = self.packets = 0
        self.pending = {}
        self.input_tags = {}
        self.max_pending = 0
        self.closed = False

    def _write(self, packets, flushing=False):
        # Exact wheel samples use iterable dictionaries, unlike web API docs.
        for packet in packets:
            payload = bytes(packet["data"])
            offset = self.bitstream.tell()
            self.bitstream.write(payload)
            timestamp = int(packet["timestamp"])
            self.sidecar.write(
                json.dumps(
                    dict(
                        packet_index=self.packets,
                        encoder_packet_timestamp=timestamp,
                        submitted_source_tag=self.input_tags.get(timestamp),
                        source_tag_mapping="inferred local encoder ordinal; verify pixels",
                        picture_type=str(packet["picture_type"]),
                        offset=offset,
                        length=len(payload),
                        flush=flushing,
                        pixel_alignment_proven=False,
                    )
                )
                + "\n"
            )
            self.packets += 1
            self.pending.pop(timestamp, None)

    def submit(self, frame, input_tag):
        if self.closed:
            raise RuntimeError("encoder closed")
        if self.cpu:
            if frame.shape != (self.height, self.width, 4) or frame.dtype.name != "uint8":
                raise ValueError("CPU input must be HWC RGBA8")
            if not frame.flags.c_contiguous:
                raise ValueError("CPU input must be contiguous and owned")
            frame = frame.reshape(-1)
        picture = self.nvc.NV_ENC_PIC_PARAMS()
        picture.inputTimeStamp = int(input_tag)
        self.input_tags[self.inputs] = int(input_tag)
        if not self.cpu:
            self.pending[self.inputs] = frame
        self._write(self.encoder.Encode(frame, picture))
        self.max_pending = max(self.max_pending, len(self.pending))
        if len(self.pending) > 8:
            raise RuntimeError("bounded GPU ownership ring exceeded eight frames")
        self.inputs += 1

    def finish(self):
        if self.closed:
            raise RuntimeError("finish called twice")
        try:
            self._write(self.encoder.EndEncode(), flushing=True)
            if self.pending:
                raise RuntimeError("encoder drain left unacknowledged GPU sources")
        finally:
            self.closed = True
            self.bitstream.close()
            self.sidecar.close()
            self.encoder = None
            self.pending.clear()
