# Корректность записи: время, изображение и физика master

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted preservation base: `fbdee2055efa325c352e13b321223cdf6c2f3e40`.
Baseline master: `beaedfd1116577fd4d8026232cfb96cba0b030fa`.

## Результат и практическое решение

Причинная последовательность записанных observations/actions/transitions/RGB
сохранена: пропусков и перестановок source IDs не найдено. Но исходная source
очередь8 позволяла получать высокую частоту с устаревающими изображениями:
**sample→доступный NVENC packet p95≈214ms**. Опция source queue1 уменьшила эту
задержку до **82ms при той же частоте52,4Hz**. С MinimalRendering получены
**56,2Hz и p95≈74ms**. Это измерения во время полноценной записи трех камер,
HDF actions/states и encoder drain; Quest не подключен.

Физика **не эквивалентна master во всех режимах**. На плавном записанном эпизоде
пиковое расхождение TCP36µm, в closed-loop41,5µm. При ступени ±5° — около3,2mm:
GPU master допускает transient вращение основания≈0,42°, CPU prototype имеет
fixed root. Гравитационный drop близок, но выполненный contact/grasp fixture
оказался неверным: куб упал до закрытия пальцев. Успешный захват, slip, сила
удержания и физическая квалификация этим исследованием не доказаны.

Оптические source IDs новых диагностических Mesh совпали во всех трех камерах
**211/211**, включая резкие скачки на80px. Полный strict freshness verdict09 —
**FAIL**: right old-ROI threshold превышен. Независимый hold control показывает
постоянный светлый фон уже в никогда не занятой позиции; нельзя выдавать эти
106 превышений за106 случаев temporal ghosting или ослаблять порог задним числом.

Рекомендуется продолжать эксперимент с `--source-queue-capacity 1`, сохранять
отдельные state/sample/packet clocks и проверять текущую физику на реальных
манипуляциях. Default очереди остается8; production selection не изменена.
>30Hz при активном Quest и допустимая задержка реального XR input пока не проверены.

## Что именно измерялось

[План и reuse audit](PLAN.md), [timing metrics](timing_audit/metrics.json),
[камера: результаты и границы доказательства](camera_audit/REPORT.md),
[парное сравнение физики](physics_audit/REPORT.md).
Все новые GPU runs имеют launch/source receipt, полный stdout/stderr, PID/GPU
process monitor, raw output и exit status. Объемный proof bundle размещен в
`/data/ebulochkin/vla-runtime/live30-correctness-20261009`.
[Retention receipt](retention.json) закрепляет SHA256-инвентарь1071 файлов
(≈1,30GB), включая все отрицательные попытки; временные CPU анализы и crops
скопированы с проверкой SHA. [Supplement02](retention-supplement02.json) сохраняет
еще два поздних CPU файла: bundle generator и неудачные проверки локального
core launcher/cache. Финальные проверки используют существующий рабочий core
environment без изменения зависимостей. Shader caches и `__pycache__` не являются доказательством.

Счетчик physics120Hz, четыре native steps/control; камеры30 изображений на
simulation second. Working throughput — число записанных control transitions
на wall second, с final encoder tail. Например,960 transitions соответствуют
32simsec, а56Hz дают примерно1,87RTF. Video30FPS воспроизводит simulation
временную шкалу. Accelerated wall run не проверяет real-time human timing.

Все задержки рассчитаны внутри host CLOCK_MONOTONIC. UTC `wall_time` хранится
отдельно и не вычитается из monotonic/perf_counter. `packet_ready` — host API
вернул пакет из Encode/EndEncode; `packet_write_completed` — завершился Python
bitstream write. Это **не fsync/durable latency**, не время GPU exposure и не
точный аппаратный NVENC completion. Все пакеты одного возвращенного batch
получают общую host ready отметку.

Worker ACK означает завершение capture/Encode submission трех камер. Encoder
еще держит примерно3 кадра; ACK не подтверждает готовность текущего пакета.
Поле `worker_render_submitted_monotonic_ns` поставлено после capture/consumer
вызовов и обозначает завершение host submission, а не render start.

## Прямые измерения задержек во время записи

Здесь p95 steady, для packet latency исключены final-flush кадры; startup source0
отдельный. Сравнение ordinary03→04 использует одинаковые motion/view/frames/
codec/observer, меняет source capacity8→1. Один run на условие, без статистики
между повторными запусками. Точные значения всех трех ролей и SHA inputs в
[timing metrics](timing_audit/metrics.json).

