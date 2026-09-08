# Gate S2 physical Quest acceptance worksheet

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
- Selected translation scale: `10.0`
- Selected rotation scale: `10.0`
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

- Translation gain is usable and consistent between arms:
- Rotation behavior is usable and consistent between arms:

### Independent clutch and rebase

- Left squeeze clutch freezes left intent while the controller moves:
- Left release has no material jump; repeated cycles remain stable:
- Right squeeze clutch freezes right intent while the controller moves:
- Right release has no material jump; repeated cycles remain stable:

### Independent grippers

- Left trigger closes left; release opens left; right does not cross-route:
- Right trigger closes right; release opens right; left does not cross-route:

### Tracking loss and recovery

- Lose left tracking; left holds and valid right remains coherent:
- Recover left; no uncontrolled jump and motion resumes after rebase:
- Lose right tracking; right holds and valid left remains coherent:
- Recover right; no uncontrolled jump and motion resumes after rebase:

### Disconnect and reconnect

- Disconnect XR/client; simulated motion intent becomes inactive:
- Reconnect; no stale replay, identities remain correct, recovery rebases:

### Reset with live session

- Reset while physically connected; no immediate large arm jump:
- Post-reset controller references recover coherently:
- Post-reset left/right identity remains correct:

## Acceptance rule

Gate S2 may be changed from `unresolved` to `accepted` only when every observation
above is PASS, the production runtime report passes with nonzero physical tracking
for both sides, both accepted wrist cameras remain valid, clean disconnect/shutdown
is supported by the retained log, and this completed worksheet is registered as a
`human_gate` evidence object. A verbal “looks good” or the existing Gate B identity
evidence is insufficient.
