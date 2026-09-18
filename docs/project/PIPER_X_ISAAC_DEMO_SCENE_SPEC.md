# Техническое задание: production-quality Isaac Lab scene bank для PIPER-X VR teleop

Статус документа: research-backed implementation specification, без реализации.

Research snapshot: 2026-09-10.

## 1. Scope / non-goals

Цель ТЗ — создать production-quality окружение Isaac Lab для:

- бимануального PIPER-X teleop через Quest 3;
- качественного live demo;
- записи человеческих D1 и автоматических G1 эпизодов;
- дальнейшего обучения VLA с входами:
  - `observation.images.left_wrist`;
  - `observation.images.right_wrist`;
  - `observation.images.scene`;
  - `observation.state`;
- action target: существующий бимануальный D0 `action[14]`.

Результат реализации должен состоять из одной общей scene architecture и набора декларативных профилей задач. Не допускается создание:

- копии RoboSyn/EmbodiChain;
- нового симуляторного framework;
- универсального `SimulatorBackend`/`RobotBackend`;
- собственного формата датасета;
- замены Isaac Lab `RecorderManager`;
- замены LeRobotDataset;
- собственного общего генератора эпизодов;
- дублирующего FK/IK;
- обязательного RPC только ради разницы окружений.

RoboSyn используется исключительно как метрический и композиционный референс.

---

## 2. Upstream findings from RoboSyn

### 2.1 Исследованный snapshot

Исследован актуальный на 10 сентября 2026 года:

- `EDEM-AI/RoboSynChallenge` commit
  `9815e9eee86f3dda88860ca971f71354f157d41c`;
- требуемый его документацией `DexForce/EmbodiChain` tag `v0.2.4`, commit
  `9ebee30011f378f94a7cbe78b01d8c2eacba231a`.[^1][^2][^3]

Уровни подтверждения:

- **A — exact source:** число непосредственно записано в config/source.
- **B — exact derived:** детерминированно вычислено из значений уровня A.
- **C — visual:** подтверждено только upstream render/example.
- **U — unresolved:** точного значения в исследованном source нет.

Все мировые координаты ниже — метры, RoboSyn/EmbodiChain world: правосторонняя система, `+X` вперёд, `+Y` влево, `+Z` вверх. `init_rot` объектов — intrinsic Euler XYZ в градусах.[^4]

### 2.2 Точная базовая геометрия RoboSyn

| Параметр | Значение | Единицы / frame | Exact upstream path | Подтверждение |
|---|---:|---|---|---|
| CobotMagic root | `[0, 0, 0.835]` | m, world | `configs/*/clear/gym_config.json → robot.init_pos` | A |
| Root orientation | identity, так как `init_rot` отсутствует | world | те же configs | A |
| Left arm относительно robot root | `[0.233, +0.300, 0]`, identity | m, CobotMagic root | `embodichain/lab/sim/robots/cobotmagic.py::_build_defaults` | A |
| Right arm относительно robot root | `[0.233, -0.300, 0]`, identity | m, CobotMagic root | тот же source | A |
| Left base world | `[0.233, +0.300, 0.835]` | m, world | композиция предыдущих transforms | B |
| Right base world | `[0.233, -0.300, 0.835]` | m, world | композиция предыдущих transforms | B |
| Расстояние между базами | `0.600` | m | разность Y | B |
| Относительная ориентация баз | `0°`; параллельны | world | identity transforms | A |
| Table center | `[0.725, 0, 0.775]` | m, world | `background[uid=table].init_pos` | A |
| Table size | `[1.0, 1.0, 0.1]` | m | `shape.size` | A |
| Table extent X | `[0.225, 1.225]` | m, world | center ± half-size | B |
| Table extent Y | `[-0.500, +0.500]` | m, world | center ± half-size | B |
| Table extent Z | `[0.725, 0.825]` | m, world | center ± half-size | B |
| Surface height | `0.825` | m, world Z | table top | B |
| Table collision | procedural cube, `body_type=kinematic` | — | `background[uid=table]` | A |
| Table friction | static `0`, dynamic `0`, restitution `0.01` | engine params | тот же config | A |
| Base midpoint → table center | `[+0.492, 0, -0.060]` | m | world transforms | B |
| Base root above table top | `+0.010` | m | `0.835−0.825` | B |

Источники значений повторяются во всех десяти `clear/gym_config.json`; репрезентативный файл — `configs/items_handover/clear/gym_config.json`.[^2][^3]

Важно: `0.835 m` — положение CobotMagic base root, а не универсальная высота монтажной плоскости. Для PIPER-X это значение нельзя копировать вслепую.

### 2.3 Внешняя камера RoboSyn

| Параметр | Значение | Единицы / frame | Path | Подтверждение |
|---|---:|---|---|---|
| UID | `cam_high` | — | `sensor[]` | A |
| Resolution | `640 × 480` | pixels | `sensor[uid=cam_high]` | A |
| Intrinsics | `[606.315186, 606.100952, 320.549316, 245.877106]` | `[fx,fy,cx,cy]`, pixels | тот же config | A |
| Eye | `[0.257046, 0.049382, 1.459689]` | m, world | `extrinsics.eye` | A |
| Target | `[0.599275, 0.044517, 0.520085]` | m, world | `extrinsics.target` | A |
| Up | `[0.939547, -0.010356, 0.342262]` | world vector | `extrinsics.up` | A |
| Eye→target distance | `1.00000002` | m | derived | B |
| Downward pitch | `69.9852°` | от горизонтали | derived | B |
| Eye above table | `0.634689` | m | derived | B |
| Horizontal FOV | `55.6482°` | full FOV | derived from intrinsics with off-centre principal point | B |
| Vertical FOV | `43.2013°` | full FOV | derived | B |
| Physical focal length | **unresolved** | mm | sensor aperture отсутствует | U |
| Camera capture FPS | **unresolved** | Hz | sensor config не задаёт FPS | U |

`control_freq: 25` в RoboSyn LeRobot recorder — это control/data frequency, но не достаточное подтверждение camera capture FPS. Его нельзя выдавать за `cam_high FPS`.

По upstream render examples в кадр входят:

- центральная рабочая поверхность;
- task objects;
- grипперы и дистальные части обоих манипуляторов по левому/правому краю;
- основания и большая часть проксимальных звеньев обычно обрезаны.

Это подтверждение уровня C, а не формальная гарантия покрытия каждого task layout.[^5]

### 2.4 Типичные RoboSyn spawn layouts

Координаты — world, метры; rotations — Euler XYZ, градусы. Z у mesh assets зависит от их внутренних origins, поэтому переносить Z без пересчёта нельзя.

