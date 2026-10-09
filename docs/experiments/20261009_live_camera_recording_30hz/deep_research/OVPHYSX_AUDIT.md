# Standalone OVPhysX / direct PhysX investigation

2026-10-09. Project checkout `research/live-camera-recording-30hz`, HEAD
`d5566834d29ef8bb56e4fb62bb324e23e0869100`. Existing untracked deep research
was preserved. Owner `vr.performance`, scratch experiment/audit; root agent
decides repository registration. No production files, SDK, environment,
contract, gate or physical hardware were changed. No simulation/GPU run was
performed by this agent.

## Concrete result

The publicly released standalone simulator is usable as a **separate small
physics-capacity assay**, with USD loading, batched articulation targets,
contact-capable native PhysX and host/device observations. An executable
213-line probe is `/tmp/live30-deep-ovphysx-bench.py`. It remains unexecuted.
Do not substitute standalone physics for the selected runtime until native
trajectory, contact and embodiment tests pass.

**There is no verified supported whole-scene CUDA-graph path here.** The
released `step_n_sync(4, 1/120)` saves three ctypes crossings, but its native
loop still calls `simulate` then `fetchResults` four times. Async `step()`
drains an earlier pending operation before starting the next. It does not
enqueue four physics steps for one eventual fetch. Native CPU work and waits
remain. The benefit to investigate is removing Kit/Lab scheduling and
per-substep bookkeeping, plus CPU-vs-GPU choice for two articulations.

The official performance guide explicitly identifies small scenes as a CPU
candidate and exposes `num_threads=0`. Benchmark CPU first; GPU is not
intrinsically faster for this workload. [Official performance guide](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/docs/guides/performance.md).

## Exact published package and compatibility

