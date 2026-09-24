# VR RECORD runtime optimization audit

Research experiment from `origin/experiment/vr-live-camera-temporal-cost-audit` at
`90e40ded79725d78b249245ab69ea93d024ef8e5`. No gate, production default,
physics configuration, canonical dataset camera, dataset label or recording schema
was changed. The measured workload is active XR with **no physical Quest client**,
deterministic injected native actions, three dataset RenderProducts suspended,
annotators detached and preview panels absent. It is a host RECORD critical-path
assay, not a human manipulation or headset presentation result.

## 1. Executive conclusion

The supported
`MinimalRendering` renderer had no material 300-control host latency benefit;
the XR `performance` quality preset and warped foveation were already effective
at baseline. Raising render resolution cost time. HDF 128 reduced the number of
flush-associated deadline misses without a meaningful mean reduction. The one
transfer native-state experiment preserved the observed state exactly in its
same-boundary checks but did not improve screening mean. Reversible P-core
affinity showed the only substantial screening signal. Its long cohort was
variable. Combined with HDF 128, it gave the best tested mean/p95/p99:
**28.397/30.966/35.321 ms** at **35.215 effective Hz**, versus the matched
**29.787/33.239/37.466 ms** and **33.571 Hz** baseline. Deadline misses fell
from **439 to 198 of 9000**. The **25 ms mean** and **30 ms p99** research
targets were not met; p99.9 worsened from 46.544 to 52.367 ms. The combination
also doubles the periodic unflushed-row window. No Quest-facing quality or
comfort conclusion follows.

## 2. Reproduced baseline and invariant checks

The unchanged source branch's retained C0 was 29.595 ms mean, 33.790 effective
Hz, 32.715 ms p95 and 36.271 ms p99. This branch first reproduced C0 in two
independent 300-warmup/1000-measured processes: 30.289 and 30.353 ms means.
A third 300-warmup/3000-measured process gave 29.804 ms mean. The first two
were slightly slower and had worse tails; the longer process converged near
the retained baseline. No optimization was benchmarked before this check.

The subsequently interleaved flush-policy H0 controls (3 × 3000) had 29.743 ms
mean, 33.216 ms p95, 37.439 ms p99, 45.806 ms p99.9 and 57.853 ms max, at
33.622 effective Hz with 427/9000 misses of the 33.333 ms deadline. This is
the conservative pre-affinity reference. The newly matched final controls are
reported in section 10.

All selected processes used 120 Hz PhysX, four native callback integrations per
logical 30 Hz control, F,F,F,T rendering, the same task and robot settings,
XR scale 0.4 except explicitly marked scale tests, and the same
`/data/ebulochkin/vla-runtime/isaac-isaac61` state/cache root. Their
`mechanisms.jsonl` records were checked for disabled dataset products,
unbound preview panels, native callbacks and Kit pumps. Each completed long
HDF process committed 3300 frames including warmup, with a terminal successor
snapshot and periodic plus terminal flush. Raw process records and controls
remain under the raw root described in
[provenance](provenance.json); numeric cohorts are explicit in
[cohorts.json](cohorts.json) and [results.json](results.json).

The no-client injected workload skips human tracking, IK variability and
CloudXR network/codec timing. The 30 Hz target is a research budget, not a gate.

## 3. Renderer results

The pinned Isaac Lab `IsaacRtxRenderer` constructor resets
`/rtx/rendermode` to `RealTimePathTracing` when determinism settings are applied.
The supported `MinimalRendering` and `/rtx/minimal/mode=2` selector therefore
had to be set after that constructor and before RenderProducts/XR resources
attached. A startup-only attempt read back as RealTimePathTracing twice;
those attempts are retained as ineffective setup, not R1 measurements. No
hot-switch was used and no CUDA error 700 was observed in valid R1 runs.

Two valid R1 screening processes measured 29.327 and 29.386 ms means, with
36.327 and 35.695 ms p99. A matched nearby R0 screen measured 29.286 ms mean
and 36.253 ms p99. Another paired screenshot run gave R0 30.510 versus R1
30.195 ms mean. These short samples do not establish a ≥0.5 ms gain, and R1
was not long qualified. Effective renderer readback was `MinimalRendering` for
R1 and `RealTimePathTracing` for R0. The representative desktop XR viewport
captures are [R0](operator-r0.png) and [R1](operator-r1.png). They look very
similar in this fixed scene; a Quest operator must assess readability and
comfort. The renderer switch affects appearance, not dataset cameras,
physics, action labels or HDF durability.

## 4. XR quality, foveation and resolution