| Task / exact config path | Объекты и точные spawn ranges |
|---|---|
| `configs/click_bell/clear/gym_config.json` | `button`: `[0.4,-0.3,0.83] … [0.85,+0.3,0.83]` |
| `configs/drawer_open_place/clear/gym_config.json` | объект `duck`, фактически tomato asset: `[0.53,0.18,0.87] … [0.8,0.35,0.87]`, yaw `±30°`; drawer initial `[0.8,0,0.9]`, relative translation `[-0.15,-0.18,0] … [0,0,0]`, rotation `[0.3,0,180]°` |
| `configs/handle_basket/clear/gym_config.json` | `milk`: `[0.6,0.05,0.83] … [0.75,0.3,0.83]`, Y rotation `−180…180°`; `basket`: `[0.6,-0.15,0.83] … [0.7,-0.1,0.83]`, Y rotation `0…20°` |
| `configs/item_assembly/clear/gym_config.json` | `guijiao1` initial `[0.6,-0.15,0.8]` + relative Δ `[-0.05,-0.01,0] … [0.08,0.01,0]`; `guijiao2` initial `[0.6,0.16,0.8]` + relative Δ `[-0.08,-0.02,0] … [0.08,0.05,0]` |
| `configs/items_handover/clear/gym_config.json` | `holder`: `[0.5,0,0.884] … [0.7,0.25,0.884]`; `pen`: `[0.52,-0.3,0.884] … [0.675,0,0.884]`, yaw `±30°`; table Z дополнительно randomizes `±0.05 m` |
| `configs/manipulate_pipette/clear/gym_config.json` | `beaker`: `[0.48,-0.05,0.83] … [0.65,0.18,0.83]`, yaw `±180°`; `pipette`: `[0.45,-0.28,0.86] … [0.72,-0.1,0.86]`, yaw `±30°` |
| `configs/mixer_operating/clear/gym_config.json` | `mixer`: `[0.54,0,0.9] … [0.65,0.1,0.9]`; `beaker`: `[0.63,-0.25,0.85] … [0.75,-0.2,0.85]`, yaw `±180°` |
| `configs/sample_loading/clear/gym_config.json` | test tube, названный `cube`: `[0.45,-0.28,0.86] … [0.68,0,0.86]`, roll `±20°`; rack `[0.63,0,0.865] … [0.7,0.15,0.865]`, yaw `0…90°` |
| `configs/table_rearrangement/clear/gym_config.json` | fork `[0.4,0.15,0.83] … [0.65,0.3,0.83]`; spoon `[0.4,-0.3,0.83] … [0.65,-0.15,0.83]`; yaw `±45°`; plate fixed `[0.5,0,1]`, но Z/scale зависят от mesh origin |
| `configs/water_pouring/clear/gym_config.json` | cup `[0.56,0.05,0.85] … [0.75,0.3,0.85]`, rotation `[[0,0,-180],[0.1,0.1,180]]`; bottle `[0.5,-0.25,0.83] … [0.7,0,0.83]`, Y rotation `±180°` |

Совокупный абсолютный spawn envelope: приблизительно `X=[0.4,0.85]`, `Y=[-0.30,+0.35]`, `Z=[0.80,0.90]`. Это envelope размещений, а не доказанный reachable workspace.

Относительно баз:

- left base: `ΔX=[0.167,0.617]`, `ΔY=[-0.60,+0.05]`;
- right base: `ΔX=[0.167,0.617]`, `ΔY=[0,+0.65]`.

Явного bimanual reachability polygon или voxel map в RoboSyn не найдено: **unresolved**.

### 2.5 RoboSyn randomization finding

`random` profiles содержат:

- `cam_high` focal offsets `fx/fy ±50 px`;
- camera translation до `20 mm`;
- Euler perturbation `±0.175 rad`, примерно `±10°`;
- light XY `±0.5 m`, RGB `[0.6,1]`, intensity `[10,30]`;
- robot joint offsets около `±0.05…0.06 rad`;
- robot EEF offsets до `±10 mm`;
- texture replacement probability `0.5`.

Но в `EmbodiChain v0.2.4` есть существенная несостыковка: `cam_high` задан через `eye/target/up`, а event передаёт `pos_range/euler_range`, используемые только для parent-attached camera. Для look-at режима функция ожидает `eye_range/target_range/up_range`. Поэтому заявленная `cam_high` extrinsics-randomization фактически является no-op.[^6]

---

## 3. Decisions adopted or adapted from RoboSyn

### Adopt

- Base separation `0.600 m`.
- Параллельные базы, обе смотрят по `+X`.
- Общий стол `1.0 × 1.0 m`.
- Table top `Z=0.825 m`.
- Основной task envelope перед роботами: `X≈0.45…0.85`, `Y≈−0.30…+0.30`.
- Высокая внешняя камера между роботами.
- Композиция: grippers по краям, task objects и workspace в центре.
- `640×480` для всех policy cameras.

### Adapt

- PIPER-X `base_link` ставится прямо на `Z=0.825`, а не на RoboSyn `0.835`.
- Scene camera делается менее вертикальной: примерно `44.9°` вниз вместо `70°`.
- Scene camera фиксируется относительно world, а не randomizes в основном профиле.
- Table height не меняется между policy episodes.
- Home poses пересчитываются по принятой Gate C кинематике PIPER-X.
- Все Z spawn задаются как `support_surface + collision_half_height + clearance`, а не копируются из asset-specific RoboSyn coordinates.

### Reject

- EmbodiChain/RoboSyn runtime dependency.
- RoboSyn recorder и task framework.
- Нулевая table friction.
- Зелёные стены benchmark-style.
- Частая замена текстур на роботах.
- Случайное изменение table height.
- RoboSyn asset binaries без per-asset provenance.
- `25 Hz` как целевой policy/data rate.

---

## 4. Proposed architecture

Использовать обычный Isaac Lab manager-based environment:

```text
ManagerBasedRLEnv
└── common InteractiveScene
    ├── LeftPiper / RightPiper
    ├── table / floor / backdrop
    ├── left_wrist / right_wrist / scene cameras
    ├── lighting rig
    └── task assets selected by SceneProfile
        ├── reset EventTerms
        ├── success/failure terms
        ├── terminations/truncations
        └── RecorderManager terms
```

Одна архитектура должна обслуживать все задачи. Профиль меняет:

- task assets;
- spawn distributions;
- fixed target poses;
- success metrics;
- time limit;
- randomization level;
- instruction/task revision.

Не меняются:

- robot model;
- robot base transforms;
- world axes;
- table;
- wrist cameras;
- scene camera semantics;
- D0 state/action ordering;
- temporal sampling contract.

### Mandatory upstream audit

**CAPABILITY / GATE**

Scene runtime для S1/S2, human recording D1, automated episodes G1.

**PINNED UPSTREAM CANDIDATES**

- Isaac Lab `release/3.0.0`, commit `913ac53f…`;
- Isaac Sim `6.0.1.0`;
- Isaac Lab `InteractiveScene`, `Camera`, manager-based env;
- `EventManager`, termination/reward observation managers;
- `RecorderManager` и `ActionStateRecorderManagerCfg`;
- Isaac Mimic/SkillGen только там, где их action assumptions совпадают с задачей.[^7][^8][^9]

**WHAT UPSTREAM ALREADY OWNS**

- scene/entity lifecycle;
- USD/URDF spawn;
- physics and collision;
- RGB rendering;
- seeded reset events;
- success/termination dispatch;
- HDF5 episode recording;
- separation of successful/failed recordings;
- multi-EEF imitation utilities.

**EXACT REMAINING GAP**

