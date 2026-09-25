# Current RECORD boundary and flush tail reduction

## Scope and provenance

This experiment starts from `ced416f2489fc1932cc649438c6b624dd8e478c7`
(`experiment/vr-current-record-performance`) in
`feat/vr-record-boundary-tail-reduction`. The prior frozen
[performance audit](../20260925_current_record_performance/REPORT.md) is the
baseline. Only the current injected RECORD path with XR enabled and no client
is measured. This does not establish Quest motion or physical S2 acceptance.
No gate state or resolved source profile is changed.

## Upstream ownership and remaining gap

| Capability | Pinned owner | Local change |
| --- | --- | --- |
| Native V2 HDF and row channels | Isaac Sim 6.1 `SessionStorage` / `Recordable` | Use upstream `buffer_frames=128` and unchanged 64-row flush calls; no custom HDF writer |
| Episode lifecycle | Upstream `on_episode_end/start`, `SessionStorage.end_episode/close/begin_episode` | Keep callbacks and mutable HDF close on the simulation thread |
| Causal V2/V3 recording | Existing `LiveRecording` and `RecordingSession` | Split seal from immutable file verification/hash/publication; no row or source conversion |
| Demo publication | Existing human lifecycle and saved-demo index | Require finalized state marker matching manifest HDF hash before indexing |

The Isaac environment pin, source profile, V3 row schema, four physics
substeps, render cadence, clutch semantics and human lifecycle remain as in
the base. The local code is a narrow owner for already closed artifacts. It
does not replace NVIDIA storage, Recordables, replay or materialization.

## Boundary decomposition

The old six-gap cohort reported these inclusive means in milliseconds:

| Old scope | Mean | What it includes |
| --- | ---: | --- |
| Technical end | 87.48 | Synchronous close, terminal artifact, verification, hash and publication |
| HDF close | 9.82 | Recordable end callbacks, storage end/flush and close |
| Terminal write / verify | 8.94 / 1.96 | Last committed successor bound to its row |
| HDF SHA-256 | 4.28 | Whole closed file |
| Manifest / result and state publication | 53.96 / 5.26 | Atomic writes with file and directory `fsync` |
| Next episode open | 72.35 | Private directory, static links/copies, in-progress state, HDF open/begin, callbacks and manifest |
| Gap to first recovered commit | 213.35 | End, unrecorded physics, open and first admitted transition |

The old audit did not instrument the components inside the 72.35 ms open or
the individual callbacks within HDF close. Those old subcomponents cannot be
reconstructed exactly from retained logs. This change adds nested timings
for the same operations; the final D run below supplies their current costs.

For a true gap the rejected observation is discarded; the already committed
row's terminal successor is written; Recordable end callbacks, HDF end/flush
and close remain synchronous. The sealed HDF can no longer accept rows. Its
descriptor contains only copied row identity/QA and paths to closed files.
The next episode owns a distinct HDF, episode ID and dense frame index.

The descriptor initially remains `queued_for_finalization`. The owner starts
the filesystem worker only after the next episode has committed its first
admissible transition, avoiding competition between manifest `fsync` and HDF
open. A single worker verifies the terminal snapshot, hashes the closed HDF,
publishes manifest/result, and writes `recording_state.json` last. Marker
states are `in_progress`, `queued_for_finalization`, `finalizing`, then
`finalized` or `failed`. A process death before the last marker leaves a
non-finalized state. Saved-demo publication requires both manifest and state
marker to say finalized with the same HDF hash. The existing replay artifact
loader also requires a finalized state marker and matching frame/outcome
identity, so a crash after manifest rename but before the final marker is
still rejected by replay.

At most two worker artifacts plus one sealed descriptor can be pending.
The owner records depth and HDF bytes, waits for the oldest result at
capacity, and raises a retained worker exception on the next control step.
Submission failure marks that segment failed. Shutdown submits any staged
descriptor, waits for every worker result, and reports failure. No HDF or
Recordable callback runs in the worker; the worker has no mutable simulation
handle. `SessionStorage.flush()` is an HDF/page-cache flush, not an `fsync`
durability claim. No periodic `fsync` was added.

## Flush investigation

Pinned upstream `storage.py` defines `DEFAULT_BUFFER_FRAMES=1024`, uses it
both for each channel's in-memory array and HDF first-dimension chunk, and
flushes buffered groups on `SessionStorage.flush()`. Current RECORD called
that method every 64 committed rows. The earlier H128 experiment changed
the flush interval; it did not change HDF chunks.

