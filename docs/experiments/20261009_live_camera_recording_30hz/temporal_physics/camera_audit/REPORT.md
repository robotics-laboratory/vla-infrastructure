# Проверка camera Mesh phase и old-position ROI

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted base: `fbdee2055efa325c352e13b321223cdf6c2f3e40`.
Baseline master: `beaedfd1116577fd4d8026232cfb96cba0b030fa`.

**Mesh09: optical source/role IDs совпали во всех633 изображениях; общий strict
result FAIL.** Все три камеры прошли current ROI и centroid, но right wrist
превысила абсолютный old-position ROI threshold на106 изменениях позиции.
Hold-анализ обнаружил ненулевой фон выше того же порога даже в позиции,
которую маркер ещё не занимал. Поэтому106 FAIL нельзя считать106 доказанными
случаями temporal ghosting. Пороги не ослаблялись; исходный FAIL сохранён.

[Метрики](metrics.json) содержат результаты по каждой роли и host packet latency.
[Provenance](sources.json) содержит SHA, первичные SDK sources, команды/locators
и ограничения. Retained CPU aggregator сохраняет provenance.json; в этом
Git bundle те же bytes названы sources.json для общей navigation. Bulk receipts, crops, исходники CPU probes и frozen tested sources
сохраняются отдельно в
`/data/ebulochkin/vla-runtime/live30-correctness-20261009/camera-audit/`
под точными basename исходных `/tmp/live30-correctness-camera*`.

## Проверяемый путь и результаты

Opt-in [helper](../mesh_freshness.py) создаёт54 диагностических Mesh только в
render overlay. Independent visible namespace явно связан с матрицами исходных
трёх камер через existing `mesh_local @ source_parent_world`; тот же renderer
batch публикует обычные robot meshes. Native physics, actions, source USD и HDF
labels не переписываются. [CPU verifier](../test_mesh_freshness.py) независимо
декодирует optical bits и измеряет скачки80px, удержания и pseudo-random позиции.
FFmpeg использует `-vsync 0`; все211 кадров каждой роли проверены после drain.

| Run | Strict verdict по ролям0/1/2 | Причина / область результата |
|---|---|---|
| Mesh01 | FAIL / FAIL / FAIL | Camera children наследовали invisible; marker отсутствовал |
| Mesh05 | FAIL / FAIL / FAIL | Helper не учёл effective vertical pixelK; исходные ROI неверны |
| Paced06 | FAIL / FAIL / FAIL | Та же ошибка ROI, при wall30Hz |
| Mesh08 | FAIL / FAIL / PASS | Wrist code board закрыт robot geometry; scene phase PASS211 |
| Mesh09 | PASS / FAIL / PASS | Все optical IDs/current/centroid PASS; right old ROI confounded |

Mesh09: minimum bit contrast230/216/204, minimum current ROI .99990/.99990/.99854,
maximum centroid error .94693/.96686/.96547px; source/role mismatches отсутствуют.
Все роли правильно показали106 discontinuous position changes. Maximum normalized
old ROI .02544/.16953/.07032 при неизменном лимите .08. Остальные критерии:
bit contrast≥30, current ROI≥.8, centroid error≤2px и точные source/role bits.
Это наблюдаемая нулевая **source-ID frame phase** контролируемого Mesh witness;
оно не измеряет экспозицию на wall clock и не доказывает pixel pose каждого CAD Mesh.

## Найденные setup errors сохранены

