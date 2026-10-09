# История recording/live RGB: 24 сентября — 9 октября 2026

Исследование read-only на `research/live-camera-recording-30hz`, HEAD/master `beaedfd1116577fd4d8026232cfb96cba0b030fa`; WIP при старте отсутствовал. В рамках исторического audit refs/worktrees, SDK и аппаратные процессы не изменялись. CodeGraph вызван до чтения/поиска; прочитаны NORMATIVE_MODEL, README, DOCUMENTATION_POLICY и релевантные INDEX owners vr.performance, vr.physics_rtf, vr.operations, data.collection. Это приложение исследования; новые GPU-прогоны родителя описаны в REPORT.md.

## Главный вывод

**Уточнение родительского задания:** обязательный конечный результат — строго **>30 wall Hz при active XR + реальном Quest 3** одновременно для actions и каждой live RGB камеры. До физического клиента ориентир screening — около **50 wall Hz без Quest**, чтобы иметь запас; результаты 30–40 без клиента недостаточны. Исторические таблицы сохраняют исходные >=30 deadline/target формулировки, но не задают нынешний acceptance threshold. Эксперимент no-XR при 43.649 action/camera Hz достигает лишь 0.873 от 50; native ZED equal-pixel40.147 — 0.803, native960×600XR-no-client28.614 — 0.572. Это ratios относительно screening target, **не прогноз переноса на Quest**. Одновременный 71FPS/view maximum даёт17.79actionHz; 89.16CUDA-onlyviewFPS даёт22.29actionHz. No-camera A1 FFFT51.649/controlHz не livecamera success.

Предшествующий A3 multi-tick >50Hz относится к другому no-XR workload и требует отдельного source scope; native XR multi-tick abort even camera-free запрещает переносить этот путь на activeXR. Из исследованных актуальных 09-24..10-08 pipeline результатов нет достаточного 50Hz noQuest simultaneity proof при нынешних native960×600 и корректных O_t изображениях.

**В сохранённой истории не найдено доказательства simultaneous >30 wall Hz действий AND >30 уникальных live RGB кадров/s для каждой из трёх нынешних 960×600 камер с текущими штатными физикой/качеством/XR и правильной causal O_t RGB-привязкой.** Есть ограниченные near-30 результаты исследовательского writer при 640×480 и сниженной rendering/XR quality, и многочисленные fast state-only RECORD результаты. Их scope различен.

Нынешний VR override — три massless/non-colliding ZED X One GS, native SVGA **960×600**, RGB shape **600×960×3**. В plain S2 base wrist config остаются 640×480: нельзя объявлять разрешение current VR по base S2. Master configs/isaac61_vr_runtime.yaml:85–112 содержит native camera selection/shape. Экспериментальный ZED SDK/ZEDAnnotator pipeline октября — другая композиция: он не равен выбранной 10-06 CameraCfg-only native Camera integration. Старые experimental wrist mounts добавляют 50g на каждую руку, нынешняя integration снимает housing physics.

Нет аппаратных новых запусков. В scope поиска все локальные refs + документация за 09-24..10-09; отбор содержательных recording/live performance bundles. Реальные физические runs приведены отдельно от XR-no-client; archive AGENTS не применялись. Успешный S2 predicate, comfort attestation, configured FPS, codec FPS metadata и 30 Hz simulation control не заменяют measured wall-rate/unique-frame/temporal-content proof.

## Сводная таблица измерений

Times — ms; Hz — wall/effective как указано; RGB rates per EACH view. N/A означает выключенные камеры либо отсутствие measurement, не нуль пропущенных кадров.

