# Offline RGB state alignment, bounded native assay

Local run date: 2026-09-25 (UTC logs: 2026-09-24). Base:
`e11887c7e16a893ea93e2e78db0bfb86a67cc0d4`. Branch:
`experiment/vr-offline-rgb-state-alignment`. **PASS for the tested production
RGB producer and bounded synthetic native snapshots.** This is an experiment,
not [[gate:D1]] acceptance or a dataset admission decision.

## Scope and upstream audit

| Item | Finding |
| --- | --- |
| Capability | Spatial agreement of each saved offline RGB with its requested native snapshot, across scene and two wrist cameras. |
| Pinned upstream | Isaac Sim 6.1.0.0, Kit 110.3.0+feature.371399.00c488ae.gl; NVIDIA Episode Recorder 0.1.6 `EpisodeReplayer`/`CameraRecordable`/`RigidBodyRecordable`; Replicator `rgb` and public `instance_id_segmentation` annotators. |
| Upstream owns | Strict state application through USD world-pose batches ordered by ancestry; camera pose/intrinsics replay; render products and instance-ID masks. `pose_backend="usd"` authors the replay sublayer. No physics step is required. |
| Project owns | Verified stage/provenance, one replay pump after `apply_frame`, `ReplayCameraMaterializer` with three persistent 640×480 products, three startup warmup `app.update()` calls and four `app.update()` calls inside every `render()`. PNG and report binding remain unchanged. |
| Remaining gap | The pre-existing RGB hash/identity join did not test whether geometry depicted snapshot N. The assay projects recorded cube corners independently, compares renderer instance masks and checks cube color in the saved RGB. |
| Processor/config/adapter | Diagnostic-only test script and pure projection oracle. No training processor, config promotion, renderer synchronization fix, or framework. The selected renderer is not optimized. |
| Environment impact | Pinned Isaac environment for one bounded GPU run; core environment for CPU checks. No dependency or execution-profile change. |

The native assay module exceeds 300 lines. The size re-audit kept only fixture
state edits, calls to the existing replay/materializer APIs, diagnostic mask
collection, and result serialization there. Geometry math and verdicts live in
the small pure oracle; no duplicate replay or camera producer was introduced.

The available finalized source recording is V1, with the same native object and
camera state tracks consumed by the current V2 producer. Its SHA-256 is
`b5f1b4b29da9dc833ff255364cebb795aaf0a10c2cd51ff6afa60931eb70e06f`.
The stage snapshot SHA-256 is
`5b4f8313665a1c33b27576d7e3ce1e65f2c01cfbb0bbf76091573579cf06d547`;
visual provenance SHA-256 is
`374b30a2e1ee131f9f3656463c12220bfb57dac4e0c778230a5a1d7597082b65`;
renderer configuration SHA-256 is
`eb02a3964d51912e2dd2df60d75dbe1e2b301231f3db5880e2a54bb42bbe1b85`.
The tested assay source SHA-256 is
`ccad69406ed6519ef42434a03ecd314d2ef990e2600875e5660c82e19da6aa24`;
the pure oracle source SHA-256 is
`f4833a8498019818d7a1c39502fea1aa32cc27c3f6c2611d681fc62ee1869a6d`.
The assay copies this HDF and edits only state-track rows. The archived V2 D0
recordable type is mapped to the current V3 provenance-only no-op type in the
**synthetic copy**, because the current checkout registers V3. These synthetic
files deliberately fail normal recording integrity and are never materialization
inputs. Source recording and production replay code are unmodified. This
qualifies the shared RGB producer, not end-to-end V2 row validation.

## Oracle and controlled states

Expected geometry is computed from the synthetic HDF's native
`state/object_0`/`state/object_1` world positions and wxyz orientations (both
0.04 m task cubes), plus each camera's recorded world pose, focal length and
apertures. Projection uses USD camera local `-Z` forward and `+Y` up, clips to
the 640×480 image bounds, and marks out-of-frame or partial views. No expected
2D point is read from RGB or from the diagnostic mask. The HDF also contains
robot link world transforms, but this bounded oracle targets the two dynamic
cube meshes and all three camera poses.

Observed geometry comes from public `instance_id_segmentation` on the **same
render products** used by unchanged production `ReplayCameraMaterializer.render()`.
The annotator is attached only by the assay and is absent from the dataset.
`idToLabels` maps mask IDs to the cube prim paths. A color dominance check on
the saved PNG requires at least 30% matching blue/orange pixels within each
visible cube mask, so a current diagnostic mask cannot silently excuse stale
RGB. SHA-256 is retained for file identity only.

