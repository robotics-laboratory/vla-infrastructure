# Deep research: NVIDIA live capture, rendering and simulation

Owner: `vr.performance`; kind: experiment; status: current.
Continuation base: `d5566834d29ef8bb56e4fb62bb324e23e0869100`.
The original master preservation base remains `beaedfd1116577fd4d8026232cfb96cba0b030fa`.

The user accepts small bounded frame delays and requests wider information-field,
repository, forum and installed-code research with measured impact of promising
findings. Delayed pixels retain their original capture identity; delay alone is
not a failure. Empty packets, lost source identities and unbounded queues remain
failures. The physical target stays >30 action and three-camera bundles/s with
active XR and Quest; approximately50 complete bundles/s without Quest screens
candidates. Existing immutable receipts are preserved.

## Upstream audit before experimental composition

CAPABILITY: concurrent source-action recording and live three-camera capture.
UPSTREAM: installed Isaac6.1/Lab17.0.2/Kit110.3/PhysX/Fabric, native Replicator
NVENC, optional standalone OVRTX/ovstage, NVIDIA Warp, CUDA media SDKs and public
XR implementations. Exact optional package versions are recorded per run.
UPSTREAM OWNS: current scene, actuators, IK, causal state recorder, render
products, GPU encode, standard media containers and tensor interoperability.
GAP: measured full-scene ceilings, camera/simulation overlap, producer identity,
bounded resource ownership and installed versus current public API differences.
ADAPTER: standalone diagnostic drivers importing the existing shared builder
and recorder; in-process source-hash-guarded opt-in ablations, restored on exit.
ENVIRONMENT: declared Isaac interpreter; optional libraries only in an isolated
package target selected by process PYTHONPATH. Production packages remain intact.
NO FRAMEWORK: no new simulator registry, IK solver, dataset format or XR protocol.

## Work streams and experimental rules

- Survey rendering, Kit scheduling, tiled products, native output events,
  PhysX/Fabric/actuator internals, media/CUDA interoperability, XR scheduling,
  standalone NVIDIA runtimes, storage and existing public implementations.
- Record exact source URLs/versions, search coverage, negative findings and
  applicability. Forum advice is anecdotal until reproduced locally.
- GPU runs are serialized by the root agent. Every attempt, including failures,
  gets command/source identity, stdout and result receipt. Bulk data stays in
  `/data/ebulochkin/vla-runtime/live30-deep-20261009`.
- Compare matched full-scene variants and bounded stress; publish preprocessing,
  warmup, working-window and drain timings separately. No physical motion or
  Quest qualification is inferred from no-client results.
- Existing production selections and gate states are unchanged. External tweaks
  use reversible process settings, guarded instance patches or an isolated
  package target; no SDK mutation in place.
