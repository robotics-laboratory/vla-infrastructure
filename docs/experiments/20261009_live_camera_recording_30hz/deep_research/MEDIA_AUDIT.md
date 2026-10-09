# NVIDIA media landscape для Piper live RGB: дополнение к upstream audit

Дата доступа ко всем внешним источникам: **2026-10-09**. Исследование read-only; GPU, Quest, encoder creation, установки и изменения SDK/environment не выполнялись. Checkout при начале дополнения: `research/live-camera-recording-30hz`, HEAD `d5566834d29ef8bb56e4fb62bb324e23e0869100`, WIP пуст. Нормативные ограничения и текущие camera owners прочитаны в предыдущем audit `/tmp/live30-gpu.md`. Этот файл — временное исследование, не зарегистрированное gate evidence и не квалификация dataset/physical S2.

## Вывод для следующего эксперимента

Самая короткая интеграция остаётся **existing RenderProducts → stock compressed LdrColor → producer Writer → owned packet bytes**, потому что encoder, RGBA interop и ABI уже входят в installed Kit. Writer надо сравнить с polling `get_data()` на одном retained Piper snapshot. Orchestrator — отдельный эксперимент: у SRTX Writer capture инициируется событиями orchestrator; простые `app.update()` могут вообще не доставлять SRTX callbacks. CPU raw → FFmpeg workers доступен без установки и позволяет вынести encode с Kit main thread, но добавляет D2H/pipe/H2D. Собственный CUDA → PyNvVideoCodec worker перспективен для контроля GOP и очередей, однако пакет отсутствует, поэтому это следующий интеграционный этап, а не готовая замена.

Цель пользователя: **строго >30 wall Hz с активным XR + Quest 3**, ориентир около **50 wall Hz без Quest**. Разрешён небольшой лаг кадров: он должен быть ограничен, измерен и отражён в provenance. Лаг не разрешает приписывать старым pixels текущий `obs_t/action_t`; требуется history lookup по источнику кадра. Рендер и encode по отдельности не доказывают цель.

| Кандидат | Что уже существует | Основная проверка/ограничение | Приоритет |
|---|---|---|---|
| Native compressed Writer | Kit stock API + `/tmp/live30-native-writer.py` | producer callbacks, long-run loss, per-camera source phase; SRTX scheduler | 1 |
| Raw CPU + три FFmpeg NVENC процесса | `/usr/bin/ffmpeg` 4.4.2 и `/tmp/live30-ffmpeg-workers.py` | D2H/H2D, pipe stalls, decode count/lag, качество | 2, baseline |
| CUDA raw → bundled Kit RTSP encoder → custom tee/filesink | installed RTSP plugin + Python CUDA pointer API | network/client lifecycle, buffer ownership, BGRA layout, EOS | 3, существующий ABI |
| Raw Warp CUDA → PyNvVideoCodec encoder worker | официальный современный API | **не установлен**, CUDA context/stream/GIL/packets; отдельный env review | 4 |
| SDK NvEncoderCuda минимальный C++ worker | upstream CUDA reference implementation | build/plugin ABI, owned rings, output thread; больше custom code | 5 |
| Gst nvcodec 1.24+/DeepStream/NITROS/Holoscan | готовые upstream components | новый runtime/transport, не camera renderer и не автоматически recorder | только при конкретном выигрышном witness |
| Vulkan direct texture interop | CUDA official samples | Kit RpResource export API не найден; ресурс scope/fences | низкий до появления supported export |

## 1. Фактическая доступность и ABI

Declared Isaac environment — Python 3.12, Isaac Sim 6.1.0.0 / Kit110.3, PyTorch CUDA12.8, tested driver580.159.03. GPU scheduling принадлежит parent. Файловая проверка подтверждает Warp1.16.0, Replicator core1.13.36+110.3, replicator.nv1.1.6, replicator.srtx1.1.11, hydra_texture1.6.2, videoencoding0.2.1, livestream.core10.4.0, livestream.rtsp10.4.1. Чтение installed source **не доказывает неизменность относительно stock wheel**: публичный `.latest` и локальный package могут отличаться, нужна сверка artifact hash с declared wheel при принятии реализации.

В top-level site-packages не обнаружены PyNvVideoCodec, PyNvCodec/VPF, PyCUDA, CVCUDA/nvcv, Holoscan. CuPy есть внутри `isaacsim.ucx.core/pip_prebundle`, не как ordinary top-level package. Это не разрешение включать extension или менять sys.path в рабочем environment.

