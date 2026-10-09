# Пара GPU PhysX master / standalone CPU PhysX

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted base: `fbdee2055efa325c352e13b321223cdf6c2f3e40`.
Baseline master: `beaedfd1116577fd4d8026232cfb96cba0b030fa`.

Восемь сценариев действительно исполнены на обоих backend из одного native
GPU snapshot для каждого сценария. Все восемь сравнения имеют structural PASS:
одинаковые commands либо Cartesian intents, согласованные индексы и finite
измеренные состояния. **Это не подтверждение полной эквивалентности физики.**
Один прогон на сценарий выявляет различия transient dynamics и представления
основания. Ни physical qualification, ни dataset admission не заявлены.

[Метрики с decomposition](metrics.json) включают отдельные основания0/12,
gripper-base TCP8/20, пальцы10/11 и объекты24–26; координаты world, quaternion
xyzw. [Воспроизводимый анализ](analyze.py) читает сохраненные NPZ и original
comparisons. [Source ledger](sources.json) содержит upstream URL, commit,
SHA256 и журнал поисков. Полные raw traces/seed/overlay/worker receipts находятся
в `/data/ebulochkin/vla-runtime/live30-correctness-20261009/pair02-output`.

## Что измерено

| Сценарий / controls | Max arm q, rad | Max prismatic q, m | Max body coordinate, m | Max body angle, rad |
|---|---:|---:|---:|---:|
| home_hold /120 | 1,59e−9 | 0 | 1,91e−6 | 8,96e−5 |
| joint_plus5 /120 | 0,0017655 | 5,30e−5 | 0,0040353 | 0,0087057 |
| joint_minus5 /120 | 0,0018030 | 5,33e−5 | 0,0040718 | 0,0087029 |
| gripper_open_close /120 | 5,84e−6 | 0,00016237 | 0,00015067 | 8,96e−5 |
| drop /120 | 1,59e−9 | 0 | 1,91e−6 | 8,96e−5 |
| blocked_gripper /120 | 3,81e−6 | 1,42e−5 | 0,0046405 | 0,215279 |
| recorded08 /960 | 0,00013784 | 1,51e−5 | 4,67e−5 | 0,00016653 |
| closedloop_reach /240 | 9,93e−5 | 7,93e−7 | 5,99e−5 | 0,00014025 |

Body coordinate — максимум одной координаты среди27 bodies. Decomposition
использует отдельно Euclidean position error, поэтому числа различаются.
Максимумы включают initial sample и transient после command. Контактный
fixture не был валидирован как удержание куба, несмотря на structural PASS.
Native body_velocity columns0:3 — linear worldCOMm/s,3:6 — angular worldrad/s.
Legacy numerical_differences.body_velocity объединяет компоненты разных
единиц: в home_hold его0,23587 — probe26 angularYrad/s наsample3; отдельный
linear max0,00391949m/s. Поэтому малые pose errors не означают эквивалентность
всех velocity transients; zero q hold не достаточен для contact parity.

При ±5° левое основание GPU вращается относительно CPU на7,268/7,288mrad
(примерно0,42°), при translation всего12,9/13,2µm. CPU fixed root неподвижен;
Kit articulation native fixed_base=false удерживается внешним world weld.
Left TCP error3,199/3,193mm объясняется прежде всего этим root rotation;
это не просто ошибка наблюдений q или Jacobian. Prop error≈1,1µm.
На меньшем движении recorded08 left TCP max36,38µm, root2,11µm/68,08µrad;
closedloop left TCP41,51µm, root1,08µm/49,64µrad. Правый root/TCP отдельно
сохранены в metrics. Универсальная bound по этим двум мягким траекториям
не установлена.

У обеих сторон ±5° rise10–90% составляет0,2simsec, t90=0,56667simsec;
settling detector position band2% и непрерывное окно0,2s впервые проходят
в0,73333s. Это описательный detector, не qualification tolerance. Original
pair02 comparator называл command time временем первого successor sample
0,36667s; фактическое target write происходит на предыдущей boundary0,33333s.
Новый comparator исправляет имя/время и отдельно сохраняет successor time.
Original pair02 comparison bytes не переписаны. Sampling30Hz не различает
transients между четырьмя physics ticks120Hz.

## Падение, контакты и неудачный fixture

