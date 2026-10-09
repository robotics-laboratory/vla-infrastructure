# GPU capture/encode для live30 Piper VR — upstream audit

Дата исследования и обращения ко всем внешним источникам: **2026-10-09**. Это исследовательская записка, не зарегистрированное gate evidence. Назначенный checkout `/home/ebulochkin/vla_infrastructure`, ветка `research/live-camera-recording-30hz`, HEAD и merge-base master `beaedfd1116577fd4d8026232cfb96cba0b030fa`; исходный WIP отсутствовал. Чтение локального кода началось с CodeGraph. Прочитаны NORMATIVE_MODEL, README, выбранные INDEX owners, DOCUMENTATION_POLICY, selected VR camera operations/configs. Это приложение [итогового отчёта](REPORT.md); production исходники и environments не изменялись. Этот агент не запускал GPU, Isaac, камеры или физическое оборудование и не устанавливал зависимости.

## Вывод и границы уверенности

Первая кандидатура для минимального custom code — **штатный Replicator renderVar hardware compression**, уже присутствующий в локальном Kit, с маленьким file/metadata sink. Сначала проверить его в фактическом shared RUN/DIAG/RECORD runtime, затем рассматривать PyNvVideoCodec. Собственный C++ CUDA/NVENC узел нужен только после измеренного провала публичных upstream API. Ни документация, ни присутствие исходников не доказывают ≥30 **wall** Hz с тремя live камерами, XR и actions.

**Уточнение пользователя, переданное parent во время исследования:** требуется устойчиво **выше 30 wall Hz при реально активном XR+Quest 3**; ориентир около **50 Hz без Quest**. Результаты 30/40 без Quest не являются достаточными. Следовательно 33.333 ms — верхняя граница среднего physical периода; no-Quest architecture следует проверять на ~20 ms complete row budget.

Замена CPU encode на NVENC не ускорит обязательные CPU/physics/Fabric/XR барьеры. Она помогает только соответствующим частям пути capture→encode→write. Если три live render products уже не укладываются в бюджет, GPU encode не устраняет этот предел. Обратная связь в действующий control loop, частота physics, fresh observation→decision identity и dataset_action должны сохраняться.

## Проверенные локальные версии и текущий путь

- Isaac Sim `6.1.0.0`, Kit `110.3`, Python `3.12.13`, PyTorch CUDA runtime `12.8`, tested driver `580.159.03`: `configs/environments/isaac1103/ENVIRONMENT.yaml`. Это декларации/прошлая квалификация; не новый performance result.
- Локальные extension directories: `omni.replicator.core-1.13.36+110.3.0.lx64.r.cp312`, `omni.replicator.nv-1.1.6+110.3.0.lx64.r.cp312`, `omni.replicator.srtx-1.1.11+110.1.1.lx64.r.cp312`, `omni.videoencoding-0.2.1+00c488ae.lx64.r.cp312`. SRTX использует другую build suffix; ABI/stock provenance надо считать отдельно, а не выводить из одного имени каталога.
- `docs/project/RUN_VR_OPERATIONS.md:64`: три mono ZED X One GS, `960×600`, vendor commit `0164268ca123fa4549fc9d2062c1fd55cf7996dc`. RUN строит ordinary Isaac Lab Camera sensors на authored vendor optical prims; RECORD делает те же prims/CameraCfg, но **не создаёт live sensors/products**. Preview использует native RGBA. Ни ZED SDK, ни vendor streaming graph, ни Sim2Real не включены. Поэтому нынешняя успешная state-only RECORD не является baseline трёх live камер.
- Три raw RGBA кадра: `3×960×600×4=6,912,000` bytes на observation; при 30 Hz — `207,360,000` bytes/s до copies/codec. Это расчёт объёма, не измерение throughput.

## A. Штатный Replicator encode: более высокий reuse tier

