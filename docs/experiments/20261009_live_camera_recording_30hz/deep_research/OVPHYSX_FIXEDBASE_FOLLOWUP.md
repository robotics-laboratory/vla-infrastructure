# OVPhysX fixed-base failure audit and derived adaptation

2026-10-09, exact OVPhysX0.6.3 release source
`da950a3537927784951853c66618036f332ca0ce`. No simulation, GPU work,
installation or SDK mutation by this agent. Root executed the failed CPU
probe; its frozen result and log remain authoritative for that attempt.

## Failure is meaningful; keep the guard

The first CPU probe loaded both expected articulations, each with9 DOFs and
12 body names, but `is_fixed_base` was false. This is **not a placeholder**:

1. `ovphysx_get_articulation_metadata()` calls the shared metatype's
   `getFixedBase()` (`ovphysxTensorBinding.cpp:4012`).
2. `ArticulationMetatype::getFixedBase()` returns its stored boolean.
3. `BaseSimulationView.cpp:1601` sets that boolean directly from the realized
   PhysX articulation's `getArticulationFlags().isSet(eFIX_BASE)`.

The getter is deprecated as part of the older tensor API, but it reports a
real native flag. Removing the assertion to obtain throughput would hide
a changed mechanism. [Exact native metadata realization](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/ovruntime/source/omni.physx/plugins/tensors/base/BaseSimulationView.cpp),
[Exact metadata C API](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/src/ovphysx/ovphysxTensorBinding.cpp).

The retained stage applies `PhysicsArticulationRootAPI` directly to each
rigid `.../Geometry/world/base_link`. Its existing fixed joint is
`.../Physics/world_to_base_link`, with body0 targeting the non-rigid robot
namespace Xform (`/World/LeftPiper` or RightPiper) and body1 the base link.
In this released standalone parser, an explicit root on a dynamic body
elects that body (`ArticulationGraph.cpp:325–340`) and produces `fixBase=false`
(`:229–233`). Native link construction confirms the body-root case as
floating (`usdLoad/Articulation.cpp:421–436`); a root on a world joint takes
the fixed branch (`:438–509`).
[Exact root election](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/ovruntime/source/omni.physics.parse/ArticulationGraph.cpp),
[Exact native construction](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/ovruntime/source/omni.physx/plugins/usdLoad/Articulation.cpp).

An external fixed constraint may constrain a floating articulation's root;
the flag alone does not prove it falls freely. It does prove the reduced
coordinate layout differs from a genuinely fixed articulation, which also
changes Jacobian/inverse dynamics conventions. No trajectory or base
reaction was observed in the failed attempt. Treat the mismatch as an
input/runtime semantics failure, not a speed result.

The12 links are the expected actual bodies: base, six arm links, flange,
gripper base, aperture carrier and two fingers. Namespace `Geometry/world`
and robot-root Xforms are not additional physical links. A13-body expectation
would introduce a dummy world link rather than fix the actual root flag.

## Minimal concrete adaptation, with preserved source

The reviewed candidate is a **separate root-authoring overlay**:

- `/tmp/live30-deep-ovphysx-fixedbase-v2.usda`
- SHA256 `548320594048c8f96b5a1b1de68eeb0a3803214bae9dc53db816e1bb399ed8df`
- `/tmp/live30-deep-ovphysx-fixedbase-v2.manifest.json`
- Authoring source `/tmp/live30-deep-ovphysx-fixedbase-overlay-v2.py` (108 lines).

For each robot it removes PhysicsArticulationRootAPI and PhysxArticulationAPI
from the rigid base link, prepends them to the **existing**
`world_to_base_link` fixed joint, copies the original articulation settings
(8 position /2 velocity iterations, self collision true) to that joint,
and makes body0 an explicit empty/world relationship. body1 remains the
same base link. There is no new body, joint, collision geometry, drive,
FK/IK or renderer implementation.

The empty relationship avoids the parser's distinction between a real
static body and an arbitrary namespace Xform. In its explicit world-root
branch one joint body must be absent; fixed root frames are ignored, so
the retained initial base pose determines the bolted location. This follows
the released fixed-base authoring example, which marks a world-connected
FixedJoint as the articulation root.
[Released fixed-base authoring contract](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/docs/simulation_setup/articulations.md).