The pinned XR experience already requests and reads back
`profile/persistent/renderQuality=performance`; R2 is a no-op contrast, so R3
Minimal plus quality was correctly not benchmarked. The explicit R2 process
read back the same `performance` setting and measured 30.195 ms mean / 38.899
ms p99, which is a repeated baseline condition rather than an independent
quality variant. The pinned XR core/profile
also reads back `foveation/mode=warped` at the baseline scale 0.4, contrary to
the suggested OFF baseline matrix. A nominal baseline process inherited a
preceding `none` setting through the persistent state root and is excluded;
later controls explicitly requested warped and verified its readback.

The supported pinned menu modes are `none`, `inset` and `warped`. No custom
foveation or CloudXR renderer was added. `none` at scale 0.4 read back `none`
and the same `2 × [819 × 716]` render resolution; two 300-control processes
gave 29.759 and 29.928 ms means. With warped effective, 0.5 read back
`2 × [1024 × 896]` and gave 31.187 and 30.292 ms means; 0.6 read back
`2 × [1228 × 1075]` and gave 31.101 and 31.488 ms means. Neither is a host
headroom optimization. Desktop captures for [none](operator-fov-none.png),
[0.5](operator-scale05.png) and [0.6](operator-scale06.png) are retained, but
cannot establish physical headset pixel quality, dropped/presented frames,
tracking quality or comfort. XR changes affect operator rendering only.

## 5. HDF flush tail and durability

H0 (64 rows) and H1 (128 rows) were isolated from renderer, XR and affinity
changes, interleaved in three fresh 300-warmup/3000-measured processes each.
Across all 9000 controls per cohort, H0 mean/p95/p99/p99.9 were
29.743/33.216/37.439/45.806 ms; H128 were
29.739/33.081/37.022/46.741 ms. H128 saved just 0.003 ms mean and 0.417 ms
at p99, but worsened p99.9 by 0.936 ms; the per-process p99 direction was
not uniform. Deadline misses fell from 427 to 395 of 9000. H0 had 141
measured flush controls, all late; H128 had 69, all late. Conditional flush
cost was 7.79 versus 7.93 ms mean. Nonflush misses were 286 versus 326, so
fewer flushes did not resolve the wider tail.

H2 (256 rows) had two 300-control processes: 31.505 and 29.448 ms means,
39.504 and 34.049 ms p99. It gave no stable screening case for long
qualification. H128 doubles the maximum unflushed periodic window from 63 to
127 committed rows; terminal close still flushes and finalizes. It changes
durability exposure, not fields, causal ordering or physics. Because larger
flush intervals did not materially improve the whole control tail, an async
writer/flush redesign was not justified. Strict pinned SessionReader and project
validation accepted 53 finalized recordings with 79,100 committed rows and
distinct observation identities. A controlled H128 interruption after at
least 63 post-warmup controls left the manifest `in_progress` with no terminal
successor or finalized claim, even after its separate Kit/CloudXR processes
were cleaned up by exact owned PIDs. This was an interrupted-launcher assay;
a direct Kit SIGKILL retry failed setup because another user occupied the
CloudXR port, so direct-Kit crash durability remains UNMEASURED. Existing
abort/failure and terminal-marker unit tests passed.

## 6. State capture audit and low-risk candidate

Measured `successor_capture` was roughly 3.6 ms/control in the inherited C0.
The scoped breakdown counted 601 snapshot captures over 300 warmup plus 300
measured controls: 1202 native joint-state reads (two CPU conversions per
snapshot), 601 Fabric pose-batch reads, 1202 pose host conversions, and 603
digest calls. Native joint reads averaged 2.386 ms/capture, the Fabric frame
1.116 ms, pose conversion 0.113 ms and digest 0.112 ms. Nested timers overlap;
these numbers are not additive with the observation-factory timer. The single
Fabric `XformPrim.get_world_poses` already batches both articulations, the two
task objects and three camera poses. Snapshot fields are copied before commit;
the existing owned staging prevents later physics from overwriting O_t.

S1 concatenated both native joint slices before one device-to-host transfer,
preserved the original field mapping and physics-generation checks, and
compared the first ten warmup snapshots per process exactly at the same
boundary. Both 300-control processes passed 10/10 exact checks. Their means
were 30.063 and 30.176 ms. The two adjacent explicit-warped controls were
29.215 and 30.210 ms; pooled S1 mean was 0.407 ms slower. Pooled S1 p99
improved but p99.9 and max worsened, and the control variation is too large
for a tail claim. S1 was not selected or long qualified. Its partial parity
assay does not qualify all future snapshots. No schema or production sampler
change was made; no extra state-copy optimization was introduced.