Drop валиден: cube Z1,120→0,84499973m, initial velocity0. До столкновения Vz
изменяется на−0,327m/s за4ticks, соответствует gravity−9,81m/s². Последняя
sample до impact0,23333s, первая после0,26667s; точный120Hz onset не измерен.
Max paired cube position error1,145µm. Contact impulse и bounce per-substep
не восстановлены из этих30Hz samples.

В blocked_gripper куб помещен между пальцами при aperture80mm, но закрытие
начинается только после5controls. Уже sample5 Z падает0,96889→0,86190m;
куб достигает стола до закрытия. После sample26 оба пальца дают netforce:
GPU peak0,02626N, CPU0,02048N, final aperture64,64/50,43µm. Силы появляются
при почти полностью закрытых пальцах; без identity/contact filters их
нельзя приписать кубу. Это совместимо с finger-to-finger contact. Cube
paired difference достигает5,152mm и0,21528rad, а TCP1,95µm и root0,466µm.
Ни sustained grasp, ни blocking aperture stall этим fixture не доказаны.
Нужны отдельный empty-close-to0 control, исправленное время/геометрия и
filtered finger→cube contact observations; повтор сейчас не выполнен.

Дополнительный **CPU-only matched empty-close** выполнен отдельно120controls/
480ticks. Starting robot q80mm, properties и close0 sequence идентичны;
только initial cube pose/velocity заменены на canonical home table snapshot.
Mutation manifest проверяет каждый измененный scalar: только поля cube0
dynamic pose/velocity и его redundant rigid-body pose24. Empty final aperture
50,433136µm против50,432933µm failed fixture; empty finger force peaks20,4937mN
против20,4807mN. Эти силы и почти нулевая конечная aperture воспроизводятся
без куба между пальцами, поэтому не являются свидетельством blocking/grasp.
Native contact identity остается unfiltered; GPU empty-close не выполнялся.
Seed/mutation/trace/receipt/result сохранены в
`/data/ebulochkin/vla-runtime/live30-correctness-20261009/physics-audit/live30-correctness-physics-empty-close`, logical480ticks, cleanup PASS,
gpu_execution=false. Это отдельный контроль, не замена original pair02.

В обоих backend есть24native articulation contact sensors. У3props нет
PhysxContactReportAPI: native binding явно сообщает unmatched paths. Их
contact arrays содержат NaN с coverage mask false, а не ложный0. Finiteness
проверяется для всех24 реально измеренных links. Net force после4ticks —
только последний1/120 substep, не average/полный impulse sum. Perpoint normals,
separation, opposing contact forces и direct prop contacts недоступны.

## Native source и mechanics scope

Master запускает **Kit GPU PhysX**, не Newton solver. Newton API tokens —
authoring schemas; SimulationCfg physics=None выбирает PhysxCfg. Пять файлов
scene/runtime configs и core совпадают byte-for-byte с указанным master.
Парный driver не меняет их; меняются только диагностические native placement
куба и импортный hook после построения canonical scene.

Оба используют TGS/PCM/patch friction, gravity−9,81, dt1/120,4steps/control.
CPU source при noCUDA явно выключает GPU dynamics/directGPU и выбираетPABP
вместо GPU broadphase. Исходные USD flags остаются GPU-authored; они не
доказывают effective CPU backend. Drive force mode, limits и фактические
gains/caps взяты из live native seed: arms400/40/100/5, leader400/40/2/3,
followers0/0/1/3. Passive followers имеют нулевыеK/D и native constraints,
не управляющие targets как substitute mimic.

OVStage default population пропускает NewtonMimicAPI. Derived overlay
переводит4followers в PhysxMimicJointAPI:rotX: gearing=−coef1,offset=−coef0,
zero naturalFrequency/dampingRatio; исходное отношение±0,5 сохранено.
Root overlay переносит articulation root на существующий world fixedJoint,
что меняет representation floating-world-weld→fixed root. Native mass,
inertia и local COM всех27bodies совпадают с GPU readback точно в initial
metadata. Native armature/friction0, robot gravity disabled, cube mass0,035kg,
probe0,01kg; cube friction0,8/0,6/restitution0 проверены отдельными CPU reads.

Kit omni.physx extension110.3.2+110.3.0 и OVPhysX0.6.3 — разные public
bindings/builds. Совпадение underlying PhysX binary версии не установлено;
native query дает толькоOVPhysX0.6.3. Retained binary SHA256:
Kit plugin `b58d830c9131b375f1024fcefc2e34418e09bac678f1dcb5452ecdac549eeb0b`,
OVPhysX library `8f4a9f7a5e3edf7cbed9516c8dadf4c46e42a9dee86a36ccf236994ea3bd2a1b`.
Пин официального standalone source
`da950a3537927784951853c66618036f332ca0ce` и URL находятся в sources.json.

