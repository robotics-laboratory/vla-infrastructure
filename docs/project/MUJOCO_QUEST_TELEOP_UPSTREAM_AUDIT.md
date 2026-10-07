# MuJoCo Quest teleoperation upstream audit

Date: 2026-09-29

Status: additive configured profile; no v5.2 gate is accepted by this document.

The normative v5.2 scope requires Quest teleoperation for Isaac and policy
evaluation for MuJoCo. The user-requested Quest-to-MuJoCo path is therefore an
additive operator profile over the concrete M1 environment. It does not start
or accept E2. Physical run 4 exposed contradictions in the old M1 wrist-camera
and gripper-contact assumptions, so that narrow scope was repaired and the full
M1 evidence was rerun before this profile advanced to v6. Physical run 5 then
showed that passive follower constraints and the upstream default deadband still
lost aperture and fine reach during multijoint motion; the narrow M1 gripper
plant was revalidated again before the profile advanced to v7. Physical run 6
then contradicted that evidence: the fingers still floated and cube grasp failed.
M1 is therefore reopened. Later feedback accepted direct finger control but
found cube pickup marginal, so plant v7/profile v9 raised the bounded finger
force from 8 N to 10 N. Run 7 then showed large symmetry error when either
independent finger met the cube. Plant v8/profile v10 adds only a mechanical
`q1=-q2` relation between the two physical fingers. The first overly stiff
candidate lost cube contact in the retained regression, so the stable constraint
reference was restored. It held symmetry below 0.01 mm but lost the left cube at
tick 293/300 with 10 N and earlier at tick 274/300 with 12 N. Plant v11/profile
v13 therefore uses 8 N with the coupled fingers. It retained contact for
300/300 ticks but shifted 20.143 mm against the strict 20 mm bound; plant
v12/profile v14 tried pad sliding friction 1.6, which lost contact at tick 292.
Plant v16/profile v18 retained the `condim=6` grasp fix and separated camera
visuals from coincident collision meshes. Its NVIDIA EGL checks passed, but
physical run 8 showed pose-dependent collapse of commanded-open fingers while
the opening-direction servos were limited at 8 N. Profile v19 raises only the
mirrored opening-direction limit to 12 N and leaves the validated closing limit
at 8 N. Physical run 9 showed that the asymmetric range must not remain active
during contact: profile v20 enabled it only for accepted targets at or above
95 mm. Physical run 10 still produced impossible open apertures and large
finger-symmetry errors. Profile v21 removes the v19/v20 force experiment,
restores symmetric 8 N authority everywhere, and moves the repair to M1 v17's
thin distal collision pads. It requires focused automated and physical evidence.
On 2026-09-28 the operator ran the six focused v21 checks; all six passed in
2.06 seconds with one non-blocking upstream `hppfcl` import deprecation warning.
Physical run 11 then restored reach and repeatable cube contact but still lost
the cube during motion. Profile v22's angled proximal extension failed its
focused offset-grasp regression at tick 240 despite `0.003 mm` symmetry error.
Profile v23 changed no controller or actuator setting and reused M1 v19's
continuous thin planar grasp insert, but its width exactly matched the cube and
contact was lost earlier at tick 215 despite `0.004 mm` symmetry. Profile v24
reuses M1 v20's `48 mm` width, restoring 4 mm lateral margin per side while
retaining the continuous `66 mm` length and `2 mm` thickness. Full
NVIDIA EGL and physical Quest evidence remain pending.

