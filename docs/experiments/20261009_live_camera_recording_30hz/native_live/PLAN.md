# Камеры основной Kit-сцены и совместное превью/запись

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted preservation base: `114a2256913cbd915d59e0890915c314d64355f7`.

До изменений сохранены checkpoint ref и verified Git bundle в
`/data/ebulochkin/vla-runtime/native-live-20261010/checkpoint`.

CAPABILITY / GATE: экспериментальная запись actual main-stage native camera
render products, один GPU RGBA источник для NVENC и SceneUI preview; HDF5
state/actions остаются live, LeRobot откладывается. Gate bindings=[].
PINNED UPSTREAM CANDIDATES: installed Isaac6.1/Kit110.3/Replicator1.13.36,
IsaacLab17.0.2, native GPU RGB annotators, upstream GPU ByteImageProvider,
PyNvVideoCodec2.2.3. UPSTREAM OWNS: main scene, physics, render products,
native recorder, GPU extraction, UI panels, encoder. GAP: completed frame
fan-out, causal source binding and optical freshness. ADAPTER: opt-in current
diagnostic entrypoint + concrete native product consumer; no render mirror,
new simulator abstraction, custom dataset format or online LeRobot converter.
ENVIRONMENT IMPACT: existing isolated environments; installed files unchanged.

Reuse original scene/cameras/control/label processors. Compare original native
physics and existing experimental standalone physics explicitly, rather than
calling them equivalent. Camera products attach to current camera prims;
they never populate a stage from HDF or recorder transform arrays.
The selected state-only RECORD remains unchanged. Late diagnostic products
are an explicit experimental side effect, not qualification or promotion.

Prior native camera tests found an N−1 pixel delay despite advancing frame
counters. Therefore optical source/role markers and held-physics capture are
required before claiming currentness. Compare ordinary native extraction,
supported held-state Replicator capture, and any bounded pipeline only when
actual pixel/source join can be established. Preserve failed attempts.

Tests: CPU lifecycle/ownership negatives, actual native GPU recording, same
owned frame preview upload, independent video decode/content checks, live HDF
coverage, source/state/physics accounting and performance. GPU runs serialize;
no previous-episode export runs alongside these tests. Record exact commands,
source SHA, logs, raw artifacts and scopes for every run.

Actual Quest is not presently connected; XR core/profile can be exercised,
but headset visibility, connected-Quest throughput and human teleop require
separate evidence. Diagnostic geometry changes only rendered appearance and
must be excluded from normal performance comparisons.


## Повторный size/reuse audit после callback

`NativeKitMedia` превысил300 LOC: это конкретный opt-in адаптер к трём main
Kit render products, canonical recorder, существующему PacketEncoder и upstream
SceneUI. Выделенный callback (~250 LOC) содержит только регистрацию/удаление
трёх штатных SyntheticData nodes, проверку layout/format и owned CUDA copy.
Preview adapter (~110 LOC) переиспользует upstream панели. Симулятор, камера,
кодек и label processors не реализованы заново. Общий новый runtime/integration
остаётся меньше1000 LOC; offline verifier/tests не входят в runtime.

Upstream Writer/NodeWriter повторно рассмотрены и отклонены для fast experiment:
WriterRegistry включает DispatchSync/scheduling. Выбран существующий
PostProcessDispatchUngated, SdRenderVarPtr, SdFrameIdentifier и Python OG node.
Сохранены producer-stream copy completion и frame ownership; бессрочный ring,
новый executor, RPC/environment bridge, custom plugin ABI не добавлены.

Оптическая проверка callback не прошла. Этот путь остаётся unqualified native
live RGB companion, не dataset admission. Фиксированный лаг не используется для
переназначения actions/state. Прямой OVRTX attach к main Kit Fabric stage
не найден в установленном публичном ABI; отдельный OVStage не выбран заменой.
