# Движение Piper не доходит до изображения OVRTX

Дата проверки: 2026-10-09. Read-only аудит; выполнены только CPU OpenUSD/ovstage проверки, без создания Renderer, GPU-прогонов и изменения исходной USD/окружений. Полный реестр локальных SHA256 и первичных URL: `/tmp/live30-meaningful-source-registry.json`.

## Что доказано непосредственно

Источник `reach-demo01` содержит разные физические позы. Для кадров 390 и 690 ожидаемое смещение центроидов геометрии достигает 0.15356 м и 137 пикселей сцены. Камера сцены в этом интервале неподвижна. Это значительно превышает различие декодированных изображений; имеющиеся изображения показывают ту же домашнюю конфигурацию. Числовые подробности и хеши источников: `/tmp/live30-meaningful-domain-audit.json`. Метаданные источника и optical boards сами по себе не доказывают движение геометрии.

CPU-сцену создавал непосредственно ovstage 0.2.1.385922, `CUDA_VISIBLE_DEVICES=''`, без импорта ovrtx. Открыл исходную mirror.usda отдельно с RENDERING=1 и ALL=3; выбрал gripper_base, вложенный instance root и вложенный instance-proxy Mesh. После `omni:resetXformStack=True` и записи effective-world `omni:xform` родителя с +0.2 м по X на ordinal=2, seal и CPU_INCREMENTAL compute_hierarchy(2,2), все три worldMatrix изменились ровно на +0.2 м. Это опровергает исходную гипотезу, что Rendering population отсутствует нужная иерархия, и показывает исправную CPU-пропагацию через реальные native instances. Скрипт, полный JSON и stdout: `/tmp/live30-meaningful-cpu-hierarchy.{py,json,log}`.

Дополнительный CPU-прогон `/tmp/live30-meaningful-cpu-delta.{py,json,log}` проверил range membership: авторский omni:xform родителя имеет ordinal=2; все derived worldMatrix возвращают ordinal=0 даже после изменения payload; read range between(2,2) не возвращает derived/leaf строки. Это факт наблюдения, но не доказанный дефект: derived-колонки могут иметь другой внутренний механизм dirty tracking. Storage omni:xform после ndarray-записи канонически float64 lanes=16; версия про неправильный NumPy shape не подтверждена.

У выбранных USD body roots и их потомков отсутствуют authored reset-xform-stack флаги. Каждый робот имеет 348 Mesh, 251 из них instance proxies. Временное деинстансирование в анонимном USD layer (без записи файлов) требует 502 instance root мнения на первом проходе, затем ещё 480 newly exposed VisualMaterials instance мнений; после первого прохода geometry уже перестаёт быть proxy. Среди authored атрибутов робота не найдено RTX/fabric/static/dynamic override.

## GPU результаты, сообщённые координатором (не мои прогоны)

01 исходный путь, 02 explicit CPU hierarchy, 03 ALL+compute, 04 ALL+compute+geometry deinstance: робот визуально неподвижен. 05 дополнительно read_gpu_transforms=True тоже визуально FAIL и примерно 41.85 Hz steady против около 56–57 Hz у некоторых прежних вариантов. Эти цифры являются локальными сообщёнными результатами; нужны соответствующие сохранённые receipts координатора. Это исключает утверждение, что перечисленные переключатели исправили meaningful video.

## Точный upstream протокол IsaacLab

Исследованный checkout `/tmp/s0-isaac-develop.O0fHSu/source/isaaclab_ov/isaaclab_ov/renderers/ovrtx_renderer.py` содержит две реализации. Актуальный attached-ovstage путь:

- `_setup_xform_bindings_ovstage` (1957–2010): выбирает `newton_model.body_label`, исключает камеры/GroundPlane; привязывает **body parent paths**, не Mesh leaves; один раз пишет boolean `omni:resetXformStack=True`.
- `_update_transforms_ovstage` (2198–2239): строит world matrices из `body_q` и retained scale в Warp mat44d GPU; пишет `omni:xform`, MATRIX, is_array=False, ordinal=current, producer cuda_stream и wait.
- `_render_ovstage` (2372–2400): seal current ordinal, renderer.step(products,dt,ordinal), increment. Явного compute_hierarchy нет.
- Initialization (1815–1874): open USD Rendering, init relationships/resets/bindings, seal, **attach_ovstage последним**. Наш worker ранее attach до population. Это конкретное различие и кандидат отдельного минимального теста; не доказанная причина.

