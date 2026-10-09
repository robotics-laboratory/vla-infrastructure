# Глубокий аудит critical path: Isaac/PhysX/Fabric и standalone OVRTX

Дата 2026-10-09. Исходный проект d5566834d29ef8bb56e4fb62bb324e23e0869100; установленный IsaacLab 0c2e2c64e51922d088b695d72ffe03faa5c6b95d. Только чтение SDK и source, web research и opt-in adapters в /tmp. Этот агент НЕ выполнял GPU/hardware tests, НЕ устанавливал runtime, НЕ менял production SDK. AST-проверка adapters — не runtime validation. Измеренное влияние должны заполнить результаты parent, который управляет GPU.

## Решение и численная рамка

Цель — строго >30 wall-Hz actions и каждой из трех source-bound 960×600 камер при активном физическом Quest3. Screening — тот же active XR rig/full recording без подключенного клиента около50Hz, mean≤20ms; это эмпирический запас на Quest overhead, не универсальная функция. Правильный известный batched-prime XR/no-client baseline50.972ms требует убрать30.972ms (60.76%), ускорить2.549×. Даже camera-off29.595ms остается выше20ms: заниматься только NVENC недостаточно. Но камера-off включает Kit/XR render, поэтому это не нижняя граница PhysX alone.

Основные полезные направления: (A) сокращение повторного Python/Warp actuator/data bookkeeping без изменения четырех120Hz physics steps; (B) process-local CUDA/Vulkan scheduling ablation; (C) измерение прямого OVRTX вне Kit на полной Piper stage. OVRTX значительно сильнее идеи просто переписать Writer: убирает Kit/Replicator scheduler из dataset render worker. Нужен сначала static fullscene smoke, затем динамический snapshot mirror, затем одновременно с active XR source producer. Ни одна из стадий по отдельности не подтверждает целевой режим.

## Конкретный reversible adapter, готовый parent

`/tmp/live30-deep-physics.py`, manifest `/tmp/live30-deep-physics.preimages.json`:

- install(env,variant='baseline'|'implicit-once'|'lazy-acceleration'|'implicit-lazy') после validation/reset, перед loop; finally handle.restore(); handle.receipt().
- implicit-once делает full robot.write_data_to_sim на первом из4substeps; следующие3 вызывают robot.actuators.submit_commands. ВСЕ PhysX effort/position/velocity submissions сохраняются. Исключается повторная pure implicit actuator compute, в т.ч. вычисление PD telemetry и q/v read. Physics120Hz и FFFT сохраняются.
- Гарантии применимости: exact upstream plain ImplicitActuator всех групп, нет explicit/subclass/nativeNewton actuator, wrenches, dirty tendon, target setters внутри группы. Direct tensor mutation target buffers междуsubsteps запрещена контрактом probe, автоматически не отслеживается. Никаких safety labels по actuator output.
- lazy-acceleration сохраняет timestamp/FK bookkeeping, но убирает eager joint_acc finite difference с каждого substep. При последующем read acceleration отражает интервал между reads; это сознательно измененная telemetry semantics, а не математически та же joint_acc120Hz.
- preimage SHA256 девяти source files, проект/SDKrevision, guard2robots/120Hz/FFFT. При изменении этих файлов probe откажет; не обновлять hashes вслепую.
- mutation только instance attributes, restore восстанавливает прежнее instance value либо delattr возвращает class implementation. Закрытие процесса гарантированно убирает patch. SDK bytes неизменны.

Подход — small executable ablation, не framework и не promotion. Effect нужно измерять main-loop buckets и matched native q/dq/action traces. Candidate pass: меньший mean/95p, no drift issued targets, no unexpected source/action sequence changes. Нужны движущиеся targets, contacts/gripper transitions, а не только static scene. Computed effort и acceleration telemetry исключить из strict equality либо явно зарегистрировать измененную семантику. Нельзя сравнивать warmup разных размеров.

## Установленный exact path и что уже оптимизировано

Paths ниже относительно `/data/vla-infrastructure/isaac61_production/IsaacLab/source/`.