| Run | Источник / Kit view / wall pacer | Complete Hz | Sample→packet p95, ms (max роли) | State receipt→apply p95, ms |
|---|---|---:|---:|---:|
| mesh01 | queue8 / original / без pacer; marker setup FAIL | 51,48 | 211,55 | 20,13 |
| ordinary03 | queue8 / original / без pacer | 52,37 | 214,05 | 20,74 |
| ordinary04 | queue1 / original / без pacer | 52,43 | 81,73 | 21,22 |
| mesh05 | queue1 / original / без pacer; projection FAIL | 51,52 | 81,09 | 20,54 |
| paced06 | queue1 / original / принудительно30Hz; projection FAIL | 29,68 | 118,87 | 32,92 |
| minimal07 | queue1 / MinimalRendering / без pacer | 56,22 | 74,19 | 19,15 |
| mesh08 | queue1 / original / без pacer; wrist occlusion FAIL | 51,53 | 81,62 | 20,87 |
| mesh09 | queue1 / original / без pacer; strict optical FAIL | 48,54 | 86,90 | 22,62 |

Mesh диагностические прогоны добавляют54 Mesh и отличаются от ordinary recording;
их частота не является оценкой production recording. Steady mesh09≈50,26Hz,
complete48,54Hz с коротким210-control эпизодом и drain. Его результат нельзя
использовать как достаточный запас производительности без Quest.

В ordinary03 enqueue→IPC receive p95=137,35ms, в ordinary04=5,66ms. Sample→packet
уменьшилось примерно в2,6 раза при неизменном throughput. State receipt→packet
p95=224,32→91,83ms; у minimal07≈84,62ms. Sample→apply p95≈11,0ms в ordinary04
и8,81ms в minimal07. Native apply здесь — запись команды до четырех physics
steps; это не момент завершения движения или точное actuator torque onset.

Cap1 ограничивает число не подтвержденных source snapshots; snapshot следующего
кадра создается перед backpressure и остается immutable. Изображения не
перезаписываются/не выбрасываются. Encoder owner capacity отдельно остается8;
все существующие GPU lifetime/retirement правила сохранены. Это не жесткая
гарантия wall age: stalled GPU или120s IPC timeout могут дать большую задержку.

При искусственном30Hz wall pacing encoder pipeline из3 кадров уже дает около
100ms ожидания; измерено sample→packet p95=118,87ms и state→packet129,12ms.
Полученные74–82ms ускоренного run нельзя обещать при реальном30Hz операторе.

Ранее demo08 и witness10 давали56–57Hz с MinimalRendering. Ordinary03 использует
original Kit view, поэтому его52Hz нельзя приписывать overhead timestamp
instrumentation: matched minimal07 снова дает56,2Hz. Retained source/overhead
analysis показывает рост renderer.step≈7,61→14,00ms для original view при
практически неизменных native physics/publish/consume/passive stages. Две GPU
нагрузки конкурируют; повторная статистика causal attribution не выполнена.

## Причинность записанных событий и исправление timestamp

[Анализатор](analyze_latency.py) проверяет source0..N, packet ordinals каждой
роли0..N, HDF observations0..N−1/successors1..N, текущие physics counters и
порядок каждой операции:

`capture_observation → decision → native_apply → advance(4) → capture_successor → commit`.

Во всех восьми новых recording runs эти temporal checks PASS. Ordinary03/04/
minimal07 содержат960 transitions и961 frame на каждую камеру; diagnostic
runs210 transitions и211 frames. Successor предыдущего перехода используется
как observation следующего: это выдача сохраненного immutable state, а не
повторный native capture; между ним и решением физика не продвигается.
[Независимый observer01](checks/observer01/results.json) дополнительно проверил
210 controls/840 steps, порядок и единственное продвижение счетчика в `_advance`.

В прежних demo08/10 standalone подменял смысл HDF `wall_time`: cached state
receipt вместо upstream sample time. Первый frozen state получал UTC до startup,
что создавало первый HDF interval≈8,3–8,5s. [Исходный offline audit02](temporal_audit/analysis02.json)
и [master diff](temporal_audit/master.diff) сохраняют это обнаружение.

Теперь `SourceClock.sample()` снова использует `wall_time=time.time()`, как
master. Физический receipt timestamp, его UTC, monotonic timestamp и origin
хранятся отдельно. Возраст начальной frozen копии **не скрывается**: mesh01
state receipt→sample=8123,75ms, но timestamp acquisition кадра новый. Для steady
frames receipt снимается непосредственно после CPU worker reply, до passive
view; это host receive, не native capture внутри CPU worker. NTP изменение
UTC не подменяет monotonic latency. HDF wall_time совпадает с worker source
sample wall_time, а sample monotonic находится внутри capture observer bounds.