- конкретный PIPER-X scene profile;
- третья policy camera;
- task-local spawn/success terms;
- episode metadata sidecar;
- D0 three-camera revision;
- causal Isaac HDF5 → LeRobotDataset v3 converter;
- task-local scripted experts for G1;
- performance scheduling для 120 Hz physics, 30 Hz sensors и XR.

**PROCESSOR / CONFIG / ADAPTER REQUIRED**

- declarative common scene config;
- small task-specific reset/success functions;
- existing D0 observation/action edge processors extended only for `observation.images.scene`;
- deterministic recording converter;
- возможный тонкий in-process multirate scheduler, только если pinned upstream не может независимо обслужить XR и sensor rendering.

**ENVIRONMENT IMPACT**

Всё исполняется в принятом изолированном Isaac environment. LeRobot не импортируется в Isaac process; materialization в LeRobotDataset остаётся отдельным profile.

**WHY NO PROJECT FRAMEWORK IS NEEDED**

Isaac Lab уже владеет scene, reset, sensor, recorder и manager API. Требуется композиция конфигов и несколько task-local terms, а не новый framework.

---

## 5. Coordinate frames and units

Ввести явный scene frame `S`:

- right-handed;
- `+X_S`: от оператора в глубину стола;
- `+Y_S`: влево от оператора;
- `+Z_S`: вверх;
- origin: world floor projection под серединой между роботами, как в RoboSyn.

Нормативные единицы:

| Величина | Scene/native | D0 boundary |
|---|---|---|
| Translation | m | state/action не содержат Cartesian translation |
| Rotation | rad или quaternion в Isaac | state/action joints — degrees |
| Quaternion configs | обязательно указывать `xyzw` или `wxyz` в имени поля | — |
| Arm state/action | Isaac radians | D0 degrees |
| Gripper | Isaac aperture m | D0 millimetres |
| Image | uint8 RGB HWC | uint8 RGB HWC |
| Time | seconds, monotonic | exact 30 Hz episode-relative grid |

Все object poses в provenance хранятся как:

```text
frame: world_S
position_m: [x, y, z]
orientation_xyzw: [x, y, z, w]
```

---

## 6. Robot layout

### 6.1 Canonical transforms

| Robot | `base_link` position | Orientation |
|---|---|---|
| Left PIPER-X | `[0.233, +0.300, 0.825] m` | identity, `quat_xyzw=[0,0,0,1]` |
| Right PIPER-X | `[0.233, -0.300, 0.825] m` | identity, `quat_xyzw=[0,0,0,1]` |

Base-to-base distance: exactly `0.600 m`.

Обе базы параллельны и смотрят по `+X`. Не нужно поворачивать их внутрь: overlap формируется joint-1 poses и рабочими зонами. Это сохраняет RoboSyn layout и упрощает симметричность данных.

### 6.2 Gate C preservation

Использовать без scale или изменения topology:

- AgileX `agx_arm_urdf`;
- commit `f6642ce0d7872c686f29c99e9e10cd23d1d49313`;
- `piper_x_with_gripper_description.xacro`;
- base `base_link`;
- TCP `gripper_base`.

Scene root transforms не изменяют внутреннюю Gate C geometry. Запрещено:

- подменять USD из другого PIPER package;
- менять joint axes/limits;
- менять gripper coordinate;
- сохранять actuator-clipped command вместо D0 label;
- неявно зеркалить правый arm через negative scale.

### 6.3 Proposed home poses

D0 units `[joint1…joint6, gripper_mm]`:

- left: `[-20, 90, -50, 0, 0, 0, 50]`;
- right: `[+20, 90, -50, 0, 0, 0, 50]`.

FK `gripper_base` по закреплённой Gate C модели:

- left local TCP: `[0.345929, -0.125908, 0.201481] m`;
- right local TCP: `[0.345929, +0.125908, 0.201481] m`;
- left world TCP: `[0.578929, +0.174092, 1.026481] m`;
- right world TCP: `[0.578929, -0.174092, 1.026481] m`.

Статус этих home poses:

- joint limits: проверены;
- FK: проверен по закреплённой модели;
- self/inter-arm/table collision: **ещё не подтверждены**;
- должны считаться candidate values до Isaac collision acceptance.

Текущий принятый S1 smoke home `[0,30,-60,0,20,0,50]` нельзя молча заменять. Новый home относится к отдельному demo scene profile.

### 6.4 Reach zones

Предлагаемые зоны, требующие последующей IK/collision верификации:

- left-private: `X=[0.43,0.75]`, `Y=[+0.08,+0.32]`;
- right-private: `X=[0.43,0.75]`, `Y=[-0.32,-0.08]`;
- shared bimanual core: `X=[0.48,0.72]`, `Y=[-0.12,+0.12]`;
- manipulation Z: `0.835…1.15 m`.

Для acceptance shared core должен быть достижим обоими TCP с набором top/side grasp orientations, а не только одной точкой.

---

## 7. Table and workspace

Canonical table:

- center: `[0.725, 0, 0.775] m`;
- size: `[1.0, 1.0, 0.1] m`;
- top: `Z=0.825 m`;
- extents:
  - `X=[0.225,1.225]`;
  - `Y=[-0.500,+0.500]`;
- static/kinematic;
- collision: простой box без визуального bevel;
- visual shell может иметь небольшой bevel, но collision остаётся стабильным;
- recommended friction:
  - static `0.8`;
  - dynamic `0.6`;
  - restitution `0.0`.

Материал:

- нейтральный тёпло-серый;
- roughness `0.65…0.8`;
- metallic `0`;
- без высокочастотного texture pattern;
- контрастирует и с чёрными grippers, и со светлыми/цветными объектами.

Рабочая поверхность делится на логические зоны:

```text
source-near:       X = 0.43…0.60
shared-manipulate: X = 0.52…0.72
target-far:        X = 0.68…0.88
left side:         Y = +0.10…+0.30
right side:        Y = -0.30…-0.10
handover corridor: Y = -0.08…+0.08, Z = 0.95…1.15
```

Любой spawn должен:

- иметь минимум `40 mm` до table edge;
- иметь минимум `30 mm` до robot pedestal/collision geometry;
- не пересекаться с другим object collision;
- проходить reachability filter;
- получать Z от support surface и фактического collision AABB;
- после settle оставаться в пределах допустимого pose drift.

---

## 8. XR presentation

### 8.1 Ergonomic target

Primary profile — seated/compact standing teleop:

- nominal HMD eye in scene: `[-0.05, 0, 1.20] m`;
- пользователь находится по центру между роботами;
- рабочая зона удалена на `0.60…0.75 m`;
- table surface на `0.375 m` ниже nominal eye;
- основной hand interaction volume имеет Z `0.95…1.10 m`;
- ожидаемый head-down angle к hand volume: примерно `10…20°`;
- масштаб сцены: строго `1:1`.

Для пользователя другого роста выполнять один раз session calibration, а не менять scene geometry между эпизодами:

- table top должен оказаться на `0.35…0.45 m` ниже eyes;
- shared-workspace centroid — на `0.60…0.75 m` впереди;
- robots не должны визуально пересекать seated torso;
- near plane: initial candidate `0.10 m`, physical acceptance `0.10…0.15 m`.

