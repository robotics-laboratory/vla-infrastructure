# Gate S2 upstream audit

Date: 2026-09-08

## Mandatory upstream audit

| Item | Resolution |
|---|---|
| Capability / gate | Gate S2, physical Quest 3 to simulated bimanual PIPER-X |
| Pinned upstream candidates | The sole selected runtime is Isaac Lab `release/3.0.0` at `913ac53f51b2f8d02c9e121caa4cbdd06262948e`, Isaac Sim `6.0.1.0`, in-tree `isaaclab_teleop==0.8.0`, frozen-lock `isaacteleop==1.4.98rc1`, and its bundled CloudXR `6.2.1` runtime. Gate B remains separately pinned to `isaacteleop==1.3.131` at `7002ed63d69454ae4f15c0ee19f803fd2846592b` and CloudXR `6.2.0`. |
| What upstream already owns | XR Kit experiences; CloudXR launch; OpenXR handle acquisition; one `TeleopSessionLifecycle`; controller tracking; controller-to-Isaac anchor transform; relative SE(3) filtering/deadband; recovery/rebase seams; `DifferentialIKController`; articulation and camera lifecycles. |
| Exact remaining gap | Bind one coherent left/right controller source to the accepted two PIPER-X articulations; define PIPER-X-specific clutch, sensitivity, tracking-recovery, analog gripper, scale, XR presentation, and reset semantics; close the pinned relative-retargeter absent-input state gap; retain human evidence. |
| Processor / config / adapter required | One concrete pure bimanual processor, one fixed upstream pipeline composition, one narrow relative-retargeter subclass for absent/unusable pose recovery, one narrow lifecycle subclass that suppresses Candidate B's redundant anchor-hotkey controller source, and one S1-loop integration branch. |
| Environment impact | Activate only Candidate B's exact frozen `teleop` extra inside `/data/ebulochkin/envs/isaac-s1-candidate-b`. No core change, global repin, out-of-lock package, or upstream-checkout mutation. |
| Why no project framework is needed | Candidate B owns application, session, XR, retargeting, IK, articulation, and camera behavior. The project code is a PIPER-X edge mapping, not a simulator/robot/camera backend or generic teleop layer. |

## Selected upstream seams

`XrAnchorManager` defines the controller-frame conversion. OpenXR is right-handed,
Y-up (`+X` right, `+Y` up, `+Z` back); its upstream fixed basis produces Isaac
Z-up coordinates `isaac[x,y,z] = openxr[x,-z,y]`, followed by the configured
anchor transform.

`Se3RelRetargeter` consumes controller grip poses in XYZW quaternion order. It
computes spatial relative orientation as `R_current * inverse(R_previous)`, with
position/rotation alpha `0.5`, pre-scale deadbands `0.001 m` and `0.01 rad`, and
NVIDIA's relative-pose defaults of `10.0` translation and `10.0` rotation. The
first physical S2 run found those gains unusably high for PIPER-X. S2 therefore
keeps upstream filtering/deadband but moves explicit, symmetric PIPER-X gains
to two config-selected modes: normal `2.0/2.0` and precise `0.5/0.5`.

The pinned relative retargeter correctly clears its first-frame baseline and
smoothing when a present controller reports `GRIP_IS_VALID=false`, but its
`inp.is_none` branch emits zero without clearing either state. Recovery at a
different pose then computes against the stale wrist pose and blends the large
delta through the old smoothing accumulator. `TrackingSafeSe3RelRetargeter` is
a version-pinned subclass that applies the same invalidation to absent,
explicitly invalid, non-finite, or zero-quaternion poses, then delegates every
valid sample and all SE(3) math upstream. It is not a second IK or retargeting
framework.

Isaac Lab's `DifferentialIKController` in relative-pose/DLS mode left-multiplies
the spatial rotation delta onto the current TCP orientation. Its output is
clipped to the accepted Gate C joint limits before entering the existing S1
`NativeBimanualTargets` position-target path. No FK/IK implementation is added.

The selected pipeline contains exactly one `ControllersSource`; its LEFT and
RIGHT outputs feed two independent relative-pose retargeters and two small state
extractors. Candidate B's normal lifecycle adds a second optional source only to
poll anchor hotkeys. S2 carries squeeze, analog trigger, and thumbstick-click
state through its required action and therefore suppresses that redundant
convenience source while inheriting every other lifecycle behavior. Per-arm
thumbstick click is otherwise unused by the selected session controls: the
client message channel owns start/stop/reset, squeeze remains clutch, trigger
remains gripper, and right primary remains upstream anchor rotation.

## Concrete semantics

- Physical LEFT remains on the LEFT branch and physical RIGHT on RIGHT.
- Controller spatial deltas and TCP targets use Isaac world axes. Both accepted
  S1 bases have identity rotation, so the same axes apply in each base frame.
- Squeeze above `0.5` is an independent per-arm clutch. While held, motion is
  zero; release discards one delta and rebases.
- Each controller's thumbstick click toggles only that arm between normal and
  precise sensitivity on a rising edge. The switching frame emits zero motion.
- Trigger `[0,1]` maps linearly and monotonically to the accepted Gate C native
  aperture from `0.1 m` fully open to `0.0 m` fully closed; reset uses `0.05 m`.
- Missing, unavailable, invalid, non-finite, or default-invalid tracking emits
  zero motion, holds the simulated target, and invalidates that arm's upstream
  pose baseline and smoothing. The opposite valid arm is unaffected. The first
  recovered pose establishes a new baseline with zero delta; later samples
  resume relative control without requiring clutch.
- Session disconnect holds both simulated targets. Reconnect cannot replay stale
  deltas. No numeric XR pose-age threshold is invented.
- Environment reset also resets upstream/processor/IK state and requires a new
  per-arm reference.
- A static XR anchor `(0.0, -0.6, -1.05)` changes presentation only, placing the
  world origin forward and higher in the user's view. Gate C/S1 geometry is not
  moved.

## Runtime boundary

The authoritative path is:

```text
Quest 3
-> CloudXR 6.2.1 / isaacteleop 1.4.98rc1
-> isaaclab_teleop 0.8.0 lifecycle
-> one LEFT/RIGHT ControllersSource
-> concrete S2 processor
-> upstream DifferentialIKController
-> accepted S1 NativeBimanualTargets
-> simulated bimanual Gate C PIPER-X
```

There is no LeRobot import, recorder, dataset action claim, RPC, second scene,
second camera path, CAN access, or physical PIPER motion in this gate.

## Acceptance boundary

Synthetic processor tests and no-client runtime smokes do not prove physical
identity, axes, scale usability, clutch feel, tracking recovery, or reconnect.
Gate S2 remains unresolved until an explicit physical Quest human-gate artifact
passes every required check.
