# Проверенная запись30Hz → LeRobot v3

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted preservation base: `e1f57032aba4777cb023ac26192eb6bb182f734a`.
Branch: `research/live-camera-recording-30hz`.

Реализован экспериментальный экспорт одного эпизода: native state и preclip
training action, три live NVENC camera streams, затем обычный LeRobot v3.
Физика120Hz, четыре native steps/control; целевая временная сетка датасета30Hz.
Запись и материализация выполняются раздельно. Код не меняет selected RECORD,
canonical offline replay или допуск данных. Реального Quest в этих тестах нет.

[План и upstream re-audit](PLAN.md) объясняют выбранные границы.
[Run/audit summary](results.json) содержит команды, source identities и результаты;
[retention](retention.json) закрепляет внешние артефакты: 568 файлов,
≈0.96GB; 419 CPU evidence files скопированы
из /tmp с проверкой SHA256. [Retention helper](retain_artifacts.py) сохранен
с exact tested source. HF/Python caches исключены, failed attempts сохранены.

## Что изменилось

- `tools/isaac_vr_live_dataset.py`: prepare в существующем Isaac environment
  проверяет finalized artifact, causal rows, asset closure, visual provenance,
  live transform/source joins и полный terminal successor. Materialize в
  существующем core environment собирает и проверяет LeRobot. Процессы связаны
  файлами артефактов, дополнительного RPC или окружения нет.
- `tools/isaac_vr_live_video_import.py`: строго закрепленный instance-only hook
  LeRobot0.6.1 переносит уже закодированные MP4 через штатный writer. Upstream
  владеет Parquet, stats, metadata и video offsets. После `save_episode` hook
  восстанавливается, установленный пакет не меняется.
- `tools/isaac_vr_replay.py`: явно экспериментальный verifier принимает только
  `ovphysx_cpu` + injected/no-client profile и переиспользует общие integrity
  проверки. Canonical verifier по-прежнему требует Fabric. Его тесты сохранены.
- Experimental recording driver задает target performance logger согласно
  wall pacer и формирует run/session identity из уникального output locator.
  Ранее жестко заданный ID переиспользовался между эпизодами; source labels и
  физическая модель от этих двух исправлений не меняются.

Training `action[i]` берется из verified native label projection, `state[i]`
из исходного O_i. Поздний packet ready не сдвигает action относительно камеры:
packet ordinal/tag привязан к immutable source snapshot. Ledger сохраняет
obs/snapshot/transition IDs, physics step и host sample/receipt timestamps.
Сетка LeRobot timestamp=i/30 описывает simulation/control time. Отдельные
wall timestamps сохраняют фактические опоздания; эти часы не смешиваются.

## Свежая запись и временные результаты

Два запуска без diagnostic Mesh/witness, original Kit view, source queue1,
GPU rendering/NVENC, XR core enabled, injected reach-demo. Второй запуск
проверяет исправленные run IDs и logger. По960 controls и961 источнику каждой
камеры:840 основных +120 warmup controls записаны в эпизод,32 simulation seconds.
Принудительный wall pacer ограничивает частоту до30Hz; это не новый замер
максимального throughput. Предыдущие uncapped52–56Hz результаты и физические
отличия остаются в [timing/physics отчете](../temporal_physics/REPORT.md).

В paced-reach02 средняя capture/control start частота29.999963Hz, median
интервал33.3334ms, p95=33.3731ms, max=71.7414ms. После опоздания pacer может
догонять график: min интервал16.1919ms. Fresh snapshot sample p95=35.2174ms,
max=87.3547ms. Это небольшие реальные пропуски deadline, а не идеальная
wall-clock acquisition сетка. Complete throughput с encoder tail29.93259Hz.

Sample→native command apply p95=22.72ms; sample→packet ready p95 по трем ролям
115.33/115.72/116.12ms, max≈170ms с terminal tail. Метрики — host monotonic
timestamps: API packet return, не GPU exposure, аппаратный completion или fsync.
Около трех кадров encoder buffering сохраняется. Delay влияет на готовность
записанного пакета, а source binding сохраняет его принадлежность O_i.

## Сборка датасета

Prepare проверяет все960 native row/snapshot/render matrix joins и отдельно
terminal snapshot960, включая полные Recordable transforms. Три encoder ledger
содержат961 packet: source ordinal, tag, byte offset и coverage сверяются.
После drain FFmpeg stream-copy кладет только prefix960 в три MP4 с time base
1/15360 и PTS=i/30. Ни интерполяции действий, ни дублирования RGB, ни нового
кодирования нет. Терминальный кадр остается в raw streams и successor artifact;
он не становится строкой без действия.

