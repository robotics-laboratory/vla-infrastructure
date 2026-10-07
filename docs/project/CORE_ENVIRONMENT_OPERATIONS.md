# Core Environment Operations

This project-specific operating note preserves the live repository information that accompanied the pre-v5.2 README. It is not a second resolved contract; `configs/resolved_contract.yaml` remains authoritative.

The existing default environment is the checked-in `uv` environment described by `pyproject.toml` and `uv.lock`.

```text
environment id: core
manager: uv
Python: CPython 3.12.13 (.python-version and pyproject.toml)
canonical prefix: uv run
```

Recreate the normal development environment with:

```bash
uv sync --frozen
```

The pinned Isaac Teleop/CloudXR dependency group is declared in the same project specification but is not required for ordinary offline checks:

```bash
uv sync --frozen --group isaac-teleop
```

The host-side Quest diagnostic is:

```bash
uv run python tools/quest_xr_diagnostics.py --help
```

This command does not establish physical Quest acceptance by itself. The v5.2 Gate B human evidence requirements still apply.

For the current **Quest -> Isaac** operator workflow use `./run-vr` and
[RUN_VR_OPERATIONS.md](RUN_VR_OPERATIONS.md). It selects the final Isaac61
environment and canonical VR composition. `./run-vr diag` adds observers to the
same runtime. Registered physical Quest 3 S2 acceptance covers the retained RUN
and RECORD sessions on clean `f2ac4ea` and the operator's checklist observations.
Later operator-stop reporting changes passed automated checks without another
headset run; see the
[acceptance supplement](../evidence/S2/20261006_operator_recording_audit/operator_stop_acceptance.json).
D1 dataset source admission remains unresolved. This core host diagnostic is a
separate real-XR profile.

## Required project checks

[[profile:offline_tests]] checks core code and deliberately deselects the
`isaac_upstream` tests. [[profile:isaac_upstream_tests]] runs those tests with
standard-library `unittest` in the exact pinned Isaac environment. The runner
verifies the SDK checkout, spec hashes and installed pins; missing imports,
skips, an empty suite and failures are errors. It does not start Kit or XR.
The SDK does not need pytest or LeRobot installed.

Use [[profile:project_validation]] to require both results from the core
environment in one command:

```bash
uv run --frozen --no-sync python tools/check_isaac_upstream.py --all
```

A core-only PASS does not establish upstream coverage. A workstation without
the pinned SDK can run core checks, but cannot complete project validation.
Physical Quest acceptance and dataset source admission remain separate.

Canonical commands and environment ownership are defined by the execution
profiles in the live contract. No hardware-motion command belongs in this
document.