Публичный Python API позволяет `AnnotatorRegistry.get_annotator("rgb", init_params={"compression":"h264"})` для RGBA8 renderVars; доступны `h264`, `hevc`/`h265`. `get_data(device="cuda")` даёт Warp, CPU — numpy. Borrowed buffer нельзя удерживать после следующего кадра в async backend без owned copy; для сохранения нужен `get_data(do_array_copy=True)` или copy в собственный slot. Документированный API: [Replicator Python API](https://docs.omniverse.nvidia.com/kit/docs/omni_replicator/latest/source/extensions/omni.replicator.core/docs/API.html). Это `latest`; наличие в проекте дополнительно установлено чтением локальных bytes.

В local `.../omni/replicator/core/scripts/annotators.py:553-764` compression template создаёт C++ `omni.replicator.nv.OgnPostRenderVarHwEncode` в POST_RENDER, связанный с `GpuInteropEntry`, затем ON_DEMAND `SdRenderVarPtr` для чтения compressed renderVar. Никакого собственного Python RGB→YUV encode loop здесь не нужно. `initialize` вынимает compression из kwargs до применения к обычным узлам.

Локальный `ogn/docs/OgnPostRenderVarHwEncode.rst` перечисляет входы только `compression, exec, gpu, outputRenderVar, renderVar, rp`; outputs `exec, renderVar, size` (число encoded bytes). Публично здесь не видны per-instance bitrate, preset, GOP, frame PTS, EOS/flush. RST упоминает AV1, но Python `_register_compression_template` отвергает `av1` при проверке `hw_requested`; нельзя обещать AV1 через этот Python путь. Нижележащая реализация binary C++ не была исходно просмотрена.

Локальные lifecycle caveats:

- `omni.replicator.nv/docs/CHANGELOG.md` 1.1.0, 2026-02-05: каждый `RepNvEncSession.cpp` output принудительно IDR с SPS/PPS, независимо декодируемый. Это может упростить exact frame sink и tail-finalization, но фактический first/last кадр всё равно надо декодировать.
- 1.1.5, 2026-08-27: освобождение hardware encoder sessions при detach, устранение exhaustion на repeated RTSP attach/detach. Установленная 1.1.6 содержит фикс.
- core 1.13.31 фиксирует остаточные USD specs после stop/play compressed-image pipeline. Проба должна покрывать несколько Start/Stop/reset/close, а не один warmup.

### Самый конкретный upstream пример: RTSPStreamWriter / SRTX

В установленном `isaacsim.streaming.rtsp/.../impl/rtsp_writer.py` upstream writer просит `LdrColor` с compression h264 и `IsaacReadSimulationTime`. `_push_encoded_frame` документирует **одномерный numpy uint8 bitstream**, делает `.tobytes()`, пропускает пустой warmup и передаёт готовые bytes серверу без повторного encode. Его можно использовать как образец захвата в маленьком локальном writer; открывать RTSP сервер для dataset sink не обязательно.

`ensure_render_var_on_product(stage, rp, "LdrColor", "h264")` перед attach author-ит child RenderVar, sourceName, `srtx:compression:type` и `orderedVars`. SRTX Annotator `compressed_shape`, `compressed_format`, `compression` сохраняют original image metadata; compressed output — flat uint8. Проверять, какой factory фактически вернул annotator: core и SRTX — разные пути. Документация конкретного подхода: [Isaac Sim RTSP camera streaming](https://docs.isaacsim.omniverse.nvidia.com/latest/digital_twin/rtsp_camera_streaming.html), last updated 2026-09-18.

RTSP writer сам по себе не удовлетворяет dataset contract. Он увеличивает frame counter до проверки пустого packet, формирует wall timestamp как server anchor + sim time, при ошибке останавливает сервер и затем молча пропускает кадры до restart. Это **не фактический host_monotonic acquisition timestamp** и не fail-closed dataset continuity. Для записи нужны собственные obs_id, camera role/prim, sim frame identity и реальный host capture interval, explicit packet/frame accounting, persistent first/last decode validation. У upstream RTSP SEI только sim time / anchored timestamp / frame number; dataset action туда не интегрирован.

`LdrColor` SRTX helpers — promising candidate, но не автоматическая замена существующего Isaac Lab sensor. Если создаётся ещё render product вместо присоединения к существующему, получится duplicate rendering и другой camera cadence. Требуется reuse существующих products, проверка полного набора roles, разрешений, optical matrices и task-camera quality.

## B. PyNvVideoCodec — управляемый GPU encoder fallback

Текущие docs — PyNvVideoCodec `2.2`, Python x86_64 wheels включают 3.12. NVIDIA называет библиотеку официально поддерживаемым наследником VPF: [Product overview](https://developer.nvidia.com/pynvvideocodec), [System requirements](https://docs.nvidia.com/video-technologies/pynvvideocodec/read-me/system-requirements-common.html). CUDA Toolkit requirement в latest описан как latest, а не доказанная совместимость именно с frozen CUDA12.8 Isaac environment. Пиновать wheel/source/version/SDK ABI и смотреть реальные dependencies до установки; `pip install` в production здесь не выполнен и не предлагается как безрисковая операция.

Конкретная форма documented API: `CreateEncoder(width, height, fmt, usecpuinputbuffer=False, codec="h264", gpu_id=0, cudacontext=..., cudastream=..., preset="p1", tuning_info="low_latency", fps=30, bf=0, gop=30, bitrate=...)`, затем `Encode(frame)` и обязательно `EndEncode()`. Formats включают NV12, ARGB/ABGR; **RGBA как fmt имя не обещано**. Требуется контроль byte channel ordering и color range тестом цветных патчей. Encode возвращает bytes, возможны несколько packets за один вызов: количество calls не равно количеству decoded frames. API: [Encoder reference](https://docs.nvidia.com/video-technologies/pynvvideocodec/pynvc-api-reference/encoder.html), updated 2026-07-29.

GPU input producer документируется через `frame.cuda()` с CUDA Array Interface для planes; простой Warp object нельзя без проверки объявить прямым допустимым Encode argument. Numpy/torch `.cpu().numpy()` возвращает CPU путь и теряет смысл GPU transport. Необходим owned device buffer и согласованный producer stream/event. Guide сам расходится в keyword `format` против API `fmt`; использовать positional arguments в feasibility probe, не переносить пример вслепую. [Programming guide](https://docs.nvidia.com/video-technologies/pynvvideocodec/pynvc-api-prog-guide/using_pynvvideocodec_apis.html).

Вариант минимального adapter: 3 encoder instances и ограниченное число owned CUDA slots на роль, GPU D2D copy на capture boundary, затем encode/file write на dedicated worker, file+frame index join через immutable obs_id. Один encoder per camera упрощает role continuity; atlas одного encoder меняет dataset decoder/layout и нуждается в отдельном обосновании. Не создавать новую RPC архитектуру только из-за dependency conflict: согласовать environment pins или предпочесть stock Kit encoder.

## C. Что фактически делает ZED upstream

Публичный main на день исследования равен **проектному pin** `0164268ca123fa4549fc9d2062c1fd55cf7996dc`. Core extension `5.2.1`, target Kit `110.1.2` (VERSION.md и config/extension.toml). Source snapshot в `/tmp/zed-upstream`; core .py/.cpp/.h/.ogn inventory прочитан/проверен текстовым поиском. Literal `send_image`/`sendImage` в этой core source inventory **не найден**. Это не API записи в данном pinned code; нельзя объяснять dataset путь несуществующим здесь вызовом. Возможный одноимённый вызов другого SDK/версии не исследован.

Primary source: [OgnZEDSimCameraNode.cpp pinned](https://github.com/stereolabs/zed-isaac-sim/blob/0164268ca123fa4549fc9d2062c1fd55cf7996dc/exts/sl.sensor.camera/plugins/nodes/OgnZEDSimCameraNode.cpp).

- `FramePipeline:103-190` — три slots: один consumer, один pending, один producer. `publish` заменяет pending на новый и возвращает старый slot в free pool. **Newest-wins drop**, а не гарантированная запись каждого кадра. Нет discard accounting, пригодного для нашего D0, в этом классе.
- Buffers — pinned host через `cudaMallocHost` по умолчанию; device через `cudaMalloc` только при `m_gpu_input`.
- `compute:630-647`: `use_yuv = transport_layer_mode > 0 || !m_stereo_camera`; `m_gpu_input = m_stereo_camera && !use_yuv`. Поэтому **моно всегда host**, независимо от CUDA annotator; IPC/YUV также host. Только stereo BGR network может остаться GPU.
- Producer копирует D2D либо D2H из annotator в owned slot. После `cudaMemcpyAsync` вызывает `cudaStreamSynchronize` (`:874`), затем публикует. Encode/send offloaded на thread, но barrier на render/compute thread остался.
- Consumer `:393-423` вызывает `m_zedStreamer.stream(...)` либо `streamLeftAndDepth(...)`. Это opaque runtime lib и streaming API; native disk recorder / actions / obs_id не реализованы здесь.
- De-dup по `simulationTime` с steady fallback при time≤0. External timestamp — system-clock anchor первого кадра + sim delta; это не измеренная wall arrival latency.
- Destructor сначала stop+join consumer, затем освобождение slot buffers/streamer/CUDA stream. Перенос этих slots требует сохранить ownership и lifecycle, включая exceptional paths.

SDK-free Isaac Lab recording example `[zed_record_demos.py](https://github.com/stereolabs/zed-isaac-sim/blob/0164268ca123fa4549fc9d2062c1fd55cf7996dc/exts/sl.sensor.camera/examples/isaaclab/zed_record_demos.py)` идёт другим путём: authored CameraCfg, ordinary Camera tensors, ObservationTerm `mdp.image`, `ActionStateRecorderManagerCfg`, `env.step(actions)`, success-only HDF export. Он удаляет static table camera, оставляет wrist left/right/depth, использует keyboard teleop и rate limiter. Default desired step_hz — не measured sustained throughput. Копирование этого recorder не сохраняет наши три roles, action semantics, human failure/incomplete episodes или temporality. `isaaclab_utils.unwrap_output` лишь unwrap ProxyArray `.torch`; warmup polling проверяет cameras[0], не три независимых readiness proofs.

## D. RTX/Fabric/tiled: менять только измеренный bottleneck

[Multi-tick rendering](https://docs.isaacsim.omniverse.nvidia.com/latest/sensors/isaacsim_sensors_multitick_rendering.html): в 6.0+ sensors могут render-иться независимо по `OmniSensorAPI`/`omni:sensor:tickRate`; `0` — autotrigger every renderer frame. Это scheduler rate в simulation domain, не 30 wall Hz гарантия. Если обновлять CameraCfg period, убедиться, что это реально сокращает GPU render products, а не лишь sensor readout. Проверить три camera frame identities: не отдаёт ли повтор прошлого изображения при новых actions.

[Camera Sensors](https://docs.isaacsim.omniverse.nvidia.com/latest/sensors/isaacsim_sensors_camera.html): `TiledCameraSensor` объединяет cameras в один tiled product; docs рекомендуют для batched workflows. Для трёх одинаковых разрешений это кандидат сокращения per-product overhead, но выигрыш для **трёх** камер не известен. Требуется проверить vendor lens schemas, authored optical pose, tile mapping/crops, dimensions, BG pixels и multiple roles. Не подменять authored ZED optics pinhole spawn. Native tiled product либо shader pass можно исследовать после separate-products baseline.

[Performance Handbook](https://docs.isaacsim.omniverse.nvidia.com/latest/reference_material/sim_performance_optimization_handbook.html) содержит settings для asyncRendering/LowLatency/Handshake/Replicator async и совет отключать лишние renderer passes. Отключение physics→Fabric output допустимо в workload без cameras/XR; наш workload к нему не относится. Async flags могут сдвинуть obs_t относительно physics/action; применять только после explicit frame-provenance protocol, и каждый settings variant отдельной измеренной пробой. Multi-GPU не является первым шагом для единственного RTX4090 и не ускоряет весь physics pipeline.

## E. Если понадобится C++ GPU ring

Это условный дизайн, **не upstream feature и не implemented result**. Минимальный узел сохраняет per-role renderVars, копирует в заранее выделенный owned CUDA slot (или удерживает GPU resource до готовности encode), пишет CUDA event и immutable frame metadata. Consumer ждёт этот event, вызывает NVENC и сохраняет bitstream. Не делать `cudaDeviceSynchronize` всего процесса; event synchronization допустимо только при доказанном upstream producer stream ordering. Простое удаление ZED `cudaStreamSynchronize` без удержания borrowed annotator buffer создаёт data race.

Для Linux NVENC API output path synchronous; event-based encode async поддержан Windows WDDM. Поэтому NVENC blocking lockbitstream/read/flush нужно держать на worker. CUDA events для producer-copy completion всё равно применимы и не тождественны NVENC Windows events. Документированный external-resource flow — register→map→encode→unmap→unregister, EOS `NV_ENC_PIC_FLAG_EOS`, input resources нельзя освобождать до завершения обработки. [NVENC SDK 13.0 Programming Guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/).

Ring не делает медленного consumer быстрым: при sustained deficit occupancy растёт до capacity. Dataset mode обязан fail-close/mark incomplete при overflow, а не newest-wins; preview может иметь другую dropout policy, явную и наблюдаемую. Capacity рассчитывается из измеренной worst-case write latency и ограниченного памяти бюджета. Простые функции и один owned worker предпочтительнее generic transport/storage framework. Для 3 roles×3 RGBA slots чистый pixel pool 20,736,000 bytes, без encoder allocations; это расчёт, не allocation probe.

[NVENC application note](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-application-note/index.html) описывает dedicated hardware engines, нагрузку multiple sessions и лимит 8 sessions для non-qualified GPUs. Три camera sessions + XR/livestream sessions следует учитывать совместно. Табличные FPS NVIDIA — codec microbenchmark, не Piper VR FPS; никаких чисел expected wall Hz отсюда не выводим.

## E2. Самые быстрые архитектуры: strict same-boundary против pipeline и GPU isolation

Локальная штатная experience `apps/isaacsim.exp.base.zero_delay.kit` (version6.1.0) включает `rtx.spg.enabled=true`, `app.hydraEngine.waitIdle=true`, `app.updateOrder.checkForHydraRenderComplete=1000`, и отключает queued/multithreaded ROS2 publish. Это concrete native **same-frame correctness candidate**. `waitIdle` явно добавляет обязательное ожидание; имя zero_delay не означает максимальный throughput. XR compatibility этой experience и сохранение IsaacTeleop/CloudXR settings не проверены. Нельзя просто заменить selected XR experience и считать control stack сохранённым. Сравнить один и тот же runtime с settings override и registered temporal proof; no-XR correctness microprobe полезен, но не выполняет пользовательскую цель.

Для single-GPU быстрого варианта: three existing products → native POST_RENDER NVENC → owned compressed packet sink; минимизировать raw D2H, runtime copies, лишние render/update циклы и encoding waits в Python main. Если допускается bounded render pipeline delay, asynchronous render может перекрывать physics/control с cameras, но row identity должен ссылаться на **original capture generation**. Нельзя выдавать camera N−1 как свежую observation N; такая схема потребует явной поддержанной temporal policy и pre-observation scheduling, а не косметической смены timestamp.

Для dual-GPU быстрого варианта: **GPU0 physics + XR, GPU1 три camera render products + encode** внутри того же процесса/declared environment. Local `ViewportManager.optimize_render_products()` документирован и implemented в `isaacsim.core.rendering_manager/.../impl/viewport_manager.py:416`: author-ит `uint[] deviceIds` в USD session layer, распределяет eligible non-viewport camera products по active GPUs, учитывает viewport loads только при существующих valid deviceIds. Алгоритм **балансирует** камеры; не гарантирует изоляцию всех камер на GPU1 и не фиксирует CloudXR/XR placement. Для exact isolation использовать тот же документированный `deviceIds` USD property на собственных camera products с `[1]`, отдельно доказав renderer device-index↔physical GPU mapping, XR placement и native encode context. Это proposal, не выполненная настройка. Не использовать private method как public API.

Этот вариант может уменьшить конкуренцию RTX камер с XR и NVENC, но увеличивает scene replication/VRAM и добавляет GPU interop/CPU handshake. Сохранять raw textures и owned encoder slots на **GPU1**, возвращать в CPU лишь compressed bytes: иначе cross-GPU transfer съест выигрыш. Native physics→Fabric→renderer shared scene остаётся одной актуальной сценой. Новый независимый process-renderer с пересылкой state имеет дополнительные world synchronization/causality расходы и не соответствует minimum-custom-code first candidate. До закупки GPU нужны измерения main-thread/renderer bottleneck; fixed CPU physics/XR waits не снимаются вторым GPU.

`SPGNode`/`RtxCamera.author_spg` — supported authoring API custom CUDA `.cu` + `.cu.lua` + USD shader внутри RenderProduct. SPG обеспечивает GPU postprocessing AOVs без CPU-side transfer **внутри SPG pipeline**, но сам не реализует recorder worker, ring lifetime, frame schedule или multiprocessing. Удобен для measured color conversion/packing/crop/atlas, если штатный encoder не принимает нужный buffer; он не обещает ускорение обычного RTX render. Source: [Isaac Sim6.1 API](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/py/source/extensions/isaacsim.sensors.experimental.rtx/docs/index.html), [SPG0.2 overview](https://docs.omniverse.nvidia.com/kit/docs/omni.rtx.spg/0.2.0/Overview.html).

Ещё local high-level CameraSensor caveats: constructor вызывает `enforce_square_pixels(resolution,modes="horizontal")` на wrapped authored camera. Это может изменить optical aperture; сравнивать authored optics before/after. `CameraSensor.get_data('rgb')` проверяет `data.size == H*W*input_channels` и reshape в image; compressed bytes сюда не подходят, хотя `annotator_init_params` принимает compression. Поэтому packet sink должен читать underlying/public Annotator, не слепо проходить через CameraSensor RGB convenience getter. Pre-authored render products могут быть reused через existing camera relationship; проверить, что путь не fallback-ит к duplicate product.

## F. Ещё один stock API: omni.videoencoding

Установленный `video_encoding.IVideoEncoding` имеет `start_encoding(filename, framerate, nframes, overwrite)`, `encode_next_frame_from_buffer(buffer_rgba8, width, height)`, `finalize_encoding`. Это готовый MP4 sink, **Python buffer** RGBA8 path: публичного CUDA pointer input и нескольких независимых encoder handles в API не видно. Singleton interface нельзя без runtime proof считать 3-camera-safe. Поэтому это low-custom fallback при уже допустимом CPU readback, не доказанный zero-copy GPU route. [IVideoEncoding reference](https://docs.omniverse.nvidia.com/kit/docs/omni.videoencoding/latest/video_encoding/video_encoding.IVideoEncoding.html).

Local extension config показывает bitrate, framerate, iframeinterval, preset P1-P7, rcMode, profile и fullRange global settings. Документация [settings](https://docs.omniverse.nvidia.com/kit/docs/omni.videoencoding/latest/SETTINGS.html) — 0.2.2, local 0.2.1. Не предполагать, что эти keys управляют **Replicator NVENC**: связь в просмотренных Python files не установлена.

## Предлагаемый порядок проверки и критерии

1. Micro-feasibility stock compressed rgb и stock compressed LdrColor/SRTX на pinned local extension bytes: request→nonempty uint8 packet→decode known color/geometry witness; verify source/packet identity. Результаты отдельных probes приведены в [отчёте](REPORT.md); эти API сами по себе не устанавливают correctness.
2. Shared live runtime baseline: три native ZED cameras одновременно, actions, XR/preview или честно отмеченный headless approximation; no compression/file I/O. Измерять wall duration/frame, fresh triplets rate, render/readout, physics, XR resolution, control age. Уже здесь установить whether 33.33 ms feasible.
3. Добавить encode только, затем durable write/finalize; отдельно сравнить CPU readback, GPU owned-copy и native post-render compression. Warmup/cold shader time вне sustained window, но сохранить оба.
4. **>30 wall-Hz active Quest 3/XR**, и отдельно **около 50 no-Quest**, считать по **fresh complete 3-camera/action rows**, не process updates, номинальному fps и timestamp denominator. Сохранить p50/p95/p99, max interval, dropped/duplicate/incomplete count, queue high-water, memory trend и final decoded per-role cardinality. Долгий bounded stress плюс pause/Start/Stop/save/discard/reset/Ctrl-C и storage slow/failure injection.
5. Динамический witness должен отвергнуть N−1, wrong role и неправильный camera pose. Lossy codec требует явной color/quality policy и decoder test; H264≠canonical raw RGB lossless guarantee. Labels source→processors→dataset_action сохраняются отдельно от accepted/executed commands.

PASS API packet+decode не PASS full runtime Hz; PASS headless не PASS Quest XR latency; automated correctness не physical S2; recorded videos не D1 admission. Любой held/buffered кадр обязан нести original capture obs_id, а не присваиваться времени позднего write.

## Rollback для низкоуровневых изменений

- Каждый вариант opt-in в существующем shared base, never copy RUN/DIAG/RECORD implementations; diagnostic observer не меняет action/control state.
- До включения: snapshot source commit/config digests, все mutated Carb settings, extension selection и upstream source hashes. Не patch-ить production SDK/site-packages inplace; если upstream patch нужен, isolated overlay + declared artifact/pin.
- На failure: закрыть admission нового capture, отметить незавершённый episode, прекратить consumer, дождаться owned in-flight buffers, flush/destroy encoder, detach annotators, destroy только созданные products, удалить добавленные owned RenderVars и восстановить settings/schema attrs. Не удалять camera USD optics/state snapshot.
- При rollback снять opt-in selection и вернуться к прежнему zero-live-products snapshot recording; сохранять все failure traces/partial video locators без маркировки finalized. Остальная recording lifecycle/label chain должна остаться проверяемой.
- GPU resource/session leak, stale/duplicate role, overflow, последняя строка без successor/packet, source timing mismatch — основания не продвигать variant. Ручной physical тест только с явной точной авторизацией.

## Provenance bytes и неизвестное

Local bytes hashes, **без подтверждения stock wheel integrity**:

- `omni.replicator.core/.../scripts/annotators.py`: SHA256 `d663acd21268b9092becd6b2b542e843323ec609995020519b8daf7fffdf1c6f`.
- `omni.replicator.nv/.../ogn/docs/OgnPostRenderVarHwEncode.rst`: `f10ddc6758011397e0f2edc39ab81893746143119646961e264cf0776e71edde`.
- `isaacsim.streaming.rtsp/.../impl/rtsp_writer.py`: `1b25f246a804cb03416376b1c676f8b96b04e23020e84566ca14a2d4c0743a8c`.
- pinned downloaded `OgnZEDSimCameraNode.cpp`: `c05d852efadb4e4251c81a7df2fa4f484e72fcb0033ed835c8defea2cc214565`.

Неизвестны: full-runtime 30-Hz performance; stock-vs-local SDK modifications; native encoder params/PTS/EOS internals; borrowed lifetime under every selected sensor backend; exact SRTX overhead/state synchronization; PyNvVideoCodec wheel ABI with frozen Isaac deps; end-to-end codec colors/geometry; device ownership across exceptional shutdown; actual combined XR/NVENC session pressure. Они разрешаются probes, а не общими claims NVENC throughput.

## Дополнение: producer Writer для probing, 2026-10-09

Parent сообщил о native packet throughput probes с decode witness lag−2 и role-dependent lag. Эти результаты этим агентом не выполнялись/не проверялись; одни rates не являются temporal PASS. Подготовлен [native_packet_writer.py](native_packet_writer.py): concrete `rep.Writer`, structured `data_structure='renderProduct'`, один callback принимает три existing RP, writes owned compressed bytes в per-role H264 и JSONL offsets/hash/metadata. Проверен только Python syntax через `compile()`, без Isaac imports/GPU runs. Около150 строк с явными guards; это probe helper, не dataset integration.

Exact installed core callback payload: top `reference_time=(num,den)`, `swhFrameNumber=0` deprecated; `renderProducts[rp_basename]` содержит `camera`, `resolution=(W,H)`, `LdrColor`, `IsaacReadSimulationTime` dict. RP basenames должны быть уникальны. Нет public independently stamped renderer generation ID в этих полях. Helper сохраняет `renderer_source_frame_id=null`/`capture_alignment_proven=false`; callback monotonic timestamp не masquerade-ится как acquisition timestamp. Warmup empties bounded; subsequent empties/repeated reference times/file failure сохраняют failure, `writer.check()` должен опрашиваться main loop.

SRTX writer **не просто on-every-render subscriber**: installed `srtx_hooks.py` attaches observer на `ORCHESTRATOR_EVENT`, ключ `capture`, вызывает request_capture_frames, собирает completed sensor sets и cached outputs. Simulation-time core annotator читается в позднем `_finish_capture`; он не independently proves original image time. Поэтому SRTX Writer с одним `app.update()` может вообще не доставить callbacks без capture events; native core non-SRTX writer имеет default OnFrame dispatch. Не превращать direct callback файл в performance/causality claim. Следующий probe должен выбрать capture_on_play/actual orchestrator drive, доказать decode witness/source alignment и проверить долгую bounded сцену.

Проверки этого агента: read-only source/document audit, public GitHub snapshot fetch, exact text/search/hash verification. Repo tests/lint не запускались, поскольку repo source/docs не изменены; parent делает итоговую governance регистрацию/валидацию своей deliverable. Это приложение зарегистрировано в INDEX как experiment, а не как gate evidence.
