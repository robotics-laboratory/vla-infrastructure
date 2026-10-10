# Использование свободных ресурсов во время записи

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted preservation base: `38185eb57016cb86786ffbc9846f91af1d629178`.
Branch: `research/live-camera-recording-30hz`.

Ускорена экспериментальная проверка готового датасета: один полный uint8
DataLoader-проход вместо двух полных float32-проходов. Измеренное время QA
960 строк снизилось с306 до94 секунд с двумя workers и до65 секунд с четырьмя.
Проверка каждого action/state и каждого RGB fingerprint сохраняется. Фоновая
сборка предыдущего эпизода уже испытана вместе с записью; результаты и границы
применимости приведены ниже. Это эксперимент с синтетическим XR input;
производительность с подключённым Quest требует отдельного испытания.

[План и reuse audit](PLAN.md); предыдущая [сборка30Hz dataset](../dataset30/REPORT.md);
[известные отличия физики и времени](../temporal_physics/REPORT.md).
[CPU receipts](cpu-results.json), [семь основных cases](matrix-results.json)
и [два QA contention cases](qa-results.json) содержат exact commands, hashes,
тайминги и scoped PASS. Bulk source/trace/video/datasets остаются вне Git.
[Retention receipt](retention.json) закрепляет 866 файлов, 4.44GB, полный SHA256 inventory
и три явно диагностических read-only video links. Внешний locator:
`/data/ebulochkin/vla-runtime/live30-resource-20261010`.
[Post-publication checks](published-export-checks.json) покрывают четыре exports.
[Полный export8E](full-e8-results.json) завершает end-to-end проверку настройки.

## Сохранённое исходное состояние

До изменений checkout был чистым на указанном trusted base. Создана и отправлена
в origin ветка `checkpoint/live30-before-resource-20261010-38185eb`.
Полный Git bundle22,059,863 bytes проверен через `git bundle verify` и хранится
в `/data/ebulochkin/vla-runtime/live30-resource-20261010/checkpoint/branch.bundle`.
Рядом находятся пустые worktree/index patches, исходный status, verification log,
SHA receipt и receipt remote ref. Это сохраняет tracked source/history;
SDK и окружения не менялись. Для восстановления без разрушения текущего WIP:

```sh
git clone --branch research/live-camera-recording-30hz \
  /data/ebulochkin/vla-runtime/live30-resource-20261010/checkpoint/branch.bundle \
  /tmp/live30-checkpoint-recovered
```

Эта команда описывает восстановление; отдельное восстановление не запускалось.

## CPU QA и upstream audit

