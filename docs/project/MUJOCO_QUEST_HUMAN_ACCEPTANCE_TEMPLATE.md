# MuJoCo Quest teleoperation physical acceptance worksheet

Status: template only. It is not evidence while any required line is blank.

This worksheet validates the additive `piperx_mujoco_quest_teleop_v39` profile and the reopened M1 v28 gripper plant.
It does not accept E2 and must not use a real PIPER/CAN
interface.

## Start

Install the already locked optional group once:

```bash
uv sync --frozen --group isaac-teleop
```

Start the bounded physical run:

```bash
uv run --frozen --no-sync --group isaac-teleop \
  python tools/run_mujoco_quest.py \
  --max-control-steps 1800 \
  --require-tracking \
  --accept-cloudxr-eula
```

Open `https://nvidia.github.io/IsaacTeleop/client/v1.3.131/` in Quest 3. If the browser
rejects the self-signed host certificate, first open the certificate URL printed
as the `certificate` field by the launcher and accept it, then connect to the
printed host IPv4 address.

Wake both physical controllers and keep them visible before pressing Play. With
`--require-tracking`, v39 keeps MuJoCo at home until both grip poses are valid,
rebases both controllers before the first command, and exits with the missing
controller name after 10 seconds instead of permitting a misleading one-arm run.

If CloudXR is already managed in another terminal, add
`--no-auto-launch-cloudxr`; there must still be exactly one CloudXR lifecycle.

## Session metadata

- Observer:
- Local start/end time:
- Quest device:
- Host/GPU:
- Command:
- Captured stdout path and SHA-256:
- Confirm no CAN or physical PIPER process was opened:

## Required observations

Write `PASS` or `FAIL` plus a short observation for every line.

### Presentation and lifecycle

- Before Play, all three camera panels are black and UI pointing/clicking causes no robot or gripper motion:
- Play changes the reported execution state to RUNNING and starts the MuJoCo camera/control stream:
- Stop changes the state to PAUSED, holds both arms/grippers, and stops physics stepping:
- WebXR Reset performs deterministic M1 reset and leaves the session paused:
- Main MuJoCo scene panel is visible, correctly oriented, and usable:
- Left and right wrist panels are visible in their expected positions:
- Each wrist panel shows the workspace directly in front of its gripper; no arm joint dominates the view:
- Initial panel height and gaze-relative placement are comfortable regardless of the current Quest floor/stage calibration:
- The area outside the three panels remains normal passthrough with no opaque or oddly shaped projection-layer region:
- All three panels advance while the simulation moves:
- Clean Quest connect, disconnect/reconnect, and process shutdown:
- No duplicate CloudXR or OpenXR session is observed:

### Identity and simultaneous control

- Status reports `tracking_gate_ready: true` before either simulated arm moves:
- Physical left controls only simulated left PIPER-X:
- Physical right controls only simulated right PIPER-X:
- Both arms can be moved simultaneously and independently:

### Translation and rotation

- Left controller translation signs match the accepted Isaac behavior:
- Right controller translation signs match the accepted Isaac behavior:
- During v39 translation without deliberate controller rotation, the gripper orientation remains stable and the arm chain articulates without straight-arm drift:
- Deliberate controller rotation above the declared threshold moves that arm's distal wrist joints smoothly without any button:

### Scale, clutch, and grippers

- Normal sensitivity is usable for coarse motion:
- Slow deliberate translation/rotation continues to move the intended arm instead of stalling below a hidden deadband:
- Each arm can reach its canonical cube without a joint appearing stuck or prematurely refusing further extension:
- Each thumbstick click toggles only its arm to/from precise mode:
- A mode switch produces no jump:
- Each squeeze clutch freezes only its arm and release rebases without a jump:
- Each trigger moves only its gripper continuously from 100 mm open to 0 mm closed:
- Immediately after Play/reset/tracking recovery, a held trigger does not close either gripper; releasing each trigger once arms only that side and `gripper_armed` reports true:
- Abrupt trigger changes are limited to 10 mm per control tick and reported as saturation:
- A full gripper open/close command reaches its endpoint promptly (automated bound: within 2 mm in 1.5 s):
- Holding a trigger fixed produces a stable aperture with no autonomous open/close oscillation:
- With trigger released, moving/rotating the wrist does not pull the gripper substantially closed; `finger_aperture_mm` remains near `target_gripper_mm`, while `finger_tracking_error_mm` and `finger_symmetry_error_mm` remain small:
- Closing on a cube and then moving/rotating the wrist keeps the cube between the fingertip pads instead of ejecting or dropping it; `finger_symmetry_error_mm` remains below 2 mm without persistent one-sided finger drift:
- Holding a fixed controller pose leaves each arm at its last commanded pose instead of relaxing back:
- The scene remains continuous beyond 300 active control ticks and does not reset home automatically:

### Tracking and reset

- Losing left tracking holds left while right remains coherent:
- Recovering left at a different pose rebases first, then resumes without a jump:
- Losing/recovering right behaves symmetrically:
- Right primary click performs the deterministic M1 reset:
- Reset with live tracking produces no immediate arm jump:
- Controller deltas/trigger, gripper armed state, target error, physical-finger aperture/targets/tracking/symmetry/forces, per-joint `arm_plant` diagnostics, and Cartesian/joint/gripper saturation categories are visible in status output:
- If the right arm still feels worse, attach status records containing both `arm_plant.left` and `arm_plant.right` from the same motion sequence:

## Result

- Overall: PASS / FAIL
- Remaining observations:
- Stdout retained and registered:

Passing this worksheet changes only the additive profile's physical-validation
status. It does not accept a normative gate unless the contract and gate rules
are explicitly amended in a separate scoped change.
