# Gate D0 pinned LeRobot audit

Scope: semantic contract and offline verification only. No robot, CAN, Quest, simulator, training, HIL, or dataset mixing activity occurred.

## Pinned-source identity

The installed LeRobot 0.6.1 files were SHA-256 compared with the same files fetched from official commit `7e241bd630a3719a56157a497ce5d08f244784f1`; every pair was byte-identical.

| Source path | SHA-256 |
|---|---|
| `src/lerobot/scripts/lerobot_record.py` | `ea53ad1dca8a3c60e3aa2e15993466c4a59c6c9f2197fceadaf034e3ee0c128c` |
| `src/lerobot/robots/robot.py` | `82b2a59afb5bf1b7191eca8b64bd578f70020be287c8b4d39afae642a5be350e` |
| `src/lerobot/processor/pipeline.py` | `a4d842ff4d123e74991d06c728d4a2fc12634f443aa52cb047a47d63dc269252` |
| `src/lerobot/processor/factory.py` | `6487d20a83b05021ae251370cb61aa6c7c2b51db2f7ce7a401025168e4c18439` |
| `src/lerobot/datasets/lerobot_dataset.py` | `07523e2a4f9c53b6a96df9255ad131ee30e707fd8610ec9d2178d3741023ae3a` |
| `src/lerobot/datasets/dataset_writer.py` | `319f4efb53e892ceeb439aae6d25209d14564e3dc91134c7cc2c6c0b5e71ebc5` |
| `src/lerobot/utils/feature_utils.py` | `53d503b8f0eda6e40be90e39504c2949f07b526a6e079d74390893be967aef19` |

## Robot boundary

- `robot.py:87-113`: `observation_features` describes values returned by `get_observation`; `action_features` describes values accepted by `send_action`.
- `robot.py:193-205`: `send_action(action)` accepts the flat `RobotAction` matching `action_features` and returns the action actually sent to motors, potentially clipped or modified.
- `packages/lerobot_robot_piperx/src/lerobot_robot_piperx/piperx.py:97-103,224-230`: the selected plugin exposes its scalar/camera observation features and scalar action features without requiring a connection.
- `piperx.py:154-176,261-269`: the plugin converts degree/millimetre values to integer SDK milli-units and returns their round-trip values. This is the command presented to the SDK, not evidence that hardware accepted or executed it.

## One recording iteration

Pinned `lerobot_record.record_loop` performs:

1. `robot.get_observation()` (`lerobot_record.py:289-290`).
2. `robot_observation_processor(obs)` (`292-296`) and builds the observation frame.
3. `teleop.get_action()` (`298-300`).
4. `teleop_action_processor((act, obs))` (`304-306`). Its output is assigned to `action_values`.
5. `robot_action_processor((act_processed_teleop, obs))` (`307`) creates the runtime command.
6. `robot.send_action(robot_action_to_send)` (`328-332`). The return is assigned to `_sent_action` and is not subsequently used for recording.
7. `build_dataset_frame(..., action_values, prefix="action")` (`334-337`).
8. `dataset.add_frame(frame)` (`338`).

Therefore the stored `action` is the `teleop_action_processor` output. It is not necessarily the raw source action, the `robot_action_processor` output, the `send_action` return, or a device-accepted command. Although the persistence call occurs after `send_action`, the label value is fixed before runtime mapping and remains the same-tick training label.

The source comment at `lerobot_record.py:329-331` says the sent action is saved, but the executable statements at `305-338` save `action_values`. D0 follows executable behavior and the causality regression locks it down.

## Processor API

- `pipeline.py:150-234`: a step exposes JSON configuration, optional tensor state, load, reset, and feature transformation. Empty `state_dict()` means stateless.
- `pipeline.py:296-328`: steps execute sequentially in declared list order.
- `pipeline.py:438-564`: serialized JSON records pipeline name and ordered steps, using registry name or fully qualified class plus config and an optional safetensors state file.
- `pipeline.py:619-820`: pipelines load from serialized configuration/state; `from_config` and `from_pretrained` reconstruct the ordered steps.
- `pipeline.py:1604-1608`: pipeline reset calls every step reset.
- `factory.py:46-81`: recording defaults are three `RobotProcessorPipeline` instances, each with one `IdentityProcessorStep`.

D0 selects no stateful processor. Any later source-specific stateful label step must serialize its state and reset at every episode boundary; it cannot silently alter this D0 output contract.

## LeRobotDataset v3

- `pipeline_features.py:26-144` and `utils/feature_utils.py:47-107`: scalar robot features become one float32 `action` vector and one float32 `observation.state` vector, using declaration order as `names`; camera triples become `observation.images.<key>` image/video features.
- `utils/feature_utils.py:110-136`: `build_dataset_frame` packs scalar values by those names and casts numeric vectors to float32.
- `dataset_metadata.py:790-855`: create adds the standard timestamp/frame/episode/index/task-index features and writes v3 metadata.
- `dataset_writer.py:202-269`: callers may not provide timestamp or frame index. `add_frame` assigns `frame_index = episode_buffer.size` and `timestamp = frame_index / fps`.
- `dataset_writer.py:271-306`: `save_episode` assigns the current episode index, global frame indices, task indices, and stacks feature values.
- `dataset_reader.py:312-353`: reads use stored timestamp for video lookup and restore the natural-language `task` string from `task_index`.
- `video_utils.py:56-104,219-224`: RGB video decode produces channel-first float32 tensors in `[0,1]` by default; raw captured frames remain the declared uint8 RGB HWC camera contract.

## Contradiction and minimum resolution

CONTRADICTION: the live unresolved contract used one global phrase, `host monotonic receipt timestamp`, for dataset timing.

UPSTREAM FACT: record-loop pacing uses `time.perf_counter`, while stored dataset timestamps are synthesized as episode-relative `frame_index / fps`.

CURRENT PROJECT ASSUMPTION: the old timing phrase could be read as saying stored dataset timestamps are host monotonic receipt times.

MINIMUM RESOLUTION: D0 separately records the host-monotonic pacing clock and the episode-relative fixed-grid dataset timestamp. No timestamp framework or recorder change is introduced.

## Reuse accounting

UPSTREAM REUSED:

- Robot, processor, recording-loop, feature mapping, LeRobotDataset v3, video, timestamp, and episode implementations.

CONFIGURATION ONLY:

- 30 FPS canonical grid, ordered PIPER-X feature view, wrist-camera roles, identity label processor, policy whitelist, provenance fields, and transform ownership.

THIN VERIFICATION CODE REQUIRED:

- Contract special check and the synthetic same-tick causality regression through the exact pinned identity-processor and `build_dataset_frame` seam used by `record_loop`. Full `LeRobotDataset` construction was not selected because its optional `datasets` extra is absent from the accepted core profile.

NEW RUNTIME IMPLEMENTATION REQUIRED:

- None.
