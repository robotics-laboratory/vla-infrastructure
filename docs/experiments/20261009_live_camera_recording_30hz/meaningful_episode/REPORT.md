# Содержательный single-GPU эпизод: движение и запись трех камер

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted base: `bc6d6a387b195025fded5c954fea8954e667c73c`.

В `reach-demo08` после явной публикации world transforms всех **696 robot
meshes** получен эпизод с видимым движением рук: **56,20 wall Hz с завершением
кодирования трех камер**, 960 принятых transitions и 961 capture каждой камеры.
XR-профиль включен, Quest не подключен. Просмотр decoded samples подтвердил изменение
геометрии Scene camera между кадрами 390/690. Это проверка демонстрационного
движения, а не независимая pixel source-ID проверка каждого кадра.
Повтор сохранил результат `reach-demo07` (56,21 Hz), убрав неэффективные ALL
domains и дополнительный compute-вызов: используются RENDERING и CPU transforms.

Первые шесть попыток выявили ошибку: wrist-камеры двигались, но robot meshes
оставались у home при изменяющемся native TCP. Их software PASS и частоты
не подтверждают корректную запись движущихся роботов. Прежняя формулировка о
проверенном полном live-camera пайплайне в
[single-GPU отчете](../single_gpu/REPORT.md) отозвана; исторические receipts
сохранены. Scope и критерии определены в [PLAN](PLAN.md).

## Эпизод и визуальный результат

Выполнен scripted simulated motion profile: заданные согласованные reaches
двух рук и движения захватов в текущей сцене Piper. Quest не подключен;
реальные роботы не задействованы. Руки опускаются, поднимаются и меняют вынос;
задается открытие/закрытие захватов. Actual TCP смещается от начального положения максимум на **15,13 cm** у каждой
руки, aperture изменяется от **15 до 90 mm**. Максимальная ошибка следования
Cartesian target составляет **9,93 cm**; это не квалификация точности движения.
Конечная ошибка возврата TCP к home меньше 1 µm по сохраненным данным.
Захват или успешная манипуляция предметами не заявляются.

Заданы `--frames 840 --warmup 120 --xr --view-mode minimal --motion reach-demo
--no-witness`. Доски optical witness отключены, чтобы они не закрывали захваты.
Следовательно, новый эпизод не дает независимого pixel source-ID proof;
проверки source ledger/matrices и decoded frame counts будут описаны отдельно.

## Частота и причинная связь

| Проверка | reach-demo08 |
|---|---|
| Принятые state/action transitions и wall interval | 960 transitions; working 16,8766 s |
| Action wall Hz, steady state | 56,81; 839 интервалов после исключения 120 warmup steps |
| Throughput с encoder tail | 56,20 |
| Throughput с полным finish/drain | 53,07; finish 1,2128 s сверх working interval |
| Камерные source captures/ACK | 961/961; включает конечное наблюдение |
| HDF → source snapshot/matrix join | PASS; включает derived mesh matrices из static USD и body poses |
| Видимое движение Scene robot geometry | Подтверждено просмотром кадров 390/690 |
| Оптические идентификаторы всех трех камер | Отключены (`--no-witness`) |
| Queue high-water/backpressure | 4; 64.91 ms |
| Native physics | 3840 шагов по 1/120 s = 32 sim seconds |
| Video playback FPS и длительность | 30 FPS; 961 frames; 32,0333 s |

960 transitions включают 120 control warmup steps; еще 20 media warmup frames
не входят в запись. Throughput с encoder tail делит 960 на интервал от начала
control loop до окончания последнего action/encode. Full finish включает
завершение mirror worker; закрытие HDF и post-run source join выполняются позже.
Название поля `drain_and_optical_decode_s` историческое: при `--no-witness`
оптическое декодирование не выполнялось. Поле `wall_rtf` нормировано на logger
50 Hz; оно не является отношением фактического simulation time к wall time.
Playback FPS, recording wall Hz и simulation Hz — разные величины.
Результат no-Quest не является physical active-Quest qualification независимо
от достигнутой частоты. Этот запуск не меняет S2/D1 gate state.

## Неудачные попытки и исправление

