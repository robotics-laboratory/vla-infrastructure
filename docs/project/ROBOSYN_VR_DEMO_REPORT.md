# RoboSyn-inspired VR demo report

This is an isolated `EXPERIMENTAL_TEST_ONLY` result. It accepts no gate,
reopens no S0/S1/S2/D0 decision, changes no canonical D0 schema, and does not
start D1/G1.

## Branch and runtime

- Branch: `experiment/robosyn-vr-demo`
- Worktree: `/home/ebulochkin/vla_infrastructure/.worktrees/robosyn-vr-demo`
- Base/checkpoint: `031143d576d923d6029d0226d963cbedaec1f6d4`
  (`checkpoint/s2-quest-remediation-20260910`)
- Launch: `python tools/launch_isaac_robosyn_vr_demo.py`
- Config: `configs/experiments/robosyn_vr_demo.yaml`
- Default profile: `dual_cube_to_matching_plates`
- Test-asset profile: `--profile robosyn_asset_lab`

The launcher verifies the frozen Candidate B checkout/environment and the
RoboSyn source commit and per-file hashes before starting. Runtime outputs are
kept under `/data/ebulochkin/cache/robosyn-vr-demo/runs`; they are not gate
evidence.

## Geometry and home smoke

- Left/right bases: `[0.233, +0.300, 0.825]` and
  `[0.233, -0.300, 0.825]`; identity rotation, parallel along scene `+X`;
  separation `0.600 m`.
- Table center/size: `[0.725, 0, 0.775]` / `[1.0, 1.0, 0.1]`; top
  `Z=0.825`.
- The specification's candidate demo-only homes were retained unchanged:
  left `[-20, 90, -50, 0, 0, 0, 50]`, right
  `[20, 90, -50, 0, 0, 0, 50]` (degrees plus millimetre aperture).
- A 120-step settled smoke with demo-only self-collision/contact reporting had
  zero measured arm contact, zero home-state drift, finite state, TCPs at
  `[0.578929, +0.174092, 1.026480]` and
  `[0.578929, -0.174092, 1.026481]`, and `0.348185 m` TCP separation.
- Gate C PIPER geometry was not modified.

The scene uses a neutral taupe table, dark neutral floor/backdrop, dome light,
and a warm key light. The inspected scene-camera preview clearly framed both
arms and the blue/orange matching task without the RoboSyn green-wall look.
The temporary preview was removed after inspection.

## Profiles and assets

`dual_cube_to_matching_plates` uses the requested procedural geometry:

- cubes: `[0.52, +0.17, 0.847]`, `[0.52, -0.17, 0.847]`;
- matching plates: `[0.72, +0.17, 0.831]`,
  `[0.72, -0.17, 0.831]`.

The `robosyn_asset_lab` profile loaded and reset-smoked these test-only assets:

- button URDF, source collision and prismatic press joint;
- beaker USD, source collision, with source-stage centimetre correction;
- pen OBJ converted by upstream Isaac Lab to a convex-hull collision USD.

Pen holder and basket were quarantined because usable collision would need
non-trivial decomposition/repair. Test tube and rack were quarantined because
the pinned converter does not accept their PLY source; the rack would also
need collision repair. Exact source paths, commit, SHA-256, format, resolved
scale, collision strategy, and status are in
`configs/experiments/robosyn_test_assets.yaml`.

All source and conversion data is stored only at:

- `/data/ebulochkin/assets/robosyn_vr_demo/RoboSynChallenge`
- `/data/ebulochkin/assets/robosyn_vr_demo/converted`

The source checkout is clean at
`9815e9eee86f3dda88860ca971f71354f157d41c`. No binary asset is committed or
redistributed. Every entry remains `TEST_ONLY_NOT_APPROVED_FOR_PRODUCTION`.

## Cameras and XR presentation

The existing left/right wrist viewpoints, resolution, intrinsics, and D0 names
are retained. The demo instantiates them as two concrete upstream `Camera`
objects so upstream PiP can bind each one; a thin facade returns their first
three RGBA channels through the unchanged two-image RGB D0 edge.

The non-D0 scene camera is `640x480`, target `30 Hz`, horizontal FOV `60 deg`:

- eye `[0.10, +0.05, 1.43]`;
- target `[0.65, 0.0, 0.88]`;
- up `[0, 0, 1]`;
- focal length `18.147558 mm`, aperture `20.955 mm`.

All three camera tensors passed shape/dtype/freshness smoke. Their configured
simulation-time rate is 30 Hz; the observed wall-time rate scales with RTF.