## 7. CPU scheduling and host configuration

Host `intel_pstate` is active, turbo is enabled and the governor reports
`powersave`. Observed P-core clocks under load reached about 4.3–5.2 GHz and
E cores about 3.4–3.7 GHz; the governor label alone is not proof of throttling.
Logical 0–15 are eight hyperthreaded P cores, 16–23 are eight E cores. Default
Kit threads can run on either class and migrate. The governor sysfs control is
read-only to this user, so performance-governor impact is UNMEASURED; no sudo
or persistent host change was used.

`taskset -c 0-15` is a reversible whole-process affinity screen. Its two
300-control runs averaged 28.266 and 28.690 ms versus adjacent default runs
of 30.047 and 31.083 ms. Pooled p99 was 34.216 versus 37.554 ms and misses
13 versus 54 of 600. One pinned run had a 108.646 ms maximum and a poor
p99.9; no outlier was removed. The longer qualification and physical caution
are below. Whole-process affinity also constrains ancillary XR threads, so a
Quest run must check presentation/tracking before selection.

An operator can later make a **temporary** governor comparison only with host
authorization. This audit did not perform it. Record and restore every
per-CPU value around the same interleaved benchmark commands:

```sh
governor_snapshot=$(mktemp)
for governor_file in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  printf '%s %s\n' "$governor_file" "$(cat "$governor_file")"
done > "$governor_snapshot"
sudo cpupower frequency-set -g performance
# Repeat the same default-scheduling no-client XR cohort in fresh output directories.
while read -r governor_file prior_governor; do
  printf '%s\n' "$prior_governor" | sudo tee "$governor_file" >/dev/null
done < "$governor_snapshot"
```

## 8. Optional live scene visuals

Pinned scene source uses one dome and one distant light, PreviewSurface table
and props, a visual-only backdrop, and imported robot visual meshes. The
tested Minimal renderer did not show material host savings, while native
physics and Kit pumping dominate the measured time. No lighting, material,
mesh, shadow, reflection or LOD switch was introduced; visual simplification
remains UNMEASURED. The retained screenshots cover renderer and XR settings
only. Scene physics, object poses and task semantics stayed identical.

## 9. Physics-cost observations, without physics changes

Native PhysX integration costs about 11.9 ms per four-step control in C0, the
largest measured single stage. The VR scene enables robot self-collision and
contact sensors at runtime, uses 8 position/2 velocity solver iterations,
table and object collision, and convex-hull properties for task geometry.
The URDF conversion's `self_collision=false` is not proof that the runtime
robot's explicit enabled-self-collision setting is off. Disabling collision,
contact reporters or reducing solver work could change reachability, contact
and accepted motion; any such variant needs separate S1/contact and physical
requalification. No physics variant was mixed into these renderer/HDF/CPU
cohorts, and no 60 Hz result is claimed.

## 10. Combined candidate and matched long qualification

`OPT-COMBINED` uses only P-core affinity plus HDF 128, each screened
independently. It keeps RealTimePathTracing, XR performance/warped/0.4,
120 Hz physics, F,F,F,T, camera products/panels OFF and exact state/action
recording. It changes host scheduling and periodic HDF durability, not visual
appearance or dataset/physics semantics. All three groups used fresh processes,
300 warmup and 3000 measured controls, in interleaved order. No slow control
was removed.

| Candidate | Mean | p95 | p99 | p99.9 | Hz | Misses / 9000 |
|---|---:|---:|---:|---:|---:|---:|
| R0 default / H64 | 29.787 | 33.239 | 37.466 | 46.544 | 33.571 | 439 |
| P cores / H64 | 29.316 | 34.071 | 37.309 | 48.856 | 34.112 | 666 |
| OPT-COMBINED P cores / H128 | **28.397** | **30.966** | **35.321** | 52.367 | **35.215** | **198** |

Per-process means and p99 expose the variability; pooling retains all nine
measured windows:

| Process | R0 mean / p99 | P cores H64 mean / p99 | Combined mean / p99 |
|---|---:|---:|---:|
| 1 | 29.804 / 37.467 | 28.403 / 35.033 | 28.480 / 35.878 |
| 2 | 29.934 / 38.391 | **30.982 / 38.857** | 28.443 / 35.865 |
| 3 | 29.624 / 36.904 | 28.562 / 35.834 | 28.270 / 34.645 |

