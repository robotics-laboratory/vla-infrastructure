"""Bounded post-run analysis for the physical S2 journal; no score or human inference."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import statistics
from typing import Any

import numpy as np

try:
    from .isaac_s2_performance import _distribution  # type: ignore[import-not-found]
    from .isaac_s2_processor import controller_pose_delta_xyzw  # type: ignore[import-not-found]
except ImportError:
    from isaac_s2_performance import _distribution
    from isaac_s2_processor import controller_pose_delta_xyzw


CRITERIA = (
    "identity", "translation_axes", "rotation_axes", "translation_scale", "rotation_scale",
    "clutch_rebase", "per_hand_speed", "gripper", "cross_talk", "tracking_valid",
    "tracking_loss", "tracking_reacquisition", "startup", "reconnect", "headset_preview",
    "wrist_cameras", "preview_recursion", "reset", "shutdown", "stale_duplicate",
    "cadence", "runtime_diagnostics",
)
HUMAN_ITEMS = {
    "startup": "Quest подключён, workspace виден, управление запускается ожидаемо",
    **{f"identity_{s}": f"Физическая {s} рука управляет только одноимённой рукой"
       for s in ("left", "right")},
    **{f"{s}_{kind}_{axis}": f"{s}: {kind} {axis}, оба знака соответствуют ожиданию"
       for s in ("left", "right") for kind, axes in
       (("translation", ("forward_back", "left_right", "up_down")),
        ("rotation", ("pitch", "yaw", "roll"))) for axis in axes},
    **{f"{s}_{kind}": f"{s}: {description}" for s in ("left", "right") for kind, description in (
        ("translation_scale", "масштаб translation адекватный"),
        ("rotation_scale", "масштаб rotation адекватный"),
        ("clutch_rebase", "squeeze удерживает; release/rebase без неожиданного скачка"),
        ("per_hand_speed", "независимый speed slider работает ожидаемо"),
        ("gripper_polarity", "trigger закрывает gripper; отпускание открывает"),
        ("gripper_range", "видны промежуточные положения и весь диапазон"),
        ("cross_talk", "вторая рука не получает управление от первой"),
        ("tracking_loss", "краткая потеря tracking вызывает ожидаемое удержание"),
        ("tracking_reacquisition", "tracking возвращается без скачка и без ручного clutch"))},
    "reconnect": "Stop AR / Start AR: identities сохранены, stale intent не воспроизводится",
    "reset": "Client reset и продолжение: обе руки и references восстановлены",
    "wrist_cameras": "Left/right feeds и ориентация соответствуют рукам",
    "headset_preview": "Preview действительно виден в Quest, нет мешающих артефактов",
    "preview_recursion": "При двух видимых feeds в Quest нет вложенных preview panels",
    "shutdown": "Client disconnect и SIGINT завершают runtime корректно",
}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def distribution(values):
    if not values:
        return {"samples": 0}
    result = _distribution(values)
    return {k.removesuffix("_ms"): v for k, v in result.items()} | {
        "stddev": statistics.pstdev(values)}


def analyze(rows):
    checks: dict[str, dict[str, Any]] = {key: {"status": "INSUFFICIENT", "reason": "required observations absent"}
              for key in CRITERIA}
    counts: Counter[str] = Counter()
    failures: dict[str, list[dict[str, Any]]] = defaultdict(list)
    gains = defaultdict(list)
    motion_counts: Counter[str] = Counter()
    transitions: Counter[str] = Counter()
    reacquisitions = []
    steps = [r for r in rows if r.get("event") == "control_step"]
    starts = [r for r in rows if r.get("event") == "runtime_start"]
    if any(r.get("schema") != "physical_s2_journal_v1" for r in rows):
        raise ValueError("unknown or missing journal schema")
    if not steps or len(starts) != 1:
        return checks, {"steps": len(steps), "issue": "missing steps or unique runtime_start"}
    required = {"step", "run_id", "monotonic_ns", "control_step_timestamp_ns", "processed_action",
                "raw_teleop_action", "applied_native_targets", "targets", "tcp_at_ik_world_xyzw",
                "tcp_before_base_xyzw", "tcp_after_base_xyzw", "reset_count", "session_epoch",
                "xr", "retargeting", "cameras", "preview", "scenario", "control_duration_ms", "deadline_missed"}
    if any(not required.issubset(row) for row in steps):
        raise ValueError("incomplete per-step evidence fields")
    cfg = starts[0]["processor_config"]
    run_id = starts[0]["run_id"]
    previous = None
    reset_epochs = set()
    publication_counts = defaultdict(set)
    source_gains = defaultdict(list)
    isolated: Counter[str] = Counter()

    def fail(key, row, reason):
        counts[f"violations:{key}"] += 1
        if len(failures[key]) < 20:
            failures[key].append({"step": row["step"], "reason": reason,
                                  "metric_window_steps": [max(1, row["step"] - 2), row["step"] + 2]})

    for row in steps:
        if row["run_id"] != run_id or (previous and (
            row["step"] != previous["step"] + 1 or row["monotonic_ns"] <= previous["monotonic_ns"]
        )):
            fail("runtime_diagnostics", row, "run identity or step/time continuity")
        command = row["processed_action"]
        raw = row["raw_teleop_action"]
        reset_epochs.add(row["reset_count"])
        timing = row["retargeting"]
        counts["duplicate_returned_results"] += bool(timing.get("duplicate_returned_result"))
        counts["dropped_submissions"] += timing.get("dropped_submissions") or 0
        counts["late_retargeting_results"] += bool(timing.get("frame_deadline_miss"))
        counts["host_control_deadline_misses"] += row["deadline_missed"]
        counts["pipeline_timing_samples"] += timing.get("returned_frame_id") is not None
        if not row["cameras"]["valid"] or not row["cameras"]["strictly_advanced"]:
            fail("wrist_cameras", row, "invalid or nonadvancing camera within reset epoch")
        preview = row["preview"]
        if preview and preview.get("topology", {}).get("active_panel_roots"):
            counts["preview_topology_samples"] += 1
        if preview:
            for name, value in preview["publications"].items():
                publication_counts[name].add(value["count"])
        for side, offset in (("left", 0), ("right", 11)):
            arm = command[side]
            delta = np.asarray(arm["delta_pose"], dtype=float)
            transitions[f'{side}:{arm["transition"]}'] += 1
            tracked = arm["tracking_valid"]
            native = row.get("applied_native_targets", {}).get(side)
            if native is not None and (len(native) != 7 or not np.isfinite(native).all()
                                       or not np.isclose(native[-1], arm["gripper_aperture_m"], atol=1e-8)):
                fail("gripper", row, f"{side}: native target invalid or gripper differs from mapped command")
            counts[f"{side}:valid"] += tracked
            if not np.isfinite(delta).all():
                fail("runtime_diagnostics", row, f"{side}: nonfinite command")
            hold = not tracked or arm["clutch_active"] or arm["rebased"] or not command["session_active"]
            if hold and np.any(delta):
                fail("tracking_loss" if not tracked else "clutch_rebase", row, f"{side}: nonzero held intent")
            if not tracked:
                index = 0 if side == "left" else 1
                gains[f"{side}:invalid_tracking_tcp_motion_m"].append(float(np.linalg.norm(
                    np.asarray(row["tcp_after_base_xyzw"][index][:3]) -
                    np.asarray(row["tcp_before_base_xyzw"][index][:3]))))
                if previous and row["reset_count"] == previous["reset_count"] and (
                    arm["gripper_aperture_m"] != previous["processed_action"][side]["gripper_aperture_m"]):
                    fail("tracking_loss", row, f"{side}: gripper changed while tracking invalid")
            if raw is not None:
                source = np.asarray(raw[offset:offset + 6], dtype=float)
                if arm["transition"] == "motion":
                    mode = arm["sensitivity_mode"]
                    if mode == "slider":
                        value = min(1., max(-1., raw[offset + 10]))
                        bounds = ("min", "center") if value < 0 else ("center", "max")
                        fraction = value + 1 if value < 0 else value
                        expected_scales = [cfg[f"slider_{bounds[0]}_{kind}_scale"] + fraction *
                            (cfg[f"slider_{bounds[1]}_{kind}_scale"] - cfg[f"slider_{bounds[0]}_{kind}_scale"])
                            for kind in ("translation", "rotation")]
                    else:
                        expected_scales = [cfg[f"{mode}_{kind}_scale"] for kind in ("translation", "rotation")]
                    scales = [expected_scales[0]] * 3 + [expected_scales[1]] * 3
                    if not np.allclose([arm["translation_scale"], arm["rotation_scale"]], expected_scales):
                        fail("per_hand_speed", row, f"{side}: gain differs from configured mode/input")
                    # Float serialization tolerance, NOT a physical jump threshold.
                    if not np.allclose(delta, source * scales, rtol=1e-6, atol=1e-9):
                        fail("translation_scale", row, f"{side}: raw-to-processed mapping differs")
                        fail("rotation_scale", row, f"{side}: raw-to-processed mapping differs")
                    for axis in range(6):
                        if abs(source[axis]) > 1e-9:
                            gains[f"{side}:{axis}"].append(float(delta[axis] / source[axis]))
                            motion_counts[f"{side}:{axis}:{'positive' if source[axis] > 0 else 'negative'}"] += 1
                    if np.any((source * delta) < 0):
                        fail("translation_axes", row, f"{side}: sign inversion")
                        fail("rotation_axes", row, f"{side}: sign inversion")
                    if not np.any(source) and np.any(delta):
                        fail("cross_talk", row, f"{side}: output without own input")
                    scenario = row["scenario"]["name"]
                    other = "right" if side == "left" else "left"
                    if scenario.startswith(other.upper() + "_TRANSLATION") and not np.any(source):
                        isolated[side] += 1
                        if np.any(delta):
                            fail("cross_talk", row, f"{side}: inactive arm commanded in isolated scenario")
                if tracked:
                    trigger = float(raw[offset + 9])
                    fraction = min(1., max(0., (trigger - cfg["gripper_trigger_min"]) /
                                          (cfg["gripper_trigger_max"] - cfg["gripper_trigger_min"])))
                    expected = cfg["gripper_open_m"] + fraction * (cfg["gripper_closed_m"] - cfg["gripper_open_m"])
                    if not np.isclose(arm["gripper_aperture_m"], expected, atol=1e-8, rtol=1e-6):
                        fail("gripper", row, f"{side}: polarity/range/mapping")
                    gains[f"{side}:trigger"].append(trigger)
                    gains[f"{side}:gripper"].append(arm["gripper_aperture_m"])
                    gains[f"{side}:speed"].append(arm["translation_scale"])
                xr = row["xr"]
                if xr and xr[side]["raw"]["available"]:
                    counts[f"{side}:source_pose"] += 1
                    if not xr[side]["raw"]["tracking_valid"] and np.any(delta):
                        fail("tracking_loss", row, f"{side}: invalid source emits motion")
                if (previous and xr and previous["xr"] and tracked and arm["transition"] == "motion"
                    and previous["processed_action"][side]["tracking_valid"]
                    and row["reset_count"] == previous["reset_count"]
                    and row["session_epoch"] == previous["session_epoch"]
                    and not timing.get("duplicate_returned_result")):
                    p0, p1 = previous["xr"][side]["world"], xr[side]["world"]
                    if p0["pose_finite"] and p1["pose_finite"]:
                        source_delta = np.concatenate(controller_pose_delta_xyzw(p0["pose_xyzw"], p1["pose_xyzw"]))
                        target_delta = np.concatenate(controller_pose_delta_xyzw(
                            row["tcp_at_ik_world_xyzw"][side], row["targets"][side]))
                        for axis in range(6):
                            if abs(source_delta[axis]) > 1e-9:
                                source_gains[f"{side}:{axis}"].append(float(target_delta[axis] / source_delta[axis]))
            if previous and tracked and not previous["processed_action"][side]["tracking_valid"]:
                previous_target = np.asarray(previous["targets"][side][:3])
                target = np.asarray(row["targets"][side][:3])
                reacquisitions.append({"step": row["step"], "side": side,
                    "target_delta_m": float(np.linalg.norm(target - previous_target)),
                    "tcp_motion_m": float(np.linalg.norm(np.asarray(row["tcp_after_base_xyzw"]
                        [0 if side == "left" else 1][:3]) - np.asarray(row["tcp_before_base_xyzw"]
                        [0 if side == "left" else 1][:3]))),
                    "rebased": arm["rebased"], "acceptance": "METRIC RECORDED; HUMAN ACCEPTANCE REQUIRED"})
                if not arm["rebased"] or np.any(delta):
                    fail("tracking_reacquisition", row, f"{side}: first valid command not zero/rebased")
        previous = row

    both = all(counts[f"{s}:valid"] > 0 and counts[f"{s}:source_pose"] > 0 for s in ("left", "right"))
    def cover(key, sufficient, reason):
        checks[key] = {"status": "FAIL" if failures[key] else "PASS" if sufficient else "INSUFFICIENT",
                       "reason": reason, "violations": counts[f"violations:{key}"],
                       "failure_windows": failures[key]}

    axes_covered = {kind: both and all(motion_counts[f"{s}:{a}:{sign}"] for s in ("left", "right")
                    for a in axes for sign in ("positive", "negative"))
                    for kind, axes in (("translation", range(3)), ("rotation", range(3, 6)))}
    for kind in ("translation", "rotation"):
        for suffix in ("axes", "scale"):
            cover(f"{kind}_{suffix}", axes_covered[kind], "own retargeted delta -> processor; physical axes need human")
    cover("identity", both, "named graph channels observed; physical identity needs human")
    cover("tracking_valid", both, "valid source and processed samples from each hand")
    for key, transition in (("clutch_rebase", "clutch_release_rebased"), ("tracking_loss", "tracking_lost")):
        cover(key, all(transitions[f"{s}:{transition}"] > 0 for s in ("left", "right")), "each hand must exercise transition")
    cover("tracking_reacquisition", all(transitions[f"{s}:tracking_rebased"] >= 2 for s in ("left", "right")),
          "zero-intent rebase checked; no numerical physical jump limit declared")
    cover("gripper", both and all(gains[f"{s}:trigger"] and min(gains[f"{s}:trigger"]) < .1 and
          max(gains[f"{s}:trigger"]) > .9 for s in ("left", "right")), "per-sample configured linear polarity/range")
    cover("per_hand_speed", cfg["sensitivity_control_mode"] == "slider" and both and all(
        len(set(gains[f"{s}:speed"])) >= 3 for s in ("left", "right")),
        "configured per-hand scale mapping; canonical toggle cannot satisfy requested sliders")
    cover("cross_talk", both and all(isolated[s] > 0 for s in ("left", "right")),
          "zero own retargeted input yields zero intent in isolated opposite-arm windows; physical jitter needs human")
    cover("startup", both, "session plus physical tracked samples required")
    last_session = max(r["session_epoch"] for r in steps)
    reconnect_rebased = all(any(r["session_epoch"] == last_session and
        r["processed_action"][s]["transition"] == "tracking_rebased" for r in steps) for s in ("left", "right"))
    cover("reconnect", last_session >= 2 and reconnect_rebased,
          "session recreation and both-hand rebase observed; human must confirm no jump")
    cover("wrist_cameras", both, "valid advancing frames; optical identity/orientation need human")
    published = all(len(publication_counts[s]) >= 2 for s in ("left_wrist", "right_wrist", "scene"))
    cover("headset_preview", published, "publication progression only; headset visibility needs human")
    cover("preview_recursion", counts["preview_topology_samples"] == len(steps),
          "partition invariants only; pixel leakage and headset view need physical observation")
    last_epoch = max(reset_epochs)
    reset_recovered = all(any(r["reset_count"] == last_epoch and r["processed_action"][s]["transition"] == "motion"
                             for r in steps) for s in ("left", "right"))
    cover("reset", len(reset_epochs) >= 2 and reset_recovered, "reset epoch and subsequent motion on both arms")
    cover("shutdown", False, "requires outer launcher process outcome")
    cover("stale_duplicate", counts["pipeline_timing_samples"] > 0,
          "retargeting result IDs/age only; acquisition stale/duplicate counts unavailable; D0/R2 open")
    cover("cadence", len(steps) >= 2, "host duration/cadence metrics only; no latency acceptance threshold declared")
    cover("runtime_diagnostics", False, "requires complete stdout/stderr and process outcome")
    if any(r.get("event") == "runtime_error" for r in rows):
        checks["runtime_diagnostics"] = {"status": "FAIL", "reason": "structured runtime_error event"}
    metrics = {"steps": len(steps), "counts": dict(counts), "transitions": dict(transitions),
        "observed_processor_gain": {k: distribution(v) for k, v in gains.items()},
        "observed_source_to_target_gain": {k: distribution(v) | {
            "positive_sign_fraction": sum(x > 0 for x in v) / len(v)} for k, v in source_gains.items()},
        "gain_scope": "world-transformed consecutive source poses -> IK desired pose relative to current TCP; upstream smoothing/deadband retained; not executed TCP gain",
        "reacquisitions": reacquisitions, "reset_epochs": sorted(reset_epochs),
        "control_duration_ms": _distribution([r["control_duration_ms"] for r in steps]),
        "control_cadence_ms": _distribution([(b["control_step_timestamp_ns"] - a["control_step_timestamp_ns"]) / 1e6
                                              for a, b in zip(steps, steps[1:])]),
        "source_acquisition_age": None, "source_duplicate_count": None,
        "source_timing_note": "No source-owned timestamp; host receipt is not acquisition"}
    return checks, metrics


def verdict(human, checks, *, provenance_exact):
    answers = human.get("answers", {})
    h = "FAIL" if any(v.get("status") == "FAIL" for v in
        [*answers.values(), *human.get("scenario_answers", [])]) else (
        "PASS" if human.get("observer") and all(answers.get(k, {}).get("status") == "PASS"
                                                for k in HUMAN_ITEMS) else "NOT TESTED")
    statuses = [v["status"] for v in checks.values()]
    logs = "FAIL" if "FAIL" in statuses else "PASS" if statuses and all(s == "PASS" for s in statuses) else "INSUFFICIENT"
    contradictions = [key for key, check in checks.items() if check["status"] == "FAIL" and
                      any(v.get("status") == "PASS" and key.removesuffix("_axes") in k
                          for k, v in answers.items())]
    overall = "BLOCKED" if h == "FAIL" or logs == "FAIL" or contradictions else (
        "ACCEPT" if h == logs == "PASS" and provenance_exact else "INCOMPLETE")
    return {"HUMAN": h, "LOGS": logs, "S2": overall, "contradictions": contradictions,
            "provenance_exact": provenance_exact,
            "unclosed_criteria": [k for k, v in checks.items() if v["status"] != "PASS"]}


def check_directory(directory):
    parsed = False
    try:
        with (directory / "structured_runtime.jsonl").open() as stream:
            rows = []
            for index, line in enumerate(stream):
                if index >= 100000:
                    raise ValueError("journal exceeds bounded 100000-record analysis")
                rows.append(json.loads(line))
        checks, metrics = analyze(rows)
        parsed = "issue" not in metrics
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        checks = {k: {"status": "INSUFFICIENT", "reason": f"invalid/incomplete journal: {exc}"} for k in CRITERIA}
        metrics = {"parse_error": str(exc)}
    stdout = directory / "stdout.log"
    diagnostics: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    if stdout.exists():
        for number, line in enumerate(stdout.open(errors="replace"), 1):
            match = re.search(r"\[(Error|Warning|Fatal)\]|Traceback \(most recent", line, re.I)
            if match:
                severity = (match.group(1) or "Error").lower()
                diagnostics[severity] += 1
                if len(examples) < 30:
                    examples.append({"line": number, "text": line.strip()[:500]})
    metrics["diagnostics"] = {"counts": dict(diagnostics), "examples": examples,
                              "scope": "stdout/stderr text severity scan; not a complete vendor diagnostic schema"}
    process_path = directory / "process.json"
    process = json.loads(process_path.read_text()) if process_path.exists() else {}
    closed = parsed and any(r.get("event") == "runtime_loop_closed" and not r.get("failed") for r in locals().get("rows", []))
    checks["shutdown"] = {"status": "PASS" if closed and process.get("exit_code") in (0, 130) else "INSUFFICIENT",
                          "reason": "loop teardown and outer process exit both required"}
    checks["runtime_diagnostics"] = {"status": "FAIL" if diagnostics["error"] or diagnostics["fatal"] or
        process.get("exit_code", 0) not in (0, 130) else "INSUFFICIENT" if diagnostics["warning"] or not closed or not stdout.exists()
        else checks["runtime_diagnostics"]["status"] if checks["runtime_diagnostics"]["status"] == "FAIL" else "PASS",
        "reason": "warnings require explicit evidence review; errors block; no allowlist inferred"}
    human = json.loads((directory / "human_acceptance.json").read_text())
    manifest = json.loads((directory / "run_manifest.json").read_text())
    launch_path = directory / "runtime/launch_manifest.json"
    launch = json.loads(launch_path.read_text()) if launch_path.exists() else {}
    after_path = directory / "environment/provenance_after.json"
    after = json.loads(after_path.read_text()) if after_path.exists() else {}
    provenance_exact = bool(manifest.get("exact_unmodified_master") and manifest.get("physical_run_started")
        and after.get("exact_unmodified_master") and after.get("sha256") == manifest.get("sha256")
        and launch.get("project_sha") == manifest.get("expected_master")
        and launch.get("stack") == "isaac61" and not launch.get("dry_run", True)
        and launch.get("source_sha256") and all(manifest["sha256"].get(k) == v
            for k, v in launch["source_sha256"].items()))
    result = verdict(human, checks, provenance_exact=provenance_exact)
    result["blockers"] = manifest.get("blockers", []) + ([] if provenance_exact else ["exact physical runtime provenance not established"])
    write_json(directory / "automated_checks.json", checks)
    write_json(directory / "metrics.json", metrics)
    write_json(directory / "result.json", result)
    lines = ["# Physical S2 result", "", json.dumps(result, ensure_ascii=False),
             "", "## Human acceptance", ""]
    lines += [f"- {k}: {v.get('status', 'UNCERTAIN')} — {v.get('comment', '')}"
              for k, v in human.get("answers", {}).items()]
    lines += ["", "## Automated/log evidence", ""]
    lines += [f"- {k}: {v['status']} — {v.get('reason', '')}" for k, v in checks.items()]
    lines += ["", "Metrics: metrics.json. Failure windows: automated_checks.json.",
              "Human and log verdicts are independent. No D0/R2 acquisition-timing claim."]
    (directory / "report.md").write_text("\n".join(lines) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(json.dumps(check_directory(parser.parse_args().directory), indent=2))