| Дата / опыт | Wall actions/control Hz | Unique live frames per view/s wall | mean / p95 / p99 ms | Главное ограничение |
|---|---:|---:|---|---|
| 09-24 temporal C0, XR no client, state RECORD | 33.790 effective | 0 (products OFF) | 29.595 /32.715 /36.271 | No live RGB; injected, no IK |
| 09-24 temporal C3 original FFFT independent | 24.957 effective | bookkeeping only | 40.069 /43.540 /46.479 | RGB shared N−1, 900/900 stale boundaries |
| 09-24 temporal correct prime tiled | 19.619 effective | content-correct tested assay | 50.972 /54.652 /57.979 | 9000/9000 deadline misses; no Quest |
| 09-24 correct prime independent | 16.401 effective | content-correct tested assay | 60.974 /65.513 /68.733 | no 30Hz headroom |
| 09-24 Replicator held-state correct | 10.101 effective | content-correct tested assay | 99.005 /103.008 /106.045 | short 900 controls, supported barrier |
| 09-24 state RECORD matched R0/H64 | 33.571 effective | 0 | 29.787 /33.239 /37.466 | 439/9000 deadline misses |
| 09-24 P-cores+H128 state RECORD | 35.215 effective | 0 | 28.397 /30.966 /35.321 | 198/9000 misses, larger unflushed window; no physical client |
| 09-25 state RECORD B1 XR no-client | 37.68 /repeat37.63 | 0 | 26.54/29.27/33.38; repeat26.58/29.38/33.29 | injected no processors/IK; 32/28 misses per3000 |
| 09-25 state RECORD B0 no XR | 42.09 /repeat42.00 | 0 | 23.76/25.74/30.60; repeat23.81/25.88/30.52 | state-only; not matched RUN |
| 09-25 RUN A1 XR no-client, per-substep render | 11.64 | not live training RGB proof | 85.94/91.32/94.89 | cadence differs from RECORD; can't infer recorder overhead |
| 09-26 physical dual cube RECORD | 31.1982 whole;30.7253 profiled wall | 0 | 32.461/38.901/98.536 | live_rgb false; 2371/10904 misses; RGB offline |
| 09-27 physical bowls RUN | 8.518239379575803 whole | wrist 2055 valid/advanced boundaries, no separate fps trace | unknown quantiles | 2056 entered ticks/241.36443088576198s; 640×480 |
| 10-01 original four-render carrier A0 vs Z3 | 12.211 vs16.081 | RP48.845 vs16.081; project reads30/sim-sec | 81.888 vs62.183 means | Explicitly corrected: NOT current RECORD cadence |
| 10-01 FFFT no-XR A0 vs Z3 | 31.983 vs29.429 | 31.983 vs29.429 RP completions | 31.264/33.483/40.189 vs33.977/35.857/42.986 | 640×480 vs960×600; no writer/IK/temporal admission |
| 10-01 FFFT XR-no-client A0 vs Z3 | 21.014 vs20.439 | 21.014 vs20.439 RP completions | 47.583/49.746/51.937 vs48.923/52.182/53.930 | every deadline missed; different pixel load |
| 10-01 ZED maximum H264 native960×600, no XR |17.79 |71.14 |56.22/64.14/74.15 | four RGB frames/control; actions <30 |
| 10-01 ZED max H264 XR-no-client native960×600 |11.26 /11.19repeat |45.05 /44.78 |88.79/92.73/95.01;89.33/93.99/98.85 | actions<30; low eye resolution/minimal renderer |
| 10-01 ZED H264 XR render once/control native960×600 |27.28 |27.28 |36.65/39.18/40.77 | both target conditions missed |
| 10-03 live matched noXR tuned A0 vs Z640 |43.649 vs40.147 |43.649 vs40.147 acquired window; decoded counts checked |22.906/26.481/32.815 vs24.905/29.452/34.867 | no XR; no pacing;640×480; successor sidecar writer |
| 10-03 live fullXR A0 vs Z640 vsZnative |20.204 /20.069 /19.624 |same window acquisition rates |49.492 /49.825 /50.953 means | no real client; all deadlines missed |
| 10-03 tunedXR H264 A0 |30.177 /29.986repeat |30.177 /29.986 |33.134/35.250/36.324;33.345/35.370/39.179 |216/295 misses per900;640×480; quality changed; no O0 pre-action RGB |
| 10-03 tunedXR H264 Z640 |28.808 /28.913repeat |28.808 /28.913 |34.708/37.490/42.299;34.582/36.695/42.339 |885/876 misses per900;resized non-calibration-equivalent |
| 10-03 tunedXR H264 Znative960×600 |28.614 |28.614 |34.944/37.475/42.183 |899/900 misses; not current massless composition |
| 10-03 tunedXR PNG A0 vs Z640 |27.547 vs26.139 |same window acquisition rates |36.297/39.306/43.502 vs38.253/40.905/46.323 |lossless host transfer/encode; no client |
| 10-03 live ablation baseline A0 |29.857 /29.964repeat |same window acquisition rates |33.487/36.092/39.289;33.367/35.525/38.826 |640×480; no real Quest |
| 10-03 same-boundary state reuse A0 |30.428 /30.461repeat |same window acquisition rates |32.859/34.945/38.242;32.823/34.965/36.867 |181/167 misses per900; no physics change; modest1.8% |
| 10-03 same-boundary reuse Z640 |29.226 /29.177repeat |same window acquisition rates |34.209/36.586/38.742;34.267/36.643/39.455 |below30; no temporal admission |
| 10-03 solver4/1 A0 |30.145 /30.248repeat |same window acquisition rates |33.166/35.292/38.243;33.054/35.505/37.666 |changed solver fidelity;228/219 misses; grasp/contact unqualified |
| 10-06 physical current native RUN |16.4944038878784 |1355 valid/advanced wrist boundaries; no 3-view fps trace |whole session only |1355 controls/82.14907366223633s,1350 actions; no 30Hz |
| 10-06 physical current native RECORD |26.96264858504903 |0 (live_rgb false) |whole session only |9636 controls/357.3832878326066s; waiting/review included |
| 10-07 offline LeRobot encode staged vs streaming |not live control |offline60rows×3views |6.953317256178707s vs5.289521765429527s full QA |AV1 fourCPU cores,960×600,streaming optional; no live speed claim |