The second P-core/H64 process had slower native physics and Kit stages and
lower observed process CPU use. Its settings and F,F,F,T checks passed, and
there is no proven external cause, so it remains in the cohort. H128 alone had
negligible mean effect, while the combined long group was steadier. Do not
attribute the full pooled combined-versus-P-core difference to flush or assume
the individual gains add. Combined mean is 1.390 ms lower than R0, p95 2.273
ms lower, and p99 2.145 ms lower. Misses fell by 241/9000, a 54.9% relative
reduction. p99.9 rose by 5.823 ms and the maximum rose from 97.320 to
102.449 ms, so extreme tails remain unresolved. H128's durability tradeoff
prevents automatic production selection. The strongest host candidate for
later physical comparison is `OPT-COMBINED`, not a gate promotion.

Mean stage times in R0 versus combined (ms/control): simulation advance
23.552→22.540, successor capture 3.661→3.672, causal commit/record
1.714→1.415. Nested nonadditive timings: native physics 11.917→11.693,
Kit visualizer pump 7.461→6.845, HDF append 0.249→0.211, amortized flush
0.121→0.056. The change is distributed across CPU-sensitive stages; neither
GPU nor CPU utilization alone identifies a bottleneck.

## 11. 30 Hz budget and remaining bottlenecks

Deadline: **33.333 ms/control**. Mean headroom is `33.333 − mean`; p99
headroom is `33.333 − p99`.

| Cohort | Mean headroom | p99 headroom | Remaining to 25 ms mean | Remaining to 30 ms p99 |
|---|---:|---:|---:|---:|
| R0 | +3.546 ms | −4.133 ms | 4.787 ms | 7.466 ms |
| OPT-COMBINED | +4.936 ms | −1.988 ms | 3.397 ms | 5.321 ms |

Thus mean meets the 33.333 ms period, but p99 misses it even after the best
tested combination. Native physics still consumes about 11.7 ms/control,
Kit pumping about 6.8 ms nested in the render path, and immutable successor
capture about 3.7 ms. HDF flushes create discrete late controls; nonflush
combined p99 is still 34.470 ms. In measured windows, R0 process CPU
averaged about 323–325% of one core, RSS about 7.49–7.51 GiB, GPU utilization
about 48% and VRAM about 7.9 GiB. Combined runs used about 323% process CPU,
7.49–7.52 GiB RSS, 50% GPU utilization and 7.8–7.9 GiB VRAM. These are
resource observations, not independent CPU/GPU bottleneck proof.

Plots: [effective Hz](effective-hz.png),
[mean/p95/p99](latency-by-candidate.png),
[deadline headroom](headroom.png), [stage times](stage-time.png),
[flush-tail comparison](flush-tail.png),
[renderer comparison](renderer-comparison.png), and
[measured optimization waterfall](optimization-waterfall.png).

## 12. Exact later physical Quest A/B

Run from this branch in the assigned checkout **after a human authorizes the
specific physical manipulation**, connects the Quest and follows the
[VR operator guide](../../project/RUN_VR_OPERATIONS.md). The opt-in
`tools/runtime_perf_followup/sitecustomize.py` keeps the regular
`./run-vr record` scene/control/preview/lifecycle and pins effective XR
performance/warped settings for a matched test. It contains no action injector.
Keep the same state root, task, operator procedure and Quest connection for
all three; use a fresh output directory each time. Stop with Ctrl-C if needed.

```sh
export OMNI_KIT_ACCEPT_EULA=Y ISAACLAB_CXR_ACCEPT_EULA=1
export STATE_ROOT=/data/ebulochkin/vla-runtime/isaac-isaac61
export PERF_HOOK="$PWD/tools/runtime_perf_followup"
export FOLLOWUP_ROOT="/data/ebulochkin/vla-runtime/evidence/20260924_vr_record_runtime_optimization_audit/physical-followup/$(date +%Y%m%dT%H%M%S)-$$"

# 1. Original baseline, 64-row flush, RealTimePathTracing.
env PYTHONPATH="$PERF_HOOK" VR_PERF_FOLLOWUP=1 VR_PERF_RENDERER=baseline VR_PERF_FLUSH_EVERY=64 \
  ./run-vr record --state-root "$STATE_ROOT" --run-dir "$FOLLOWUP_ROOT/baseline/run" \
  --recordings-root "$FOLLOWUP_ROOT/baseline/recordings" --xr-resolution-scale 0.4 \
  --max-control-steps 3300 --performance-warmup-steps 300 --performance-window-steps 3000

# 2. Renderer-only research candidate, MinimalRendering mode 2; HDF 64.
env PYTHONPATH="$PERF_HOOK" VR_PERF_FOLLOWUP=1 VR_PERF_RENDERER=minimal VR_PERF_FLUSH_EVERY=64 \
  ./run-vr record --state-root "$STATE_ROOT" --run-dir "$FOLLOWUP_ROOT/minimal/run" \
  --recordings-root "$FOLLOWUP_ROOT/minimal/recordings" --xr-resolution-scale 0.4 \
  --max-control-steps 3300 --performance-warmup-steps 300 --performance-window-steps 3000

# 3. Best measured host candidate: P cores plus 128-row flush, baseline renderer.
taskset -c 0-15 env PYTHONPATH="$PERF_HOOK" VR_PERF_FOLLOWUP=1 VR_PERF_RENDERER=baseline VR_PERF_FLUSH_EVERY=128 \
  ./run-vr record --state-root "$STATE_ROOT" --run-dir "$FOLLOWUP_ROOT/combined/run" \
  --recordings-root "$FOLLOWUP_ROOT/combined/recordings" --xr-resolution-scale 0.4 \
  --max-control-steps 3300 --performance-warmup-steps 300 --performance-window-steps 3000
```