A local probe reused the exact channel shapes/dtypes of the baseline B1 HDF,
512 rows, 64-row explicit flushes, and three trials per buffer size. The
32/64/128/1024-row upstream buffer and HDF chunk settings were compared.
At 1024, flush calls ranged roughly 5–10 ms; at 128, roughly 4.4–6.4 ms;
at 64, the 64th append carried roughly 4.3 ms while explicit flush was
roughly 0.3 ms; at 32, writes occurred at both 32 and 64. This probe is
CPU/HDF only. Its 64-row result moved blocking work into append, so it was
checked against full wall intervals rather than accepted from `hdf_flush_ms`.

The full XR ON/no-client B1 comparisons below use the same 3101 controls,
100 warmup controls, scene, native target sweep and 64-row flush interval.
The 64 and first 128 runs were selection probes; the next 128 run preceded
the final failure-path fix. The third 128 run is final-code validation.
A flush-associated miss is a start-to-start deadline
miss immediately after a control that called `SessionStorage.flush()`.

| B1 cohort | buffer/chunk | mean | p95 | p99 | p99.9 | max | misses / 3000 | flush-associated misses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Old B1 | 1024 | 26.54 | 29.27 | 33.38 | 39.12 | 43.97 | 32 | 29 |
| Old B1 repeat | 1024 | 26.58 | 29.38 | 33.29 | 38.39 | 43.95 | 28 | 20 |
| Selection probe | 64 | 26.67 | 29.62 | 34.07 | 39.92 | 65.37 | 35 | 17 |
| Selection probe | 128 | 26.62 | 29.39 | 32.36 | 38.99 | 44.82 | 20 | 10 |
| Pre-fix repeat | 128 | 26.55 | 29.12 | 32.34 | 41.22 | 47.51 | 18 | 15 |
| Final-code B1 | 128 | 26.68 | 29.45 | 32.43 | 39.58 | 85.15 | 22 | 15 |

All durations are milliseconds. The final B1 p99 and deadline miss count
improved with a 0.14 ms higher mean, but p99.9 and maximum were worse than
the two old runs. The 85.15 ms maximum was one `sim_step` outlier (78.20 ms),
without an HDF flush. This is a mixed upper-tail result; the data do not show
elimination of all rare stalls. The selected buffer/chunk is 128; the flush interval stays
64. At 128, the HDF readback has exactly 3101 V3 rows and every V3 dataset
uses a 128-row chunk. The full `SessionReader` readback and SHA-256 match the
manifest and final state marker.

## Matched runs and correctness

The final numeric comparison, source/run identities, output hashes and raw
artifact locators are in [results.json](results.json). Each B1 cohort uses
3000 measured start-to-start intervals after 100 warmup controls. D uses six
real `tracking_invalid` gaps and seven separate technical HDF episodes.
The small clutch run checks the absence of technical boundaries; it is not
a steady performance comparison.

| D boundary metric | Old D | Final D |
| --- | ---: | ---: |
| Synchronous technical end mean / max, ms | 87.48 / 93.57 | 20.45 / 23.49 |
| Next episode open mean / max, ms | 72.35 / 74.70 | 72.42 / 76.17 |
| Gap to first recovered commit mean / max, ms | 213.35 / 222.42 | 145.32 / 152.48 |

The final D nested end consists mainly of `hdf_close` 8.50 ms and terminal
successor write 8.40 ms. Within HDF close, Recordable end callbacks average
0.003 ms, HDF end (including buffered flush) 8.07 ms, and file close 0.38 ms.
The extra ~3.38 ms between `seal_ms` (17.07) and the inclusive technical end
(20.45) includes publication of the non-finalized queued marker. Rejected
observation discard averages 0.007 ms.

The final D open's measured means are: static links/copies 0.32 ms,
in-progress state 2.64 ms, HDF session open 2.48 ms, HDF begin 7.44 ms,
Recordable start callbacks 0.004 ms, and initial manifest publication
53.33 ms. The inclusive open is 72.42 ms; its remaining time covers private
directory validation/creation, manifest copy and Python setup. This is the
same per-segment HDF contract as the old run; the old 72.35 ms open was not
nested, so an exact *historical* sub-scope decomposition is unavailable.
The first observation capture stage in each recovered segment averages
1.38 ms across six controls.