Physical v24 then contradicted both retained-grasp and symmetric-motion
assumptions: a manually acquired cube still chattered out, and equal down intent
sent the right arm primarily sideways. The log reported zero IK exceptions but
320 gripper force-limit frames. Audit of Dream Machines Robotics'
`vr-teleop-kit` found no alternative MuJoCo contact plant to reuse: that project
uses MuJoCo for FK/Jacobians and a passive viewer, while its DK1-specific solver
separates position and orientation. V25 therefore keeps upstream
LeRobot/Placo, restores its `1.0/0.01` position/orientation weighting, and adds a
post-IK Cartesian direction guard with a position-only retry through the same
public solver. M1 v22 replaces the over-constrained two-finger servo plus hard
equality with a standard actuated MuJoCo aperture tendon, a soft constraint on
the passive centre tendon, and explicit pad/cube contact pairs. V26 force diagnostics then
identified the remaining pre-contact stall: both rectangular grasp-surface proxies contacted
the table, whose constraint force cancelled the bounded aperture actuator almost exactly.
M1 v23 disables generic collision for those pads while retaining their explicit cube pairs;
arm geometry, IK, friction and force limits are unchanged. The subsequent force history
showed `20-22 mm` penetration into the `40 mm` cube before ejection. A direct
`solref=[-10000, -200]` candidate then ejected even centred cubes during closure
at the `120 Hz` timestep and was rejected. A high-impedance
`solimp=[0.99, 0.999, 0.001]` candidate reduced penetration below one millimetre
but still rotated and ejected a centred cube during small wrist motion. M1 v26
therefore restores the centred-grasp-stable `0.9/0.95` impedance. An enlarged
rotational-friction candidate was also rejected: it left the offset failure
unchanged and introduced a late centred-grasp failure. M1 v27 retained only the
proven explicit-pair/table-filtering correction with the original contact
friction and 8 N force limit. Physical v26 still dropped a manually acquired
cube. M1 v28 therefore leaves geometry, friction, impedance and force unchanged
and raises only internal physics from 120 to 240 Hz, with eight zero-order-held
steps per 30 Hz control tick. Quest v27 also clears the upstream relative-pose
and smoothing state on every paused/reset frame; previously menu-pointing motion
left a path-dependent smoothing tail after Play. Physical v27 then confirmed
repeatable arm motion and successful cube transport, with only a small jerk as
the closing actuator reached its 8 N limit. Quest v28 reduced closing to
5 mm/tick, but physical validation reported worse cube shaking, so that
candidate is rejected. Quest v29 restores the v27 10 mm/tick opening and
closing ramps; force, contacts, physics rate and arm control are unchanged.
Physical v29 then exposed two independent residuals: filtered right-controller
rotation steps of 0.064-0.070 rad coincided with asymmetric joint-target lag,
and a constant zero-aperture/8 N grasp oscillated from 44.8 to 52.0 mm. Quest
v30 therefore bounds both arms to 0.05 rad per control tick and raises only the
aperture velocity damping from 30 to 45. Translation gain, basis, IK, static
grip force, contacts and command slew remain unchanged. This is a revalidation
candidate, not accepted evidence.
Physical v30 was not a valid bimanual motion/grasp trial: the retained report
contained 907 valid left frames and zero valid right frames, while the right
joint target remained exactly at home. Quest v31 makes `--require-tracking` a
startup interlock rather than an end-of-run assertion: neither arm actuates
until both grip poses are present, all stateful edges are then rebased, and a
missing side fails explicitly after 10 seconds. No joint sign, basis, IK or
gripper parameter changes from v30.
Quest v32 tested an identity controller-to-M1 map, but physical v32 rejected it:
both controllers supplied 1194 valid frames and almost no operator action
matched the intended direction, preventing either arm from reaching its cube.
The same run isolated a separate cause of apparently random joint motion: it
reported 245 Cartesian saturation frames, frequent controller rotation at the
0.05 rad bound, and wrist-joint excursions of tens of degrees while achieved
translation retained alignment `1.0`. Quest v33 restores `[-z, -x, y]` for
controller forward/right/up and makes the existing upstream Placo task
position-only (`orientation_weight=0.0`). Non-zero ignored rotation remains
reported as Cartesian saturation. Joint order/signs, translation gain and all
gripper/contact parameters remain unchanged.
Physical v33 then confirmed coherent translation with no IK failures or joint
saturation, but its position-only task left joint6 fixed at zero and joint5
nearly stationary while the operator moved both arms with straight wrists.
Quest v34 keeps the validated basis and translation path, restores the same
upstream Placo orientation task at weight `0.001`, and bounds controller
rotation to `0.005 rad/control tick`. Both values are one tenth of v32; the
gripper, contacts, joint order/signs, limits and translation gain are unchanged.
Physical v34 then showed that every MuJoCo joint followed its target, but
integrated controller rotation accumulated 1096 Cartesian saturation frames,
moved the left distal joints through roughly 58-63 degrees, did not improve
operator translation and regressed grasp quality. Quest v35 does not integrate
controller rotation. It keeps Placo's upstream default orientation weight
`0.01` so translation preserves the current accepted gripper orientation and
the six-joint chain is no longer underconstrained. Ignored rotation remains
reported. No gripper or contact parameter changes.
Physical v35 confirmed good translation and grasp but, as designed, no direct
wrist rotation. Quest v36 retains the v35 translation/grasp path and accepts a
rotation delta only when its scaled magnitude is at least `0.004 rad` while
simultaneous scaled translation is at most `0.00075 m`. Applied rotation remains
bounded to `0.005 rad/control tick`; rejected intentional rotation is reported.
Physical v36 showed that normal Quest positional drift made this inference
unusable: only 3 of 20 sampled rotation requests passed. Quest v37 removes the
numeric gesture inference. The existing per-controller `SECONDARY_CLICK` is an
explicit rotation-mode hold: Y for left and B for right. Released preserves the
validated v35 translation/grasp path; held passes bounded controller rotation.
Physical v37 reported the rotation mode false and zero rotation delta in every
retained row, so that button path is rejected. Quest v38 removes both failed
gates and admits scaled rotation at `0.006 rad`, just above the observed
`<=0.0055 rad` noise band. Deliberate samples reached `0.05-0.067 rad`.
Physical v38 passed rotation above that boundary in 7 retained left rows and 8
right rows. MuJoCo joint5/joint6 targets and measured positions followed through
tens of degrees (left minima `-28.434/-22.062` degrees), with no IK failures or
joint saturation, but the operator still observed the corresponding mechanisms
as unmoving. A direct headless official-renderer sweep subsequently showed that
joint5 and joint6 rotate both complete gripper visual chains by the commanded
`+/-20 degrees`, exactly and symmetrically. This rules out detached visual
geometry. It also exposed that v38 clipped the observed deliberate
`0.05-0.067 rad` controller samples to `0.005 rad`, discarding roughly 90% of
the intended rotation. Quest v39 therefore restores the earlier `0.05
rad/control tick` safety bound while keeping the measured `0.006 rad`
activation threshold. Translation, gripper physics and contact parameters are
unchanged.