### 8.2 OpenXR frame issue

Текущий проектный S2 config описывает:

```text
OpenXR → Isaac: [x, y, z]isaac = [x, -z, y]openxr
```

Следовательно, при identity anchor OpenXR forward попадает в Isaac `+Y`, а не в выбранный scene `+X`. Начальный candidate alignment:

- anchor yaw: `−90°` around world Z;
- `anchor_rot_xyzw=[0,0,-0.7071068,0.7071068]`;
- semantic anchor point candidate: `[-0.05,0,1.20] m`.

Это не считать принятым до physical Quest run. Текущий S2 anchor `[0,-0.6,-1.05]`, identity, уже относится к remediation после неудачного первого physical run и всё ещё ожидает вторую human acceptance.[^10]

### 8.3 Comfort acceptance

Непрерывная сессия 30 минут должна пройти без:

- вынужденного постоянного наклона головы более `30°`;
- необходимости тянуть controllers за комфортный arm reach;
- clipping table/arms near plane;
- изменения apparent scale;
- неожиданного recenter;
- controller jumps при tracking recovery;
- cybersickness report выше `2/10`.

---

## 9. Camera configuration

### 9.1 Wrist cameras

Оставить текущую принятую семантику неизменной:

| Поле | Left / Right |
|---|---|
| Keys | `observation.images.left_wrist`, `observation.images.right_wrist` |
| Parent | соответствующий `gripper_base` |
| Offset | `[0.10,0,0.05] m` |
| Offset quaternion | `[0,0,0,1] xyzw` |
| Resolution | `640×480` |
| FPS | `30` |
| Data | uint8 RGB HWC |
| Focal length | `18.0 mm` |
| Horizontal aperture | `20.955 mm` |
| Clip | `[0.02,10.0] m` |

Источник — текущий [`configs/isaac_s1_runtime.yaml`](../../configs/isaac_s1_runtime.yaml).

Новый scene profile не имеет права менять mounting, intrinsics или crop wrist cameras.

### 9.2 Canonical scene camera

Recommended world-static camera:

| Поле | Значение |
|---|---:|
| Key | `observation.images.scene` |
| Eye | `[0.10, +0.05, 1.43] m` |
| Look-at target | `[0.65, 0.00, 0.88] m` |
| World up | `[0,0,1]` |
| Eye-target distance | `0.779423 m` |
| Height above table | `0.605 m` |
| Downward pitch | `44.882°` |
| Horizontal FOV | `60.0°` |
| Vertical FOV at 4:3 | `46.826°` |
| Resolution | `640×480` |
| FPS | `30` |
| Data | uint8 RGB HWC |
| Clip | `[0.05,5.0] m` |
| Attachment | world/static, не XR head |

При сохранении Isaac horizontal aperture `20.955 mm` focal length для HFOV `60°` должен быть `18.14756 mm`.

Источник истины для orientation — `eye/target/up`, либо upstream `set_world_poses_from_view`, а не вручную перенесённый quaternion. Isaac Lab camera APIs и conventions должны оставаться upstream-owned.[^7]

### 9.3 Ожидаемая композиция

В L0 reset кадре должны находиться:

- оба gripper/TCP;
- дистальная часть каждого предплечья;
- shared bimanual zone целиком;
- все task objects и targets;
- table region примерно `X=0.35…0.95`, `Y≈−0.43…+0.43`;
- не более 20% заведомо пустого фона.

Основания роботов могут частично входить в нижние углы, но не являются обязательным policy content. Камера не должна превращаться в room overview.

Почему `640×480@30`:

- совпадает с wrist streams;
- сохраняет один temporal grid;
- не требует дополнительного resize/crop processor;
- не увеличивает policy schema неодинаковыми spatial resolutions;
- даёт суммарно `27.65 Mpixel/s` для трёх cameras до encoding.

Depth, segmentation и optical flow допустимы только как debug/evidence channels и не входят в policy input.

---

## 10. Asset strategy

RoboSynChallenge имеет repository-level Apache-2.0 license, но у большинства binary assets не обнаружена per-asset provenance или third-party notice.[^11] Для production это означает: repository license сам по себе не заменяет asset provenance review.

### SAFE TO REUSE

На текущем уровне доказательств:

| Ресурс | Path | Почему безопасно |
|---|---|---|
| Геометрические числа и task layout ideas | `configs/*/{clear,random}/gym_config.json` | текстовые Apache-2.0 configs |
| CobotMagic base transform idea | EmbodiChain `cobotmagic.py` | Apache-2.0 source |
| Procedural table/button/cube concepts | создавать средствами Isaac primitives | нет переноса чужого binary asset |
| Цвета, размеры spawn regions, camera composition principles | configs/source-derived | не требуют EmbodiChain runtime |

Ни один RoboSyn binary mesh пока не должен автоматически попадать в production asset bank.

### NEEDS REVIEW

| Asset | Upstream path / format | Collision | Scale в RoboSyn | Dependencies / conversion | Оценка |
|---|---|---|---|---|---|
| Bell/button | `assets/button/button.urdf`; OBJ/MTL, STL | отдельные collision OBJ/STL; prismatic travel `−0.005…0 m` | URDF-native | Isaac URDF import, joint/contact test | Лучший технический кандидат; подтвердить авторство SolidWorks export |
| Beaker | `assets/Beaker/beaker.ply` | runtime convex decomposition, max 24 hulls | `[1.4,1.4,1.5]` | units unresolved; пересобрать collision | Полезен после provenance/scale review |
| Pen | `assets/Pen/the_pen.obj`, `.mtl` | convex decomposition, max 8 | `[1,1.6,1.6]` | MTL; config override material | Хороший elongated grasp object |
| Pen holder | `assets/PenHolder/pen_holder.obj`, `.mtl` | max 8 hulls | `[0.56,0.45,0.56]` | openings требуют collision validation | Полезен для placement/insertion |
| Basket | `assets/Basket/kago3_deform.obj` | max 8 hulls | `[1,0.5,0.82]` | связанные MTL/textures неоднозначны | Возможны проблемы с проёмом collision |
| Test tube | `assets/test_tube_standard.ply` | max 24 hulls | `[1.1,1.1,1.3]` | units/material unresolved | Полезен для fine alignment |
| Test-tube rack | `assets/test_tube_rack_standard.ply` | upstream max 1 hull + SDF 128 | `[1.1,1.1,1.1]` | нужен compound/SDF collision, сохраняющий holes | Высокая ценность, высокая цена подготовки |
| Pipette | `assets/pipette_good/pipette_good.urdf` | ACD collision meshes | `[3,3,3]` | OBJ, MDL, materials, USD dependencies | Технически богатый, provenance пока недостаточен |
| Mixer | `assets/beaker_mixer/beaker_mixer.obj` | max 12 hulls | `[0.3,0.3,0.3]` | MTL/images | После license и articulated-button review |

### DO NOT USE

До появления новых доказательств:

