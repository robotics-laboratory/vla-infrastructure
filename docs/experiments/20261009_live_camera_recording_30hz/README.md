# Исследование записи live RGB >30 Гц с Quest 3

Продолжение: [глубокое исследование и реальные live/profile прогоны](deep_research/REPORT.md). Оно добавляет tested OVRTX GPU/NVENC, standalone PhysX, Fabric batching, live source joins и отрицательные результаты; выводы первой фазы ниже сохранены в исходном scope.


Продолжение: [запись30Hz и сборка LeRobot из live NVENC](dataset30/REPORT.md),
включая exact source/terminal/PTS проверки и независимое чтение датасета.

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Task base/trusted preservation base: `beaedfd1116577fd4d8026232cfb96cba0b030fa`.
Branch: `research/live-camera-recording-30hz`; дата: 2026-10-09.

Цель — найти архитектуру NVIDIA/Isaac для >30 средних wall Hz действий при активном XR с Quest 3 и
уникальных live RGB кадров каждой из трёх камер. Основная геометрия —
960×600; 640×480 рассматривается как явно отличающийся кандидат.
Без подключённого Quest ориентир — около 50 Гц полного runtime при той же XR конфигурации.
Исследование не выбирает production profile и не принимает gates.

## Upstream audit перед bounded probe

- CAPABILITY: аппаратная запись трёх RGB потоков непосредственно из RTX.
- PINNED UPSTREAM: установленный Isaac Sim 6.1 / Kit 110.3,
  `omni.replicator.core` 1.13.36, `omni.replicator.nv` 1.1.6.
- UPSTREAM OWNS: RenderProduct, post-render H264 annotator, аппаратный encoder,
  render barrier `rep.orchestrator.step`.
- REMAINING GAP: измерить доступность/throughput API и декодируемость в простой
  сцене. Это не тест Piper/CloudXR, action recorder или physics alignment.
- ADAPTER: самостоятельный диагностический скрипт, стандартный H264 output;
  production runtime не изменяется, зависимости не устанавливаются.
- ENVIRONMENT: существующий declared Isaac environment; output вне SDK.
- NO FRAMEWORK: только composition upstream APIs; никаких новых simulator,
  controller или dataset abstractions.

[Полный отчёт](REPORT.md), [история](HISTORY.md), [ledger](run_ledger.json) и
[инвентарь артефактов](artifact_inventory.json) находятся в этом bundle. Все неудачные
попытки сохраняются вместе с успешными. Исторические ветки читаются без правок.