## Mandatory upstream audit

| Item | Resolution |
|---|---|
| Capability / gate | Physical Quest 3 controls `PiperX-DualCubeToMatchingPlate-Mujoco-v0`. This is profile `piperx_mujoco_quest_teleop_v39`, not a new normative gate and not E2; M1 is reopened for revalidation. |
| Pinned upstream candidates | Core `isaacteleop==1.3.131` at `7002ed63d69454ae4f15c0ee19f803fd2846592b`, bundled CloudXR `6.2.0`, its `TeleopSession`, one `ControllersSource`, `Se3RelRetargeter`, and Televiz `VizSession`/`QuadLayer`; LeRobot `0.6.1` `RobotKinematics` backed by Placo `0.9.15`; accepted MuJoCo `3.9.0` M1 environment and D0 edge processor. |
| What upstream already owns | CloudXR/WebXR lifecycle and `teleop_command` UI messages; graphics-bound OpenXR session; `MessageChannelSource` and `DefaultTeleopStateManager`; sharing that session with controller trackers; LEFT/RIGHT acquisition; SE(3) relative filtering and deadbands; CUDA-to-XR quad composition; PIPER-X FK/IK; MuJoCo physics/rendering; Gymnasium lifecycle. |
| Exact remaining gap | Compose one OpenXR session and the Isaac-compatible Play/Stop/Reset channel, expose the PIPER-X clutch/sensitivity/analog-gripper semantics, map controller forward/right/up into M1, preserve the accepted gripper orientation below the measured rotation noise boundary while admitting deliberate wrist rotation, persist safe actuator targets across plant lag, command one compliant physical aperture whose grasp-surface proxy uses only explicit cube pairs, anchor fixed panels, expose Cartesian/joint/gripper diagnostics, and close MuJoCo EGL before the graphics-bound session is released. |
| Processor / config / adapter required | One MuJoCo-specific upstream graph with tracking reset and a measured rotation threshold; one task-local WebXR command parser; one pure MuJoCo Quest IK/D0 adapter with held-orientation translation and achieved-direction validation; one fixed-tendon aperture mapping in the existing concrete environment; explicit task pad/cube pairs; one fixed runtime config and launcher. |
| Environment impact | Activate the already locked root `isaac-teleop` dependency group in `core`. No Isaac environment, upstream checkout, CAN interface, or real PIPER process is used. |
| Why no project framework is needed | The concrete M1 environment remains the only simulator object. The added code is one task-specific controller/IK/display composition, not a simulator backend, XR protocol, registry, robot abstraction, or replacement renderer. |

## Selected runtime path

