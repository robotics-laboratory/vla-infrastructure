# XR teleop coordinates, gray camera panels, and performance — 2026-09-15

This is a diagnosis and implementation proposal, not a physical acceptance.
Runtime code, dependency pins, gates and the resolved contract are unchanged.
The earlier [performance report](ISAAC_CAMERA_PERFORMANCE_20260915.md) contains
the measured upload costs and retained CloudXR timing analysis.

## Investigated stack

RoboSyn demo worktree: 9591f7f14a82ec33d0969c856b7ff52c97b5b842.
Isaac Lab checkout: 913ac53f51b2f8d02c9e121caa4cbdd06262948e.
Isaac Sim 6.0.1.0; isaaclab_teleop 0.8.0; isaacteleop 1.4.98rc1;
CloudXR 6.2.1; Kit XR core 109.0.0; scene_view.xr_utils 1.0.1;
omni.ui 3.2.0. RTX 4090 / driver 580.159.03.

Official Spatial documentation covers Kit 109.0.3+, while the installed XR
extension is 109.0.0. Conclusions about specific APIs were checked against
the installed Python wrappers. The xr_utils 1.0.2 documentation was similarly
checked against installed 1.0.1 WidgetComponent source. Its
[changelog](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.scene_view.xr_utils/1.0.2/CHANGELOG.html)
lists documentation changes for 1.0.2; upgrading this extension alone is not
an established fix.

## R3: what is established

R3 changes XR navigation/view placement, not robot/table geometry.
tools/isaac_s2_upstream.py:428 calls schedule_teleport_to_view with the scene
camera's full world pose and immediately requests a teleop reset.
tools/isaac_s2_runtime.py subsequently consumes the reset and reports
demo_xr_recenter_retargeters_rebased without recording the applied navigation
matrix or verifying that teleport completed.

The retained September 12 stdout contains three successful scheduling events
at lines 453, 464 and 512, followed by rebase messages at steps 107, 149 and
377. These prove request/reset handling, not correct axis mapping. There are
no saved before/after coordinate matrices or controller/TCP motion traces.

The existing _NavigationAwareXrAnchorManager already reads
XRCore.get_physical_to_virtual_world_transform. The installed wrapper explicitly
says this includes anchor pose, anchor-to-space-origin pose, and scaling.
Thus proposing this API as a new fix would duplicate an existing attempted fix.
The adapter transposes Gf's row-vector matrix into the pipeline's column-vector
representation. A bounded calculation using the exact pinned function bodies
passed this conversion and preserved a rightward controller delta after a
synthetic 90-degree navigation rotation.

There are three concrete correctness gaps:

