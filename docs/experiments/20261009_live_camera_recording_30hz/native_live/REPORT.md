# Полноценный native live: реализованный прототип и границы результата

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted preservation base: `114a2256913cbd915d59e0890915c314d64355f7`.
Branch: `research/live-camera-recording-30hz`. Gate bindings=[].

Реализована и испытана экспериментальная камера основной живой Kit-сцены:
существующие camera prims → native RenderProduct → owned CUDA RGBA → NVENC
и GPU SceneUI preview. Canonical state/actions/HDF и три видеопотока пишутся
во время движения; LeRobot conversion в этих прогонах отсутствует. Этот путь
не читает HDF для рендера, не создаёт сцену из recorder snapshots и не применяет
записанные camera/robot transforms. Исходная native Kit физика проверена
отдельно от существующего standalone physics worker.

**Цель >30Hz с подключённым Quest и примерно50Hz без него не достигнута.**
Контрольный длинный native callback run дал37.9Hz (первый36.6Hz), длинный
standalone callback run41.5Hz без Quest. Временное соответствие camera pixels и source state/actions
не подтверждено: строгие optical assays FAIL. Это работающий live media
прототип, а не готовый admissible30Hz training dataset или promoted runtime.

[План/reuse audit](PLAN.md), [сводка всех попыток](results.json),
[retention](retention.json), [repository checks](checks/repository02/results.json).
Предыдущие [physics/temporal findings](../temporal_physics/REPORT.md) и
[resource research](../resource30/REPORT.md) относятся к отдельной snapshot-fed
renderer архитектуре; её53Hz не являются результатом native main-stage камер.

## Что изменилось

Опция `--media kit` в существующем diagnostic runner создаёт три native products
960×600 на уже существующих wrist/scene cameras после начала state-only RECORD.
`--physics-source native` использует исходную IsaacLab/Kit физику;
`standalone` сохраняет ранее исследованный CPU PhysX worker. Последний передаёт
текущие physics tensors в обычную main Kit visual scene, как в его RUN path;
это не replay записанного эпизода, но физическая эквивалентность мастеру от него
не следует. Основная новая проверка использует native physics без worker.

Вместо второго preview-camera acquisition используются существующие upstream
SceneUI панели. Одна immutable GPU allocation передаётся PacketEncoder и
preview provider; pointers записаны в ledger, exact-object fan-out проверен
CPU tests. UI partition исключает panel geometry из sensor cameras. Показ
панелей в настоящем Quest и GPU provider completion остаются непроверенными.

Три режима захвата: `pump` — дополнительный camera-only app.update;
`orchestrator` — supported held-time step с wait_for_render;
`callback` — PostProcessDispatchUngated → SdRenderVarPtr(LdrColorbuff) →
SdFrameIdentifier → connected Python consumer. Последний копирует CUDA buffer
на producer stream прямо в OmniGraph compute, сохраняет same-result metadata,
не добавляет app.update в observation capture и не опрашивает RGB annotator.
Ненужные RGB/ReferenceTime nodes убраны в финальном callback варианте.

Каждый accepted transition по-прежнему идёт через исходные processors,
canonical recorder и D0 digest checks. Encoder сохраняет packet/source tags,
полные byte extents и terminal successor frame. HDF содержит raw state/actions,
RGB companion — три live H264 streams и frame/result ledger. Сам HDF не содержит
новые RGB массивы; это явно экспериментальный companion, не новый selected
source profile. LeRobot импорт этого native companion не реализован, пока
связь пикселей с source state не квалифицирована.

## Измерения

Все GPU runs выполнены последовательно на одной RTX4090, исходном i7-13700K,
affinity0–15, synthetic injected XR input, wrist/scene960×600. XR admission
flag включён; Quest не подключён, runtime profile/headset session throughput
не подтверждены. Диагностический reach-demo двигает руки и grippers; физических
команд роботу нет.20 warmup +160 measured controls в optical runs;60+960 в
normal runs. Native media пишет181/1021 кадров на роль, включая terminal.

Точные rates, source hashes, preview counts, resource statistics, optical и
HDF joins находятся в results.json. Steady rate исключает warmup; complete rate
включает encode tail. Ни schema `passed=true` у runner, ни rate>30 сами по себе
не устанавливают camera freshness или Quest success.

| Путь | Steady без Quest | Результат актуальности |
|---|---:|---|
| Main Kit RGB, pump, standalone physics |27.27Hz| устойчивый optical lag2 |
| Held RGB, standalone physics |12.75Hz| identity почти current; strict optical FAIL |
| Held RGB, native physics |12.24Hz| identity почти current; strict optical FAIL |
| Main Kit LdrColor, pump, native, shared preview |24.90Hz| устойчивый optical lag2 |
| Held RGB, native, shared preview, fast settings | около12Hz | lag0 после initial; contrast/ghost checks FAIL |
| Connected callback, native, shared preview, optical |35.55Hz| assay FAIL; scene lag3, wrists phase/contrast errors |
| Connected callback, native, normal1020 transitions |36.62 /37.90Hz| optical witness отсутствует; freshness unknown |
| Connected callback, standalone, normal1020 transitions |41.47Hz| optical witness отсутствует; freshness unknown |

