# PIPER-X + Quest 3 Codex Instruction Pack — v4.3 environment-hardened

v4.3 keeps the v4.2 architecture and adds one missing operational contract:

> which reproducible environment owns each runnable component, and what to do when dependency / Python / CUDA / vendor-runtime constraints conflict.

This remains an integration project, not an environment-orchestration framework.

## Core rule

```text
REUSE
> CONFIGURE
> COMPOSE
> THIN ADAPTER
> NEW IMPLEMENTATION
```

## Contract model

```text
pinned upstream evidence
        │ must agree
        ▼
configs/resolved_contract.yaml
        │ validated runtime + environment contract
        ▼
reproducible environment lock/manifest(s)
        │
        ▼
implementation / tests / hardware
```

Any mismatch between pinned evidence, the resolved contract, or the environment actually used to run a stage is an error.

## Environment model

Start with ONE default `core` environment.

The core environment should contain every component that is compatible and intended to run in the main process:

```text
project
LeRobot
selected PIPER-X Robot/plugin
selected AgileX driver
dataset / record / replay / rollout
HIL
Quest/Isaac Teleop integration IF compatible with the same process/runtime
```

Create another environment only after a concrete conflict is demonstrated, such as:

```text
incompatible Python
incompatible torch/CUDA
vendor runtime constraint
simulator-specific runtime
dependency conflict
required process isolation
```

A second environment is not free architecture. If two components must share one process, an environment conflict between them is a BLOCKER until resolved; do not silently split them across processes.

## Canonical files

- `AGENTS.md` — binding global rules.
- `ENVIRONMENT_POLICY.md` — environment selection, locking, conflicts and launch ownership.
- `PIPER_X_VERIFICATION.md` — PIPER-X Robot/driver/firmware resolution.
- `configs/resolved_contract.yaml` — only resolved machine-readable contract.
- `configs/resolved_contract.schema.json` — structural schema.
- `tools/validate_resolved_contract.py` — gate validator.
- `HIL_EXTENSION.md` — per-arm HIL / async generation semantics.
- `SAFETY_TIMING.md` — action-label/safety/timing/inter-arm invariants.
- `SIMULATION_POLICY.md` — simulator and process-isolation policy.
- `IMPLEMENTATION_PLAN.md` — staged work and environment gates.
- `ACCEPTANCE_CHECKLIST.md` — review gate.

Quest 3 is already available, so XR bring-up can run in parallel once the environment that owns it is resolved.

## Session 0 core environment

The repository currently contains contract and validation tooling only; no prior
package-manager convention or robotics dependency is present to reuse. The one
default environment is therefore the checked-in `uv` environment in
`pyproject.toml` / `uv.lock`:

```text
environment id: core
manager: uv
Python: CPython 3.10.12
purpose: contract tooling, offline checks, and the future main runtime once
         Tracks A/B/C supply compatible pinned dependencies
canonical prefix: uv run
```

Recreate it, including the development tools, with:

```bash
uv sync --frozen --all-groups
```

Run the Session 0 checks from `core` with:

```bash
uv run python tools/validate_resolved_contract.py configs/resolved_contract.yaml
uv run python -m unittest discover -s tests
uv run ruff check .
uv run mypy
```

This initial spec intentionally has no torch, CUDA, simulator, vendor-runtime,
LeRobot, driver, or XR package. Their pinned requirements and same-process
compatibility are prerequisites for Tracks A, B, and C; they must be added to
this same lock first unless concrete evidence proves a blocker.
