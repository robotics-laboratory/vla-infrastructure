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
        self.cai = {"shape": (height, width, 4),
                    "strides": (pitch or width * 4, 4, 1),
                    "data": (int(ptr), False), "typestr": "|u1", "version": 3}

    def cuda(self):
        return self.cai


class PacketEncoder:
    def __init__(self, directory, width=960, height=600, cpu=True,
                 cuda_context=0, cuda_stream=0, gpu=0, gop=50, fps=50):
        import PyNvVideoCodec as nvc
        if getattr(nvc, "__version__", None) != "2.2.3":
            raise RuntimeError("adapter audited against PyNvVideoCodec 2.2.3 only")
        self.nvc = nvc
        self.cpu = cpu
        self.width, self.height = width, height
        self.encoder = nvc.CreateEncoder(width, height, "ABGR", cpu,
            cudacontext=int(cuda_context), cudastream=int(cuda_stream), gpu_id=gpu,
            codec="h264", preset="p1", tuning_info="ultra_low_latency",
            bf=0, gop=gop, fps=fps, bitrate="16M", rc="vbr")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.bitstream = (self.directory / "stream.h264").open("wb")
        self.sidecar = (self.directory / "packets.jsonl").open("w")
        self.inputs = self.packets = 0
        self.closed = False

    def _write(self, packets, flushing=False):
        # Exact wheel samples use iterable dictionaries, unlike web API docs.
        for packet in packets:
            payload = bytes(packet["data"])
            offset = self.bitstream.tell()
            self.bitstream.write(payload)
            self.sidecar.write(json.dumps(dict(packet_index=self.packets,
                encoder_input_timestamp=int(packet["timestamp"]),
                picture_type=str(packet["picture_type"]), offset=offset,
                length=len(payload), flush=flushing,
                pixel_alignment_proven=False)) + "\n")
            self.packets += 1

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
        self._write(self.encoder.Encode(frame, picture))
        self.inputs += 1

    def finish(self):
        if self.closed:
            raise RuntimeError("finish called twice")
        try:
            self._write(self.encoder.EndEncode(), flushing=True)
        finally:
            self.closed = True
            self.bitstream.close()
            self.sidecar.close()
            self.encoder = None