## Temporal correctness и причинность

09-24 — strongest live content experiment. Under active XR no-client, original FFFT path was **N−1 in900/900** reference boundaries (3processes), including moving wrist/gripper context. Simple post-physics render, two renders without intervening extraction, batched producer, low-latency OFF, double extraction and post-extraction CUDA fence did not fix phase. Replicator supported held-state capture with delta_time=0/pause_timeline=false/wait_for_render=true and prime sequence render→discarded Camera extraction→render→final extraction yielded N/N/N. Their own physics callback guards excluded extra integrations. Fastest tested correct long path 19.619Hz, not >=30. NoXR T0 control was100/100 current: the result is context-dependent, not a universal renderer defect.

10-01/10-03 independently count native RP identities/completions/reads and validate state/action successor span4; they **do not demonstrate depicted native state O_t**, unlike 09-24 content oracle. 10-03 sidecars depict successors; segment first pre-action RGB is missing. Exactly900 distinct completion IDs/files perview means900 unique published acquisitions, not necessarily900 distinct image hashes or900 correct training observations. Static scenes can legitimately repeat pixels; completion counts cannot establish temporal content. Do not shift O_(t+1) bytes into O_t labels as a performance shortcut.

09-25 current recorder→offline RGB E2E passed6 genuine unedited V2/V3 rows,18 images,24/24 geometry checks, max3.315px error,minIoU.273;42wrong-row controls failed. Previous offline component assay48/48/max7.647px was synthetic copy of historical V1 and explicitly not genuine V2 end-to-end. Neither measures live speed. 10-06 native960×600 integration passed6rows/18images,24geometry checks(max8.065px,minIoU.5658), no replay physics, source-upload parity and repeated lifecycle; no 30-FPS claim.

## Почему источники с >30 не закрывают нынешнюю цель

