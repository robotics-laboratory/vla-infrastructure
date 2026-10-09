# PyNvVideoCodec 2.2.3: точный протокол, владение CUDA и проверка FFmpeg

Дата получения первичных источников: 2026-10-09. Это дополнение к `/tmp/live30-deep-media.md`, а не изменение исторического отчёта. В этой работе не запускались GPU/HW, не устанавливались пакеты и не изменялись SDK, окружения или исходники проекта. Состояние назначенного checkout: `research/live-camera-recording-30hz`, HEAD `d5566834d29ef8bb56e4fb62bb324e23e0869100`; untracked `docs/experiments/20261009_live_camera_recording_30hz/deep_research/` — работа родителя. Перед чтением проектных адаптеров использован CodeGraph. Сведения о результатах GPU-проб ниже обозначены как сообщения родителя, а не самостоятельные измерения.

## Главные исправления к предыдущему аудиту

1. Возвращаемый `packet['timestamp']` в точной версии 2.2.3 — внутренний ordinal отдельного encoder instance, начиная с 0. Это **не** переданный приложением `NV_ENC_PIC_PARAMS.inputTimeStamp`. Обе ветви helper SDK, 13.0 и 12.1, безусловно перезаписывают поле в `NvEncoder::DoEncode`. Из-за этого role-tag `1_000_000 + index` нельзя использовать как ключ подтверждения владения буфером. В предыдущем дополнении предположение о сохранении source tag было неверным.
2. `.cuda()` должна вернуть объект с атрибутом `__cuda_array_interface__`, а не сам словарь интерфейса. В предыдущем приложенном примере возвращение dict было ошибкой. Исправленный родителем вариант `.cuda() -> self` с property CAI соответствует C++ binding.
3. CAI RGBA требует **точно** contiguous layout `(H,W,4)`, strides `(W*4,4,1)`, `typestr='|u1'` или `'B'`. Аргумент `pitch` адаптера не делает произвольный pitched renderer buffer поддержанным: C++ проверяет strides и отклоняет любой другой шаг строки.
4. Python-объект, удержанный до packet ACK, защищает allocation от освобождения. Он не защищает его содержимое от повторного использования renderer. Для живого RP нужен producer ownership либо собственная immutable копия с правильной синхронизацией.

