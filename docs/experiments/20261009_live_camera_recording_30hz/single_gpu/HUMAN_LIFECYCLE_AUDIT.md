# Human lifecycle integration — exact minimal seams, not yet a ready human runner

Audit of current WIP on 2026-10-09. No shared source edited during this subtask; no GPU runs. The source04 actual-scene physics/initial-state/J parity PASS is parent-provided evidence, not a human lifecycle test.

The existing run_s2 loop can own every human DeviceIO receipt, processor decision, upstream IK call and canonical recorder transaction. Do not copy the loop or patch module-global run_s2/start_live_recording. A small explicit optional argument `single_gpu_hooks=None` on run_s2 plus three calls suffices for normal flow; failure/reset handling adds two explicit boundaries. A new human runner cannot honestly be enabled with the CURRENT media/reset interfaces: source reset still rejects, media construction blocks the Kit thread, and persisted source verification assumes injected contiguous observations. Therefore this note proposes exact changes instead of creating an unwired file that would imply readiness.

## 1. Lifetime and startup

Wrapper launcher/context creates a concrete SingleGpuHuman owner, passes it to the EXISTING run_s2 and closes it in finally. Cleanup must cover exceptions before run_s2's own main try (current initial reset occurs earlier). No module-global monkeypatches, no background Kit/PXR calls.

Insertion in `tools/isaac_s2_runtime.py` immediately after initial `env.reset(0)` and before first action acquisition:

    if single_gpu_hooks is not None:
        single_gpu_hooks.after_initial_reset(env)

That method calls prepare_recording_view, exports an immutable bootstrap USD using existing upstream export_stage_snapshot, then starts StandaloneState from that exact native boundary. Bootstrap export goes outside any claimed human technical episode. Do not manufacture an empty first recorder episode merely to obtain a stage file. Current native initial reset/settling must happen BEFORE the source clock freeze. The original device and IK objects remain in use; the existing dynamic standalone_state branch supplies IK data.

Restrict first human candidate to actual XR + teleop + RECORD mode, with an explicit diagnostic execution selection. Do not infer active Quest from --xr. Keep source/dependency/worker hashes and physical qualification false until measured. Current start_live_recording automatically reads env.standalone_state and already registers ValidationProbe, external time and pose batch.

## 2. Per-technical-episode media startup

Current open path is `run_s2` around lines950–1020: start_live_recording/RecordingSession or recording_session.start_episode, then capture_observation. Insert hook after BOTH branches and BEFORE the first capture:

    if single_gpu_hooks is not None:
        single_gpu_hooks.open_episode(recording)
        processor.session_inactive()
        # Explicit startup interruption/rebase receipt; discard the previously
        # acquired action, do not solve/apply its stale XR packet after startup.
        completed_control_steps = step
        continue

On the following iteration the existing top-of-loop recording.capture_observation runs and a NEW device.advance receipt drives the decision. Record startup/rebase as a non-admitted boundary. Do not reuse pre-startup observation/XR/command merely because validation objects still compare equal.

Reuse the CURRENT media construction from run_single_gpu_live_recording.benchmark: move its ~35 lines into a concrete helper called by both benchmark and human coordinator. It produces preimage guards, representative immutable warmup payload from the same external source snapshot, then LiveMirror(record, capacity=8, worker=isaac_vr_live_worker.py, extra_seed.single_gpu=...). No new media protocol/encoder is needed for a bounded experiment.

However LiveMirror.__init__ currently waits synchronously up to180s for shaders/assets/representative rendering. Ordinary Quest human flow cannot freeze its Kit app during every startup. Add one explicit optional `idle_pump` callback to LiveMirror's receive wait and poll at <=10–20ms; callback is executed synchronously on the owning Kit thread and calls a new StandaloneState.present_only method (publishes current immutable poses + PassiveKitView.update, never physics step/recorder sample). Do not call device.advance from this wait, as that would silently consume input generations outside run_s2. If upstream requires DeviceIO polling while initial media startup occurs, make this an explicit pre-admission state in the shared loop instead of burying it in a callback.

This wait-pump is required also during drain/CPU decode after Y or tracking gaps: retain XR presentation while admission is closed. A constructor worker plus callback is not a background Kit thread. If such pumping still interferes with CloudXR lifecycle, next solution is persistent OVRTX worker with explicit begin/end episode; current worker supports only one episode and stop, so persistent rotation is not an existing free switch.

Repeated tracking/clutch technical gaps currently finalize an episode and later open a fresh one while keeping RecordingSession alive. Restarting the expensive renderer for each short gap can dominate usability even if steady-state Hz passes. Count gap frequency/startup latency in the human experiment; do not hide those timings from whole-session throughput.

## 3. Drain before seal, including failures