| Gap operation | Final D mean ms | Context after change |
| --- | ---: | --- |
| Discard rejected observation | 0.007 | Simulation thread |
| Terminal successor write | 8.40 | Synchronous seal |
| Recordable end callbacks | 0.003 | Synchronous seal |
| HDF end, including buffered flush | 8.07 | Synchronous seal |
| HDF file close | 0.38 | Synchronous seal |
| Whole-HDF SHA-256 | 3.71 | Filesystem worker |
| Manifest / result and final marker | 82.01 / 11.19 | Filesystem worker |
| Static link/copy for next segment | 0.32 | Next open |
| Next HDF open / begin | 2.48 / 7.44 | Next open |
| Recordable start callbacks | 0.004 | Next open |
| First recovered observation capture | 1.38 | First admitted control |

The initial manifest write (53.33 ms) and in-progress state write
(2.64 ms) are also synchronous parts of next open. Each row above is a
nested scope; rows should not be summed to reconstruct the inclusive gap.

The seven finalized files each contain exactly 172 dense V3 rows with
128-row chunks, a verified terminal successor and V2 source identity. Their
control ticks are 1–172, 174–345, 347–518, 520–691, 693–864, 866–1037,
and 1039–1210: precisely six rejected gap ticks, no duplicate or missing
committed tick. All seven passed strict `SessionReader` readback and HDF
SHA-256/manifest/final-state agreement. The queue peaked at one artifact
(2,353,552 HDF bytes) and returned to zero before shutdown; it did not grow
across six gaps. Mean seal-to-worker-start wait was 110.09 ms, and mean
finalization work 113.49 ms. Worker work includes terminal verification
5.89 ms, whole-HDF hash 3.71 ms, manifest publication 82.01 ms and
result/final marker publication 11.19 ms. These nested figures are not added
to the inclusive work timer.

The improvement to recovery does not remove all D tails. The final D wall
interval p95/p99/p99.9/max was 30.08/48.51/144.44/145.08 ms, compared
with old D's 29.39/37.28/211.75/217.39 ms. Deadline misses rose from
18/1103 (1.63%) to 33/1103 (2.99%) because asynchronous filesystem
publication still competes with other controls. The 30 Hz steady B1 result
above has no technical gaps and is unaffected by finalizer work. The
per-segment initial manifest `fsync` remains the dominant open cost; future
multi-episode HDF or manifest contract work needs a separate design, not a
replay change in this branch.

The 120-control clutch regression has one HDF and zero discarded rows or
technical boundaries. Exact V3 readback contains 114 motion, one
`clutch_engaged`, four `clutch_held`, and one `clutch_release_rebased`
left-arm rows. Its artifact is finalized with a 128-row chunk. This is a
small semantic smoke, not a measured Quest cohort.

## Checks and limitations

The targeted CPU tests cover seal versus later finalization, worker failure,
bounded queue, shutdown drain, causal isolation and saved-demo marker checks.
The final HDF chunk layout and exact `SessionReader` readback are checked on
the live cohorts. No physical Quest/client measurement, offline RGB
materialization, F16 encoding or D1 acceptance is claimed.

The source and tests pass `compileall`, Ruff, 87 focused CPU tests, 108
documentation/contract governance tests, documentation lint with trusted base
`ced416f2489fc1932cc649438c6b624dd8e478c7`, spec-reference lint,
resolved-contract validation, selective MANIFEST verification and
`git diff --check`. The declared checkout `.venv` lacked pytest and PyYAML;
`uv sync --frozen` could not fetch `pyzmq` under network restrictions. The
CPU checks ran in the pre-existing `core-migration-tests` environment, so
they do not repair or qualify the declared core environment. A broader
`tests/test_run_vr.py` invocation stops in an existing test mock that omits
`RECORD_STOP_BUTTON_INDEX`; the focused affected tests pass.

`docs/INDEX.yaml` registers this frozen experiment report and compact
results file. The root MANIFEST was regenerated only for its already
selected source, tests, operator guide and INDEX members. There is no new
contract evidence/artifact registration or gate binding: these are
no-client performance and correctness observations, not physical S2 or D1
gate proof. Raw logs, run manifests, HDFs and terminal artifacts remain
under the retained `/data/ebulochkin/p26/` locators in `results.json`.