| Asset | Причина |
|---|---|
| `assets/tomato/**` | `asset.json` имеет пустую provenance; mesh >1.2M vertices, non-watertight, validation false; дополнительно используется под именем `duck` |
| `assets/MilkBox/**` | branded packaging, неизвестное происхождение, scale около `0.0066` |
| `assets/bottle/**` | readme сообщает генерацию через ImageToStl, но не содержит лицензии/source rights |
| `assets/background_texture/100/**` | нет per-file provenance/license |
| `TableWare/**`, `PaperCup/**`, `SlidingBoxDrawer/**` | пути ссылаются на внешние EmbodiChain data, отсутствующие в RoboSyn repository |
| `assets/guijiao_standard/**` | неясная семантика и provenance |
| RoboSyn green-wall/background pack | benchmark-specific look и неподтверждённые textures |

### Conversion requirements

Каждый допущенный asset обязан получить:

- `asset_id`, semantic name, source URL, source commit;
- SHA-256 каждого исходного файла;
- author/license/provenance record;
- исходные units и фактический metric bounding box;
- visual USD и отдельную collision representation;
- explicit mass/inertia/friction;
- material/texture dependency manifest;
- contact/grasp test;
- scale screenshot с метрической линейкой;
- promotion status `quarantine → reviewed → production`.

Dynamic objects не должны использовать произвольный triangle-mesh collider.

---

## 11. Scene bank

Общие зоны:

- `L`: `X=.43… .68`, `Y=.10… .30`;
- `R`: `X=.43… .68`, `Y=−.30…−.10`;
- `C`: `X=.48… .72`, `Y=−.12…+.12`;
- `GL`: `X=.68… .86`, `Y=.10… .28`;
- `GR`: `X=.68… .86`, `Y=−.28…−.10`;
- Z вычисляется от support collision.

| Task | Description / objects | Spawn / target | Success | Arms | Training value | Teleop | Scene cam |
|---|---|---|---|---|---|---:|---|
| `cube_to_plate` | Один cube → plate | cube L или R; plate соответствующий GL/GR | released, contained, stable 5 ticks | single, side alternates | базовый grasp/place, camera calibration | 1/5 | средне |
| `dual_cube_to_plates` | Два цветных cube одновременно на matching plates | cubes L/R; plates GL/GR | оба contained/released/stable | bimanual independent | синхронность, left/right state/action | 2/5 | высоко |
| `object_sorting` | 3–4 primitives двух классов → два bins | objects `X=.44… .62,Y=±.24`; bins GL/GR | все objects в correct bins | bimanual | semantics, multi-stage planning | 3/5 | очень высоко |
| `container_transfer` | Перенести 2–3 objects из source tray в target tray | source L/R, target opposite side | required count transferred | single или bimanual | repetitive pick/place, recovery | 2/5 | высоко |
| `bimanual_handover` | Один arm передаёт elongated object другому, затем placement | source R, handover volume C, target GL | receiver grasped, giver released, final placement | bimanual cooperative | coordination и occlusion robustness | 4/5 | критично |
| `dual_independent_pick_place` | Разные objects и targets, асинхронно | независимые L/R и GL/GR | обе подзадачи выполнены | bimanual independent | disentangling simultaneous actions | 3/5 | высоко |
| `stacking` | Stack 2–3 cubes | source L/R; stack target `[.70,0]` | ordered stack, stable 10 ticks | single/bimanual | precision, contact dynamics | 4/5 | критично |
| `drawer_open_place` | Один arm открывает drawer, второй кладёт object | drawer fixed `X=.78… .92`; object opposite private zone | drawer travel threshold + object inside/released | bimanual | articulated interaction, staging | 4/5 | критично |
| `button_and_place` | Press button после placement либо пока другой arm удерживает object | button fixed C/far; object L/R | placement stage complete + button travel ≥ configured threshold | bimanual | temporal ordering, event interaction | 3/5 | высоко |
| `cup_to_coaster` | Cup/container на coaster/tray | cup L/R; coaster opposite/forward | upright, centered, released, stable | single/bimanual | orientation-sensitive placement | 3/5 | высоко |
| `peg_insertion` | Peg/tube в socket/rack | peg L/R; fixture C/far | depth, lateral и angular tolerance | single; optional bimanual fixture hold | fine alignment | 5/5 | критично |
| `tool_relocation` | Marker/spatula/tool → holder/tray | elongated tool private zone; target opposite | tool within pose/containment tolerance | single/handover variant | elongated grasp, wrist viewpoint | 3/5 | высоко |

Первая реализация не должна моделировать жидкость. `water pouring` можно добавить позднее только как separate validated physics profile; placement cup/bottle достаточно для первой версии.

---

## 12. Randomization profiles

Randomization разделяется на три независимых revisioned блока:

1. `task_randomization`;
2. `visual_randomization`;
3. `camera_randomization`.

Robot bases, camera identities, state/action ordering и mounting wrist cameras не randomize никогда.

### LEVEL 0 — demo

- fixed object poses;
- fixed task targets;
- fixed materials/colors;
- fixed lighting;
- fixed camera intrinsics/extrinsics;
- no distractors;
- deterministic seed;
- предназначен для live demo и geometry acceptance.

### LEVEL 1 — light training

Task:

- object XY perturbation `±15 mm`;
- yaw `±5°`;
- без mass/friction variation;
- targets fixed или `±5 mm`.

Visual:

- key/fill intensity `±7%`;
- небольшая brightness/color-temperature variation;
- curated object color variants;
- никаких texture replacements на роботах.

Camera:

- `0` variation.

### LEVEL 2 — training

Task:

- полные разрешённые private/shared spawn rectangles;
- yaw `±30°` или `±180°` для rotationally symmetric objects;
- object mass/friction `±10%`;
- target position до `±20 mm`;
- rejection sampling через reachability/collision filters.

Visual:

- curated PBR palette;
- light position до `±0.15 m`;
- intensity `±20%`;
- 0–2 license-safe distractors вне manipulation corridors;
- background hue/roughness variation.

Camera:

- policy cameras остаются фиксированными;
- рекомендуется offline image augmentation, не camera pose perturbation.

### LEVEL 3 — robustness

Task:

- boundary-biased positions;
- full valid orientation distribution;
- mass/friction `±25%`;
- 0–4 distractors;
- partial non-task occluders;
- pose/physics combinations только из validated envelope.

Visual:

- более широкие, но реалистичные illumination/material ranges;
- exposure checks обязательны;
- никаких provenance-unknown textures.

Camera:

- по умолчанию всё ещё fixed;
- отдельный opt-in `camera_robustness_v1`:
  - scene translation `±5 mm`;
  - rotation `±0.5°`;
  - focal length `±1%`;
  - wrist cameras без variation;
- actual intrinsics/extrinsics записываются per episode;
- данные этого профиля нельзя молча смешивать с canonical camera dataset.

---

## 13. Data recording requirements

### 13.1 Policy features

Предлагаемый D0-v2 training view:

```text
observation.images.left_wrist  uint8 [480,640,3] RGB @30
observation.images.right_wrist uint8 [480,640,3] RGB @30
observation.images.scene       uint8 [480,640,3] RGB @30
observation.state              float32 [14]
task                           string/task index
action                         float32 [14]
```