[Первичный код IsaacLab](https://github.com/isaac-sim/IsaacLab/blob/develop/source/isaaclab_ov/isaaclab_ov/renderers/ovrtx_renderer.py), получен 2026-10-09. Локальный хеш фиксирует фактически исследованные байты; develop URL изменяемый.

## Поддержанные API и границы выводов

`RendererConfig(read_gpu_transforms=True)` поддержан локальным Python wrapper и C config. Он задаёт GPU world propagation. Public default None не доказывает конкретный native default. CPU/GPU switch уже оказался недостаточен по результату 05.

`renderer.step(...ordinal=N)` сам вызывает attached update_from_stage перед step. Добавление отдельного update_from_stage по документации должно быть избыточно; это не отдельная операция «invalidate BVH». При attach параметры ordinal являются минимальной publication gate, а не историческим selector. [OVRTX integration](https://nvidia-omniverse.github.io/ovrtx/core/ovstage_integration.html), получен 2026-10-09.

Нельзя заменить Stage write на renderer.write_attribute при сохранении attach: upstream CHANGELOG 0.4 прямо указывает ошибку OVRTX_API_ERROR для stage-building/write/map APIs в attached mode. [CHANGELOG](https://raw.githubusercontent.com/NVIDIA-Omniverse/ovrtx/main/CHANGELOG.md), получен 2026-10-09.

Официальный authored transform protocol: omni:xform local; reset=True делает его effective-world, дочерние примы продолжают наследование. Float64 lanes16, row-vector, translation last row. Derived omni:fabric:worldMatrix по ovstage transform docs — read-only output; писать его в generic transform-authoring path не следует. [ovstage transforms](https://nvidia-omniverse.github.io/ovstage/scene/transforms.html), [OVRTX transforms](https://nvidia-omniverse.github.io/ovrtx/scene/transforms.html), получены 2026-10-09.

Есть специализированное исключение в официальном ovphysx.utils step_and_write_to_ovstage: utility пишет reconstructed worldMatrix непосредственно, не меняет omni:xform/reset и не обновляет потомков. Это consumer-facing physics output contract, а не рекомендованная замена local protocol для произвольного дерева. Позднее compute_hierarchy перезапишет его из прежних locals. [ovphysx integration](https://nvidia-omniverse.github.io/PhysX/ovphysx/latest/ovstage_integration.html), строки 427–429, получен 2026-10-09. Поэтому direct-worldMatrix leaf write может быть узким диагностическим bypass на данной версии, но требует явной записи unsupported/stable-protocol caveat и отсутствия последующей hierarchy computation.

## Следующие минимальные диагностические шаги и rollback

Прямые Mesh effective-world omni:xform+reset=True: static mesh_to_body из snapshot USD умножается на live body_world. Это сохраняет официальный authored protocol, делает leaf явно changed at N и обходит propagation-notification путь. Результат 07 приведён ниже. Не выдавать этот workaround за canonical IsaacLab: upstream обновляет body parents.

### Дополнение: 07 и независимая sampled проверка

Координатор сообщил SUCCESS07: CPU transforms, 502 derived-overlay deinstance мнения, прямые effective-world записи 696 Mesh. Полный локальный capture около 56.2136 Hz, steady 57.141 Hz; реальные руки в изображении двигаются. Этот workaround обновляет leaves явно; точная внутренняя причина пропуска parent-to-descendant renderer update ещё не установлена. Варианты ALL/compute/GPUTrue не следует приписывать этому успеху; координатор отдельно проверяет их удаление в 08.

Я независимо выполнил CPU-only sampled проверку на retained `reach-demo07`: `/tmp/live30-geometry-projection07.{py,json,log,png}`. Использованы исключительно вершины реальных gripper_link1/2 Mesh из stage_snapshot.usd, статическое mesh-to-body отношение из этой USD, фактические HDF world poses тела и сцены, реальные focal/aperture. FK и requested actions не использованы. Декодированные координатором PNG источников 0/390/690 связаны с его экспортным receipt (ffmpeg select exact frame ordinals, vsync=0); все входные файлы SHA256 закреплены. Визуально projected hull совпадает с видимыми пальцами во всех трёх кадрах. Между 390 и 690 projected finger centroid смещается на 93.347 px слева и 90.251 px справа. В объединённых expected-finger hull ROI 90.26%/87.70% пикселей изменились более чем на 20 по максимальному RGB channel; 88.47%/83.60% — более чем на 50. Это намного больше codec/path-tracing шума.

JSON дополнительно содержит dark-pixel occupancy (mean RGB<100) внутри eroded projected hull: matching frame 87.85%/89.08% слева для 390/690 и 84.13%/83.32% справа; opposite frame в тех же ROI во всех четырёх случаях 0%. Это описательная метрика конкретных тёмных пальцев на светлом фоне, не универсальный segmentation gate. Convex hull не учитывает occlusion и не является native ground-truth mask. Sampled geometrical alignment проверяет только три кадра scene camera, не все 960 frames, не wrist source alignment и не physical/XR qualification.

Если leaf не поможет, сравнить новый graph с initialization, полностью опубликованной **до attach**, как IsaacLab. Если это не поможет, отдельный diagnostic standalone Renderer.open_usd + deprecated renderer.write_attribute отличит ovstage consumer integration от renderer geometry update; этот тест нельзя делать через уже attached graph. Также стоит проверить минимальный движущийся примитив и moving mesh на каждом пути, затем реальную geometry silhouette.

Rollback: удалить только новые derived-overlay мнения и экспериментальные runtime переключатели; не менять исходный stage_snapshot/USD, физику и actions. Вернуть matched baseline body-only transforms после диагностики. Повторно hash-pin retained launch sources для каждого нового запуска. Historical recordings со статичной геометрией сохранить как metadata PASS / visual FAIL. Пока meaningful geometry source verification не проходит, native source IDs/optical witness не устанавливают correctness RGB.
