# Isaac XR backlog — 2026-09-15

| ID | Status | Work / acceptance evidence |
|---|---|---|
| XR-01 | Implemented; physical retest pending | R3: after each of 0°, 90°, 180° and −90° viewer yaw, test both arms' right/forward/up directions, repeated R3, tracking loss/reconnect and no robot jump. Preserve timestamped navigation events and register human evidence for S2. Unit tests + no-client smoke are in `xr_fixes/20260915/01_recenter/`. |
| XR-02 | In progress | Repair SceneUI pixel layout; show both live wrist feeds in Quest. Save headset screenshot/video and corresponding camera/frame/provider metadata. A no-client geometry probe cannot establish headset texture visibility. |
| XR-03 | Pending | Eliminate CPU sequence conversion, hidden preview work and duplicate frame uploads; preserve 640×480 RGB 30 Hz and renderer/physics cadence. Save matched before/after timings and counters. |
| XR-04 | Physical retest pending | R3 completion under large head motion: current acknowledgment tolerance is 5 cm / 0.1 rad. If motion remains held, inspect actual HMD/view matrices and SDK application timing; use an upstream completion signal if one becomes public. No timeout may silently resume a stale frame. |
| XR-05 | Deferred | If layout repair leaves gray panels, qualify a pinned supported DynamicTextureProvider/RTX world-quad presentation or native OpenXR compositor layer. Do not upgrade CloudXR/IsaacTeleop without environment requalification. |
| XR-06 | Deferred | Active Replicator render products remain expensive independently of preview visibility. Evaluate supported render-product scheduling / tiled cameras only after preserving headset update cadence and avoiding warmup flicker. Do not equate lower camera `update_period` with fewer RTX renders. |
| XR-07 | Physical benchmark pending | Reproduce the user's camera-off/on FPS in the same scene and Quest session, recording renderer/encoder/frame interval and control/pose rates separately. Existing 70/10 observation is not a controlled archived ablation. |

No canonical contract or gate is accepted by this experiment. Save new evidence alongside the fix artifacts and update statuses when the checks actually run.
