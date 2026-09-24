# OLD master versus CURRENT: native physics and wall-time result

## Verdict

For the four deterministic, no-client cases tested here, OLD and CURRENT have
**identical native trajectories at every retained 120 Hz sample** in all three
repetitions. The render-policy assay ran OLD at **13.07 control Hz (RTF 0.436)**
and CURRENT at **50.33 control Hz (RTF 1.678)** after 30 warmup controls. The
same simulated motion therefore took roughly **3.85 times as long** on OLD in
this matched-command workload. Separate full no-client launches measured OLD
`./run-vr` at **11.58 Hz (RTF 0.386)** and CURRENT `./run-vr record` at
**41.86 Hz (RTF 1.395)**, a **3.61×** rate ratio. This supports removal of historical wall-clock slow motion as
the main explanation for the tested drop and gripper observations. The headset
operator workload was not reproduced, so these are not claimed as physical
Quest session rates.

The first OLD bounce placement overlapped the arm workspace and produced lateral
cube motion. Its trace is retained as a failed attempt. The reported bounce
comparison uses `(1.10, 0.40, 1.12)` metres on the open table corner in both
revisions. No outlier or native sample was removed from any completed case.
The failed OLD trial advanced its process-global physics-step counter by 363;
the full-state comparison aligns steps relative to each case start and retains
that absolute counter in the raw samples. All recorded cube pose and velocity,
joint pose and velocity, TCP pose, target, contact proxy, and simulated-time
fields match at corresponding native samples.

## Native trajectories first

| Case | Simulation-time result | Wall-time result |
|---|---|---|
| Cube free fall | OLD/CURRENT `z` and `vz` differ by **0** at every point through 0.400 simulated seconds. At that point `z=0.414178 m`, `vz=-3.923985 m/s`; median acceleration is `-9.80999 m/s²` in both. | 0.400 simulated seconds takes 0.940 s OLD versus 0.256 s CURRENT (mean of 3). |
| Table drop/settling | `z` and `vz` differ by **0** at every sample. First impact 0.250 simulated seconds, pre-impact `vz=-2.370755 m/s`; zero rebounds and no rebound height in either run. Both satisfy the 0.2 s low-velocity settling window starting at 0.2667 simulated seconds and end at the same pose. | Mean impact 0.575 s OLD versus 0.153 s CURRENT; mean settle 0.615 s versus 0.167 s. |
| Free gripper close | Leader aperture differs by **0** at every sample. 10–90% closure 0.2167 simulated seconds; settle 0.4667 simulated seconds, peak speed 1.1555 m/s, and no overshoot in both. Followers and velocities are retained in raw samples. | Mean 10–90% closure 0.523 s OLD versus 0.139 s CURRENT; mean settle approximately 1.114 s versus 0.295 s. |
| Arm target | Left joint 1 and TCP X differ by **0** at every sample. Final TCP position is `(0.595538, 0.236075, 1.026480) m` in both. | Mean 1.5 simulated seconds takes 3.557 s OLD versus 0.941 s CURRENT. |

The free-fall comparison stops at 0.400 simulated seconds, before the floor
collision. The drop contact event is identified from the vertical velocity
jump; the plotted contact dots are a geometric height proxy. PhysX contact
impulse was unavailable from this cube setup, so no impulse is claimed.
Mass alone would not change ideal gravitational acceleration; the directly
measured acceleration and effective gravity agree across these checkpoints.

The separate rate pass ran 300 controls with no per-substep readback, after 30
warmup controls. It measured 52.28 physics steps/s OLD and 201.32 physics
steps/s CURRENT. Native trajectory pass wall times include GPU readback and
are used only to align the same motion in wall time.

The additional full-loop check ran 330 controls through OLD `./run-vr --smoke`
and CURRENT `./run-vr record --smoke --injected-actions`. OLD's own execution
report gives 330 controls in 28.500 wall seconds: 11.58 control Hz and 46.32
physics Hz. CURRENT's 300 post-warmup control boundaries span 7.167 wall
seconds: 41.86 control Hz and 167.43 physics Hz. CURRENT committed all 330
recording frames and passed its no-client validation. These full launches are
supporting rate evidence, not a matched-action physics experiment: OLD had no
tracking and held target, while CURRENT used deterministic injected actions
and committed rows. Neither included a physical XR session.

## Direct answers

