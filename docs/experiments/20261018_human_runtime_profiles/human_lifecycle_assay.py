#!/usr/bin/env python3
"""Test-only simulated controller input through the real Kit human S2 lifecycle.

Run with the Isaac Python from a matching native RUN/DIAG/RECORD dry-run manifest. This does not
test Quest, physical input, task success, dataset admission or performance.
"""
from __future__ import annotations

import argparse
import faulthandler
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import sys
import traceback
from types import SimpleNamespace


TICKS = 48
BUTTONS = {4: "x", 18: "y", 20: "x", 22: "x",
           26: "x", 40: "y", 42: "x", 44: "b"}
PREVIEW_BUTTONS = {4: "x", 6: "x", 8: "layout", 10: "layout", 12: "b", 14: "b"}


def simulated_device(runtime, torch, mode="record"):
    from isaac_vr_injected_recording import _xr

    class Device:
        session_running = True
        navigation_reset_applied = False

        def __init__(self):
            self.tick, self.reference_epoch = 0, 1
            self.budget = TICKS if mode == "record" else 16
            self.xr_receipt = SimpleNamespace(last_consumed=0)
            self.xr_input = None
            self.rows, self.resets, self.validations = [], [], 0
            self.entered = self.exited = False

        def __enter__(self):
            self.entered = True
            return self

        def __exit__(self, *unused):
            self.exited = True
            return False

        def reset(self, pause=False):
            if pause:
                raise RuntimeError("Assay only expects active reset(pause=False)")
            self.resets.append(self.tick)
            self.reference_epoch += 1
            self.xr_input = None

        def advance(self):
            self.tick += 1
            if self.tick > self.budget:
                raise RuntimeError("Assay exceeded its bounded input schedule")
            self.xr_input = replace(_xr(self.tick), control_reference_epoch=self.reference_epoch)
            last_index = (runtime.RECORD_PREVIEW_LAYOUT_BUTTON_INDEX if mode == "record"
                          else runtime.PREVIEW_LAYOUT_BUTTON_INDEX)
            action = torch.zeros(last_index + 1, dtype=torch.float32)
            # unpack_pipeline_action owns the fixed 22-value bimanual layout.
            action[[6, 7, 17, 18]] = 1.0
            action[[9, 20]] = 0.5
            action[0] = 0.000005 if self.tick % 2 else -0.000005
            action[11] = -action[0]
            button = (BUTTONS if mode == "record" else PREVIEW_BUTTONS).get(self.tick)
            if button is not None:
                action[{"x": runtime.DEMO_DISPLAY_BUTTON_INDEX,
                        "y": runtime.RECORD_STOP_BUTTON_INDEX,
                        "layout": runtime.PREVIEW_LAYOUT_BUTTON_INDEX,
                        "b": runtime.DEMO_BACKDROP_BUTTON_INDEX}[button]] = 1.0
            if mode == "record" and self.tick in (6, 12, 19, 21, 28, 36):
                action[runtime.RECORD_PREVIEW_LAYOUT_BUTTON_INDEX] = 1.0
            self.rows.append(dict(tick=self.tick, button=button,
                                  reset_requested=mode == "record" and self.tick == 2, action=action.tolist(),
                                  reference_epoch=self.reference_epoch))
            return action

        def validate_xr(self, xr):
            if (xr is not self.xr_input or xr.deviceio_update_epoch != self.tick
                    or xr.control_reference_epoch != self.reference_epoch
                    or xr.deviceio_update_epoch <= self.xr_receipt.last_consumed):
                raise RuntimeError("Assay XR identity changed or was reused")
            self.validations += 1

        def schedule_recenter_to_view(self, _path):
            return False  # No physical XR reference exists in this assay.

    return Device()


