"""Acceptance must fail closed on missing, contradictory or corrupted evidence."""
from copy import deepcopy
from dataclasses import asdict
import json
from types import SimpleNamespace

import numpy as np
import pytest

from tools.check_physical_s2 import CRITERIA, HUMAN_ITEMS, analyze, check_directory, verdict, write_json
from tools.isaac_s2_acceptance_log import S2AcceptanceLog, plain
from tools.isaac_s2_processor import BimanualS2TeleopProcessor, S2ProcessorConfig, unpack_pipeline_action


def journal():
    cfg = S2ProcessorConfig()
    processor = BimanualS2TeleopProcessor(cfg)
    raw = [0.01, 0, 0, 0, 0, 0, 1, 1, 0, .5, 0] * 2
    rows = [dict(event="runtime_start", run_id="test", processor_config=asdict(cfg))]
    for step in (1, 2):
        command = plain(processor.advance(*unpack_pipeline_action(raw)))
        pose = [step * .01, 0, 0, 0, 0, 0, 1]
        sample = dict(available=True, tracking_valid=True, pose_finite=True, pose_xyzw=pose)
        rows.append(dict(event="control_step", run_id="test", step=step, monotonic_ns=step * 33000000,
            control_step_timestamp_ns=step * 33000000, raw_teleop_action=raw.copy(), processed_action=command,
            reset_count=0, retargeting={"returned_frame_id": step}, session_epoch=1,
            cameras=dict(valid=True, strictly_advanced=True), preview=None,
            scenario={"name": "NEUTRAL"}, deadline_missed=False, control_duration_ms=30,
            xr={s: {"raw": sample, "world": sample} for s in ("left", "right")},
            applied_native_targets={s: [0.] * 6 + [command[s]["gripper_aperture_m"]] for s in ("left", "right")},
            targets={s: pose for s in ("left", "right")}, tcp_before_base_xyzw=[pose, pose],
            tcp_after_base_xyzw=[pose, pose], tcp_at_ik_world_xyzw={s: pose for s in ("left", "right")}))
    for row in rows:
        row["schema"] = "physical_s2_journal_v1"
    return rows


def test_nominal_incomplete_does_not_infer_physical_acceptance():
    checks, metrics = analyze(journal())
    assert checks["identity"]["status"] == "PASS"
    assert checks["per_hand_speed"]["status"] == "INSUFFICIENT"
    assert metrics["observed_processor_gain"]["left:0"]["mean"] == 2
    assert metrics["source_acquisition_age"] is None
    assert verdict({}, checks, provenance_exact=True)["S2"] == "INCOMPLETE"


@pytest.mark.parametrize("kind", ["invalid_motion", "wrong_gain", "wrong_gripper", "cross_talk"])
def test_corrupted_mapping_is_detected(kind):
    rows = journal()
    arm = rows[-1]["processed_action"]["left"]
    expected = "tracking_loss"
    if kind == "invalid_motion":
        arm["tracking_valid"] = False
    elif kind == "wrong_gain":
        # Both reported scale and output are wrong; config remains authoritative.
        arm["translation_scale"] = 4
        arm["delta_pose"][0] = .04
        expected = "translation_scale"
    elif kind == "wrong_gripper":
        arm["gripper_aperture_m"] = .1
        expected = "gripper"
    else:
        rows[-1]["raw_teleop_action"][0] = 0
        expected = "cross_talk"
    checks, _ = analyze(rows)
    assert checks[expected]["status"] == "FAIL"
    assert checks[expected]["failure_windows"][0]["step"] == 2


def test_human_and_logs_are_independent_and_failures_persist():
    all_pass = {k: {"status": "PASS"} for k in CRITERIA}
    human = {"observer": "tester", "answers": {k: {"status": "PASS"} for k in HUMAN_ITEMS}}
    assert verdict({}, all_pass, provenance_exact=True)["HUMAN"] == "NOT TESTED"
    assert verdict(human, all_pass, provenance_exact=False)["S2"] == "INCOMPLETE"
    assert verdict(human, all_pass, provenance_exact=True)["S2"] == "ACCEPT"
    all_pass["cross_talk"]["status"] = "FAIL"
    report = verdict(human, all_pass, provenance_exact=True)
    assert report["HUMAN"] == "PASS" and report["LOGS"] == "FAIL"
    assert report["S2"] == "BLOCKED" and report["contradictions"] == ["cross_talk"]
    human["scenario_answers"] = [{"status": "FAIL", "comment": "jump"}]
    assert verdict(human, all_pass, provenance_exact=True)["HUMAN"] == "FAIL"