Финальные guards также проверяют CUDA device0, RGBA8 TextureFormat, strides,
повторные/разные/регрессирующие result identities. После smoke добавлена
проверка возврата scoped settings к исходным значениям; она покрыта CPU suite,
отдельный GPU run этих последних строк не повторялся.

Не следует вычитать постоянный лаг из source IDs: текущая marker publication
в callback assay происходит после обычного render pump, а камера и body/Fabric
publication имеют собственные фазы. Lag3 показывает несостоятельность текущей
привязки; он не является доказанным универсальным latency камеры. При больших
движениях wrist bits становятся неоднозначными. Held capture устраняет
устойчивый identity lag, но не все startup/ghost/contrast failures.

Product-specific RTX schemas AA=`none`, ray reconstruction disabled, scoped
low-latency/async flags проверены отдельно. Старый global carb setting оказался
недостаточным основанием утверждать pixel freshness; product overrides также
не дали строгого optical PASS. Уменьшение history synthesis ухудшает качество
изображения и само по себе не решает source publication matching.

## Корректность и ресурсы

Offline verifier повторно использует canonical_committed_transition,
verify_committed_transition_sample и terminal snapshot verifier. Проверяются
каждый action/state/payload/snapshot digest, promoted successor, точные media
source IDs и шаги, N+1 terminal coverage, все packet tags/byte hashes/extents.
Это проверка ledger binding, **не независимое доказательство image content**.
На native path global SimulationManager step отличается от локального Lab step
на6 стартовых шагов; проверяются постоянный offset и все delta/time increments,
включая terminal. Это upstream два counter, а не отставание media на6 кадров.
Первые версии без setup.json сохраняют provenance unknown; setup не придуман
постфактум. Исправленные joins и первая неудачная verifier попытка сохранены.

В direct-native probe GPU utilization около50.5%, encoder2.3%, VRAM3.95GB,
CPU tree около3.14 core-equivalents. В held probe GPU около77%, encoder1.2%.
Точное sampling window/coverage и остальные runs представлены в results.json.
CPU/RAM/VRAM не заполнены, но свободная память не ускоряет последовательные
Kit/Fabric/render fences. Полностью асинхронный pool требует подтверждённого
resource lifetime; выкидывание completion fences без такого контракта не выбрано.
Фоновой сборки предыдущих эпизодов во время этих native runs не было.

## SDK research: практический следующий путь

Installed Kit110.3, IsaacSim6.1, IsaacLab17.0.2, Replicator1.13.36 и
SyntheticData0.6.17 исследованы по исходникам, SDK headers и NVIDIA первичным
документам. Четыре агента проверили native camera graph, SceneUI provider,
state/media joins и низкоуровневый FSD resolver. Хэши и verbatim excerpts
сохранены в external research bundle; источники закреплены независимо от
текущих web docs.

