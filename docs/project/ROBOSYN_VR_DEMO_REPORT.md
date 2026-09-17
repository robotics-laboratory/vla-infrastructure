# RoboSyn-inspired VR demo report

This is an isolated `EXPERIMENTAL_TEST_ONLY` result. It accepts no gate,
reopens no S0/S1/S2/D0 decision, changes no canonical D0 schema, and does not
start D1/G1.

## Branch and runtime

- Branch: `experiment/robosyn-vr-demo`
- Worktree: `<repository-root>`
- Base/checkpoint: `031143d576d923d6029d0226d963cbedaec1f6d4`
  (`checkpoint/s2-quest-remediation-20260910`)
- Launch: `python tools/launch_isaac_robosyn_vr_demo.py`
- Config: `configs/experiments/robosyn_vr_demo.yaml`
- Default profile: `dual_cube_to_matching_plates`
- Test-asset profile: `--profile robosyn_asset_lab`

The launcher verifies the frozen Candidate B checkout/environment and the
RoboSyn source commit and per-file hashes before starting. Runtime outputs are
kept under `/data/vla-infrastructure/cache/robosyn-vr-demo/runs`; they are not gate
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

- `/data/vla-infrastructure/assets/robosyn_vr_demo/RoboSynChallenge`
- `/data/vla-infrastructure/assets/robosyn_vr_demo/converted`

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
`[-0.05, 0, -0.10]`, quaternion
`[0, 0, -0.7071067812, 0.7071067812]`, and near plane `0.10 m`. This maps XR
forward to scene `+X`. The Z value is a demo-only physical-retest candidate.
Physical evidence showed `+1.20 m` was far too low and the subsequent
`-0.25 m` setting slightly too high. The new value lowers the unchanged scene
by `0.15 m`, putting the table surface at `0.925 m` in the XR floor frame.
Physical comfort still requires confirmation; no robot or table geometry was
moved to compensate for presentation.

The same physical run found the inherited S2 gains too slow. Only the demo
config now selects NORMAL translation/rotation `4.0 / 4.0` and PRECISE
`1.0 / 1.0`. Stock S2 remains at `2.0 / 2.0` and `0.5 / 0.5`.

## Wrist-camera panels

The implementation is upstream `isaaclab_teleop` `XrCameraFeedSession` with
`XrCameraFeedCfg`, horizontal head-locked layout, and the Kit SceneUI presenter.
The physical log proved that X reached the runtime, both feeds bound, and the
old viewer-start anchor captured successfully, despite the panels not being
visible to the operator. The narrow presentation fix selects upstream
`head_locked`, keeping both compact panels in front of the viewer instead of at
that captured world pose. A later physical run exposed two gray triangulated
panels. Runtime diagnostics now prove that both source images are non-uniform
camera frames and that their alpha is already fully opaque, so the sensors and
RGBA content are not the cause. This localizes the failure downstream of
capture, in XR presentation; the next compatibility candidate specifically
bypasses the direct CUDA-pointer upload branch.

The feed source, layout, panels, subscription, and visibility lifecycle remain
upstream-owned. A demo-only presenter delegate now stages the unchanged RGBA
frames into a reusable CPU tensor, selecting the same upstream panel's
`ByteImageProvider.set_bytes_data` path instead of
`set_bytes_data_from_gpu`. Capture remains upstream zero-copy CUDA; only the
final presentation upload is staged. Physical confirmation that the panels now
show images is still required.

The audited `ControllersSource` exposes grip pose/valid, primary, secondary,
thumbstick X/Y/click, menu, squeeze, and trigger. Upstream reserves only right
`PRIMARY_CLICK` (Quest A) for anchor rotation; Start/Stop/Reset arrive on the
separate message channel. Each demo thumbstick X axis now continuously controls
only its own arm from 2× (left) through 4× (center) to 6× (right), and the
display toggle uses free left `PRIMARY_CLICK` (Quest X). Squeeze clutch and
analog trigger gripper are unchanged. Free right `SECONDARY_CLICK` (Quest B)
now edge-toggles only the visual USD backdrop. It does not change table/robot
geometry, physics, XR lifecycle, or orientation.

DISPLAY ON binds and refreshes the upstream session once. DISPLAY OFF now calls
only the pinned SceneUI `UiContainer.hide()` path; ON after that calls `show()`
without rebinding. Both wrist cameras and feed acquisition keep running while
hidden. Final resource close happens only after the control loop, so no
performance improvement is claimed and no sensor performance mode was added.

### R3 controller-frame root cause and remediation

The R3 edge correctly called upstream `XRCore.schedule_teleport_to_view` and
then the existing S2 lifecycle reset/rebase. The reset prevented an arm jump,
but `ControllersSource` still received
`XrAnchorManager.get_world_matrix()`. That matrix represents the authored
stage anchor only; Kit teleport additionally changes the XR navigation space
origin. Consequently the visible world rotated/repositioned while physical
controller poses continued to be mapped through the pre-teleport axes.

