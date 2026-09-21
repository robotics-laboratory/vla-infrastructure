"""Opt-in S2 observation journal. Never a dataset or source-acquisition clock."""
from dataclasses import asdict, is_dataclass
import json
import math
import os
from pathlib import Path
import time

import numpy as np


SCHEMA = "physical_s2_journal_v1"


def plain(value):
    if is_dataclass(value) and not isinstance(value, type):
        return plain(asdict(value))
    if hasattr(value, "detach"):
        return plain(value.detach().cpu().numpy())
    if isinstance(value, np.ndarray):
        return plain(value.tolist())
    if isinstance(value, np.generic):
        return plain(value.item())
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None  # explicitly unusable; checker must never interpret as zero
    return value


def controller_snapshot(controller):
    from isaacteleop.retargeting_engine.tensor_types import ControllerInputIndex as I

    available = controller is not None and not controller.is_none
    pose = None
    if available:
        pose = np.concatenate((np.from_dlpack(controller[I.GRIP_POSITION]),
                               np.from_dlpack(controller[I.GRIP_ORIENTATION])))
    return plain({
        "available": available,
        "tracking_valid": bool(available and controller[I.GRIP_IS_VALID]),
        "pose_xyzw": pose,
        "pose_finite": bool(pose is not None and np.isfinite(pose).all()),
        "source_sequence": None, "source_timestamp": None, "source_age_ms": None,
        "source_timing_status": "not_exposed_by_ControllerInput",
    })


class S2AcceptanceLog:
    def __init__(self, directory, *, config, processor_config, versions):
        self.directory = Path(directory)
        self.run_id = self.directory.name
        self.stream = (self.directory / "structured_runtime.jsonl").open("x", buffering=1)
        self.step = 0
        self.reset_count = 0
        self.session_epoch = 0
        self.was_running = False
        self.tracking = dict(left=False, right=False)
        self.last_valid = dict(left=None, right=None)
        self.last_frame = None
        self.event("runtime_start", config=config, processor_config=processor_config,
                   versions=versions, timing_scope="host observation only; D0/R2 unresolved")

    @classmethod
    def optional(cls, **kwargs):
        directory = os.environ.get("VLA_S2_ACCEPTANCE_DIR")
        return cls(directory, **kwargs) if directory else None

    def event(self, event, **fields):
        record = plain(dict(schema=SCHEMA, event=event, run_id=self.run_id,
                            step=self.step, monotonic_ns=time.monotonic_ns(), **fields))
        self.stream.write(json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n")

    def begin(self, step):
        self.step = step
        self.started_ns = time.monotonic_ns()
        self.source = None
        self.info = {}
        self.receipt_ns = None
        marker = self.directory / "scenario.json"
        self.scenario = json.loads(marker.read_text()) if marker.exists() else {"name": "UNMARKED"}

    def observe(self, device, action):
        self.receipt_ns = time.monotonic_ns()
        running = bool(device.session_running)
        if running != self.was_running:
            if running:
                self.session_epoch += 1
                self.last_frame = None
            self.event("session_start" if running else "session_stop",
                       session_epoch=self.session_epoch, reconnect=running and self.session_epoch > 1)
            self.was_running = running
        lifecycle = device._session_lifecycle  # pinned 0.9.0 adapter boundary
        session = lifecycle._session
        info = getattr(session, "last_step_info", None)
        if info is not None and action is not None:
            self.info = {key: getattr(info, key, None) for key in (
                "returned_frame_id", "submitted_frame_id", "returned_age_frames",
                "returned_age_s", "compute_duration_s", "dropped_submissions", "frame_deadline_miss")}
        frame = self.info.get("returned_frame_id")
        self.info["duplicate_returned_result"] = (
            frame == self.last_frame if frame is not None and self.last_frame is not None else None)
        self.last_frame = frame
        # A failed/deferred advance can leave old lifecycle.last_step_result.
        # Do not relabel that old output as a newly received controller sample.
        if action is not None:
            result = lifecycle.last_step_result
            self.source = {side: {
                frame: controller_snapshot(result.get(f"acceptance_{side}_{frame}"))
                for frame in ("raw", "world")} for side in ("left", "right")}

    def reset(self):
        self.reset_count += 1
        self.event("reset_completed", reset_count=self.reset_count)

    def end(self, *, action, command, before, after, ik, camera, env, device):
        for side in ("left", "right"):
            arm = getattr(command, side)
            valid = arm.tracking_valid
            if valid != self.tracking[side]:
                self.event("tracking_reacquired" if valid else "tracking_lost", side=side,
                           last_valid_pose=self.last_valid[side], command=arm,
                           first_target=ik.acceptance_targets[side] if valid else None)
            self.tracking[side] = valid
            if valid and self.source:
                self.last_valid[side] = self.source[side]["world"]["pose_xyzw"]
        preview = getattr(env, "preview", None)
        preview_state = None
        if preview is not None:
            preview.assert_valid()
            preview_state = {"topology": preview.isolation.report() if preview.isolation else None,
                             "publications": getattr(preview.manager, "acceptance_publications", {})}
        elapsed = (time.monotonic_ns() - self.started_ns) / 1e6
        self.event("control_step", control_step_timestamp_ns=self.started_ns,
                   host_receipt_timestamp_ns=self.receipt_ns, scenario=self.scenario,
                   session_epoch=self.session_epoch, session_running=bool(device.session_running),
                   reset_count=self.reset_count, xr=self.source, retargeting=self.info,
                   raw_teleop_action=action, processed_action=command,
                   processor_revision="piper_x_isaac_s2_bimanual_relative_v3",
                   targets=ik.acceptance_targets, applied_native_targets=ik.acceptance_native,
                   tcp_at_ik_world_xyzw=ik.acceptance_tcp_world,
                   tcp_before_base_xyzw=before, tcp_after_base_xyzw=after,
                   cameras=camera, preview=preview_state,
                   task_state="S2 teleoperation; no task outcome evaluated",
                   control_duration_ms=elapsed, deadline_ms=1000 / 30,
                   deadline_missed=elapsed > 1000 / 30)

    def close(self, *, interrupted, failed):
        self.event("runtime_loop_closed", interrupted=interrupted, failed=failed,
                   last_observed_session_running=self.was_running,
                   shutdown_scope="device context exited; process/Kit shutdown checked by runner")
        self.stream.close()
