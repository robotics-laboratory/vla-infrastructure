# HDF → OVRTX dynamic mirror probe

Research glue only. `/tmp/live30-ovrtx-live-probe.py` uses existing guarded repository `deep_research/ovrtx_snapshot.py`; `/tmp/live30_optical_witness.py` is reusable by both standalone OVRTX and a Kit stage. No GPU run was performed by its author. Syntax checked with ast.parse.

Preparation and rendering MUST be separate processes: prepare imports pxr; render imports OVRTX. Example with explicit absolute paths:

```sh
/data/vla-infrastructure/isaac61_production/env/bin/python /tmp/live30-ovrtx-live-probe.py --prepare-only --episode /data/ebulochkin/vla-runtime/live30-deep-20261009/full-cpu-poll-contention/episode --output /tmp/live30-mirror-prepared --witness
PYTHONPATH=/data/ebulochkin/vla-runtime/live30-deep-20261009/optional-ovrtx /data/vla-infrastructure/isaac61_production/env/bin/python /tmp/live30-ovrtx-live-probe.py --prepared /tmp/live30-mirror-prepared --output /tmp/live30-mirror-rendered --frames 420 --warmup 30
```

Use new output directories each time. A second preparation without `--witness` gives full recorded-scene timing without diagnostic geometry; this cannot independently prove source phase. Source HDF/stage hashes must match manifest; prepared bytes and helper hashes are rechecked before GPU initialization.

Observed source structure:420 rows;26 articulation/root poses,2 cube poses,3camera poses. Quaternions wxyz; worldpositionsmeters; all authored world scales checked unit with pxr CPU. Camera intrinsics fixed across recordedrows. All UsdPhysics.RigidBodyAPI paths compared against manifest pose paths. Sole uncovered `/World/RobosynDemo/ValidationProbe` is explicitly deactivated in the stronger overlay and logged; its config sets opacity0, but this does not justify claiming its dynamicstate was captured.

Helper source-id snapshots are immutable bytes. Worker owns ovstage exclusively: full worldmatrix writes + resetXformStack, publication, synchronous rendercomplete, CPUcopy before next snapshot. Ordinal is a minimum publication gate, NOT a historical snapshot selector. Source sample identity references both HDF row and recorder snapshot_id/hash. Per-frame renderer capturetimes are preserved. No current-physics/previous-image relabeling.

Witness uses three camera-relative boards, each16 geometric cells:12 row-ID bits,2 rolebits,2anchors. Cells move to one of two rows to encode0/1; RGB decoder compares each row's sampled luminance. No pixel postprocessing inserts IDs. Boards change scene/fidelity and are probe-only. Threshold failure or source/role mismatch is logged, not silently repaired; first warmup, postwarmup, final and up to three mismatch rows saved as.npy. `optical_phase_all_pass` means all3boards decode expected row for allcaptures. It does NOT prove complete dynamicbody coverage or render equivalence, nor liveXR throughput. It rejects source phase lag for this direct synchronous smoke; decodedrow is retained to diagnose any lag.

If board decode is not confident, inspect saved arrays before touching labels. Camera aperture fit or render output flips may require an explicit calibrated decoder convention. Such a change must be documented; never infer row simply from requestedordinal.

Timing includes snapshot creation, application+publication, rendering,3×CPUreadback/copy, opticaldecode. Excludes initial preparation/load, warmup and artifact saves. This is worker service cost, not end-to-end livecapture/action Hz. No encoder, producerIPC, queue or Quest client is present. All receipts set dataset_admissible=False and live_xr_qualified=False.

The reusable witness helper exports `usd()`, `paths(role)`, `matrices(camera_world,intrinsics,row,role)` and `decode(image)`; intrinsics is(focalLength,horizontalAperture,verticalAperture). Matrices use USD row-vector convention (translationlastrow), unit meters. `usd()` authors Scope+materials+Cube definitions with explicit newlines, avoiding the one-line USD parser issue from initial staticprobe.