For this experiment only, the existing single `ControllersSource` now reads
`XRCore.get_physical_to_virtual_world_transform()` every frame. The upstream
API explicitly includes the anchor, anchor-to-space-origin transform, and
scale. Its USD/Gf row-vector matrix is transposed into the existing pipeline's
column-vector convention. R3 remains one rising-edge request, scale remains
1:1, no robot/table geometry moves, and the existing reset/rebase handles the
transition without restarting the session. Production S2 continues to use the
original `XrAnchorManager` path.

### Physical Y shutdown root cause and remediation

The two full physical logs are:

- `/data/vla-infrastructure/cache/robosyn-vr-demo/runs/20260911T120807675727Z-dual_cube_to_matching_plates-hud-off/stdout.log`;
- `/data/vla-infrastructure/cache/robosyn-vr-demo/runs/20260911T121148303909Z-dual_cube_to_matching_plates-hud-off/stdout.log`.

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
  `/data/vla-infrastructure/cache/isaac-s2/runs/20260908T212016Z/result.json`;
- HUD OFF:
  `/data/vla-infrastructure/cache/robosyn-vr-demo/runs/20260910T181722625678Z-dual_cube_to_matching_plates-hud-off/result.json`;
- HUD ON:
  `/data/vla-infrastructure/cache/robosyn-vr-demo/runs/20260910T181757892980Z-dual_cube_to_matching_plates-hud-on/result.json`.

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

The CPU presentation compatibility candidate was also smoke-tested twice while
an unrelated Python workload already occupied approximately `11.7 GiB` and
`100%` GPU before demo startup. The final run still passed lifecycle and camera
validation, but its `1.9323 Hz` control / `7.7292 Hz` physics result is
contaminated and is not a valid replacement for the clean table above. A clean
GPU comparison is deferred until that external workload is absent; no update
rate or scene element was changed based on the contaminated sample.

XR Kit, the CloudXR runtime, and the upstream feed lifecycle started and shut
down with exit code zero in both XR runs. With no Quest connected, the XR
session correctly remained inactive; physical stream stability is therefore
not claimed.

## Grasp-contact stabilization

The clean pre-investigation state is recoverable at
`checkpoint/robosyn-vr-demo-pre-grasp-shake-20260911`, commit `aa5d934`.
The scripted probe held the arm fixed, placed the 40 mm / 35 g procedural cube
between the left fingers, issued one constant zero-aperture command, and sampled
180 settled physics ticks at 120 Hz. This excludes Quest trigger noise, IK,
retargeting, and arm motion as causes.

The imported USD already applies `NewtonMimicAPI` constraints from
`gripper_joint1/2` to the geometry-free `gripper` aperture leader. The previous
demo configuration additionally drove all three joints at 2000 stiffness,
100 damping, and 10 N each. The three drives saturated against the cube and
fought the contact/mimic constraint loop. Candidate B's upstream robot configs
instead actuate the leader and set passive/mimic joints to zero stiffness and
damping.

| 120 Hz settled metric | previous demo | demo-only fix |
|---|---:|---:|
| leader joint peak-to-peak | 5.467 mm | 0.296 mm |
| follower 1 peak-to-peak | 2.202 mm | 0.211 mm |
| follower 2 peak-to-peak | 2.035 mm | 0.009 mm |
| cube position peak-to-peak | 2.176 mm | 0.120 mm |
| mean reported contact force | 19.582 N | 2.184 N |

The demo-only fix drives only `gripper` at 400 stiffness, 40 damping, and a
2 N effort limit; the two imported mimic followers remain passive. Cube
geometry, collision mesh, friction, D0 aperture semantics, analog trigger
mapping, and the production S1 robot configuration are unchanged. The 2 N
candidate provides about 3.8x the 35 g cube's weight in available dynamic
friction at the configured 0.6 coefficient, but still requires a physical
Quest pick/move test before acceptance.

## Validation and regressions

- Procedural scene, candidate home, contacts, table collision, task objects,
  reset, three cameras, and XR Kit: PASS.
- Test-asset profile: PASS; button/pen/beaker prims valid and reset smoke within
  `3.743 mm`.
- Wrist HUD startup: PASS for both feeds using upstream zero-copy path.
- Core plus pinned isaac-teleop tests after grasp stabilization: `72 passed,
  11 skipped` (the skips are environment-conditioned).
- Exact Candidate B processor/upstream tests: `26 passed`, including shared-Y
  mapping, held-button debounce, repeated NORMAL/PRECISE switches with zero
  switch-frame delta, X display mapping, B backdrop mapping/debounce, and no
  mid-session feed close.
- Updated standalone demo smoke: PASS with the configured `4.0 / 4.0` and
  `1.0 / 1.0` gains and `[-0.05, 0, -0.10]` anchor:
  `/data/vla-infrastructure/cache/robosyn-vr-demo/runs/20260911T130630768531Z-dual_cube_to_matching_plates-hud-off/result.json`.
