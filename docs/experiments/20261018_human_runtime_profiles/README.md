# Human launch of native live-camera runtime variants

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted preservation base: `897e6018bf92fd8ba2add6055cfedfce12c91b14`.
Gate bindings=[]; no selected-profile promotion, physical S2 qualification or D1 admission.

This bundle integrates the retained architecture research with the existing
human Quest control loop. It owns the new bounded implementation/validation
record; [operator instructions](../../project/RUN_VR_OPERATIONS.md) own usage.

## Preserved state and provenance

Before edits, the assigned checkout was clean. Checkpoint
`checkpoint/before-human-runtime-profiles-20261018-897e601` points to the trusted
base. A verified Git bundle, empty index/worktree patches and branch inventory
are retained at `/data/ebulochkin/vla-runtime/runtime-profiles-20261018/checkpoint`.
Its [receipt](checkpoint.json) identifies hashes and the exact master baseline.
No existing worktree was reset or cleaned.

The original master is `beaedfd1116577fd4d8026232cfb96cba0b030fa`.
Native callback capture5 originates in `835d0b3`; event preview6, full source
proof7 and identity/cache/binding8 were consolidated in `57a69b8`. Timing and
scope refinements are in `daf6d41`, `b43d261` and `897e601`.
[History/dependency audit](history_audit.json) records recent experiment branches,
exact retained launch options and per-assay source pins. Some recipes were
uncommitted intermediate source snapshots before consolidation; profile switches
recreate those architectures using maintained code, not their historical bytes
or guaranteed historical FPS. All previous FAIL runs and artifacts remain intact.
The final integration retains the synchronous main-Kit benchmark recipe and
standard Replicator product owner. Async scheduling/product creation was also
tested: unrecorded RUN succeeded, but source-proved recording did not receive a
complete triplet. Those prototype changes were removed. Several renderer-call
timeouts coincided with active shader-cache compilation; their exact cause is
unresolved, and the stack alone does not prove deadlock. Final renderer readback
is in `native-camera/setup.json`; current throughput must be measured with Quest.

## Upstream and reuse audit

CAPABILITY: human-runnable alternatives to snapshot-only recording, sharing
teleop, recording and diagnostics; no gate acceptance is asserted.
PINNED: installed Isaac6.1/Kit110.3, Replicator1.13.36, CUDA12.8 and the retained
PyNvVideoCodec2.2.3 target. Kit owns rendering; PhysX owns dynamics; existing
processors/DLS and NVIDIA Episode Recorder own control labels and canonical HDF.
Existing native callback/copy/encode/source-binding adapters are reused.
REMAINING GAP: select the runtime before Kit startup and connect persistent
camera/preview ownership to Start/Stop/reset and per-episode writers.
ADAPTER: explicit profile mapping, early dependency bootstrap, NativeRuntimeSession
and attach/detach methods on NativeKitMedia. No backend framework, replacement
controller, dataset format, XR protocol, new environment or RPC is introduced.
ENVIRONMENT: existing declared Isaac/core environments. CUPTI adapter compiles
from tracked source against installed headers into private launch state. SDKs
and environments are not patched or installed. Source/header/library hashes and
compiler command are retained in each native launch's dependency receipt.

## Running the variants

```sh
./run-vr --list-runtimes
./run-vr run --runtime master
./run-vr run --runtime native-live
./run-vr record --runtime native-live
./run-vr diag --runtime native-proof
./run-vr record --runtime native-event --dry-run
```

`selected` is the unchanged default selection. `master` dispatches to a clean,
pinned baseline checkout (created locally from existing objects when absent);
it does not substitute the research branch's modified common files. Master
listing/dry-run is read-only. Scene selection remains `--profile`, runtime
selection is `--runtime`. Native-sync/event/proof/live correspond to overview5–8.
Each mode shares the human S2 loop and upstream processors/DLS; no scripted
benchmark replaces run_s2. Diagnostic observers do not mutate commands.

Native variants have separate default state roots at
`/data/<linux-user>/vla-runtime/isaac-<stack>-<runtime>`; pinned master uses
`isaac-<stack>-master-<commit-prefix>`. This isolates Kit settings, caches,
CloudXR state and output bundles. Explicit `--state-root` overrides the default;
the selected runtime retains its existing state location.
Native plain `--smoke` is rejected because its controller source requires an XR
session; use `./run-vr run --runtime native-live --xr-smoke` for bounded RUN/DIAG
checks, and the ordinary human RECORD lifecycle for recording. An XR smoke run
does not establish physical Quest qualification.

Native profiles use CPU PhysX/DLS, three actual main-scene960×600 RenderProducts,
GPU copies and NVENC; event/proof/live use exclusive scoped CUPTI copy ACK.
Source proof is full for native-proof, identity/cache for native-live, absent
for historical sync/event recipes. Bindings identify actual prior observations,
not a hard-coded frame offset. These are explicit experimental selections.