System FFmpeg `4.4.2-0ubuntu0.22.04.1` перечисляет h264_nvenc и hevc_nvenc, но не av1_nvenc. CPU-only `-h encoder=h264_nvenc` подтверждает p1…p7, tune ll/ull, lookahead, bf, multipass, delay, zerolatency, gpu ordinal, raw packed RGB0/BGR0 и CUDA input formats. **Наличие encoder в build не доказывает успешную загрузку libnvidia-encode и GPU session**; здесь encode не запускался.

System GStreamer1.20.3 не содержит найденного nvcodec plugin binary в `/usr/lib/x86_64-linux-gnu/gstreamer-1.0`. Но installed Kit RTSP содержит **собственную GStreamer runtime1.24.12** (`*.so.0.2412.0`) и **encoder-only `libgstnvenc.so` из адаптированных upstream~1.20 sources**. Это существенное уточнение: нельзя смешивать system `gst-inspect`1.20 с Kit library/plugins1.24 и считать их одной проверенной ABI.

Local hash ledger:

| Installed file | SHA256 |
|---|---|
| RTSP `PACKAGE-LICENSES/dependencies/gstnvenc-source.tar.gz` | `8dd256f2f81c1c51c1fbf56fafed526e339f28bffff6151002ea099b94e41f45` |
| RTSP `bin/plugins/libgstnvenc.so` | `06c8ae3581bdf8187189e954a06b5d935761eeca42f33da66fa11b8804bb3b25` |
| hydra_texture1.6.2 `config/python_api.md` | `d5871e19d2e6264865a71759646fd812021de85917331e3dd7725fd8036646ba` |
| gpu_foundation `config/python_api.md` | `fd13f094b902b55335f5eff2719d91530fa561dde25f6764ad3c1973953f89d2` |

## 2. Native media: убрать polling race раньше собственного encoder