1. `isaaclab/isaaclab/sim/simulation_context.py:780` — step вызывает native physics; `:843` forward перед render. `isaaclab_physx/isaaclab_physx/physics/physx_manager.py:509` — simulate(cfg.dt,0.0)→fetch_results (`:521–522`) на каждом шаге. Затем CUDA set_device и raised callbacks. Следующий physics step зависит от завершения текущего; просто удалить fetch или вынести его после4simulates нельзя без подтвержденного PhysX API/state contract.
2. Тот же manager `:490` forward — update_articulations_kinematic и force_update Fabric. `:860` _load_fabric уже выключает USD write-back. Kit visualizer render временно playSimulations=False вокруг app.update: симуляцию не нужно дополнительно замедлять timeline rateLimiter; Python direct simulate задаетdt сам.
3. Не найден явный Python Fabric publication на каждом simulate. Native PhysX/Fabric plugin C++ binary локально недоступен. Утверждение «Fabric 4× на каждом control» пока НЕ доказано. Поэтому обещать выигрыш «дефер Fabric4→1» нельзя: явный forward уже1/control. Native settings fabricEnabled/fabricUseGPUInterop/fabricUpdateTransformations/fabricUpdateVelocities/fabricUpdateJointStates/fabricUpdatePoints существуют, но отключение может сломать RTX/XR или stale observation и не доказывает savings.
4. `tools/run_isaac_s1.py:510` _apply задает targets перед группой; `:535` _advance повторяет write/step/update2robots×4. `isaaclab/isaaclab/actuators/actuator_collection.py:196` compute делает fused implicit pass и q/v getter даже при отсутствии explicit execution groups; `:224` submit_commands отделен. `:498` execution plan распознает exact type ImplicitActuator, поэтому наследников без повторного аудита пропускать нельзя.
5. `isaaclab_physx/isaaclab_physx/assets/articulation/articulation_data.py:133` update принудительно читает joint_acc после timestamp; lazy q/dq таким образом не полностью lazy. `joint_acc` использует finite difference; любой skip должен честно менять metadata semantics.
6. CPU-vs-GPU physics: выбор device='cpu' до scene construction активирует CPU/MBP и readback; cuda — GPU dynamics/broadphase. Для2articulations GPU launch/sync может стоить больше полезной работы; sign unknown, full scene test нужен. Это новый scene backend, не безопасный runtime flag. Комментарий pinned CPU path: НЕ дублировать attach_stage warmup, двойная initialization разрушает MBP/collision state. Keeping render GPU при CPU physics требует audit всех downstream tensor device assumptions.
7. XR experience `apps/isaaclab.python.xr.openxr.kit` уже app.asyncRendering=True, app.asyncRenderingLowLatency=True, omni.replicator.asyncRendering=False. Последнее сделано для external cameras. Переключательasync сам по себе не означает fresh pixels или free speed; source-bound readback нужно повторно квалифицировать.

## Новая обратимая process-only ablation

`CUDA_DEVICE_MAX_CONNECTIONS=1` в environment нового процесса ДО первого CUDA context. Официальный OVRTX документ описывает Linux concurrency bug/interaction: CUDA stream wait одновременно с Vulkan submission создает graphics scheduling bubbles. Ограничение hardware CUDA queues устраняет эффект в измерениях upstream, но уменьшает параллелизм CUDA streams; нужен A/B. Это документированная OVRTX рекомендация; перенос на Kit/PhysX правдоподобен по CUDA↔Vulkan, но пока лишь гипотеза. Rollback — новый процесс без переменной, никаких global changes.

Установленный OVRTX wrapper уже делает Linux-specific CPU wait по умолчанию (`_map_render_var_to_dlpack:856`, sync_stream0+wait). Opt-in ISAAC_LAB_OVRTX_DISABLE_LINUX_CUDA_CPU_SYNC меняет это, но его нельзя применять в произвольном Kit pipeline как будто это глобальный Isaac параметр. Primary: https://nvidia-omniverse.github.io/ovrtx/core/cuda_vulkan_scheduling.html .

Другие process-start ablations: PhysX worker count0/1/2/4 на CPU scene; ограничение Kit CPU threads по documented CLI. Это меньший приоритет, пока CPU span не локализован. Governor/sudo/SCHED_FIFO не изменялись и не требуются для первых tests.

## Standalone OVRTX: реальная совместимость и неработающий простой switch

Установлен ovstage0.1.1.355824; ovrtx и ovphysx отсутствуют. Lab optional pins: ovrtx0.4.1.364340+ovstage0.1.1.355824; current develop docs описывают более новый renderer API. Pinned OVRTXRendererCfg не имеет async_rendering, нет render_batch. Поэтому API snippets develop нельзя вставить в installed EA без backport.