- [SdFrameIdentifier](https://docs.omniverse.nvidia.com/extensions/latest/ext_omnigraph/node-library/nodes/omni-syntheticdata/sdframeidentifier-1.html)
  даёт metadata реального render result. В прототипе все три роли проверяют
  одинаковую identity и её advancement. Это полезный callback seam, но metadata
  времени не является physics-step/source-token join.
- [ByteImageProvider](https://docs.omniverse.nvidia.com/kit/docs/omni.ui/2.26.8/omni.ui/omni.ui.ByteImageProvider.html)
  принимает GPU memory. В установленном Python API нет stream/event/ACK;
  current/previous owners плюс CUDA context fence не доказывают completion
  graphics queue. Поэтому preview buffer reuse нельзя объявлять квалифицированным.
- [Replicator changelog](https://docs.omniverse.nvidia.com/kit/docs/omni_replicator/1.13.30/source/extensions/omni.replicator.core/docs/CHANGELOG.html)
  фиксирует переход FabricReader на current StageReaderWriter ради FSD.
  Attribute annotator нельзя считать historical source-token reader.
- Exact FSD resolver найден в installed IFabricContextManager:
  getFabricIdForTime(USD stage, FrameIdentifier, sample time, ...) выдаёт
  FabricId/SampleIndex/storage/read-lock реального rendered sample. Но headers
  не дают definitions FrameIdentifier/HydraRenderResults и Python binding.
  Нужен supported NVIDIA bridge, возвращающий copied source tag/poses из
  immutable rendered sample. Угадывать layout C++ struct нельзя.
- InstanceMappingWithTransforms из same renderResults — кандидат независимой
  проверки rendered body transforms. Добавляет semantics/instance AOV cost;
  не внедрён и performance benefit не утверждается. Naive SIMULATION→POST_RENDER
  scalar wire также не доказан: inspected cross-stage connector передаёт exec,
  а не произвольные historical scalar values.
- [RENDERER_RECORDING_COMPLETE](https://docs.omniverse.nvidia.com/kit/docs/omni.usd/1.13.61/Events.html)
  позволяет native operations после recording до GPU submit. Python получает
  opaque graph handles; это отдельная native extension задача, не готовый copy API.
- OVRTX attach принимает OVStage instance ABI, а не main Kit USD/Fabric ID.
  BORROW читает уже подключённый OVStage; он не создаёт мост к main stage.
  Installed Lab экспортирует USDA→новый OVStage→writes transforms. Такой путь
  оставался бы второй сценой, поэтому не подменяет проверенный native live path.

Рекомендация: развивать connected same-result callback, затем exact native
source receipt/FSD bridge и completion-aware fan-out. Ускорение извлечения уже
проверено; source matching и реальный Quest остаются обязательными. Стоимость
такой доработки больше небольшого изменения Writer: потребуется разобраться
с native publication/history lifetime, а возможно узкая C++ extension или
изменение SDK. Ни гарантия50Hz, ни успешный Quest benchmark не получены.

## Неудачи, восстановление и воспроизводимость

Все неудачные попытки сохранены: неправильный initial assay CLI/config;
неверный Orchestrator enable key и остановленный owned process; первоначальные
CPU test failures с последующими fixes; failed optical checks; invalid format
import и ошибочный timeline getter в teardown smoke; первый verifier ошибочно предполагал абсолютное step/120 без offsets.
Один прогон отклонил auto-review из-за предполагаемого reused output directory;
проверка показала config-only directory, дальнейший run перенесён в новый locator.
Результаты прежних runs не перезаписывались. Точные source bytes каждой GPU
попытки находятся рядом с её assay receipt. Отдельное исправление ошибочной
интерпретации agent clock audit также сохранено; HDF bytes не менялись.

До работы сохранён checkpoint ref
`checkpoint/live30-before-native-20261010-114a225` и verified branch.bundle.
Состояние SDK/environments не редактировалось. Products/templates/panels
создаются только экспериментом и удаляются; recorder observer, scoped settings
и camera session partition opinions восстанавливаются. Orchestrator teardown
останавливает capture, ждёт delayed setting restoration при frozen physics;
исправленный short GPU smoke завершился без cleanup errors.
Exact source-only checkpoint позволяет откатить tracked code; настройки Kit
также возвращаются к запускным при новом процессе. Физическая квалификация
после этих edits не подразумевается.

Пример isolated diagnostic (только симуляция, source/pixel admission=false):

```sh
OMNI_KIT_ACCEPT_EULA=Y ISAACLAB_CXR_ACCEPT_EULA=1 \
PYTHONPATH=/data/ebulochkin/vla-runtime/live30-deep-20261009/optional-pynvcodec \
/data/vla-infrastructure/isaac61_production/env/bin/python \
 tools/run_single_gpu_live_recording.py --output /tmp/native-live-distinct-output \
 --media kit --physics-source native --kit-capture callback --kit-fast --xr \
 --motion reach-demo --frames 960 --warmup 60 --no-witness
```

Каждый запуск требует нового output и отдельного assay/report, как в сохранённых
config.json. CPU verifier/optical scripts запускаются после закрытия HDF/video.
Normal recording не имеет optical witness, поэтому optical verifier к нему
не применяется. Selected `./run-vr`/`record` и normative source profiles не
продвинуты; S2/D1/DQ contracts/gate evidence не изменены. Registration: новый
experiment subbundle, explicit INDEX entries; selective MANIFEST membership
проверяется, bulk runtime artifacts остаются вне Git.

Bulk bundle заморожен:1020 файлов,1,391,993,670 bytes; inventory SHA256
`997da8bd0cd74163f0db1cc423dadfa37434b73eb5ddc92d82012e318d09d014`.
Locator: `/data/ebulochkin/vla-runtime/native-live-20261010`. Нет symlink video
зависимостей; media/source/CPU failures включены в inventory. Repository checks
сохраняются отдельно в Git; новых writes в этот frozen bulk root не выполняется.

Repository validation:481 tests PASS,38 optional dataset checks SKIP в core
без h5py; полные HDF joins отдельно выполнены Isaac Python с h5py.14 clock/packet
negative/positive CPU checks сохранены в external agent audit. Первая repository
попытка сохранила stale INDEX manifest и ошибку синтаксиса Ruff noqa; затем
обновлён только уже selected manifest hash INDEX и исправлен comment.
[Первая попытка](checks/repository01/results.json) сохранена; итоговые повторные
проверки и [final docs](checks/final-docs/results.json) отдельные.
