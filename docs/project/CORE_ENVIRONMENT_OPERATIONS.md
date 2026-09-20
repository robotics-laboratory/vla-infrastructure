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
same runtime; final physical S2 acceptance remains pending. This core host
diagnostic is a separate real-XR profile.

Canonical offline checks are defined by the `offline_tests` execution profile in the live contract. No hardware-motion command belongs in this document.
