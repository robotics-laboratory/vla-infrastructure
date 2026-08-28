# SAFETY_TIMING.md

## 1. Canonical action-label terminology

Do not invent new action classes; use these names only to reason about pipeline points.

```text
data_action
    action in the resolved dataset/policy semantic space

dataset_action
    output after all deterministic transformations that the project intentionally
    wants reflected in the training label

device_accepted_command
    command actually accepted/sent after Robot/driver/device residual behavior,
    when observable
```

Canonical flow:

```text
policy/human data_action
↓
HIL merge if applicable
↓
deterministic label processors
  limits / slew / conversions / IK only where applicable to the chosen data space
↓
dataset_action
├─> dataset.action
└─> normal Robot/send path
      ↓
residual Robot/driver/device safety
      ↓
device_accepted_command (if observable)
```

For the baseline joint-space dataset, IK is normally before the data action reaches this label path, not repeated here.

---

## 2. Deterministic vs residual safety

Reuse current safety first.

Inspect:

```text
LeRobot processors
selected Robot/plugin
selected AgileX driver
device/controller
```

Move/share deterministic transformations that should define the learning target into the resolved label-processor sequence where practical.

Keep emergency/device-native clamp as residual safety.

If residual behavior changes the command, make the mismatch diagnosable. Store `device_accepted_command` only if the actual workflow needs it and it is observable.

---

## 3. Freshness clock domain

Default safety timebase:

> host monotonic receipt/capture timestamp unless an explicitly synchronized clock domain is configured and verified.

Never compare unrelated Quest/robot/host wall clocks for safety age.

Source timestamps may still be recorded as diagnostics.

Resolve numeric:

```text
max_xr_pose_age_ms
max_joint_state_age_ms
max_policy_action_age_ms
```

and explicit stale behavior for each:

```text
stale XR -> hold | pause | stop | other resolved fail-safe
stale joint state -> ...
stale policy action -> ...
```

These behaviors belong in `configs/resolved_contract.yaml`.

---

## 4. Watchdog / fail-safe

Strong invariant:

> failure/stall of the main process AND failure/stall of an optional hardware-host process must not permit indefinite continuation of the last command.

Preferred evidence order:

```text
1. device/controller/firmware deadline or command timeout
2. driver/SDK fail-safe that is actually backed by controller/device behavior
3. separate hardware-host heartbeat as an additional layer
```

A same-process thread is insufficient.

A separate host process alone is not a complete substitute if it can hang after the last command.

Resolve:

```text
owner
trigger/deadline
effect: hold | controlled_stop | disable | other
hardware evidence
```

If no verified low-level stop/deadline/fail-safe exists, autonomous real-hardware gate does not pass.

---

## 5. One-session XR invariant

For the pinned LeRobot/Isaac Teleop path, use one Isaac Teleop/CloudXR session lifecycle per process.

```text
ONE session
  ├─ left controller stream
  └─ right controller stream
```

Do not instantiate separate process-local CloudXR/TeleopSession lifecycles for left/right arms.

---

## 6. Frames

Use:

```text
T_A_B transforms coordinates from frame B into frame A.
p_A = T_A_B * p_B
```

Store exact frame names and calibration artifact/hash in the resolved contract.

Do not scatter frame fixes through code.

---

## 7. Kinematics acceptance

Do not require:

```text
IK(FK(q)) == q
```

Use:

```text
target pose
→ IK
→ q
→ FK
→ solved pose
```

and check numeric:

- position error
- orientation error
- joint limits
- continuity/max step

---

## 8. Inter-arm safety gate

Before simultaneous real bimanual operation, one of these MUST be verified:

```text
A. verified inter-arm collision handling
OR
B. conservatively non-overlapping allowed workspaces for left/right arms
```

Baseline should prefer B because it is smaller and easier to verify.

Full collision checking may remain an advanced feature.

`if needed` is not sufficient for the real bimanual gate.

---

## 9. Numeric thresholds

Unknown hardware values remain `DECIDE/PIN`.

Codex must not invent them.
