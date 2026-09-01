# Gate S0 Isaac compatibility remediation audit

Audit date: 2026-08-31

Live repository baseline: `75acc551af73a81d4181392edd358a1b2e8fd0c3`

Remediation verdict: **D — NO SUPPORTED PATH**

Gate state after audit: **BLOCKED**

This addendum is limited to the unresolved Isaac/LeRobot compatibility question.
It does not select or implement S1, S2, D1, G1, M1, E1, or any process adapter.
It does not change the accepted LeRobot 0.6.1 pin, D0 semantics, Quest
architecture, PIPER-X plugin, or the already-audited MuJoCo selection.

## 1. Immutable sources audited

| Project | Release/ref | Immutable revision or package version | Status at audit |
|---|---|---|---|
| LeRobot | `v0.6.1` | `7e241bd630a3719a56157a497ce5d08f244784f1` | accepted project pin; released 2026-08-03 |
| Transformers | `v4.57.6` | tag target `753d61104116eefc8ffc977327b441ee0c8d599f` | Isaac Lab exact dependency |
| Isaac Lab | `v3.0.0-beta` | `a4a7602f29e755e2673fe0022ea35566df6dd7d5` | released beta |
| Isaac Lab | `v3.0.0-beta2` | `28a37cecdd433c22d9eabd6a5954add9f13a8951` | released beta |
| Isaac Lab | `v3.0.0-beta2.patch1` | `ffff603eafc6b74264a5261cc0183d6a65390d78` | latest release; released 2026-07-02 |
| Isaac Lab | `release/3.0.0-beta2` | `bffdce9d7467f349bfc8ab111fe633a0bb234851` | post-release research only; not a tag |
| Isaac Lab | `develop` | `630317ba1ff900c120a65e705a688b9514f353a8` | research only; not selectable |
| Isaac Sim | PyPI/NVIDIA wheel release | `6.0.1.0` | current patch candidate |
| Isaac Sim | PyPI/NVIDIA wheel release | `6.0.0.1` | beta/beta2 candidate |
| Isaac Teleop | PyPI release/tag | `1.3.131`, `7002ed63d69454ae4f15c0ee19f803fd2846592b` | current Quest integration candidate |

Primary evidence:

