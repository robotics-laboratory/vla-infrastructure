# Native live: источник кадра и оставшийся критический путь

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted preservation base: `835d0b3ad1b8d211fb50f9d79b6d16c020454c93`.
Исходная точка сохранена ref `checkpoint/live30-before-native-deep-20261010-835d0b3`
и verified bundle в `/data/ebulochkin/vla-runtime/native-deep-20261010/checkpoint`.
Предыдущие [результаты native live](../native_live/REPORT.md) и их bulk bytes
сохраняются. Новый root артефактов: `/data/ebulochkin/vla-runtime/native-deep-20261010`.

CAPABILITY / GATE: экспериментальная запись трёх камер основной Kit-сцены в
лайве, HDF5 state/actions + online NVENC, одна4090. Нужны около50Hz без Quest
и >30Hz с подключённым Quest. Gate bindings=[]; selected RECORD не меняется.
PINNED UPSTREAM CANDIDATES: installed Isaac6.1/Kit110.3/Replicator1.13.36,
SyntheticData0.6.17, IsaacLab17.0.2, existing native recorder, PyNvVideoCodec2.2.3.
UPSTREAM OWNS: physics/control, Fabric publication, RTX products, result nodes,
SceneUI and storage/encoder. GAP: source-result closure and сериализованный путь.
ADAPTER: read-only timings, scoped upstream settings, same-renderResults camera
and semantic transforms, concrete publication observer; no custom framework.
ENVIRONMENT IMPACT: existing environments; any installed source modification
needs retained preimage/hash/restore receipt. Пока SDK files не меняются.

Сначала измерить отдельно capture_frame, observation factory/hash, encoder submit,
preview upload/fence и native sim.step. Новые observer не вызывают дополнительных
physics steps, не меняют labels и восстанавливают inherited/instance attributes.
Проверить independently async scheduling, lowLatency, preview and viewport cost;
отключение desktop viewport является ablation, не заявлением о работающем Quest.
Обычный native physics — основное сравнение; standalone остаётся отдельно.

Для проверки актуальности использовать actual rendered camera matrices и
semantic world matrices из того же renderResults, что pixels/frame identifier.
Сравнение должно покрывать движущуюся геометрию, а не только диагностический stamp.
Фиксированный лаг не является доказательством и не используется для relabel.
Отдельно проверить fair optical marker before Fabric publication/app.update.
Source history и CUDA ownership должны иметь явные bounds и failure checks.

Все GPU прогоны последовательны, каждый имеет explicit argv/config/source
hashes/stdout/stderr/resource telemetry и результат, включая сбои. Сохранить raw
live HDF/H264 и независимую проверку state/actions/packet coverage; small receipts
в Git, bulk вне Git. CPU и repository checks также сохранять отдельными attempts.
Физический робот не используется. Реальный Quest не подключён: synthetic XR
профиль не доказывает реальную XR session/headset performance или S2/D1 admission.

Основные источники для следующего сравнения:

- [Isaac6.1 performance handbook, runtime async recipe](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/reference_material/sim_performance_optimization_handbook.html#runtime-asynchronous-rendering).
- [FSD vs OmniHydra: delayed USD→Fabric publication](https://docs.omniverse.nvidia.com/kit/docs/usdrt.scenegraph/7.6.3/fabricsd/fsd_vs_omnihydra.html).
- [FSD configuration](https://docs.omniverse.nvidia.com/kit/docs/usdrt.scenegraph/7.6.3/fabricsd/configuration.html).
- [NVIDIA performance workflow](https://nvidia-omniverse.github.io/omniverse-performance/get-started/quick-start.html).

Повторный size/reuse audit: existing NativeKitMedia превышает300LOC; сохранить
его конкретным adapter. Source proof и profile — только диагностические observers;
при суммарном runtime>1000LOC повторно проверить upstream alternative и границы.
