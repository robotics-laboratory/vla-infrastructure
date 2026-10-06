# Native ZED cameras with state-only FFFT recording

Frozen bounded evidence for development source over `86bcd6f0b13425a5beacfed2f009723db0ac0b83`
on `codex/vr-recording-ui`. Exact tested runtime/config/test identities, dataset
semantic inputs and diagnostic wrappers are in [source inputs](source_inputs.json).
The later contract registry additions do not change those tested dataset inputs.

Capability / gates: D0 native image schema and S1/S2/D1 camera composition. D0's
state/action order, processors and causal transaction semantics remain unchanged;
its three image shapes become 600×960×3 with the new fingerprint recorded in
[validation](validation.json). Frozen historical 640×480 proof retains its scope.
Legacy recordings retain their source geometry/fingerprint during replay and
conversion. This bundle supplements offline D0 schema proof and bounded native VR
checks; it does not admit a D1 dataset or accept physical S2.

Pinned upstream: Isaac Lab 17.0.2 / materialization `0c2e2c64`, Sim 6.1 / Kit 110.3,
Stereolabs `zed-isaac-sim` `0164268ca123fa4549fc9d2062c1fd55cf7996dc`.
Upstream owns USD optics, Camera/CameraCfg, Recordables, RTX products and XR feeds.
The project reuses composition from `358e7f341f2545726773377ab4010a330fbae19e`.
The remaining adapter gap is preserving the existing optical mount poses and
selecting CameraCfg-only composition in RECORD. One 174-line helper serves all
modes; no replacement recorder, camera subclass, renderer, RPC or dependency is
introduced. The shared vendor checkout contains an unrelated helper patch and ABI
accommodation; selected USD/utils/package bytes and the invoked make_camera_cfg
AST are checked against the pin, with effective file hashes retained. No SDK
files were changed by this task. Existing large runtime files were re-audited;
new camera mounting logic remains in this narrow helper.

The native launcher observer forwards the original SimulationContext.step calls,
checks their render flags and the completed render generation, then inventories
canonical-camera RenderProducts. It does not change actions, physics, capture,
control inputs or the scheduler. Its exact temporary scripts are retained as
source text in source_inputs.json. [Scheduling receipts](scheduling.json) cover
startup, control and lifecycle resets: 28/7 reset, 92/23 remaining startup, 4/1
control. Preview has three dataset products; RECORD has zero at every checked
boundary, including waiting, recording and repeated review/reset cycles.

[Native results](native_results.json) retain the complete selected machine outputs,
including the first incomplete 36-control preview attempt and the passing 60-control
scenario. All 12 captured preview uploads match the source RGBA buffers. Three
ZED X One GS cameras use the vendor SVGA optics at 960×600, massless/non-colliding
housing and the selected optical poses. The six-row recorder-generated V2/V3
source passes extraction, production replay, 24 independent geometry checks,
wrong-row negative controls and LeRobot decoding of 18 native RGB images.
Replay and alignment have zero physics callbacks. Four lifecycle cycles cover
success, failure, incomplete and discard. A separate human WAITING process exits
cleanly with code 130 after one SIGINT; no active episode existed to save in that
particular interrupt check. Existing active-recording preservation remains covered
by the recorder/lifecycle regression tests, not a new physical interrupt claim.

## Commands and environments

Run from the assigned worktree, with `OMNI_KIT_ACCEPT_EULA=Y`,
`ISAACLAB_CXR_ACCEPT_EULA=1`, `DISPLAY=:0`. Restore the retained observer scripts to
their recorded `/tmp` paths when reproducing the diagnostic scheduler inventory.
The observer launcher is run with the declared core Python and launches the normal
pinned Isaac child through the production launcher:

