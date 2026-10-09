# Low-level PhysX/Fabric/actuator audit

Read-only audit 2026-10-09. Installed Isaac Lab checkout `0c2e2c64e51922d088b695d72ffe03faa5c6b95d`; root `/data/vla-infrastructure/isaac61_production/IsaacLab`. PhysX/Fabric installed extension110.3.2. Никаких imports Isaac/Kit, запусков GPU, изменения среды или tests. Source/strings inspection только. Рабочая записка, не qualification evidence.

**Уточненная цель:** >30 average wall Hz в активном physical Quest3 полном recording трех960×600 камер; no-client screening ~50Hz / ≤20ms при той же XR конфигурации. Измеренные30–40Hz без Quest кандидатом не считаются. Headset penalty не обязан быть линейным/постоянным; screening не заменяет physical evidence.

## 1. Exact stepping и где уже нет лишней публикации

Ниже `LAB` = `/data/vla-infrastructure/isaac61_production/IsaacLab/source/`.

- `LAB/isaaclab/isaaclab/sim/simulation_context.py:780`, `SimulationContext.step`: `wait_for_playing()`; increment physics count; `physics_manager.step()`; `if render and is_rendering: render()`.
- `LAB/isaaclab_physx/isaaclab_physx/physics/physx_manager.py:509`, `PhysxManager.step`: animation recorder hook; **`physx_sim.simulate(sim.cfg.dt,0.0)` :521; `physx_sim.fetch_results()` :522**; CUDA device selection; callback exception check. В этом Python методе **нет** `forward`, Fabric update, Kit app pump.
- `simulation_context.py:797` `render`: `pre_render()` → `update_visualizers()` → `after_visualizers_render()` → registered render callbacks → increment render generation.
- `simulation_context.py:843`: перед visualizer step вызывает `physics_manager.forward()` только если any visualizer requires it.
- `LAB/isaaclab_visualizers/isaaclab_visualizers/kit/kit_visualizer.py:415`: Kit требует forward. `:198` `step` → `:226` set `/app/player/playSimulations=False`, `app.update()`, вернуть True, что предотвращает лишнюю physics интеграцию от Kit pump.
- `physx_manager.py:490` `forward`: `view.update_articulations_kinematic()` и `_update_fabric(0,0)`; `:877` binding выбирает `fabric.force_update`, если доступен, иначе `update`.
- Generic `LAB/isaaclab/isaaclab/physics/physics_manager.py:422/433` `pre_render/after_visualizers_render` являются no-op; в PhysxManager overrides не найдены.
- Repository `tools/run_isaac_s1.py:535–579`: четыре step с FFFT, final camera capture. Следовательно **явный Python Fabric force_update уже раз/control**, не четыре раза. Предложение «просто перенести forward на четвертый substep» в текущем коде ничего не сокращает.

Fetch_results — отдельная blocking native граница, четыре раза/control; это нельзя удалить между зависимыми simulate вызовами без изменения native stepping contract. [NVIDIA simulation-control](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/110.1/dev_guide/simulation_control/simulation_control.html) документирует simulate/fetch и отдельный Fabric update в прямом lifecycle. Источник110.1 — contextual, установленный110.3 проверен через местный wrapper. Сохраненные host9–12ms/three nonrender steps включают этот native call и ожидания, а не только solver вычисления.

## 2. Exposed native output settings: есть рычаги, нет доказанной лишней работы

`EXT` = `/data/vla-infrastructure/isaac61_production/env/lib/python3.12/site-packages/isaacsim/extscache/omni.physx.fabric-110.3.2+110.3.0.lx64.r.cp312.u7f4/`.

`EXT/omni/physxfabric/scripts/settings.py:36–53` предоставляет UI controls для enabled, GPU interop, transformations, velocities, joint states, points. Точные пути подтверждены literal strings в установленном `EXT/bin/libomni.physx.fabric.plugin.so` и `omni.physx.ui` source:

