# Gate S0 process-boundary decision — repin confirmation

Decision date: 2026-09-08
Result: **PRESERVED / PASS**

The Candidate B repin changes the Isaac implementation/environment identity, not
the policy-facing architecture.

```text
core process (LeRobot policy/eval ownership)
        |
        | D0 canonical policy/data semantics
        | EVAL: synchronous, episode-sensitive, one step in flight
        | CONTROL: independent, asynchronous/freshness-sensitive
        | transport selection deferred for both
        v
isolated Isaac process (Candidate B native runtime)
```

## Exact selections

| Fact | Selection |
|---|---|
| Isaac Lab | `release/3.0.0`, `913ac53f51b2f8d02c9e121caa4cbdd06262948e` |
| Isaac Sim | `6.0.1.0` |
| Isaac environment | exact Candidate B frozen uv workspace, CPython 3.12.13 |
| Core/LeRobot | unchanged LeRobot 0.6.1 at `7e241bd…` |
| D0 boundary | unchanged `piper_x_d0_policy_data_v1` |
| EVAL transport | deferred to E1 |
| CONTROL transport | deferred to its owning later gate |

## Decision invariants

- `same_process_lerobot_isaac_required = false`.
- `generic_simulator_api_exists = false`.
- `rpc_implementation_selected = false`.
- LeRobot is excluded from the Isaac environment.
- Native observation/action dictionaries do not cross the EVAL boundary.
- EVAL and CONTROL do not share retry, lifecycle, timing, or transport semantics.
- S1 runs directly inside the isolated Isaac environment; it needs no per-step IPC.

Candidate B owns camera transforms and publication through its upstream parented
Camera/FrameView path. This does not create a reason for same-process
LeRobot+Isaac or for a project framework.

## Driver and dependencies

The current driver `580.159.03` satisfies Candidate B's documented `580.95.05+`
recommendation and passed the qualified runtime; no host-driver blocker remains.
Candidate B's 11 visible metadata incompatibilities arise from its upstream
`[tool.uv].override-dependencies`; the qualified S1 surface passes, while S2/XR
must recheck the expanded environment.

## Gate ownership

S0 owns this pin/environment/boundary selection. S1 owns the concrete PIPER-X
environment, direct D0 mappings, task, cameras, reset/step, parity, and executable
evidence. S2, D1, G1, and E1 remain untouched.