Read-only USD checks verified all1475 initial world transforms remain
numerically identical, exactly two root APIs now occur on the intended
fixed joints, stage metrics are identical, and the original source still
hashes to `03453f4d22eedb40c77cee68aabab241d0c0bf58b824f9c72afb59bef27b812b`.
These are authoring checks; they do not verify native realization,
trajectory/contact parity or physical performance.

New guarded probe:
`/tmp/live30-deep-ovphysx-fixedbase-bench-v2.py` (244 lines), run as:

```bash
/data/ebulochkin/vla-runtime/live30-deep-20261009/optional-ovphysx/bin/python /tmp/live30-deep-ovphysx-fixedbase-bench-v2.py --stage /tmp/live30-deep-ovphysx-fixedbase-v2.usda --fixedbase-manifest /tmp/live30-deep-ovphysx-fixedbase-v2.manifest.json --out /data/ebulochkin/vla-runtime/live30-deep-20261009/ovphysx-cpu-fixedbase-v2 --mode cpu --threads 0 --steps 3000
```

It accepts only the reviewed overlay hash plus exact original source hash,
checks the manifest and metre/Z-up metadata, binds the new fixed-joint root
paths, retains the native fixed-base assertion, requires all force-drive
types=1, and checks fixed root world poses remain unchanged on every
observed control boundary. It still rejects changed names/counts, checks
drive property write/read round-trips and observes all27 rigid bodies.
Mode `observation=none` remains an upper-bound ablation, without the per-tick
root witness. The original probe/source and failed result were not rewritten.

Both the original input and derived overlay should be retained in any
run bundle, with the manifest and all dependencies. The overlay references
the original absolute path; relocating it requires reviewed path/closure
registration, not silently changing this checksum. A successful adapted
run would qualify only this derived fixture and the selected CPU/SDK
configuration. It would not transfer existing Kit/S2 qualification.

## Preserved negative attempt: first overlay had wrong stage units

The first scratch overlay, hash
`95b66891d28cd93e9db7e2e684db8034f9b43470421bdc813fae9ae6cbf22610`, preserved
numeric transforms but omitted root-layer stage metadata. USD stage metrics
do **not** inherit from its sublayer: original was1m/unit andZ-up, whereas
that overlay defaulted to0.01m/unit andY-up. That is a serious semantic
error even when all authored transform numbers compare equal. It was
identified before this agent ran simulation and parent was told to stop
using that candidate. The first overlay, author and manifest are retained
as rejected artifacts; **do not run them**.

V2 explicitly authors and checks metres, up axis, kilograms, time codes,
frame rate, time range and default prim from the source stage. This is why
both stage metadata and transforms are checked, and why V2 has a different
immutable input hash. These checks are also relevant to any independent
render-stage overlay/mirror: numeric pose equality alone is insufficient.

Raw `apiSchemas` metadata was checked as well: PhysxRigidBodyAPI,
PhysxArticulationAPI, PhysxContactReportAPI and PhysxSceneAPI are present
in the original snapshot. Read-only stock pxr without those plugins omits
them from `GetAppliedSchemas()`, but that does not mean the source lost
the API tokens. The standalone loader already registers its codeless
schemas before population. Do not diagnose schema loss from the filtered
Python list alone.

## Drive limits and deprecated APIs: precise interpretation

The older tensor API's cached native target path is real, not stubbed:
`CpuArticulationView::setDofPositionTargets()` loops through DOFs and calls
`PxArticulationJointReducedCoordinate::setDriveTarget()` with body-order
sign mapping (`CpuArticulationView.cpp:1881–1897`). Rotational values here
are native radians; prismatic values are metres for this retained stage.

Likewise the property setters update actual native drive structs:
`setDofStiffnesses()` changes drive stiffness, `setDofDampings()` changes
damping, `setDofMaxForces()` updates maxForce or an active envelope's
maxEffort, and `setDofMaxVelocities()` calls `setMaxJointVelocity()`.
They are the appropriate native force-PD property surface for the current
plain implicit actuator. The new probe additionally verifies force-drive
type1, rather than assuming the imported type.
[Native property implementation](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/ovruntime/source/omni.physx/plugins/tensors/base/BaseArticulationView.cpp),
[Native CPU target/force implementation](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/ovruntime/source/omni.physx/plugins/tensors/cpu/CpuArticulationView.cpp).