RUN/DIAG keep cameras and previews alive with no episode HDF/video writers.
X toggles preview visibility; L3 switches the existing head-locked/wall layouts
using the same GPU frames and no additional cameras. Only active panels upload.
B backdrop and R3 recenter retain the existing teleop control semantics.
RECORD uses the existing X/Y/B Start/Stop/Save/Discard/outcome lifecycle, including
tracking-gap segmentation and repeated episodes. Native RECORD also accepts L3
layout changes in WAITING, recording and review. X/B remain lifecycle controls;
initial visibility uses `--hud-on-start`/`--no-hud-on-start`, and R3 does not
recenter in RECORD. The native recording controller tensor appends L3 at slot 26
(27 values total), preserving Y Stop at slot 25. Selected RECORD remains at 26
values; dataset action labels retain their canonical dimensions. Actual Quest
panel visibility and layout usability remain unqualified. Canonical HDF retains the
snapshot-backed observation/action source profile; actual live RGB, encoded
ordinals and source bindings are separate companions under each `live_rgb/`,
identified by `live_rgb_manifest.json`. `live_rgb=False` in the canonical state
profile is not a claim that these companions were rendered offline.
Pre-episode sources are explicitly skipped until binding is possible. Terminal
coverage is reported; no duplicated image or silent index shift fills a gap.
LeRobot export of the new source-bound native companions remains separate work.

Manual testing requires normal Kit rendering and a working X display with
`HEADLESS=0`. On this installed stack, `HEADLESS=1` makes `KitVisualizer.step`
skip `app.update`; native callback capture then fails because the three camera
frames are unavailable. Automated assays use `DISPLAY=:0 HEADLESS=0`. Retained
failed attempts remain part of validation; an X-display assay does not prove
actual Quest presentation or comfort.

## Validation and limits

Validation results and retained failure attempts are recorded in the
[validation receipt](validation.json). Raw runs live under
`/data/ebulochkin/vla-runtime/runtime-profiles-20261018`; each run has command,
configuration, source identity and logs. The
[human lifecycle assay](human_lifecycle_assay.py) injects controller samples only
in the assay, leaving the actual S2 loop/PhysX/DLS/cameras/recording unchanged.
It tests simulated Start/Stop/classification/reset without physical Quest inputs.

Known research limits remain: RTX temporal image quality, CPU preview-related
physics differences, long host-memory growth, version-coupled CUPTI ownership,
source lag and terminal coverage. No new performance, physics equivalence,
actual Quest usability, physical success or dataset admission is inferred from
unit tests, no-client tests or former branch results.

Size re-audit: the callback and CUPTI source are retained implementations copied
into maintained runtime locations; the main new work is lifecycle composition.
NativeKitMedia remains a concrete existing adapter, not a new simulator layer.
Maintaining independent controller or recording loops for each profile is forbidden.


The final runtime-source matrix passed all 12 cases (four profiles × RUN/DIAG/
RECORD). RUN/DIAG each exercised 16 eligible synthetic controller ticks, X/L3/B
and no episode writers. Each RECORD case saved two classified synthetic demos,
14 committed transitions each, three live streams and six L3 switches across
record/review/classification. Proof/live retained 11 source-bound RGB frames per
short episode; sync/event retained 15 images without proving their source ID.
Those different counts are explicit coverage, not a dense aligned dataset.
All 24 H264 streams decoded completely with expected dimensions/frame counts.
The ordinary `run-vr run --runtime native-live --xr-smoke` command also passed
with actual CloudXR/OpenXR device initialization and no connected Quest.

Final combined core runtime/recording/governance tests: 684 passed; 29
SDK-dependent tests skipped there. Running those same 29 tests inside the pinned
Kit environment passed with no skips. Ruff, docs preservation, spec references,
contract and selective manifest checks passed. Full commands,
logs, source/config bytes and retained failures are identified in the receipt.
These are functional checks, not a fresh 30/50 Hz qualification. Whole-process
assays included startup/reset/save/teardown; their seconds are not tick timings.
Two initial private-state cases took 75/107 seconds with shader-cache warmup
observed; subsequent short
RUN/DIAG assays took about nine seconds. Earlier bounded startup timeouts remain
FAIL; their stacks do not distinguish every compiler/transition failure.

Implementation size: the new profile mapping/session/bootstrap total 284 lines;
the maintained callback (532 lines) and CUPTI source (170 lines) reuse the
retained adapters. Existing media and S2 owners gained concrete attach/detach
and profile branches. There is one controller/physics loop and one canonical
recorder. No SDK or installed environment file was edited.


Integration failures and corrections are retained, including:

- Explicit SceneUI/XR extension activation was required for native camera helpers.
- A bare native `--smoke` cannot create the controller session; it now fails early
  with an `--xr-smoke` recommendation. Native RECORD uses the human lifecycle.
- Detached native RUN had no recorder snapshot to persist. It now retains state/
  XR validation in solve/apply and prepares persistent transactions only in RECORD.
- RECORD L3 collided with Y Stop's slot25; it now appends slot26. The first22
  motion values and selected RECORD's26-value shape remain intact.
- Closing an SDK panel drops its actual provider reference. Native preview now
  retains the real providers and in-flight source owners through app shutdown.
- Assay setup initially omitted the launcher's ground/environment and recording
  root; asset closure correctly rejected it. The assay now uses the same per-user
  environment and local pinned assets, without weakening closure checks.
- Fresh shader caches caused long initialization. Final source/checks and early
  timeout attempts are separate retained scopes. Async experiments did not pass
  source-proved recording and were removed from the runtime selection.
- One older SDK-only X-visibility fixture lacked the newer layout owner. Its
  fixture was corrected; all29 tests were then rerun successfully in real Kit.

No historical FAIL or qualification record was rewritten. Source/config bytes
for matrix03 are retained separately; the only later runtime-byte change removes
one redundant blank line at bootstrap EOF, with an identical AST. The combined core tests cover the final files; matrix/launcher checks
are linked by this AST comparison.