| Попытка | Изменение / наблюдение | Transitions / captures | Encode-tail Hz | Видимая геометрия |
|---|---|---|---|---|
| reach-demo01 | Исходная публикация body transforms | 960 / 961 | 56,94 | FAIL: meshes у home |
| reach-demo02 | Transform publication update | 960 / 961 | 56,12 | FAIL |
| reach-demo03 | ALL domains и compute world matrices | 960 / 961 | 56,95 | FAIL |
| reach-demo04 | Развернуты 502 instance roots | 960 / 961 | 56,12 | FAIL |
| reach-demo05 | GPU transform reads включены | 960 / 961 | 41,56 | FAIL |
| reach-demo06 | GPU transform reads выключены | 960 / 961 | 56,95 | FAIL |
| reach-demo07 | Явные world matrices 696 leaf meshes | 960 / 961 | 56,21 | Видимое движение подтверждено |
| reach-demo08 | Удалены ALL domains и лишний compute | 960 / 961 | 56,20 | Видимое движение подтверждено |

Все восемь raw receipts содержат software `passed=true`. Первые шесть не проходят
проверку видимого движения; исходные bytes не исправляются задним числом.
Точные tested source hashes сохранены в каждом run; название попытки не
подменяет проверку ее кода.

CPU audit **не доказал сбой USD/OVStage иерархии**: в RENDERING и ALL domains
изменение parent body на 0,2 m изменяет worldMatrix и instance root, и mesh proxy
на 0,2 m. У производных worldMatrix при этом остаются ordinal=0, а в change
membership отсутствуют отдельные updates; это может быть поведением учета
производных данных и само по себе не устанавливает причину. GPU/renderer в
этих CPU probes не создавался. Наблюдаемая граница ошибки — потребление
изменившихся transforms видимой геометрией RTX; точный внутренний дефект SDK
не установлен.

Рабочий обход развертывает instances в отдельном derived rendering overlay,
находит ближайший известный rigid body каждого mesh, сохраняет неизменный
локальный transform и на каждом snapshot явно публикует его world matrix.
Source USD и physics state не редактируются; дополнительных physics steps нет.
Source join повторно вычисляет те же mesh matrices из persisted HDF и static
USD mapping. Он подтверждает отправленные matrices, но не заменяет наблюдение
pixels. Locators сохраненных CPU audits, comparison frames и preview будут
зафиксированы в inventory.

Дополнительный `reach-witness09` с оптическими досками завершился **FAIL**
строгого контрастного guard: role1/frame544 декодировался как row544/role1,
но минимальный контраст13 не дал `confident=true`. В остальных двух ролях
все 961 frames прошли; encoder packet counts — 961×3. Это не доказательство
рассинхронизации: recorded identity совпала, надежность чтения недостаточна.
Порог не ослабляется; этот запуск не считается optical PASS.

Повтор **`reach-witness10` прошел**: все source IDs0…960, role IDs и anchors
совпали во всех трех потоках, по 961 decoded frames, при прежнем строгом пороге
контраста **≥30**. Изменена только геометрия witness boards: optional
`--witness-depth-scale 0.5` помещает клетки в 3 cm перед камерой вместо 6 cm,
сохраняя projected pixel/cell размеры. Default1.0 и decoder threshold неизменны.
Фактический минимум контраста успешных кадров отдельно не сохраняется;
receipt доказывает прохождение guard, а не более сильный численный минимум.

[Receipt10](receipts/reach-witness10-result.json),
[worker10](receipts/reach-witness10-worker.json) и
[source join10](receipts/reach-witness10-source-join.json): **57,02 Hz с encoder
tail**, steady57,28 Hz; 960 actions, 961×3 images. Throughput с полным finish и
offline optical decode — **44,05 Hz**. Декодирование после завершения записи
проверяет записанные pixels; RGB рендерились и кодировались во время control
loop. Optical run10 отдельно от viewing run08: proof10 не переносится на каждый
кадр08. В сочетании с sampled geometry audit07 и видимым движением08 это
поддерживает работоспособность исправленного пути, но не устанавливает
all-frame silhouette parity или physical Quest qualification.

## Воспроизводимость и артефакты

Готовы три камеры в одном видео
`/data/ebulochkin/vla-runtime/live30-meaningful-episode-20261009/preview08/episode-three-views.mp4`
и исходная Scene camera в MP4
`/data/ebulochkin/vla-runtime/live30-meaningful-episode-20261009/preview08/episode-scene.mp4`.
Это монтаж/перепаковка **уже записанных RGB**, без повторной симуляции или
рендера. Три исходных H264 потока по 961 frames проверены ffprobe. Экспорт
показывает 32,0333 s при 30 FPS; запись 32 sim seconds заняла 16,8766 working
wall seconds плюс tail. Postprocessing исключен из recording Hz.

