# D0 temporal recording integration — 2026-09-17

## Capability / gate

Gate D0 temporal semantics at the production LeRobot frame-write boundary. This work
does not accept D1, R2, or any physical Quest/hardware gate.

## Pinned upstream candidates

- LeRobot 0.6.1 at `7e241bd630a3719a56157a497ce5d08f244784f1`.
- `lerobot.scripts.lerobot_record.record_loop` and `LeRobotDataset` v3.
- PIPER SDK 0.6.1 CAN feedback timestamps.
- Isaac Lab release/3.0.0 native recorder lifecycle, if a D1 artifact is later enabled.

## What upstream already owns

LeRobot owns observation/action processors, same-tick label construction, robot
actuation, pacing, episode lifecycle, logical `frame_index / fps` timestamps, image
storage, and dataset finalization. Isaac owns its native recorder lifecycle. No project
dataset format or general recorder is introduced.

## Exact remaining gap

The upstream LeRobot frame did not carry acquisition identity for joint state, wrist
cameras, XR poses, or source action. PIPER CAN payloads have no device timestamp;
python-can exposes a kernel SocketCAN receive timestamp in wall-clock time. Standard
LeRobot camera buffers expose host read/decode timing, not a guaranteed physical
capture timestamp, and the existing Quest diagnostic exposes only host receipt time.
The previous helper was not passed to the real upstream `record_loop` and validated too
late, after the robot action had already been sent.

## Processor / config / adapter required

- `TemporalLeRobotDatasetAdapter` is passed as the dataset object to the unmodified
  upstream loop. The paired teleoperator validates and freezes the exact source bundle
  before it returns the action and therefore before upstream can call
  `Robot.send_action`; `add_frame` only commits that prepared enrichment.
- `BiPiperXFollower` exposes the acquisition timing produced by the same
  `get_observation` call. The adapter captures and atomically copies all three PIPER
  joint-pair frames plus gripper feedback, selects their oldest SocketCAN receive time,
  and converts the wall clock to host monotonic. Every temporal observation rechecks
  the wall-to-monotonic offset and fails closed if calibration uncertainty or drift
  exceeds the configured 5 ms budget.
- A recording camera must atomically return a `CameraAcquisitionSample` from its own
  backend. Receipt/read/decode/postprocess timestamps and inspection of LeRobot private
  camera buffers are rejected.
- `TimestampedTeleoperator` stamps the newly created source action. Human-VR mode uses
  one atomic reader for action plus the exact source-owned left/right XR identities and
  fails fast without it.
- Repeated identities are never reused. An invalid bundle increments QA and aborts the
  current record loop before actuation; episode clear/discard remains caller-owned.
- Episode save/clear resets validator history. QA counters remain cumulative.

## Recording entrypoint audit

| Path | Result |
|---|---|
| LeRobot dataset recording | Integrated and exercised through the real upstream `record_loop` and real `LeRobotDataset` writer. |
| Real PIPER-X observation recording | Joint/gripper component timing is implemented. A selected camera backend must still implement source-owned `async_read_with_acquisition_timing`; otherwise recording fails closed rather than stamping a buffered frame as fresh. |
| VR/teleop recording | Source-action timing is integrated. One atomic action/XR reader must return both pose identities; current receipt-only Quest diagnostics cannot start a human-VR recording. |
| Isaac artifact to canonical dataset | No converter/recording entrypoint exists in this revision (`isaac_dataset_convert.command` and converter fields remain unresolved), so no fictitious integration was added. The same dataset adapter is the required canonical-write seam when D1 implements conversion. |

## Bounded profile and limit basis

The selected profile is 30 Hz dataset/XR/camera/control/policy/command with 120 Hz
Isaac physics and interpolation multiplier 1 (no interpolated intermediate command).
Rates are separately declared and are not globally forced equal. For this duplicate-free
live path, however, a configured required camera rate below dataset FPS is rejected at
construction; faster camera rates remain valid.

- 30 Hz source period: 33.333 ms.
- 120 Hz physics period: 8.333 ms.
- Accepted optimized Isaac measurement
  `piper_camera_xr_raw_cpu_upload_render_once_timings.json`: 35.662 ms mean bounded
  advance, 0.527 ms camera update, 0.376 ms observation copy, and 1.500 ms camera
  validation across 55 measured advance calls.
- Camera/XR/skew limit: 75 ms. This covers two 30 Hz source periods plus one 120 Hz
  physics period (`66.667 + 8.333`) and exceeds the measured optimized advance plus one
  source period (`35.662 + 33.333 = 68.995 ms`).
- Joint/source-action limit: 45 ms. This covers one 30 Hz control period plus one
  physics period (`41.667 ms`) with 3.333 ms explicit rounding margin.

The slower historical preview modes (85.568–193.885 ms mean advance) intentionally
fail this production envelope; they are performance evidence, not permission to record
stale BC pairs.

## Environment impact

Core environment only; the local PIPER-X package and lock entry move from 0.2.1 to
0.2.2 with no external dependency change. Isaac and Quest environments are not merged.
The exact physical camera and Quest acquisition-timestamp behavior remains unverified
because those devices were not available for this change.

## Why no project framework is needed

The project code is one validation/provenance proxy plus source-specific timing
side-channels. All recording and storage behavior remains upstream-owned.

## Physical follow-up

Before R2/D1 human-VR recording, the selected wrist-camera backend must implement the
source-owned acquisition API and the selected XR provider must expose one atomic
action/pose sample with acquisition sequence and timestamp in host monotonic time or a
recorded conversion to it. Then run a connected camera/Quest/PIPER capture and
demonstrate state, image, pose, and action ages plus cross-modal skew stay within their
limits. Receipt timestamp fallback for camera/XR is forbidden.