```
/physics/fabricEnabled
/physics/fabricUseGPUInterop
/physics/fabricUpdateTransformations
/physics/fabricUpdateVelocities
/physics/fabricUpdateJointStates
/physics/fabricUpdatePoints
```

`omni.physx.ui-110.3.2+110.3.0.lx64.r.cp312.u7f4/omni/physxui/scripts/simulationInfo.py:121–129` ставит эти настройки при переключении Fabric CPU/GPU output; это показывает, что output backend — отдельная настройка от physics device.

`physx_manager.py:860–894` при `use_fabric=True` включает extension, получает interface, отключает `/physics/updateToUsd`, `updateParticlesToUsd`, `updateVelocitiesToUsd`, `updateForceSensorsToUsd`, `updateResidualsToUsd`, выключает visualizationDisplaySimulationOutput. То есть отсутствие USD writes уже намеренно настроено. Повторно «выключить USD per-step» не новое ускорение.

Binding strings `_physxFabric.cpython-312-x86_64-linux-gnu.so` говорят: `force_update` обновляет Fabric даже если simulation не выполнялась; arguments currentTime/elapsedSecs unused. Есть `enable_kinematic_body_transformation_update`, причем менять после initialization бесполезно; default enabled как Isaac workaround. Не трогать этот flag ради скорости moving-wrist/kinematic scene без отдельного анализа.

**Неизвестно из доступных исходников:** какие именно native callbacks/fetch paths публикуют GPU interop buffers каждый physics step; как toggling update transformations влияет на native state caching, dirty flags и allocation. `FabricManager.cpp`/`DirectGpuHelper.cpp` доступны только как имена в бинарнике, полного C++ source локально не найдено. Нельзя назвать конкретную «лишнюю Fabric публикацию на каждом substep» доказанным bottleneck. Публичного `fabric_update_interval=4` config в прочитанном Lab wrapper не обнаружено.

Исследовательский обратимый selector возможен, **условно после attribution**: оставить extension и GPU interop, выключить transformations/velocities/joint-state output на трех `render=False` substeps; восстановить их исходные значения до последнего `step(render=True)`, использовать штатный final forward/force_update; `try/finally` восстанавливает все значения при stop/error. Не отключать весь extension/не detach stage. Но этот selector может дать ноль, замедлить через settings callbacks, оставить stale child transforms или повлиять на native dynamics если какая-либо interop запись двунаправленная. Поэтому это probe hypothesis, не основной architecture path и не safe ready patch. Сначала сравнить native profiler events `FabricManager::update`, `DirectGpuHelper::updateRigidBodies`, `updateXForms_GPU`, simulate/fetch отдельно по F/F/F/T; labels найдены в binary. Нужны будущие явно разрешенные runtime измерения.

Более простой static output ablation — отключить Fabric velocities/jointStates/points, если ни recorder, ни renderer motion/history, ни camera consumers их не читают. Dynamics продолжает жить в PhysX; однако нельзя утверждать полноту recording при неподтвержденном data backend. Transformations обязаны остаться свежими. GPUInterop on/off исследовать отдельно, не путать CPU Fabric output с CPU physics.

## 3. Конкретный небольшой adapter с проверяемой семантикой: убрать повторный pure-implicit compute

Current repository `tools/run_isaac_s1.py:315/357` задает arm/gripper `ImplicitActuatorCfg`; `tools/isaac_vr_runtime.py:1270/1277` заменяет gripper leader/followers тоже implicit. `_apply` (`run_isaac_s1.py:508`) меняет target position один раз/control. `_advance:539` зовет `robot.write_data_to_sim()` два робота × четыре substeps =8 раз/control.

`LAB/isaaclab_physx/isaaclab_physx/assets/articulation/articulation.py:237–294` делает больше простого write: wrenches, reset instantaneous wrench, `actuators.compute(dt)`, `submit_commands()`, dirty tendon properties.