[Run receipt08](receipts/reach-demo08-result.json),
[source join08](receipts/reach-demo08-source-join.json) и
[export receipt08](receipts/preview08-export.json) сохраняют команды,
denominators, measured motion, tested hashes и SHA256 готовых видео.
Bulk root: `/data/ebulochkin/vla-runtime/live30-meaningful-episode-20261009`.
Все неудачные попытки01–06, успешные07/08, optical FAIL09 и optical PASS10
остаются в этом root;
малые receipts сохранены byte-exact в `receipts/`, CPU audits — в `audits/`.
Краткое сравнение запусков сохранено в [run ledger](run_ledger.json).
[Artifact inventory](artifact_inventory.json) фиксирует 1192 внешних файла
(2,408 GB), 100 retained artifacts и byte-exact copy provenance.
[Tested source recovery](receipts/source-recovery.json) восстановил и проверил
79 source/hash bindings всех десяти запусков; соответствующие bytes находятся
в bulk `tested-sources/`. [AST parity](checks/format-ast-parity.json) отдельно
фиксирует эквивалентность финального форматирования протестированному коду.

Дополнительный [CPU geometry projection audit07](audits/live30-geometry-projection07.json)
независимо проектирует retained USD vertices через persisted HDF body poses в
три выбранных Scene frames (0/390/690). Projected centroid между390/690 меняется
на 93,35/90,25 pixels слева/справа; темные pixels внутри ожидаемой grip housing
области занимают 83–89% соответствующего кадра и 0% противоположного.
[Наложение hulls](audits/live30-geometry-projection07.png) и
[точный CPU script](audits/live30-geometry-projection07.py) сохранены.
Это sampled соответствие геометрии; hulls не являются occlusion-aware
rasterizer/segmentation, все кадры этим анализом не проверялись.

Исходные historical outputs не редактируются. Новые artifact/evidence entries
для gate qualification пока не создаются: gate bindings пусты, diagnostic
dataset admission отсутствует. Будущий bundle inventory фиксирует provenance
эксперимента и не заменяет contract evidence registration.

## Проверки и ограничения

Raw result.json первых шести попыток содержит `passed=true`, но этот флаг
отражает программные checks и не учитывает найденное позднее несоответствие meshes. Аналогично
`camera_source_alignment_proven=true` в raw receipt означает пройденный
HDF→submitted matrices join; он не доказывает применение этих transforms к
видимой геометрии. Исходные bytes сохраняются; этот отчет фиксирует уточнение.

Optical boards проверяют соответствие кадров источнику, но сами по себе не
доказывают, что все robot meshes перемещаются вслед за body poses. Новая
демонстрация обнаружила пробел в покрытии. После исправления движение геометрии
проверяется отдельно. Каждый кадр не проверен на совпадение геометрии всех мешей;
независимая проверка оптических source IDs относится к отдельному `reach-witness10`.

Первый [repository check](checks/repository01/results.json) сохранен как FAIL:
304 tests PASS, 4 tests FAIL, 38 SKIP. Docs lint и связанный governance test
отклонили абсолютные `/data` video links. Три worker-protocol tests использовали устаревшие fake API:
отсутствовали `RendererConfig`/актуальный constructor и keyword `depth_scale`
у fake witness. Исправлены только эти test fixtures и запись video locators
в документации; GPU implementation не менялась.

Повтор после этих исправлений зарегистрирован отдельно:
[repository02](checks/repository02/results.json) и
[raw log02](checks/repository02/results.log): **PASS**, 308 tests PASS и 38 SKIP.
Пройдены docs/spec/contract/manifest, scoped Ruff и staged/unstaged whitespace;
сохранены 819 frozen files относительно trusted base. Retained raw logs
исключены только из whitespace check. Optional native/PXR tests пропущены в
core environment; реальные GPU/native запуски и CPU geometry audit приведены
отдельно. Первоначальные FAIL bytes сохраняются. Contract structural/semantic
checks проходят, существующие blockers FINAL RC остаются нерешенными.
Production selection и SDK не меняются. Human lifecycle и physical Quest
проверка остаются за пределами этого демонстрационного запуска.

Текущая проверка задержек, свежести и различий физики с master: [temporal/physics audit](../temporal_physics/REPORT.md). Высокая частота сама по себе не означает малую задержку камеры или эквивалентность физики.