Observer cleanup01 первоначально восстанавливал methods после `owner.close`,
что могло повторно поставить закрытые overrides. Исправлено restoration до
close; следующие runs проверяют восстановление owner methods. Данные01 не
повреждены этим cleanup bug, но его старые исходники не являются проверкой
исправления. Точные preimages и source hashes01 сохранены.

Task success отдельно false ожидаем для reach-demo: успешное execution commit
не означает manipulation success. Первоначальный offline analysis01 неверно
включил этот false flag в temporal verdict; corrected02 разделяет понятия.
Оба результата сохранены без переписывания исходных bytes.

## Pixel freshness и projection

Source/HDF/packet ID join не доказывает, что renderer показал нужные pixels.
Для этого использованы camera-relative diagnostic Mesh, публикуемые через тот
же `local @ source_parent_world` batch, что и leaf robot meshes. Это проверка
пути публикации, не полная pixel equivalence всей сцены или материалов робота.

Предыдущий плавный robot replay менял projection менее0,64px/source. Сходство
изображений для current и previous frame практически одинаковое; такой тест
не исключает один кадр lag. Новый тест кодирует12-bit source ID и role anchors,
перемещает маркер на80px и использует удержания. Во09 точные current source/
role IDs читаются211/211 для каждой камеры; current ROI>0,9985, centroid error
<0,967px. Наблюдаемой перестановки/однокадрового отставания **этого маркера** нет.

Strict previous ROI≤0,08 остался неизменным. Role0/2 проходят; role1 превышает
его106 раз, max≈0,1695. Hold control показывает пустую right-slot ROI≈0,096
у source0..15 до первого посещения; другая пустая ROI стабилизируется≈0,121.
Это оптический фон материала/освещения, возможно вместе с history, а не
доказательство106 stale-frame событий. Strict assay09 остается FAIL.

Отрицательные этапы сохранены:01 visibility inheritance скрывал маркеры;
05/06 raw vertical aperture давал ошибочную projection;08 ближняя геометрия
робота заслоняла wrist boards. CPU triangle-ray probe нашел препятствие ближе
0,03717m;09 перенес board с0,06 на0,02m при неизменном near clip≈0,01m.
Ни camera near, ни physics, ни HDF labels этим не менялись.

Isaac Lab master уже использует square-pixel fy=fx; исходные USD apertures
16:9 при output960×600 не дают raw fy=408,89. Для conform expandAperture/
pixelAspect1 effective fx=fy368. Ошибка была в diagnostic projection; это
**не обнаруженное изменение FOV master**. Pixel K и conform policy требуют
проверки вместе с raw USD optics. Точные pinned source bytes и hold/crop данные
в [camera provenance](camera_audit/sources.json).

## Физика и поведение относительно master

Master Kit использует **GPU PhysX**, а не Newton solver; Newton schema/token
в authoring не является свидетельством runtime solver. CPU prototype — native
OVPhysX с derived USD и fixed root. Сравнение использует unchanged master scene
construction и один exact initial native q/dq/target/body state на каждый case.
Основные master runtime/config файлы byte-identical baseline; master checkout
не модифицировался, import hook диагностический, SDK patch не делался.

Общие dt, gravity, TGS/PCM/patch friction,27 масс/инерций/COM совпали по actual
native reads. Но broadphase GPU→CPU PABP, fixed-base authoring и solver cache
различаются; равенство PhysX native binary version не установлено. Mimic из
Newton authoring явно переведен в PhysxMimic с gearing/offset sign conversion;
followers не получают независимые K/D. Детали и67 source pins в
[physics report](physics_audit/REPORT.md) и [sources](physics_audit/sources.json).

| Парный case | Controls на backend | Максимальный результат |
|---|---:|---|
| home_hold | 120 | Body coordinate≈1,91µm, но angular velocity transient до0,236rad/s |
| joint ±5° step | 120 каждый | TCP≈3,20/3,19mm; основание≈0,42°; q-arm≈0,0018rad |
| gripper open/close | 120 | Prismatic q≈0,162mm; pose parity не гарантирует force parity |
| cube drop | 120 | Cube3D difference≈1,15µm; gravity−9,81m/s² до контакта |
| blocked gripper | 120 | Cube difference≈5,15mm/12,3°; fixture не является grasp |
| replay demo08 targets | 960 | TCP≈36,38µm; max body coordinate≈46,7µm |
| closed-loop reach | 240 | TCP≈41,51µm, same upstream DLS controller на CUDA |

