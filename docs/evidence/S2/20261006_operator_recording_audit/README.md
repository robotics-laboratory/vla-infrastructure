# Operator recording and S2 readiness audit

Frozen read-only audit of the operator's 2026-10-06 RUN/RECORD sessions. The
saved demonstration was recorded on clean `f2ac4ea` / `codex/vr-recording-ui`.
The earlier RUN at `516978b` retains its own source identity. Exact launch
manifests, configs, results, logs, disposition files, hashes and executed audit
script are retained in [checks.json](checks.json). The completed RECORD log is
also retained byte-for-byte as [record_stdout.log](record_stdout.log).

| Attempt in the RECORD session | Rows | Disposition | Audit |
|---|---:|---|---|
| `d8afd25f…` | 1281 | Reset aborted; subsequently discarded | Non-finalized source correctly rejected |
| `4cb3c310…` | 304 | Stop then Discard | Finalized artifact/session checks pass; discard retained |
| `e7847a6c…` | 836 | Stop, Save, operator success | Finalized artifact/session checks pass |

The native pinned Episode Recorder `SessionReader` reads closed HDF files only.
Its filesystem modules are loaded without extension UI/Kit startup; the existing
Kit `libcarb` directory resolves its native import. There is no simulator, camera
render, CloudXR takeover or real robot command in the audit. No dependency or SDK
bytes changed. An initial missing-library setup failure is retained in checks.
The production `verify_recording_artifact` and `_validate_session` check HDF,
stage/asset closure, visual provenance, dense canonical transition identities,
successor continuity and the terminal successor. The capture's existing hash
function additionally verifies all 836 saved observation snapshots against the
HDF scene-state tracks. The discarded finalized episode also passes all 304.

For the saved demonstration, all 836 rows have valid tracking and finite native
state/action. Each successor advances physics by exactly four steps. All three
recorded ZED optics declare 960x600; source metadata records `live_rgb: false`.
This audit does not independently inspect a running stage's render-product
inventory or establish headset pixel visibility. Twenty-three saved rows have
native saturation (2.75%); this records command limitation, not observed jumps.
The saved index's `task_outcome: success` is the operator's classification. All
native D0 `success` rows are false; no automatic task-success result is inferred.
The finalized source still declares `dataset_admissible: false`. No offline RGB,
LeRobot conversion or dataset admission was performed.

The final `f2ac4ea` RUN has 1355 valid/advanced camera boundaries and 1088 tracked
frames per side. Mean host control frequency is 16.49 Hz over the whole session;
its 116 saturated frames are retained. RECORD has 9636 control ticks, 3779 tracked
frames per side and mean host control frequency 26.96 Hz. These are whole-session
host-loop averages, including waiting; they are not measured headset stream FPS
or stage-specific recording performance. All retained launches explicitly require
physical tracking and use the expected pinned environment. Both `f2ac4ea` RUN
and RECORD manifest source/config hashes match the audited checkout. The
`516978b` RUN naturally differs in the later wall-position configuration.

All three sessions report clean SIGINT shutdown / exit 130. They are intentionally
`passed: false` after interruption before their requested 18000 control ticks.
A native lifecycle can close cleanly while the bounded runtime acceptance predicate
fails; no result was rewritten. RECORD includes a pre-session form-factor error
and a shutdown `xrWaitFrame` validation error, followed by the retained clean
launcher result. No Python traceback is present in these retained logs.

S2 stays unresolved. The operator stated that the full physical checklist was
exercised, but detailed results, headset identity and observer identity were not
yet supplied when this audit was frozen. There is no new human PASS evidence.
The [current worksheet](../../../project/GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md)
now follows the canonical three-camera roles, L3 placements and FPS observation;
the obsolete claim that SCENE was only a noncanonical preview is removed.
Completion still needs the exact RUN composition's runtime PASS, the required
physical observations and registered human evidence. Current rules are owned by
[the S2 gate definition](../../../GATE_SPEC.md) and
[gate rules](../../../../configs/gate_rules.yaml). This audit is supplemental
artifact evidence, not S2 acceptance or a replacement for RUN's preview checks.