def child_command(manifest, output, mode="record"):
    """Keep launcher bootstrap/scene/media settings; replace test I/O and XR inputs."""
    command = list(manifest["launch"]["command"])
    if (manifest["mode"] != {"diag": "diagnostic"}.get(mode, mode)
            or not manifest["runtime_profile"]["native"]):
        raise ValueError(f"Assay requires a native {mode} launcher manifest")
    if Path(command[0]).resolve() != Path(sys.executable).resolve():
        raise ValueError(f"Use the manifest's Isaac Python: {command[0]}")
    remove = {"--xr", "--s2-require-session", "--no-s2-require-session",
              "--s2-require-tracking"}
    command = [value for value in command if value not in remove]
    replacements = {
        "--config": str(output / "runtime.yaml"), "--report": str(output / "result.json"),
        "--s2-max-control-steps": str(TICKS if mode == "record" else 16), "--s2-reset-step": "0",
        "--s2-cloudxr-profile": "standalone",
        "--s2-performance-log": str(output / "performance.jsonl"),
        "--s2-performance-warmup-steps": "0", "--s2-performance-window-steps": "48" if mode == "record" else "16",
    }
    if mode == "record":
        (output / "recordings").mkdir(mode=0o700, exist_ok=True)
        replacements.update({"--s2-recording-dir": str(output / "recordings/episode_000000"),
                             "--s2-recordings-root": str(output / "recordings")})
    elif "--demo-hud-on-start" not in command:
        command.append("--demo-hud-on-start")
    source_config = Path(command[command.index("--config") + 1])
    (output / "runtime.yaml").write_bytes(source_config.read_bytes())
    for flag, value in replacements.items():
        if flag in command:
            command[command.index(flag) + 1] = value
        else:
            command.extend([flag, value])
    command.append("--no-s2-require-session")
    if "--s2-teleop" not in command or ("--s2-record" in command) != (mode == "record"):
        raise ValueError("Assay must use the matching ordinary S2 teleop branch")
    return command