The package is in `NVIDIA-Omniverse/PhysX/ovphysx`; the separate repository
`NVIDIA-Omniverse/ovphysx` returned HTTP404. Latest published wheel is
`ovphysx==0.6.3`, uploaded 2026-09-16; release source commit
`da950a3537927784951853c66618036f332ca0ce`. Current repository main resolved
to `123c7dbe587e46b760d65dd91e1c184948d83258`; fetched Python API files
match the release byte-for-byte. The release bundles PhysX5.11.
[Official release](https://github.com/NVIDIA-Omniverse/PhysX/releases/tag/ovphysx-0.6.3).

PyPI's exact requirements are `ovstage==0.2.0.377349`,
`warp-lang>=1.16,<2`, `packaging>=20,<24`. Linux x86_64 wheel is
`ovphysx-0.6.3-py3-none-manylinux_2_35_x86_64.whl`, 138,962,118 bytes,
SHA256 `21cbe1877b91bdce6951e4f3ac5fd1845b99d567bb4dd742df51a5b0c081eeb5`.
Metadata is saved in `/tmp/live30-ovphysx-src/pypi.json`.
[PyPI metadata](https://pypi.org/pypi/ovphysx/json).

**Do not overlay the current optional OVRTX environment.** It has
OVStage0.2.1.385922, while this simulator requires0.2.0.377349. Existing
production also has packaging26.0, above the simulator's ceiling. Production
Warp1.16.0 and NumPy2.5.1 are known local versions; they may be pinned in a
separate environment along with packaging23.2. Neither the mismatch nor
separate dependencies mandate RPC: first determine whether matching older
OVRTX can share this OVStage, or use an application-owned immutable snapshot
boundary where isolation is genuinely needed. The supplied current OVRTX
candidate is not established compatible with this physics wheel.

Requested pin validation against PyPI succeeded: NumPy2.5.1 exists and
requires Python>=3.12; Warp1.16.0 and packaging23.2 also exist. Use the
production Python3.12 interpreter for the separate venv, as the command below
does. This is dependency metadata validation, not package installation.

Host glibc2.35 matches the wheel baseline. Prebuilt GPU runtime needs a
CUDA12.8-compatible driver, not an installed CUDA Toolkit. Reported
driver580.159.03 exceeds CUDA12.8 GA's570.26 minimum; this supports
compatibility, not proof that the package loads or this scene runs.
[Pinned Linux SDK requirements](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/physx/documentation/platformreadme/linux/README_LINUX.md),
[NVIDIA CUDA12.8 driver table](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html).

Example installation/run commands for root, who serializes GPU work:

```bash
uv venv --python /data/vla-infrastructure/isaac61_production/env/bin/python /data/ebulochkin/vla-runtime/live30-deep-20261009/optional-ovphysx
uv pip install --python /data/ebulochkin/vla-runtime/live30-deep-20261009/optional-ovphysx/bin/python ovphysx==0.6.3 ovstage==0.2.0.377349 warp-lang==1.16.0 numpy==2.5.1 packaging==23.2
/data/ebulochkin/vla-runtime/live30-deep-20261009/optional-ovphysx/bin/python /tmp/live30-deep-ovphysx-bench.py --stage /data/ebulochkin/vla-runtime/live30-20261009/piper-inputs/stage_snapshot.usd --out /data/ebulochkin/vla-runtime/live30-deep-20261009/physx-cpu-t0 --mode cpu --threads 0 --steps 3000
```

These commands were not executed by this agent. Every comparison uses a
fresh output directory and process. CPU-mode selection is process-sticky.
GPU/readback versus GPU/direct adds a separate semantic/device comparison,
not an in-process toggle.

## Exact Piper scene and fidelity gaps

Read-only `pxr.Usd` inspection used the declared production Python without
SimulationApp. Result is `/tmp/live30-deep-ovphysx-stage-audit.json`.
Retained stage SHA256 is
`03453f4d22eedb40c77cee68aabab241d0c0bf58b824f9c72afb59bef27b812b`.
It comes from an earlier injected recording with its own source identity;
it is a retained full-scene fixture, not a claim that current HEAD physically
qualified it.

Articulation roots are
`/World/LeftPiper/Geometry/world/base_link` and
`/World/RightPiper/Geometry/world/base_link`. The audit finds27 rigid-body
prim APIs, two articulation roots and18 arm/gripper DOFs. Scene uses GPU
broadphase, GPU dynamics, TGS,120Hz and scene-query support disabled;
articulation solver iterations are8/2. Native scene population must use
ALL for the arbitrary scene, so instance prototypes and physics data are
available. Register OVPhysX's codeless schemas with OVStage before the first
population call, populate, seal write ordinal, then attach.
[Pinned USD-loading sample](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/tests/python_samples/tensor_bindings.py).

**Loading the USD alone does not restore current effective controls.**
Exported arm drives have stiffness6.981317 and damping0.698132 in USD
degree-based conventions and maxForce infinity; exported finger drives
have400/40 and maxForce infinity. Lab's native arm drive is400/40 with100Nm
effort limit and5rad/s velocity limit. Native aperture/finger drives are
2000/100,10N,3m/s. Live native engine state overrides are not necessarily
authored back into USD. The prototype sets and round-trips these properties
before timing, and initializes home pose/zero velocities and held targets.
Additional runtime fields such as gravity flags, friction, masses, local
inertias, contacts and transform composition still require parity checks.

The imported canonical fingers have **no PhysxMimicJointAPI**, but the retained layer does author four NewtonMimicAPI constraints; see [raw schema audit](stage-mimic-audit-all.json). Standalone PhysX does not automatically interpret those Newton schemas. Both finger
prismatic joints carry regular linear drives. Current project `_with_mimics`
maps one aperture to carrier aperture, finger1=+aperture/2,
finger2=-aperture/2. Thus the2×9 drive target tensor carries18 native DOFs,
but the policy/source command remains14 values:12 arm angles plus2
apertures. Sending only14 raw native DOFs or enabling a new mimic constraint
would change execution. The prototype preserves all18 derived targets.

Standalone PhysX supports native GPU mimic joints and compliance, but that
is a separately qualifiable physics redesign, not a speed-preserving switch
for this exported asset. [Pinned articulation/mimic documentation](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/docs/simulation_setup/articulations.md).

Keep source intent → deterministic label →14-value dataset action → native
derived18DOF targets → executed transition. Never replace labels with drive
output. Preserve four1/120 integrations per1/30 simulation-control boundary.
Fresh state observations are read only after the completed group.

## Batched tensors, angular units and stream ownership

The benchmark intentionally uses public deprecated cached `TensorBinding`
objects for q/dq, target and drive-property access. They expose DOF names,
body names and articulation layout, for which the new session API has no
replacement yet. Reusing a stable buffer object allows cached DLPack
descriptors. Reads/writes are synchronous; create once and destroy before
topology change. The C implementation forwards old articulation DOF
position/target tensors directly to TensorAPI `getDofPositions` /
`setDofPositionTargets`; these preserve the engine's radian/metre convention.
The prototype uses those native units and explicit name-to-index mapping.
[Pinned tensor implementation](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/src/ovphysx/ovphysxTensorBinding.cpp),
[Pinned Python cached-binding implementation](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/python/ovphysx/api.py).

The **new** session API has different rules: articulation joint angular
columns `jointPosition`, `jointVelocity`, and their targets are **degrees**;
prismatic axes remain stage length units. Body angular velocities and
Jacobian angular coordinates remain radians. Convert per authored joint
axis, not across an entire mixed column. The README's tensor migration
discussion is easy to misread as an instruction to change legacy engine
tensors; inspect the actual C setter/read dispatch when selecting an API.
[Pinned session write contract](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/docs/read_write/writable.md),
[Pinned session read contract](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/docs/read_write/readable.md).

For a maintained successor, read q/dq for all ARTICULATION_JOINTs in one
session and select the18 named joints. Current session writes cover all
objects of one type, with no subset selection, one attribute per session,
and whole-group commit. Do not overwrite unrelated articulation joint
values when generalizing beyond this exact inventory. Drives/targets
persist; write-only external forces are consumed each step.

Read session buffers are owned snapshots, not aliases of live engine state.
For CUDA consumption use the group's event on the consumer stream; for
writes pass producer stream/event at commit. Numeric buffers survive until
read release, not forever. Release promptly to reuse the256MiB-default
pool. Cached tensor binding descriptors skip stream negotiation, so the
benchmark explicitly waits for its Warp command-copy stream before native
write; that conservative wait is included in measured target cost.
[Device/event contract](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/docs/read_write/device.md).

DirectGPU is opt-in through `/physics/suppressReadback` at construction,
with GPU dynamics/broadphase already authored. It disables standard CPU
state readback; observations must use the tensor/direct API. Native
`PxDirectGPUAPI` batches articulations and accepts start/finish CUDA events,
but exposes no caller-owned simulation stream or supported whole-scene
graph-capture entrypoint. Passing no finish event makes direct data
operations wait. These APIs reduce transfers; they do not eliminate
the solver's host scheduling/fetch requirements.
[Exact native DirectGPU header](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/physx/include/PxDirectGPUAPI.h).

## What the executable measures and what remains

Modes: cpu, gpu-readback, gpu-direct; thread count configurable; cadence
batch/sync/async; observations none, qv, or qv-links-all. A moving120-target
cycle sweeps joint1 and aperture; fingers remain derived. Default observes
q/dq plus all27 rigid-body poses and rejects nonfinite output. The command
uses a stable buffer. The first256 traces and every tick's target/physics4/
read-state/whole-tick buckets are written alongside wall throughput,
package identities, scene hash, names and paths. Whole wall interval includes
trace/list handling and final wait. Warmup is separate; native minimal~1ns
warmup initializes DirectGPU before state writes.

CPU versus GPU, thread0/1/2/4, then batch versus sync are the first
comparisons. All use the same moving inputs and full state payload. A
`none` observation case is only a physics upper bound. Host readback is
deliberate for source-state persistence and external mirrors; a later
device-only observation case would be a different workload.

The probe's `target_achieved` and `dataset_admissible` remain false. It lacks
XR, Quest, IK, cameras, recording, durable flush and a contact qualification
assay. CPU physics can still initialize the CUDA driver through CUDA-enabled
Warp or OVStage; no guarantee of a driverless process is made. Native
contact reports are available, require authored contact reporting and
their default buffers expire at the next step; use owned copies for traces.
Stable contacts, grip/release, free fall/bounce, joint-sign/limits/FK/TCP,
reset and optical frame binding remain necessary comparisons.

Standalone physics gains do not automatically accelerate the existing Kit
XR/control loop. A physically separate source process would need the
existing NVIDIA input session, upstream IK and explicit small state
publication into the Kit XR presentation and OVRTX dataset renderer.
No custom OpenXR/CloudXR transport is proposed. If renderer pixels lag,
join them to their immutable depicted source state by identity, never the
latest physics state. Service capacity and bounded queue depth must each
support about50Hz with active XR/no client before Quest>30Hz is tested.

## Audit discipline and rollback

Capability/gate: experimental performance for future S2/D0/D1 work, no gate
state claim. Reused: NVIDIA USD population, native PhysX simulation/PD,
public tensor bindings, Warp arrays, stock Python benchmark timing.
Remaining adapter gap: exact asset/control mapping and measured source
publication/optical binding. Environment impact: isolated pinned package
set; no project framework is needed. Prototype is213 lines, below the300
line integration re-audit threshold.

Rollback is deterministic: stop the scratch process; run the unchanged
selected Kit composition without its optional environment. No monkeypatch,
driver/global setting or production bytes were changed. Never add the
optional simulator environment to production PYTHONPATH.

Checks: checkout/HEAD/WIP inspected, CodeGraph used before code location,
normative/reading map/implementation/documentation guidance read, relevant
owner and configs selected; official NVIDIA skill catalog checked with no
strong OVPhysX-specific catalog match. API/source files fetched into /tmp
with SHA256 ledger; AST parse and CLI --help passed; USD read-only audit
passed. Runtime tests/install were deliberately delegated to root for
serialized execution. No physical evidence. No tracked documentation
changes by this agent; trusted-base documentation/gate checks remain root's
final bundle responsibility.

Full primary/local locators, hashes, checks and search ledger:
`/tmp/live30-deep-ovphysx-sources.json`.
