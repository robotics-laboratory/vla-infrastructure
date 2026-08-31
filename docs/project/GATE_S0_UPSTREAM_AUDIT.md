# Gate S0 upstream audit and architecture selection

Audit date: 2026-08-31  
Live repository baseline: `0515b74809497a983c25da39c9dbe2fee3fe2741`  
Gate verdict: **BLOCKED**

S0 was limited to upstream research, pinning, compatibility probes, architecture
selection, and contract evidence. No S1/S2/D1/G1/M1/E1/E2/E3/B0 runtime was built.
The already accepted transition audit and D0 policy/data semantics were not
reopened.

## Decision summary

MuJoCo has a current, minimal, fully resolved path in `core`: MuJoCo 3.9.0,
Gymnasium 1.3.0, and LeRobot 0.6.1. Isaac does not have an acceptable supported
same-process pin today:

1. Isaac Lab 2.3.2 / Isaac Sim 5.1 requires Python 3.11, while accepted LeRobot
   0.6.1 requires Python 3.12 or newer.
2. Isaac Lab 3.0.0-beta2.patch1 / Isaac Sim 6.0.1 uses Python 3.12 and compatible
   torch/Gymnasium ranges, but pins Transformers 4.57.6. That package requires
   `huggingface-hub<1.0`, while LeRobot 0.6.1 requires
   `huggingface-hub>=1.6,<2`; the exact resolver probe is unsatisfiable.
3. The current host driver is 580.159.03 and target filesystem has 27 GiB free;
   Isaac Sim 6.0.1 publishes 595.58.03 and 50 GB as x86_64 minimums.

Overriding NVIDIA's exact dependency, running LeRobot on an unsupported Python,
copying the policy runtime, or inventing an RPC transport would violate S0's
selection standard. S0 is therefore blocked, and S1/M1/B0 remain ineligible even
though the MuJoCo and edge architectures below are resolved.

## A. Selected Isaac stack

There is **no accepted Isaac stack pin**. The closest current first-party candidate
is retained for a future S0 re-audit, not selected as compatible:

| Field | Closest current NVIDIA candidate | Status |
|---|---|---|
| Isaac Sim | `isaacsim[all,extscache]==6.0.1.0`, released 2026-06-22 | blocked |
| Isaac Lab | `v3.0.0-beta2.patch1`, commit `ffff603eafc6b74264a5261cc0183d6a65390d78`, released 2026-07-02 | blocked; beta |
| Python | CPython `3.12.x`; intended project pin `3.12.13` | compatible by itself |
| torch | `2.10.0+cu128` | compatible with LeRobot's `>=2.7,<2.12` range |
| torchvision | `0.25.0+cu128` | compatible with LeRobot's `>=0.22,<0.27` range |
| CUDA | PyTorch CUDA 12.8 wheels; NVIDIA driver 595.58.03 published/tested for Isaac Sim 6.0.1 x86_64 | host blocked |
| Gymnasium | Isaac Lab package pin `1.2.1` | compatible with LeRobot's `>=1.1.1,<2` range |
| Transformers | Isaac Lab exact `4.57.6` | hard conflict with LeRobot 0.6.1 through Hugging Face Hub |
| Install model | NVIDIA-supported source checkout plus uv/PyPI Isaac Sim installation; dedicated `isaac` environment | cannot yet produce a valid lock |
| License | Isaac Lab BSD-3-Clause; Isaac Teleop Apache-2.0; Isaac Sim/CloudXR under NVIDIA proprietary licenses/EULAs | recorded, not a compatibility cure |

Authoritative sources:

