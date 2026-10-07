# AGENTS.md

## Mission

Build the minimum-custom-code PIPER-X robot-learning system defined by v5.2.

Do not build a robotics framework.

## Read first

For every task:

```text
docs/NORMATIVE_MODEL.md
configs/resolved_contract.yaml
configs/gate_rules.yaml
the topic policy document
```

For hardware/safety also read:

```text
docs/PIPER_X_VERIFICATION.md
docs/SAFETY_TIMING.md
docs/HIL_EXTENSION.md
```

## Mandatory upstream audit

Before substantial runtime code report:

```text
CAPABILITY / GATE
PINNED UPSTREAM CANDIDATES
WHAT UPSTREAM ALREADY OWNS
EXACT REMAINING GAP
PROCESSOR / CONFIG / ADAPTER REQUIRED
ENVIRONMENT IMPACT
WHY NO PROJECT FRAMEWORK IS NEEDED
```

## Reuse ladder

```text
upstream implementation
> upstream configuration
> composition
> LeRobot processor / rename map
> thin adapter
> local implementation against public boundary
> fork
```

## Forbidden by default

Do not create without demonstrated need:

- universal `SimulatorBackend`;
- `RobotBackend`;
- generic simulator registry/factory;
- project-wide `EpisodeSource` or `EpisodeGenerator` hierarchy;
- custom dataset format;
- replacement dataset recorder;
- replacement `lerobot-eval`;
- replacement policy runtime;
- duplicate FK/IK solver;
- custom OpenXR/CloudXR protocol;
- generic action ontology;
- mandatory RPC because environments differ;
- one environment/container per conceptual component.

## Shared semantics

The shared contract is the policy-facing PIPER-X semantics, not identical raw simulator dictionaries.

Use runtime-specific processors at the edges.

## Action-label rule

```text
source intent/action
-> deterministic label processors
-> dataset_action_t
-> dataset.action
-> runtime-native mapping
-> accepted/executed native command
```

Do not silently replace the training label with the downstream actuator/device command.

## Temporal rule

```text
obs_t
-> decision
-> dataset_action_t
-> native actuation
-> transition/outcome_t
-> obs_t+1
```

Every converter explicitly maps native fields to these semantics.

## Evidence discipline

A gate cannot be accepted without evidence required by `configs/gate_rules.yaml`.

Do not write "verified manually" without a registered evidence object.

## Environment discipline

Execution profile is not environment identity.

Each runnable stage uses a declared profile and environment. Dependency conflict does not automatically authorize RPC.

## Current MuJoCo M1 implementation

- Gate `M1` was reopened on 2026-09-25 after physical Quest runs contradicted the earlier gripper-retention evidence. The v22 candidate retains the `8 N`, friction `1.5`, `condim=6` plant and continuous `56 x 66 x 2 mm` planar grasp inserts whose width matches the measured `-28..+28 mm` source finger STL, but replaces two finger position servos plus their conflicting equality with one actuated `q1-q2` aperture tendon and one soft constraint on the passive `q1+q2` centre tendon. Explicit pad/cube pairs own grasp contact parameters. Rendered visual group 1 remains separate from collision group 0. M1 remains unresolved until the full NVIDIA EGL verifier and physical Quest validation are retained. Do not reinterpret this work as E2 policy evaluation; E2 remains unresolved and out of scope.
- Exact Gymnasium ID: `PiperX-DualCubeToMatchingPlate-Mujoco-v0`.
- Canonical task scene: `assets/mujoco/scenes/dual_cube_to_matching_plates_v1.xml`.
- Concrete environment and D0 edge processors live only in `packages/lerobot_env_piperx_mujoco`; do not generalize them into simulator backends or registries.
- `observation.images.left_wrist` and `observation.images.right_wrist` are D0 inputs. The `scene` camera is debug-only.
- Each wrist camera looks along the corresponding gripper's local `+Z` approach axis. Imported tapered finger meshes are visual-only; fixed flat pads own finger contact. One external aperture drives a fixed `q1-q2` tendon; a soft MuJoCo equality constrains the passive `q1+q2` centre tendon. There is no second finger actuator and no actuated compatibility leader.
- Preserve `dataset_action_t` in D0 degrees/signed millimetres before mapping to MuJoCo radians/metres; saturation must be reported, never silent.
- Level-0 reset is fixed and deterministic for all seeds, then settles for 120 physics ticks which are not policy steps.
- The requested table static/dynamic friction pair cannot be represented literally by MuJoCo's single sliding coefficient. M1 uses sliding friction `0.8` and records the approximation in `configs/mujoco_m1_runtime.yaml`.
- Rebuild assets with `uv run --frozen --no-sync python tools/build_mujoco_piperx.py --source-checkout <AGX_ARM_URDF_AT_F6642CE>`; the tool rejects another commit or tracked PIPER-X source edits.
- Run the EGL smoke with `uv run --frozen --no-sync python tools/run_mujoco_m1.py --steps 8`; the runner sets `MUJOCO_GL=egl` itself.
- Reproduce the required M1 revalidation evidence on an NVIDIA EGL host with `MUJOCO_GL=egl uv run --frozen --no-sync python tools/verify_mujoco_m1.py --resets 1000 --performance-ticks 180`.
- View the current home scene interactively with `uv run --frozen --no-sync python tools/view_mujoco_m1.py`; a working desktop/X11 or Wayland display is required.
- On an SSH-only NVIDIA host, render the isolated joint-5/joint-6 comparison with `uv run --frozen --no-sync --group isaac-teleop python tools/view_mujoco_m1.py --headless-wrist-diagnostic`; this uses EGL and writes PNG/JSON diagnostics under `artifacts/mujoco_wrist_diagnostic` without opening a window.
- In this user checkout, the repository-wide validator cannot traverse historical accepted S1 artifacts under `/data/ebulochkin` and exits with `Permission denied`. M1 schema, gate rules, references, and every M1 artifact hash are independently validated; do not rewrite or invalidate the unrelated S1 records while working on MuJoCo.
- Pre-existing dirty Isaac files are outside this MuJoCo increment and must not be overwritten or reformatted incidentally.