1. Fast state-only RECORD has no live dataset camera products; physical09-26≥30Hz is therefore irrelevant to simultaneous liveRGB condition.
2. Experimental throughput uses deterministic native targets without human DifferentialIK/controller/processor cost. “XR-no-client” is actual native transport/session overhead with no headset client; physical stream codec/network latency is absent.
3. 10-03 A0 state-reuse reaches mean≥30 at640×480, minimal renderer/XRscale.4/P-core affinity/unpaced throughput. Current native960×600 massless vendor optics have no equivalent live writer+full temporal benchmark.
4. ZED 45FPS maxima have11Hz control. Four render samples/control do not become four independent actions.
5. Reused timestamp/frame counters ensure delivery bookkeeping; training correctness needs explicit O_t scene-state-content oracle and full episode including first frame.
6. >=30 average rates and zero drops differ from every33.333ms deadline. Even best no-physics-change near30 candidate misses167/900 deadlines; report as average ceiling only.

## Bottlenecks с измеренным scope

09-24 marginal full cameras independent C3−C0 **+10.463ms** but stale; correct tiled prime **+21.377ms** over long cameraOFF. C1 products +4.362, C2 extraction+5.129,C3ownedCPU+0.972ms. Direct three-camera extraction5.146ms,RGBdevice-to-host.483,ownedcopy.184,binding.113. Nested render_app11.928/Kit11.114 are nonadditive. RTX diagnostic published pass4.164ms operator-only,10.027withindependentcams,7.219tiled; not per-control CPU criticalpath nor per-role GPU attribution.

10-01 corrected FFFT A0 baseline cameraOFF/noXR19.358ms and paused-products20.730;XRcameraOFF35.996ms already exceeds deadline. A0 current fullcameraXR47.583 vsZ3 48.923; changing camera owner cannot erase XR baseline. Native Nsight bounded traces A0 cuCtxSynchronize304calls mean3.996ms,max13.476;Z3 cudaStreamSynchronize9279mean.140 + cuEventSynchronize2394mean.228. They are overlapping/nested API calls with noPythonstacks/product labels; do not sum or assign entirely to capture.

10-03 instrumented calls A0 three nonrender9.170ms,finalstep+render12.811,captureRGB9.382,stateHDF.376; Z64011.819/14.463/5.744/.695. After reuse A09.102/12.764/9.087/.171; repeated values9.105/12.701/9.118/.170. Hostphase sums exclude pre-action/actionmapping/targetsubmit, waits may land at later boundary. IOqueuepeak3/64, no throttling/writeslost, encoder/GPU not saturated. FullXR eye/runtime dominance is inference, not per-kernel proof.

09-25 tail: most B1 misses follow64rowflush; chunk128 lowersp99 to32.43ms finalcode from33.38old. Offthread sealed immutableverification/publication lowers synchronousend87.48→20.45ms, gap recovery213.35→145.32, open remains72.35→72.42. It removes boundary stalls without creating liveRGB budget. Context differs from09-24 flush128(policy period) experiment: don't conflate buffer_frames128 with changing period128.

## Неудачи, отклонённые изменения и fidelity

- Native XR multi-tick aborts RtxHydraEngine.cpp:2386 even camera-free: mismatched render products/result count/additional views unsupported. tickRate30 alone with multi-tick OFF does not throttle four-render carrier; FFFT controls opportunity count.
- Original10-01 four-render benchmark explicitly corrected in report: A0≠current RECORD; earlier scheduling superiority conclusions withdrawn; raw data kept.
- XR desktop viewport pause/headless+paused produces emptyCUDA output; native headless pump alone gives no material benefit and viewportproduct remains900drawables. No valid fastpath evidence.
- 10-03 disablecontacts-reporting wholesale first trials also changed unmeasured sleep override; later reporting-only preserved sleepThreshold0 and offered no improvement. Collisions stay enabled, but reporting omission removes evidence even if dynamics stay unchanged.
- Solver4/1 saves~1%, changes integration quality. No grasp/contact fidelity proof. Physicsfrequency90/60 not tested. FFFT120Hz/foursteps unchanged native trajectories in09-24 matched old/current assay(0diff allretainedsamples); this supports cadenceoptimization within scope, not any future solver reduction.
- MinimalRendering changes RGB appearance; XRscale.4 reduces eyes2048×1792→819×716; rescaled ZED640×480 preserves authored960×600optics and is not calibration-equivalent; old50gmassmounts≠currentmassless.
- H264lossy and NVENC alternative needs imagequality/trainingqualification; storedfilefpsmetadata irrelevant. PNGslower but lossless.
- Setupfailures include disabledReplicatororchestrator timeout, wrongwristquaternion, shaderstartup/tensordtype,ContactSensorbodyenumeration, missingNV_CXR_RUNTIME_DIR, portbusy, recordingparentprivacy, stale640projection, invalidoraclewitnessplacement. They remain failedattempts, never counted as complete runs.
- 10-07 codec TorchCodec0.11.1→0.5candidate paired retainedTorch2.7.1; decoderimport/AV1readQA repaired. Offline streaming removes180temporaryPNGs but raisesRSS1847.195→2428.387MiB; it speeds conversion23.928%, not live recording.