```text
Meta Quest 3
-> CloudXR 6.2.0 / Televiz graphics-bound OpenXR session
-> upstream teleop-command MessageChannelSource / DefaultTeleopStateManager
-> the same session shared with one bimanual ControllersSource
-> upstream Se3RelRetargeter filtering/deadband
-> accepted S2-v2 clutch/sensitivity/analog-gripper state policy
-> LeRobot RobotKinematics / Placo IK
-> accepted D0 degrees + millimetres
-> PiperXMujocoActionProcessor
-> concrete reopened M1 MuJoCo environment
-> scene + left/right wrist RGB QuadLayers
-> Meta Quest 3
```

M1 declares `+X` forward, `+Y` operator-left and `+Z` up. Physical v32 rejected
passing the controller tuple through unchanged. Quest v39 retains the proper
rotation `[-z, -x, y]`, so controller forward/right/up becomes M1
forward/right/up. Both robot bases have identity orientation, so no per-arm
axis or joint-sign map is added. Controller rotation passes through the same
coordinate audit and enters the existing upstream orientation task when its
scaled magnitude reaches the measured `0.006 rad` activation boundary. The
task uses weight `0.01` to preserve orientation below that boundary and bounds
an admitted sample to `0.05 rad/control tick`.

## Deliberate presentation boundary

Version 1 presents the fixed M1 `scene` camera as the main XR panel and the two
policy wrist cameras as smaller panels. V5 captures one valid HMD pose at
session start, composes configured head-relative offsets into Televiz's OpenXR
stage space, and then leaves the panels world-stable. This removes dependence
on the Quest floor/stage calibration that placed the old absolute-Y panels too
high. The Televiz clear alpha is zero so its selected `ALPHA_BLEND` environment
mode retains passthrough outside the panels instead of displaying an opaque
projection-layer region. This is a real Quest visual/control loop, but it is not
claimed to be a head-tracked stereoscopic reconstruction of the MuJoCo world.
Televiz still owns the XR compositor and session; project code only composes
poses and submits the three existing camera images.

## Safety and semantics

- This profile drives only MuJoCo. It imports no CAN or real-robot package.
- The execution state starts STOPPED. WebXR Play alone enters RUNNING; Stop
  pauses and holds the complete D0 state; menu Reset resets M1 and pauses.
- Before the first Play, all three panels are black and controller pose/trigger
  activity is ignored. This prevents menu pointing and selection clicks from
  becoming robot or gripper commands.
- LEFT stays LEFT and RIGHT stays RIGHT.
- Squeeze is an independent per-arm clutch.
- Thumbstick click independently toggles normal/precise sensitivity.
- The v25 normal translation/rotation gain remains `0.5`: physical run 3 found the
  unit-gain persistent MuJoCo target still too sensitive for comfortable use.
  Precise gain is `0.125`, retaining the established four-to-one mode ratio.
  Isaac S2 keeps its separately qualified `2.0/0.5` values; copying them after
  the MuJoCo persistent-target correction made the physical response too
  sensitive and is not a shared policy-facing contract requirement.
- Physical run 5 showed that upstream's fixed `1 mm` translation and `0.01 rad`
  rotation deadbands discard slow deliberate motion before the half-scale gain.
  The narrow subclass retains upstream smoothing/math but sets the profile
  thresholds to `0.25 mm` and `0.0025 rad`; sensitivity gains are unchanged.
- Trigger maps monotonically from `100 mm` open to `0 mm` closed.
- Missing, invalid, non-finite, or zero-quaternion tracking holds the affected
  arm and clears its upstream relative-pose history.
- The first recovered pose rebases with zero motion.
- Right primary button requests a complete deterministic M1 reset; the next
  controller sample also resets upstream relative state.
- IK output is clipped to accepted Gate C limits and to a configured per-tick
  joint step. Every clip is reported; it is never silent.
- Relative Cartesian deltas are integrated from the last accepted D0 actuator
  target, which is held after controller motion stops. A `25 degree`
  target-to-measured bound prevents the command from running away from the
  MuJoCo plant. Computing every delta from lagging measured qpos had discarded
  the prior target each frame and made translations weak and rotations vanish.
  Physical run 5 reached `14.738 degrees` while Cartesian saturation stayed
  zero, so v25 retains this lag guard; accepted joint limits and the
  `8 degree/control-tick` target step bound remain unchanged.