## Current MuJoCo Quest profile

- `piperx_mujoco_quest_teleop_v39` is an additive operator profile over the reopened M1 implementation. It is not E2 and it does not expand the normative v5.2 gate DAG.
- Status is `CONFIGURED_PHYSICAL_QUEST_VALIDATION_REQUIRED`; never call it accepted until `docs/project/MUJOCO_QUEST_HUMAN_ACCEPTANCE_TEMPLATE.md` is completed and retained.
- Read `docs/project/MUJOCO_QUEST_TELEOP_UPSTREAM_AUDIT.md` and `configs/mujoco_quest_runtime.yaml` before changing the profile.
- Reuse core `isaacteleop==1.3.131` / CloudXR `6.2.0`, its Televiz compositor, one shared `ControllersSource`, upstream `Se3RelRetargeter`, LeRobot `RobotKinematics`, and the concrete M1 environment/processors. Do not add a custom XR protocol, duplicate IK, or generic teleop/simulator layer.
- Presentation v1 is three fixed mono Quest panels: the debug `scene` camera plus both wrist cameras. Their stage poses are captured from one valid HMD pose at session start using head-relative offsets, then remain world-stable; transparent clear preserves upstream ALPHA_BLEND passthrough outside the panels. Do not claim head-tracked stereoscopic MuJoCo rendering.
- Quest v39 retains the `[-z, -x, y]` controller basis restored by v33. Physical v35 confirmed good translation and grasp while holding orientation. V36's low-translation gesture gate admitted only 3 of 20 sampled rotation requests, while physical v37 showed the secondary-button path inactive in every retained row. V38 removed both failed gates and admitted rotation when its scaled magnitude reached `0.006 rad/control tick`, just above the observed `<=0.0055 rad` noise band. Physical v38 deliberate samples reached `0.05-0.067 rad`, but its `0.005 rad` applied bound discarded about 90% of every sample. A subsequent headless official-renderer sweep proved that joint5 and joint6 rotate both complete gripper visual chains exactly and symmetrically. V39 therefore restores the `0.05 rad/control tick` safety bound while retaining the measured activation threshold and Placo orientation weight `0.01`. Translation gain, joint order/signs, limits, tracking guards, gripper and contacts are unchanged. Do not introduce a second IK solver. Squeeze is clutch, trigger is analog gripper, thumbstick click toggles per-arm precision, and right primary resets M1.
- Reuse the Isaac WebXR `uuid5(NAMESPACE_DNS, "teleop_command")` message channel and upstream `DefaultTeleopStateManager`. The session starts STOPPED; Play alone enables MuJoCo stepping/actions, Stop holds state, and menu Reset resets then pauses. Before the first Play, submit black panels so menu pointing and trigger clicks cannot move the robots or grippers.
- The MuJoCo IK edge accumulates Cartesian deltas from the last accepted actuator target and retains that target while controller deltas are zero. It bounds target-vs-measured joint error to 25 degrees while retaining the 8-degree per-tick step and accepted joint limits. Reinitialize this persistent target only on explicit scene reset; deriving every frame from lagging measured joints makes translation and especially rotation disappear before MuJoCo reaches the target.
- The MuJoCo v27 motion gains remain `0.5` normal and `0.125` precise for both translation and rotation. Its narrow upstream-retargeter subclass reduces only the positional/rotational deadbands to `0.00025 m` / `0.0025 rad`. The existing LeRobot/Placo frame task uses position weight `1.0` and soft orientation weight `0.01`; a Cartesian direction guard retries the same upstream solver position-only if incidental wrist rotation turns requested translation sideways. Unlike Isaac's separately qualified `2.0/0.5` profile, MuJoCo integrates the complete filtered delta sequence into its persistent actuator target. V27 clears upstream relative-pose and smoothing history throughout pause/reset, so controller motion in the WebXR menu cannot leak into the next Play interval. V30 bounds rotation to `0.05 rad/control tick` on both sides; physical v29 logged right-side filtered rotation spikes above this value, and every clipped sample remains visible as Cartesian saturation.
- The MuJoCo IK edge holds grippers while inactive/invalid/rebasing and, after every Play/reset/tracking recovery, requires a trigger-release sample corresponding to at least `95 mm` open intent before accepting close commands. It limits both opening and closing to `10 mm/control tick`, measured from the last accepted gripper target rather than lagging qpos. The rejected v28 `5 mm/control tick` closing ramp worsened physical cube shaking; Cartesian, joint, and gripper saturation remain separately reported.
- Quest v30 raises only the aperture actuator's velocity damping from `30` to `45`; the `8 N` force limit, command gain, contact geometry, friction, and external 14-value action remain unchanged. Physical v29 held a constant target and force limit while loaded aperture oscillated by more than `7 mm`, so this profile change targets finger velocity rather than trigger slew.
- With `--require-tracking`, Quest v31 does not step MuJoCo or update either actuator target until both controller grip poses are simultaneously available. It rebases the upstream relative retargeters, local state processor and persistent IK target before the first bimanual command, and fails with the missing side after 10 seconds instead of silently permitting a one-controller validation run.
- M1 v22 and Quest v26 keep the external 14-value native action; each scalar aperture maps to one fixed physical-finger `q1-q2` tendon. Its command gain and position bias are `1250`, damping is `30`, and force range is symmetric `[-8, +8] N`. Each finger uses armature `0.1 kg`, damping `2 N s/m`, and zero joint stiffness. A soft equality with `solref=[0.02,1]` and `solimp=[0.9,0.95,0.001]` constrains the passive `q1+q2` centre tendon without adding an actuator or preloading the orthogonal aperture coordinate. Rejected passive-spring candidates at `4000/30` and `1000/15` N/m/Ns/m collapsed open aperture to `84.26` and `90.63 mm` respectively and prevented contact. The contact surface is one continuous planar `56 x 66 x 2 mm` insert, matching the measured source-mesh width instead of the previous truncated 48 mm proxy. Explicit pad/cube pairs use friction `[1.5, 1.5, 0.005, 0.0001, 0.0001]`, `condim=6`, damped `solref=[0.02, 1]`, and `solimp=[0.9, 0.95, 0.001]`; the earlier near-rigid impedance produced unilateral contact chatter. The main Newton solver uses elliptic friction cones with `impratio=10`, matching MuJoCo's upstream grasping guidance; the unstable `noslip` post-pass is disabled. Cameras exclude collision group 0 and render visual/task group 1. Runtime 10-mm/tick opening and closing must remain bounded and monotonic; open-finger multijoint motion must retain at least `95 mm` aperture, and bilateral off-centre grasp evidence uses a `3 mm` cross-pad cube offset inside the declared `8 mm` per-side margin, requires 300/300 contact ticks during smooth `+/-5 degree` wrist roll, and permits less than `20 mm` cube translation relative to the moving gripper frame.
- The Quest profile constructs the concrete M1 environment with `terminate_on_task_end=False`: M1's default 300-tick termination/truncation semantics remain unchanged for evaluation, while physical teleoperation continues until explicit Reset instead of silently resetting home every 300 ticks.
- Run with `uv run --frozen --no-sync --group isaac-teleop python tools/run_mujoco_quest.py`; a physical Quest, NVIDIA GPU, accepted CloudXR EULA, and the WebXR client are required.
- The direct-file launcher explicitly adds the repository root to `sys.path`; keep the documented `python tools/run_mujoco_quest.py` invocation covered by a regression test so its `tools.*` imports work outside pytest.
- Auto-launch CloudXR through the pinned upstream `python -m isaacteleop.cloudxr` CLI in one owned child process, wait for `127.0.0.1:48322`, then enter Televiz's blocking HMD wait. Do not embed `CloudXRLauncher` in the Televiz process: its Python WSS thread is starved by the native 120-second OpenXR system wait, leaving the Quest certificate URL unreachable. `--no-auto-launch-cloudxr` still reuses exactly one externally owned lifecycle.
- On shutdown destroy MuJoCo EGL while the graphics-bound `TeleopSession` is still alive, then destroy `TeleopSession` and Televiz panels before stopping the owned CloudXR child. If upstream EGL destruction already reports `EGL_NOT_INITIALIZED`, retire its invalid handles so Python destructors cannot retry them.
- The runtime opens no CAN or real-robot interface. Preserve D0 degrees/millimetres before the existing MuJoCo native mapping and report every Cartesian, joint-step, joint-limit, gripper-slew, and gripper-force saturation. Status must expose physical-finger aperture/targets/tracking/symmetry/forces plus per-joint target, measured value, error, saturation, force, and IK status for both arms.

## Code-size re-audit

Repeat upstream audit at roughly:

```text
>300 LOC in one integration module
>1000 LOC new runtime code for one gate
```

Tests/config/schema are excluded.

## Final report

```text
GATE
REUSED
PINNED / VERIFIED
EXECUTION PROFILE / ENVIRONMENT
CONTRACT CHANGES
EVIDENCE ADDED
ARTIFACTS ADDED
PROCESSORS / ADAPTERS
TESTS
HUMAN EVIDENCE
BLOCKERS / REOPEN REASONS
NEXT GATE
```