`LAB/isaaclab/isaaclab/actuators/actuator_collection.py:196–226`: fused implicit compute, затем unconditional retrieval joint_pos/joint_vel и per-group explicit compute. `:648–697` implicit kernel cached args+launch.

**Решающая деталь** `LAB/isaaclab/isaaclab/actuators/actuator_kernels.py:104–146`, `compute_implicit_actuator_batch`: q/qdot используются для computed/applied effort telemetry; actual processed targets:

```
target_pos = command_pos
target_vel = command_vel
target_effort = command_effort  # feedforward; не computed PD effort
```

PD физически считает native implicit solver. `LAB/isaaclab_physx/isaaclab_physx/assets/articulation/actuator_control.py:114–156` `submit_commands` отправляет effort и, для implicit, position/velocity targets; при joint ordering есть дополнительный reorder kernel.

**Предложение experiment-only flag**, без изменения installed package: first substep каждой boundary — штатный `robot.write_data_to_sim()`; subsequent substeps — только `robot.actuators.submit_commands()`. Это сохраняет отправку backend force и targets **каждый physics step**, но использует неизменные обработанные target buffers. Убирает шесть повторных `compute` из восьми и associated getter overhead. Не заменять на «вообще ничего не отправлять»: персистентность effort/wrench across PhysX steps должна быть отдельным доказательством, сейчас его нет.

Обязательные construction/runtime guards: все actuator groups pure implicit; no native/newton/explicit actuator path; нет instantaneous/permanent external wrench; нет dirty fixed-tendon target; target buffers и gains/limits не меняются внутри control group; preserved ordering и current processed buffers; reset/recenter/new target всегда начинает полный write; fallback штатного path при нарушении. Не пытаться создать общий scheduler для всех actuator моделей. При force3 guards можно проектировать узко для конкретного PIPER setup.

Недостаток: intermediate computed/applied effort telemetry станет stale. Не подписывать такие значения как per-substep measured effort. В repository audited `tools/isaac_s*`, `run_isaac_s1.py`, `isaac_vr*` прямых consumers `joint_acc`, `computed_effort/applied_effort/computed_torque/applied_torque` не найдено; это **не** аудит каждого upstream recordable/extension. Если telemetry требуется, compute придется сохранить в моменты чтения либо изменить контракт с явным cadencing. Такой adapter не меняет dataset_action labels и не подменяет их native output.

Ожидаемый выигрыш **неизвестен**. Это concrete reversible code experiment порядкадесятков строк и guards, но он не обещает50Hz. При current tiny robot workload kernel-launch/getter overhead может быть существеннее math, однако8→2 compute не означает4× быстрее entire step.

## 4. Acceleration buffers: еще один реальный per-step consumer, но не безопасный drop

`LAB/isaaclab_physx/isaaclab_physx/assets/articulation/articulation_data.py:133–146` `update(dt)` двигает timestamp и **eagerly reads `self.joint_acc`**. `:1227–1248` refresh acceleration получает joint velocity и запускает Warp finite-difference kernel. Repository `robot.update(PHYSICS_DT)` выполняет это8 раз/control. Этот overhead реален в исходнике.

Можно исследовать upstream opt-out/lazy acceleration telemetry при неиспользуемом joint_acc, сохраняя timestamp invalidation; текущего публичного flag не найдено. Просто вызывать `robot.update(4*dt)` раз/control меняет acceleration finite-difference interval, per-step freshness и потенциальные sensor consumers. Предпочтительнее маленькая upstream-supported optional flag, а не monkeypatch нескольких внутренних timestamps. Сначала measured cost этой стадии; она явно отделена существующим `robot_update` timer от `sim_step`. Если тормозит именно sim_step/fetch, этот tweak не решает основной предел.

## 5. CPU physics для двух роботов

