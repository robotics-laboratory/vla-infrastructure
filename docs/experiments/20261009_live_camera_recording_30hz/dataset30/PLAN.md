# Запись30Hz и сборка LeRobot из live NVENC

Kind: experiment; status: current; owner: `vr.performance`; mutable: true.
Trusted base: `e1f57032aba4777cb023ac26192eb6bb182f734a`.

CAPABILITY: полноценный30Hz recording episode с HDF states/preclip actions,
тремя NVENC camera streams и последующей materialization LeRobot v3.
PINNED CANDIDATES: текущий NVIDIA Episode Recorder; PyNvVideoCodec2.2.3;
LeRobot0.6.1 из declared core; FFmpeg/PyAV stream-copy; existing projection
validation/schema/QA in tools/isaac_vr_lerobot_materialize.py.
UPSTREAM OWNS: causal rows/HDF, encoding/GPU lifetime, Parquet/video metadata,
video decoding and DataLoader. Existing pacing/source queue1 reuses current
experimental driver; no new physics/controller/robotics framework.
GAP: existing materializer expects offline RGB replay/PNG identities; live NVENC
packets need their own exact obs/snapshot join, terminal successor and
container PTS checks. Avoid fabricating an offline replay proof for live pixels.
ADAPTER: minimum concrete live-media bridge to existing projection checks and
pinned LeRobot API; choose public import boundary after pinned-source audit.
ENVIRONMENT: existing Isaac Python owns HDF extraction/live recording;
existing core Python owns LeRobot. No dependency installs or SDK edits planned.

1. New serial one-GPU run:960 controls/961 sources, reach-demo, no witness/marker,
   source queue1, original Kit view,30Hz wall pacing; XR core enabled but no Quest.
2. Check source/action/successor causal joins and host clock intervals/drain.
3. Materialize exact source actions/state and three ready encoded streams.
   Source frameN retained only as terminal successor, not an actionless BC row.
4. Decode all frames, compare stream-copy pixel/frame fingerprints, validate
   exact30Hz PTS, labels/state, and iterate upstream dataset/DataLoader.
5. Meaningful negative checks for changed source identity, missing/reordered
   media/terminal evidence, timestamp/label corruption; retain every attempt.
6. Register report/artifacts in INDEX, selective MANIFEST refresh and scoped
   repository checks from trusted base. Commit/push existing research branch.

Scope remains experimental: synthetic input, no task grasp/success claim, no
Quest freshness, no physical qualification or D1 admission. Existing selected
RECORD/offline path and production configuration stay authoritative.

## Повторный upstream audit после300LOC

`tools/isaac_vr_live_dataset.py` остается конкретным двухэтапным адаптером
одного экспериментального эпизода. Объем вырос из-за обязательных source/hash,
causal-row, terminal, packet, transform, PTS и final-output проверок; собственный
формат обучения или альтернативный recorder не вводятся. Схема обучения,
Parquet, video offsets, stats и DataLoader принадлежат LeRobot. Projection,
native causal validation, asset closure и terminal validation переиспользуются.

Проверен установленный LeRobot0.6.1: публичного импорта уже закодированного
эпизода нет. `save_episode(episode_data=...)` все равно читает staged images
для stats и кодирует их; streaming путь также кодирует и может пропускать кадры
при заполненной очереди. Поэтому выбрана изолированная instance-only подмена
одной точки импорта на время serial `save_episode`: writer source SHA256
закреплен, источники копируются во временный каталог перед upstream move/delete,
все методы восстанавливаются в `finally`. Installed SDK не меняется. Это
исключение из предпочтения публичного API имеет узкую проверяемую область:
один RGB эпизод0, три камеры, без streaming/depth/batch encoding.

Первый экспорт выявил отдельный gap: канонический replay требует Fabric;
экспериментальная запись честно объявляет `ovphysx_cpu`. Новый явно названный
experimental verifier использует общие integrity проверки, принимает только
точный standalone injected/no-client profile и возвращает тот же артефакт.
Канонический verifier остается Fabric-only. Native metadata с именем offline
profile используется как идентификатор схемы causal rows; `live-media.json`
отдельно объявляет фактический live pixel profile и запрет dataset admission.

Установка зависимостей, fork SDK, RPC, универсальный backend и изменение
selected runtime не нужны. Компромисс: CPU decode/PNG staging/statistics после
эпизода сохраняются. Их время измеряется отдельно от recording throughput.