- [Isaac Lab latest release](https://github.com/isaac-sim/IsaacLab/releases/tag/v3.0.0-beta2.patch1)
- [Isaac Lab exact root pins](https://github.com/isaac-sim/IsaacLab/blob/ffff603eafc6b74264a5261cc0183d6a65390d78/pyproject.toml)
- [Isaac Lab exact package dependencies](https://github.com/isaac-sim/IsaacLab/blob/ffff603eafc6b74264a5261cc0183d6a65390d78/source/isaaclab/setup.py)
- [Isaac Sim 6.0.1 requirements](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/installation/requirements.html)
- [Isaac Sim 6.0.1 PyPI package](https://pypi.org/project/isaacsim/6.0.1.0/)
- [LeRobot 0.6.1 exact dependency metadata](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/pyproject.toml)

The latest release is maintained but explicitly beta. The stable 2.3.2 line is the
final 2.x release and is rejected for Python 3.11 plus the same Transformers/Hub
conflict. An unversioned `develop` checkout is rejected because it is not a release
pin and does not repair the dependency metadata. NVIDIA containers do not change
the Python/package incompatibility and still require a compatible host driver.

### Conditional capability ownership after the blocker is cleared

| Capability | Upstream owner | Selected API/path | Pin | Exact remaining gap | Implementing gate |
|---|---|---|---|---|---|
| asset/articulation | Isaac Lab | `UrdfFileCfg`/`UrdfConverter`, `ArticulationCfg`, `ImplicitActuatorCfg` | candidate commit `ffff603…` | Gate C asset conversion/config; two namespaced instances | S1 |
| reset/step | Isaac Lab | `ManagerBasedRLEnv.reset(seed=...)` and `.step()` | same | PIPER-X task/reset config and verified seed protocol | S1 |
| action application | Isaac Lab | `ActionManager`, joint action terms, public differential-IK controller for teleop | same | D0 joint/gripper mapping and actual control configuration | S1/S2 |
| observations | Isaac Lab | `ObservationManager` | same | measured PIPER-X joints plus D0 rename/unit processor | S1 |
| cameras | Isaac Lab | `CameraCfg`/`TiledCameraCfg`; `AppLauncher --enable_cameras` headless path | same | two wrist mounts, exact D0 resolution/color ordering | S1 |
| task success | Isaac Lab | named `TerminationManager` term `success` | same | canonical task-specific predicate/revision | S1 |
| termination | Isaac Lab | `TerminationManager` terminated/time-out buffers | same | canonical horizon/failure categories | S1 |
| recorder | Isaac Lab | `RecorderManager`, `ActionStateRecorderManagerCfg`, `HDF5DatasetFileHandler` | same | small recorder terms plus deterministic HDF5-to-LeRobot conversion | D1/G1 |
| VR teleop | Isaac Lab Teleop + Isaac Teleop | `IsaacTeleopDevice`, `IsaacTeleopCfg`, `TeleopSessionLifecycle` | Isaac Lab candidate + Isaac Teleop 1.3.131 commit `7002ed…` | PIPER-X bimanual validity/clutch/gripper/action composition | S2 |
| automated generation | Isaac Lab | manager env + native state-machine/scripted-expert pattern + RecorderManager | same | one task-local PIPER-X expert, no framework | G1 |
| evaluation | LeRobot + Isaac Lab | `EnvConfig.create_envs`, environment processor pipelines, `lerobot-eval`/`eval_policy` | LeRobot `7e241bd…`; Isaac candidate | supported dependency set is presently impossible; thin env config/processors later | E1 after S1 |

No project simulator framework is needed: upstream already owns the lifecycle,
managers, physics, cameras, recording, teleop session, and evaluation loop.

## B. Quest -> Isaac path

The correct current NVIDIA API path is conditionally selected:

```text
Quest 3
-> NVIDIA CloudXR 6.2.0 auto-webrtc/OpenXR bridge
-> one isaaclab_teleop.IsaacTeleopDevice context
-> one TeleopSessionLifecycle / TeleopSession
-> one ControllersSource with LEFT and RIGHT OptionalTensorGroups
-> thin PIPER-X bimanual mapping
-> Isaac Lab action/controller terms
```

Pins and ownership:

- Isaac Teleop `1.3.131`, tag commit
  `7002ed63d69454ae4f15c0ee19f803fd2846592b`, Apache-2.0.
- Isaac Lab Teleop extension `0.5.2` at candidate commit `ffff603…`.
- CloudXR `6.2.0`, already physically accepted at Gate B under its NVIDIA EULA.
- `IsaacTeleopDevice(..., cloudxr_env_file=CLOUDXR_JS_ENV,
  auto_launch_cloudxr=True)` is the canonical single production lifecycle owner.
  Gate B's externally launched diagnostic path remains evidence tooling, not the
  production Isaac launcher.
- `ControllersSource.LEFT` (`controller_left`) and `.RIGHT`
  (`controller_right`) carry grip/aim XYZ, XYZW rotation, per-pose validity,
  primary/secondary/menu buttons, thumbstick, squeeze, and trigger.
- `XrAnchorManager` and `IsaacTeleopCfg.target_frame_prim_path` own frame rebasing.
- The upstream raw trigger owns gripper input acquisition; Gate S2 will choose and
  verify the PIPER-X aperture mapping. The generic binary `GripperRetargeter`
  output is not the D0 signed-millimeter ontology.

Exact PIPER-X gap: upstream has no PIPER-X bimanual retargeter. The thin mapping
must independently preserve left/right identity, gate on Optional presence and
`GRIP_IS_VALID`, hold then re-arm after loss, keep a clutch origin per arm, rebase
through the upstream anchor API, map trigger to the model aperture explicitly, and
produce the D0 joint/gripper label before native action processing. The upstream
SO-101 clutch/gripper implementations are valuable references but their robot
constants and gripper meaning cannot be reused as PIPER-X truth. Numeric stale-age
policy remains owned by R2/HIL as already accepted at Gate B.

`tools/quest_xr_diagnostics.py` remains diagnostic evidence only. No universal
teleop backend or custom OpenXR/CloudXR protocol is selected.

## C. Isaac recording path

Conditional selection: Isaac Lab `RecorderManager` with
`ActionStateRecorderManagerCfg` and native `HDF5DatasetFileHandler`.

Native order in `ManagerBasedRLEnv.step` is:

```text
ActionManager.process_action(input action)
-> RecorderManager.record_pre_step()
   - actions = ActionManager.action
   - obs = current policy obs buffer (obs_t)
-> action apply / physics decimation
-> termination, timeout, reward
-> compute recording observation
-> RecorderManager.record_post_step()
   - states = post-transition state
   - processed_actions = action-term processed values
-> RecorderManager.record_pre_reset(terminated ids)
-> export and reset
```

The native HDF5 format has `data/demo_N`, nested tensor datasets, `actions`, `obs`,
`processed_actions`, `initial_state`, `states`, `num_samples`, `seed`, `success`,
format version, and JSON `env_args`. The manager recognizes success only from the
termination term named `success`, supports all/success-only/separate success-failed
export modes, and has HDF5 replay utilities. Cameras can be native observation
terms/nested tensors; native video utilities do not make the file a
LeRobotDataset.

Native output is not LeRobotDataset v3. The selected path is:

```text
native Isaac HDF5
-> deterministic thin D1 converter
-> LeRobotDataset v3
```

Converter required: **YES**, implemented only at D1. D1 must preserve the recorded
pre-step D0 label (never substitute `processed_actions`), `obs_t/action_t`, outcome
and `obs_(t+1)`, success/termination/timeout, fixed-grid `frame_index/30`
timestamps, the exact left/right wrist roles, task revision, FPS rejection or
declared resampling, source provenance, config/seed/commit lineage, and replay
checks. Small recorder terms for camera/task/termination reason are configuration
at the native boundary, not a replacement recorder.

## D. Automated generation path

Baseline required method: a **task-local scripted expert/state machine** composed
with `ManagerBasedRLEnv`, the native action manager, `RecorderManager`, and the
same success term used by the task. Isaac Lab owns the execution and recording;
G1 owns only the PIPER-X/task state machine and manifest wiring. This requires no
seed demonstrations and is the least complex way to generate successful episodes.

G1 must retain master/per-episode seeds, candidate config and source revisions,
every attempted/success/failed count and failure category, successful episode
artifacts, and generator lineage. Native separate success/failed export is used so
failures are not silently discarded. Source-demo lineage is `not_applicable` for
the baseline, not omitted.

Optional future methods, not baseline:

- Isaac Lab Mimic/SkillGen (`isaaclab_mimic` 1.3.3 at the same candidate commit):
  first-party, bimanual examples exist, but requires annotated demonstrations and
  greater task setup. Consider after D1 supplies demonstrations.
- Mimic plus cuRobo planner: more dependencies and embodiment configuration; use
  only if the scripted expert cannot solve the task reliably.
- policy-generated trajectories: useful after a checkpoint exists; not a G1
  bootstrap.

No `EpisodeGenerator` hierarchy is proposed. A gate-local integration module must
stay below the 300-LOC re-audit threshold (tests/config excluded), or G1 must stop
and repeat this upstream audit.

## E. Isaac evaluation path

The architecture is selected but not currently installable:

```text
LeRobot checkpoint
-> make_policy + checkpoint PolicyProcessorPipeline preprocessor
-> native Isaac observation
-> thin Isaac environment preprocessor (radians/meters/HWC -> D0)
-> policy.select_action
-> checkpoint postprocessor
-> thin Isaac environment postprocessor (D0 -> native radians/aperture)
-> native Isaac ManagerBasedRLEnv
-> upstream lerobot-eval metrics/eval_info.json
-> small run-manifest sidecar
```

LeRobot 0.6.1 already owns `EnvConfig.create_envs`, `make_env`,
`make_env_pre_post_processors`, checkpoint processors, vector rollout, seeding,
`terminated`/`truncated`, `info["is_success"]`/`final_info`, video/evaluation
recording, aggregation, and `eval_info.json`. E1 should add a narrow Isaac
`EnvConfig`/Gym wrapper plus two registered processor steps; it must not replace
`lerobot-eval`. The existing `IsaaclabArenaEnv` is not selected because it delegates
to an unrelated Hub arena/embodiment rather than the accepted PIPER-X task.

The E1 run-manifest wrapper must hash/record checkpoint, policy config, checkpoint
pre/postprocessor files, environment processor config/state/revision, Isaac
environment/asset/task revision, policy contract revision, seed set, episode
count, horizon, success and timeout semantics, execution profile, raw log,
`eval_info.json`, videos, and final metrics. Actual values and a real run belong to
E1.

This is a same-process per-step path: policy processors and the native environment
share observations/actions each step. No supported upstream remote seam was found,
so splitting them would require a new RPC/runtime contract and is rejected.

## F. Selected MuJoCo stack

| Project | Exact pin | Release/commit | Python/runtime | Install/license/status |
|---|---|---|---|---|
| MuJoCo | `mujoco==3.9.0` | 2026-05-27; tag commit `237c17e48539b6c90bf90d3161547cbdcbfaa1e0` | Python >=3.10; bundled C library; no torch/CUDA requirement | uv/PyPI wheel; Apache-2.0; canonical Google DeepMind binding, maintained |
| Gymnasium | `gymnasium==1.3.0` | 2026-04-22; tag commit `53bf3e9a884783eb72ad3fc8b15780914c97c3e1` | Python >=3.10 | uv/PyPI; MIT; Production/Stable |
| LeRobot | `0.6.1` | 2026-08-03; commit `7e241bd630a3719a56157a497ce5d08f244784f1` | Python >=3.12; torch >=2.7,<2.12 | existing core lock; Apache-2.0; current accepted release |

Primary sources:

- [MuJoCo 3.9.0 package/API/install/license](https://pypi.org/project/mujoco/3.9.0/)
- [MuJoCo documentation](https://mujoco.readthedocs.io/en/3.9.0/python.html)
- [Gymnasium 1.3.0 release](https://github.com/Farama-Foundation/Gymnasium/releases/tag/v1.3.0)
- [Gymnasium 1.3.0 package metadata](https://pypi.org/project/gymnasium/1.3.0/)
- [LeRobot 0.6.1 release](https://github.com/huggingface/lerobot/releases/tag/v0.6.1)

Public native APIs selected: `MjModel.from_xml_path/from_xml_string`, `MjData`,
`mj_resetData`, `mj_forward`, `mj_step`, named joints/actuators/cameras,
`Renderer.update_scene/render`, and Gymnasium `Env.reset(seed)` / five-value
`Env.step`. The bounded probe compiled, stepped, seeded, and rendered with these
exact core pins.

## G. MuJoCo evaluation path

Use the same LeRobot 0.6.1 `EnvConfig`/processor/`lerobot-eval` seam described for
Isaac, with a thin PIPER-X Gymnasium environment. Native measured joint positions
and camera renders pass through a MuJoCo-specific observation processor; D0 actions
pass through a MuJoCo-specific action processor into named position actuators.
`is_success`, `terminated`, and `truncated` come from the task Gym environment.

E2 uses the same run-manifest schema as E1 with MuJoCo/model/task/processor hashes.
No alternate policy runtime, simulator registry, or generic simulator interface is
needed.

## H. PIPER-X Isaac adaptation strategy

Selected strategy: **B — import/convert the accepted Gate C model** through Isaac
Lab `UrdfFileCfg`/`UrdfConverter`, then configure a normal `ArticulationCfg`. The
Gate C revision `f6642ce0d7872c686f29c99e9e10cd23d1d49313` remains the embodiment
source of truth. Instantiate it twice with explicit left/right namespaces.

An exact-named first-party AgileX candidate was found:
`agilexrobotics/piper_isaac_sim` commit
`8e1f88fdb7afca49c40e9a0c1c01cc588e86f0d2`, file
`USD/piper_x_v1.usd`. It is rejected as the direct asset because its accompanying
URDF is not Gate C equivalent (frame names/origins, several limits,
masses/inertias, gripper joints), and the repository contains no license file.
Generic Piper/DoublePiper assets are not PIPER-X proof.

Known conversion gaps for S1: mesh/package resolution, collision/inertia checks,
fixed flange/TCP preservation, gripper mimic/coupling, drive/actuator properties,
two-arm namespacing, self/inter-arm collision configuration, home state, and
control parameters. S1 must compare home/zero, all limits/signs, positive
perturbations, base-to-flange/TCP FK, and gripper endpoints against Gate C. S0 does
not select gains, dt, decimation, saturation, reset distribution, success
threshold, or timeout.

## I. PIPER-X MuJoCo adaptation strategy

Selected strategy: deterministically derive MJCF from the accepted Gate C expanded
URDF using MuJoCo's public URDF parser/spec/save boundary, then add only named
position actuators, two wrist cameras, task objects/sites, and explicit gripper
coupling. The derived MJCF must retain the Gate C revision/hash as provenance and
be instantiated twice with collision-safe namespacing.

No exact PIPER-X MJCF was found. AgileX's generic
`piper_description/mujoco_model/piper_description.xml` declares model `piper`, not
PIPER-X, and its limits/control ranges are not Gate C. MuJoCo Menagerie contains no
Piper listing and is not an officially supported Google product. Both are
rejected. URDF import may omit mimic behavior, actuators, camera sites, and task
semantics; those are the narrow M1 gap, not a reason to implement FK/IK again.

## J. Environment matrix

Profile-to-environment decision:

| Profile | Environment | Decision |
|---|---|---|
| `offline_tests` | `core` | existing accepted uv lock |
| `isaac_env` | `isaac` | conceptual vendor environment; blocked, no accepted spec |
| `isaac_vr_record` | `isaac` | same blocked Isaac environment; CloudXR is a co-process, not another Python environment |
| `isaac_generate` | `isaac` | same blocked Isaac environment |
| `isaac_dataset_convert` | `core` | conversion does not require Isaac Sim |
| `isaac_eval` | `isaac` | same-process policy/environment requirement; blocked |
| `mujoco_env` | `core` | proven compatible |
| `mujoco_eval` | `core` | proven compatible |

Environment records:

- `core`: uv, CPython 3.12.13, torch 2.7.1+cu126, existing CUDA bundle and
  CloudXR 6.2.0 only where the Quest profile needs it, `uv.lock`, canonical
  `uv run`. It now directly pins Gymnasium 1.3.0 and MuJoCo 3.9.0.
- `mujoco`: a mandatory conceptual record that aliases the exact `core` lock; it
  is not a second environment. Manager/launcher `uv` / `uv run`, CPython 3.12.13,
  torch 2.7.1+cu126, MuJoCo 3.9.0 PyPI wheel, `uv.lock`.
- `isaac`: a separate vendor environment is genuinely justified by Isaac Sim,
  torch 2.10.0+cu128, CUDA/driver, and proprietary runtime requirements. It would
  use uv and CPython 3.12.13 with the candidate source commit, but no reproducible
  environment spec can be accepted while the resolver and host checks fail.

MuJoCo -> core: **YES**. Isaac -> dedicated environment: **required but blocked**.
No environment-per-component topology and no RPC are selected.

## K. D0 processor and semantic map

Isaac conditional map:

```text
Isaac native measured q (radians), model aperture (meters),
left/right CameraCfg RGB (native layout), native task info
-> thin Isaac observation PolicyProcessorPipeline step
   - explicit joint order from Gate C
   - radians -> degrees
   - explicit aperture -> D0 signed-mm semantics (pending physical mapping boundary)
   - image layout/dtype/range -> exact D0 camera tensors
   - exact rename map
-> observation.state[14], observation.images.left_wrist,
   observation.images.right_wrist, task

D0 action[14] in degrees/signed millimeters
-> label remains fixed and recordable as dataset_action_t
-> thin Isaac action PolicyProcessorPipeline step
   - degrees -> radians
   - explicit signed-mm -> model-aperture mapping
   - exact left/right joint order
-> Isaac Lab native joint/gripper action
```

MuJoCo map:

```text
MjData.qpos in named Gate C order + renderer RGB + Gym task info
-> thin MuJoCo observation PolicyProcessorPipeline step
   - radians -> degrees
   - explicit aperture -> D0 gripper observation
   - image layout/dtype/range and exact rename map
-> the identical D0 observation keys/shapes/units/task

D0 action[14] in degrees/signed millimeters
-> label remains fixed as dataset_action_t
-> thin MuJoCo action PolicyProcessorPipeline step
   - degrees -> radians
   - explicit gripper mapping
   - named actuator order
-> MjData.ctrl / mj_step
```

Native runtimes own sensing and actuation; LeRobot owns processor pipelines and
policy preprocessing/postprocessing; config owns names/order; the project owns
only the two small runtime-specific unit/shape mappings. No transform is duplicated,
no unit change is implicit, and no generic gripper ontology is introduced. Exact
physical signed-mm-to-aperture behavior still depends on R1 evidence.

## L. Cross-sim parity strategy

S1 and M1 independently prove:

- Interface parity: exact D0 feature/action names, shapes, dtypes, degrees/mm
  units, left/right wrist roles, task ID/revision, gripper meaning, processor
  config/state/reset revisions, success/timeout semantics, and horizon.
- Embodiment parity: Gate C home/zero, joint order/names, limits, positive
  directions, gripper endpoints, base/flange/TCP frames, FK matrices at the Gate C
  reference vectors, and policy-facing control meaning.
- Task parity: one canonical task revision with semantically matched workspace,
  initial-condition policy, objects, success predicate, timeout, and horizon;
  each simulator retains its own explicit physics/control parameters.

This does not claim physics equivalence or equal policy scores. E3 compares the
compatible contracts and actual E1/E2 artifacts only after both exist.

## M. Reuse accounting

| Capability / gate | Pinned upstream candidates | What upstream owns | Exact remaining gap | Processor/config/adapter | Environment impact | Why no project framework |
|---|---|---|---|---|---|---|
| Isaac environment / S1 | Isaac Lab candidate `ffff603…` | app, managers, scene, articulation, physics, reset/step, sensors | Gate C conversion, one task config, parity evidence | config + thin D0 processors | dedicated blocked `isaac` | one native env is sufficient |
| Quest/Isaac / S2 | Isaac Lab Teleop candidate + Isaac Teleop `7002ed…` + CloudXR 6.2 | XR/session/controller streams/rebase | bimanual validity/clutch/gripper/PIPER mapping | one thin retargeting composition | same `isaac`; one CloudXR co-process | upstream lifecycle replaces a teleop backend |
| Isaac recording / D1 | RecorderManager at `ffff603…` | phase hooks, HDF5, episode export/replay | D0 fields/reasons and deterministic conversion | small terms + converter | record in `isaac`, convert in `core` | native recorder remains authoritative |
| Isaac generation / G1 | manager env/state-machine pattern at `ffff603…` | execution, seeds/reset seam, success, recording | task-local expert and lineage manifest | script/config only | same `isaac` | no generator hierarchy |
| Isaac eval / E1 | LeRobot `7e241bd…` + candidate Isaac | policy load/process/eval metrics and native env | dependency blocker, EnvConfig, two processors, manifest | thin glue | same-process `isaac`, blocked | no replacement eval/runtime |
| MuJoCo env / M1 | MuJoCo `237c17e…`, Gym `53bf3e9…` | physics/parser/render and Env protocol | Gate C-derived MJCF, task, parity | thin Gym env/processors | `core` | one task env, no sim abstraction |
| MuJoCo eval / E2 | LeRobot `7e241bd…` | checkpoint/processors/eval metrics | EnvConfig registration and manifest | small glue | `core` | reuse `lerobot-eval` |
| benchmark readiness / B0 | same LeRobot EnvConfig/processors/eval seam | benchmark-specific protocol when selected | later native benchmark config and artifact policy | edge processors only | benchmark-owned; default `core` | no second policy/runtime framework |

Mandatory upstream audit conclusion:

```text
CAPABILITY / GATE: S0 simulator/evaluation path selection
PINNED UPSTREAM CANDIDATES: exact commits/releases above
WHAT UPSTREAM ALREADY OWNS: simulator lifecycle, managers, XR session, recorder,
  Gym contract, policy runtime, processors, and evaluation
EXACT REMAINING GAP: PIPER-X assets/tasks, runtime-specific processors, a thin
  Isaac HDF5 converter, a task-local expert, and manifests
PROCESSOR / CONFIG / ADAPTER REQUIRED: edge-only, runtime-specific
ENVIRONMENT IMPACT: MuJoCo joins core; Isaac needs one vendor environment but is blocked
WHY NO PROJECT FRAMEWORK IS NEEDED: every orchestration/lifecycle role has an
  upstream public boundary
```

## N. Rejected alternatives

- Isaac Lab 2.3.2 / Isaac Sim 5.1: Python 3.11 and Hub dependency conflicts with
  LeRobot 0.6.1.
- Isaac Lab 3.0 beta with a Transformers override, `--no-deps`, or forced Hub
  version: violates NVIDIA's exact supported dependency metadata.
- Isaac Lab `develop`/nightly: moving, unreleased, and does not remove the audited
  metadata conflict.
- NVIDIA container as a cure: retains the incompatible package set and requires a
  suitable host driver.
- Custom RPC between `core` policy inference and Isaac: no selected upstream seam,
  changes temporal/failure semantics, and is unnecessary invention at S0.
- Replacement LeRobot runtime or copied processor/eval code: forbidden duplication.
- AgileX `piper_isaac_sim` USD direct use: exact name is insufficient; Gate C
  geometry/frames/limits/gripper differ and repository licensing is absent.
- Generic Piper/DoublePiper as PIPER-X: no equivalence proof.
- Isaac Lab Mimic/SkillGen as baseline G1: requires demonstrations and more setup;
  retained as optional after D1.
- Third-party simulator wrappers/registries: upstream native boundaries already
  own the capability.
- Generic AgileX Piper MJCF: not PIPER-X and not Gate C equivalent.
- MuJoCo Menagerie: no Piper model found; not an officially supported product.
- Separate MuJoCo environment: exact core lock and bounded execution passed.

## O. Known blockers and risks

Critical acceptance blockers:

1. No supported Isaac Lab/Isaac Sim dependency set resolves with accepted LeRobot
   0.6.1 for the required same-process E1 seam.
2. Host NVIDIA driver 580.159.03 is below Isaac Sim 6.0.1's published/tested
   x86_64 595.58.03 requirement.
3. Only 27 GiB is free on the target filesystem versus the published 50 GB
   minimum.

Re-audit triggers: a new NVIDIA release compatible with Hugging Face Hub >=1.6, a
new accepted LeRobot release compatible with NVIDIA's supported pins, or an
official upstream process boundary that preserves LeRobot processors/eval and D0
temporal semantics. Host driver/storage must also be remediated before S1.

Non-blocking future risks: beta API churn, the stale Gymnasium pipapi manifest,
URDF-to-USD/MJCF gripper coupling, exact wrist-camera mounts, physical gripper
mapping pending R1, and task-local bimanual collision/reset tuning.

## P. Exact next-gate responsibilities

- S0 re-audit: choose a supported resolvable Isaac pin, record an accepted Isaac
  environment spec/lock, and repeat host compatibility checking. Only then can S0
  become accepted.
- S1 after S0: implement/run only the Isaac PIPER-X environment, task, parameters,
  cameras, reset/seed protocol, and Gate C parity evidence.
- M1 after S0: derive/run only the MuJoCo PIPER-X Gym environment and parity
  evidence in core. Its technical path is ready but its hard machine dependency is
  not bypassed.
- S2 after S1: implement and physically validate the selected one-session Quest
  bimanual PIPER-X mapping.
- D1 after S2+D0: record human VR data and implement/validate the deterministic
  Isaac HDF5 -> LeRobotDataset v3 converter.
- G1 after S1+D0: implement the task-local scripted expert and generate actual
  successful/failure-accounted episodes.
- E1 after S1: run the selected upstream LeRobot/Isaac evaluation path and retain
  its manifest/artifacts.
- E2 after M1: run the same LeRobot evaluation seam in MuJoCo.
- E3 after E1+E2: compare actual artifacts under the parity contract.
- B0 after S0: prove benchmark-native integration readiness through the same
  EnvConfig/processor/eval seam; do not select B1 without a configured benchmark.

The currently eligible independent hardware frontier R0 is unchanged. No spec/DAG
patch is required. Final RC remains not ready.
