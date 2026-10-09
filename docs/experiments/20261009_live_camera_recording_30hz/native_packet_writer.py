"""Bounded producer-callback H.264 probe sink for installed Isaac/Kit 110.3.

Load after SimulationApp startup, then instantiate with role -> existing RP path.
Call attach_existing(); drive the app/Replicator; call check() after each update;
finally call detach(). SRTX dispatch requires orchestrator capture events.
reference_time and sampled sim time are retained separately. Neither is declared
to prove the renderer's original frame generation; decode a moving witness.
"""
import hashlib
import json
import math
import os
import time
from fractions import Fraction
from pathlib import Path

import numpy as np
import omni.replicator.core as rep
import omni.usd
from isaacsim.streaming.rtsp.impl.render_var_utils import ensure_render_var_on_product


class NativePacketWriter(rep.Writer):
    data_structure = "renderProduct"

    def __init__(self, products, output_dir, *, warmup_callbacks=120):
        if set(products) != {"left_wrist", "right_wrist", "scene"}:
            raise ValueError("Exactly three canonical camera roles are required")
        self.version, self.node_type_id = "0.1.0", type(self).__name__
        self._kwargs = {}
        self.products = dict(products)
        self.names = {role: path.rsplit("/", 1)[-1] for role, path in products.items()}
        if len(set(self.names.values())) != 3:
            raise ValueError("RP basenames must be unique for structured callback routing")
        self.output = Path(output_dir)
        self.output.mkdir(parents=True, exist_ok=False)
        self.annotators = [
            rep.AnnotatorRegistry.get_annotator("LdrColor", init_params={"compression": "h264"}),
            rep.AnnotatorRegistry.get_annotator("IsaacReadSimulationTime", init_params={"resetOnStop": True}),
        ]
        self._annotators = list(self.annotators)
        self.files = {role: (self.output / f"{role}.h264").open("xb") for role in products}
        self.index = (self.output / "packets.jsonl").open("x", encoding="utf-8")
        self.warmup_callbacks = int(warmup_callbacks)
        self.callbacks = self.complete_rows = 0
        self.previous_ref = None
        self.error = None
        self.closed = False
        self.expected = {}

    def attach_existing(self):
        stage = omni.usd.get_context().get_stage()
        for role, path in self.products.items():
            prim = stage.GetPrimAtPath(path)
            if not prim or prim.GetTypeName() != "RenderProduct":
                raise ValueError(f"Missing existing RenderProduct: {path}")
            cameras = prim.GetRelationship("camera").GetTargets()
            if len(cameras) != 1:
                raise ValueError(f"Expected one camera target: {path}")
            self.expected[role] = {
                "camera": str(cameras[0]),
                "resolution": tuple(int(v) for v in prim.GetAttribute("resolution").Get()),
            }
            ok, _ = ensure_render_var_on_product(stage, path, "LdrColor", "h264")
            if not ok:
                raise RuntimeError(f"Cannot prepare compressed LdrColor: {path}")
        self.attach(list(self.products.values()))

    def write_metadata(self):
        self._is_metadata_written = True

    def write(self, data):
        if self.error is not None or self.closed:
            return
        self.callbacks += 1
        row = {"callback": self.callbacks, "callback_host_monotonic_ns": time.monotonic_ns(),
               "renderer_source_frame_id": None, "capture_alignment_proven": False}
        try:
            ref = tuple(int(v) for v in data["reference_time"])
            if len(ref) != 2 or ref[1] <= 0:
                raise ValueError(f"Invalid producer reference_time: {ref}")
            row["reference_time"] = ref
            ref_value = Fraction(*ref)
            entries, packets = {}, {}
            for role, name in self.names.items():
                payload = data["renderProducts"][name]
                if str(payload["camera"]) != self.expected[role]["camera"]:
                    raise ValueError(f"Wrong camera identity for {role}")
                if tuple(payload["resolution"]) != self.expected[role]["resolution"]:
                    raise ValueError(f"Wrong native resolution for {role}")
                sampled_time = float(payload["IsaacReadSimulationTime"]["simulationTime"])
                if not math.isfinite(sampled_time):
                    raise ValueError(f"Invalid sampled simulation time for {role}")
                array = payload["LdrColor"]
                array = array["data"] if isinstance(array, dict) else array
                if not isinstance(array, np.ndarray) or array.dtype != np.uint8 or array.ndim != 1:
                    raise ValueError(f"Expected flat uint8 H.264 packet for {role}")
                packets[role] = array.tobytes()  # Own bytes before another producer update.
                entries[role] = {"render_product": self.products[role], **self.expected[role],
                                 "sampled_simulation_time": sampled_time,
                                 "offset": self.files[role].tell(), "bytes": len(packets[role]),
                                 "sha256": hashlib.sha256(packets[role]).hexdigest()}
            row["cameras"] = entries
            if any(not packet for packet in packets.values()):
                if self.callbacks > self.warmup_callbacks:
                    raise RuntimeError("Empty camera packet after bounded callback warmup")
                row["status"] = "warmup_empty"
            else:
                if self.previous_ref is not None and ref_value <= self.previous_ref:
                    raise RuntimeError("Repeated/regressed producer reference time; new epoch required")
                for role, packet in packets.items():
                    if self.files[role].write(packet) != len(packet):
                        raise OSError(f"Short write: {role}")
                self.previous_ref = ref_value
                self.complete_rows += 1
                row.update(status="complete_packets_unverified", packet_row=self.complete_rows)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            row.update(status="failed", error=self.error)
        self.index.write(json.dumps(row, separators=(",", ":")) + "\n")

    def check(self):
        if self.error:
            raise RuntimeError(self.error)

    def on_final_frame(self):
        if not self.closed:
            self.closed = True
            for stream in [*self.files.values(), self.index]:
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()

    def detach(self):
        try:
            super().detach()
        finally:
            self.on_final_frame()
