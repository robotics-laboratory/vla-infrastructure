# LIVE-MIN120-DEFERRED temporal qualification

Frozen failed experiment record. Owner: `vr.performance`. This report does not
change canonical runtime selection, accept a gate, qualify physical operation,
or supersede the separately qualified LIVE-MIN60-DEFERRED camera association.

## Scope and identity

- Candidate: `LIVE-MIN120-DEFERRED`
- Tested repository parent HEAD: `72318595c5515740b705fe107ec6d34c1f4395f0`
- Branch/worktree: `wip/vr-recording` at
  `/home/ebulochkin/vla_infrastructure/.worktrees/vr-recording`
- Physics/control/render: 120 Hz / 30 Hz / four physics steps and one render per control
- Renderer/XR scale: RTX Minimal mode 2 / 0.4
- Cameras: independent non-tiled left wrist, right wrist, and scene Camera
  products; live 640 x 480 uint8 RGB; panels off
- Owned copy: 2,764,800 bytes per extracted boundary
- Persistence: RecorderManager, HDF5, compression, and LeRobot off

Only physics frequency and physics steps per control changed from the qualified
LIVE-MIN60-DEFERRED experiment. The one-deep binder, synchronous render path,
native witnesses, one-render boundary, camera products, ownership, and failure
policy were unchanged. Exact copied-source hashes and invocation are retained in
`/tmp/live-min120-deferred-short-01/launch.json` for the lab run.

## Result: camera source disagreement

The required 300-boundary gate failed at its second accepted changing boundary.
After 30 diagnostic witness-calibration boundaries, accepted boundary 31 mapped
all three cameras to N-1. At accepted boundary 32, both wrist products still
mapped to N-1 while the scene product mapped to N:

| availability boundary | left wrist | right wrist | scene |
|---:|---:|---:|---:|
| 31 | -1 | -1 | -1 |
| 32 | -1 | -1 | 0 |

Boundary 32 advanced from physics generation 1599 to 1603: exactly four physics
steps. It performed exactly one render and one Kit update. All cameras reported
the same extraction ID 359, frame 325, and data generation 363, so extraction
counters alone could not expose the content disagreement.

The source classification was content-sensitive and well separated at the
failing boundary:

- Left-wrist right-cube feature errors for N/N-1/N-2 were 84.071, 8.613,
  and 183.642; result N-1.
- Right-wrist left-cube feature errors were 113.683, 8.246, and 83.143;
  result N-1.
- Scene robot-articulation area errors were 28, 81, and 216 pixels;
  result N.

Thus the image bundle available at N did not have one common source boundary.
The failure is not an inferred counter slip and cannot be repaired by individually
shifting cameras without falsifying observation semantics.

## Priming and stopped work

Two render-only primes were discarded, advanced zero physics, and cost 283.305 ms.
The camera-child USD marker remained disabled; the native PhysX cubes and moving
robot finger were used. Calibration itself showed transient source variation,
although its final three boundaries all classified N-1. This does not rescue the
accepted boundary-32 disagreement.

The fail-closed stop rule prevented terminal-drain qualification, reset/recenter
qualification, the 300-warmup plus 3 x 3000 performance runs, performance class,
canonical-120 native parity/contact confirmation, and physical candidate creation.
No 90 Hz, scale, quality, tiled-camera, tuning, or alternative architecture trial
was run.

## Gates and verdict

Canonical D0, S0, and S1 remain unchanged. S2 and D1 remain unresolved. No
canonical runtime was promoted and no 4D work was started.

**LIVE-MIN120-DEFERRED TEMPORAL BINDING FAILED**