USD visibility определяется ancestor pruning: исходные camera prim имеют
`visibility=invisible`, поэтому их Mesh children тоже невидимы. Отдельный
render-only root сохраняет исходную camera visibility.
[OpenUSD Imageable API](https://openusd.org/release/api/class_usd_geom_imageable.html),
retrieved2026-10-09, подтверждает эту семантику. Exact Mesh01 helper replay
совпадает со всеми первоначальными измерениями; strict HDF source join replay PASS.

Raw USD optics2.208/5.76/3.24 задают aperture aspect16:9; output960×600 имеет
aspect1.6. При square pixels и expandAperture effective pixelK имеет
fx=fy≈368, cx480, cy300. Ошибочная формула из raw vertical aperture давала fy≈408.889
и предсказывала y530 вместо фактического y507. Исправление author explicit
`aspectRatioConformPolicy=expandAperture`, `pixelAspectRatio=1`; helper использует
fy=fx и отвергает неподдерживаемые конфигурации. Исходные FAIL05/06 не переименованы
в успешные результаты после recalibration.

Master contract pins Isaac Lab0c2e2c64. Его clean Git camera.py751–787 использует
fx=width×focal/horizontalAperture и fy=fx для камер без authored OpenCV distortion.
Native Isaac renderer создаёт tiled RP без явного aspect override;
RenderSettingsBase schema задаёт expandAperture/pixelAspect1. Локальные bytes/SHA
сохранены в `camera-audit/live30-correctness-camera-optics-source/`.
Публичные [Camera sources](https://github.com/isaac-sim/IsaacLab/blob/main/source/isaaclab/isaaclab/sensors/camera/camera.py)
и [RenderProduct API](https://docs.omniverse.nvidia.com/kit/docs/usdrt.scenegraph/7.6.1/api/classusdrt_1_1_usd_render_product.html),
retrieved2026-10-09, поддерживают square-pixel/default-policy вывод.
Публичный main отличается от installed pin; именно локальный clean pinned source
служит точным baseline. **Raw optics equality не заменяет effective pixelK**;
при dataset materialization нужно сохранять resolution/projection policy и
проверять effective K, особенно при distortion или aperture offsets.

CPU HDF→USD triangle rays на sources0/17/95/128/209 подтвердили Mesh08 occlusion:
27–28 из34 center rays каждой wrist пересекали robot triangles до board depth.06;
ближайшая depth .0371693 при near .01. Mesh09 использует depth.02/background.021,
без изменения near clip или основной сцены. Это sampled opaque two-sided ray
analysis, не полный material/depth renderer. Actual09 pixels подтвердили устранение
wrist code occlusion.

## Почему right old ROI остаётся неразрешённым

Empty slot x180 в right frames0–15 имеет normalized energy .0952–.0968, хотя он
не был занят маркером ни в20 warmup frames, ни в начальном hold. Empty x100 после
перехода на hold96–111 стабилизируется около .121, первый96≈.135. Локальный фон
не совпадает с black anchor x636. Default UsdPreviewSurface с diffuse0 сохраняет
specular response при metallic0/ior1.5;
[официальная спецификация](https://openusd.org/release/spec_usdpreviewsurface.html),
retrieved2026-10-09. Это поддерживает интерпретацию background confound, но отдельно
не измеряет долю reflections, render history и codec artifacts. Background
subtraction не применялась для превращения исходного strict FAIL в PASS.

## Время и пределы вывода

Mesh09 source sample→packet return, sources1–210 включая drain: median81.03–81.67ms,
p95 86.42–87.08ms, max104.22–121.25ms по ролям. Paced06: median113.53–114.34ms.
Это host return Encode/EndEncode; write completed не означает fsync.
`worker_render_submitted_monotonic_ns` ставится после capture/consume и является
host upper bound, не GPU/exposure timestamp. Source0 startup freeze исключён из
steady latency; declared capture_end совпадает с source simulation time, но
metadata само по себе не доказывает момент появления каждого пикселя.

Все runs diagnostic: Quest отсутствует, input source deterministic injected XR,
Mesh09 XR core enabled at admission, original view, source queue1. Нет physical
S2 qualification, D1 admission или проверки реального Quest display latency.
Нулевая source-ID phase не означает81ms image age bound для любого material,
не универсальный no-ghost результат и не динамическую physics equivalence с master.
Physics/causal audit и итоговая интерпретация принадлежат
[общему текущему REPORT](../REPORT.md). Rollback probe: отключить `--mesh-freshness`.