| State | Cube A position m | Cube B position m | Additional treatment |
| --- | --- | --- | --- |
| S0 / first | (0.82, 0.13, 0.86) | (0.87, -0.13, 0.87) | First frame after stage open. |
| S1 | (0.94, -0.04, 0.90) | (0.83, 0.16, 0.88) | Large adjacent translation. |
| S2 | (0.83, -0.11, 0.89) | (0.95, 0.07, 0.87) | Cube A rotated 45° about world Z. |
| S3 | (0.72, 0.17, 0.855) | (0.90, -0.10, 0.87) | Cube A on target plate; expected partial wrist view. |
| S4 | (0.91, 0.13, 0.88) | (0.82, -0.14, 0.88) | Both cubes displaced. |
| S5 | (0.86, -0.06, 0.90) | (0.94, 0.15, 0.88) | Left/right wrist cameras shift ±0.09 m in Y; scene shifts +0.08 m in X. |
| S6 / terminal | (0.95, -0.12, 0.89) | (0.85, 0.14, 0.88) | Last primary snapshot. |
| Reset first | (0.80, -0.16, 0.88) | (0.95, 0.12, 0.89) | New HDF replay session and distinct episode/session identity after S6. |

All states are intentionally nonperiodic; they are qualification inputs, not a
manipulation demonstration. Several cubes intentionally hover above the table
to make their projected geometry visible. They cannot fall during this assay:
the timeline is stopped, no physics step is invoked, and the callback count is
zero. S3 places cube A at the target plate height. Every state is checked in
`scene`, `left_wrist` and `right_wrist`. Two projected witnesses are fully outside the image, and five
are partial. Missing evidence is allowed for genuinely out-of-frame/partial
views. For a visible witness, pass requires projected vs observed bbox center
error ≤ **24 px** and IoU ≥ **0.20**; an observed mask requires ≥ **12 pixels**.
These thresholds were fixed before the valid native run and were not widened
after examining results. They allow mesh/raster boundaries and photometric
variation while rejecting the deliberately large one-state displacements.

## Results

| Boundary / run | Spatial verdict | Detail |
| --- | --- | --- |
| S0 first | PASS, 6/6 object-role checks | Max center error 0.890 px. |
| Adjacent S0–S6 | PASS, 42/42 checks | Nonperiodic A/B translations and S2 rotation; all roles. |
| S6 terminal | PASS, 6/6 | Max center error 0.479 px. |
| New episode first | PASS, 6/6 | Distinct replay session after S6; max center error 4.468 px. |
| Full process reopen | PASS, 12/12 | Reopened stage and replayed S0/S6. |
| Physics | PASS | `physics_callbacks=0` in both processes. |

Across the primary run: **48/48 checks pass**, 45 visible masks compared;
maximum center error **7.647 px**, minimum IoU **0.6043**, minimum RGB color
fraction within a visible mask **0.9492**. Restart: maximum center error
**0.890 px**, minimum IoU **0.9352**. The machine-readable per-role/per-object
expected and observed boxes, PNG hashes, visibility decisions and verdicts are
in [summary.json](summary.json) and [restart_summary.json](restart_summary.json).

Deliberate negative controls all failed as required: frame N compared to the
previous expected snapshot, a scene expected projection compared with a left
wrist observed mask, and cube A's expected transform shifted by +0.35 m in Y.
The CPU control also rejects frozen geometry when a native witness moves.
Identical RGB hashes alone are now a materializer QA flag; static correct
frames pass the join. This diagnostic change does not admit a dataset.

The [preliminary invalid run](preliminary_invalid_summary.json) is retained:
18/48 checks failed because several assay cubes were placed below the table top
(`z=0.825 m`) and edge boxes were compared before clipping. This was an assay
input/projection error, not evidence of stale production pixels. Positions
were raised above the table and bbox clipping corrected; spatial tolerances
and `ReplayCameraMaterializer.render()` remained unchanged.

## Reproduce and limits

Run from this branch in the pinned Isaac environment, with the pinned SDK and
private runtime assets available. Use a fresh output path for the first command:

```sh
OMNI_KIT_ACCEPT_EULA=Y /data/vla-infrastructure/isaac61_production/env/bin/python \
  tools/isaac_vr_rgb_alignment_assay.py \
  --recording /data/ebulochkin/vla-runtime/isaac-isaac61/recordings/recorder-pair-current-20260923-v2/session.hdf5 \
  --output /tmp/new-offline-rgb-alignment
OMNI_KIT_ACCEPT_EULA=Y /data/vla-infrastructure/isaac61_production/env/bin/python \
  tools/isaac_vr_rgb_alignment_assay.py \
  --recording /data/ebulochkin/vla-runtime/isaac-isaac61/recordings/recorder-pair-current-20260923-v2/session.hdf5 \
  --output /tmp/new-offline-rgb-alignment --restart
```

The complete synthetic HDFs, PNGs and native logs for this run are retained at
`/data/ebulochkin/vla-runtime/isaac-isaac61/evidence/20260925_offline_rgb_state_alignment/`;
the original summary's `/tmp/vr-offline-rgb-alignment-20260925e/` prefix maps
to its `passing_run/` mirror. The preliminary run is mirrored under
`preliminary_invalid_run/`. Recorded stage and renderer identity were verified
before replay. Raw colors and PNG digests may differ across restarts without
affecting the spatial verdict.

This PASS means only that the unchanged production offline RGB producer
spatially depicts the requested snapshot in this bounded, synthetic-state assay.
It does not qualify pixel determinism, full robot polygon geometry, physical
Quest use, a genuine V2 end-to-end recording, dataset admission, LeRobot
capacity, or render speed. No gate state or camera cadence was promoted.