```sh
core=/data/vla-infrastructure/core-reconcile-validation/20260919T082843.713211Z/env/bin/python
native=/data/vla-infrastructure/isaac61_production/env/bin/python
"$core" /tmp/vr_ffft_native_launcher.py diag --xr-smoke --hud-on-start --capture-preview-evidence --max-control-steps 60 --run-dir /tmp/vr-zed-ffft-preview-60
"$core" /tmp/vr_ffft_native_launcher.py record --smoke --injected-actions --rgb-e2e-assay --injected-count 6 --max-control-steps 12 --run-dir /tmp/vr-zed-ffft-record/run --recording-dir /tmp/vr-zed-ffft-record/episode
"$core" /tmp/vr_ffft_native_launcher.py record --xr-smoke --no-client-audit --injected-actions --audit-lifecycle-cycles 4 --performance-warmup-steps 0 --performance-window-steps 10 --max-control-steps 60 --run-dir /tmp/vr-zed-ffft-lifecycle/run --recordings-root /tmp/vr-zed-ffft-lifecycle/recordings
./run-vr replay --recording /tmp/vr-zed-ffft-record/episode/session.hdf5 --episode 0 --render-cameras /tmp/vr-zed-ffft-record/replay-rgb --run-dir /tmp/vr-zed-ffft-record/replay-run
"$native" tools/isaac_vr_lerobot_materialize.py extract --recording /tmp/vr-zed-ffft-record/episode/session.hdf5 --output /tmp/vr-zed-ffft-record/projection --portable-root recording=/tmp/vr-zed-ffft-record/episode --portable-root isaac61_production=/data/vla-infrastructure/isaac61_production --portable-root project_assets=/data/vla-infrastructure/assets
"$core" tools/isaac_vr_lerobot_materialize.py materialize --bundle /tmp/vr-zed-ffft-record/projection --replay-report /tmp/vr-zed-ffft-record/replay-run/result.json --output /tmp/vr-zed-ffft-record/lerobot --repo-id local/zed-ffft-check --task-id dual_cube_to_matching_plates
"$native" tools/isaac_vr_rgb_alignment_assay.py --recording /tmp/vr-zed-ffft-record/episode/session.hdf5 --output /tmp/vr-zed-ffft-record/alignment --current-projection /tmp/vr-zed-ffft-record/projection --replay-report /tmp/vr-zed-ffft-record/replay-run/result.json
"$core" /tmp/vr_stop_ffft_native_check.py
```

These are original run locators; repetitions require new private output directories.
The first diagnostic used `--max-control-steps 36` and `/tmp/vr-zed-ffft-preview`.
It failed the unfinished toggle/recenter smoke, while camera/mount validation passed.
The full scenario passed; no failed output was rewritten.

Core checks use the declared reconciled environment with `uv run --no-sync`,
`UV_PROJECT_ENVIRONMENT` pointing at that environment,
`UV_CACHE_DIR=/tmp/vla-vr-ui-uv-cache`, `HF_HOME=/tmp/vr-zed-ffft-hf`,
`HF_DATASETS_CACHE=/tmp/vr-zed-ffft-hf/datasets`, and `PYTHONPATH` pointing at
`packages/lerobot_robot_piperx/src` in the assigned worktree.
`python -m pytest -q` produced [701 passes and three socket sandbox failures](core_tests.txt),
26 skips and four passing subtests. The independent escalated
`python -m pytest -q tests/test_isaac_eval_rpc.py` [passed all 27 tests](rpc_tests.txt),
including those three; 704 distinct tests therefore passed across runs. Earlier
missing editable-source and default-cache setup errors were corrected without
changing environment pins or weakening tests. The focused runtime suite passed 199.
The retained pytest stdout preserves its original bytes, including whitespace on
empty traceback lines; source diff whitespace checks exclude that raw attachment.

## Registration and limitations

Every retained file is indexed as frozen evidence. Source identities, selected
native results, scheduling, validation and test outputs have artifact IDs; the
README is navigation. The new evidence is bound to D0/S1/S2/D1 with physical S2
and D1 unresolved. The reviewed MANIFEST membership remains unchanged; frozen
bundle bytes are checked through artifact hashes and historical documentation
protection rather than added to the normative manifest set.

Bulk recordings, snapshots, RGB files and videos remain outside Git at temporary
paths. This bundle retains selected outputs and their identities, not durable
retention of those bulk artifacts. It proves the bounded reported checks, not
reproducibility after disposable data removal, headset visibility, a 30-FPS
wall-clock rate or physical qualification. The native diagnostic's legacy
`canonical_d0_changed=false` field is not image-schema evidence; native ZED
schema/fingerprint changes are explicit in the contract and D0 tests. Preview
source/upload buffers match byte-for-byte; independent preview/replay RTX renders
share optics/poses/geometry, without a claim of identical stochastic pixels.
