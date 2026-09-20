# Gate S2 physical Quest acceptance worksheet

**Current final-master physical S2 procedure: `./run-vr`.** The target is the
exact default isaac61 composition: run-vr + RoboSyn demo overlay + final Isaac61
stack, with Scene Partitions and three previews. Follow
[RUN_VR_OPERATIONS.md](RUN_VR_OPERATIONS.md) for prerequisites and client setup.

This worksheet is intentionally **not evidence** while any item is blank. A new
completed copy must describe the actual run; old blank/completed worksheets and
historical base-S2 results are not evidence for this composition. The overlay is
still `EXPERIMENTAL_TEST_ONLY_NOT_A_GATE`, and its slider is
`DEMO_ONLY_CANDIDATE_REQUIRES_PHYSICAL_RETEST`.

After accepting both NVIDIA EULAs, start from your project checkout with a
physical Meta Quest 3 and no real robot interface:

```bash
export OMNI_KIT_ACCEPT_EULA=Y
export ISAACLAB_CXR_ACCEPT_EULA=1
./run-vr
```

Retain the run directory printed by the launcher. Its expanded command includes
`--xr --s2-cloudxr-profile cloudxrjs --s2-require-tracking`. The runtime requires
valid tracked frames from both physical controllers; that check does not replace
the observations below. Use the configured release-1.4.x Quest client, select
Isaac Lab, Reset to defaults, then Quest 3 before connecting.

## Session metadata

- Observer:
- Local start/end time:
- Quest device:
- Exact project Git commit and clean tracked status:
- Exact operator command (`./run-vr`) and EULA prerequisites:
- Run directory:
- Generated `runtime.yaml` path / SHA-256:
- `launch_manifest.json` path / SHA-256 (expanded command and source hashes):
- `configs/isaac61_s1_runtime.yaml` copy / SHA-256 (generated config source):
- `configs/isaac61_s2_runtime.yaml` copy / SHA-256 (base S2 semantics):
- `configs/experiments/robosyn_vr_demo.yaml` copy / SHA-256 (operator overlay):
- Processor revision: `piper_x_isaac_s2_bimanual_relative_v3`; processor source SHA-256:
- Environment path: `/data/vla-infrastructure/isaac61_production/env`:
- Environment specification / lock / materialization record hashes:
- Exact observed package pins (Sim 6.1.0.0, Kit 110.3, Lab 17.0.2,
  isaacteleop 1.4.98rc1, isaaclab_teleop 0.9.0, CloudXR 6.2.1):
- Lab checkout: `0c2e2c64e51922d088b695d72ffe03faa5c6b95d`:
- `performance.jsonl` path / SHA-256 and optional diagnostics:
- Runtime result path:
- Runtime result SHA-256:
- Runtime log path:
- Runtime log SHA-256:
- Effective sensitivity: `slider`, per-controller `thumbstick_x`, per-arm independent:
- Min / center / max translation AND rotation scale: `2x / 4x / 6x`:
- Preview isolation / cameras: `scene-partitions / 3`:
- XR presentation anchor: `(-0.05, 0.0, -0.10)` m; rotation XYZW
  `(0, 0, -0.7071067811865475, 0.7071067811865476)`; scale `1.0`:
- Confirm no CAN or physical PIPER interface was opened:

## Required observations

Write `PASS` or `FAIL` plus a short observation for every line.

### Session

- Quest connects; one coherent XR/teleop lifecycle:
- Clean start:
- Clean client disconnect and process shutdown:

### Identity and simultaneous motion

- Move physical left only; simulated left responds and right does not:
- Move physical right only; simulated right responds and left does not:
- Simultaneous independent bimanual motion:

### Translation axes

- Left `+X` / `-X` expected direction:
- Left `+Y` / `-Y` expected direction:
- Left `+Z` / `-Z` expected direction:
- Right `+X` / `-X` expected direction:
- Right `+Y` / `-Y` expected direction:
- Right `+Z` / `-Z` expected direction:

### Rotation axes