Repeat in a different order and fresh directories. Retain each run's
`performance.jsonl`, `stdout.log`, `result.json`, run manifest, native HDF and
recording manifest; extract available CloudXR/server presented/dropped-frame
telemetry without inventing unavailable fields. Record tracking interruptions,
operator task/manipulation success, and subjective readability/comfort on a
physical worksheet. If CloudXR does not expose a metric, mark it UNMEASURED.
No physical motion or Quest assessment was performed here.

## 13. Validation, provenance and interpretation limits

Raw run launch/config/source hashes, failed setups, timing rows, resource traces
and native HDF artifacts are retained outside Git; see [provenance](provenance.json).
Each plot is reproducible from [analyze.py](analyze.py). No slow controls are
discarded, and screening/long durations are labeled separately. An unrelated
user's CPU-heavy MuJoCo task overlapped three early screens, which remain
retained but excluded from matched conclusions. Unrelated CloudXR sessions
occupied port 48322 during two attempted launches; both failed setups are
retained and have no timing samples. No no-client result is a claim about headset FPS, motion-to-photon,
network/codec, operator success or comfort.

The [cohort invariant check](cohort-check.json) passed for 27 selected
processes. Strict pinned SessionReader plus project artifact validation passed
for 53 finalized recordings / 79,100 committed rows; all observation identities
were distinct. The external [raw inventory](provenance.json) lists 56 process
directories, 1,578 files and 1.706 GB, and independently matched all 1,499
completed-launch artifact hashes without mismatch. The interrupted H128
recording remained `in_progress`; it was never counted as finalized. A first
abort orchestration attempt completed before its compact-JSON threshold parser
triggered, and the subsequent direct-Kit attempt was blocked by another
user's CloudXR session. Both are retained, not performance evidence.

Focused recording/replay/XR tests: **166 passed**. The full feasible declared
core suite: **615 passed, 26 skipped, 2 warnings, 4 subtests passed**. Its
first collection attempt lacked the repository's workspace package on
`PYTHONPATH`; rerunning with the source workspace path passed without installing
dependencies. Ruff and scoped mypy passed after checking the two distinct
`sitecustomize.py` modules separately. All three proposed physical commands
passed launcher `--dry-run`; this does not test child-side renderer readback or
Quest behavior. Documentation lint with trusted base
`90e40ded79725d78b249245ab69ea93d024ef8e5` passed coverage and protected
405 frozen files. Spec-reference lint, structural/semantic resolved-contract
validation, selective MANIFEST verification (110 reviewed files), and
governance regression tests (**108 passed**) all passed. The canonical
`FINAL RC NOT READY` blockers are unchanged. Existing historical-integrity
debt and external artifact authenticity are not independently checked by the
documentation linter; the separate raw inventory checks this audit's retained
launch artifacts. Exact commands and logs are in provenance.

The report, results, provenance and raw inventory are registered as bounded
experiment artifacts with an experiment evidence record. No S1/S2/D1 gate
binding or state, dataset admission, production selector or physical acceptance
is changed.

## 14. Recommended next optimization

Run the physical Quest A/B above before selecting any host setting. The next
host investigation with a plausible remaining payoff is a measured CPU
performance-governor comparison by an authorized operator, then targeted
Kit/PhysX profiling without changing 120 Hz semantics. If a physics setting
is proposed, plan independent S1/contact requalification first. An async HDF
writer is not justified by this flush-only evidence.
