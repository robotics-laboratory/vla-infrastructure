# ENVIRONMENT_POLICY.md

## 1. Purpose

Define exactly:

- which environment is the default;
- when a second environment is justified;
- how environments are reproduced;
- which environment runs each stage/component;
- how Python/CUDA/torch/vendor-runtime conflicts are handled.

This is not a request to build an environment management framework.

---

## 2. Default: one core environment

Start with exactly one resolved environment:

```text
environment id: core
purpose: main runtime + normal development/tests
```

Put compatible in-process components there:

```text
project source
LeRobot
selected PIPER-X Robot/plugin
selected AgileX driver backend
dataset / record / replay / rollout
HIL
ordinary tests/tools
Quest/Isaac Teleop dependencies if compatible
MuJoCo if compatible and actually used
```

Do not pre-create special environments.

---

## 3. What makes an environment reproducible

Every required environment must resolve:

```text
environment id
purpose
package/environment manager or vendor launcher
Python version
lock/specification artifact
lock/specification artifact hash where stable/applicable
torch version if relevant
CUDA/runtime expectation if relevant
system/vendor runtime requirements if relevant
canonical activation/launch procedure
```

Use existing project/upstream conventions when possible.

Examples of acceptable specification mechanisms include:

```text
pyproject.toml + uv.lock
requirements/constraints lock
conda environment file + explicit lock
vendor-provided container/runtime manifest
pinned Dockerfile/image digest
simulator/vendor launcher with pinned manifest
```

Do not invent a custom package resolver.

Do not require one universal lock format across incompatible vendor ecosystems.

---

## 4. No invisible mutations

Do not treat this as reproducible:

```text
conda activate old-working-env
pip install random-package
run successfully
```

unless the change is reflected in the resolved environment specification.

A one-off diagnostic installation may be used experimentally, but the stage cannot be accepted until the reproducible spec is updated and recreated/tested.

---

## 5. When a special environment is allowed

A second environment may be created only after a concrete conflict is demonstrated and recorded.

Valid reasons include:

```text
Python version conflict
torch version conflict
CUDA runtime/toolkit conflict
binary ABI conflict
vendor runtime requirement
simulator process/runtime requirement
dependency versions that cannot coexist
intentional failure-domain/process isolation
```

Invalid reasons include:

```text
"cleaner"
"best practice"
"simulators should be separate"
"we may need it later"
"different component name"
```

Record evidence, for example:

```text
package A requires torch X
package B requires torch Y
vendor docs require Python Z
import/runtime test proves ABI conflict
```

---

## 6. Same-process compatibility is a hard constraint

Environment separation implies a process boundary.

Therefore:

> if two components must run in the SAME process, they must resolve into one compatible environment.

This especially matters for the baseline:

```text
one Isaac Teleop/CloudXR lifecycle
+
left/right controller streams
+
LeRobot processing/control path
```

If the chosen pinned versions cannot coexist in one environment and the architecture requires same-process integration, this is a BLOCKER.

Do not silently "solve" it by inventing RPC.

Possible resolutions:

1. choose another compatible pinned upstream version/component;
2. use an upstream-supported extension/process boundary that preserves the required semantics;
3. prove that process separation is actually acceptable and then update the architecture/contract;
4. otherwise stop the gate.

---

## 7. Execution profiles

Every runnable stage must map to a resolved environment id.

Baseline profiles:

```text
offline_tests
core_runtime
piper_readonly
piper_motion
quest_xr
dataset_record
replay
rollout
hil
```

Optional profiles may include:

```text
robotwin
embodichain
isaac_sim
mujoco
```

Do not guess the active environment from shell history.

The canonical mapping belongs in `configs/resolved_contract.yaml`.

---

## 8. Environment activation/launch

Each required environment must have one documented canonical way to run commands.

Examples:

```text
uv run ...
conda run -n <env> ...
vendor launcher ...
docker compose run ...
```

The contract should store a stable launch prefix/profile, not a user's temporary interactive shell state.

Tests/reports must state which environment id was used.

---

## 9. CUDA / GPU rule

Do not conflate:

```text
host NVIDIA driver
CUDA toolkit/runtime in environment
PyTorch CUDA build
simulator/vendor runtime
```

Resolve only the pieces relevant to each environment.

Before separating environments due to "CUDA conflict", prove the actual incompatibility from pinned package/runtime requirements or an executable smoke test.

---

## 10. Simulator environments

Follow `SIMULATION_POLICY.md`.

A simulator may get its own environment if its pinned runtime requires it.

Examples:

```text
RoboTwin -> special env only if its dependencies conflict with core
EmbodiChain -> special env only if actually used and incompatible
Isaac Sim -> often vendor-specific runtime; resolve from pinned requirements
MuJoCo -> stay in core if compatible
```

The simulator's size is NOT by itself a reason for another Python environment.

Storage location and runtime environment are separate concerns.

---

## 11. Docker later

Native-first implementation must remain containerizable.

Do not make code depend on shell-specific absolute paths or implicit activation state.

External resources must be configurable:

```text
dataset/model/cache roots
CAN interfaces
camera devices
ports
calibration paths
sim assets
```

Later containerization should normally map:

```text
core environment -> core image
special environment -> separate image only if it already had a justified runtime boundary
```

Do not introduce RPC merely because Docker may be used later.

---

## 12. Gate behavior on conflicts

When a dependency conflict appears:

```text
1. capture exact error / requirement evidence
2. determine whether conflicting components must share a process
3. try compatible pinned upstream resolution first
4. only then create a special environment if justified
5. update resolved_contract.yaml
6. create/update reproducible lock/spec
7. validate from a clean/recreated environment
8. only then continue the stage
```

No "works on this shell" acceptance.