The experiment-only XR presentation uses scale `1.0`, anchor position
`[-0.05, 0, -0.25]`, quaternion
`[0, 0, -0.7071067812, 0.7071067812]`, and near plane `0.10 m`. This maps XR
forward to scene `+X`. The Z value is a demo-only physical-retest candidate:
the first Quest run showed that `+1.20 m` put the unchanged table far too low,
so lowering the simulation anchor raises the table to `1.075 m` in the XR
floor frame. Physical comfort still requires confirmation; no robot or table
geometry was moved to compensate for presentation.

The same physical run found the inherited S2 gains too slow. Only the demo
config now selects NORMAL translation/rotation `4.0 / 4.0` and PRECISE
`1.0 / 1.0`. Stock S2 remains at `2.0 / 2.0` and `0.5 / 0.5`.

## Wrist-camera panels

The implementation is upstream `isaaclab_teleop` `XrCameraFeedSession` with
`XrCameraFeedCfg`, horizontal viewer-start layout, and the Kit SceneUI
presenter. The XR smoke confirmed feed-owned zero-copy CUDA annotators for both
`left_wrist` and `right_wrist`.

The audited `ControllersSource` exposes grip pose/valid, primary, secondary,
thumbstick X/Y/click, menu, squeeze, and trigger. Upstream reserves only right
`PRIMARY_CLICK` (Quest A) for anchor rotation; Start/Stop/Reset arrive on the
separate message channel. Demo sensitivity therefore uses left
`SECONDARY_CLICK` (Quest Y), routed to both existing per-arm edge handlers, and
the display toggle uses free left `PRIMARY_CLICK` (Quest X). Squeeze clutch and
analog trigger gripper are unchanged.

DISPLAY ON binds and refreshes the upstream session once. DISPLAY OFF now calls
only the pinned SceneUI `UiContainer.hide()` path; ON after that calls `show()`
without rebinding. Both wrist cameras and feed acquisition keep running while
hidden. Final resource close happens only after the control loop, so no
performance improvement is claimed and no sensor performance mode was added.

### Physical Y shutdown root cause and remediation

The two full physical logs are:

- `/data/ebulochkin/cache/robosyn-vr-demo/runs/20260911T120807675727Z-dual_cube_to_matching_plates-hud-off/stdout.log`;
- `/data/ebulochkin/cache/robosyn-vr-demo/runs/20260911T121148303909Z-dual_cube_to_matching_plates-hud-off/stdout.log`.

Both show a healthy running session, Y-driven HUD ON and then OFF, followed by
the first exception from the next Isaac Lab `Camera.update()`:
`AnnotatorRegistryError: Annotator rgb is not attached to any render products.`
No sensitivity transition or CloudXR lifecycle command precedes it; both modes
remain `normal`. The old OFF path called `XrCameraFeedSession.close()`, whose
pinned `_ReplicatorCameraFeedSource.close()` detached the registry `rgb`
annotator from the wrist render product. On this pinned stack that annotator is
shared with the camera renderer, despite being described upstream as
feed-owned. CloudXR stop and `IsaacTeleop session ended` are cleanup after the
exception, not its trigger. The fix does not catch the exception: it removes
the invalid mid-session detach by hiding only the upstream panel and defers
`close()` to final shutdown.

## Performance

These are bounded, sequential 60-control-step RTX 4090 no-client XR smokes,
not physical-stream latency qualification. RTF is effective physics Hz / 120.

| Profile | Control Hz | Physics Hz | RTF | Wrist/scene wall Hz | sampled GPU | max VRAM |
|---|---:|---:|---:|---:|---:|---:|
| current S2 baseline | 5.4265 | 21.7060 | 0.1809 | wrist 5.4265; scene n/a | 39–65% (2 samples) | 5910 MiB |
| demo, HUD OFF | 4.6871 | 18.7482 | 0.1562 | 4.6871 / 4.6871 | 3–63% | 6617 MiB |
| demo, HUD ON | 4.6802 | 18.7207 | 0.1560 | 4.6802 / 4.6802 | 48–72% | 6620 MiB |

Evidence:

- baseline:
  `/data/ebulochkin/cache/isaac-s2/runs/20260908T212016Z/result.json`;
- HUD OFF:
  `/data/ebulochkin/cache/robosyn-vr-demo/runs/20260910T181722625678Z-dual_cube_to_matching_plates-hud-off/result.json`;