## Реальное человеческое proof и gate состояние во времени

09-26 physical state-only RECORD and09-27 bowls RUN remain exact historical scope; no applied gate promotion from them. 10-06 physical f2ac4ea RUN/RECORD originally interruptedpassedfalse; frozen operatoraudit README saysS2unresolved. Later **dd28b32 supplement** operator_stop_acceptance.json explicitly registers retrospectiveS2accepted under correctedoperator-stop predicate using original cleanexit130 and exactphysicalsource; nosecondphysicalrun. Master contains supplement. Do not assert masterS2unresolved merely from original frozenREADME. Gateacceptance doesn't assert30wallfps; operatorcomfortPASS is not numericheadsetfps trace. Saved836rowdemo declareslive_rgbfalse;23saturationrows(2.75%) documented. D1/dataset admission not established by physicalS2 supplement or staticD0 schema proof.

10-08 safety branch adds native scriptedstateRECORD/replay/loadchecks(420rows/1260offline960×600frames, and21rowcompletionfixture), no Quest/liveRGBwallrate proof. These are safety/dynamics scope, not30Hzcamera evidence. Branch is independent from master and must not be silently combined into historical testedsource.

## Raw availability, provenance и граница проверки

All primary external roots listed below exist and are readable at research time. This is existence inventory, **not full hash reauthentication**, stream reddecode or rerun. Git reports include source/run hashes and retained inventories. Runtime snapshots with WIP are identified by externalfullfiles+diff+perfileSHA; HEAD63c6db1 alone does not identify benchmark source. No artifact invented when rawlog not retained. 10-06 master FFFT bundle stores selected machine outputs in Git but bulktemporary `/tmp/vr-zed-ffft-record` remainsdisposable; directoryexistsnow doesnotguarantee durablefuture retention.

Точные `branch:commit:path` locators и SHA256 исходных Git bytes находятся в historical_sources.json. Исторические файлы не изменены и не квалифицируют новое дерево.