- Left roll expected axis/sign:
- Left pitch expected axis/sign:
- Left yaw expected axis/sign:
- Right roll expected axis/sign:
- Right pitch expected axis/sign:
- Right yaw expected axis/sign:

### Independent continuous sensitivity sliders

- Left horizontal thumbstick at -1 / 0 / +1 selects 2x / 4x / 6x for
  translation and rotation; the right arm's sensitivity is unchanged:
- Right horizontal thumbstick selects the same endpoints/center independently;
  the left arm's sensitivity is unchanged:
- Sweep each thumbstick through intermediate positions; gain changes continuously
  (piecewise linear, e.g. -0.5 -> 3x, +0.5 -> 5x), without discrete toggling:
- Change either slider with its controller pose stationary; no target jump:
- Return each thumbstick to center; only that arm returns to 4x without a jump:
- Slow alignment at 2x, centered motion at 4x and faster motion at 6x are usable
  on both arms; note any drift, jitter, saturation or loss of control:

### Independent clutch and rebase

- Left squeeze clutch freezes left intent while the controller moves:
- Left release has no material jump; repeated cycles remain stable:
- Right squeeze clutch freezes right intent while the controller moves:
- Right release has no material jump; repeated cycles remain stable:

### Independent grippers

- Left trigger moves left continuously and monotonically from fully open at
  `0` through intermediate apertures to fully closed at `1`; no right cross-route:
- Right trigger does the same independently; no left cross-route:
- Confirm visibly distinct aperture at approximately `0`, `.25`, `.5`, `.75`, `1`:

### Tracking loss and recovery

- Lose left tracking; left holds and valid right remains coherent:
- Recover left at a deliberately different physical pose; the first recovered
  frame has no jump and subsequent relative motion resumes without clutch:
- Lose right tracking; right holds and valid left remains coherent:
- Recover right at a deliberately different physical pose; the first recovered
  frame has no jump and subsequent relative motion resumes without clutch:

### Disconnect and reconnect

- Disconnect XR/client; simulated motion intent becomes inactive:
- Reconnect; no stale replay, identities remain correct, recovery rebases:

### Reset with live session

- Client start/stop changes teleoperation activity without terminating the host:
- Reset while physically connected; no immediate large arm jump:
- Post-reset controller references recover coherently:
- Post-reset left/right identity remains correct:

### XR presentation

- Workspace is comfortably in front and slightly below eye level:
- Demo table/robot placement and 1:1 scale match the selected overlay:
- R3 recenters once per press; no scene reset, target jump or session restart:
- Recheck both hands' forward/right/up and rotation axes after repeated R3:
- X shows/hides three distinct live feeds: left wrist, right wrist, scene preview:
- The third feed remains preview-only; no third canonical D0 camera is claimed:
- Aim sensor cameras toward visible preview panels; no panel/recursive image
  appears in sensor feeds, with Scene Partitions active:
- B toggles only backdrop visibility; repeat X/B, hold buttons, and reset while
  connected to check debounce and retained presentation state:

## Historical / base-S2 note

`tools/launch_isaac_s2.py` is the BASE / GENERIC S2 LAUNCHER. Without the demo
overlay it selects per-arm thumbstick-click toggle normal 2x / precise 0.5x.
Those checks belong to base-S2 qualification, not the current procedure above.
In the operator composition R3 is recenter, and sensitivity uses the horizontal
axis. Existing historical physical reports retain their original commands and
results; this updated blank template creates no new human evidence.

## Acceptance rule

PRIMARY OPERATOR PATH is distinct from ALREADY ACCEPTED GATE CONFIG. Gate S2 may
be changed from `unresolved` to `accepted` only when every current observation
above is PASS, the exact composition's runtime report passes with physical tracking
for both sides, both accepted wrist cameras remain valid, clean disconnect/shutdown
is supported by the retained log, and this completed worksheet is registered as a
`human_gate` evidence object. Retain required command-test, log and test-output
evidence and satisfy all prerequisites in `configs/gate_rules.yaml`; reconcile
the selected configuration/provenance through the contract before promotion.
A verbal “looks good”, interrupted run, or existing Gate B identity evidence is
insufficient. No gate state or overlay status is changed by this template.