Current `finalize_recording` around line528 must call `single_gpu_hooks.finish_episode(active)` BEFORE `recording_session.end_episode`. It must not leave a media failure classified operator_stopped:

    media_error = None
    try:
        if single_gpu_hooks is not None:
            single_gpu_hooks.finish_episode(active)
    except Exception as exc:
        media_error = exc
        outcome, reason = 'failure', f'live_media_failed:{type(exc).__name__}:{exc}'
    try:
        recording_session.end_episode(outcome=outcome, reason=reason)
    finally:
        recording = None
    if media_error is not None:
        raise media_error

Place summary construction AFTER outcome adjustment (current summary precedes end_episode). Finish joins pending source submissions, drains ALL three encoders, validates tail/optical evidence as configured, restores only that LiveRecording instance's capture observer, writes per-episode media receipt. On error abort only the session-owned worker and mark failure. Never let the recording finalizer background thread own GPU/Kit operations.

The outer run_s2 finally fallback `recording.close` when recording_session is None must also finish/abort media first. `RecordingSession.close` can call end_episode directly: ensure every active media episode is finalized by the explicit hook before this fallback, or add a narrow before-seal callback at RecordingSession.end_episode as the sole authoritative boundary. Prefer the latter if tests show an uncovered failure path. Do not scatter different copies of media teardown among normal/reset/interrupt paths.

## 4. Reset and epochs

`RecordingLifecycle` already seals the demo/session before invoking reset_demo for save/discard/external reset. Current reset_demo does env.reset, processor.reset, ik.reset, camera_guard.reset, device.reset(pause=False). Preserve this ordering and original callbacks.

Root-owned StandaloneState must replace reject_reset with a concrete restart-from-INITIAL-seed operation. It must NOT call build_seed(env,...) after external motion: the native Kit engine is frozen and its q/poses are stale. Save original seed/native initial state and boot the fresh worker from those bytes into a new output epoch directory. Source root/world/drive/mimic hashes remain identical; increment/reset authoritative camera+source epoch atomically before any next observation. Reset current target/seq/clock/snapshot/IK caches and publish initial mirror poses. env._state_physics_step and clock.physics_step must agree, and actual frozen Kit counter must remain unchanged. The current SourceClock constructor hardcodes initial epoch only in old code; use camera.reset_epoch.

A new technical episode after a mere tracking gap is NOT a physics reset: it reuses the current external owner, and only media/source capture sequence restarts. A new demo after env.reset gets a new source epoch and fresh media. Session sampler currently captures the owner object in pose_batch; closing the old RecordingSession before swapping owner is essential. Alternatively restart worker inside the same owner instance so existing closures remain valid; never retain a sampler closure pointing to a closed old worker by accident.

## 5. Source/media join and witness limitations specific to human input

The current deep_research/verify_live_source.py assumes `rows[i]` equals HDF committed row i. Human recording can capture then discard an observation at a tracking/clutch/reset boundary. LiveMirror observes `_capture_new_observation`, so those discarded observations can already be in videos. This is expected under the current observer placement; an ordinal counter alone does not make them committed training frames.

Before promoting human recording, generalize verification to join each HDF `observation_capture_sequence` to `worker-rows.source_id` (unique dictionary with duplicate rejection), then compare snapshot ID/hash + matrices. Record unmatched rendered rows as explicit rejected/terminal source observations. Do not silently drop them from the count or claim video ordinal==dataset row. Final successor is separately rendered; all three camera streams retain their own complete ordered source ledger. Parameterize manifest/HDF/media paths rather than creating misleading symlinks to satisfy the injected script's hardcoded `episode/` and `mirror/` layout.

Optical witness supports only4096 distinct capture IDs/technical episode. A first human diagnostic must be explicitly bounded below that limit (including discarded observations and terminal successor), or widen the witness protocol. Witness=False supports longer captures but removes independent pixel source proof; metadata-only success must not be reported as equivalent qualification. Boards also alter diagnostic camera pixels; they are not production training imagery.

## Assessment and smallest proof sequence

The shared loop reuse is feasible. The added code is a source/media lifecycle coordinator plus ~20–35 lines of explicit loop hooks, and small reusable wait-pump/verification changes. It is not safe to claim current benchmark script is a human-ready runner, nor to install global monkeypatches to bypass the missing hooks. A new `isaac_vr_single_gpu_human.py` should be added when these concrete contracts exist, not as a dead wrapper requiring undocumented patches.

Required CPU tests before human launch: startup failure cleanup; two technical episodes in one demo reuse source owner; media failure seals failure; exception before RecordingSession creation; discard/reset new epoch with stale sampler rejection; reconnect startup does not reuse old XR packet; gap-rendered rows joined by source sequence;4096-boundary behavior. Then root performs same single-GPU full media loop and active physical Quest qualification. Physics-only/initial-parity PASS and no-media38Hz do not establish the requested >30 physical activeQuest action+three-camera result.