Поддерживаемая ветвь `SimulationCfg(device='cpu',use_fabric=True)` уже выбирает native CPU path. `physx_manager.py:747–758`: GPU sets cudaDevice and suppressReadback=True; CPU cudaDevice=-1 and suppressReadback=False. `:776–780`: GPU broadphase vs CPU **MBP**, enableGPUDynamics toggles. TGS selected отдельно; dt120 можно сохранить. Это не только перемещение вычислений на другой процессор: broadphase/numerics/contact outcomes меняются, поэтому replay same commands и grasp/contact сравнения обязательны. Нет достаточного основания считать этот вариант хуже лишь по числу GPU cores: две маленькие articulations могут тратить на dispatch/sync больше полезной math. Но historical bakeoff CPU11.52Hz против live baseline11.68 не дает положительной поддержки и не сравним с нынешним20ms target.

Критичная pinned startup особенность `physx_manager.py:943–955`: GPU `attach_stage` вызывается перед warmup, CPU намеренно **не** вызывается; комментарий описывает double initialization → corrupted MBP collision → objects falling through. Новый direct-PhysX wrapper, скопированный с GPU примером, может нарушить это. Существующий native SimulationContext CPU selection безопаснее собственного attach sequence.

Если CPU physics выигрывает, renderer остается GPU; CPU-resident states могут упростить snapshot transport и убрать small GPU fetch boundary, но добавят transform upload для rendering, а IK текущего runtime/torch data может получить иную стоимость. Сравнивать full causal path, не physics-only FPS. Thread count/affinity отдельный фактор; не менять system governor без authorization.

## 6. Почему прямой simulate wrapper не является обещанным ускорением

На текущем pin SimulationContext уже тонко вызывает native simulate/fetch. Переход к прямым API в `_advance` сэкономит несколько Python вызовов и проверок, не известные9–12ms native latency. Более важная работа внутри fetch/outputs/dispatch остается. Нельзя запускать4 simulate подряд с одним fetch: это не документированный four-integrations protocol и ломает per-step callbacks/contacts. Нельзя заменить на dt1/30: direct API не делает substepping автоматически [NVIDIA simulation control](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/110.1/dev_guide/simulation_control/simulation_control.html).

Единственно правдоподобный широкий fork после profiler — native multi-substep primitive, сохраняющий exact four120Hz integrations+native per-step actuator/contact work, но избегает ненужных Python/tensor output transfers между ними, с одной final publication. Такого готового callable primitive в прочитанной public wrapper части **не найдено**. Разработка собственного C++ path существенно шире thin adapter и требует upstream engagement; обещать ее как ближайший простой fix неверно.

## 7. Приоритеты под50Hz screening

Сохраненный correct path50.972ms→20ms требует−30.972ms (60.76%,2.549×). Даже удаление всего measured21.377ms camera increment оставляет29.595ms base, то есть50Hz не достигается. Значит pipeline split нужно сочетать с faster base; одна вторая GPU не снимает native main-thread wait автоматически.

Первый конкретный low-risk coding experiment: pure-implicit compute decimation с full per-step submit и native dynamics verification. Вторая линия: идентифицировать real GPUInterop/PhysX fetch cost и static output channels, потом reversible native output flags. CPU physics — отдельная доступная upstream config ablation для этой маленькой сцены. Не ждать, что микротвики суммой дадут2.55× без замеров.

Сильная альтернативная architecture: control/physics/XR на GPU0, snapshot camera mirror+NVENC на GPU1, dataset pixels строго из immutable snapshot, no duplicate physics. Оба no-client pipelines должны иметь≤20ms sustainable service и combined run не наращивать очередь; control-only≥50Hz остается prerequisite. Если base не проходит, выделенная camera GPU может все равно приблизить physical>30, но такой кандидат по пользовательскому screening пока не проходит. Нужны реальные latency/queue curves и active Quest end-to-end; numerical overhead extrapolation не заменяет proof.