Один неизменный `dataset-reach03`:960 строк, три видео960×600, исходная projection
и RGB fingerprints из manifest. Declared core: LeRobot0.6.1, PyTorch2.7.1,
PyAV; SHA installed sources и exact scripts сохранены вне Git. Новый helper
использует public DataLoader spawn, prefetch_factor=1, batch_size=1,
persistent_workers=False, pin_memory=False. [PyTorch2.7 DataLoader](https://docs.pytorch.org/docs/2.7/data.html)
определяет multiprocessing и prefetch; installed source SHA закрепляет испытанную
реализацию. Собственный decoder, writer или worker scheduler не добавлялись.

| QA | Wall, с | Ускорение | CPU self+children, с |
|---|---:|---:|---:|
| canonical, два полных прохода |305,742|1,00×|827,942|
| один проход, workers0 |175,511|1,74×|460,850|
| один проход, workers2 |93,914|3,26×|506,156|
| один проход, workers4 |65,014|4,70×|650,483|

Все960 labels/state/task/indices/timestamps и2880 RGB hashes совпали. Дополнительно
первые, средние и последние две строки проверены через обычный float32 API:
18 RGB tensors точно равны uint8/255. UInt8 используется внутри QA; training
API и опубликованные видео не меняются. Тесты включают15 unit tests и
три проверки настоящего копированного Parquet/ожидаемого source hash: action,
timestamp и pixel identity corruption правильно отклонены. Полный inventory
оригинального dataset до/после совпал. Диагностические symlinks на исходные
read-only videos принадлежат negative fixture, не опубликованному датасету.

Workers4 быстрее отдельно, но используют больше CPU и Python processes.
Для фоновых сравнений выбран workers2. Peak parent RSS около1,2GiB; rusage
largest-child около1,2GiB — максимум одного ребёнка, не сумма памяти всех.
Prefetch payload ограничен: около5,18MB на uint8 триплет, плюс текущие frames,
до шести retained sample triplets, decoder/preroll buffers и runtime workers.
Torch/OMP/MKL threads1 не ограничивают все native PyAV threads.

Installed `video_utils.decode_video_frames_pyav` открывает container на каждый
query, seeks к ключевому кадру и переводит preceding GOP frames в RGB до выбора
нужного timestamp. Workers параллелят повторную работу, но не устраняют её.
Upstream cached decoder/backend не менялся и не испытан в этом этапе.
Public AsyncImageWriter не включён: его Queue/JoinableQueue не имеет capacity,
что требует отдельной проверяемой стратегии ограничения RAM. Exact source
snapshots и подробный CPU audit лежат в `cpu-qa/` внешнего bundle.

## Методы измерения live recording

RTX4090, i7-13700K,24 logical CPUs, около31GiB RAM. На этой машине0–15 —
восемь пар SMT на P-ядрах;16–23 — отдельные E-ядра. Recording на P-ядрах
в тестах имеет affinity0–15; background либо делит эту группу, либо использует
16–19, nice10. Сначала сравнивается сама affinity без background.

Original Kit view, existing standalone CPU PhysX owner, GPU live render/NVENC,
source queue1, reach-demo без diagnostic witness/mesh markers, XR core enabled.
Все paced cases имеют960 controls/961 camera sources, включая120 warmup;
uncapped cases1920 controls/1921 sources. Физика и source labels не менялись.
Uncapped измеряет throughput capacity: его simulation time по-прежнему идёт
с четырьмя120Hz physics steps/control и сеткой30Hz, а wall time ускорен.

Пассивный monitor каждые0,5s сохраняет /proc/stat по CPU, RAM/swap counters,
owned process trees, status/io, GPU activity/VRAM/power/temperature/clocks,
encoder/decoder utilization. Clock join uses CLOCK_MONOTONIC; Unix timestamps
не смешиваются с ним. GPU metrics относятся ко всему устройству. Activity
не равна SM/RT occupancy. RSS tree суммирует shared pages повторно; MemAvailable
лучше отражает доступную память. CPU tick interpolation и короткие exited
fragments имеют явно сохранённые ограничения. Monitor также создаёт нагрузку;
сравниваемые cases используют одинаковую instrumentation.

Фоновый полный export использует один уже завершённый предыдущий эпизод.
Запуск происходит по реально видимой flushed post-warmup performance_step,
не по end-only worker ledger. Harness ждёт завершения/drain обоих процессов.
Есть общий lock, freshness outputs и ограниченные timeout; ошибки и owned
descendant cleanup проверены CPU smoke. Физические устройства не управлялись.

| Во время записи | Control wall Hz | С encoder tail, Hz | Control p95 / p99, ms |
|---|---:|---:|---:|
| paced, все CPU, quiet |30,000|29,939|20,55 /23,77|
| paced, P-only, quiet |30,000|29,921|16,86 /22,28|
| paced, P-only + полный export на P |30,000|29,930|17,40 /22,91|
| paced, P-only + полный export на4E |30,000|29,936|18,72 /22,87|
| uncapped, все CPU, quiet |53,185|52,866|22,65 /26,05|
| uncapped, P-only, quiet |52,900|52,504|22,52 /25,93|
| uncapped, P-only + полный export на4E |53,044|52,860|22,46 /25,25|
| uncapped, P-only + QA на4E |52,662|52,492|22,23 /25,49|
| uncapped, P-only + QA на8E |52,930|52,499|22,02 /26,45|
| uncapped, P-only + полный export на8E |53,098|52,850|22,36 /25,39|

Полный export на4E перекрыл реальные decode/PNG stages24–30s, QA-only cases
перекрыли положительные CPU ticks именно `pt_data_worker`27,67/27,36s, а не
только процесс startup. Все encoded source ordinals сохранены:961 либо1921
packet каждой камеры, включая terminal. Во время QA8E MemAvailable minimum
16,57GiB; во всех десяти cases device VRAM max7419MiB, GPU temperature max64°C.
Это не evidence исчерпания RAM/VRAM или температурного ограничения.

Измеренная QA4E165,213s → QA8E123,737s:25,1% быстрее, средняя background CPU
нагрузка3,34 →4,57 полностью занятых logical cores; peaks4,04 →5,84. Остальные
ядра не заняты этим процессом. GPU activity при uncapped по-прежнему около100%.
Average throughput с encoder tail практически совпал с P-only control, но
tail latency не идеальна: max control73,57ms и p99.9=45,39ms в QA8E против
60,14/30,34ms в quiet P. По одному run это наблюдение, не доказательство
причины каждого spike. Dropping/дублирование source frames не обнаружены.

## Наблюдения о ресурсах и постобработке

Тихая paced запись: GPU activity mean54,3%, NVENC2–3%, NVDEC0%; device VRAM
max7181MiB, MemAvailable minimum около18,57GiB, CPU recorder tree около4,16
полностью занятых logical cores. GPU temperature max62°C, power около210W.
В uncapped P-core control GPU activity mean99,7%, NVENC4–5%, power около299W,
temperature max63°C. Свободная VRAM и отдельный encoder не доказывают запас
времени GPU на максимальной частоте. Для дополнительной постобработки сначала
проверяются CPU ресурсы; запас GPU нужен для настоящего XR workload.

В paced shared-background export полный32s episode собирался160,813s:
decode/add_frame62,896s, save/stats4,232s, QA92,753s. Recording overlap27,13s
с положительными CPU ticks; реальная перекрытая стадия — decode/PNG, не QA.
При isolated E-core export полное время250,912s: decode/add_frame88,333s,
save/stats6,060s, QA155,248s. Изоляция не ускоряет работу сама по себе.
При непрерывном поступлении32s episodes такая materialization накапливала бы
backlog. Проверенная очередь здесь — один предыдущий финализированный episode;
надёжные raw HDF/bitstreams и финальная публикация LeRobot остаются разными этапами.

Отдельный QA-only contention assay нужен для более тяжёлой reader/IPC стадии:
то же960-row source, workers2, низкий приоритет, uncapped recording на P-ядрах.
Оба случая полностью завершены и проверили все960 строки/2880 RGB плюс18 float
sample images; обработка продолжалась после остановки recording до полного drain.
Известный32s source episode остаётся immutable. Независимая post-publication
проверка первых трёх готовых exports проверила все hashes/source bindings и реальные
uint8/float reader first/middle/last rows после atomic rename.

Последний whole-pipeline8E export завершён:210,147s, включая89,064s decode/PNG,
6,089s save/stats и113,688s QA. Во время uncapped recording positive CPU overlap
33,28s, реальный decode/PNG overlap29,62s; QA стадия отдельно покрыта QA-only
assays. Все960 rows/2880 RGB и18 float sample views PASS; source bindings и
terminal exclusion сохранены. Это на16,9% быстрее аналогичного uncapped4E
export252,817s, но медленнее shared P-core export160,813s. Изоляция покупает
предсказуемое разделение CPU ценой времени materialization.

## Применимая настройка и дальнейшая работа

Проверенный кандидат этой машины: recording affinity0–15; один предыдущий
finalized episode в фоне, nice10, affinity16–23, `--qa-workers 2`. Можно ускорять
QA до4workers при отдельной обработке после записи; fastest isolated CPU
result65s не переносится автоматически на E-core/Quest workload. Affinity IDs
зависят от topology и не должны становиться универсальным default.

Экспорт в существующем declared core environment, с новым output:

```sh
HF_HOME=/tmp/live30-export-cache/hf \
HF_DATASETS_CACHE=/tmp/live30-export-cache/hf-datasets \
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
nice -n 10 taskset -c 16-23 \
  /data/vla-infrastructure/core-reconcile-validation/20260919T082843.713211Z/env/bin/python \
  tools/isaac_vr_live_dataset.py materialize \
  --prepared /data/ebulochkin/vla-runtime/live30-dataset-20261010/prepared-reach03 \
  --output /data/ebulochkin/vla-runtime/new-live30-dataset \
  --repo-id local/new-live30-dataset --qa-workers 2
```

Frozen command specs сохраняют explicit argv и являются источником точных команд.
Without `--qa-workers` the canonical QA remains the default. Existing selected
RUN/DIAG/RECORD and runtime configurations are unchanged. A production background
queue/scheduler was not added: the assay owns one bounded previous episode.

Следующее узкое место — repeated random-access GOP decoding и synchronous PNG
staging, а не NVENC. Следующий полезный этап: проверяемый cached/sequential reader
и ограниченная parallel PNG/statistics стадия через upstream API. NVDEC имеет
отдельный свободный engine, но CUDA color conversion/copies/context contention
ещё не измерены; его нельзя считать доказанным ускорением рядом с активным XR.
Без устранения этих затрат непрерывная финальная materialization30Hz не доказана.

## Границы результата

Одиночные короткие runs с прогретыми файлами, без рандомизации и cache flush.
Это не длительный soak test и не гарантия tail latency. Pacing допускает catch-up
после опоздания; wall intervals, host control duration и complete throughput с
encoder tail различаются. Все packet ordinals/byte ranges проверяются отдельно.
Source/snapshot binding сохранён; sample→packet ready — host API boundary,
а не camera exposure/GPU completion/fsync. Новый optical source proof не заявлен.
Ранее выявленные physics-master differences этим изменением не устраняются.

GATE: эксперимент vr.performance, gate bindings=[]; S2/D1 не продвигаются.
REUSED: recorder, render/encoder, schema/projection, source integrity, LeRobot.
PINNED / VERIFIED: versions/SHA, row/pixel checks и конкретные commands/outputs.
EXECUTION PROFILE / ENVIRONMENT: synthetic injected XR в Isaac; CPU export в core.
CONTRACT CHANGES: none. PROCESSORS / ADAPTERS: source label processors unchanged;
отдельный opt-in QA и passive experiment helpers. HUMAN EVIDENCE: none.
BLOCKERS / REOPEN REASONS: actual Quest, длительная устойчивость, backlog и
дальнейшая оптимизация PNG/reader. NEXT GATE: сначала измерение с Quest и
сохранение required registered evidence; этот отчёт его не заменяет.

EVIDENCE ADDED / ARTIFACTS ADDED: отдельные frozen experiment summaries,
source/command/output receipts и SHA inventory; resolved contract/gate evidence
не изменяются. Все source snapshots и неудачи сохранены; SDK byte changes нет.

TESTS: [repository01 receipt](checks/repository01/results.json) — 440 passed,
38 skipped; Ruff PASS, documentation governance PASS с trusted base выше,
spec references PASS, MANIFEST PASS (110 reviewed paths), resolved contract
structurally/semantically valid. Пропуски относятся к optional environment tests;
FINAL RC NOT READY и существующие gate blockers сохраняются. Проверены также
15 новых unit tests, реальные negative probes и десять recording cases;
это не physical/manual qualification.

[Final documentation/source/inventory checks](checks/final-docs/results.json)
сохраняют команды и результаты проверки финальных registrations, SHA всех
retained files и неизменности исходников относительно repository01. Все новые
documentation files зарегистрированы в INDEX как vr.performance experiments;
frozen receipts имеют mutable=false. Старые historical bytes сохранены.
