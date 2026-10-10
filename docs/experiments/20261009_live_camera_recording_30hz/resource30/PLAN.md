# Проверка распределения ресурсов записи

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted preservation base: `38185eb57016cb86786ffbc9846f91af1d629178`.

Сначала сохранены чистый HEAD, checkpoint ref и проверенный полный Git bundle
в `/data/ebulochkin/vla-runtime/live30-resource-20261010/checkpoint`.
Предыдущие источники, датасеты и frozen receipts не изменяются.

CAPABILITY: ускорить проверку датасета и проверить фоновую обработку завершенного
эпизода во время live recording на одной RTX4090. PINNED CANDIDATES: уже
установленные LeRobot0.6.1, PyAV, PyTorch DataLoader, Linux affinity/nice,
NVIDIA CLI telemetry. UPSTREAM OWNS: dataset rows, decoding, worker lifecycle,
recording/control/physics/rendering/encoding. GAP: canonical QA дважды читает
весь RGB; предыдущий монитор учитывал allocation, но не загрузку двигателей.
ADAPTER: отдельный однопроходный QA с ограниченным числом upstream workers,
внешний пассивный монитор и команды с конкретной affinity. Не нужны новые
SDK, RPC, physics/controller, универсальный scheduler или framework.

Reuse audit: сохраняются projection/schema/array validators, source SHA binding,
preencoded-video import, exact PTS и canonical materializer по умолчанию.
Новый QA вызывается только явным `--qa-workers`; проверяет каждый label/state,
каждый RGB fingerprint и representative float32 training access. Decoder и
DataLoader принадлежат upstream; spawn/prefetch=1 ограничивают IPC память.
Размер existing bridge превышает300LOC из-за source integrity checks; изменение
здесь является узким opt-in и phase timing, не новым backend. Installed files
не изменяются. Revert checkpoint полностью восстанавливает runtime source.

1. Actual960-row CPU baseline и one-pass QA с0/2/4workers; сохранить время,
   корректность, source bytes, команды, неудачи и ресурсные замеры.
2. Пассивная telemetry CPU/core, RAM, GPU utilization/VRAM/power/temperature,
   encoder/decoder activity; smoke-test самого монитора.
3. Serial matched GPU runs: тихая запись, фоновая materialization прошлого
   эпизода на общих CPU и на выделенных cores. Проверить overlap, drain,
   recording throughput/latency/media coverage, итоговый dataset QA.
4. Uncapped comparison проверяет запас относительно ориентира50Hz; paced30
   проверяет deadline и backpressure. Повторы зависят от выявленных эффектов.
5. Сохранить все attempts и bulk artifacts вне Git; компактный frozen inventory,
   результаты, maintained report и INDEX; checks с указанным trusted base.

XR core включен, источник синтетический, Quest не подключен. Результаты не
устанавливают >30Hz с Quest, physical qualification, task success или D1 admission.
Фоновая очередь в тесте ограничена одним предыдущим завершенным эпизодом.
Ресурсы можно считать доступными только после contention measurements, а не по
остатку host wall-time или VRAM. GPU прогоны сериализованы; CPU benchmark
завершается до начала GPU comparisons.

По результатам phase timestamps полного экспорта запись перекрывает decode/PNG,
а QA начинается позже. Добавлен отдельный uncapped QA-only contention assay:
реальный reader960 строк,2 workers на16–19, тот же P-core recording baseline.
Он проверяет более тяжелую reader/IPC стадию; не подменяет полный экспорт и
не доказывает, что pipeline способен постоянно завершать один эпизод за32s.

QA-only comparison дополнен8E вариантом: при том же recording около53Hz
QA ускоряется примерно на25%. До рекомендации whole-pipeline8E выполнен
дополнительный end-to-end full export+uncapped recording case. Экспорт полностью
дожидается QA/finalize; staged source и все неудачи остаются в bundle.

Повторный size/reuse audit: passive monitor343LOC нужен из-за proc-tree/PID
identity cleanup, race-safe sampling, CLI unsupported metrics и source receipts.
Он опирается на Linux/proc и NVIDIA CLI; existing run_receipted сохранял только
compute-app allocation и не обеспечивал эти наблюдения. Никакой production
scheduler не вводится. Общий объём experimental helpers около1000LOC — это
run retention/analysis, не новый runtime одного qualifying gate; bindings=[]
и selected runtime/configs не меняются. Новый runtime QA173LOC + opt-in/timing
в existing bridge остаётся конкретным adapter поверх public upstream API.