1. **OLD wall control rate:** 11.58 Hz in exact no-client `./run-vr`; 13.07 Hz in the matched-command native assay.
2. **OLD RTF:** 0.386 in the full no-client run; 0.436 in the assay.
3. **CURRENT wall control rate/RTF:** 41.86 Hz / 1.395 in exact no-client RECORD with 300 post-warmup controls; 50.33 Hz / 1.678 in the matched-command assay with RECORD's render and camera policy.
4. **Cube free fall in simulation time:** exact equality through the contact-free 0.400 s window.
5. **Bounce/restitution/settling in simulation time:** exact equality; neither drop rebounded in this tested placement, and both settled at the same simulated time and final pose.
6. **Gripper closure in simulation time:** exact equality in leader position, with the same 10–90%, peak velocity, overshoot and settling result.
7. **Arm motion in simulation time:** exact equality for the fixed joint target and TCP trajectory.
8. **Wall-time difference:** OLD takes about 3.6–3.8 times longer for these instrumented trajectories; the separate control-rate ratio is 3.85.
9. **Cube mass:** unchanged; effective PhysX tensor mass is `0.035000000149 kg` on both.
10. **Inertia:** unchanged; effective cube diagonal inertia is `(9.333332855e-6, 9.333332855e-6, 9.333332855e-6) kg·m²`, zero off-diagonal, and COM at the origin on both.
11. **Friction/restitution/damping/sleep:** unchanged in the snapshots. Cube/table static/dynamic friction are 0.8/0.6, restitution 0; cube linear/angular damping 0/0.05, sleep threshold `5e-5`, and max depenetration velocity 1.0. Effective cube contact/rest offsets are 0.0013625/0 m on both.
12. **Gripper actuator/mimic:** unchanged. Effective leader stiffness/damping/force/velocity are 400/40/2/3; follower pairs are 0/0/1/3. Both imported followers have `NewtonMimicAPI`; generated coefficients are +0.5 and −0.5. PhysX tensor friction and armature are zero on all nine joints in both.
13. **Timestep/substeps:** both use `1/120 s` physics and four substeps per 30 Hz logical control. OLD renders four times; CURRENT RECORD renders only on the fourth. Neither alters the native step count.
14. **Robot conversion/USD:** source and composed URDF SHA-256, converter settings and converter asset hash match. The isolated fresh conversions produce different byte SHA-256 for two of nine USD payload files; the Physics payloads match. One difference is an absolute-path document field in `base.usda`; the binary geometry payload also differs bytewise, but no semantic geometry change was established. The effective mass, inertia, drives and trajectories match.
15. **Classification:** the tested effect is wall-clock RTF plus changed visual presentation cadence. No real physics regression or gripper control increment change was measured. Similar perceived arm speed during live relative-pose teleop remains an inference until a matched headset input trace is available.
16. **Exact physics parameter/commit cause:** none identified because no simulation-time trajectory difference remains; change-point archaeology and substitutions are unwarranted for this result.

## Control semantics and presentation

Both `isaac_s2_processor.py` revisions compute `aperture = open +
trigger_fraction × (closed − open)` as an **absolute** target. The offline
processor check in `control-semantics.json` fed the same 0.1 m controller-pose
change in eight versus thirty relative samples. After the configured 2×
translation scale, both revisions integrated to 0.2 m, while the individual
output delta was 0.025 m at 8 Hz and 0.006667 m at 30 Hz. All gripper target
samples were 0 m. This checks the processor's semantics; it does not recreate
the operator's physical controller path or IK under different sampling.

OLD calls `sim.step()` with rendering on each 120 Hz substep and services camera
updates inside that loop. CURRENT RECORD uses `F,F,F,T`, disables live RGB and
suspends its three dataset RenderProducts. The current physics scene has one
extra `NewtonSceneAPI` schema, but `runtime-diff.json` finds no differing
effective USD physics attribute or PhysX tensor value. Faster wall presentation
must not be read as faster simulated acceleration.

## Asset and cache finding

The generated root URDF has SHA-256
`103af50b99b17e4ff962b7f563459672ad89556661de79cbd30c1792fea92a6f`
in both isolated state roots. Both use the same converter settings: fixed base,
unmerged fixed joints, no self collision, force position drives, 400/40 gains,
and native mimic import. The pinned `AssetConverterBase` checks a hash of the
converter config and main URDF before reusing its output, even though the
directory name itself contains only URDF SHA. Its own documented limitation is
that referenced secondary files are outside that hash. The assay's separate
state roots prevent cross-checkpoint cache reuse. `asset-parity.json` retains
every generated USD payload hash; byte mismatch alone is not a PhysX parameter
change.

## Evidence and limits

`results.json` has per-repetition metrics and exact sim-time maximum differences;
`full-loop-rates.json` holds the separate exact-launch rate check and durable
raw result/benchmark/recording digests;
`runtime-old.json`, `runtime-current.json` and `runtime-diff.json` hold actual
loaded USD/PhysX readbacks. `provenance.json` contains exact checkpoint, source,
raw trace path and SHA-256 identities. The nine SVG plots show the requested
simulation-time, wall-time, contact and rate views. No gate was promoted, no
production default was changed, and this run supplies no physical-human
qualification. The no-client assay applies the RECORD render/suspension policy
but bypasses Episode Recorder row commits and the live XR session; its rate is
an explanatory workload measurement, not a claim about the operator's headset
rate. USD exposed some properties only as defaults or did not expose a PhysX
tensor accessor; those cases are explicitly marked in the snapshots.
Cube density does not determine mass because 0.035 kg is authored explicitly;
the material's density field is 0. The table's effective static collider
contact/rest offsets and material combine modes were not exposed by this
readback, so their exact numeric values are not asserted. Their authored
configuration and recorded USD attributes match.