def check_outputs(output, device, mode="record"):
    result = json.loads((output / "result.json").read_text())
    native = result["native_runtime"]
    if (not result["passed"] or device.tick != device.budget or not device.validations
            or not device.entered or not device.exited or native["media"]["cleanup_errors"]):
        raise RuntimeError("Shared S2 loop, fresh eligible XR decisions or media cleanup failed")
    if mode != "record":
        layout = native["preview_layout"]
        if (device.xr_receipt.last_consumed != device.budget or device.resets
                or layout is None or layout["toggle_count"] != 2
                or native["episodes"] or native["media"]["encoders"]
                or result.get("recording_episodes") or (output / "recordings").exists()
                or list(output.rglob("session.hdf5")) or list(output.rglob("stream.h264"))):
            raise RuntimeError("Unrecorded native decisions/layout toggles failed or episode writers were opened")
        return dict(mode=mode, control_ticks=device.tick, preview_layout=layout,
                    validated_xr_identities=device.validations,
                    last_applied_xr_update=device.xr_receipt.last_consumed,
                    episode_writers=0, unbound_snapshot_decisions_applied=True)
    import h5py

    episodes = result.get("recording_episodes", [])
    saved = [json.loads(path.read_text()) for path in (output / "recordings/saved_demos").glob("*.json")]
    if (not result["passed"] or result["human_recording"]["state"] != "waiting"
            or len(episodes) != 2 or len(saved) != 2
            or {item["task_outcome"] for item in saved} != {"success", "incomplete"}):
        raise RuntimeError("Two saved/classified demonstrations did not finish in WAITING")
    if native["preview_layout"]["toggle_count"] != 6:
        raise RuntimeError("RECORD/review/classification L3 layout switching failed")
    summaries = []
    for episode in episodes:
        directory = Path(episode["output_dir"])
        manifest = json.loads((directory / "manifest.json").read_text())
        marker = json.loads((directory / "recording_state.json").read_text())
        media = json.loads((directory / "live_rgb/receipt.json").read_text())
        if (episode["committed_frames"] < 2 or episode["reason"] != "explicit_stop"
                or manifest["artifact_state"] != "finalized" or marker["artifact_state"] != "finalized"
                or media["cleanup_errors"] or media["encoded_packets"] < 1):
            raise RuntimeError(f"Incomplete native episode finalization: {directory}")
        hdf = directory / "session.hdf5"
        if hashlib.sha256(hdf.read_bytes()).hexdigest() != manifest["hdf5_sha256"]:
            raise RuntimeError(f"Native HDF digest mismatch: {hdf}")
        with h5py.File(hdf, "r") as stream:
            groups = list(stream["episodes"].values())
            count = sum(len(group["d0/committed_transition/frame_index"]) for group in groups)
            if count != episode["committed_frames"]:
                raise RuntimeError("Canonical committed HDF rows disagree with shared-loop receipt")
        bound = None
        if result["native_runtime"]["profile"]["media"]["bind_sources"]:
            bindings = directory / "live_rgb/camera_bindings.hdf5"
            with h5py.File(bindings, "r") as stream:
                bound = len(stream["bindings"])
                if bound < 1 or int(stream.attrs["committed_rows"]) != bound:
                    raise RuntimeError("Native source binding HDF is empty or not committed")
        videos = [directory / "live_rgb/media" / f"role{role}/stream.h264" for role in range(3)]
        if not all(path.is_file() and path.stat().st_size > 0 for path in videos):
            raise RuntimeError("Expected three nonempty live NVENC streams")
        summaries.append(dict(path=str(directory), committed_rows=count, bound_frames=bound,
                              encoded_packets=media["encoded_packets"], hdf5_sha256=manifest["hdf5_sha256"]))
    if (device.tick != TICKS or len(device.resets) != 3 or not device.validations
            or not device.entered or not device.exited):
        raise RuntimeError("Assay input schedule, explicit/classification resets or device scope incomplete")
    if result["native_runtime"]["media"]["cleanup_errors"]:
        raise RuntimeError("Native media teardown reported errors")
    return dict(episodes=summaries, saved_demonstrations=len(saved), reset_ticks=device.resets,
                preview_layout=native["preview_layout"],
                validated_xr_identities=device.validations, final_state="waiting")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("run", "diag", "record"), default="record")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    trace = (output / "thread_stacks.log").open("w")
    faulthandler.dump_traceback_later(60, repeat=True, file=trace)
    if (output / "assay_receipt.json").exists() or (output / "result.json").exists():
        raise FileExistsError("Use a fresh assay output directory")
    receipt = dict(schema="piper_x_real_kit_simulated_human_lifecycle_assay_v1", passed=False,
                   physical=False, quest_connected=False, dataset_admissible=False,
                   mode=args.mode, simulated_input=True, simulated_classification=args.mode == "record",
                   manifest=str(args.manifest.resolve()),
                   assay_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   limitations=["No Quest, physical controller, task-success or dataset qualification.",
                                "Headless synthetic input is not a performance measurement."],
                   replacement_seams=["isaac_s2_runtime.create_piper_x_teleop_device",
                                      "isaaclab_teleop.control_events.poll_control_events"])
    namespace, device, restores = None, None, []
    return_code = 1
    try:
        manifest = json.loads(args.manifest.read_text())
        command = child_command(manifest, output, args.mode)
        receipt["child_command"] = command
        (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        sys.path.insert(0, str(Path(command[1]).parent))
        sys.path.insert(0, str(Path(command[1]).parents[1]))
        from isaac_demo_launch import STACKS, user_environment
        stack_name = manifest["launch"]["stack"]
        environment, _ = user_environment(
            STACKS[stack_name], stack_name,
            state_root=Path(manifest["host_paths"]["kit_portable_root"]).parent,
        )
        os.environ.update(environment)
        os.environ.pop("VLA_CLOUDXR_INSTALL_DIR", None)
        os.environ["ISAACLAB_CXR_SKIP_AUTOLAUNCH"] = "1"
        sys.argv = command[1:]
        namespace = runpy.run_path(command[1], run_name="human_lifecycle_assay_child")
        import torch
        import isaac_s2_runtime as runtime
        import isaaclab_teleop.control_events as controls

        device = simulated_device(runtime, torch, args.mode)
        restores = [(runtime, "create_piper_x_teleop_device", runtime.create_piper_x_teleop_device),
                    (controls, "poll_control_events", controls.poll_control_events)]
        runtime.create_piper_x_teleop_device = lambda *a, **kw: device
        controls.poll_control_events = lambda current: SimpleNamespace(
            should_reset=args.mode == "record" and current.tick == 2, is_active=True)
        if namespace["args_cli"].xr or namespace["owned_cloudxr"] is not None:
            raise RuntimeError("Assay must not create an XR session or own CloudXR")
        return_code = namespace["main"]()
        if return_code:
            raise RuntimeError(f"Shared S2 loop returned {return_code}")
        receipt["checks"] = check_outputs(output, device, args.mode)
        receipt["passed"] = True
    except BaseException as error:
        return_code = 1
        receipt["error"] = f"{type(error).__name__}: {error}"
        traceback.print_exc()
    finally:
        for module, attribute, original in reversed(restores):
            setattr(module, attribute, original)
        if device is not None:
            receipt["input_schedule"] = device.rows
        receipt["return_code"] = return_code
        (output / "assay_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        faulthandler.cancel_dump_traceback_later()
        trace.close()
        print("HUMAN_LIFECYCLE_ASSAY=" + json.dumps(receipt, sort_keys=True), flush=True)
        if namespace is not None:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            namespace["simulation_app"].close(exit_code=return_code)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