- Physical v24 then showed unequal Cartesian response despite zero IK
  exceptions. The frame task had equal `1.0/1.0` position/orientation weights,
  so incidental controller rotation dominated millimetre translation. V25
  uses upstream `RobotKinematics`' `1.0/0.01` default balance, measures the FK
  direction achieved after all joint bounds, and retries the same public
  solver with orientation weight zero when alignment is below `0.5`. A command
  is held and reported as failed if it still points in the wrong direction.
- Gripper commands hold during inactive/rebase frames. After every Play, reset,
  or tracking recovery, each side must first observe released-trigger intent
  corresponding to at least `95 mm` aperture; that arming sample itself holds.
  This prevents the trigger click used on the WebXR Play menu from becoming an
  initial close command. Once armed, opening changes by at most `10 mm` and
  closing by at most `5 mm` per control tick from the prior accepted gripper
  target. Arming and slew limiting are reported separately from Cartesian and
  joint saturation.
- Physical run 6 showed that the old compatibility leader plus follower
  constraints formed an overdetermined plant. Later direct-finger candidates
  added a hard symmetry equality, but physical v24 still chattered under
  sustained force limiting. M1 v22 now represents the single physical aperture
  as a fixed MuJoCo tendon `q1-q2` with command gain and position bias `1250`,
  damping `30`, and `[-8,+8] N`. Each finger retains `0.1 kg` armature and
  `2 N s/m` damping but has zero joint stiffness. A soft equality constrains a
  passive `q1+q2` tendon to zero with `solref=[0.02,1]` and
  `solimp=[0.9,0.95,0.001]`. Unlike the old over-constrained plant, there is
  only one actuator, on the orthogonal aperture coordinate. There is no
  compatibility actuator or second finger servo. Pad friction remains
  `[1.5, 0.005, 0.0001]`. V17 uses `condim=6` on the pads so
  all three terms are active; the previous default `condim=3` used only sliding
  friction and allowed the cube to walk tangentially during repeated wrist roll.
  Physical runs 8-10 motivated and then contradicted the v19/v20 directional
  force experiment. Run 10 retained zero Cartesian saturation and zero IK
  failures but measured open aperture up to `111.75 mm` and symmetry error up
  to `8.454 mm`. V21 restores symmetric `[-8, +8] N` on every physical-finger
  actuator. M1 v17 replaced the former full-finger bounding boxes with thin
  distal pads. Run 11 showed repeatable `36-38 mm` cube contact followed by
  slip. M1 v18's angled proximal extension then failed the offset-grasp test,
  with the cube lost while the fingers remained symmetric and closed almost
  fully. M1 v19 used one continuous thin planar insert across the working
  length, but its exact 40 mm cube-width contact lost the cube earlier. M1 v20
  restores the v17 48 mm lateral width while retaining the continuous 66 mm
  length and 2 mm thickness. V25 acquisition-and-roll A/B diagnostics later
  showed loss along pad-local X for both centred and 3 mm-offset cubes. The
  source finger STL measures exactly 56 mm across that axis (`-28..+28 mm`),
  proving the 48 mm proxy truncated 4 mm of real surface per side. The active
  V21 plant uses that measured 56 mm width. V21 additionally declares explicit pad/cube pairs
  so the five friction coordinates and solver impedance are not inherited from
  generic geom mixing. An attempted ten-iteration NoSlip post-pass made centred
  retention fail sooner and prevented the off-centre lift. This agrees with
  MuJoCo's warning that the secondary NoSlip solver can destabilize complex
  multi-contact systems. The active scene follows MuJoCo's primary grasping
  recommendation instead: Newton with elliptic friction cones and `impratio=10`,
  with NoSlip disabled and the declared physical coefficients unchanged. The
  first elliptic acquisition run then ended with only one instantaneous pad
  constraint active. Expanded diagnostics showed `52.9-61.4 mm` aperture around
  a 40 mm cube and about `13-14 mm` common-mode displacement: the regression had
  translated the arbitrary home wrist orientation rather than aligning the two
  pad planes with opposite cube faces. A fully vertical replacement pose then
  missed its Cartesian target by `17.65 mm` under the accepted joint limits.
  The acquisition regression now preserves the reachable home approach after
  projecting it perpendicular to world `Y`, while aligning local `Y` as the
  closing axis. That reachable test then exposed `-17.9..-18.2 mm` common-mode
  displacement and unilateral contact: the former weak centre let the first
  contacted finger slide the 35 g cube before the opposite finger arrived.
  The first `4000 N/m`, `30 N s/m` candidate reduced common-mode displacement
  below `0.9 mm` but coupled enough numerical load into aperture to collapse a
  commanded-open gripper to `84.26 mm` and stop closing at `69-71 mm`. The
  `1000 N/m`, `15 N s/m` candidate still collapsed open aperture to `90.63 mm`
  and stopped closing at `59-64 mm`. Passive spring tuning is therefore
  rejected. The active soft equality constrains only the common coordinate and
  leaves the single actuator to control aperture. It addresses this measured
  mode directly while leaving
  arm IK, aperture force, friction, geometry, and the external action unchanged.
  The explicit pair retains MuJoCo's damped default
  `solref=[0.02,1]` and `solimp=[0.9,0.95,0.001]`.