Существующий left-then-right ordering и units сохраняются. Текущий контракт описан в [`configs/resolved_contract.yaml`](../../configs/resolved_contract.yaml).

### 13.2 Temporal semantics

На canonical tick `t`:

```text
fresh camera/state obs_t
→ controller/expert decision
→ source_action_t
→ deterministic label processor
→ dataset_action_t
→ native Isaac mapping/clipping
→ physics transition
→ outcome_t
→ obs_t+1
```

Обязательно:

- ровно 30 dataset ticks/s;
- три fresh RGB frame на одном dataset tick;
- никакого повторения stale frame;
- никакой интерполяции action;
- `dataset_action_t` фиксируется до native clipping;
- accepted/executed native command не подменяет training label;
- post-step state хранится как outcome, а не выдаётся за `obs_t`.

### 13.3 Per-episode metadata

Обязательные поля:

```text
task_id
task_revision
seed
scene_profile
scene_profile_revision
object_identities[]
object_initial_poses[]
success
terminated
truncated
failure_reason
camera_configuration_revision
randomization_configuration_revision
```

Дополнительно сохранить:

```text
runtime = isaac
source_class = human_vr | scripted_expert | generated
embodiment_revision
processor_contract_revision
dataset_revision
conversion_revision
generator_revision
source_demonstration_lineage
policy_checkpoint
isaac_lab_commit
isaac_sim_version
asset_manifest_revision
xr_presentation_revision
```

`object_identities[]` содержит `instance_name`, `asset_id`, `asset_revision`, `source_sha256`.

`object_initial_poses[]` содержит фактический post-settle pose, а также отдельно sampled pre-settle pose.

### 13.4 Storage

Не создавать custom dataset format:

1. Isaac Lab `RecorderManager` пишет native HDF5.
2. Успешные и неуспешные attempts сохраняются раздельно либо отмечаются в одном attempt manifest.
3. Детерминированный D1/G1 converter создаёт LeRobotDataset v3.
4. Расширенная episode metadata хранится через существующую hybrid sidecar strategy, keyed by dataset/episode index.
5. Converter QA проходит все frames и все три video streams.

Isaac Lab `RecorderManager` уже умеет разделять succeeded/failed episodes; режим «экспортировать только успешные» для D1/G1 запрещён, потому что потеряет failure evidence.[^8]

---

## 14. Reset / success / failure semantics

### 14.1 Reset order

Каждый task profile обязан выполнять:

1. зафиксировать effective seed;
2. reset robot roots;
3. записать home joints, zero velocities и matching drive targets;
4. reset task articulations;
5. sample object poses;
6. collision/reachability rejection;
7. spawn/write poses и zero velocities;
8. physics settle без записи dataset frames;
9. проверить object bounds/penetration;
10. reset recorder/task state;
11. очистить camera buffers;
12. получить три новые camera frames;
13. сохранить фактический post-settle initial state;
14. начать tick `t=0`.

Одинаковые config revisions + seed должны давать одинаковые sampled poses и task semantics.

### 14.2 Common task API

Каждый task profile предоставляет только:

- asset bindings;
- spawn terms;
- target terms;
- `compute_metrics`;
- `is_success`;
- `is_unrecoverable_failure`;
- `time_limit_steps`;
- task instruction.

Не создавать общий новый class hierarchy.

Success должен возвращать:

```text
success: bool
stage: string
metrics: dict[str, scalar]
stable_ticks: int
```

### 14.3 Recommended success tolerances

| Task class | Условие |
|---|---|
| Placement | object center внутри target footprint, eroded margin `10 mm`; bottom/support error ≤`10 mm`; released; linear speed `<0.05 m/s`; stable 5 ticks |
| Sorting/bin | object AABB/COM внутри назначенного bin; released; correct class |
| Handover | receiver contact/grasp confirmed; giver released; затем final placement; stage history обязателен |
| Stacking | XY overlap ≥80%; vertical gap ≤`5 mm`; tilt ≤`8°`; stable 10 ticks |
| Drawer | drawer joint exceeds task-specific threshold; object inside drawer volume and released |
| Button | prismatic/contact threshold, например travel ≥`4 mm`; event edge записан |
| Cup placement | center error ≤`20 mm`; tilt ≤`10°`; stable 8 ticks |
| Insertion | lateral error ≤`5 mm`; angular error ≤`5°`; insertion depth ≥`20 mm`; stable 8 ticks |

Точные thresholds являются частью `task_revision`.

### 14.4 Episode flags

- `terminated=true`: success или unrecoverable task failure.
- `truncated=true`: time limit, operator abort, tracking/camera/recorder infrastructure abort.
- Они могут сопровождаться `success=false`.
- `failure_reason=null` только для successful episode.

Нормативный enum:

```text
timeout
operator_abort
object_out_of_bounds
object_dropped_below_table
invalid_reset
self_collision
inter_arm_collision
joint_limit_saturation
task_rule_violation
xr_tracking_stale
xr_disconnect
camera_frame_missing
camera_frame_stale
recorder_error
simulation_nan
performance_overrun
unknown
```

---

## 15. Performance targets

### 15.1 Required rates

| Pipeline | Target |
|---|---:|
| Physics | exact simulated `120 Hz`, wall-clock RTF ≥1 |
| Control/action | exact `30 Hz` |
| Three policy cameras | `30 Hz` each |
| Dataset | exact `30 Hz`, no skipped canonical ticks |
| Quest presentation | `72 Hz` minimum; `90 Hz` preferred after validation |

Policy camera rendering не должно выполняться на каждом physics tick. Необходимо найти upstream-compatible multirate configuration. Если XR viewport и offscreen sensors нельзя развести только config, допускается узкий in-process scheduler, но не отдельный RPC service.

### 15.2 Current blocker

Текущие no-client S2 evidence с двумя wrist cameras показывают:

- standalone: `5.315 control Hz`, `21.262 physics Hz`;
- XR Kit/no client: `5.426 control Hz`, `21.706 physics Hz`;
- VRAM около `5.2–5.9 GiB`.

Evidence:

- `/data/vla-infrastructure/cache/isaac-s2/runs/20260908T211945Z/result.json`;
- `/data/vla-infrastructure/cache/isaac-s2/runs/20260908T212016Z/result.json`.

Эти runs прошли собственный smoke, но не удовлетворяют real-time targets настоящего ТЗ. Третью camera нельзя считать production-ready, пока не устранена wall-clock деградация.

### 15.3 Latency/resource targets

- controller sample → native target dispatch:
  - p95 `<25 ms`;
  - p99 `<33.3 ms`;
- camera age при формировании dataset tick:
  - p99 `≤33.3 ms`;
- skew между тремя cameras:
  - preferred `≤5 ms`;
  - hard limit — один 30 Hz tick;
- GPU:
  - average `<80%`;
  - p95 `<90%`;
- VRAM:
  - peak `<12 GiB` на целевой RTX 4090 24 GiB;
  - рост за 30 минут `<256 MiB`;
- canonical tick overruns: `0`;
- stale/missing policy frames: `0`;
- XR disconnect/recenter during accepted run: `0`.

Перед и после добавления scene camera запускать официальный camera benchmark/instrumentation на pinned Isaac environment.[^12]

