# Current V2/V3 recorder to offline RGB, bounded integration

Local date: 2026-09-25 (UTC run: 2026-09-24). Base:
`9800afa6092a97089be06db58a9b1dce2b49abf8`. Branch:
`experiment/vr-current-v2-v3-rgb-e2e`; worktree:
`.worktrees/vr-current-v2-v3-rgb-e2e`. **PASS for the tested current
recorder-generated V2/V3 single-episode source and offline RGB chain.** This is
an experiment, not [[gate:D1]] acceptance, dataset admission, or physical Quest
acceptance.

## Scope and reuse audit

| Item | Finding |
| --- | --- |
| Capability | Bind committed row N to its saved native snapshot, extracted projection, strict replay identity and production RGB geometry. |
| Pinned upstream | Isaac Sim 6.1.0.0, Kit 110.3.0+feature.371399.00c488ae.gl, NVIDIA Episode Recorder 0.1.6 recordables/replayer and Replicator RGB/instance segmentation. |
| Upstream owns | Native HDF state tracks, strict `EpisodeReplayer`, camera state application and diagnostic instance masks. |
| Project reuses | `start_live_recording`, `RecordingSession`, causal commit, source validator, `extract_projection`, `replay_from_snapshot`, `ReplayCameraMaterializer`, and the existing RGB geometry oracle. |
| Remaining gap addressed | The earlier component assay used an archived V1 HDF with synthetic state-track edits. This run starts from a finalized artifact produced by the current V2 recorder. |
| Adapter | One opt-in six-row injected input plan, one current-source mode in the existing assay, one pure static-relative check. No new recorder, replay implementation, renderer or camera cadence. |
| Environment | Declared core `uv` environment for CPU checks and pinned Isaac61 GPU environment for bounded native recording, extraction, replay and masks. No dependency change. |

The native assay was already over 300 lines at the base. The size re-audit kept
the new code in the existing diagnostic assay and injected recorder seam; it
uses the current APIs and does not introduce a second RGB framework. Production
`isaac_vr_recording.py`, `isaac_vr_replay.py`, `isaac_vr_lerobot_materialize.py`
and the four `app.update()` calls inside `ReplayCameraMaterializer.render()`
were not changed. The launcher/run-script edits only expose the opt-in
diagnostic input plan.

## Component qualification and current pipeline qualification

The [earlier component report](../20260925_offline_rgb_state_alignment/REPORT.md)
retains its archived V1 source, synthetic state-track copies, 48/48 primary
geometry checks, restart/reset coverage and negative controls. Its proof is
that the production renderer depicts the state it receives. Its HDF copies are
not source artifacts for this run.

This report uses the **unmodified after finalization** HDF written by the
current `./run-vr record --smoke --injected-actions --rgb-e2e-assay` path.
Before recorder startup, the opt-in input plan positions the two live cubes
through Isaac `RigidObject.write_root_pose_to_sim_index` and advances physics.
The recorder then captures actual Fabric state tracks. Six subsequent injected
native targets pass through current command/decision types, native apply and
physics advance, successor capture, causal commit, `RecordingSession`, NVIDIA
HDF append and terminal finalization. No HDF, row identity, camera pose or
state track was edited after finalization. This no-client plan uses
`SolvedControlDecision.from_native` and deterministic target mapping; it does
not qualify physical XR acquisition or the live Differential IK solve.

Final source:
`/data/ebulochkin/vla-runtime/evidence/20260925_current_v2_v3_rgb_e2e/state-h/recordings/source/session.hdf5`.
HDF SHA-256:
`1e646b7dc4fe5ce265c4c36fec5e9ff90d3a2eba2415d9547e600621a5a12b2a`.
Stage snapshot SHA-256:
`25d98934cd7a01af06c16a0ac834d5a21eb3668ee609e8a70c45ea6e54e2d989`.
The finalized manifest and a fresh read of the HDF agreed on its digest after
replay and assay. The source profile is `isaac_human_vr_offline_rgb_v2`, the
HDF track schema is `piper_x_committed_transition_v3`, and the contract row
revision is `isaac_vr_committed_transition_row_v2`. The one technical episode
has ID `episode_000000` and HDF name `episode_00000`.

| Committed row | Left transition | Right transition | Selected for geometry |
| ---: | --- | --- | --- |
| 0 | motion | motion | yes, first row |
| 1 | motion | motion | no |
| 2 | clutch_held | motion | yes, actual V3 clutch row |
| 3 | motion | motion | no |
| 4 | motion | motion | yes, after clutch |
| 5 | motion | motion | yes, last row |

