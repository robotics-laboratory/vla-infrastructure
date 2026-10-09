# Временная причинность и физическое поведение относительно master

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted base: `fbdee2055efa325c352e13b321223cdf6c2f3e40`.
Baseline master: `beaedfd1116577fd4d8026232cfb96cba0b030fa`.

Проверить задержки, свежесть событий и физическое поведение single-GPU
диагностического recorder относительно master. Частота записи и совпадение
начального состояния не заменяют проверку времени доступности изображения,
реального XR input или динамической эквивалентности физики.

CAPABILITY: проверяемая временная связь observations/actions/physics/RGB и
сопоставимое физическое поведение при одинаковых native commands.
REUSED: canonical transition/HDF recorder, immutable source IDs, существующие
OVRTX/encoder ledgers; native Kit и standalone PhysX без нового physics solver.
GAP: отсутствуют per-packet host timestamps и paired dynamic baseline.
ADAPTER: read-only offline анализ сохраненных08/10; узкий comparator одинаковых
native120Hz траекторий. Новые runtime probes и GPU запускает координатор отдельно.
ENVIRONMENT: HDF читается имеющимся production Python с numpy/h5py, без Kit/CUDA
imports и изменения зависимостей. Core environment не содержит h5py; ошибка
первой проверки доступности сохраняется.

## План проверки

1. Сопоставить исходники causal capture/decision/apply/step/successor/commit с
   указанным master; различать неизменный протокол и измененный state backend.
2. Проверить HDF observations/successors, physics steps, epochs и worker/packet
   sequence; измерить интервалы только внутри совместимых clock domains.
3. Разделить source generation, sampler capture, enqueue, render submission,
   GPU completion, packet return и durable storage. Отсутствующие события
   обозначить как непроверенные; реконструкции назвать bounds/approximations.
4. Сравнить одинаковую начальную сцену и команды на native120Hz, включая
   обе руки,27 rigid bodies, grippers/contacts и transient events. Comparator
   сообщает различия; критерии физической эквивалентности задаются отдельно.
5. Сохранить исходники анализа, команды, SHA, отрицательные результаты и
   raw outputs. Финальные docs/spec/contract/manifest/topic checks выполняются
   от trusted base после объединения результатов; historical bytes неизменны.
6. Opt-in `--mesh-freshness` добавляет только в derived render overlay54Mesh
   в независимом видимом namespace с явной привязкой к матрицам трёх existing
   cameras. [mesh_freshness.py](mesh_freshness.py)
   задаёт скачки80px, удержания и optical source/role bits; публикация использует
   прежнее `mesh_local @ source_parent_world` и единственный SnapshotRenderer
   batch. Native physics, исходная USD и HDF labels не меняются. После parent
   GPU запуска [test_mesh_freshness.py](test_mesh_freshness.py) декодирует все
   три потока на CPU и измеряет centroid/current/previous-disjoint ROI.
   Это camera-relative Mesh phase test, не доказательство отсутствия history
   для всех материалов и не equivalence arbitrary robot bodies. CPU self-test
   проверяет ideal current, stale-frame rejection и25%ghost rejection; его
   успешность не заменяет фактический GPU receipt. Отключение flag полностью
   убирает marker injection и динамический helper hook.

[REPORT](REPORT.md) — текущий owner результатов. Temporal outputs находятся в
`temporal_audit/`; bulk runtime locators остаются в прежнем meaningful_episode
хранилище. Gate bindings пусты; ни S2, ни D1 этим аудитом не принимаются.