`isaaclab_ov/isaaclab_ov/renderers/ovrtx_renderer.py:1227` ovstage path требует camera prefix /World/envs/env_0/; `:1348` setup и legacy`:546` собирают тела через NewtonManager. Current Piper/PhysX rigs так не расположены; simple renderer cfg replacement НЕ обновит их transforms. Развилка — либо большой upstream Lab renderer/SDP upgrade, либо существенно меньший direct standalone ovstage+ovrtx worker с explicit snapshot input. Второй сохраняет исходный PhysX engine и научный experiment state.

Wrapper `:1548` закрывает publication, вызывает один renderer.step(allrenderproducts,ordinal), но берет output своего первого product. Legacy`:1053` аналогичен. Прямой API позволяет передать set из3products. Installed helper `ovrtx_usd.py:211` создает native RenderProduct, camera relationship, orderedVars LdrColor, resolution, deviceIds; env_i — wrapper restriction, не OVRTX restriction.

Latest develop docs говорят async_rendering возвращает предыдущий CAPTURE, не предыдущий physics/control tick. Первое изображение priming затем повторяется; capture pose/intrinsics должны браться из capture metadata, не live fields. Ovstage path остается synchronous. Docs на момент чтения называют IsaacRtxRendererCfg внутри isaaclab_physx; я НЕ подтвердил имя IsaacSimRtxRendererCfg из сообщения parent. Не распространять названия другой revision на installed pin. Источник: https://isaac-sim.github.io/IsaacLab/develop/source/concepts/renderers.html .

OVRTX0.5.0 changelog исправляет значительную0.3→0.4 регрессию map на application CUDA stream.0.5.1 от2026-10-05 исправляет загрузку сцен и transforms/cloned instances. Для standalone test целесообразна отдельная pinned пара0.5.1.385782+ovstage0.2.1.385922; нельзя подменять production packages. Source: https://raw.githubusercontent.com/NVIDIA-Omniverse/ovrtx/main/CHANGELOG.md и https://raw.githubusercontent.com/NVIDIA-Omniverse/ovrtx/main/pyproject.toml .

Точные binary URLs (webindex подтвердил имена; size/sha не получены через browser, нужен HEAD/download root):

- https://pypi.nvidia.com/ovrtx/ovrtx-0.5.1.385782-py3-none-manylinux_2_35_x86_64.whl
- https://pypi.nvidia.com/ovstage/ovstage-0.2.1.385922-py3-none-manylinux_2_35_x86_64.whl

PyPI23.1KB sdist — downloader/bootstrap, не runtime wheel; нельзя использовать его размер для disk budget. Linuxglibc≥2.35 wheel tag; Python3.10–3.13; driver validated minimum зависитGPU (проверить уже установленный, не менять автоматически). https://nvidia-omniverse.github.io/ovrtx/driver_requirements.html .

## Исполняемый OVRTX smoke

`/tmp/live30-ovrtx-capture.py` — public direct API latest0.5.1, stdlib/numpy/ovrtx/ovstage, без pxr/Kit/Lab imports. Аргументы stage,3×camera absolutepath, outputNEWDIR; default3×960×600,30warmup+180captures. Авторит отдельный USDA overlay с sublayer исходнойUSD,3nativeRenderProducts, sharedLdrColor. Один step на все3products, ordinal publication. CPU mode map+D2H+copy каждыйкадр; none mode — только render нижняяграница. Последние arrays.npy для visual/shape validation и receipt; finalsave исключенизtiming. No live-motion/source qualification; receipt явно false. Не изменяет sourceUSD; outputSHA фиксирует12MB inputstage, packagesversions/environment.

Важно: RealTimePathTracing mode OVRTX не гарантирует pixel equivalence текущему IsaacSim RaytracedLighting. Материалы/lighting/USD schema compatibility нужно проверять визуально. Minimal доступен как throughput bound с измененной fidelity, не drop-in canonicalRGB. Static capture throughput не обещает динамический RTX acceleration-structure update cost, XR coexistence или NVENC.

## Правильный динамический mirror после smoke

Producer сохраняет исходный PhysX+XR/control. После source observation boundary создает immutable snapshot source_id n: все меняющиеся world transforms robot links/props/3cameras, calibratedintrinsics, exactactiondecision/transition identity, timestamp/simtime, episode/reset id, scene/material/topology generation. Для rigid-only сцены100mat44float64 =12.8KB/sample, при50Hz0.64MB/s — намного дешевле raw3RGBA(6.912MB/frame,345.6MB/s50Hz). Это оценка100bodies, actual count надо посчитать. Raw RGB тоже лишь259.2MB/s; здесь synchronization более вероятен чем PCIebandwidth.

