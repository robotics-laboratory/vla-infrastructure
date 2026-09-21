# Gate S2 physical Quest acceptance worksheet

For final-master re-acceptance, first use
[the 2026-09-21 coverage audit and structured procedure](GATE_S2_FINAL_MASTER_COVERAGE_20260921.md).
It adds separate human/log verdicts, scenario markers and provenance checks.
The toggle-based worksheet below is retained as the existing procedure; it must
not be interpreted as evidence for the demo's continuous speed sliders.

This worksheet is intentionally **not evidence** while any item is blank. Run the
production command below with a physical Meta Quest 3 and no real robot interface:

```bash
OMNI_KIT_ACCEPT_EULA=Y python3 tools/launch_isaac_s2.py --max-control-steps 1800
```

Record the generated `result.json` and `stdout.log` paths and hashes. The runtime
itself requires at least one valid tracked frame from each physical controller,
but that machine check does not replace the observations below.

## Session metadata

- Observer:
- Local start/end time:
- Quest device:
- Runtime result path:
- Runtime result SHA-256:
- Runtime log path:
- Runtime log SHA-256:
- Normal translation/rotation scale: `2.0 / 2.0`
- Precise translation/rotation scale: `0.5 / 0.5`
- Per-arm mode toggle: controller thumbstick click
- XR presentation anchor: `(0.0, -0.6, -1.05)` m
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

### Scale

- Normal mode is usable for coarse/navigation motion on both arms:
- Click only the left thumbstick; left enters precise while right stays normal:
- Click only the right thumbstick; right enters precise independently:
- Neither arm jumps on a mode switch; holding the click does not retrigger:
- Precise mode permits controlled gripper alignment on both arms:
- Click each thumbstick again; that arm returns to normal without a jump:

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

- Reset while physically connected; no immediate large arm jump:
- Post-reset controller references recover coherently:
- Post-reset left/right identity remains correct:

### XR presentation

- Workspace is comfortably in front and slightly below eye level:
- Gate C/S1 robot/ground geometry itself is unchanged:

## Acceptance rule

Gate S2 may be changed from `unresolved` to `accepted` only when every observation
above is PASS, the production runtime report passes with nonzero physical tracking
for both sides, both accepted wrist cameras remain valid, clean disconnect/shutdown
is supported by the retained log, and this completed worksheet is registered as a
`human_gate` evidence object. A verbal “looks good” or the existing Gate B identity
evidence is insufficient.