Эти выводы получены из официального [пакета исходников NVIDIA v2.2.3](https://api.ngc.nvidia.com/v2/resources/nvidia/pynvvideocodec/versions/v2.2.3/files/PyNvVideoCodec_2.2.3.zip), а не из старых web-примеров. [Каталог NGC](https://catalog.ngc.nvidia.com/orgs/nvidia/resources/pynvvideocodec) подтверждает версию, дату 2026-09-15 и распространение исходников.

## Источник и точность воспроизведения

Архив `/tmp/live30-media-upstream/PyNvVideoCodec_2.2.3.zip`: 40,163,701 bytes, SHA256 `29f7c0694d683266c563aca9a4f8e979ba0c5dce8f0ccc1efe500073e0948be0`. Hash совпал с `sha256_base64` официального [NGC manifest](https://api.ngc.nvidia.com/v2/resources/nvidia/pynvvideocodec/versions/v2.2.3/files): `KffAaU1oMmbFY6yppPjpeboMXc6PDMwe/lAAc+CUi+A=`. Выбранные текстовые файлы ZIP извлечены в `/tmp/live30-media-upstream/pynv223-source/` без build/import/install. Полный реестр с SHA256 отдельных исходников находится в `/tmp/live30-media-followup-sources.json`.

Сопоставляемый binary wheel: `pynvvideocodec-2.2.3-cp312-cp312-manylinux_2_28_x86_64.whl`, SHA256 `126224753a41655c72c1576cb23a835cb853a1a3c3568d78360ff07d24627b42`. Это совпадение публичной версии источников и binary distribution; reproducible build соответствия бинарных инструкций архиву здесь не проводился. Наблюдение родителя, что все три encoder instance возвращают 0,1,2 независимо от role-tag, дополнительно подтверждает нужный runtime path.

Все относительные пути далее начинаются с `PyNvVideoCodec_2.2.3/src/` внутри ZIP; номера строк исходника сохранены, CRLF нормализован только при просмотре.

| Факт | Точное место в официальном исходнике |
|---|---|
| Замена `inputTimeStamp` | `VideoCodecSDKUtils/helper_classes/NvCodec/NvEncoder/NvEncoder_130.cpp:685–704`, особенно 697; `_121.cpp:650–669`, особенно 660 |
| Очередь успешных submit | `_130.cpp:611–635`: при SUCCESS/NEED_MORE_INPUT увеличивает `m_iToSend`, читает доступный output |
| Получение ACK | `_130.cpp:771–819`: blocking lock, копирует bitstream, получает outputTimeStamp, unlock, unmap input resource |
| Python output | `PyNvVideoCodec/src/PyNvEncoder.cpp:702–714`: list of dict, owned Python bytes, timestamp, picture_type |
| Python params передаются по значению | `PyNvEncoder.cpp:745–779`, binding 1233–1243 |
| `.cuda()` + CAI | `PyNvEncoder.cpp:750–754`; `PyCAIMemoryView.cpp:32–49` |
| RGBA shape/strides | `PyCAIMemoryView.cpp:211–249` |
| Асинхронная D2D/H2D копия | `PyNvEncoder.cpp:684–698` / CPU 439–453; `NvEncoderCuda.cpp:136–222`, особенно 158,183,221 |
| Input/output stream NVENC | `PyNvEncoder.hpp:40–62`; `NvEncoderCuda.cpp:88–91`; `Interface/nvEncodeAPI_130.h:3499–3532` |
| Проверка context/stream | `PyNvVideoCodec/utils/PyNvVideoCodecUtils.hpp:46–75` |
| Внутренний ring/delay | `_130.cpp:468–480`; `NvEncoderCuda.h:58`: extra delay default 3 |
| SEI binding и payload lifetime | `PyNvEncoder.cpp:813–885`, 1244–1254; `NvCodecUtils.h:63` |
| Flush | `PyNvEncoder.cpp:887–897`; `_130.cpp:750–768` |

## Timestamp ledger: что действительно связывается

`NvEncoder::DoEncode` сначала копирует picture params в локальную структуру, затем назначает свой timestamp и frameIdx. Счётчик timestamp увеличивается **до** вызова драйвера. Поэтому после любой Encode exception нельзя продолжать тот же instance с обычным ordinal счётчиком приложения: возможна рассинхронизация. Сессию следует остановить, пометить неполной, дренировать в best effort и пересоздать только для новой сессии.

На каждый instance хранить `ordinal -> {source_tag, owner, role, source_frame_id, observed_time, stage/transition identity}`. Ordinal зарезервировать до `Encode`; после успешного return увеличить application submit counter; затем обработать **все** dict-пакеты. Для CPU также нужен ledger metadata; удерживать реальный исходный numpy allocation до ACK — простая консервативная защита от асинхронной H2D копии и будущих pinned-buffer вариантов.

Не принимать `pending.pop(timestamp, None)`: неизвестный ACK должен вызывать ошибку. Проверять повторный ACK, неизвестный ordinal, missing/extra packet, bytes пустой длины, число output после EndEncode. Для режима H.264 bf=0 expect one frame packet per successful input; исключения формата, AV1 superframes, multi-view HEVC и другие настройки требуют отдельной модели, а не переноса этого правила.

Произвольные source tags должны храниться как отдельные JSON fields. Не преобразовывать одновременно ключи Python dict и source tag через `int()` незаметно: строки, float и bool могут давать коллизии. Лучше принимать в текущем benchmark только `type(tag) is int`, неотрицательный диапазон и явно уникальную пару `(role, source_frame_id)`. Encoder timestamp не является scene frame ID, physics tick, временным значением в наносекундах или кодированным PTS внутри elementary H.264. В самом NVENC header `inputTimeStamp` описан как opaque data, которое не включается в bitstream (`nvEncodeAPI_130.h:2573–2575`).

Предлагаемый короткий фрагмент для существующего адаптера (фрагмент не запускает GPU и не предлагает менять SDK):

```python
# Вызовы одного encoder instance сериализуются приложением.
ordinal = self.inputs
if ordinal in self.pending:
    raise RuntimeError('duplicate encoder ordinal')
self.pending[ordinal] = {'owner': frame, 'source_tag': source_tag}
self.max_pending = max(self.max_pending, len(self.pending))
try:
    packets = self.encoder.Encode(frame, picture_params)
except BaseException:
    self.failed = True  # не продолжать эту сессию и не менять ledger молча
    raise
self.inputs += 1
for packet in packets:
    ordinal = int(packet['timestamp'])
    if ordinal not in self.pending:
        raise RuntimeError(f'unknown/duplicate encoder ACK: {ordinal}')
    record = self.pending[ordinal]
    self.write_packet(packet, source_tag=record['source_tag'])
    del self.pending[ordinal]  # после успешной записи bytes и metadata
# EndEncode: тот же цикл, затем require not pending и packets == inputs.
```

Capacity 8 имеет смысл как лимит остатка очереди после обработки output. Если считать абсолютный transient peak до Encode, устойчивое `pending=8` означает девятый source owner на следующем submit — это следует отдельно учитывать в high-watermark и budget. При ring delay=3 обычный пик pending до Encode — 4, после — 3. Поведение и peak следует подтвердить реальной пробой, особенно с lookahead.

## CUDA ownership: когда можно освободить или переиспользовать буфер

GPU CAI pointer не регистрируется напрямую как внешний input NVENC в этом Encode path. PyNv выбирает собственный ring buffer, копирует source D2D с `cuMemcpy2DAsync` в encoder stream, затем кодирует этот ring. Это route без D2H для raw pixels, но **с D2D copy**, а не zero-copy. Производные заявления о bandwidth/FPS без measurements не делаются.

Перед D2D helper выполняет `cuCtxPushCurrent(encoder_context)`, после enqueue — PopCurrent. Constructor проверяет, что encoder context принадлежит выбранному gpu_id и переданный stream принадлежит именно этому context. Это не полная проверка producer pointer/context compatibility; CAI path получает device ordinal source pointer, но не сравнивает его с encoder gpu_id. Для camera GPU1/encoder GPU0 нельзя предполагать автоматическое peer-copy: использовать один device/context для producer и encoder до отдельного peer-memory протокола.

Источнику нужно быть полностью готовым **до** чтения копией. Точная CAI coercion не устраивает wait на producer stream: проверяет dict через `py::hasattr(array_interface, 'stream')`, а в возвращаемом view всё равно ставит streamid=0; аргумент local stream не используется для event/wait. Нельзя рассчитывать, что добавление CAI `stream` автоматически синхронизирует RTX/Warp/PyNv. Для ABGR также используется CAI path, не DLPack consumer-stream handshake, даже если объект предоставляет DLPack.

Сначала минимальная проверяемая схема: producer GPU operation complete → собственный contiguous RGBA allocation → Encode на согласованном stream → owner удерживается до packet ordinal ACK. Для fixture `wp.array(numpy_pixels, device)` плюс явно выполненный `wp.synchronize_stream()` даёт готовый source; это не эквивалентность реальному renderer.

После возврата соответствующего packet, C++ уже успешно заблокировал completed bitstream, скопировал его в CPU vector, разблокировал и unmapped свой input resource. Python bytes также имеют собственную копию. **Вывод по этому source path:** immutable external source owner можно освободить при ordinal ACK; source copy и encode завершились раньше. Это достаточная консервативная граница, а не специальный публичный callback «external input released». Более ранняя граница возможна по event после D2D на encoder stream, но такого handle публичный Encode не возвращает. Можно после Encode записать CUDA event на этом stream и ждать его для собственной source ring; это потенциальная оптимизация, требующая отдельного теста, и она может ждать дополнительные queued NVENC CUDA операции.

Сырой renderer RP buffer: retention Python object не делает backing buffer immutable. Даже после enqueue copy renderer может начать перезапись из другого stream, пока D2D читает. Требуются две зависимости: render-complete → consumer copy; copy-complete → renderer reuse. Если Kit не даёт retain/fence contract для конкретного source handle, практический безопасный путь — собственная копия во время authoritatively completed producer callback до reuse. Иначе «малый разрешённый frame lag» маскирует race, а не исправляет его.

[CUDA Driver API](https://docs.nvidia.com/cuda/cuda-driver-api/group__CUDA__MEM.html) прямо описывает cuMemcpy2DAsync как обычно асинхронную операцию. [NVENC guide 13.0](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html) требует получить завершённый output через lock и корректно освободить mapped resources; Linux output mode использует blocking lock. Это совместимо с producer/worker очередями приложения, но не доказывает отсутствие stall в main XR thread.

При cleanup сначала explicit EndEncode и запись всего output, затем synchronize source/copy stream и уничтожение encoder, только затем освобождение ещё удержанных owners при failed session. Destructor source содержит best-effort flush, который отбрасывает payload; его нельзя считать успешной записью. На fatal CUDA/device error безопасная reuse гарантия неизвестна; пометить session failed, завершить isolated worker/process, не продолжать сбор и не объявлять complete.

## Picture params, потоки и SEI

Binding принимает `NV_ENC_PIC_PARAMS` **по значению**, дважды копируя структуру в локальные объекты до encode. Scalar Python property mutation после Encode не меняет уже отправленные scalar поля. Pointer members для external input/output, completion event, hints и некоторых maps explicitly обнуляются Python wrapper. Нет необходимости держать Python picture object до ACK ради inputTimeStamp: поле вообще заменяется.

Однако mutex внутри encoder path не найден; GIL освобождается на EncodeFrame/EndEncode. Два Python threads с одним instance могут пересечь mutable ring counters, поэтому сериализовать вызовы одного instance отдельным worker/lock. Три отдельные instance допустимы как дизайн, но общие source stream/context и scheduling ещё требуют испытания. Через CPU/GPU codec-only benchmark не выводить XR/main-thread latency.

SEI имеет отдельный overload `Encode(frame, pic_flags, sei_messages)`, где messages — список пар `({'sei_type': 5}, list_of_byte_values)` для H.264/HEVC. C++ преобразует в собственный vector payload, создаёт NV_ENC_SEI_PAYLOAD array и удаляет его после EncodeFrame; официальный sample использует ту же схему. Для source identity возможно `uuid16 + binary/json payload` типа user_data_unregistered. Например:

```python
import json, uuid
payload = uuid.UUID('9dd6ec2a-78c8-4bdb-b7fc-c44d733deaa1').bytes + json.dumps(
    {'role': role, 'source_frame_id': source_frame_id, 'source_tag': source_tag},
    separators=(',', ':'), sort_keys=True).encode('utf-8')
packets = encoder.Encode(frame, 0, [({'sei_type': 5}, list(payload))])
```

Этот overload не комбинируется в API с полным Python picture params: существуют separate overloads. Для flags FORCEIDR/OUTPUT_SPSPPS использовать OR SDK enum согласно версии, не добавлять IDR на каждый кадр без необходимости. Вставленный SEI подтверждает submission metadata, **не** semantic identity pixels: если renderer buffer уже устарел, SEI будет свежим, а изображение старым. Требуется декодированный optical witness/динамическая сцена.

## Что брать для реального camera source

| Источник | Минимальная схема | Неизвестное / блокирующее условие |
|---|---|---|
| Native compressedLdr producer Writer | stock encode, bytes сразу от native annotator; frame/source metadata из того же callback | Native metadata не заменяет pixel witness; проверить пропуски и 3 roles; уже исследован в основном memo |
| GPU RGB annotator / Camera device=cuda | wrapper `.cuda()->self`, CAI contiguous RGBA, same CUDA context/device, explicit producer-ready, own storage | Уточнить actual API returned owner/reuse для Kit110.3; отсутствие D2H не означает отсутствие synchronous get_data |
| Replicator/Warp TiledCamera atlas | одна contiguous GPU texture → PyNv single encoder или GPU split в 3 buffers | Atlas encoder снижает число sessions, увеличивает frame area; роли/opticalIDs должны пережить packing и lossy codec |
| Hydra texture / renderer buffer | authoritative render-complete callback; GPU resource interop в свои contiguous allocations | Ранее найденный Python RpResource не предоставляет доказанный public CUDA pointer; нужен поддержанный C++/graphics interop surface API и fences |
| CPU raw RGB(A) | FFmpeg native worker или PyNv CPU input, bytes/numpy owner до drain/ACK | D2H и CPU ownership copy; worker throughput не равен полной XR camera throughput |

Для 960×600 RGBA один source frame — 2,304,000 bytes. Три роли ×8 pending owners ≈55.3 MB плюс native encoder input rings и остальная память renderer. Это arithmetic capacity estimate, не measurement VRAM. Для contiguous source route и bf0/lookahead0 использовать известные рабочие опции родителя: `preset='P1'`, `tuning_info='ultra_low_latency'`, `bitrate=16000000` integer, `bf=0`, `gop=50`, `fps=50`, explicit `lookahead=0`. Constructor верхнего слоя uppercases preset, но CLI второй стадии также парсит options, поэтому lowercase p1 оказалось нерабочим в сообщении родителя. Integer bitrate исключает неподдержанное строковое `16M`. Exact source ring delay=3 остаётся даже при ULL; открытого kwargs для nExtraOutputDelay не найдено. Не патчить helper для уменьшения delay до измерения latency и completion safety.

## FFmpeg: проверка без manufactured frames и честная скорость

Для установленного 4.4.2 verifier использовать:

```text
ffmpeg -hide_banner -loglevel error -i camera.h264 -map 0:v:0 -vsync 0 -f rawvideo -pix_fmt rgb24 pipe:1
```

Не добавлять output `-r`/fps filter. В [точной документации FFmpeg n4.4.2](https://raw.githubusercontent.com/FFmpeg/FFmpeg/n4.4.2/doc/ffmpeg.texi), section vsync, 0 означает passthrough, auto может выбрать CFR, CFR дублирует/удаляет frames. Наблюдение родителя о лишнем первом decoded frame при auto соответствует этой способности verifier; оно не является доказательством duplicate на NVENC input/output. Современное `-fps_mode passthrough` предназначено для новых FFmpeg и не следует требовать у системного 4.4.2.

Проверять не только byte count: read ровно W×H×3, EOF только на границе кадра, process exit0, expected number decoded frames, decoded role+sequence marker, порядок/lag, один triplet source identity для трёх roles. Current marker `index | (role << 10)` однозначен лишь пока index<1024. При длительной пробе 3000 frames нужна большая битовая разметка или явный guard; иначе role bits пересекаются с frame index, свидетель теряет способность различать роли. Позиционный moving stripe дополняет bit marker, не заменяет его. Threshold tolerance и цветовые каналы проверять после lossy decode.

В `codec_probe.py` на момент read submitted latency для all warm+measuredframes и bundle timer без drain смешивают разные scopes. `1 / mean(measured_bundle_duration)` — submit/encode loop throughput, **не** запись полного файла и не wallHz реальных live cams. Полезные отдельные показатели: measured input triplet wallHz; acknowledged/durable output wallHz до последнего ACK; drain seconds; queue high-watermark; p50/p95/p99/max main-thread submit stall; decoded count/errors; source-to-output lag. EndEncode/time at last sidecar write нужно учитывать для finite recording throughput. Для долгого устойчивого run отдельно отчётный участок после warmup без startup/drain допустим, если bounded queue не растёт и окончательный drain подтверждает completeness.

FFmpeg pipe `write()` подтверждает передачу в OS/process, не получение соответствующего output frame. EOF stdin → wait exit0 → decode all output → source count/witness — минимальная complete-проверка. При asynchronous worker mainloop быстро принимает enqueue в queue до насыщения; report queue acceptance Hz отдельно от encode-durable rate. Error handling не должно потерять result JSON: исключение в final cleanup можно записать отдельным cleanup_error, сохранив original failure. При stdout pipe verifier stderr нужно читать/направлять в файл, чтобы ошибки не приводили к pipe deadlock.

## Статус доказательств и rollback

Доказано source audit: input timestamp overwrite, exact CAI object protocol/contiguous restriction, internal owned D2D copy, stream/context checks, ring delay formula, owned output bytes, scalar params by-value, SEI overload, full EndEncode output list. Родитель сообщил runtime timestamp ordinal и работающий GPU byte protocol role0 до ошибки неверного ACK ledger; это не completed 3-camera XR benchmark. Производительность выше 30 Hz с активным Quest3 XR и target около 50 Hz без Quest данным дополнением не подтверждена.

Минимальная следующая проба у родителя: исправленный ordinal ledger на всех 3 roles; 210frames с guard marker<1024; require pending empty/packets=inputs/decoded optical witness; затем continuous source buffers immutable vs reused renderer buffer; затем fullscene XR measured section. Нельзя переносить результаты pureUSD encoder fixture на Piper physics+XR.

Rollback не требует SDK патча: отключить экспериментальную camera encoder selection; вернуть stock runtime/RECORD owner; остановить workers после drain и очистить только session-owned `/tmp`/experimentoutputs. Изолированный PyNv target добавлять в sys.path только probe/worker process; не менять declared Isaac env. Если требуется собственный C++ interop/fence — отдельный experimental selection с явным fail-fast и compatibility manifest; сохранить stock native Writer fallback. Не изменять historical evidence bytes и не приписывать gate admission этому аудиту.
