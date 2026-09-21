# Resolved XR to preclip D0 decision qualification

Scope: development over `4423cacfd1ed226bc0169cc55890589e2a5b2a4c` in the assigned
VR recording checkout. Exact tested source/config/upstream hashes, environments,
commands, numerical precision and runtime manifests are in [provenance](provenance.json).
This is bounded application-level machine evidence; no physical Quest or dataset
acceptance is asserted. D0/S0/S1 retain their accepted scope; S2/D1 remain unresolved.

## Upstream audit and size

Capability: the Isaac human resolved-input and post-IK preclip decision seam for
[[gate:D1]], with [[gate:S1]]/[[gate:S2]] regressions. Pinned candidates are Isaac
Teleop 1.4.98rc1, IsaacLab Teleop 0.9.0 and IsaacLab
`0c2e2c64e51922d088b695d72ffe03faa5c6b95d`. Their source owns DeviceIO update,
controller polling/conversion, synchronous execution and last_step_info, transforms,
relative retargeting, DifferentialIK and native articulation writes. Source was
read locally; exact file identities are retained. No upstream algorithm is copied.

The remaining gap is owned receipts and application admission. Two narrow source/
transform subclasses delegate upstream, one immutable solved-decision object binds
existing data, and the existing IK wrapper separates solve/apply. The stateful S2
processor adds a monotonic generation and immutable delta storage; its control
revision/numerics remain v3. Its provenance revision is `piper_x_s2_generation_v1`.
The new decision/source revision is `piper_x_xr_preclip_decision_v1`.
Existing integration files exceed 300 lines, so reuse was re-audited before edits:
no replacement source, transform, retargeter, IK, renderer, transaction framework,
recorder, dependency, RPC or environment is needed. Added/reworked production lines
remain below the task's 400-line re-audit threshold; exact count is in provenance.

## Exact ownership and reference

Pinned TeleopSession completes DeviceIO.update before its one source poll. The
adapter attaches a monotonically increasing application update epoch there and
captures the current request frame. One normal tracker call per hand supplies
upstream conversion. At the transform graph input, resolved controller tensors are
copied into immutable scalar/tuple values before any transform/retargeter consumes
them. The actual matrix used by ControllerTransform is copied at the same point.
Both poses/validities and all primary/secondary/menu/thumbstick/trigger/squeeze
fields are retained. Missing hands are explicit None; invalid tracking cannot
prepare a human demonstration. No second provenance poll occurs.

Session identity changes with the DeviceIO session object. Reference generation
changes on reset, applied navigation reset, recenter scheduling, exact transform
change, and tracking validity/recovery changes. Source execution reset marks its
receipt rebased. The returned metadata must be synchronous with both frame IDs
equal to the frame seen by the poll and exactly one new update. Frame/update IDs
are application causality, never physical acquisition time. No SourceTiming is
constructed. Host duration is not needed for admission.

The live matrix, session, update/reference epoch and last-consumed update are checked
before solving and again before application. Processor generation is checked at
apply. A reference change after input cannot relabel that input. Recenter keeps
existing hold/rebase behavior. Reset discards the already-acquired action without
polling again; the next loop acquires a fresh input against the new observation.

## Observation, label and native branch

The loop latches the qualified 4B capture before device.advance. Its exact object,
reset/capture/three-camera identities, physics/render producer and immutable state
are retained. Immediately before and after solving and before apply, the capture
must still be the environment's current qualified capture and both simulator and
refreshed articulation generation must match its physics step. All code executes
on the existing serialized simulation thread. Both arms solve and validate before
either target is applied; state advancement/substitution invalidates the solution.

Each arm's six original DifferentialIK desired radians are converted to degrees,
followed by processed aperture metres converted to millimetres. The ordering is
left joints 1–6, left aperture, right joints 1–6, right aperture. Immutable bytes
and a read-only view encode little-endian float32[14]. Conversion uses the exact
native float32 values promoted to float64 for unit conversion, then one float32
label cast. Quantified error is recorded in provenance; the label is the training
contract. Actuation never uses degrees-to-radians reconstruction.

