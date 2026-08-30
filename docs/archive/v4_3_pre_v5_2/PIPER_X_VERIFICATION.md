# PIPER_X_VERIFICATION.md

## Purpose

Select and verify the actual PIPER-X LeRobot Robot + AgileX driver/firmware stack and ensure the selected stack is reproducible in the environment that will own it.

Do not assume:

```text
generic Piper == Piper X
latest SDK == best integration
legacy piper_sdk == mandatory
pyAgxArm == mandatory
```

All resolved values go only to `configs/resolved_contract.yaml`.

---

## 1. Candidate evidence matrix

Build a matrix:

```text
candidate
× explicit PIPER-X support
× bimanual support
× LeRobot plugin seam vs fork
× driver backend
× firmware-aware PIPER-X correctness
× action/observation contract clarity
× limits/safety behavior
× maintenance state
× adaptation required
× core-environment compatibility
```

Prefer the smallest correct integration.

---

## 2. Driver backend resolution

Treat the driver as a resolved choice.

Audit the driver required by the selected plugin and current official candidate(s), potentially including:

```text
pyAgxArm
legacy agilexrobotics/piper_sdk
```

Resolve:

```text
driver backend
repo/version/commit
robot model/profile
firmware profile expected by driver
actual firmware left/right
PIPER-X-specific sign/workaround behavior
environment requirements
```

Do not rewrite a correct plugin solely to use a newer SDK.

---

## 3. Phase A — Static contract resolution

Resolve without commanding hardware:

```text
Robot implementation/pin
PIPER-X and bimanual evidence
driver backend/pin
firmware compatibility logic
action_features / observation_features
joint order / units / gripper semantics
declared limits
send_action behavior
URDF/model/frame names
deterministic processor pipeline
declared fail-safe mechanisms
required Python/runtime/dependency constraints
```

Evidence should be re-checkable:

```yaml
repository: ...
commit: ...
path: ...
symbol_or_section: ...
notes: ...
```

Also resolve whether the selected Robot/plugin/driver stack can run in the `core` environment.

If not, follow `ENVIRONMENT_POLICY.md`; do not invent a process boundary casually.

### Phase A gate

`status.static_resolution_complete` may become true only after:

```bash
python tools/validate_resolved_contract.py configs/resolved_contract.yaml
```

passes.

---

## 4. Phase B — Hardware validation

Validate per arm:

```text
actual firmware
CAN identity
left/right identity
joint direction/units
gripper polarity/range
saturation
clipping/slew
returned/accepted command behavior
limits
fail-safe behavior
```

Do not turn requirements into verified facts without evidence.

---

## 5. Action/driver rule

Determine where deterministic transformations happen:

```text
label processor
Robot action processor
Robot.send_action()
driver
device/controller
```

Transformations that should define the learning target belong in the resolved deterministic label path where practical.

Residual device safety remains a final guard.

---

## 6. Acceptance

Offline integration requires Phase A plus a reproducible resolved environment for the selected stack.

Real hardware requires the relevant Phase B fields.

Simultaneous bimanual operation also requires the inter-arm safety gate from `SAFETY_TIMING.md`.
