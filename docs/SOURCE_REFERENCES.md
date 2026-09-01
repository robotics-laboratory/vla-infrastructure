# SOURCE_REFERENCES.md

These are non-binding design references checked while hardening v5.2.

They are **not** runtime pins. Every implementation gate still resolves an exact selected version/commit in `resolved_contract.yaml` with evidence.

## LeRobot

- EnvHub / IsaacLab Arena integration: https://github.com/huggingface/lerobot/blob/main/docs/source/envhub_isaaclab_arena.mdx
- Environment rename-map pattern: https://github.com/huggingface/lerobot/blob/main/docs/source/rename_map.mdx
- Recording loop and dataset action path: https://github.com/huggingface/lerobot/blob/main/src/lerobot/scripts/lerobot_record.py
- Robot `send_action()` contract: https://github.com/huggingface/lerobot/blob/main/src/lerobot/robots/robot.py
- Processor pipeline / state / feature transforms: https://github.com/huggingface/lerobot/blob/main/src/lerobot/processor/pipeline.py
- Dataset factory / current multi-dataset training behavior: https://github.com/huggingface/lerobot/blob/main/src/lerobot/datasets/factory.py
- Dataset tools / merge requirements: https://huggingface.co/docs/lerobot/using_dataset_tools
- Dataset v3 design: https://github.com/huggingface/lerobot/blob/main/docs/source/lerobot-dataset-v3.mdx
- Dataset merge/video integrity issue used as QA motivation: https://github.com/huggingface/lerobot/issues/3883
- Evaluation entry point: https://github.com/huggingface/lerobot/blob/main/src/lerobot/scripts/lerobot_eval.py
- Inference / RTC semantics: https://github.com/huggingface/lerobot/blob/main/docs/source/inference.mdx
- Bring-your-own-policy end-to-end compatibility guidance: https://huggingface.co/docs/lerobot/bring_your_own_policies

## NVIDIA Isaac Teleop / Isaac Lab

- TeleopSession lifecycle: https://nvidia.github.io/IsaacTeleop/main/getting_started/teleop_session.html
- Retargeting semantics: https://nvidia.github.io/IsaacTeleop/main/references/retargeting/index.html
- Isaac Lab recorder terms including pre-step/post-step phases: https://isaac-sim.github.io/IsaacLab/develop/_modules/isaaclab/envs/mdp/recorders/recorders.html
- Isaac Lab teleop / imitation workflow: https://isaac-sim.github.io/IsaacLab/develop/source/overview/imitation-learning/teleop_imitation.html
- Isaac Lab SkillGen: https://isaac-sim.github.io/IsaacLab/main/source/overview/imitation-learning/skillgen.html

## AgileX PIPER-X

- piper_sdk: https://github.com/agilexrobotics/piper_sdk
- piper_sdk protocol/interface reference: https://github.com/agilexrobotics/piper_sdk/blob/master/asserts/V2/INTERFACE_V2.MD
- pyAgxArm firmware reference used to motivate firmware+API-specific semantics: https://github.com/agilexrobotics/pyAgxArm/blob/master/docs/piper/firmware_reference.md
- official PIPER Isaac repository: https://github.com/agilexrobotics/piper_isaac_sim
- current simulator issue tracker used to motivate executable sign/FK parity rather than trusting asset names: https://github.com/agilexrobotics/piper_isaac_sim/issues

## MuJoCo

- XML/reference documentation for timestep, actuators, gains/ranges and control parameters: https://mujoco.readthedocs.io/en/stable/XMLreference.html

## JSON Schema

- Object/additional-properties semantics: https://json-schema.org/understanding-json-schema/reference/object
- Conditional/dependency constructs: https://json-schema.org/understanding-json-schema/reference/conditionals

## Rule

If a reference above changes, disappears, or conflicts with the pinned implementation revision, the pinned revision/evidence for the active gate is authoritative for the resolved fact, while v5.2 safety/gate rules still apply. Record any safety- or semantics-relevant upstream change as a reopen reason.