def test_truncated_journal_and_missing_runtime_never_pass(tmp_path):
    write_json(tmp_path / "human_acceptance.json", {})
    write_json(tmp_path / "run_manifest.json", {})
    (tmp_path / "structured_runtime.jsonl").write_text('{"event":')
    result = check_directory(tmp_path)
    assert result["LOGS"] == "INSUFFICIENT"
    assert result["S2"] == "INCOMPLETE"
    assert "parse_error" in json.loads((tmp_path / "metrics.json").read_text())


def test_failed_advance_does_not_relabel_old_source_as_new(tmp_path):
    log = S2AcceptanceLog(tmp_path, config={}, processor_config={}, versions={})
    log.begin(1)
    device = SimpleNamespace(session_running=False, _session_lifecycle=SimpleNamespace(
        _session=None, last_step_result={"old": "must not be read"}))
    log.observe(device, None)
    assert log.source is None
    assert log.receipt_ns > 0
    log.close(interrupted=True, failed=False)
    with pytest.raises(FileExistsError):
        S2AcceptanceLog(tmp_path, config={}, processor_config={}, versions={})
    assert plain(np.array([float("nan")])) == [None]


def test_missing_steps_are_not_silently_accepted():
    rows = journal()
    rows[-1]["step"] = 10
    checks, _ = analyze(rows)
    assert checks["runtime_diagnostics"]["status"] == "FAIL"


def test_mutating_one_hand_cannot_hide_in_other_hand_stats():
    rows = journal()
    original = deepcopy(rows)
    rows[-1]["processed_action"]["right"]["delta_pose"][0] = -.02
    checks, metrics = analyze(rows)
    assert checks["translation_axes"]["status"] == "FAIL"
    assert metrics["observed_processor_gain"]["left:0"] == analyze(original)[1]["observed_processor_gain"]["left:0"]


def test_runner_refuses_blocked_preflight_before_launch(tmp_path, monkeypatch):
    from tools import physical_s2_acceptance as runner
    write_json(tmp_path / "run_manifest.json", {
        "expected_master": "6430dc1", "blockers": ["sliders vs toggle"],
        "physical_run_started": False})
    monkeypatch.setattr(runner, "provenance", lambda expected: {"exact_unmodified_master": True})
    def forbidden(*args, **kwargs):
        pytest.fail("must not launch or ask human answers for blocked preflight")
    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    monkeypatch.setattr("builtins.input", forbidden)
    with pytest.raises(RuntimeError, match="Preflight blocked"):
        runner.run(tmp_path)


def test_journal_persists_step_targets_and_host_only_clock(tmp_path):
    cfg = S2ProcessorConfig()
    log = S2AcceptanceLog(tmp_path, config={}, processor_config=cfg, versions={})
    processor = BimanualS2TeleopProcessor(cfg)
    raw = np.array([.01, 0, 0, 0, 0, 0, 1, 1, 0, .5, 0] * 2)
    pose = np.array([0, 0, 0, 0, 0, 0, 1])
    device = SimpleNamespace(session_running=False, _session_lifecycle=SimpleNamespace(_session=None))
    log.begin(1)
    log.observe(device, None)
    ik = SimpleNamespace(acceptance_targets=dict(left=pose, right=pose),
        acceptance_native=dict(left=np.zeros(7), right=np.zeros(7)),
        acceptance_tcp_world=dict(left=pose, right=pose))
    log.end(action=raw, command=processor.advance(*unpack_pipeline_action(raw)), before=[pose, pose],
        after=[pose, pose], ik=ik, camera=dict(valid=True, strictly_advanced=True),
        env=SimpleNamespace(), device=device)
    log.close(interrupted=True, failed=False)
    rows = [json.loads(line) for line in (tmp_path / "structured_runtime.jsonl").read_text().splitlines()]
    step = next(row for row in rows if row["event"] == "control_step")
    assert step["host_receipt_timestamp_ns"] > step["control_step_timestamp_ns"]
    assert step["processed_action"]["left"]["rebased"]
    assert step["targets"]["left"] == pose.tolist()
    assert step["xr"] is None
    assert "source_timestamp" not in step