The strict source validator read all six committed rows and the terminal
successor. For every selected row, the assay recomputed the committed native
snapshot digest from *saved HDF state tracks*, then joined exact episode,
frame, transition, observation and snapshot identities to the current
projection bundle and production replay report. Projection bundle identity:
`6a8d8bf0e2aa09875b8374a21c4dd9bb65065d3518a891a4f46fb913f37078f4`.
Production replay rendered all six rows in three roles, wrote 18 RGB files,
used strict USD state replay and reported zero physics callbacks and exit 0.

## Geometry result

The existing cube projection/oracle compared two cube witnesses in `scene`,
`left_wrist` and `right_wrist` for rows 0, 2, 4 and 5. **24/24 checks passed**;
19 had visible masks (scene 8, left wrist 5, right wrist 6). Maximum visible
bbox-center error was **3.315 px**; minimum visible IoU was **0.273**. Fixed
limits were 24 px and 0.20. Minimum matching cube-color fraction inside a
visible mask was **0.9638**. Partial/out-of-frame cases retain the earlier
oracle's visibility rules; every role still has multiple visible witnesses.

The independent static world reference is the left target plate position in
the [VR configuration](../../../configs/isaac61_vr_runtime.yaml), outside the
HDF cube/camera state pair.
For scene row 0, observed cube-to-plate mask-center displacement agreed with
the projected world-relative displacement within **9.145 px** (24 px limit).
This catches a shared erroneous global cube/camera transform that would leave
cube-to-camera projection unchanged while the static plate stays fixed.

The current integration adapter's required wrong-row control also failed as
intended: **42** visible comparisons of row N render against another recorded
row's expected native state failed the spatial oracle. One direct example is
row 0 left-wrist LeftCube render checked against row 2 native expectation:
67.336 px center error and IoU 0.1692. The per-check source profile, schema,
episode/frame/transition/observation/snapshot IDs, source snapshot digest,
projection identity, production render digest, role, expected/observed witness
positions, error, IoU and verdict are in [summary.json](summary.json).
Diagnostic replay physics callbacks: **0**. Final result: **current V2/V3
single-episode RGB E2E PASS**.

## Reproduce and retained attempts

Run in the pinned Isaac environment from this worktree with fresh output paths.
The commands used for the final source replace `h` with another unique run
suffix when repeated:

```sh
export OMNI_KIT_ACCEPT_EULA=Y ISAACLAB_CXR_ACCEPT_EULA=1
root=/data/ebulochkin/vla-runtime/evidence/20260925_current_v2_v3_rgb_e2e
./run-vr record --smoke --injected-actions --rgb-e2e-assay --max-control-steps 8 \
  --state-root "$root/state-h" --run-dir "$root/run-h" \
  --recording-dir "$root/state-h/recordings/source"
/data/vla-infrastructure/isaac61_production/env/bin/python \
  tools/isaac_vr_lerobot_materialize.py extract \
  --recording "$root/state-h/recordings/source/session.hdf5" \
  --output "$root/projection-h" \
  --portable-root "recording=$root/state-h/recordings/source" \
  --portable-root isaac61_production=/data/vla-infrastructure/isaac61_production \
  --portable-root project_assets=/data/vla-infrastructure/assets
./run-vr replay --recording "$root/state-h/recordings/source/session.hdf5" \
  --episode 0 --render-cameras "$root/production-rgb-h" \
  --state-root "$root/replay-state-h" --run-dir "$root/replay-run-h"
/data/vla-infrastructure/isaac61_production/env/bin/python \
  tools/isaac_vr_rgb_alignment_assay.py \
  --recording "$root/state-h/recordings/source/session.hdf5" \
  --current-projection "$root/projection-h" \
  --replay-report "$root/replay-run-h/result.json" --output "$root/assay-h"
```

Bulk HDF, PNGs, generated projection, replay report and raw run output remain
under that `/data` root; none is committed. The final machine result is also
copied into this small experiment bundle. Earlier attempts are retained there:
`setup_failures/` records sandbox GPU, `/tmp` ownership and disk-space setup
failures; `assay-e/failure.json` records a local import error fixed only in the
adapter. The first finalized source (`state-e`) had cube witnesses outside both
wrist views: `assay-f/current_summary.json` correctly returned FAIL despite
passing observed spatial comparisons and a 7.274 px plate check; it produced
no wrong-row failure. A second source (`state-g`) passed geometry with cubes
placed through the native API, but preceded the final `RecordingSession`
owner wiring. These are distinct immutable artifacts, not post-finalization
revisions of the final source.

## Limits and governance

The run contains one technical episode. It does **not** test a causal gap or
the first row of episode B; that requires a separate bounded session-boundary
source. It does not test Quest tracking, human manipulation, admission quality,
full robot mesh geometry, photometric determinism, all dataset frames, or
materialized LeRobotDataset admission. No gate state, selected runtime config,
render cadence or performance setting was promoted. This experiment adds no
physical-human evidence. The current V2/V3 result and the archived/synthetic
V1 component result retain separate scopes.
