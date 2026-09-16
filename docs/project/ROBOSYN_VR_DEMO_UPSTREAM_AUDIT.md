# RoboSyn-inspired VR demo upstream audit

This audit covers an isolated experiment only. It accepts no gate, reopens no
S0/S1/S2/D0 decision, and does not change the canonical D0 schema.

## CAPABILITY / GATE

Compose a playable dual-PIPER-X tabletop scene, an optional test-asset profile,
a non-contract scene camera, and wrist-camera panels in XR. Gate: none
(`EXPERIMENTAL_TEST_ONLY`). The existing S2 runtime remains unresolved and is
reused without claiming acceptance.

## PINNED UPSTREAM CANDIDATES

- Isaac Lab release/3.0.0, commit
  `913ac53f51b2f8d02c9e121caa4cbdd06262948e`, package 16.4.0.
- Isaac Sim 6.0.1, `isaaclab_teleop` 0.8.0,
  `isaacteleop` 1.4.98rc1, CloudXR 6.2.1.
- Existing Gate C PIPER-X composed URDF and converted geometry, unchanged.
- RoboSynChallenge snapshot
  `9815e9eee86f3dda88860ca971f71354f157d41c`, local test-only checkout under
  `/data/vla-infrastructure/assets/robosyn_vr_demo/RoboSynChallenge`.

## WHAT UPSTREAM ALREADY OWNS

- App/XR/CloudXR session lifecycle and one bimanual `ControllersSource`.
- SE(3) retargeting, the existing tracking-safe S2 edge adapter, clutch/rebase,
  analog gripper and sensitivity semantics.
- Isaac Lab `DifferentialIKController`, articulations, rigid objects, PhysX,
  URDF/mesh conversion, cameras and render products.
- `XrCameraFeedSession`, `XrCameraFeedCfg`, `XrCameraFeedLayoutCfg`, and the Kit
  SceneUI camera-panel presenter, including its existing zero-copy/fallback
  upload path.
- Kit `XRCore.schedule_teleport_to_view` for presentation recentering and
  `XRCore.get_physical_to_virtual_world_transform` for the corresponding full
  anchor, navigation-space-origin, axis, and scale transform.

## EXACT REMAINING GAP

- Instantiate the specified experimental table, bases, lights, procedural task
  objects and scene camera without changing S1 production construction.
- Expose the two existing wrist-camera viewpoints as distinct named upstream
  Camera instances because upstream PiP selects batch element zero of a named
  camera; preserve the existing two-image D0 edge through a demo-only facade.
- Route the free left secondary/Y field to both existing sensitivity inputs,
  append the free left primary/X field for a rising-edge display toggle, and
  append free right secondary/B for visual-only backdrop visibility.
- Bind the upstream feed session once, show/hide its existing SceneUI
  `UiContainer` without detaching the shared RGB annotator, close only at final
  shutdown, and collect demo-only diagnostics. Physical capture diagnostics
  show valid non-uniform RGB and opaque alpha before the gray triangulated
  panels, localizing the remaining compatibility gap downstream of capture;
  bypass the direct CUDA-pointer SceneUI branch through the presenter's
  supported CPU `ByteImageProvider` path without changing acquisition or panel
  ownership.
- After R3 teleport, feed `ControllersSource` the full upstream
  physical-to-virtual transform rather than the authored anchor alone. This
  keeps controller deltas aligned with the newly presented world and then uses
  the existing S2 reset/rebase path to avoid a command jump.
- Import a small number of low-repair RoboSyn test assets and quarantine the
  rest rather than building asset infrastructure.

## PROCESSOR / CONFIG / ADAPTER REQUIRED

- One experiment YAML plus one test-asset manifest.
- One concrete demo scene composer/camera facade and one launcher.
- Three optional one-float outputs (`left_primary_click`,
  `right_secondary_click`, `right_thumbstick_click`) appended after the
  unchanged 22-value S2 action.
  The S2 processor receives exactly its original first 22 values; the demo
  config routes `left_secondary_click` into both existing per-arm sensitivity
  slots and selects only demo gains.
- One demo-only navigation-aware subclass of the pinned `XrAnchorManager` and
  one narrow presenter delegate that stages the unchanged upstream RGBA tensor
  to a reusable CPU buffer. Production S2 retains its original anchor manager
  and upload path.
- No new policy processor, task backend, recorder, IK implementation, camera
  protocol, or D0 field.

## ENVIRONMENT IMPACT

The experiment runs in the existing frozen Candidate B environment. No package
is added. RoboSyn sources and any generated conversion cache stay under
`/data/vla-infrastructure`; no large binary is committed or redistributed. Default S1
and S2 config/launch paths are unchanged.

## WHY NO PROJECT FRAMEWORK IS NEEDED

There are two small profiles in one fixed scene composition. A concrete scene
builder, a profile branch, and upstream Isaac Lab objects cover the entire gap;
a backend, registry, task hierarchy, second teleop stack, or asset bank would
only duplicate upstream ownership.

## CODE-SIZE RE-AUDIT

`tools/isaac_robosyn_vr_demo.py` exceeds the 300-line integration-module audit
threshold because it contains explicit scene spawning, two fixed profile
branches, camera validation, and result assembly. Re-auditing the reuse ladder
does not expose another upstream abstraction to adopt: Isaac Lab still owns
simulation assets and sensors, while `isaaclab_teleop` owns XR presentation.
Factoring the remaining concrete composition into backend, registry, task, or
sensor frameworks would add indirection without removing an integration gap.
