# Демонстрационный эпизод с заметными движениями и живой записью

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted base: `bc6d6a387b195025fded5c954fea8954e667c73c`.

Пользователь запросил содержательный эпизод, просматриваемое видео и проверку
фактической частоты записи. Этот bundle продолжает
[single-GPU прототип](../single_gpu/REPORT.md) отдельным запуском с более заметными
скоординированными движениями рук и открытием/закрытием захватов. Предыдущие
результаты не переносятся на новый motion profile; их байты сохраняются.

## Scope и upstream reuse

CAPABILITY: одна GPU, simulated Piper, согласованные state/action переходы и три
живых видеопотока с проверяемой идентичностью источника.
REUSED: существующий shared scene builder, standalone CPU PhysX, upstream
DifferentialIKController, label/native mapping, snapshot-backed NVIDIA HDF recorder,
OVRTX/NVENC, bounded ownership и source/pixel verification.
GAP: существующий injected motion слишком мал для наглядного видео; требуется
другой детерминированный Cartesian intent и демонстрационный монтаж трех камер.
ADAPTER: опциональный `--motion reach-demo` в существующем diagnostic driver,
без нового episode framework, IK solver или recorder.
ENVIRONMENT: те же изолированные pinned runtimes, что у single-GPU прототипа;
точные source/config/package identities сохраняются в launch/run receipts.
Новые зависимости и изменения production selection не предусмотрены.

Уточнение после первых запусков: крупное движение выявило неподвижные robot
meshes при корректном source/matrix join. Поэтому scope дополнен минимальным
обходом renderer propagation: derived overlay раскрывает robot instances,
из static USD заранее извлекается mesh-to-body transform, а текущие immutable
body poses задают world matrices 696 meshes. Требуется отдельная visual motion
проверка; metadata и optical source-ID сами по себе ее не заменяют. Сбой
вычисления CPU hierarchy не установлен; native SDK не исправляется.

Это simulated scripted reach demonstration, без подключенного Quest и без
команд реальным роботам. Траектория не является human teleoperation или
доказательством успешного захвата/переноса предмета. После получения видео
описание должно соответствовать реально видимому и измеренному движению.

## Выполнение и проверка

1. Добавить ограниченную по амплитуде и скорости последовательность намерений:
   заметные перемещения обеих рук, согласованные фазы, открытие/закрытие захватов
   и возвращение. Сохранить source intent → processors/label mapping → dataset
   action → native command; измерять actual state отдельно от target.
2. Выполнить CPU checks изменения и последовательный GPU integration run на
   одной GPU. Startup/warmup не считать принятыми кадрами. Все failed attempts
   оставить с исходными логами и source/config hashes.
3. Проверить finite state, native mimic residual и saturation; показать actual
   TCP excursions и диапазон aperture по сохраненному состоянию. Если заданные
   reaches не реализовались, исправить профиль и сохранить неудачную попытку.
4. Проверить canonical HDF→snapshot/matrices join, порядок и количество кадров
   каждой камеры, bounded queue и полный tail. Для просмотра захватов выбран
   `--no-witness`: оптические доски закрывают часть полезной сцены. Поэтому
   независимая проверка pixel source-ID в новом эпизоде отключена; номер кадра
   в metadata не заменяет ее. Ранее сохраненные optical tests не редактируются
   и не выдаются за pixel proof именно этого эпизода.
5. Подготовить отдельное просматриваемое видео из записанных потоков, сохранив
   сырые потоки. В caption/отчете указать playback FPS и measured wall Hz записи:
   закодированный FPS не измеряет производительность. Монтаж не должен скрывать
   пропущенные кадры или менять вывод о фактическом движении.
6. Сохранить commands, measured denominators, receipts, locators и SHA256 в этом
   bundle. Обновить [REPORT](REPORT.md), INDEX и artifact inventory после завершения.

Предполагаемый bulk root:
`/data/ebulochkin/vla-runtime/live30-meaningful-episode-20261009`.
Видео, HDF, USD snapshots, полные логи и runtime outputs остаются вне Git;
в bundle сохраняются небольшие receipts и воспроизводимые locators/digests.

## Что означает частота

Отдельно сообщаются принятые action transitions на wall second, уникальные кадры
каждой из трех камер и complete-run throughput с encoder drain. Для каждого
значения нужны явные count и elapsed wall time, а также состав исключенных
startup/warmup/decode затрат. Конечное наблюдение может давать N+1 frames на N
действий; это не дополнительное действие. Simulation clock 4×1/120s на control
tick и video playback FPS указываются отдельно.

Новый no-Quest run может подтвердить performance именно этого motion profile.
Он не доказывает прежнюю hard goal >30 wall Hz actions и каждой камеры при
физически подключенном active Quest3. Около50 Hz без Quest остается screening
ориентиром. Gate bindings пусты; contract facts, S2 qualification и D1 admission
этим демонстрационным запуском не изменяются.

## Сохранность и проверки

Новые документы индексируются как текущий owner `vr.performance`; сохраненные
receipts/inventory после завершения индексируются как historical/mutable:false.
Root MANIFEST membership не расширяется автоматически. Перед завершением:
relevant CPU tests, docs/spec/contract checks, historical preservation от trusted
base, selective manifest verification и `git diff --check`. Код и новые документы
готовит текущая ветка; никаких изменений SDK и исторических bundle members.
