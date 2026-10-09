# Покрытие источников для русского сводного черновика

Рабочий snapshot 2026-10-09 13:49:12 UTC; HEAD `d5566834d29ef8bb56e4fb62bb324e23e0869100`. Исследовательский checkout не изменялся этим агентом. GPU/Kit/SDK не запускались, установленные пакеты не изменялись. Черновик `/tmp/live30-deep-report-draft.md` консолидирует десять исследовательских направлений и независимый широкий source/repo/forum survey; дополнительные MD являются углублениями направления, а не отдельными валидационными голосами.

В `/tmp/live30-deep-source-coverage.json` зафиксированы SHA256 34 MD/JSON из текущего research owner и25 top-level runtime result/receipt JSON, а также3 optical-decode receipts. Raw-data snapshot `/tmp/live30-deep-results-snapshot.json` содержит данные этих25 результатов. Время snapshot — точка отсечения: root продолжает tests, данные позднейших запусков следует добавить явно.

Точное dedup строк URL в этих материалах:460 locators. Это включает страницы документации, API/raw GitHub ссылки, commit links, форумы и повторные представления источника; число не означает460 независимых проверенных публикаций. Поисковые ledger entries тоже неоднородны: запросы, query families и topics, их нельзя суммировать и выдавать за число уникальных поиска/подтверждений.

| Ledger | URL locators в JSON | Записанная поисковая область | Локальная/точная база |
|---|---:|---|---|
| independent_sources.json |152|40 query entries,128 browser records|8 pinned repos,24 downloaded primary files,11 installed hashes|
| media_sources.json |46|30 search query entries|44 source records, archive/wheel/version pins|
| media_exact_sources.json |7|1 follow-up search ledger|11 exact source files,5 explicit source corrections|
| ovphysx_sources.json |50|6 search-ledger collections|56 source records, release/main pins, optional package validation|
| render_sources.json |53|8 topic families; exact-query claim explicitly ограничен|50 source records,9 local sources|
| scheduler_sources.json |9|6 ledger entries|23 local sources,9 primary sources|
| storage_sources.json |22|12 query entries|22 source records,9 local hashes, CPU-only storage assay|
| tiled_sources.json |13|9 query entries|13 source records,13 local sources; source/optics guards|
| warp_newton_sources.json |19|5 query entries|14 browser records,17 installed-source records|
| xr_sources.json |73|22 query ledger entries|25 local files,14 primary-doc/forum snapshots,8 extra web sources,5 canonical startup files|

PHYSICS_AUDIT имеет собственный installed preimage artifact и direct primary links; OVRTX notes используют отдельные runtime receipts и fixtures. Поиск охватил NVIDIA official docs/samples/repositories, точные installed extensions, официальный архив Video Codec SDK, NVIDIA developer forums, Isaac Lab/Newton issues, Stereolabs ZED и публичный retained Isaac benchmark. Сведения форума служат traceable lead; final architecture claims проверены against source/version либо явно отмечены как hypothesis.

Источники охватывают code и platform behavior, но публичного exact-match benchmark «Isaac6.1/Kit110.3 + PIPER-X + live connected Quest +3fresh960×600 +>30 wallHz actions» не найдено. Главные измерения сделаны root на текущей машине; все scope exclusions в raw receipts сохранены.

Для standalone physics raw V3 отличается от ранних неуспехов: `ovphysx-cpu-fixedbase-v3/result.json` завершён,27-body inventory retained,917 controlHz для physics-only; camera/XR/IK/recorder/contact qualification исключены. OVRTX GPU decode420×3 PASS подтверждает source-clock freshness в HDF replay; physical-pose alignment и liveXR этим не установлены. Kit sibling decode FAIL остаётся FAIL по confidence guard при correct consecutive118 IDs/role и lag2. Профилируемые GPU38.25/32.96Hz и atlas exposure/schema guard failures добавлены как results, без непроверенной attribution или фиктивной atlas скорости.

Файлы черновика и coverage лежат только в `/tmp`. Старый frozen first-phase report не редактировался. При переносе черновика relative audit links предназначены для каталога research owner; root выполняет документационные регистрации и проверки по project policy.