---

## 16. Acceptance criteria

### Geometry

- Base transforms совпадают с profile с tolerance `≤0.1 mm`, `≤0.01°`.
- Base distance `0.6000 ±0.0001 m`.
- Table top `0.8250 ±0.0001 m`.
- Gate C FK/joint/collision parity не регрессирует.
- Home pose проходит self/table/inter-arm collision checks.
- Минимальный home clearance между robot collision bodies — `≥20 mm`.

### Reachability

Для каждой task zone:

- не менее 1,000 deterministic pose/orientation samples;
- private zone: assigned arm collision-free IK success `≥95%`;
- shared core: оба arms success `≥90%`;
- ни один accepted spawn не требует выхода за joint limits;
- handover volume имеет минимум 500 poses, достижимых обоими arms.

### Camera

На всех L0 task resets:

- оба grippers видимы в scene camera;
- все task objects/targets находятся внутри image с margin `≥5%`;
- минимальная сторона bbox основного object `≥18 px`;
- task surface + robots + objects занимают `≥60%` кадра;
- empty/background pixels `≤20%`;
- exposure: p1 не crushed, p99 не saturated;
- no stale frame;
- exact shape/dtype/color space.

На 1,000 Level-2 resets:

- все initial task objects visible в `≥99%` resets;
- оба grippers visible в `≥95%` frames успешных эпизодов, кроме явно зарегистрированной task occlusion;
- camera intrinsics/extrinsics revision совпадает с metadata.

### Reset and physics

- 1,000 consecutive resets без NaN/invalid spawn.
- Initial penetration `≤2 mm`.
- Одинаковый seed воспроизводит sampled and post-settle state в установленных tolerances.
- Reset frames не попадают в dataset.
- После reset получаются новые camera frame IDs.

### Recording

- Полная итерация каждого LeRobot episode.
- Три video streams имеют одинаковое число canonical frames.
- `state/action` shapes `[14]`.
- Causal fixture доказывает соответствие `obs_t/action_t/outcome_t`.
- Missing image приводит к reject/abort, не duplicate.
- Success/failure flags совпадают с native task metrics.
- Все неуспешные attempts представлены в attempt manifest.

### XR/human

- Physical Quest 3 run продолжительностью 10, затем 30 минут.
- Оба контроллера управляют независимыми arms.
- Re-clutch/recovery не вызывает TCP jump.
- Пользователь подтверждает комфорт workspace, scale и table height.
- Demo task выполняется минимум 8 из 10 раз после короткого ознакомления.
- Human evidence оформляется зарегистрированным evidence object.

### Assets

- В scene profile нет unreviewed asset.
- Все source hashes/material/collision dependencies разрешаются offline.
- Scale и collision проходят визуальный и физический acceptance.

---

## 17. Contract / gate impact

Добавление `observation.images.scene` как policy input — это не косметическая S1-модификация, а D0 schema change.

Необходимо предложить revision вроде:

```text
piper_x_d0_policy_data_v2_three_rgb
```

и изменить:

- `dataset.observation_contract.policy_whitelist`;
- `dataset.common_training_view.input_features`;
- `dataset.feature_classification.training_input`;
- `dataset.cameras`;
- schema fingerprint;
- camera intrinsics/extrinsics artifacts;
- per-source projections;
- dataset QA;
- processor snapshots/tests.

Текущий fingerprint `eb7e4613…` больше не будет действителен.

Gate impact:

| Gate | Impact |
|---|---|
| Gate C | Не reopen, если model topology/frames/limits неизменны; parity rerun как regression evidence |
| D0 | Reopen для three-camera v2 contract |
| S0 | Review изменения Candidate B capability/dependencies; новых dependencies ожидаться не должно |
| S1 | Новый scene profile и camera runtime evidence; старый JointReach smoke остаётся regression fixture |
| S2 | Повторная physical Quest acceptance из-за новой scene geometry, anchor и performance |
| D1 | Реализация human VR recorder/converter только после D0-v2 и S2 |
| G1 | Task-local scripted expert и generation report после S1/D0-v2 |
| D2a/DM | Должны потреблять новый общий three-camera fingerprint |

Для G1 первой ступенью должен быть task-local scripted expert. Isaac Mimic поддерживает multi-EEF, но ожидает task-space action representation; текущий D0 target — joint-space absolute labels. Поэтому Mimic нельзя подключить напрямую без явного внутреннего task-space representation и детерминированной проекции в D0, не меняющей training label.[^9]

---

## 18. Implementation phases, risks, default demo profile, ASCII diagrams

### 18.1 Recommended implementation order

1. **Contract proposal**
   - D0-v2 three-camera schema;
   - scene/task/randomization/camera revision conventions;
   - evidence plan.

2. **Performance baseline**
   - профилирование текущих двух cameras;
   - устранение `21.7/5.4 Hz` wall-clock;
   - доказательство 120/30 до добавления третьей camera.

3. **Common scene shell**
   - PIPER roots;
   - table/floor/background;
   - lighting;
   - scene camera;
   - no task-specific framework.

4. **Canonical L0 task**
   - procedural cubes/plates;
   - reset;
   - success;
   - XR presentation.

5. **S1/S2 evidence**
   - geometry/camera/performance;
   - physical Quest acceptance.

6. **D1 recording path**
   - RecorderManager terms;
   - metadata;
   - causal HDF5 → LeRobotDataset v3 conversion;
   - failed-attempt retention.

7. **Scene bank**
   - add profiles one by one;
   - prioritize procedural/license-safe assets.

8. **G1**
   - task-local expert for the first task;
   - generation report;
   - later assess Mimic/SkillGen.

9. **Randomization**
   - L1, затем L2;
   - L3 only after camera/reach/data baselines.

10. **Asset promotion**
    - quarantine, provenance review, conversion, collision QA.

### 18.2 Main risks / blockers

1. Текущий Isaac S2 не работает в real time даже с двумя cameras.
2. Raw XR anchor требует физической проверки и согласования OpenXR/Isaac axes.
3. Третья policy camera требует D0 reopen.
4. RoboSyn binary assets не имеют достаточного per-asset provenance.
5. Candidate home poses пока не проверены на Isaac collision.
6. Shared reachable core пока основан на layout hypothesis, а не dense reachability report.
7. Renderer-level exact pixel determinism может зависеть от GPU/driver; geometry/state determinism следует отделить от perceptual render QA.
8. Mimic action assumptions не совпадают с текущим D0 joint action без дополнительной явной проекции.

### 18.3 Canonical default demo profile

