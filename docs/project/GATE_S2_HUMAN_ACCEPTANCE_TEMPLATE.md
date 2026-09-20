# Gate S2 physical Quest acceptance worksheet

**Current physical S2 procedure: `./run-vr` in run mode.** Test the exact canonical
composition selected by [the VR config](../../configs/isaac61_vr_runtime.yaml) and
[shared S2 config](../../configs/isaac61_s2_runtime.yaml). Follow
[RUN_VR_OPERATIONS.md](RUN_VR_OPERATIONS.md) for prerequisites and client setup.

This blank worksheet is not evidence. Complete a new copy for the actual run;
configuration selection and diagnostic smoke do not establish human acceptance.

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
the observations below. Use the exact client URL and setup in the canonical VR config.

## Session metadata

- Observer:
- Local start/end time:
- Quest device:
- Exact project Git commit and full tracked/untracked status:
- Exact operator command (`./run-vr`) and EULA prerequisites:
- Run directory:
- Generated `runtime.yaml` path / SHA-256:
- `run_manifest.json` path / SHA-256 (expanded command and source hashes):
- `configs/isaac61_s1_runtime.yaml` copy / SHA-256 (generated config source):
- `configs/isaac61_s2_runtime.yaml` copy / SHA-256 (base S2 semantics):
- `configs/isaac61_vr_runtime.yaml` copy / SHA-256 (canonical operator composition):
- Processor revision / source SHA-256 from manifest:
- Selected environment / package pins / SDK commit from manifest:
- Environment specification / lock / materialization record hashes:
- Runtime result path / SHA-256 / observed shutdown:
- Optional diagnostic qualification run id / logs (same config and controls):
- Effective sensitivity mode, input and per-arm scales from manifest:
- Preview isolation/count and XR presentation from manifest:
- Confirm these match the exact configs retained for this run:
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

Use endpoints, center and interpolation defined in canonical `teleop_tuning.sensitivity`.

- Left horizontal thumbstick selects minimum/center/maximum for translation and
  rotation; right sensitivity is unchanged:
- Right thumbstick does the same independently:
- Sweep intermediate positions; gain changes continuously according to config:
- Change either slider with controller pose stationary; no target jump:
- Release either thumbstick; only that arm returns to configured center:
- Both arms remain usable across the configured range; note drift, jitter or saturation:

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
- Table/robot placement and scale match the canonical config:
- R3 recenters once per press; no scene reset, target jump or session restart:
- Recheck both hands' forward/right/up and rotation axes after repeated R3:
- X shows/hides three distinct live feeds: left wrist, right wrist, scene preview:
- The third feed remains preview-only; no third canonical D0 camera is claimed:
- Aim sensor cameras toward visible preview panels; no panel/recursive image
  appears in sensor feeds, with Scene Partitions active:
- B toggles only backdrop visibility; repeat X/B, hold buttons, and reset while
  connected to check debounce and retained presentation state:

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
insufficient. No gate state is changed by this template.