- A full-range endpoint-to-endpoint plant regression requires monotonic motion
  and reaches within `2 mm` in at most `45` control ticks (`1.5 s`). V29 uses
  the physically better `10 mm/tick` ramp in both directions. The v28
  `5 mm/tick` closing experiment is rejected because it increased cube shaking.
- V30 leaves that command ramp and the 8 N force limit unchanged, increases
  aperture velocity damping from 30 to 45, and applies the same reported
  `0.05 rad/control tick` rotation bound to both arms. It does not alter the
  OpenXR basis, translation gain, Placo solver, joint order or joint limits.
- V32's identity-map experiment is rejected by physical evidence. V33 restores
  `[-z, -x, y]` and sets only the existing Placo orientation weight to zero.
  Ignored rotation is reported; joint signs/order, position gain, limits,
  actuators, contacts and gripper parameters are unchanged.
- M1 keeps its default 300-tick truncation. The interactive profile
  disables task-end termination at environment construction, so it never
  performs an implicit home reset; only the operator's Reset command does.
- Status output every 30 session frames contains raw filtered controller
  translation/rotation deltas, squeeze/trigger values, target tracking errors,
  measured/target gripper apertures, per-side gripper armed state, and separate
  saturation counters. V25 also reports aperture target/error/force,
  common-mode finger-centre offset, force-limit state, achieved Cartesian
  translation/alignment, and per-joint target/measured/error/saturation/force/IK
  state for both arms.
- D0 degrees/millimetres are preserved before the existing M1 native mapping.
- The Quest-specific joint audit confirms both LeRobot solvers use
  `joint1..joint6`, D0 remains left J1..J6/gripper then right J1..J6/gripper,
  and the twelve MuJoCo arm position actuators target exactly the corresponding
  names with positive degree-to-radian scale. The two remaining native action
  values target the named left/right aperture tendons. No arm joint rename/sign
  repair was required; Gate C joint parity remains consistent with this edge.
- MuJoCo EGL is closed inside the live graphics-bound `TeleopSession`; only
  then do the session, Televiz panels, and owned CloudXR process shut down. A
  narrow failure guard clears already-invalid upstream EGL ownership handles so
  `Renderer.__del__` and `GLContext.__del__` cannot repeat an
  `EGL_NOT_INITIALIZED` destroy call.

## Acceptance boundary

Unit and no-hardware tests can prove mapping, tracking recovery, IK composition,
limits, and absence of real-robot dependencies. They cannot prove physical
Quest identity, axes, scale, comfort, panel visibility, tracking recovery, or
clean reconnect. Until the physical worksheet is completed, the profile must
remain `CONFIGURED_PHYSICAL_QUEST_VALIDATION_REQUIRED`.

Automated results are retained in
`docs/project/MUJOCO_QUEST_AUTOMATED_EVIDENCE.txt`; the physical procedure is
`docs/project/MUJOCO_QUEST_HUMAN_ACCEPTANCE_TEMPLATE.md`.

## Code-size re-audit

The v25 runtime increment is approximately 1,500 source lines: the concrete
launcher/display lifecycle, the pinned upstream controller graph, the
Isaac-compatible task-local WebXR command adapter, and the pure D0/IK edge. This
crosses both code-size re-audit triggers. The added size closes observed
physical defects: separate-process WSS readiness, Play/Stop/Reset gating,
persistent bounded target actuation, head-relative initial panel placement,
transparent XR composition, categorized diagnostics, and correct resource
shutdown. Upstream still owns the protocol, message source,
state manager, retargeting, IK, compositor, physics, and environment. Splitting
these four concrete seams into a simulator/teleop framework would introduce the
forbidden generic backend and would not remove any task-specific behavior, so
no project framework is justified.