Worker принимает bounded queue immutable snapshots. Для каждого n: применяет world matrices с resetXformStack=True на matching paths, записывает changes, advance_write_floor(n).wait, step({3products},ordinal=n), consumes all outputs, затем ACK release n. Трансформы matrix convention нужно сверить (USD translation в последней строке; Omni matrixcolumn16lanesFloat64 в installed0.1 helper). Parent-child link transforms нельзя одновременно писать world matrices без resetXformStack — будет doubletransform. Материалы/visibility/deformations требуют additional channels; qpos-only replay не тождественен exact world snapshot.

**Критическая найденная оговорка:** ordinal не historical snapshot selector. OVRTX official docs говорят renderer may observe committed publication or a LATER one; ovstage0.1 latest-only. Поэтому нельзя producer thread писатьn+1 в тужеstage, пока rendern читает ее, и объявлять pixelssource=n поаргументуordinal. Worker делает sequential apply→stepcomplete; producer перекрывает его через отдельные immutable snapshot slots. Direct API step_async доступен, но не доказывает freeze scene. Upstream newer async renderer использует собственные alternatingbuffers+consumedfences; требуется именно такая гарантия, а не самостоятельныйn-minus1 label. https://nvidia-omniverse.github.io/ovrtx/core/ovstage_integration.html и https://nvidia-omniverse.github.io/ovrtx/core/async_status_errors.html .

Небольшой lag допустим: image(n) можно доставить приcurrentactionn+1/n+2; хранить source_idn, requested/rendered timestamps, age, threecamera binding. Нельзя silently pair delayedimage сlatestpose/state. Recorder join должен ждать3imagesn либо маркироватьmissing; all3counts/second, unique source IDs и bounded queue depth обязательны. Однаstage attached толькоодномуrenderer; дваrenderers требуют отдельныеstages/history, не sharedmutableobj.

ОднаGPU: двапроцесса убирают CPU scheduler serial dependencies, но делятGPU execution/VRAM/CUDA–Vulkanqueues; GPU contention может уничтожить ускорение. ДвеGPU: strongest overlap possibility — source PhysX+XR GPU0, renderworker GPU1, small CPU snapshotIPC. Выбор deviceIds в RP; проверить physicalCUDA↔Vulkan device mapping и сохранятьGPUUUID. Не обещать2× почислуGPU. Rendererworker service throughput и producer wallthroughput должны оба устойчиво≥50Hz noQuest; приboundedlag queue нерастет. Физическое>30 толькозамерQuest.

## Что говорят forums и чего они НЕ доказывают

1. https://forums.developer.nvidia.com/t/aligning-physics-stepping-with-real-time/339683 — разбор Kit asyncio, где eventloop прогрессирует app.update cadence; авторответа предлагает offthread private PhysicsContext._step и сообщает headlessaarch64 результаты. Это anecdotal version-specific experiment, не guarantee threadsafety Fabric/XR/current6.1. Наш currentdirectFFFT уже позволяет4physics между appupdates; менять asyncio не устраняет нынешний mainloopcost. Не переносить private_thread hack в production без mutex/ownership design и exact nativecounts.
2. https://forums.developer.nvidia.com/t/improving-rtf-with-high-physics-time-steps/368735 — 5articulations, рекомендации снизитьphysics150→100 дали instability уавтора; followup советуетменьшеthreads/Fabric/collideraudit. Полезный отрицательныйпример: менятьdt/solver радиfps нельзя считатьsemantics-preserving. SuggestionsSDF/contact changes не доказаны наPiper и не включены вrecipe.
3. https://forums.developer.nvidia.com/t/cpu-bottleneck/321542 — lowerresolution неустраняетcpu bottleneck, workstation сбыстрымsinglecore лучшеmanycoreVM; нечисленноеобещание нашемуhost.
4. https://forums.developer.nvidia.com/t/why-so-slow-speeding-up-simulations/226738 — historical USD writeback/Fabric advice; наш installedpath alreadyFabric, поэтомуповторитьпереключательнеявляетсяновойоптимизацией.