```text
scene_profile:
  id: piperx_isaac_demo
  revision: piperx_isaac_demo_v1

camera_configuration_revision:
  piperx_three_rgb_640x480_30_v1

randomization_configuration_revision:
  demo_level_0_v1

world:
  frame: S
  axes: +X forward, +Y left, +Z up
  units: meter

robots:
  left_base:
    position_m: [0.233, +0.300, 0.825]
    orientation_xyzw: [0, 0, 0, 1]
    home_d0: [-20, 90, -50, 0, 0, 0, 50]

  right_base:
    position_m: [0.233, -0.300, 0.825]
    orientation_xyzw: [0, 0, 0, 1]
    home_d0: [+20, 90, -50, 0, 0, 0, 50]

table:
  center_m: [0.725, 0, 0.775]
  size_m: [1.0, 1.0, 0.1]
  top_z_m: 0.825

xr:
  nominal_eye_m: [-0.05, 0, 1.20]
  scene_forward: +X
  candidate_anchor_rot_xyzw: [0, 0, -0.7071068, 0.7071068]
  near_plane_m: 0.10
  physical_verification_required: true

scene_camera:
  eye_m: [0.10, +0.05, 1.43]
  target_m: [0.65, 0, 0.88]
  up: [0, 0, 1]
  hfov_deg: 60.0
  resolution: [640, 480]
  fps: 30

task:
  task_id: PiperX-DualCubeToMatchingPlate-v1
  task_revision: dual_cube_plate_success_v1
  instruction: Place each colored cube on the matching plate using both arms.
```

First demo task: **dual cube → matching plates**.

Причины выбора:

- оба манипулятора участвуют;
- легко понятна аудитории;
- меньше contact instability, чем stacking/insertion;
- success хорошо формализуется;
- сцена симметрична, но сохраняет left/right semantics;
- подходит для первых D1 и G1 checks.

Objects:

- два procedural cube, edge `0.040 m`;
- два procedural target disc/plate:
  - diameter `0.140 m`;
  - thickness `0.008 m`;
  - static/kinematic;
- цвета выбираются из высококонтрастной, color-blind-aware пары.

Level-0 poses:

```text
left_cube_center:   [0.52, +0.17, 0.847]
right_cube_center:  [0.52, -0.17, 0.847]

left_plate_center:  [0.72, +0.17, 0.831]
right_plate_center: [0.72, -0.17, 0.831]
```

Level-1 initial spawn regions:

```text
left_cube:
  X = [0.49, 0.55]
  Y = [+0.14, +0.20]

right_cube:
  X = [0.49, 0.55]
  Y = [-0.20, -0.14]
```

Success:

- каждый cube на matching plate;
- center внутри plate с `10 mm` eroded margin;
- cube released;
- linear speed `<0.05 m/s`;
- оба условия стабильны 5 consecutive control ticks;
- episode success только после выполнения обеих сторон.

### 18.4 ASCII top view

```text
TOP VIEW — world S, metres
+X forward / away from user
                         ↑ +X

x=1.225   y=+0.50  +----------------------------------+  y=-0.50
                    |                                  |
                    |          FAR TABLE               |
x=0.88              |    [ left goals ] [right goals] |
                    |       GL             GR          |
x=0.72              |        ○ L plate   R plate ○    |
                    |                                  |
                    |     shared bimanual core         |
                    |       X=.48…72, Y=±.12           |
x=0.52              |      ■ L cube     R cube ■      |
                    |                                  |
x=0.233             |   L base ●<--- 0.600 m --->● R  |
x=0.225             +----------------------------------+
                         TABLE NEAR EDGE

x=0.10                     ▲ scene camera
                           eye y=+0.05

x=-0.05                    ☺ XR user
                           centered at y=0

Horizontal table width: 1.000 m
Left base:  y=+0.300
Right base: y=-0.300
Task core:  approximately y=-0.300…+0.300
```

### 18.5 ASCII side view

```text
SIDE VIEW — Y=0 section
Z up
↑
1.43 m          scene camera ●
                              \
                               \  0.779 m look-at distance
1.20 m   XR eye ☺               \
                                  \
1.03 m              TCP home ●     \
0.88 m                             × look-at target
0.85 m                 task objects ■
0.825 m       +======================================+ table top
              |                                      |
0.775 m       |             table body               | center
0.725 m       +======================================+ table bottom
              base_link ●
              x=0.233

0.00 m  ------------------------------------------------ floor
         x=-0.05  0.10  0.225       0.65          1.225  → +X

User eye → workspace center: approximately 0.65–0.70 m
Table top below nominal eye: 0.375 m
Scene camera above table: 0.605 m
Table depth: 1.000 m
```

---

## Источники

[^1]: [RoboSyn benchmark site](https://robosyn-bench.net/).
[^2]: [RoboSynChallenge snapshot `9815e9e`](https://github.com/EDEM-AI/RoboSynChallenge/tree/9815e9eee86f3dda88860ca971f71354f157d41c).
[^3]: [Representative RoboSyn `items_handover` clear config](https://github.com/EDEM-AI/RoboSynChallenge/blob/9815e9eee86f3dda88860ca971f71354f157d41c/configs/items_handover/clear/gym_config.json).
[^4]: [EmbodiChain CobotMagic transforms](https://github.com/DexForce/EmbodiChain/blob/9ebee30011f378f94a7cbe78b01d8c2eacba231a/embodichain/lab/sim/robots/cobotmagic.py) and [configuration units](https://github.com/DexForce/EmbodiChain/blob/9ebee30011f378f94a7cbe78b01d8c2eacba231a/embodichain/lab/sim/cfg.py).
[^5]: [RoboSyn task visualization 1](https://github.com/EDEM-AI/RoboSynChallenge/blob/9815e9eee86f3dda88860ca971f71354f157d41c/misc/task-vis-1.png) and [visualization 2](https://github.com/EDEM-AI/RoboSynChallenge/blob/9815e9eee86f3dda88860ca971f71354f157d41c/misc/task-vis-2.png).
[^6]: [RoboSyn random config](https://github.com/EDEM-AI/RoboSynChallenge/blob/9815e9eee86f3dda88860ca971f71354f157d41c/configs/items_handover/random/gym_config.json) and [EmbodiChain camera randomization implementation](https://github.com/DexForce/EmbodiChain/blob/9ebee30011f378f94a7cbe78b01d8c2eacba231a/embodichain/lab/gym/envs/managers/randomization/visual.py).
[^7]: [Isaac Lab camera sensor documentation](https://isaac-sim.github.io/IsaacLab/main/source/tutorials/04_sensors/add_sensors_on_robot.html).
[^8]: [Isaac Lab RecorderManager source documentation](https://isaac-sim.github.io/IsaacLab/main/_modules/isaaclab/managers/recorder_manager.html).
[^9]: [Isaac Lab Mimic teleoperation/data generation](https://isaac-sim.github.io/IsaacLab/develop/source/overview/imitation-learning/teleop_imitation.html) and [SkillGen documentation](https://isaac-sim.github.io/IsaacLab/main/source/overview/imitation-learning/skillgen.html).
[^10]: [Current project S2 config](../../configs/isaac_s2_runtime.yaml).
[^11]: [RoboSynChallenge repository license](https://github.com/EDEM-AI/RoboSynChallenge/blob/9815e9eee86f3dda88860ca971f71354f157d41c/LICENSE) and [tomato asset metadata](https://github.com/EDEM-AI/RoboSynChallenge/blob/9815e9eee86f3dda88860ca971f71354f157d41c/assets/tomato/asset.json).
[^12]: [Isaac Lab camera-count performance guide](https://isaac-sim.github.io/IsaacLab/main/source/how-to/estimate_how_many_cameras_can_run.html).
