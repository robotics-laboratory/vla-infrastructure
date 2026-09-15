# Isaac XR fixes — 2026-09-15

Experimental `robosyn-vr-demo` branch. Canonical S1/D0 contracts and production gate states are unchanged. Implementation is split into three commits; the table records completed code checks separately from physical acceptance.

| Fix | Implementation | Saved validation | Physical status |
|---|---|---|---|
| 1. R3 coordinate frame | Current XR physical-to-world transform; synchronous upstream execution; hold across scheduled teleport; rebase after application; world-frame IK inputs | [01_recenter](xr_fixes/20260915/01_recenter/): 29 tests pass, 60-step Isaac smoke passes | Quest disconnected: no actual teleport/tracking; retest required |
| 2. Camera panel layout | Preserve physical size; layout at camera pixel resolution, supersampling 1 | [02_panels](xr_fixes/20260915/02_panels/): 30 tests pass, real Kit frame 640×551, 16-step smoke passes | Quest texture visibility retest required |
| 3. Preview overhead | Pending | Pending | Retest required |

## Upstream audit / integration size re-audit

CAPABILITY / GATE: experimental Isaac S2 teleoperation and camera preview; S2 remains unresolved pending human evidence.

PINNED UPSTREAM CANDIDATES: Isaac Lab `913ac53f51b2f8d02c9e121caa4cbdd06262948e` / package 16.4.0, Isaac Sim 6.0.1.0, IsaacTeleop 1.4.98rc1, isaaclab_teleop 0.8.0, CloudXR 6.2.1. Exact PIPER-X model remains Gate C's authoritative AGX revision.

WHAT UPSTREAM ALREADY OWNS: XR/CloudXR transport, teleport scheduling, controller acquisition, SE(3) retargeting/reset, differential IK, Replicator cameras, SceneUI panels, image providers and resource lifetime.

EXACT REMAINING GAP: Lab's pipelined results can straddle the asynchronous R3 navigation change; relative history must reset in the applied world frame. Panel UI units are meters despite pixel-sized child widgets. Preview uploads run at every render callback, including hidden and duplicate camera frames; the CPU sequence upload is expensive.

PROCESSOR / CONFIG / ADAPTER REQUIRED: extend the existing experiment-specific device and presentation adapters; configure upstream sync execution. No replacement solver, transport, recorder or camera implementation.

ENVIRONMENT IMPACT: unchanged Candidate B environment, dependencies and GPU requirements. Changes are confined to the demo navigation/presentation path. The existing >300 LOC modules have been re-audited; the added navigation logic delegates execution and pose processing to pinned upstream boundaries.

WHY NO PROJECT FRAMEWORK IS NEEDED: these are three local integration defects with known upstream entry points and explicit pins.

## Fix 1 details and limits

R3 no longer resets relative history immediately after merely scheduling a teleport. Motion stays held until the current HMD world pose reaches the scheduled viewpoint, then upstream resets history in sync mode. Missing/invalid active XR transforms cannot fall back to an authored anchor. A changed navigation transform also rebases on reconnect or other navigation. IK now uses world TCP pose alongside the world Jacobian and world Cartesian delta.

Tests exercise delayed application over multiple advances, a repeated teleport to the same pose, missing/invalid transforms and recovery, plus actual pinned SE(3) rightward deltas for both hands at four viewer yaws. The first failing test output is retained alongside the corrected passing output. The completion tolerances (5 cm / 0.1 rad) accommodate head motion; they are not acceptance tolerances. Excessive head movement before acknowledgment can keep motion held; see backlog.

The no-client XR smoke reports `passed: true`, 60 valid advancing RGB frames, and no authoritative geometry/contract changes. Its two R3 requests have `scheduled: false`; it does not validate a live teleport. OpenXR instance-loss messages occur during final runtime shutdown and are retained in the log.

## Fix 2 details and limits

The thin CPU presenter corrects `WidgetComponent.unit_to_pixel_scale` to camera width divided by panel world width, and sets texture supersampling to 1. Labels, source, physical dimensions, placement and upstream lifecycle remain intact. The sizing follows the [official WidgetComponent model](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.scene_view.xr_utils/1.0.2/WidgetComponent.html), checked against installed 1.0.1.

The live Kit probe now computes UI frame 640×551 rather than the prior 0.36×22, with a 640×551 texture on the unchanged 0.36×0.31 world-unit panel. It deliberately makes the panels visible through the demo visibility state, so subsequent updates cannot hide them again. Both feeds have nonuniform RGB and alpha 255. This repairs demonstrated layout overflow; it cannot prove headset sampling/texture visibility without a connected Quest. Two unrelated Python GPU processes were present during this run; the captured GPU context explains why its wall time should not be compared to an idle-machine benchmark.

## Sources and prior diagnosis

Navigation uses the [official XR spatial transform and scheduling model](https://docs.omniverse.nvidia.com/xr/omniverse-spatial-docs/109.0.3/development/core-concepts.html) and [IsaacTeleop execution modes](https://nvidia.github.io/IsaacTeleop/main/getting_started/teleop_session.html), checked against the pinned local implementation.

The [performance diagnosis](ISAAC_CAMERA_PERFORMANCE_20260915.md), [XR diagnosis and solution options](ISAAC_XR_FAILURES_AND_SOLUTIONS_20260915.md) and [hashed diagnostic artifacts](performance/20260915/manifest.json) retain the documentation, firsthand forum discussions, historical logs and controlled experiments. Measurements are control-loop timings without a headset, not measured Quest FPS.

## Required final report

GATE: NONE_EXPERIMENTAL; no acceptance claim.
REUSED: upstream device lifecycle, retargeters, XR teleport, IK, cameras and panels.
PINNED / VERIFIED: versions above; upstream source inspection, unit tests and bounded Isaac smoke.
EXECUTION PROFILE / ENVIRONMENT: experimental extension of `quest_xr_isaac`, Candidate B `/data/ebulochkin/envs/isaac-s1-candidate-b`; CUDA 4090.
CONTRACT CHANGES: none; experimental config documents sync and the navigation motion barrier.
EVIDENCE ADDED: experimental test/run results only, no registered human gate evidence.
ARTIFACTS ADDED: original diagnostic bundle and per-fix commands, logs, JSON results and SHA-256 manifests.
PROCESSORS / ADAPTERS: existing narrow Piper-X teleop and demo presentation adapters.
TESTS: see per-fix table and artifacts.
HUMAN EVIDENCE: user's observed R3 direction, gray panels and FPS collapse; no new physical verification.
BLOCKERS / REOPEN REASONS: physical Quest retest remains outstanding; see [backlog](ISAAC_XR_BACKLOG_20260915.md).
NEXT GATE: collect registered physical evidence before S2 acceptance.