Stock Replicator поддерживает `AnnotatorRegistry.get_annotator("LdrColor", init_params={"compression":"h264"})`; аппаратный encode встроен в POST_RENDER graph. Можно attach existing RP. API компрессии не предоставляет per-session preset, GOP, bitrate или явный EOS. NV extension changelog1.1.0 требует IDR+headers на каждом кадре; это удобно для независимого decode, но не должно считаться наиболее экономным режимом записи. В1.1.5 исправлена утечка encoder sessions при detach. [Replicator API](https://docs.omniverse.nvidia.com/kit/docs/omni_replicator/1.13.30/source/extensions/omni.replicator.core/docs/API.html).

`/tmp/live30-native-writer.py` — конкретный producer sink, подготовленный ранее, syntax-only проверка. Он пишет три Annex-B streams и offset/hash/metadata, не объявляет pixel alignment. Рекомендуемая пара опытов: core Writer OnFrame с SRTX выключенным в session-only config; SRTX Writer с `orchestrator.step/step_async`, поскольку installed hook подписан на `ORCHESTRATOR_EVENT`. Смешивание scheduler вариантов при сравнении приведёт к неверному объяснению производительности. Нельзя создавать дополнительные продукты или CameraSensor, который меняет authored aperture, поверх existing3RPs.

Parent сообщил 102.225Hz pureUSD cube app.update, но decoded source phase−2 на всех3; orchestrator52.149Hz с phases−1/0/0; retained Piper pureUSD longrun failed empty на2071 после120warm. Эти числа не проверены этим memo по первичным output artifacts и не являются XR результатом. Они уже показывают, что polling callback time не равен capture source time. Для разрешённого малого лага полезнее измерять очередь/phase, чем требовать глобальный `waitIdle` после каждого app.update.

Есть ещё stock producer interface `omni.kit.hydra_texture`: GLOBAL_EVENT_DRAWABLE_CHANGED с `result_handle`, `get_frame_info(handle)`, `get_aov_info(handle,"LdrColor",include_texture=True)`, `get_drawable_resource(handle,...)`; `set_render_product_path(existingRP,keep_camera=True,keep_resolution=True)` позволяет проверить binding к уже существующему продукту. Локальные tests проверяют `frame_number`, view/projection/device_mask; более старые официальные docs дополнительно описывают optional `swh_frame_number` и subframe_count. Это **кандидат измерителя renderer completion**, ещё не доказанный action label identity. [Hydra overview](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.hydra_texture/latest/Overview.html), [frame-info API](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.hydra_texture/1.4.1/omni.kit.hydra_texture/omni.kit.hydra_texture.IHydraTexture.html).

`RpResource` должен потребляться внутри callback либо downstream owner должен удерживать GPU texture reference. Python public class `RpResource` в installed gpu_foundation API не имеет методов CUDA pointer/Vulkan FD export. Поэтому нельзя подменять его opaque object адресом CUDA buffer. Высокоуровневый viewport capture отдаёт callback/future; это capture API, а не подтверждённый CUDA encode path. [Viewport capture](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.viewport.utility/latest/omni.kit.viewport.utility/omni.kit.viewport.utility.capture_viewport_to_buffer.html).

## 3. FFmpeg baseline, который можно запустить без установки

Подготовлен `/tmp/live30-ffmpeg-workers.py`: import не запускает subprocess; создание `FFmpegTripleEncoder` явно стартует3 `/usr/bin/ffmpeg`; bounded queue хранит owned CPU RGBA triplets, feeder thread пишет три pipe, NVENC процессы encode параллельно. Queue overflow/worker failure/early process exit завершают probe; `finish()` drain→stdin EOF→wait. Sidecar считает **input**, не decoded frames. Разрушающий GPU run не выполнялся; только `compile()` PASS.

Default packed mode трактует тот же RGBA8 байтовый layout как RGB0, игнорируя alpha, и отдаёт RGB0 прямо NVENC. Matching FFmpeg4.4.2 source содержит native ABGR/ARGB mapping для packed formats; это позволяет избежать CPU planar YUV preprocessing. `packed_rgb=False` — контрольный RGBA→CPUYUV420 вариант. Проверить color patches после decode, range/primaries, разрешение и chroma format. Worker сохраняет копию CPU input: D2H остаётся в producer, затем pipe+H2D; этот путь **не GPU zero-copy**. [Matching FFmpeg source](https://github.com/FFmpeg/FFmpeg/blob/n4.4.2/libavcodec/nvenc.c).

Настройки speed baseline (поддерживаются локальным `-h`, GPU execution пока unknown):

```text
-c:v h264_nvenc -gpu 0 -preset p1 -tune ull -bf 0
-rc-lookahead 0 -multipass disabled -zerolatency 1 -delay 0
-rc vbr -b:v 16M -g 50
```

Сначала сравнить GOP1 и GOP50 при одной scene/quality witness. `-g50` число между keyframes, не доказательство IDR каждого50; принудительные IDR/headers и random seek проверять bitstream parser. 16M — стартовый parameter, не утверждение достаточного качества. Сохранить stdout/stderr/exit statuses и измерить full drain. FPS container tag задаёт playback, не делает producer50Hz. Клиент `pipe:0` не принимает CUDA pointer; GPU input к FFmpeg требует AVHWFramesContext/AVFrame reference, C/C++ binding или иной настоящий interop, не `data_ptr()` сериализации. [NVIDIA FFmpeg guidance](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html).

## 4. Уже установленный RTSP CUDA ABI: необычный shortcut

Installed `omni.kit.livestream.core` поддерживает Python:

```python
from omni.kit.livestream.core import Server, ServerConfig, VideoCodec
server = Server("rtsp")  # corresponding extension must already be enabled
ok = server.start(ServerConfig(width=960, height=600, target_fps=50,
    stream_port=8554, video_pre_encode=VideoCodec.NONE))
# After validated producer completion and owned BGRA buffer lifetime:
ok = server.stream_video_cuda_buffer_timed(ptr, pitch, 960, 600, begin_ns, end_ns)
server.stop()
server.close()
```

API принимает **BGRA8**, не RGBA8. Проверка shape без проверки каналов даст красный/синий swap. `_with_metadata` есть для CUDA и preencoded. Return True означает stream API acceptance, не disk durable acknowledgement. Python source реально возвращает bool, lifecycle failures могут не throw. [Core API](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.livestream.core/latest/Overview.html).

ServerConfig имеет `rtsp_pipeline` и `video_pre_encode=VideoCodec.CUSTOM`. Custom pipeline должен иметь `appsrc name=source` и payloader `pay0`; теоретически можно добавить `tee` и `filesink` к encoded leg, минуя отдельный RTSP recorder receiver. Но pipeline создаётся при client connect, timing/metadata semantics, transfer of ownership и EOS/drain ещё неизвестны. Нельзя считать API self-contained disk recorder. Default pipeline queue2 предназначен jitter streaming. [RTSP implementation docs](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.livestream.rtsp/latest/Overview.html).

Самое полезное: installed LGPL source archive позволяет проверить настоящий encoder. Он скопирован для анализа в `/tmp/live30-media-upstream/gstnvenc` без записи в extension. `gstnvbaseenc.c`:

- `cuda-device-id` writable в **этом bundled plugin**. Current official nvh264enc docs показывают read-only — ещё один version trap.
- Preset значения `low-latency-hp`, `hp`, `low-latency`, etc.; **не `p1`**. В архиве mapping low-latency-hp→P2+LOW_LATENCY, low-latency→P3. Есть comments про R590 GUID migration: hash сохранить и wheel provenance проверить; нельзя объявлять это upstream1.20 без patches.
- CUDA context создаётся/передаётся через GstContext; свой CUstream. Upload routine всегда копирует2D into owned encoder input, в device mode **D2D**, затем `CuStreamSynchronize`. Это меньше raw host transfers, но не pointer alias/no-copy.
- Отдельный bitstream thread, pending/available queues и NVENC input/output timestamps; `finish` drain существует. Старое memory layer не содержит public `gst_cuda_allocator_alloc_wrapped` нового Gst1.24.

Произвольный `ctypes` запуск GStreamer parse/PLAYING и callback возможен с installed C ABI, но потребует точного GObject signatures/GstVideoInfo layout/GstBuffer lifetime. Это больше custom code, чем Writer; не подготовлен как production adapter. Если native Writer longrun проходит, делать такую интеграцию не оправдано.

## 5. PyNvVideoCodec и NVENC SDK

PyNvVideoCodec2.2 — поддерживаемый современный successor VPF. `CreateEncoder(960,600,"ABGR",False,cudacontext=ctx,cudastream=stream,gpu_id=0,codec="h264",preset="p1",tuning_info="ultra_low_latency",bf=0,gop=50,fps=50,bitrate="16M",rc="vbr")`; `Encode(frame)` документирован как CUDA Array Interface/DLPack→bytes, но **реальный wheel2.2.3 возвращает list packet dicts**, см. точное дополнение ниже; `EndEncode()` обязателен, все output packets сохранять. Device caps query поддерживается. Docs расходятся в именах kwargs (`format` vs `fmt`, `cuda_context` vs `cudacontext`): required positional args предпочтительнее; optional names брать из точной версии. Пакета локально нет. [Encoder API](https://docs.nvidia.com/video-technologies/pynvvideocodec/pynvc-api-reference/encoder.html), [version2.2](https://docs.nvidia.com/video-technologies/pynvvideocodec/index.html).

Warp1.16.0 array содержит CAI v2 (ptr,shape,strides,typestr), но **без stream field**. `__dlpack__(stream=...)` умеет stream wait относительно Warp current stream, однако это не автоматически renderer completion. Возможный minimal adapter: rawCUDA annotator → own Warp RGBA/ABGR slot copy на подтверждённом stream → event→worker sameCUDAcontext → Encode(slot). Release slot лишь после encoder input no longer needed; реально ли Encode копирует немедленно и releases GIL — проверить exact binding/sample+probe. CAI compatibility подтверждена уровнем API, **actual Warp→PyNv runtime не проверен**.

Официальный DeepStream Libraries `encode_video/encode.py` уже использует four AppFrameGPU buffers, CreateEncoder(...False), Encode, writes allbytes и EndEncode. Но sample сначала читает rawfile и H2D; его README baseline сейчас требует CUDA13.2/driver595, отличный от declared driver580. В sample gpu_id CLI отмечен unused. `encode_config_lowlatency.json` фактически содержит `high_quality`, fullres multipass, bf3: **название config не гарантирует latency**. Конкретные files pin `d31deae34bb4f443d54cc98be84a3c08afc2e3fa`. [Sample](https://github.com/NVIDIA-AI-IOT/deepstream_libraries/blob/d31deae34bb4f443d54cc98be84a3c08afc2e3fa/encode_video/encode.py), [repository requirements](https://github.com/NVIDIA-AI-IOT/deepstream_libraries).

Published wheels дают CPython3.12/Linux compatibility на уровне диапазона Python, не Kit ABI. Latest requirements меняются; нельзя утверждать поддержку данной CUDA12.8 +580 комбинации из фразы latest CUDA Toolkit. Выбрать pin wheel и inspect metadata/linkedlibs до environment proposal. [System requirements](https://docs.nvidia.com/video-technologies/pynvvideocodec/read-me/system-requirements-common.html).

SDK13 `NvEncoderCuda` reference применим к existing device pointer through owned registered inputs. Register→map→encode→unmap, input consumption fence и output bitstream readiness — разные границы. Linux synchronous NVENC bitstream lock может выполняться на output worker, освобождая render thread; Windows asynchronous events не являются переносимым Linux API. Не пересоздавать session/context/frame allocations каждый кадр. [NVENC programming guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html).

NVENC engines независимы от graphics/CUDA cores, но format conversion/copies/scheduling потребляют общие ресурсы. Three camera sessions могут быть распределены драйвером между engines. Split-frame encoding предназначен HEVC/AV1, **не H264**; implicit height thresholds HEVC2112/AV12048 выше600. Для уже нескольких sessions split-frame не повышает aggregate throughput и может уменьшать quality. Не оправдывать atlas3camera как необходимость использовать обаNVENC. [Application note](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-application-note/index.html), [split frame API](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-video-encoder-api-prog-guide/index.html).

VPF архивирован10June2024; SampleEncodeMultiThread действительно использует retained primarycontext и perworker stream с PyFrameUploader/SurfaceConverter/PyNvEncoder. Это существующий reference pattern, не современная dependency рекомендация. Его sample только performance loop, не полноценный output accounting; прочитан pin `529fb192f22ec305b8b237ed9e6014e171339c81`. [Archived project](https://github.com/NVIDIA/VideoProcessingFramework), [worker sample](https://github.com/NVIDIA/VideoProcessingFramework/blob/529fb192f22ec305b8b237ed9e6014e171339c81/samples/SampleEncodeMultiThread.py).

## 6. GStreamer, DeepStream, NITROS, Holoscan: готовые components, не ускоритель RTX scene

Modern GStreamer nvcodec CUDA-memory encoder принимает `memory:CUDAMemory` RGBA/NV12 и другиеformats. New zero-copy elements nvcudah264enc/nvcudah265enc введены1.22; autoGPU selects inputdevice. В current docs nvh264enc property cuda-device-id read-only, nvautogpuh264enc writable. Для1.24+ `gst_cuda_allocator_alloc_wrapped(allocator,context,stream,info,ptr,user_data,notify)` позволяет ownedCUDA ring; info offsets/strides/size должны совпадать с allocation. **Без notify allocator освободит ptr**, с notify lifetime — caller. Explicit stream integration и cudaipcsrc/sink появились1.24, отсутствуют в system1.20. [New elements1.22](https://origin.gstreamer.freedesktop.org/releases/1.22/), [integration1.24](https://gstreamer.freedesktop.org/releases/1.24/), [CUDA allocator](https://gstreamer.freedesktop.org/documentation/cuda/gstcudamemory.html), [autoGPU encoder](https://gstreamer.freedesktop.org/documentation/nvcodec/nvautogpuh264enc.html).

Potential pipeline после **настоящего CUDA GstBuffer wrapping**: appsrc capsRGBA/CUDAMemory → CUDA encoder bf0/lookahead0/zerolatency → h264parse→filesink; собственные PTS в GstBuffer и sidecar source IDs. Одна `appsrc` caps string не превращает hostbytes/opaque pointer в CUDAMemory. NVMM из DeepStream и CUDAMemory из gstnvcodec — разные buffer representations. Kit bundled~1.20plugin не следует автоматически current documentation выше.

DeepStream `nvv4l2h264enc`/`nvv4l2h265enc` — hardware path на Jetson **и dGPU**, через NVIDIA libv4l2 extension; inputs I420/NV12/YUV444. Это не обычный system v4l2 plugin. dGPU `preset-id`1..7, `tuning-info-id`1HQ/2LL/3ULL/4lossless, bitratebits/s; Jetson preset-level имеет другой enum. Для RGBA→NV12 нужна подходящая GPU conversion (NvBufSurface/nvvideoconvert). Наш existing Warp pointer не становится NvBufSurface автоматически. Нет evidence установленного DeepStream; запуск нового stack не нужен лишь ради трёх codecs. [Current nvvideo4linux2](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_plugin_gst-nvvideo4linux2.html).

DeepStream nvstreammux batching полезен inference throughput, а не синхронизация трёх Piper exposures. batched-push-timeout/queue может добавить лаг; NvDs frame metadata input IDs не заменяет capture generation. nvdsxfer переносит NVMM batches междуNVLINK GPUs с copy; не считать его zero-copy наRTX4090 или обещанием P2P доступности. [nvstreammux](https://docs.nvidia.com/metropolis/deepstream/7.1/text/DS_plugin_gst-nvstreammux.html), [nvdsxfer](https://docs.nvidia.com/metropolis/deepstream/dev-guide/text/DS_plugin_gst-nvdsxfer.html).

IsaacROS release3.2 h264 encoder имеет actualconfig qp,hw_preset,profile,iframe_interval; **config=custom** обязателен, иначе presets переопределяют custom. Input rgb8/bgr8 and even dimensions; node рассчитывает1frame→1encodedimage. NITROS typeadaptation переноситCUDA между совместимыми nodes; переход к обычномуROSimage/rosbag приводит к CPU представлению. Создание дополнительногоROS transport ради записи здесь не ускоряет existing capture. Managed NITROS builders позволяют CUDAimage+header; ROSstamp не independent render stamp. [Encoder3.2](https://nvidia-isaac-ros.github.io/v/release-3.2/repositories_and_packages/isaac_ros_compression/isaac_ros_h264_encoder/index.html), [ManagedCUDA](https://nvidia-isaac-ros.github.io/v/release-3.1/concepts/nitros/cuda_with_nitros.html), [NITROS3.2](https://nvidia-isaac-ros.github.io/v/release-3.2/concepts/nitros/index.html).

HoloHub concrete `NvVideoEncoderOp` pin `8a6c0bdfc70df1469a0cac1d2dade03940ec1f75` и `nvc_encode_writer` готовые references для CUDA12.8/driver≥570. Код принимает unnamed deviceTensorRGBA, NvEncoderCudaABGR, retainedprimarycontext; ownGPUinputcopy; defaultP3+LL; custom ratecontrol/multipass. **Каждый кадр forcedIDR+SPS/PPS**, при нескольких packets выбираетfirst, noframe size mismatch лишь return, stop вызывает EndEncode и discard результата. Следовательно это upstream demo, не fail-closed lossless recorder. Полезная speedconfig P1+multi_pass_encoding0 требует собственного верифицированного callback/flush учёта. [Actual encoder source](https://github.com/nvidia-holoscan/holohub/blob/8a6c0bdfc70df1469a0cac1d2dade03940ec1f75/operators/nvidia_video_codec/nv_video_encoder/nv_video_encoder.cpp), [encode-to-file](https://github.com/nvidia-holoscan/holohub/blob/8a6c0bdfc70df1469a0cac1d2dade03940ec1f75/applications/nvidia_video_codec/nvc_encode_writer/README.md).

Holoscan built-in VideoStreamRecorderOp — сериализатор tensors в `.gxf_entities/.gxf_index`, **не NVENC MP4 recorder**. GPU input не означает zero-transfertodisk. New GPU-residentexecution использует static CUDAgraphs/device buffers для computeoperators; NVENC asynchronous session/output и Kit render scheduling не становятся graph-capturable автоматически. SDK отсутствует; переносить framework нет основания. [Recorder semantics](https://docs.nvidia.com/holoscan/sdk-user-guide/4-3/faq/faq), [GPUresidentexecution](https://docs.nvidia.com/holoscan/sdk-user-guide/using-the-sdk/gpu-resident-execution), [stream handling](https://docs.nvidia.com/holoscan/sdk-user-guide/using-the-sdk/cuda-stream-handling).

## 7. Vulkan/GL interop, SPG, packing и альтернативные image codecs

CUDA имеет supported GL register/map/unmap и Vulkan external-memory import+semaphore interop; Vulkantexture не регистрируется API cudaGraphicsGLRegisterImage. Vulkanproducer должен экспортировать VkDeviceMemory FD, allocationflags/layout/size и external semaphore, затем CUDA импортирует и соблюдает ownership. Existing Kit RpResource не раскрывает такие handles в найденном PythonAPI. `simpleVulkan` — actualworking reference собственной Vulkanapplication, **не patch Kit**. Ставить ctypes.cast на handle unsafe/unproven. [CUDA interop](https://docs.nvidia.com/cuda/cuda-programming-guide/04-special-topics/graphics-interop.html), [simpleVulkan code](https://github.com/NVIDIA/cuda-samples/blob/master/Samples/5_Domain_Specific/simpleVulkan/main.cpp).

SPG customCUDA kernels выполняют GPU postprocessAOV: channel swap, RGBA→NV12/packing или marker возможно внутри render graph. Это не снимает стоимость трёхviews, barriers и encoder I/O. Atlas960×1800 или2880×600 сохранит pixelcount, может уменьшить session/call overhead, но добавит pack/crop policy, bordercompression/quality differences и общий failuredomain. Crossproductjoin трёхAOV и independentcameras supportedstock SPG shortcut **не найден**; не выдавать atlas как authored3cameras equivalent. Current0.4docs новее ранее проверенного0.2API; pin installedversion beforebuild. [SPG](https://docs.omniverse.nvidia.com/kit/docs/omni.rtx.spg/0.4.0/Overview.html).

nvImageCodec предоставляет CAIinterop и GPUJPEG/nvJPEG2000/TIFF backends; PNGencoding — CPU backend. Это вариант independentframecompression, если NVENClossy недопустим или imagefiles требуются, но packages отсутствуют. ExplicitCUDAstream/deviceformat/channel checks всё равно необходимы; nvJPEG encode — не доказанный isolated dedicatedNVENC engine и может конкурировать с rendererGPUwork. СвойnvJPEGworker через PyTorchbundledlib потребует CAPIbinding/build, не готового Python API. [ImagecodecAPI](https://docs.nvidia.com/cuda/nvimagecodec/py_api.html), [backendoptions](https://docs.nvidia.com/cuda/nvimagecodec/codec_options.html), [nvJPEG](https://docs.nvidia.com/cuda/nvjpeg/).

## 8. Форумы и существующие попытки: только anecdotal evidence

- [ThreeCamera performance issue,2024](https://forums.developer.nvidia.com/t/camera-class-from-omni-isaac-sensor-significantly-reduces-sim-performance/306269): авторRTX3080/Isaac2023.1→4.1 reported55fps→20with3cams640×400→13ROS; другой пользователь profiler нашёл четвёртыйviewportpass и reported22→34–35 послеdestroyviewports. Не переносить numbers на6.1/4090/XR. Польза: проверить actualRPcount и лишний spectatorrender; **XRviewport удалять нельзя**.
- [4RenderProducts slowdown,2025/2026](https://forums.developer.nvidia.com/t/performance-of-render-product-in-action-graph/322300): NVIDIAforumответ советует tiledrendering5+. Это hint проверять exactTiledCameraAPI, а не доказательство3arbitrary authoredcamera/Quest benchmark или разрешение снизить resolution/cadence.
- [MultiGPU cloud <30Hz,2025](https://forums.developer.nvidia.com/t/low-frame-rate-30-in-isaacsim-on-g6e-12xlarge/334049): multipleL40 само по себе не обеспечивает camera rate. Version/model отличаются; причина должна быть измерена profiler, не обобщена из thread.
- [Gst CUDA streams,2024](https://discourse.gstreamer.org/t/cuda-encoder-stream-synchronization-without-cpu-block/1191): maintainer обсуждает собственный encoderstream, GstCudaBufferPool stream sharing/allocwrapped1.24. Это usefulintegrationpattern, official release notes подтверждают APIs; установленный Kit bundledfork и версия требуют отдельной проверки.

## 9. Матрица bench и граница успеха

Нужно различать render-only, transfer-only, encode-only, fullretainedPiper, fullRUN+XR. Один опыт за раз, parent планируетGPU. Предлагаемый порядок:

1. RetainedPiper3existingRP, same render settings, longrun≥3000 после120warm: native Writer OnFrame versus polling, затем SRTX orchestrator. Capture render callbacks/frameinfo как observer. Полныйdecodeвсех3streams и rolling phase distributions; не randomsampleonly.
2. Тот же rawCUDA/CPUcamera producer с disk sinkdisabled: сколько complete freshtriplets, времяD2H/copy; ownmetadataframeidentity сохранять.
3. CPUraw retainedscene + FFmpegTripleEncoder packedRGB versus CPUYUV, GOP1 versus50. Включить recorderdrain в walltime, показать ringhighwater/full и frames submitted/written/decoded perrole. No synthetic repeatedframes evidence.
4. Если bottleneck именно encoder, sourceAPIcandidatePyNv/SDK: pinnedfutureenvironment, sameCUDAcontext/device, event-controlledGPUring. Encode-only3streams измерить вместе сgraphicsload; затем fullrenderer.
5. SessiononlyMultiGPUplacement: GPU0 physics/XR, cameraRPsGPU1; exact `deviceIds`/actualframeinfo и GPUusage witness. ВторойGPUне найден/доступностьP2Punknown — scenario, не localresult. Rawtextures не таскать межGPUбез необходимости; encode на cameraGPU.
6. Active Quest, realXRrendering, operators/actions в текущемsharedRUN/DIAG lifecycle; verify phasebound и wallrate. БезXRнастоящего run не выводить >30.

Success record: complete triplets perelapsedwall **послеdrain**,>30XR/~50withoutQuest, boundedlag и rolephase verified, noempty/repeat/drop beyonddeclaredpolicy, maximumgap,p95/p99 latency, queuebounded, optical/pose/configmatch, pixelscorrect and datasetlabels provenance retained. A fixed−2frame lag can be acceptable only with measuredidentity/actionhistory; phases−1/0/0 need truthfulperrolecapturetimes or explicittripletalignmentpolicy. Encoder playbackframerate/fps target/APIreturnTrue не засчитываются.

Unknowns: stockWriterfixlongrun; validHydraRPbindingwithoutduplicatepass; actualSWHstampavailability; nativeencodequality/hiddensettings; FFmpegNVENCsessionload; RGBrange/channelmapping; PyNv exactCUDA12.8ABI/GIL; bundledRTSPsource-vs-wheelprovenance; rawCUDAbufferconsumptionlifetime; XR encoder contention/sessionlimits; actualsecondGPUavailability/rendererplacement; fullPiperphysics/UIlatency.

## 10. Rollback и артефакты

Experimentonly `/tmp`: native/FFmpeghelpers, rawstderr+bitstreams+sidecars in uniquedirectory; no officialenvironmentwrites, no SDKpatches, no dataset admission. Sessiononly flags/RenderProductdeviceIds/SPG authoredoverrides записать beforevalues и restoreonexit; не save root USDlayer. Detachannotators/Writer, unregistercallback, stopcloseRTSP, EOSdrainencoders, joinworkers, releaseownedGPUslots aftercompletion; shutdown then closeapp. Каждое изменение сравнить с unchangedsnapshotmanifest. При failure оставить evidencebytes неизменными и прежнийsharedRUN/RECORD путь. НовыйPyNv/Gst/Holoscanstack требует отдельного proposal/pin, а не импровизированного pipвIsaac.

Созданы/прочитаны:

- `/tmp/live30-deep-media.md` — этот memo.
- `/tmp/live30-ffmpeg-workers.py` — runnableCPUtriplet→3NVENCprocess adapter, syntaxPASS, **runtime/GPU не проверен**.
- `/tmp/live30-native-writer.py` — producercompressed sink из предыдущейзадачи, syntaxPASS, runtimeparent.
- `/tmp/live30-media-upstream/` — pinnedpublicsource snapshots, GitHubtree metadata, selectedFFmpeg/NVIDIAsamples и extractedselectedLGPLsource files (толькоtmp).

Repo/installed SDK modifications этим audit не выполнялись. Поэтому doclint/gate suites кtmpmemo не запускались; проверка документации/индекса/регистрации обязательна при переносе в maintainedowner. Все URL выше — источник утверждения рядом с ним, датаretrievedобщая2026-10-09; upstreammain следует заменятьpin передimplementation.


## Дополнение: exact PyNvVideoCodec2.2.3 wheel вместо догадок по webdocs

PyPI показывает **pynvvideocodec==2.2.3**, release2026-09-15; LinuxCPython3.12 wheel manylinux_2_28_x86_64,26,860,478bytes, SHA256`126224753a41655c72c1576cb23a835cb853a1a3c3568d78360ff07d24627b42`,requires_dist=None. ZIP downloadedonlyinto/tmp и hashverified; install/import не выполнялся. [PyPI release](https://pypi.org/project/pynvvideocodec/2.2.3/).

Actual wheel `PyNvVideoCodec/__init__.py`: CreateEncoder requiredpositional(width,height,fmt,usecpuinputbuffer); popsintcudacontext/cudastream, otherkwargs stringifies→PyNvEncoder. Import вызывает NVENCVersionCheck и выбирает bundledbindings130 или121 по поддерживаемойdriverAPI. Поэтому дажеimport уже не чистыйread-onlyCPUcapabilitycheck.

Actual `samples/basic/encode.py` lines298–320/438–460: `pic_params=nvc.NV_ENC_PIC_PARAMS();pic_params.inputTimeStamp=frames_encoded;enc_list=nvenc.Encode(frame,pic_params)`; output **iterable dictionaries** with `data`,`picture_type`,`timestamp`. Сохранять bytes(packet['data']) для каждогоpacket и каждогоEndEncodepacket. **Это расходится с currentwebAPI referencebytes return.** `GetSequenceParams()` есть для extradata; samplemuxer inputs preserve packetpicturetype/timestamp.

Actual `samples/utils/Utils.py` AppFrame: GPUARGB/ABGRbuffer W*H*4; `.cuda()` возвращает CAIdict shape(H,W,4), strides(4W,4,1),data(ptr,False),typestr|u1,version3. CPU sample flatnumpyuint8buffer. Для rawKitRGBA byteorder используется **ABGR**, как concreteHoloHubRGBA→NVENCABGR; ARGB соответствуетBGRAbytes. Validate colorpatches, no alpha in standardH264output.

Concrete helper `/tmp/live30-pynv223-adapter.py` (syntaxPASS/noimport/noGPU) реализует CPUcontiguousHWCflatten, CudaRGBAFrame(owner,ptr,width,height,pitch)`.cuda()`shim, exactNV_ENC_PIC_PARAMStags и allpacketsinclflush. Он не делает ownershipcopy/synchronization заcaller; rawborrowedannotatorpointer нельзя передаватьasynchronouslyбезownedslot. Caller обязан обеспечить producercompletion и currentCUDAcontext. Нельзя infer pixelidentity только из encoderinputTimeStamp.

Сырыеsources из wheel под `/tmp/live30-media-upstream/pynv223-wheel/`; verifiedwheel и PyPIjson рядом. Publicsourceprovenance rootURLPyPI + fileinsidewheel + wheelSHA достаточны для reproducibility; webAPInever silently overrides exactbinaryversionexample.