[LeRobot v3](https://huggingface.co/docs/lerobot/lerobot-dataset-v3) сохраняет
табличные записи и видео с metadata. Public `add_frame/save_episode/finalize` формируют dataset с960 строками и
960×600 RGB каждой камеры. Изображения декодируются после записи для штатной
statistics/PNG staging; после QA staging удаляется из публикуемого output.
Импортированные MP4 сохраняют байты stream-copy файла. Ограничение импортера:
один RGB episode0, serial encoding boundary, без depth/streaming/batched save.
Writer version и SHA256 проверяются перед hook. При несовпадении он отклоняет
операцию; новая версия LeRobot требует повторного upstream audit.

Итоговый dataset locator:
`/data/ebulochkin/vla-runtime/live30-dataset-20261010/dataset-reach03`.
Подготовленная projection и source evidence:
`/data/ebulochkin/vla-runtime/live30-dataset-20261010/prepared-reach03`.
Исходная запись: `paced-reach02-output` в том же durable root.

## Проверки и неудачи

Сборка с decode/statistics и полным штатным QA заняла365.23s для32s
эпизода. Она выполнялась после записи; это не6min простоя внутри control loop.
Штатный QA прочитал960 строк/2880 изображений и480 DataLoader batches
на всех960 строках. Repository suite:425PASS/38SKIP; skipped scope —
отсутствующий в core h5py и аппаратные upstream checks.
Независимый QA04 завершилсяPASS за219.25s: все2880 RGB fingerprints
исходного H264 prefix совпадают с итоговыми MP4, exact PTS проверены, все960
`return_uint8` dataset lookups дают соответствующие пиксели и bitexact labels/state.
Проверены также первые/средние/последние DataLoader пары; исходные bytes/code
не менялись во время аудита. Отдельная мутация `action[17][0]` отклонена.
Дополнительное QA время — исследовательская проверка, не recording overhead.
Сводка окончательных проверок и длительностей находится в [results](results.json).
Raw commands, logs, exact tested sources, FFprobe/decoded frame fingerprints,
Parquet negative fixture и encoder/HDF/video evidence сохранены во внешнем
bundle. Проверки core repository: [receipt](checks/repository/results.json)
и [log](checks/repository/results.log), с trusted preservation base выше.

Сохранены также отрицательные попытки: initial import test использовал
незаписываемый HF cache; независимый final loader audit также потребовал
process-scoped writable cache и отдельного повторного запуска; первый export корректно отверг standalone backend
из-за Fabric-only canonical guard; первый latency audit в core не нашел h5py
и был повторен в declared Isaac environment без установки зависимостей.
Remux verifier сначала учитывал новое FFprobe имя вместо `pkt_pts` текущей
версии и неверно ожидал camera-dependent tag offset; исправленные проверки
используют фактическую версию и исходный ledger. Исходные FAIL receipts сохранены.

Проверка опубликованного manifest/inventory через CLI `verify` такжеPASS.
Negative checks намеренно нарушают packet identity/coverage/terminal count,
prepared manifest self-hash, bound camera source,30Hz FPS и row count; экспорт
отклоняет их до публикации. Отдельно измененный training action в настоящем
Parquet должен отвергаться сравнением с verified projection. Terminal leakage
961→960 и объявленный25Hz FPS также проверены независимым remux audit.

## Риски и границы

Это проверка записи/формата, не доказательство исходной цели >30Hz с Quest3.
XR client input отсутствует. Synthetic reach-demo не является human VR
trajectory и не подтверждает успех dual-cube task, хотя использует declared
controlled task label. Dataset admission и physical qualification остаютсяfalse.

Leaf-mesh mirror и standalone CPU fixedroot physics сохраняют ранее описанные
отличия от master. В этом запуске нет optical witness; host snapshot/matrix
проверка не доказывает exposure alignment, полноту материалов или абсолютное
визуальное соответствие каноническому renderer. Формат и causal binding
проверяются отдельно от этих неподтвержденных свойств.

CPU PNG/statistics/decode/QA увеличивают время после эпизода и временное место.
NVENC остается lossy H264; проверки доказывают отсутствие дополнительной
потери при remux/import. Они не доказывают равенство RGB исходному framebuffer.
Private upstream hook требует source pin и повторного аудита при обновлении.
Реальное падение ниже30Hz нельзя скрывать дублями: wall lag/sequence остается
в ledger; выбранная политика повторного эпизода или допуска требует отдельной
квалификации. Текущий prototype fail-closed, без dropped/reused source frames.

## Воспроизведение и откат

Точные команды двух GPU runs и export сохранены в runtime configs/launch
receipts и summary. Экспорт использует core Python
`/data/vla-infrastructure/core-reconcile-validation/20260919T082843.713211Z/env/bin/python`;
`--extract-python` указывает
`/data/vla-infrastructure/isaac61_production/env/bin/python`.
Повторный запуск требует новых output/prepared locators. Portable roots:
recording=run output, isaac61_production=`/data/vla-infrastructure/isaac61_production`,
project_assets=`/data/vla-infrastructure/assets`.

Результат читается стандартным `LeRobotDataset(..., root=..., video_backend="pyav")`.
CLI `verify` проверяет self-hash, весь final dataset inventory, source/prepared
hashes. Это integrity verification; полный decoded QA выполнен при сборке.

Gate: ни один не принимается. Contract changes: нет. Reused/pinned: upstream
Recorder, native validators, PyNvVideoCodec2.2.3, FFmpeg/PyAV, LeRobot0.6.1.
Artifacts: отдельные frozen run/check receipts, внешний SHA inventory; регистрации
в INDEX, без gate binding/contract evidence claim. Human evidence: отсутствует.
Следующий шаг — отдельная Quest/physics/optical qualification и audit следующей
upstream import API перед promotion. Откат: revert изменения этого scope;
installed SDK/runtime packages и selected configs не патчились. Внешние
артефакты сохраняются как история, source запись не изменялась.

## Последующая проверка распределения ресурсов

[CPU QA и фоновая обработка во время записи](../resource30/REPORT.md) проверены
в отдельном bundle от сохранённого38185eb. Он сохраняет baseline выше и
исследует opt-in one-pass QA, CPU affinity и реальные telemetry на одной GPU.
Frozen dataset30 receipts и исходные артефакты не изменяются.
