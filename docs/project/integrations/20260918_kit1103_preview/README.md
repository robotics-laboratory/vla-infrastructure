> Historical integration checkout. Current project entry point and per-user storage: [migration operations](../../migrations/20260918_isaac1103/OPERATIONS.md).

# Общий VR запуск и откат

Рабочая копия для всех Linux-пользователей: `/data/vla-infrastructure/robosyn-kit1103`.
SDK 6.1 установлен отдельно; прежние SDK и demo checkout не обновлялись.
Интеграция разрешена пользователем; это не принятие physical S2/Quest gate.

После принятия соответствующих NVIDIA лицензий, **в своей login shell**, без sudo:

```bash
export OMNI_KIT_ACCEPT_EULA=Y
export ISAACLAB_CXR_ACCEPT_EULA=1
cd /data/vla-infrastructure/robosyn-kit1103
./run-vr --hud-on-start
```

По умолчанию: Sim6.1 / Kit110.3, Scene Partitions, три preview (left wrist, right wrist, scene). Кнопка X управляет показом всех preview. Существующие per-hand sliders, clutch, rebase/recenter и mapping не меняются.

CloudXR запускается upstream IsaacTeleop в **вашем** `~/.cloudxr`. Первый запуск может загрузить его runtime. Открыть на Quest точный [NVIDIA client release-1.4.x](https://nvidia.github.io/IsaacTeleop/client/release-1.4.x/), выбрать Isaac Lab, Reset to defaults, Quest3, адрес этой машины. Физическое подключение и движение коллеги ещё требуют acceptance-теста.

На стандартных портах одновременно запускается один оператор. Если48322 занят чужим CloudXR, launcher откажется запускаться; владелец должен штатно завершить свой сервер. Чужие процессы launcher не останавливает. Для **своего уже запущенного** CloudXR использовать `--cloudxr-mode existing`: manifest и IPC берутся только из вашего home, UID каталога проверяется.

## Откат

Завершить текущий запуск и выполнить:

```bash
./run-vr --stack legacy --hud-on-start
```

Это выбирает прежние Sim6.0.1 / Kit110.1.2 / Lab913ac53f, прежние runtime configs, два preview, isolation=off и отдельный пользовательский cache. Ничего переустанавливать или удалять не надо. Прежняя recursion при видимой камере preview в этом режиме ожидаема.

Для диагностики можно отдельно выключить только partition policy (`--preview-isolation off`) или оставить два preview (`--preview-cameras 2`). Старый Kit с включёнными partitions launcher отвергает.

Исходный demo60a2786 и accepted environments остаются нетронутыми; legacy режим общего launcher добавляет лишь перенос записей в личные каталоги. При потере самой новой рабочей копии исходный checkout остаётся самостоятельным резервным путём.

## Данные пользователя

По умолчанию `~/.cache/vla/robosyn-isaac61` или `robosyn-legacy`: Kit portable-root, XDG config/cache/data, CUDA/Warp, временные и converted assets, launch manifests и logs. Это отдельные0700 каталоги текущего UID. `HOME` должен совпадать с home Linux-аккаунта; shell после некорректного `su` отвергается.

Можно задать собственный `--state-root /data/.../my-private-vr-cache`; каталог должен принадлежать вам. Не использовать git tree. Перед реальным запуском проверить `./run-vr --dry-run`. Права чтения shared SDK/asset paths проверяются фактическим запуском/верификацией pin-ов; разрешение на запись SDK не требуется.

Полная запись PNG не включена. `--capture-preview-evidence` включает ограниченный набор PPM для диагностики feed; обычный запуск сохраняет manifest, stdout и итоговый JSON. Сохранение scene screenshot — только через `--scene-preview /path/outside/repo.png`.

## Проверка без физического клиента

```bash
./run-vr --xr-smoke --hud-on-start
```

Этот60-шаговый тест проверяет создание scene/cameras/session, hide/show/reset/recenter, но не физический tracking и не пригодность FPS для оператора. Для ручного приёмочного прогона нужны Quest, три live preview, движение обоих контроллеров/headset и взгляд sensor прямо на preview, с pixel-детектором, минимум3000 кадров.

Hot teardown/recreation камер и live restart XR внутри той же Kit application не являются поддержанным путём этой интеграции: при необходимости перезапустить процесс. Обычный reset robot scene и hide/show проходят отдельные проверки. Ошибка потерянного partition останавливает рендер/запуск, а не включает незащищённый fallback.
