# Master versus CURRENT physics and RTF assay

This experiment compares exact OLD `master` `76b93ee6562ac1da2e21551d1aff5454cfd7a859`
and CURRENT `experiment/vr-record-runtime-optimization-audit`
`a36bc5cc302eefef19fe4f94063a3f6179aaf1aa`. Both remote refs were
verified with `git ls-remote` before branch creation. Neither source checkout is
modified. The experiment branch starts at CURRENT.

## Question and interpretation

Compare native trajectories by simulated time first. A wall-time rate difference
alone changes perceived fall, rebound, and actuator speed without changing PhysX
dynamics. Keep trajectory sampling separate from the no-readback rate pass because
120 Hz GPU-to-CPU readback itself slows the loop. The no-client result is a
bounded scene/render workload, not a physical Quest operator observation.

## Execution

After accepting both NVIDIA EULAs, run from this branch using the declared
Isaac 6.1 environment through each checkpoint's `./run-vr`:

```sh
OMNI_KIT_ACCEPT_EULA=Y ISAACLAB_CXR_ACCEPT_EULA=1 python \
  docs/experiments/20260924_master_current_physics_rtf_audit/launch_pair.py \
  --old /home/ebulochkin/vla_infrastructure \
  --current /home/ebulochkin/vla_infrastructure/.worktrees/vr-record-runtime-optimization-audit \
  --output /home/ebulochkin/vla_infrastructure/.worktrees/vr-master-current-physics-rtf-audit/docs/experiments/20260924_master_current_physics_rtf_audit \
  --state-parent /tmp/vr-physics-rtf-20260924
```

The process-local `sitecustomize.py` intercepts only the final `run_s2` call,
after each exact source revision has constructed and validated the VR scene.
`physics_assay.py` applies identical native targets and samples each 120 Hz
substep. OLD keeps its four rendered steps. CURRENT selects the production
RECORD `FFFT` step policy, disables live RGB, and calls the same dataset camera
suspension adapter. The experiment does not commit dataset rows or use a headset.
Each state root contains its own generated URDF and converted USD; this prevents
either assay from consuming the other's conversion output.

Cases: a cube outside the table footprint dropped with zero initial velocity
(analyzed only through 0.4 simulated seconds, before floor contact);
a cube above the open table corner at `(1.10, 0.40, 1.12)` metres dropped with zero initial velocity; free
gripper closure from 100 mm to 0 mm; and a left first-arm-joint target 10 degrees
from the shared home. Every case has three deterministic repetitions. A separate
30-control warmup and 300-control timing pass records control boundaries without
native readback. The `geometric_table_contact_proxy` is a cube-height threshold,
not a PhysX contact impulse.

The first OLD bounce placement `(0.52, 0.17, 1.12)` was in the arm workspace:
the cube moved laterally before table impact. Its raw trace is retained as
`samples-old-attempt1.json.gz` at the path and SHA-256 in `provenance.json`; it is
excluded from the paired bounce comparison. Both completed paired native traces and the failed OLD attempt
are compressed under `/data/ebulochkin/vla_physics_rtf_20260924/`, with hashes
and exact locators in `provenance.json`. The source bundle keeps concise derived
results and plots in Git.

When both sample files exist, render the requested plots and concise metrics:

```sh
/data/vla-infrastructure/isaac61_production/env/bin/python \
  docs/experiments/20260924_master_current_physics_rtf_audit/summarize.py \
  docs/experiments/20260924_master_current_physics_rtf_audit
```

## Reuse and scope

| Discipline | Decision |
|---|---|
| Capability / gate | Physics forensics; no gate promotion or physical claim |
| Pinned upstream candidates | Isaac Sim 6.1, Isaac Lab 17.0.2 materialization, `RigidObject`, `Articulation`, `SimulationContext`, USD/PhysX APIs |
| Upstream ownership | Integration, native state tensors, USD properties, URDF conversion cache validation |
| Remaining gap | Paired substep and wall-clock records with matched deterministic commands |
| Adapter | Process-local import hook and bounded case runner; no production path changes |
| Environment impact | Existing declared Isaac environment; no dependency installation |
| Framework need | None; this is one experiment against the concrete VR scene |

The generated USD cache directory in production is named by composed URDF SHA,
but the pinned `AssetConverterBase` also hashes converter configuration and the
main asset before lazy reuse. It does not hash referenced secondary asset files;
the two source trees are checked against the same accepted source files and the
assay uses isolated state roots.

Every tracked bundle member is indexed in `docs/INDEX.yaml`. This forensic
experiment changes no selected contract fact, gate state, or production default;
it therefore has no contract artifact/evidence registration or gate binding.
`provenance.json` supplies exact raw trace locators and digests for review.
