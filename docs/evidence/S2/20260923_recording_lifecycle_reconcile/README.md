# Recording lifecycle reconciliation assay

This frozen automated assay tests local `0cae8990159e978cd987a98402021931b5d6014a`
plus the exact changed source hashes in [summary.json](summary.json). It ports
remote `420acb6`, `0dce238` and `a6f14c3` onto the local performance/reset/telemetry
line. Native artifacts record the dirty checkout; they do not qualify an arbitrary
later commit. No physical Quest connection, robot motion, upload or push occurred.

## Scope and upstream audit

NVIDIA Isaac Lab 17.0.2 / Isaac Sim 6.1 / Kit 110.3 own physics, camera resources,
Episode Recorder storage, strict replay and XR. Existing project adapters own
causal admission and processor semantics. The remaining gap is episode ownership
inside the existing S2 loop: finalize storage, retain device/renderer/logger,
start a sibling recorder, and skip native apply for rejected RECORD decisions.
No dependency, environment, framework, format or profiler was added. The large
existing integration module was re-audited: this change adds only lifecycle
composition and the small upstream rejected-decision helper.

`prepare_recording_view()` hides the backdrop while retaining the local live-RGB
disable/invalidation and the recorder's dataset-only RenderProduct suspension.
Subsequent recorders retain the existing session logger's timing callback.
RUN/DIAG keep native control behavior; the remote motion-only D0 admission guard
also excludes their clutch/processor holds from prepared decision receipts.

## Native results

The external injected-device adapter ran the **production S2 RECORD loop**, real
processor, DifferentialIK, native apply, Fabric capture and NVIDIA HDF writer for
20 controls. CloudXR/device input alone was substituted; no actual CloudXR stream
was established. The test device exited only after control 20. Finalized segments:

| Episode | Rows | Boundary |
|---|---:|---|
| 000000 | 3 | operator_hold |
| 000001 | 2 | tracking_invalid |
| 000002 | 2 | control_reference_rebased |
| 000003 | 2 | causal_epoch_changed |
| 000004 | 3 | control_loop_completed |

Native application occurred only at ticks 2–4, 8–9, 12–13, 15–16 and 18–20.
Clutch engage/hold/release and tracking loss/recovery created no rows or native
writes; subsequent motion resumed. All 20 controls had four integrations,
F,F,F,T and one Kit pump. All dataset products remained disabled through every
closure/restart, with zero observed dataset drawable events. The external reset
probe after first recorder setup returned only `observation.state`, incremented
the reset epoch, and settled F×24,T with one pump; suspension persisted.

One performance stream retained all 20 steps, gaps included. Episode-open/snapshot
work is visible as long controls in this deliberately gap-heavy run (138.8 ms mean
for 20 controls); this is separate from the steady-state benchmark below and does
not establish smooth physical XR presentation across episode creation. Every episode has
independent episode-scoped observation/action/transition identities, terminal
successor, manifest and asset closure. Run/session grouping is intentionally shared,
as in Blackfire's convention; no continuity is asserted across episodes.

All five episodes independently passed strict replay, zero physics callbacks,
three-camera offline rendering (36 RGB frames total), LeRobot v3 materialization,
and full dataset/video/DataLoader read (12 rows / 36 decoded frames total).
These small injected, operator-stopped artifacts are validation data, not admitted
human demonstrations or [[gate:D1]] evidence.

## Performance regression

Three no-client runs used 30 warmup + 300 measured controls, flush interval 64,
the existing S2 logger and the same external native counters as the retained local
candidate. Each confirmed four integrations, F,F,F,T, one pump and zero dataset
drawable events. Rates were 41.8811, 41.5897 and 41.8330 Hz. Pooled mean was
23.9420 ms/control (41.7676 Hz), versus retained 24.0846 ms / 41.5204 Hz:
approximately −0.1426 ms and +0.60% Hz. This catches no obvious regression; runs
at different times do not establish exact parity or physical performance.
The original retained comparison is
`/tmp/recording-reset-telemetry-validation/performance-comparison.json`; the raw
archive retains its compact candidate statistics and original run locators.

## Checks and limitations

Focused tests passed (208 tests); full core passed (601 tests, 26 skipped, four
subtests). Ruff lint/format, documentation with trusted-base preservation,
contract/spec and selective-manifest checks passed. Logs are retained in the raw archive.
Mypy was compared per changed runtime module against a `git archive` of `0cae899`:
15 existing errors across four modules, zero new errors. Existing errors concern
SDK/import and array/object typing; no suppression or unrelated fix was added.

Initial CPU attempts encountered missing workspace-package search paths, read-only
Hugging Face caches and sandbox-blocked local sockets. The successful rerun used
the declared core environment, local package source, writable cache and host socket
access, without installing dependencies. Replay rejects the historical `--smoke`
example; additionally, a custom `--replay-report` leaves the launcher's default
result absent, producing exit 1 despite successful replay. The final five replay
runs use current syntax and the default report, all exit 0. Failed attempts are
retained, and these pre-existing CLI issues remain outside this lifecycle change.

Core Python:
`/data/vla-infrastructure/core-reconcile-validation/20260919T082843.713211Z/env/bin/python`.
Native/extractor Python:
`/data/vla-infrastructure/isaac61_production/env/bin/python`.
Commands, source copies, injected driver/observer hashes, run manifests, per-control
mechanisms, JSONL timing, replay/materialization commands and validation logs are
retained in
`/data/ebulochkin/vla-runtime/evidence/20260923_recording_lifecycle_reconcile/validation.tar.gz`.
Bulk HDF/RGB/video artifacts remain at the exact private runtime locators in
[summary.json](summary.json). The two repository files and external archive are
registered artifacts under one command-test evidence record. No gate binding or
acceptance was added; selective MANIFEST membership is unchanged.

## Physical follow-up

The operator reported 191 committed rows followed by `control_reference_rebased`,
teleop teardown, XR disabled, and Quest `0xF22300`. This assay verifies that the
recorder no longer exits the S2 loop at those injected gaps; it cannot verify
physical stream persistence or fix general codec/network errors. Physical Quest
retest must check clutch/release/rebase, resumed arm motion, persistent stream,
sibling episodes and continuous telemetry, using the maintained
[operator command](../../../project/RUN_VR_OPERATIONS.md).

VRR-070 remains in progress, VRR-080 blocked, VRR-100/101 in progress;
[[gate:S2]] and [[gate:D1]] remain unresolved. Explicit environment reset still
ends RECORD at its existing boundary; full operator start/stop/reset UX is pending.