Все8 structural trace comparisons PASS: clocks, commands, path/units/body
coverage совпадают. **Numerical acceptance tolerances и physical parity gate
не заданы и не приняты**. Replay не содержит захвата и контакта пальцев с кубом.
Closed-loop assay использует CUDA DLS на обеих сторонах, чтобы изолировать
physics; actual prototype DLS работает на CPU. Поэтому это не полная
эквивалентность двух end-to-end human pipelines.

GPU master — floating articulation с world weld: при ступени вращение основания
7,27–7,29mrad и translation≈13µm; CPU fixed root не двигается. Именно на такой
нагрузке выявляется миллиметровое расхождение TCP. На smoother trajectories
оно значительно меньше; универсальный перенос master labels/behavior на
новую физику нельзя заключать только по этому эпизоду.

Drop сохраняет одинаковую высоту пола и гравитацию. Impact известен лишь в
control-boundary bracket0,2333–0,2667s: trace30Hz не показывает все120Hz substeps.
Contact coverage24 robot links, три props unavailable (NaN+mask, не ложный0).
Legacy body_velocity metric смешивает m/s и rad/s; отчет отдельно разделяет их.

Blocked fixture куб уже на столе к закрытию. CPU matched empty-close меняет
только pose/velocity куба; воспроизводит aperture≈50,43µm и forces≈20,49mN,
почти как ошибочный fixture. Это поддерживает finger self-contact explanation;
GPU matched empty-close и corrected true grasp не выполнены. Нельзя объявлять
захват успешным или доказать force/contact equivalence.

Physics pair01 FAIL до шагов (venv Python symlink resolve потерял environment).
Pair02 все8 raw traces завершены, но launcher exit1: отсутствовал canonical
report file. Оба отрицательных launch status сохранены. Исправленный pair03
home_hold завершился exit0,120 controls/480 native ticks на backend с прямым
GPU delta4 assertion и clean cleanup; он не переписывает scope/status pair02.

## Изменения, откат и остающиеся ограничения

Изменены SourceClock sampling semantics, отдельные monotonic timing поля,
packet host receipt/write ledger; добавлены opt-in host observer/marker/wall
pacer и source cap1. Native diagnostics flag по умолчанию false. Physics worker
props/velocity читаются только для assay; обычная физика/encoder codec/labels
новыми timing изменениями не перенастраивались. Новые scripts — диагностические
adapters/comparators существующего native API, не robotics framework.

Откат исходников этого этапа — revert данного audit commit к trusted base.
Отключение `--audit-host-events`, `--mesh-freshness`, `--pace-hz` и выбор
`--source-queue-capacity 8` возвращают исходный экспериментальный режим очереди.
Derived render/physics USD находится только в output bundles. Исходные assets,
master, system SDK и production selection не переписывались; удаление артефактов
не нужно для отката и не допускается как способ скрыть FAIL.

Не проверено: реальный Quest source/frame age и DeviceIO, motion-to-photon,
>30Hz при активном Quest, durable fsync, native120Hz contact history, true grasp
и slip, все материалы/все body pixels, длительный soak/межпрогонная статистика.
Freshness marker и HDF IDs не заменяют эти проверки. S2/D1 gate bindings пусты;
physical qualification и dataset admission не заявляются.

## Проверки и регистрация

[Instrument01](checks/instrument01/results.json):42 CPU tests PASS;
[source-queue01](checks/source-queue01/results.json):33 tests PASS, включая
backpressure/no-loss/error paths. Observer01 independent32checks PASS.
Physics native7tests,20property reads,6analytic comparator cases и launcher
report-copy unit retained вместе с exact environments/preimages.
[Repository checks02](checks/repository02/results.json) запускаются от указанного
trusted preservation base: docs, spec refs, resolved contract, selective
manifest, Ruff и18 relevant pytest modules. Первый repository01:319 tests PASS/38 SKIP, все functional/doc проверки PASS,
но whitespace check FAIL на verbatim CodeGraph/git-diff transcripts. Исходные
bytes сохранены;02 явно исключает только четыре raw transcripts и raw logs
из whitespace check, все code/docs проверяются. [Retention SHA verification](checks/retention-verify.json)
подтверждает все1071 proof files. **Финальный02 PASS:319 tests passed,38 skipped**, docs/spec/contract/manifest/
Ruff и whitespace checks PASS. Подробности
в receipt02; никакой hardware qualification из CPU tests не следует.

Все bundle files зарегистрированы в INDEX; frozen outputs исторические,
maintained scripts/REPORT current. MANIFEST refresh сохраняет выбранный набор
members. Исторические bytes относительно trusted base защищены lint_docs.
[Заключительные проверки документов и staged diff](checks/final-docs/results.json)
проверяют последнюю регистрацию receipts после repository02; код после02 не менялся.