- Updated XR Kit smoke: PASS, four injected post-mapping X edges and four B
  edges, reset between pairs, both zero-copy feeds, backdrop visibility
  round-trips, 60/60 valid and advancing camera frames, clean shutdown, and no
  annotator error:
  `/data/vla-infrastructure/cache/robosyn-vr-demo/runs/20260911T130700296111Z-dual_cube_to_matching_plates-hud-off/result.json`.
- Updated stock S2 smoke: PASS with its original thumbstick mapping and original
  `2.0 / 2.0`, `0.5 / 0.5` gains:
  `/data/vla-infrastructure/cache/isaac-s2/runs/20260911T130749Z/result.json`.
- Post-R3-fix stock S2 smoke: PASS, 60/60 cameras, session remained running,
  and the report explicitly retained
  `XrAnchorManager.get_world_matrix` rather than the experiment-only
  navigation-aware transform:
  `/data/vla-infrastructure/cache/isaac-s2/runs/20260912T113526Z/result.json`.
- Updated stock S1 regression: PASS, including both 110-frame camera sequences:
  `/data/vla-infrastructure/cache/isaac-s1/runs/20260911T130822Z/result.json`.
- Post-grasp-fix standalone demo smoke: PASS; both articulations report one
  400/40/2 N leader drive and zero-stiffness/damping mimic followers, scene
  preflight passes, reset passes, both wrist cameras advance 60/60 frames, and
  the unchanged S2 loop shuts down cleanly:
  `/data/vla-infrastructure/cache/robosyn-vr-demo/runs/20260911T141639351652Z-dual_cube_to_matching_plates-hud-off/result.json`.
- Tracking-loss recovery, clutch/rebase, analog gripper, the stock toggle modes,
  and the demo's independent continuous speed sliders remain covered by the S2
  processor suite. Exact controller-field tests cover both thumbstick X axes,
  Quest X, and Quest B without changing the 22-value production S2 action.
- Navigation-transform tests apply two different upstream
  physical-to-virtual matrices and verify that the controller mapping tracks
  the changed XR space origin. R3 debounce and upstream teleport dispatch pass.
- CPU presentation tests verify reusable-buffer allocation and byte-for-byte
  RGBA preservation. Final no-client XR smoke bound both zero-copy wrist
  sources to CPU uploads (`RGB stddev 30.3344/32.0653`, alpha `255/255`),
  advanced all 60/60 camera frames, exercised X/B/R3 events and reset, and
  exited cleanly:
  `/data/vla-infrastructure/cache/robosyn-vr-demo/runs/20260912T113103366077Z-dual_cube_to_matching_plates-hud-on/result.json`.
- Repository regression after these changes: `72 passed, 13 skipped`; Ruff:
  PASS. Exact Candidate B processor/upstream suite: `26/26` PASS.

No Quest was connected during the post-fix automated runs, so physical R3 axis
alignment, actual panel pixels, and a live CloudXR client remaining connected
through R3/X remain explicit retest items. This does not mark the demo or S2
accepted.

## Physical Quest demo procedure

1. From the experiment worktree, start exactly:
   `OMNI_KIT_ACCEPT_EULA=Y python tools/launch_isaac_robosyn_vr_demo.py`.
2. In Quest, open exactly
   `https://nvidia.github.io/IsaacTeleop/client/release-1.4.x/`. Select
   `Isaac Lab`, press `Reset to defaults`, select the `Quest 3` device profile,
   and connect through the working S2 CloudXR flow. Do not use the unversioned
   `/client` URL: it currently redirects to the older stable 1.3 client. Wait
   for both controllers to track. Confirm the table is slightly below eye
   level, ahead, and at 1:1 scale.
3. Before R3, with squeeze released, move each controller forward/right/up;
   confirm its robot follows the same visible directions. Then hold squeeze
   clutch so the robots stay still, face the desired workspace direction,
   press and release R3 once, and wait one second. Release clutch and repeat all
   three axes for both arms; confirm axes still match, neither arm jumps, and
   the CloudXR session never restarts.
4. Press X once. Confirm two rectangular panels show distinct live LEFT WRIST
   and RIGHT WRIST images rather than gray triangles; move each wrist to verify
   the matching image advances. Confirm both panels sit above the eye line and
   leave the robots unobstructed. Press X again and confirm only the panels hide.
5. Move each thumbstick independently left/center/right and confirm only that
   arm changes between 2×/4×/6×. Recheck both analog triggers, one clutch/rebase,
   and a brief tracking-loss/recovery. Pick and move one cube to confirm the retained
   no-shake grasp fix. Stop through the existing S2 path and keep the generated
   result/log directory.

Preflight status: `READY_FOR_PHYSICAL_RETEST`; not accepted.
