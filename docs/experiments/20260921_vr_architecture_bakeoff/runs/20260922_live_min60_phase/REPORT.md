# LIVE-MIN60-NONTILED camera-phase result

Frozen failed experiment record. Owner: `vr.performance`. This record does not
change canonical runtime selection, qualify physical operation, or accept a gate.

## Scope and identity

- Candidate: `LIVE-MIN60-NONTILED`
- Tested repository HEAD: `f858ff3f293a6d6024690258af2c09df0590d15d`
- Branch/worktree: `wip/vr-recording` at
  `/home/ebulochkin/vla_infrastructure/.worktrees/vr-recording`
- Physics/control/render: 60 Hz / 30 Hz / one render per two physics steps
- Renderer/XR scale: RTX Minimal mode 2 / 0.4
- Cameras: existing independent `left_wrist`, `right_wrist`, and `scene` Camera
  products; live 640 x 480 uint8 RGB; panels and uploads off
- Owned copy: 2,764,800 bytes per accepted boundary
- Persistence: RecorderManager, HDF5, compression, and LeRobot off

The TiledCamera path was not selected. Its retained assay qualifies static/held
roles only; it has no dynamic wrist-transform and exact-boundary proof. Extending
it would require new architecture work, so the instructed non-tiled fallback was
used.

The exact executed source hashes, environment, command, base HEAD, and copied
source directory are recorded in [launch.json](launch.json). The source hash for
the final tested `live_min60.py` was
`d4b23e9d282a4f680c8042b9cfd2135067a3d2a145d4def624c655b2a0e93d26`.

## Result: camera alignment blocked

The candidate is **STALE**. The decisive native articulation witness in the fixed
scene camera selected lag 2 at all 35 consecutive changing accepted boundaries.
Every boundary had exactly one render. For the final three independently restored
reference states, the captured mask matched P-2 with IoU 0.992528, 0.995758, and
1.000000 and centroid errors 0.099, 0.014, and 0.000 pixels. Current-state P had
IoU 0.007286, 0, and 0 and centroid errors 64.380, 62.990, and 117.540 pixels.

The USD marker and native PhysX-cube witnesses were exercised, but their Minimal
renderer color/visibility decoders were not reliable enough across all three views
to assert alignment. Wrist-camera native geometry was also not continuously
visible. These are explicit qualification failures, not passes. The definitive
scene-articulation stale result is sufficient to reject the three-camera bundle:
one stale canonical camera makes the dataset invalid.

Raw boundary states and view measurements are in [phase.json](phase.json), the
bounded analysis is in [phase-analysis.json](phase-analysis.json), and the restored
articulation comparisons are in
[phase-articulation-references.json](phase-articulation-references.json). No PPM
captures were retained.

## Synchronization attempts

The experiment used only pinned mechanisms and did not add physics or render work:

1. Disable Kit/XR low-latency asynchronous rendering and Replicator asynchronous
   rendering before Kit startup.
2. After two completed 60 Hz physics steps, call the PhysX manager's supported
   `forward()` path to update articulation kinematics and Fabric.
3. Enable renderer synchronous capture after the app, scene, and render products
   exist.
4. Perform one Kit/RTX render, then one camera extraction per role and owned RGB
   copy. A follow-up removed all camera reads between the two physics steps and the
   render; phase was unchanged.

The measured explicit forward cost in the 70-sample diagnostic interval was
0.752 ms mean, 0.815 ms p95, and 0.855 ms p99. Renderer capture synchronization
was enabled once outside the measured boundary. None of these mechanisms repaired
the P-2 content lag. Extra physics steps: 0. Extra renders: 0.

## Stop conditions

Per the task's correctness-first rule, the required 300-control warmup plus
600-control short screen was not run. The 3 x 3000 long benchmark, 120-versus-60
dynamics comparison, and physical A0/LIVE-MIN60 procedure were also not run after
the hard camera-alignment failure. No performance classification is made.

A non-qualifying 70-sample post-warmup diagnostic interval is retained only to
show acquisition actually occurred. It measured 27.080 wall controls/s and one
accepted frame per role per control, RTF 0.911, and 36.927 ms mean total control
latency (p50 29.871, p90 34.658, p95 44.670, p99 164.344, max 416.104 ms). These
figures do not satisfy the requested short-screen sample counts and must not be
used to assign a LIVE performance label.

Diagnostic mean stage times were: control/input 6.747 ms, IK/apply 2.514 ms,
physics 7.634 ms, synchronization 0.752 ms, render/app 9.687 ms, camera extraction
4.690 ms, RGB freeze 0.884 ms, and other 4.019 ms. Owned RGB freeze was 0.884 ms
mean, 1.462 ms p95, and 1.500 ms p99. The diagnostic mean was 3.594 ms over the
33.333 ms budget.

Raw per-control timing is retained in [performance.jsonl](performance.jsonl) and
raw acquisition timing in [live_min60_samples.jsonl](live_min60_samples.jsonl).
[runtime-result.json](runtime-result.json) contains the runtime summary;
[gpu.csv](gpu.csv) is the unedited one-second GPU sample stream.

## Reproduction and rollback

From the assigned worktree, with no other process using the candidate's CloudXR
port:

```sh
python docs/experiments/20260921_vr_architecture_bakeoff/launch.py LIVE-MIN60-NONTILED --mode xr-smoke --ticks 100 --warmup 30 --output /tmp/live-min60-phase-repeat --state-root /tmp/live-min60-state --phase-qualification
```

Use a fresh output directory. Ctrl-C stops the launcher; if it leaves a child,
identify it from that run before stopping only that process. The selector is
opt-in and process-local, so ordinary `./run-vr` remains the rollback. No physical
variant is queued because this candidate did not survive camera qualification.

## Governance

Canonical runtime changed: **NO**. D0, S0, S1, S2, and D1 are unchanged. No gate
acceptance, physical success, dataset admission, or 4D work is claimed. This
failure bundle is indexed for navigation but is not registered as positive gate
evidence or added to the selective root manifest.