- HUD ON:
  `/data/ebulochkin/cache/robosyn-vr-demo/runs/20260910T181757892980Z-dual_cube_to_matching_plates-hud-on/result.json`.

HUD ON versus OFF changed control/physics rate by `-0.15%`, and maximum VRAM
by `+3 MiB`. The `+9 percentage-point` sampled GPU peak is the first startup
sample in a short run; steady samples overlap, so it is not evidence of a
sustained HUD cost. The main measured scene cost versus baseline is `-13.6%`
control/physics rate and about `+707 MiB` maximum VRAM. It is localized to the
third RTX camera, two individually addressable wrist render products, and the
additional visual/physics scene—not to panel visibility. The narrow applied
fix uses wrist RGBA once for both upstream PiP and D0 RGB and stops forced
contact-tensor reads after preflight; no scene element or camera was silently
disabled.

XR Kit, the CloudXR runtime, and the upstream feed lifecycle started and shut
down with exit code zero in both XR runs. With no Quest connected, the XR
session correctly remained inactive; physical stream stability is therefore
not claimed.

## Validation and regressions

- Procedural scene, candidate home, contacts, table collision, task objects,
  reset, three cameras, and XR Kit: PASS.
- Test-asset profile: PASS; button/pen/beaker prims valid and reset smoke within
  `3.743 mm`.
- Wrist HUD startup: PASS for both feeds using upstream zero-copy path.
- Core tests: `72 passed, 6 skipped` (the skips are environment-conditioned).
- Exact Candidate B processor/upstream tests: `19 passed`, including shared-Y
  mapping, held-button debounce, repeated NORMAL/PRECISE switches with zero
  switch-frame delta, X display mapping, and no mid-session feed close.
- Updated standalone demo smoke: PASS with the configured `4.0 / 4.0` and
  `1.0 / 1.0` gains and `[-0.05, 0, -0.25]` anchor:
  `/data/ebulochkin/cache/robosyn-vr-demo/runs/20260911T124038829352Z-dual_cube_to_matching_plates-hud-off/result.json`.
- Updated XR Kit smoke: PASS, four injected post-mapping X edges
  (`ON -> OFF -> ON -> OFF`), reset between pairs, both zero-copy feeds, 60/60
  valid and advancing camera frames, clean shutdown, and no annotator error:
  `/data/ebulochkin/cache/robosyn-vr-demo/runs/20260911T124506940513Z-dual_cube_to_matching_plates-hud-off/result.json`.
- Updated stock S2 smoke: PASS with its original thumbstick mapping and original
  `2.0 / 2.0`, `0.5 / 0.5` gains:
  `/data/ebulochkin/cache/isaac-s2/runs/20260911T124204Z/result.json`.
- Updated stock S1 regression: PASS, including both 110-frame camera sequences:
  `/data/ebulochkin/cache/isaac-s1/runs/20260911T124240Z/result.json`.
- Tracking-loss recovery, clutch/rebase, analog gripper, and normal/precise
  sensitivity remain covered by the S2 processor suite. Exact controller-field
  tests cover Y and X without changing the 22-value production S2 action.

No Quest was connected during the post-fix automated runs, so a live CloudXR
client remaining connected through physical Y/X presses and the new anchor's
comfort remain explicit retest items. This does not mark the demo or S2
accepted.

## Physical Quest demo procedure

1. From the experiment worktree, start exactly:
   `OMNI_KIT_ACCEPT_EULA=Y python tools/launch_isaac_robosyn_vr_demo.py`.
2. Connect Quest 3 through the same working S2 CloudXR flow; wait for both
   controllers to track. Confirm the table is slightly below eye level, ahead,
   and at 1:1 scale.
3. Move left, right, then both arms in NORMAL. Press and release Y once; confirm
   one logged switch to PRECISE for both arms, no jump and no stream restart.
   Hold Y for two seconds and confirm it does not switch repeatedly; release
   and press once more to return both arms to NORMAL.
4. Verify both squeeze clutch/release paths and both analog triggers. Briefly
   lose and restore one controller's tracking; confirm zero-jump rebase.
5. Press X once for both wrist panels and X again to hide them. Repeat twice;
   confirm the scene, wrist cameras, teleop and CloudXR stream remain live.
6. Move both colored cubes to their matching plates and confirm the scene
   camera framing remains centered. Run for two minutes, then stop through the
   existing S2 control path and keep the generated result/log directory.

Preflight status: `READY_FOR_PHYSICAL_RETEST`; not accepted.