## Внешние roots: проверено наличие
- `/data/ebulochkin/vla-runtime/evidence/20260924_live_camera_temporal_cost_audit` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/vla-runtime/evidence/20260924_vr_record_runtime_optimization_audit` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/vla_physics_rtf_20260924` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/p25` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/p26` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/vla-runtime/zed-upstream-experiment/current-final-substep-20261001` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/vla-runtime/zed-upstream-experiment/max-fps-20261001` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/vla-runtime/zed-upstream-experiment/live-episodes-20261003` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/vla-runtime/zed-upstream-experiment/runtime-ablations-20261003` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/vla-runtime/evidence/20261006_zed_native_cameras` — exists=True, digest audit NOT PERFORMED.
- `/tmp/vr-zed-ffft-record` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/vla-runtime/manual-record-04/20260926T173138` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/vla-runtime/isaac-isaac61/runs/20260927T154956149597Z-run-robotwin_bowls_bin-hud-off` — exists=True, digest audit NOT PERFORMED.
- `/data/ebulochkin/vla-runtime/isaac-isaac61/runs/20261006T185931122784Z-record-dual_cube_to_matching_plates-hud-off` — exists=True, digest audit NOT PERFORMED.

## Machine correction: window throughput vs drain-inclusive saved throughput

В сводке и original report таблицах FPS означают measured-window `wall_control_hz`/`views.*.frames_per_wall_s`. Отдельное machine поле `fps_including_rgb_flush` включает финальный RGB flush. Это не whole-processstartup/shutdown rate и не гарантированно полный finish-sealHDFclose-inclusive rate: используем только точное определение поля. Количество сохранённых/декодированных файлов checked separately, поэтому строку с “saved rates” выше следует читать как window acquisition rate при последующем подтверждённом сохранении всех кадров. Нельзя принимать window>=30 за full-drain>=30 автоматически.

| phase/run | window control/unique camera Hz | RGB flush-inclusive FPS per view | final consumer.flush_s | raw metrics exists/read matches stored windowHz |
|---|---:|---:|---:|---|
| zed_live_rgb_episodes/no-xr-A0 | 43.648909211175 | 43.438008632417 | 0.100109888706 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/no-xr-Z640 | 40.146899718685 | 39.968411370797 | 0.100111387204 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/smoke-A0 | 43.702998301828 | 39.394000818864 | 0.100114021916 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/smoke-Z2-rp640 | 39.188281265024 | 35.688244934323 | 0.100103931967 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/xr-full-A0 | 20.203639841393 | 20.203620833508 | 0.000041909982 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/xr-full-Z640 | 20.068527756560 | 20.068510681398 | 0.000038157217 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/xr-full-Znative | 19.624418197597 | 19.581670335320 | 0.100117589813 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/xr-tuned-A0 | 30.176650743638 | 30.075635947617 | 0.100170915946 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/xr-tuned-A0-png | 27.547267475106 | 27.463100402195 | 0.100128253922 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/xr-tuned-A0-repeat | 29.985769932169 | 29.886016359548 | 0.100181546994 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/xr-tuned-Z640 | 28.807948566502 | 28.715933470769 | 0.100107431877 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/xr-tuned-Z640-png | 26.138648675214 | 26.062872972049 | 0.100107603706 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/xr-tuned-Z640-repeat | 28.912896042025 | 28.820123448802 | 0.100201627240 | exists=True, metrics equality=[True] |
| zed_live_rgb_episodes/xr-tuned-Znative | 28.613834375856 | 28.523036804981 | 0.100125550758 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/baseline-A0 | 29.856506723590 | 29.757675399863 | 0.100114994217 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/baseline-Z640 | 28.954668460772 | 28.861697681422 | 0.100126379170 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/baseline-repeat-A0 | 29.964484221506 | 29.864905339271 | 0.100147890858 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/baseline-repeat-Z640 | 28.955117652040 | 28.862136512973 | 0.100134460256 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/headless-A0 | 29.875927970868 | 29.776923199809 | 0.100160713308 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/headless-Z640 | 28.955479344852 | 28.862438056987 | 0.100196938030 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/headless-smoke-A0 | 30.177632829542 | 28.057915909502 | 0.100137623027 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/no-report-A0 | 29.803990793699 | 29.705411044038 | 0.100212116260 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/no-report-Z640 | 28.989659009007 | 28.896460890418 | 0.100129464176 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/report-only-A0 | 29.951753890480 | 29.852287300003 | 0.100119776092 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/report-only-Z640 | 28.991640508473 | 28.898368105498 | 0.100195811130 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/reuse-A0 | 30.427894068791 | 30.325226819096 | 0.100137901027 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/reuse-Z640 | 29.226488134364 | 29.131776172012 | 0.100116059184 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/reuse-repeat-A0 | 30.460812846816 | 30.357948904689 | 0.100113295950 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/reuse-repeat-Z640 | 29.177369064687 | 29.082831727539 | 0.100268162321 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/solver4-A0 | 30.145488954509 | 30.044708409701 | 0.100144911092 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/solver4-Z640 | 29.171487414679 | 29.077096967109 | 0.100152302068 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/solver4-repeat-A0 | 30.248175773593 | 30.146741044085 | 0.100112804212 | exists=True, metrics equality=[True] |
| vr_runtime_ablations/solver4-repeat-Z640 | 29.206348420921 | 29.111752192679 | 0.100131500047 | exists=True, metrics equality=[True] |
