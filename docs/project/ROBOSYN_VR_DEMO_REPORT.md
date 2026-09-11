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
`[-0.05, 0, 1.20]`, quaternion
`[0, 0, -0.7071067812, 0.7071067812]`, and near plane `0.10 m`. This maps XR
forward to scene `+X` and places the shared workspace in front of the viewer.
Physical comfort remains part of the Quest run; no robot geometry was moved to
compensate for presentation.

## Wrist-camera panels

The implementation is upstream `isaaclab_teleop` `XrCameraFeedSession` with
`XrCameraFeedCfg`, horizontal viewer-start layout, and the Kit SceneUI
presenter. The XR smoke confirmed feed-owned zero-copy CUDA annotators for both
`left_wrist` and `right_wrist`.

The audited `ControllersSource` exposes grip pose/valid, primary, secondary,
thumbstick X/Y/click, menu, squeeze, and trigger. Existing S2 owns squeeze
clutch, analog trigger gripper, thumbstick-click sensitivity, and its existing
control-event path. Left `SECONDARY_CLICK` (Quest Y) was therefore selected as
the demo-only rising-edge display toggle. It is appended after the unchanged
22-value S2 pipeline output and is removed before the existing S2 processor.

DISPLAY OFF closes only presenter/display resources; DISPLAY ON binds and
refreshes the two panels. Both wrist cameras keep acquiring in both states.
No performance improvement is claimed for hiding the panels. Actual runtime
sensor disable/pause was intentionally not added, and there is no demo
performance mode.

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
- Core tests: `70 passed, 4 skipped` (the skips are environment-conditioned).
- Exact Candidate B S2 processor/upstream tests: `16 passed`.
- Stock S2 launcher regression: PASS, clean exit, 60 valid and strictly
  advancing bimanual frames:
  `/data/ebulochkin/cache/isaac-s2/runs/20260910T181935Z/result.json`.
- Stock S1 launcher regression: PASS, including FK, joint/gripper parity,
  success/timeout task behavior, reset, and both 110-frame camera sequences:
  `/data/ebulochkin/cache/isaac-s1/runs/20260910T182015Z/result.json`.
- Tracking-loss recovery, clutch/rebase, analog gripper, and independent
  normal/precise sensitivity semantics remain covered by the unchanged S2
  processor tests. A controller-source unit test covers the new isolated Y
  field without changing the S2 action prefix.

No physical Quest was connected during these automated runs, so simultaneous
human control, headset comfort, physical tracking recovery, and in-headset Y
toggle remain the explicit demo checks. This does not mark S2 accepted.

## Physical Quest demo procedure

1. From the experiment worktree, start exactly:
   `OMNI_KIT_ACCEPT_EULA=Y python tools/launch_isaac_robosyn_vr_demo.py`.
2. Connect Quest 3 through the same working S2 CloudXR flow; wait for both
   controllers to report tracking and confirm the table is comfortably below
   eye level with both arms ahead at 1:1 scale.
3. Move left, right, then both arms. Verify independent squeeze clutch/release,
   analog triggers, and each thumbstick-click normal/precise transition.
4. Briefly lose and restore tracking on one controller; confirm the recovered
   arm rebases without a TCP jump. Exercise the existing Start/Stop/Reset path.
5. Move each colored cube onto its matching plate.
6. Press left-controller Y once: confirm two compact labelled wrist panels
   appear without blocking the task. Press Y again: confirm both disappear.
7. Confirm the scene framing remains centered and operate for several minutes
   without XR instability; stop through the existing S2 control path and keep
   the generated `/data/ebulochkin/cache/robosyn-vr-demo/runs/.../result.json`.

Preflight status: `READY_FOR_PHYSICAL_DEMO`.