1. Teleport scheduling and rebase have no completion barrier. Reset is tied
   to the request, rather than to the first tracked sample in the applied
   coordinate frame. The installed API documents a scheduled operation;
   [Spatial frame scheduling](https://docs.omniverse.nvidia.com/xr/omniverse-spatial-docs/109.0.3/development/core-concepts.html)
   places XR synchronization and application event handling at different frame
   points. This establishes a possible race, not proof that every R3 races.
2. Lab's configured default is pipelined, deadline-paced retargeting. The
   returned action can be an older completed frame. The application does not
   use last_step_info to reject an already-consumed frame or an output computed
   with an earlier navigation transform. This also permits replay of a relative
   delta when a completed frame is returned more than once.
3. When XR is active but its full transform is unavailable, the navigation-aware
   adapter falls back to the authored anchor. That silently changes coordinate
   semantics instead of holding motion until the full transform is valid.

The synthetic calculation also shows why the barrier matters: subtracting
controller poses expressed under two different origins creates a fictitious
1.52 m / 90-degree delta with an unchanged physical controller. Using the old
anchor after a 90-degree navigation change makes the requested rightward delta
perpendicular to the new view's right vector. These are controlled examples,
not measurements of the user's controller motion.

### Proposed R3 fix and decisive verification

First run the existing integration with
RetargetingExecutionConfig(mode="sync"). The installed IsaacTeleop/Lab APIs
support this, and upstream recommends it for current-frame debugging. See
[TeleopSession execution semantics](https://nvidia.github.io/IsaacTeleop/main/getting_started/teleop_session.html).
It separates stale output from a coordinate/basis disagreement; it is not by
itself a complete teleport fix. Execution mode is latched for a session, so
configure it before entering the session rather than changing it on R3.

On R3, hold native motion, schedule the view operation, and observe its applied
state at the XR synchronization boundary. Confirm the resulting HMD world pose
against the requested view pose and associate a new transform epoch with the
first valid controller sample. Only then reset relative retargeter references,
smoothing and processor rebase state, discard pre-epoch outputs, and resume with
a zero first delta. A repeated teleport may already target the current pose;
matrix inequality alone is not a sufficient completion criterion.

For each hand, record monotonic time, raw grip pose and source reference-space
handle, physical-to-virtual matrix, stage/XR units and up axis, transformed grip
pose, XRCore virtual-world grip pose, frame IDs, epoch, outgoing Cartesian delta,
and measured TCP displacement. Compare the same named grip pose at compatible
timestamps; aim and grip poses are different. Cross-checking with
XRInputDevice.get_virtual_world_pose localizes errors before IK. Do not apply a
second OpenXR-to-USD basis conversion to an already complete SDK transform.

Acceptance exercises: no-motion R3, repeated R3, and independent positive/
negative right, forward and up motions before and after navigation rotations.
For small translations away from limits/singularities, compare intended and
measured directions in the current viewer frame, and register the recording
and trace as physical evidence. Begin with precise 1x demo gains; current normal
mode's 4x translation and rotation gains amplify defects but do not explain a
coordinate rotation.

An additional latent IK issue exists in _BimanualDifferentialIk.apply: TCP poses
are expressed in robot base coordinates, while the Jacobian and incoming
Cartesian deltas are in world coordinates. Current demo bases have identity
orientation, and R3 does not rotate those bases, so this is not established as
the cause of the reported R3 failure. Make all three quantities share one frame:
either solve with world pose/world Jacobian/world delta, or rotate linear and
angular blocks of the Jacobian and both delta vectors into each arm's base.
Upstream advance(target_T_world=...) already supports a target-frame transform;
two independently oriented bases require per-arm composition. Retain upstream
DifferentialIKController. Rotate Cartesian vectors; do not add base translation
to a displacement.

## Gray triangles: what is established

Physical-session diagnostics at September 12 stdout line 349 show CUDA camera
sources, CPU-staged upload buffers, nonuniform RGB and opaque alpha=255.
Valid advancing wrist images continue through control step 660. The user's
headset report concerns final presentation; camera-output validation cannot
accept that presentation. CPU staging is already enabled and has not supplied
physical evidence of a working panel.

The panel uses ByteImageProvider -> ImageWithProvider -> WidgetComponent ->
XRSceneView, not an RTX image directly textured onto a robot-scene surface.
There is a verified dimensional mismatch in upstream camera_feed_kit_scene_ui.py:

| Quantity | Existing value for one wrist panel |
|---|---:|
| Physical width / total height | 0.36 m / 0.31 m |
| Intended texture size | 640 x 551 |
| resolution_scale | 1777.78 |
| unit_to_pixel_scale at XR meters_per_unit=1 | 1 |
| UI layout area implied by the sizing model | 0.36 x 0.31 UI units |
| Fixed label height / font size | 22 / 14 UI units |

The [WidgetComponent sizing model](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.scene_view.xr_utils/1.0.2/WidgetComponent.html)
and installed source distinguish UI layout from texture supersampling.
Multiplying resolution_scale increases texture resolution, without providing
the UI layout area required by a 22-unit label and the image. In general the
existing formula's layout width is width_m regardless of meters_per_unit.

A 16-control no-client Kit run confirmed actual components/textures at these
values. Both frames reported computed height 22, with computed widths about
64.54 and 73.78. An in-memory change redistributed the scaling to a 640 x 551
nominal UI layout while preserving texture and physical size. The frame's
computed content dimensions remained unchanged in this no-client run; it does
not establish recapture behavior or visible pixels in XR. Both wrists passed
16/16 valid advancing camera observations, and the application shut down.
The mismatch is confirmed; its responsibility for gray triangles is a strong
presentation-side hypothesis requiring an actual XR image comparison.

### Proposed panel repair and alternatives

Use physical dimensions in the correct coordinate system and a UI layout of
image-sized pixels: unit_to_pixel_scale=image_width/panel_width_units and
resolution_scale=1, with image_height and header height explicitly allocated.
For the existing 0.04 m header, reserve approximately 71 UI pixels at this scale.
Alternatively remove the header for the first image-only experiment. Keep
contiguous uint8 RGBA, explicit RGBA8_UNORM, correct [width,height] ordering, and
owned upload-buffer lifetime. This can be supplied by a narrow presenter/panel
delegate or a focused upstream patch, without changing Camera or the recorder.

Isolate presentation with a four-color checkerboard and frame counter:

1. Display it in an ordinary Kit image widget, then in a fixed world XR panel,
   then in a head-locked panel. Use the same byte buffer/provider.
2. Compare raw CPU and direct GPU uploads with the corrected layout. Capture
   desktop and XR display images; valid input or a non-throwing upload is not
   sufficient. The installed XRCore wrapper exposes schedule_capture_display_frame.
3. If fixed world presentation works but head-locking fails, inspect xrCamera
   prim validity, XR/stage coordinate conversions and the prim/translation/
   look-at source stack. Simplify to one placement transform before adding
   billboard behavior. Check startup versus XR restart initialization.

If SceneUI still cannot present a correct checkerboard, use two USD quads with
UVs, an unlit/emissive material, and a named dynamic texture. The installed
omni.ui 3.2.0 exposes
[DynamicTextureProvider](https://docs.omniverse.nvidia.com/kit/docs/omni.ui/3.2.0/omni.ui/omni.ui.DynamicTextureProvider.html),
which publishes CPU/GPU pixels at dynamic:// URIs for RTX materials. This avoids
the SceneUI widget-to-XR texture conversion while reusing sensor capture and the
same feed/session lifecycle. Retain providers and buffers; check image aspect,
UV orientation, material binding and back-face visibility. It is an available
alternative, not a physically verified implementation.

IsaacTeleop
[v1.4.142 release notes](https://github.com/NVIDIA/IsaacTeleop/releases/tag/v1.4.142)
also describe Televiz/OpenXR native QuadLayer support. This is a longer-term
upstream candidate with a different compositor/session boundary. It is not a
drop-in replacement for this Kit SceneUI presenter, and a second independent
OpenXR session should not be introduced casually. Qualify a coherent candidate
environment before migrating; do not update individual pins blindly.

## Performance: proposed order

The existing probes isolate two costs: active RTX render products and repeated
panel publication. Hidden panels still acquire and upload images. Wall-clock
max_update_hz=30 does not deduplicate frames or enforce camera render cadence.
At low XR FPS every physics-driven app update passes that throttle.

1. Replace the CPU sequence call set_bytes_data with the supported raw buffer
   upload set_raw_bytes_data in the narrow delegate, retaining buffer ownership.
   Prior controlled no-client probes reduced four-physics-step latency from
   193.89 to 85.57 ms (2.27x). GPU-to-CPU staging was only 0.178 ms per image.
2. Skip presentation publication for hidden panels and already-published sensor
   frames. Keep their bound sources alive. Do not call close/detach on X:
   the pinned shared-annotator teardown defect has already been observed.
3. Separate headset/Kit update cadence from redundant physics-driven uploads.
   One render per four physics ticks isolated a 3.20x improvement, and combined
   with raw upload reached 35.66 ms (5.44x). These are stage timings without a
   headset, not promised headset FPS. A 30 Hz headset loop is not an acceptable
   automatic consequence of targeting 30 Hz sensor images.
4. If RTX cost remains material, test preview-only downscaling and a coherent
   tiled-render configuration using the pinned Lab renderer. Preserve canonical
   D0 640x480 RGB observations. Disable the extra scene-camera render product
   after preflight only when no preview/validation consumer needs it; its USD
   camera prim can remain as the R3 viewpoint. Lowering Camera.update frequency
   or panel visibility alone does not necessarily disable a render product.
5. An explicit demo mode without camera acquisition can disable render-product
   updates and provide the camera-free comparison. It cannot claim valid D0
   observations or record a canonical camera dataset while sensors are off.
   Re-enable in a controlled phase and wait for fresh valid frames.

Measure requested headset resolution/frequency separately: retained logs show a
packed 4096x4032 stream with a 90 Hz format and about 9.6 Hz server XR cycle in
the slow September 12 session. The roughly 12.4 ms encode stage does not explain
the roughly 104.6 ms total cycle alone. Existing 14.1 ms incoming pose intervals
are not headset rendering FPS. Record timestamped X/R3 events, sensor frame IDs,
upload/render counts and CloudXR timing in a single A/B session.

## What other users and NVIDIA report

- [Multiple render products: 35 FPS to 5–8](https://forums.developer.nvidia.com/t/performance-of-render-product-in-action-graph/322300):
  a firsthand four-camera report; NVIDIA recommends lower resolution, staggering,
  tiled rendering and removing unnecessary annotators. This supports investigating
  render-product cost; it does not prove our slow provider boundary.
- [Scheduling under app.update, April 2026](https://forums.developer.nvidia.com/t/standalone-python-how-are-sensor-render-products-scheduled-under-app-update/363871):
  NVIDIA says active products render together and suggests enabling/disabling as
  an untested workaround. The reporter observed flicker and roughly 100 ms
  stabilization after re-enabling. Thus per-frame toggling should be measured,
  rather than presented as a free scheduling fix.
- [Render frequency despite a slower camera rate](https://forums.developer.nvidia.com/t/controlling-fps-of-createrenderproduct-createrenderproductfromviewport/273238):
  the reporter found camera-rate settings did not recover RTF; NVIDIA points to
  hydra_texture.set_updates_enabled. This matches the distinction between reading
  sensor output and enabling an actual render product.
- [Byte-image texture performance](https://forums.developer.nvidia.com/t/change-the-texture-with-2d-array-image-in-python-extension/245613):
  a user found different ByteImageProvider upload APIs had substantially different
  speed. It supports testing the boundary, but concerns another format/version;
  our raw-buffer benefit comes from our own pinned-stack measurements.
- [Isaac Lab issue #6822, July 31, 2026](https://github.com/isaac-sim/IsaacLab/issues/6822):
  Quest 3, Sim 6.0.1.0 and CloudXR 6.2.0, white/untextured scene and erratic arm
  motion in an upstream task. It remains open in the retrieved page. Unlike our
  recorded nonuniform wrist images, that report also has white camera outputs;
  its arm task uses absolute retargeting. It is relevant compatibility evidence,
  not an exact match or an identified fix for our two defects.
- [Older VR initialization failure, Sim 4.2](https://forums.developer.nvidia.com/t/vr-experience-still-broken-with-isaac-sim-4-2/307504):
  the author got tracking working by enabling VR before loading a new scene.
  This motivates testing lifecycle order, but cannot be applied as proof about
  the current Kit 109 / CloudXR 6 stack.

No retrieved issue demonstrates this exact gray-triangle panel defect or a
specific upstream commit that fixes it. Claims of an exact NVIDIA-known fix
would exceed the available evidence.

## Upstream audit and required final report

- CAPABILITY / GATE: experimental S2 XR teleop/presentation diagnosis.
- PINNED UPSTREAM CANDIDATES: installed clean Lab pin and exact packages above;
  DynamicTextureProvider in installed omni.ui; separately qualified IsaacTeleop
  v1.4.142/Televiz candidate only if the minimal presenter repair fails.
- WHAT UPSTREAM ALREADY OWNS / REUSED: XR navigation, pose conversion APIs,
  retargeting execution and telemetry, relative SE(3), DifferentialIKController,
  Camera/RTX rendering, feed session, SceneUI and dynamic-texture upload.
- EXACT REMAINING GAP: synchronized navigation-frame rebase and stale-output
  handling; incorrect panel UI dimensions; slow/duplicate hidden-frame uploads;
  physical verification of the user's two visual/control defects.
- PROCESSOR / CONFIG / ADAPTER REQUIRED: sync-mode diagnostic config, narrow
  navigation lifecycle handling and presentation delegate. No generic robotics
  framework, replacement recorder/runtime, solver, protocol or custom dataset.
- ENVIRONMENT IMPACT / EXECUTION PROFILE: declared isaac_vr_record / isaac,
  experiment-only bounded variants. No installed dependency/driver changes.
- WHY NO PROJECT FRAMEWORK IS NEEDED: public upstream boundaries provide the
  transforms, frame metadata, controller, panel and texture operations.
- PINNED / VERIFIED: matrix/right-delta calculations with pinned function bodies;
  live no-client Kit component inspection; retained physical logs.
- CONTRACT CHANGES: none. Proposed presentation changes preserve policy-facing
  D0 images; a camera-free demo mode would explicitly be outside D0 acceptance.
- EVIDENCE ADDED: diagnostic artifacts only, not gate registry acceptance.
- ARTIFACTS ADDED: this report, two probe scripts/results, full panel probe log,
  S2 smoke result, and hashed source references under performance/20260915.
- PROCESSORS / ADAPTERS: only temporary in-memory diagnostic changes executed.
- TESTS: pinned matrix/right-delta assertions passed; panel probe exited 0 with
  16/16 valid and advancing wrist observations and orderly application shutdown.
  No live controller tracked and no XR teleport actually executed in that probe.
- HUMAN EVIDENCE: user's reported R3 direction failure and gray triangles remain
  unregistered observations; no new physical recording was created.
- BLOCKERS / REOPEN REASONS: exact physical cause and acceptance of proposed
  repairs need an active Quest session with coordinate traces and image capture.
  No gate was reopened or accepted by this investigation.
- NEXT GATE: retain S2 state, implement the minimal experiment changes, then
  register Quest evidence for direction after R3, visible wrist images and FPS.