Jacobian нормализован в worldCOM2×11×6×9: GPUfloating raw12×6×15 явно
лишен root row и6base columns; CPUfixed raw66×9. piper_ik_state единожды
переводит COM Jacobian к link origin. Botharm6DOF nativeFK finite differences
прошли в CPU tests. Closedloop вызывает pinned upstream DLS(relative world,
lambda0,01), set_joint_pos_limits и hard clamp. **Оба paired controllers
работают на CUDA**, чтобы изолировать physics difference; actual standalone
pipeline controllerCPU, поэтому controller device parity этим assay не
подтверждена. Intent trace идентичен; resulting native targets может отличаться.

Каждый CPU case создается fresh из того же GPU q/dq/targets/effort/props
pose+velocity snapshot. Это не восстановление contact warm-start/solver caches.
Initial velocity error≤4,33e−7; body mass/inertia/COM identical. GPU root linear/
angular velocity не имеет отдельного reset field в seed; исходный case
начинается после canonical reset. Warm GPU versus cold CPU caches остаются
источником различий. Нельзя объявлять эти результаты доказательством точного
restore произвольного движущегося floating root.

## Retained failures и проверки

pair01 завершился до physics controls: ошибочное resolve symlink Python
потеряло isolated venv и worker не импортировал numpy. Исправлено сохранением
absolute interpreter path, без installs/SDK edits; все bytes сохранены.
pair02 отработал все8cases за93,50wallsec, result.completed=true, однако
wrapper exit1. Причина — отсутствующий canonical args.report: launcher
lines726–727 возвращает return_code or1 даже при child exit0, если report
не существует. Traceback/post-assay physics exception не найден. Driver
сохранял только assay result в другом пути. Новый adapter пишет оба receipts;
[CPU unit check](launcher-unit.json) проверяет success/error report copying.
pair02 raw receipt остается launch FAIL, не переименован в end-to-end PASS.

Новый driver поддерживает --cases home_hold для отдельного короткогоpair03;
nativeGPU step counter guard также добавлен для будущих runs. Pair02 GPU
step coordinates основаны на audited env._advance(4), CPU coordinates
проверены каждым worker reply; explicit GPU delta counter guard в pair02
отсутствовал. **Pair03 home_hold end-to-end PASS** после исправления adapter:
wrapper exit0 за15,244wallsec, обаbackend120controls/480ticks,
structuralPASS, nativeGPUdelta4 guard, CPUcleanup без ошибок. Canonical
launcher report существует и отмечает clean_shutdown=true. Это дополнительный
короткий запуск, не исправление original pair02 exit1; его artifacts находятся
в `/data/ebulochkin/vla-runtime/live30-correctness-20261009/pair03*`.

CPU-native tests7/7PASS и дополнительные20property reads сохранены в
`/data/ebulochkin/vla-runtime/live30-correctness-20261009/physics-audit/live30-correctness-physics-native-tests*` и
`/data/ebulochkin/vla-runtime/live30-correctness-20261009/physics-audit/live30-correctness-physics-native-properties.*`. Comparator analytic
freefall/COMenergy/input/clock checks6PASS. Эти проверки не заменяют paired
trace и не устанавливают numerical physics approval. Driver564lines и
comparator408lines после форматирования — узкий экспериментальный glue к canonical launcher/native
views/существующему worker/upstream DLS; отдельный robotics framework не создан.

## Воспроизведение decomposition

```sh
/data/ebulochkin/vla-runtime/live30-deep-20261009/optional-ovphysx/bin/python \
  docs/experiments/20261009_live_camera_recording_30hz/temporal_physics/physics_audit/analyze.py \
  --input /data/ebulochkin/vla-runtime/live30-correctness-20261009/pair02-output \
  --empty-close /data/ebulochkin/vla-runtime/live30-correctness-20261009/physics-audit/live30-correctness-physics-empty-close \
  --output /data/ebulochkin/vla-runtime/live30-correctness-20261009/physics-audit/live30-correctness-physics-decomposition-rerun.json
```

CPU proof files initially written in `/tmp` are retained under the corresponding
`physics-audit/<original basename>` in the runtime bundle; original locator fields
in frozen source receipts remain unchanged. [Hash retention receipt](../retention.json).
