# Step 1 canonical VR base review

Scope: one S2 VR runtime with run/diagnostic observers; no dataset recording and
no physical Quest evidence. S2 and D1 remain unresolved. The runtime source hashes
in retained run manifests identify the tested implementation over parent `2e80d23`;
these development smokes intentionally record the dirty worktree.

## Upstream audit and size re-audit

- CAPABILITY / GATE: canonical operator composition for S2; runtime smoke only.
- PINNED UPSTREAM CANDIDATES: existing final Isaac61 SDK/environment, retained
  legacy rollback. Exact package/checkout pins remain in the environment and shared
  S2 config and were checked by the launcher; no new dependency selection.
- WHAT UPSTREAM ALREADY OWNS: Isaac application, articulation/physics, Camera,
  Teleop lifecycle/controller source, relative retargeting, differential IK,
  XRCore recenter and SceneUI feed presentation.
- EXACT REMAINING GAP: canonical configuration selection, run/diag observers,
  required-feed metadata guard, complete small launch provenance and accurate
  S2/experimental report scope.
- PROCESSOR / CONFIG / ADAPTER REQUIRED: preserve the S2 processor and narrow
  tracking-safe retargeter; rename existing VR composition and launcher; add the
  explicit config loader and camera guard. The same loop applies native targets.
- ENVIRONMENT IMPACT: none to packages, lock files or environment identity.
  Current launch references changed. The registered original environment spec is
  retained byte-for-byte in `isaac1103_environment_before_vr.yaml`; its historical
  artifact keeps the original hash. The current spec has a new artifact ID.
- WHY NO PROJECT FRAMEWORK IS NEEDED: two explicit mode values select observers;
  one existing scene builder and one existing S2 loop own all control/lifecycle
  behavior. Existing integration modules already exceed the size threshold; this
  re-audit does not justify another backend/factory/loop. Future recording consumes
  the same observation/decision/label/native/outcome boundary.

## Review points

RUN reads only small source frame counters plus image-buffer shape/dtype. It does
not instantiate the performance logger, compute full-frame hashes or poll GPU
telemetry. Required camera progression is bounded by canonical config and reset
starts a new epoch. DIAG requires strict progression for all three feeds and adds
hashes/timers/GPU/transition data. A source counter that falsely advances while its
content is stale is outside this guard's guarantee; static images are legitimate.

The real shared loop is exercised offline with synthetic controller sequences and
vendor IO/IK substituted deterministically. Its actual processor commands and
native target conversion/clamping match exactly across modes through tracking
loss/recovery, clutch, inactivity, reconnect and reset. Vendor differential IK
execution itself is covered by the pinned runtime smokes, not the substitute.

The asset-lab profile is diagnostic-only and verifies its manifest/checkout/assets.
Default composition never reads that manifest or checkout. Existing generic S2
wrapper had no live useful consumers; current environment/contract references now
point at `./run-vr`. Historical evidence and dated launch records remain intact.

`validation.json` records observed results and hashed persistent run artifacts.
Full core tests use the existing core environment with the local plugin source on
PYTHONPATH, HF cache redirected to /tmp and local Unix sockets permitted. Isaac
upstream tests run separately in the pinned Isaac61 environment. Mypy checks the
changed modules with explicit package bases and vendor imports unavailable in core
ignored; this is not a claim of vendor type checking.

No new physical human gate, dataset, recorder or recording command was created.
Next gate work is physical S2 qualification; recording remains the later D1 task.
