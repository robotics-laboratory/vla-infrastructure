# IMPLEMENTATION_PLAN.md

Quest 3 is already available.

Before Tracks A/B/C, resolve the initial environment baseline.

---

# Session 0 — Environment/bootstrap gate

1. inspect existing repo/package-manager conventions;
2. define `core` as the default environment;
3. resolve its Python/package manager/specification mechanism;
4. create or identify the reproducible lock/spec artifact;
5. map offline tests and Track A tooling to `core`;
6. do NOT create simulator/special environments yet;
7. run the validator.

### Gate E0

The repo has one reproducible `core` environment and canonical launch/activation procedure.

No special environment exists without evidence.

---

# Track A — PIPER-X Robot / driver static resolution

Run from the resolved `core` environment unless the candidate audit proves that the selected required stack cannot coexist there.

1. pin LeRobot;
2. audit PIPER-X Robot candidates;
3. build evidence matrix;
4. audit driver backend including actual Python/dependency requirements;
5. resolve firmware compatibility logic;
6. resolve core compatibility;
7. fill Phase A contract fields;
8. run environment/contract validator.

### Gate A

Pinned evidence agrees with YAML, and the selected stack has a reproducible declared execution environment.

---

# Track B — Quest / official Isaac Teleop baseline

Before implementation, resolve the `quest_xr` execution profile.

Preferred:

```text
quest_xr -> core
```

if the pinned Isaac Teleop + LeRobot integration is compatible.

If not compatible, follow `ENVIRONMENT_POLICY.md`.

Remember that splitting the XR/control path across environments implies a process boundary and may be unacceptable.

Tasks:

1. pin/run closest official LeRobot Isaac Teleop example;
2. verify Quest connection;
3. verify controller poses/buttons/tracking loss;
4. verify one session lifecycle per process;
5. expose left/right streams;
6. inspect/reuse LeRobot clutch/rebase/processors.

### Gate B

The Quest XR path runs from its declared reproducible environment and one process-local session provides both streams.

---

# Track C — Offline PIPER-X kinematics

Default execution profile:

```text
offline_tests -> core
```

1. pin official PIPER-X URDF/Xacro;
2. record repo/commit/path/hash;
3. resolve frame names;
4. reuse LeRobot kinematics;
5. cross-check QuestArmTeleop;
6. test FK/IK task-space error/continuity;
7. prepare calibration artifact scheme.

### Gate C

Offline geometry/kinematics passes from the declared environment.

---

# Integration Stage 1 — Bimanual Quest glue

The in-process integration environment must contain the actual components that share the process.

Do not "solve" environment incompatibility by inventing RPC.

Combine Tracks A/B/C with only:

```text
one-session left/right split
PIPER-X frame calibration
minimal embodiment mapping
```

---

# Integration Stage 2 — Dataset/action pipeline

Execution profile should normally be:

```text
dataset_record -> core
```

unless the resolved XR/control runtime legitimately uses another single environment.

Test:

```text
data_action
→ deterministic label processors
→ dataset_action
→ dataset.action + Robot path
→ residual device safety
```

No custom recorder/dataset framework.

---

# Integration Stage 3 — Replay

Map `replay` to a declared environment, normally `core`.

Use current LeRobot replay.

---

# Integration Stage 4 — Camera/operator visualization

Keep dataset recording independent from operator visualization.

Do not create an environment boundary solely for visualization unless a vendor runtime requires it and the process boundary is acceptable.

---

# Integration Stage 5 — Optional simulation

For every simulator:

1. prove value;
2. inspect pinned runtime requirements;
3. try core compatibility where appropriate;
4. create a special environment only if justified;
5. record the execution profile mapping.

Follow `SIMULATION_POLICY.md`.

---

# Integration Stage 6 — Policy rollout

Map `rollout` to a declared environment, normally `core`.

Use current LeRobot rollout.

---

# Integration Stage 7 — HIL baseline

Map `hil` to the environment owning the real control/inference path.

Use current LeRobot HIL/DAgger.

---

# Integration Stage 8 — Per-arm HIL

Implement only the remaining gap from `HIL_EXTENSION.md`.

Do not create a separate "HIL env" unless there is a demonstrated compatibility/process reason.

---

# Hardware Stage 1 — One-arm PIPER-X validation

Use execution profile:

```text
piper_readonly
then piper_motion
```

Both must resolve to explicit environments, normally `core`.

Do not run motion from an undeclared interactive environment.

Complete Phase B checks and low-level fail-safe validation.

---

# Hardware Stage 2 — Real simultaneous bimanual PIPER-X

Before simultaneous operation:

```text
verified inter-arm collision handling
OR
conservatively disjoint workspaces
```

The environment used must match the resolved bimanual control profile.

---

# Benchmark Stage — RoboTwin

Resolve `robotwin` environment from pinned dependency evidence.

Reuse native LeRobot integration and run contract smoke tests before interpreting results.

---

# Advanced Stage

Only on demand:

- EE-space policy/data
- relative/delta actions
- full collision checking
- remote process bridge
- large-scale synthetic generation
- alternate IK/XR

Each addition begins with a reuse + environment audit.