`ARTICULATION_DOF_ACTUATION_FORCE` is the applied external joint effort cache
(`applyCache(eFORCE)`), not a replacement for solver PD effort or dataset
action. Setting it to zero preserves the intended absence of external
actuation; the position drive supplies motion. The benchmark does not
observe or redefine the label using computed/applied torque.

The new per-joint session API converts angular units to USD degrees;
these old direct tensors do not. Metadata/topology names still have no
fully nondeprecated successor. A deprecation warning is a maintenance
limitation, not evidence that fixed-base/drive values can be ignored.

CPU-mode logs show GPU broadphase falls back to ePABP when no CUDA context
manager is available. Keep that exact effective mode in results; do not
describe this observed CPU run as MBP. CPU physics and GPU physics remain
separate reproducible configurations even on the same USD fixture.

## Checks and remaining qualification

Read-only source audit, USD root/relationship/raw-schema/metric inspection,
overlay reload and all1475 world-transform checks passed. Both V2 scripts
passed AST; benchmark CLI help passed. Original bytes preserved. No
benchmark simulation was executed by this agent. Root owns subsequent
native fixed flag/base drift/drive round-trip checks and measured traces.

Further acceptance requires full native q/dq/base/link/contact comparisons
against the current Kit configuration, grip/release and free fall/bounce,
then full XR+IK+three960×600 camera+recording workload. No throughput or
physical gate success is inferred from a parsed/adapted stage.

All relevant artifacts and exact source hashes are registered in the
scratch ledger `/tmp/live30-deep-ovphysx-fixedbase-sources.json`. Repository
documentation/evidence registration remains root's final bundle work.

## Root's V2 native result and V3 exact rigid-body inventory

Root subsequently executed V2 on CPU in the isolated pinned environment.
Its frozen result is
`/data/ebulochkin/vla-runtime/live30-deep-20261009/ovphysx-cpu-fixedbase/result.json`.
It reports the intended fixed-joint root paths, 2×9 expected DOFs, 12 links
per articulation, native `fixed_base=true`, all native drive types=1 and
successful gain/force/velocity property round trips. This resolves the
original flag failure for the derived fixture only. The retained manifest
continues to record its authoring-time `fixed_base_runtime_verified=false`;
the separate runtime result is the new witness, not a rewrite of the old
manifest.

That attempt next failed before the timed motion loop because the rigid
query used `/World/*`. The pinned matcher treats a bare leaf `*` as a
single hierarchy level, rather than recursive descent
(`BaseSimulationView.cpp:298–321`). The immediate children of `/World` are
namespace prims, so none are direct physical bodies. Explicit `**` performs
recursive descent (`:300–306`). This is a query-scope failure, not evidence
that articulated links are missing from the engine.

`getRigidBodyAtPath()` accepts articulation links, articulation-root aliases
(mapped to their root link), and rigid dynamic actors (`:1881–1934`). It
excludes rigid static actors. `processRigidBodyEntries()` deduplicates native
body pointers (`:897–918`), which matters when recursive matching returns
both a fixed-joint articulation root and its base link.
[Exact matcher and native body realization](https://github.com/NVIDIA-Omniverse/PhysX/blob/da950a3537927784951853c66618036f332ca0ce/ovphysx/ovruntime/source/omni.physx/plugins/tensors/base/BaseSimulationView.cpp).

The independent V3 probe is
`/tmp/live30-deep-ovphysx-fixedbase-bench-v3.py`. It uses an explicit
27-path `prim_paths` inventory derived by read-only USD traversal:
24 actual articulation links and the retained LeftCube, RightCube and
ValidationProbe dynamic actors. This avoids alias selection and requires
returned paths and order exactly match the inventory, as well as count27.
The inventory is also frozen in `/tmp/live30-deep-ovphysx-rigid-paths.json`.
V3 uses the same unchanged V2 overlay/manifest and preserves all earlier
fixed-base, drive, provenance, root-pose and finiteness guards. No guard was
relaxed to obtain a rate. V2 source and failed bytes remain preserved.

V3 AST parsing and CLI help passed. This agent performed no simulation.
Parent should execute V3 in a new output directory; command is the V2
command above with the script replaced by V3 and a fresh result path.
Any rate still covers only native stepping, commands and selected state
observations; it excludes XR, cameras, IK and recording, and provides no
contact/physical/canonical parity qualification.