Native preclip values and the original torch-clamped targets are retained separately.
The old concatenate path's float64 native values survive tuple storage exactly.
Residual is clipped minus preclip, with 14 component masks and aggregate saturation.
Gripper label/native aperture is preserved independently; current processor bounds
already limit it, and the existing native path performs no extra aperture clamp.
Its residual is therefore zero. Existing mimic expansion (+aperture/2, -aperture/2)
is unchanged and absent from the label. No saturation rejection threshold is added.
Cartesian intent retains delta, aperture, tracking, clutch, rebase, sensitivity
mode/scales and transition plus processor revision/generation. This is provenance;
the policy whitelist is unchanged.

## Preparation and tests

The shared loop exposes `env.last_control_decision` and
`env.prepared_control_transaction`. Non-eligible RUN solutions have no tick ID. Tick IDs count eligible attempts monotonically
across reset/recenter; inactive, invalid-tracking and recovery/rebase frames still
follow RUN control behavior but are not eligible. The 4A validator prepares the
observation producer reference, typed label bytes, state/three-camera identities,
and all four XR source identities in the correct session/reset/reference epoch.
It never completes or commits a transition in this step. RUN aborts the pending
preparation on the next loop. 4D must freeze images before advancing, bind the
actual native write, successful transition and qualified successor, then persist.

[Core tests](core_tests.txt) cover D0 v4, capture, processor, loop RUN/DIAG parity,
reset, old observation, state advancement, prior XR, generation/replay rejection,
preclip clipping/residuals and immutable ownership. Native parity compares the
actual original wrapper from the trusted base against the refactor for both arms,
normal/zero motion, clutch/release, loss/recovery, sensitivity min/center/max,
trigger 0/.25/.5/.75/1 and saturation. Applied arrays match byte for byte. The
actual environment mimic/write/advance methods remain byte-equivalent in AST;
the loop tests assert four requested steps and exercise eligible transactions.

[SDK tests](upstream_tests.txt) execute the actual upstream synchronous TeleopSession,
ControllersSource conversion using real schema objects, transform graph, relative
retargeters and DifferentialIKController. They prove single polling, matching
request/result metadata, owned snapshots, all controls, missing/invalid hands,
reference reset/reconnect, and original/native parity with the real solver.
[Checks](checks.txt) retain lint, contract, manifest and type results.

## Governance and limitations

The previous S2 config's exact bytes are retained in [previous config](previous_s2_config.yaml).
The existing `isaac1103_s2_config` artifact moves only its locator to those bytes,
keeping its digest and historical proof scope. A new current config artifact covers
the new machine revisions. Evidence and every bundle attachment are indexed;
MANIFEST membership is unchanged and selected current hashes are regenerated.

Initial retained failures are in [attempts](attempts.json): the AST fixture correction,
cache/import/socket environment issues, and initial smoke setup. These are not
passing qualification. The separate initial schema fixture used read-only properties;
it was corrected to the actual immutable schema constructors before passing SDK tests.
Runtime results and manifests distinguish any intermediate
source from final source. No physical acquisition timestamps, real timing changes,
HDF5, RecorderManager, converter, episode buffers, datasets or camera recording
copies were added. Physical Quest, performance qualification and human S2/D1
acceptance remain future work after 4D storage/lifecycle and 4E conversion.

Final canonical non-headless no-client [RUN](run_result.json) and
[DIAG](diag_result.json) both pass 36 control steps with reset and clean shutdown.
These do not exercise physical controller tracking. The initial no-display launch
was terminated; the subsequent cold shader compilation completed and exposed the
missing package import path. The entrypoint now explicitly adds the project root;
final source manifests and result hashes are retained. Precision sweep maximum
float32-label roundtrip error is 2.83707713322201e-7 radians; this error never enters
native actuation. Production delta is 341 added/reworked lines, 20 removed (net 321).

Final results: core **398 passed, 26 skipped, 4 subtests passed**; all 26 SDK
upstream tests pass. SDK-dependent core skips are exercised in the pinned SDK
suite. All listed governance, contract, manifest, Ruff, scoped mypy and diff checks
pass. Two warnings remain: an existing dependency deprecation and read-only input
warning from executing the unchanged historical IK wrapper for parity.
