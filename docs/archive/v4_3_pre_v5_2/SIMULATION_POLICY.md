# SIMULATION_POLICY.md

## 1. Principle

Simulators are tools, not project architecture.

Do not create a universal simulator backend and do not create a simulator-specific environment until its pinned runtime proves one is needed.

Read `ENVIRONMENT_POLICY.md`.

---

## 2. MuJoCo

Use only if it materially improves:

- deterministic offline tests
- lightweight physics/kinematics CI
- cheap Robot-like simulation

Keep it in `core` if compatible.

A separate `mujoco` environment requires an actual dependency/runtime conflict.

Preserve native Gym evaluation semantics.

---

## 3. EmbodiChain

Optional.

Before integration:

- pin exact version/commit
- inspect current API
- verify PIPER-X support
- verify dependency/runtime compatibility with core
- create a special environment only if incompatibility is demonstrated

Do not make it a blocker for Quest -> dataset baseline.

---

## 4. Isaac / LW-BenchHub

Use as reference/alternative simulation where useful.

Do not assume `DoublePiper` geometry equals PIPER-X.

Distinguish:

```text
Isaac Teleop dependency used in the core XR/control path
vs
Isaac Sim/vendor simulator runtime
```

They may have different environment requirements.

Do not split the core Quest control path merely because Isaac Sim itself has a vendor-specific runtime.

---

## 5. RoboTwin

Reuse pinned native LeRobot RoboTwin integration.

Before benchmark acceptance:

```text
1. pin LeRobot integration
2. pin benchmark/dataset revision
3. resolve environment ownership
4. smoke-test declared action space
5. smoke-test observation keys/shapes
6. record known upstream issues
```

Create a RoboTwin-specific environment only if pinned dependencies cannot coexist with core or its runtime explicitly requires isolation.

Do not create `RoboTwinBackend`.

---

## 6. Process/environment isolation

Default:

```text
one core environment
direct in-process integration
```

A special environment normally implies a separate process.

Allow it only after a real:

- Python/dependency conflict
- torch/CUDA conflict
- vendor runtime requirement
- simulator process requirement
- stability/failure-domain requirement

Then use the smallest transport needed, and only after confirming the process boundary is semantically acceptable.