УправлениеOSpriority/governor можетуменьшитьjitter, но не заменяетудаление31ms среднего. Busywait вPythonможетконкурироватьзаGIL. Никакие предложенныеforum команды root/sudo здесь не выполнялись.

## Рекомендуемый порядок и rollback

1. CPU/source guarded implicit-once / lazy /combined ablations root наmatchedactiveXR no-client workload: изолироватьexcessbookkeeping, удержать120Hz и nativeactions.
2. Новый процесс CUDA_DEVICE_MAX_CONNECTIONS1 A/B (в томже workload). Keepunset baseline; никаких sourceedits.
3. DirectOVRTX staticfullscene smoke вisolatedpackage target; еслиloads иcorrectpixels, measurecpu/none. Если worker20ms иproducer20ms пока не достигнуты — нетоснованияpromote50. Не прекращать mainloopprofilingиз-за успехаstaticworker.
4. Dynamicimmutablemirror, exactimage-phase movingfiducial proof, boundedlag, first/resetflush. Затем concurrenton1GPU;2GPU толькоеслиестьhardware иwallGPUcontention evidence.
5. Fullrecording decodedallthree, source-boundsequence audit, boundedqueue+drain included, sameactiveXRrig/noQuestmean≤20ms. Затем physicalQuest>30 approvedhumanrun. Строгуюqualification доэтого неclaim.

Rollback всейисследовательскойветки: неимпортировать adapters, удалитьprocessenv overrides, запускатьknownselection. IsolatedruntimeнепопадаетвproductionPYTHONPATH; source/SDKhashescompare. Никакого gitreset/stash/clean илиglobal driver/settings changes.

## Дополнение: exact installed isolated API audit и dynamic adapter

Parent установил отдельный runtime target `/data/ebulochkin/vla-runtime/live30-deep-20261009/optional-ovrtx`; этот агент только прочитал его bytes. Confirmed ovrtx0.5.1.385782 + ovstage0.2.1.385922. `_src/renderer.py:985` step synchronous, ordinal minimum publication; `:1135` reset rebases sensor clock, запрещает negative time; `:340` destroy idempotent и детерминированно закрывает bindings/mappings/attached stage. `_src/types.py:324` CPU mapping уже ready при return; `:833` map interface совпадает; `:871` FrameOutput содержит start_time/end_time/progression; `:919` dict-like output имеет simulation_start/end_time. Current static adapter этим интерфейсам соответствует; result lifetime надо закончить до renderer destruction.

`ovstage/_src/stage.py:524` write_attribute принимает numpy(N,4,4), нормализует до16lanes; operation удерживает caller tensor до wait. `:288` query_from_path_list сохраняет reference на caller-owned path list; требуется release_query + destroy_path_list. `_src/path_dictionary.py:480` create list возвращает int-subclass handle и `:574` get_path_strings позволяет проверить order.

Новый adapter `/tmp/live30-ovrtx-snapshot.py` плюс `/tmp/live30-ovrtx-snapshot.preimages.json` source-guarded на этой паре. Snapshot.freeze создает immutable bytes world matrices; constructor получает loaded+attached stage/renderer, fixed ordered list ALL dynamic links/props/cameras, three products/camera roles, generation/episode, last ordinal. capture строго sequential apply/publish/render/readback,3CPUcopy. Первый capture rebases sensor clock к source_simtime−delta, subsequent steps проверяют renderer simulation_end==source_simtime. Первый snapshot нужен после >=initial_delta_s physics (default1/30); obs timezero priming этим adapter пока не покрыт. Внутри snapshot matrix convention: affine USD row vectors, translation последняя строка; shape/finite/affine checks. ResetXformStack authored True на всехsnapshotpaths. Input paths уже должны быть verified against actual scene; UPSERT сам по себе не доказывает path существовал.

Возвращает images +source_id/hash/episode/generation/camera products/frame times/apply+render+readback timings. output dataset_admissible=False и optical_phase_verified=False: metadata — это provenance request, не доказательство фактического оптического отклика. Targeted moving-marker test все еще нужен. Camera intrinsics/material/topology считаются fixed generation; изменения требуют rebuild. Дополнительные velocities для motion blur, dynamic material/visibility и mesh deformation пока не реализованы. Для exact scientificstate нужно явно отключить motion blur либо передавать весь exposure/velocity history; transform snapshot alone не описывает motion-blurred exposure. Только AST check; runtime effects root измеряет отдельно.