- [LeRobot 0.6.1 exact metadata](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/pyproject.toml)
- [Isaac Lab release list](https://github.com/isaac-sim/IsaacLab/releases)
- [Isaac Lab patch-1 core metadata](https://github.com/isaac-sim/IsaacLab/blob/ffff603eafc6b74264a5261cc0183d6a65390d78/source/isaaclab/setup.py)
- [Transformers 4.57.6 dependency table](https://github.com/huggingface/transformers/blob/753d61104116eefc8ffc977327b441ee0c8d599f/src/transformers/dependency_versions_table.py)
- [Isaac Sim 6.0.1 kernel metadata](https://pypi.org/pypi/isaacsim-kernel/6.0.1.0/json)
- [Isaac Sim 6.0.1 core metadata](https://pypi.org/pypi/isaacsim-core/6.0.1.0/json)
- [Isaac Teleop 1.3.131 metadata](https://pypi.org/pypi/isaacteleop/1.3.131/json)

## 2. Complete resolver conflict

The originally reported Hugging Face collision is exact and sufficient to make
the set unsatisfiable:

```text
lerobot==0.6.1
  -> huggingface-hub>=1.6.0,<2.0.0

isaaclab==6.1.14 (source at v3.0.0-beta2.patch1)
  -> transformers==4.57.6
     -> huggingface-hub>=0.34.0,<1.0

intersection: empty
```

The expanded audit found additional empty intersections in the published
Isaac Sim 6.0.x package metadata. A Transformers-only fix would therefore not
make the complete environment resolvable:

| Dependency | LeRobot 0.6.1 | Isaac/NVIDIA requirement | Intersection |
|---|---|---|---|
| Python | `>=3.12` | Isaac Sim `==3.12.*`; patch-1 source `>=3.12` | `3.12.*` — compatible |
| torch | `>=2.7,<2.12` | Isaac Sim core `==2.11.0`; Isaac Lab source package `>=2.10` | `2.11.0` — compatible for source-package install |
| torchvision | `>=0.22,<0.27` | Isaac Sim core `==0.26.0` | `0.26.0` — compatible |
| huggingface-hub | `>=1.6,<2` | Transformers 4.57.6 `>=0.34,<1` | **empty** |
| numpy | `>=2,<2.3` | Isaac Sim kernel `==2.3.1` | **empty** |
| packaging | `>=24.2,<26` | Isaac Sim core `==26.0` | **empty** |
| Gymnasium | `>=1.1.1,<2` | Isaac Lab `==1.2.1` | `1.2.1` — compatible |
| Pillow | `>=10,<13` | patch-1/Sim kernel `==12.2.0` | `12.2.0` — compatible |
| pydantic | no conflicting LeRobot base pin | Isaac Lab `>=2.7,<2.12`; FastAPI admits `<3` | compatible range exists |
| typing_extensions | no conflicting LeRobot base pin | Isaac Lab/Sim kernel `==4.12.2` | compatible with audited direct requirements |
| coverage | no LeRobot runtime requirement | Isaac Lab `==7.6.1`; Sim kernel `==7.4.4` | **empty inside NVIDIA stack** |
| websockets (S2 only) | no LeRobot base requirement | Isaac Teleop CloudXR `>=14`; Sim kernel `==12.0` | **empty inside NVIDIA stack** |

The repository-root Isaac Lab uv development environment also pins
`torch==2.10.0`, while `isaacsim-core==6.0.1.0` pins `torch==2.11.0`. The
official source-package metadata is broader (`torch>=2.10`) and can admit
2.11.0, so this particular collision can be avoided by the supported
source-package installation model. It does not repair the four unconditional
conflicts above.

The exact earlier dry-run already stopped at the first contradiction:

```text
Because lerobot==0.6.1 depends on huggingface-hub>=1.6.0,<2.0.0 and
transformers==4.57.6 depends on huggingface-hub>=0.34.0,<1.0,
lerobot==0.6.1 and transformers==4.57.6 are incompatible.
```

No package was installed. The full conclusion above is a direct set-intersection
check over the signed/released package metadata; it does not depend on import
success in an invalid environment. NVIDIA's own [dependency-conflict issue
#6200](https://github.com/isaac-sim/IsaacLab/issues/6200) independently records
the Isaac Sim 6.0 `packaging==26.0` and `numpy==2.3.1` class of conflicts, but
links no released fix or supported constraint set.

## 3. Why Isaac Lab core requires Transformers

The complete Python-source search at patch-1 found exactly one Transformers
import:

```text
source/isaaclab/isaaclab/envs/mdp/observations.py:571
    from transformers import AutoModel
```

It is a lazy import inside
`image_features._prepare_theia_transformer_model()`. The path calls
`AutoModel.from_pretrained("theaiinstitute/<theia model>",
trust_remote_code=True)` to provide optional frozen Theia image-feature
observation terms. The only shipped task configuration found selecting that
path is a Theia cartpole camera variant. ResNet feature terms use torchvision.
The same single runtime import remains on audited `develop`.

Capability classification:

| S0/S1 follow-on capability | Uses Transformers/Theia path? | Classification |
|---|---:|---|
| PIPER-X articulation, reset, step, actions | no | unrelated optional functionality |
| raw joint/gripper observations | no | unrelated optional functionality |
| raw left/right wrist cameras | no | unrelated optional functionality |
| Quest/CloudXR teleoperation | no | unrelated optional functionality |
| native RecorderManager/HDF5 recording | no | unrelated optional functionality |
| scripted-expert generation | no | unrelated optional functionality |
| LeRobot checkpoint evaluation | no Isaac-side Theia term is selected | unrelated; the LeRobot policy owns its image preprocessing |

The dependency is nevertheless unconditional in the core `isaaclab` package's
`install_requires`. It is therefore a real metadata contract for an optional
core feature and packaging-level over-coupling for this project's capability
subset. Its optional runtime use does not authorize deleting or bypassing the
declared requirement.

The exact pin was introduced by commit
[`438629c09721365c3cfc0096f15da356d8259ba5`](https://github.com/isaac-sim/IsaacLab/commit/438629c09721365c3cfc0096f15da356d8259ba5)
(PR #4484) after Transformers 5.0 meta-device behavior broke the Theia example.
That commit is the origin of the current constraint, not a fix for the
LeRobot/Hub collision.

## 4. Current Isaac Lab 3.0 upstream status

- `v3.0.0-beta2.patch1` remains the newest released tag. There is no released
  RC, GA, or later patch in the official release list.
- The current post-tag `release/3.0.0-beta2` branch still declares
  `transformers==4.57.6`.
- Current `develop` at `630317ba...` centralizes dependencies in root
  `pyproject.toml` but still declares `transformers==4.57.6`.
- No fetched official ref contains a commit that removes, relaxes, or scopes
  the Transformers dependency, and no official Hub-compatible constraint set
  was found.
- The [Isaac Lab 3.0 GA milestone](https://github.com/isaac-sim/IsaacLab/milestone/2)
  is open, has no due date, and was 85% complete (12 closed, 2 open) at audit
  time. A milestone is not a release or a compatibility promise.

Therefore this is not result B: no upstream fix exists even on `develop` as of
the audit. There is no evidence-backed earliest release expected to contain a
fix. The safe revisit trigger is an immutable released tag whose complete
metadata resolves with LeRobot 0.6.1 and the required Isaac Sim/Teleop packages.

## 5. Released candidate matrix

| Released first-party candidate | Required capability coverage | Metadata result | Selection |
|---|---|---|---|
| Isaac Lab `v3.0.0-beta2.patch1` + Isaac Sim `6.0.1.0` | closest match; Sim, cameras, RecorderManager, Mimic/datagen, Isaac Teleop APIs | Hub, NumPy, packaging, and coverage intersections are empty; CloudXR adds websockets conflict | rejected |
| Isaac Lab `v3.0.0-beta2` + Isaac Sim `6.0.0.1` | Sim 6.0 release line and relevant 3.0 APIs | same Transformers/Hub, Sim NumPy, Sim packaging, and coverage conflicts; source extra also retained a stale `isaacsim==5.1.0` entry despite release-level 6.0 support | rejected |
| Isaac Lab `v3.0.0-beta` + Isaac Sim `6.0.0.1` | first 3.0 architecture/Teleop release | same Hub, NumPy, and packaging conflicts; older beta with no remediation advantage | rejected |
| Isaac Lab `v2.3.2` + Isaac Sim `5.1` | stable 2.x core, but older teleop/recording architecture | Sim 5.x runtime is Python 3.11 while LeRobot requires Python >=3.12; Transformers 4.57.6 retains Hub conflict | rejected |
| Current `develop` / post-tag release branch | research evidence only | still carries Transformers 4.57.6 and is not an immutable release | not selectable |
| Isaac Lab kit-less Newton/OV paths | first-party but not the requested Isaac Sim capability set | does not supply the selected Isaac Sim/Quest/RTX/recording path and core still carries Transformers | not an alternative |
| IsaacLab-Arena/main or other wrappers | not a released replacement for accepted PIPER-X task/evaluation; uses dependency overrides | violates first-party released pin and no-override criteria | rejected |

Across the 6.0.x rows, the common compatible subset is Python 3.12,
torch 2.11, torchvision 0.26, Gymnasium 1.2.1, Pillow 12.x, and an admissible
pydantic/typing_extensions pair. Those compatible fields cannot compensate for
the empty intersections.

## 6. Official modular-install and constraint checks

**Official modular-install escape: NO.** The patch-1 source installation docs
state that `./isaaclab.sh -i` always installs the core source packages and that
the `core` selection only excludes optional submodules/features. The
unconditional Transformers dependency belongs to that unavoidable core
`isaaclab` package. Selecting `core`, omitting `teleop`/`mimic`, or installing
only task submodules cannot remove it through supported metadata.

Sources:

- [Patch-1 selective installation documentation](https://github.com/isaac-sim/IsaacLab/blob/ffff603eafc6b74264a5261cc0183d6a65390d78/docs/source/setup/installation/include/selective_install.rst)
- [Patch-1 core setup metadata](https://github.com/isaac-sim/IsaacLab/blob/ffff603eafc6b74264a5261cc0183d6a65390d78/source/isaaclab/setup.py)

**Official constraint/workaround: NO.** No NVIDIA documentation or released
constraint file was found that produces a version set satisfying both projects
without violating metadata. Patch-1's root uv configuration includes
`override-dependencies = ["numpy>=2"]`; this deliberately supersedes exact
transitive metadata and cannot satisfy this audit's no-violation condition.
An experimental RLInf document uses `--no-deps` for an unrelated package set;
that is neither a LeRobot workaround nor permitted here. Closing issue #6200
without a linked release, PR, or constraint set is not an endorsed solution.

No `setup.py` edit, dependency deletion, `--no-deps`, forced override, or fork
is selected.

## 7. Same-process semantics by gate

| Gate | Isaac process owns | LeRobot/core process owns | Isaac + LeRobot same process semantically required? | Existing upstream boundary |
|---|---|---|---:|---|
| S1 | environment construction, reset/step, native actions/observations/cameras, parity measurements | accepted contract and offline artifact checks | **NO** for native environment bring-up/parity | files/config/parity artifacts; no per-step IPC needed |
| S2 | Isaac Teleop session, controller streams, retargeting, PIPER-X mapping, native environment step | no LeRobot operation required | **NO** | CloudXR/OpenXR is NVIDIA-owned; this does not solve the separate Sim/Teleop websockets metadata collision |
| D1 | RecorderManager writes native HDF5 with episode outcome | deterministic HDF5-to-LeRobotDataset-v3 conversion/materialization | **NO** | native HDF5 file boundary and replay metadata |
| G1 | scripted expert, native environment, success/failure, RecorderManager | deterministic conversion/materialization and common-view checks | **NO** | native HDF5 plus run/generation manifests |
| E1 | seeded environment reset/step, termination/timeout/success and native metrics inputs | checkpoint load, LeRobot pre/postprocessors, policy inference, `lerobot-eval` aggregation/result | **YES** for the selected normal `lerobot-eval` seam | none that preserves the required evaluation contract |

This distinction means S1/S2/D1/G1 do not themselves justify an invented
LeRobot/Isaac process API. It does not unblock S0 because E1 is mandatory and
the selected evaluation architecture exchanges policy observations/actions on
every environment step.

## 8. Existing process-boundary audit

LeRobot 0.6.1 does contain an upstream async-inference gRPC utility:

- [`policy_server.py`](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/async_inference/policy_server.py)
- [`robot_client.py`](https://github.com/huggingface/lerobot/blob/7e241bd630a3719a56157a497ce5d08f244784f1/src/lerobot/async_inference/robot_client.py)

It does not solve E1:

1. `RobotClient` is coupled to `RobotConfig`, `make_robot_from_config()`, and a
   connected LeRobot robot; it is not a Gymnasium/Isaac environment client.
2. Installing the client still installs/imports the LeRobot distribution in
   the Isaac process, recreating the package conflicts.
3. The service transports timed observations and asynchronous action chunks.
   It has no reset, seed, terminated, truncated, success, episode, horizon, or
   evaluation-metrics messages.
4. Its queue filtering/action aggregation is not the deterministic one-policy-
   decision-per-environment-step behavior selected for E1.
5. Adapting or reimplementing this protocol for simulator evaluation would be
   new process/evaluation architecture, not reuse of a complete upstream
   `lerobot-eval` boundary.

NVIDIA LEAPP is a same-process exported-policy runtime and has no released
LeRobot-checkpoint/processor exporter. Isaac ROS, CloudXR, Rerun gRPC, and MCAP
serve different concerns and do not provide the missing policy-evaluation
contract. A container or second environment is only isolation; without an
upstream policy/evaluation protocol it is not an execution boundary.

Consequently result C is not available. No custom RPC or thin process adapter
is proposed or implemented in this audit.

## 9. Host remediation (independent of architecture)

### NVIDIA driver

- Installed package/kernel module: `580.159.03` (`nvidia-driver-580`).
- Isaac Sim 6.0.1 x86_64 published/tested Linux driver: `595.58.03`.
- The module is loaded, but `nvidia-smi` could not communicate with the driver
  during this audit, which is an additional host-health check for the operator.
- Upgrade requires host-administrator package/module control and normally a
  reboot (or equivalent GPU module reload). It changes no project Python pin or
  software architecture and was not attempted.

[NVIDIA's Isaac Sim 6.0.1 requirements](https://docs.isaacsim.omniverse.nvidia.com/6.0.1/installation/requirements.html)
publish the driver and storage minimums.

### Storage

- Published minimum: 50 GB SSD.
- Current target filesystem at audit: 7,079,378,944 bytes available
  (approximately 6.6 GiB), far below 50 GB. `/tmp` is on the same filesystem,
  so it is not an escape.
- No files, caches, packages, or assets were deleted or moved.

An operator may place the Python environment/runtime and download cache on a
different filesystem. uv supports `UV_PROJECT_ENVIRONMENT` and `UV_CACHE_DIR`.
Isaac/Kit supports `--portable-root PATH` for data/cache/logs. The ordinary
Linux locations are `~/.cache/ov/Kit`, `~/.local/share/ov/data/Kit/Isaac-Sim`,
and `~/.nvidia-omniverse/logs/Kit/Isaac-Sim`; downloaded Isaac assets can also
live in an explicitly selected asset pack/root. Container installations expose
official cache, ComputeCache, log, config, data, package, and Hub-cache volume
mounts. The chosen alternate filesystem must have enough capacity for the
environment, wheel/download cache, extension/shader caches, and assets—not just
50 GB nominal free space.

Sources:

- [Isaac Sim 6.0 setup paths and `--portable-root`](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/installation/install_faq.html)
- [Isaac Sim 6.0 container cache/data mounts](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/installation/install_container.html)
- [uv storage locations](https://docs.astral.sh/uv/reference/storage/)

These driver and storage tasks are operational prerequisites. They are not
reasons to alter policy/runtime architecture and would not cure the resolver.

## 10. Decision and revisit condition

**Result D — NO SUPPORTED PATH.** No released same-process Isaac Lab/Isaac Sim/
Isaac Teleop set resolves with accepted LeRobot 0.6.1 under normal upstream
metadata, and no existing upstream process boundary supplies the complete E1
evaluation semantics.

No architecture change is made. S0 remains blocked. The safest next action is
to wait for and re-audit a released NVIDIA stack that:

1. supports the required Isaac Sim, RecorderManager, datagen, teleop, and
   evaluation APIs;
2. has nonempty intersections for Hub, NumPy, packaging, coverage, and the
   selected Teleop extras;
3. resolves normally with LeRobot 0.6.1; and
4. is eligible on a host with the required driver and storage.

If proceeding before such a release becomes necessary, a separately authorized
decision must reconsider either the accepted LeRobot pin or the accepted
same-process E1 evaluation assumption. This audit authorizes neither and does
not justify a dependency hack, unreleased branch, fork, or invented RPC.
