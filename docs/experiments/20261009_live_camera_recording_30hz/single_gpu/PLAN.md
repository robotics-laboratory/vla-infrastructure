# Single-GPU live recording implementation

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted continuation base: `d1676c5c05f3bf6ae300f47533526085fdab4204`.

The user authorizes developing the proposed pipeline on the existing RTX4090,
without a second GPU. Keep current shared scene, XR input/processor boundary,
upstream DifferentialIKController, 14 source labels/18 native coordinates and
canonical NVIDIA HDF state/action recording. Experimental opt-in only; no
production selection, physical S2 qualification or D1 admission is implied.

## Upstream audit and remaining adapter

CAPABILITY: simultaneous source-bound actions and three live960x600 cameras.
PINNED UPSTREAM: ovphysx0.6.3/ovstage0.2.0.377349; OVRTX0.5.1.385782/
ovstage0.2.1.385922; Warp1.16.0; PyNvVideoCodec2.2.3; current Kit/Isaac/Lab.
UPSTREAM OWNS: physics, mimic constraints, transforms/Jacobians, DLS IK, XR,
native NVIDIA HDF schema/storage, RTX rendering and NVENC compression.
GAP: one authoritative immutable standalone snapshot shared by IK/recording/
camera workers; passive Kit XR view; exact current drive initialization;
bounded frame ownership, warmup before admission and explicit stop/drain.
ADAPTER: a private inherited socket to the concrete CPU physics worker, explicit
field/order/unit mappings and an opt-in shared recorder/IK state reader.
ENVIRONMENT: existing declared Kit interpreter, previously isolated optional
CPU worker environment and renderer package targets. No SDK changes or installs
into production. Process split follows independent physics/render ownership;
version conflict alone does not justify a new RPC framework.
NO FRAMEWORK: no simulator registry, new robotics hierarchy, IK implementation,
dataset format, episode serializer or XR protocol.

## Implementation and qualification scope

- Use current selected VR leader400/40/2/3 and passive follower0/0/1/3 drives,
  not the earlier generic screening gripper2000/100/10/3. Import initial q/dq,
  body state, limits and effective overrides from the shared scene.
- Preserve all27 dynamic bodies, including ValidationProbe. Preserve source
  geometry/units. Fixed-root adaptation stays in a derived rollback-safe overlay.
- The native parser recognizes NewtonMimicAPI, but default standalone population
  drops the unregistered schema. Use a verified equivalent PhysxMimic translation
  in the derived overlay; verify follower ±0.5leader residual at runtime.
- Correctly map backend body/DOF order, xyzw/wxyz and COM→link Jacobian origin.
  Native Kit simulation must not advance while rendering the passive view.
- Warm assets/render/encode before recording. Never count warmup as admitted
  frames; retain source IDs, epoch/hash, capacity/backpressure and tail receipts.
- Serialize GPU tests. Every attempt retains launcher/source/config identity,
  stdout, PASS/FAIL and bulk locators/digests. Freeze all previous receipts.
- Validate meaningful CPU lifecycle/order/error tests, then real integration,
  independent physical-state/camera-source parity and long single-GPU cadence.
- Strict target remains >30 action and each camera Hz with connected Quest.
  Around50 complete bundles/s without Quest is a screening target, not physical
  acceptance. Initial availability is no connected Quest client.

Bulk outputs: `/data/ebulochkin/vla-runtime/live30-single-gpu-20261009`.
Gate bindings remain empty until separately qualified and registered.

Implementation and measured results are maintained in [REPORT](REPORT.md).
