# DESIGN_BASIS.md

This file is explanatory, not a runtime pin. Implementation tasks must still inspect and pin exact upstream revisions.

v5.2 hardening is based on verified current behavior:

- LeRobot environment evaluation uses Gym/EnvHub/environment processors rather than requiring a project simulator backend.
- LeRobot recording stores the intended processed action label separately from the return value of `Robot.send_action()`, while the Robot API permits the sent action to differ because of clipping/safety behavior.
- LeRobot processors can transform feature contracts and may have serialized state/reset semantics.
- standard LeRobot dataset merge requires identical features; multi-dataset training support must not be assumed.
- Isaac Lab exposes separate pre-step action/policy-observation and post-step recorder phases, so converter temporal mapping must be explicit.
- Isaac Lab provides native recording/replay and automated generation workflows such as Mimic/SkillGen.
- PIPER-X simulator/driver evidence is not accepted by name alone; executable sign/FK parity is required because model/API/firmware-specific behavior can matter.
- MuJoCo actuator behavior depends on explicit actuator/control/timestep configuration.
- LeRobot eval already provides rollout metrics and explicit policy/environment/episode configuration, so v5.2 adds reproducibility manifests rather than another eval engine.

These facts justify stricter contracts and tests, not new runtime frameworks.

The selected human-VR RECORD path uses Isaac Sim's
`isaacsim.replicator.episode_recorder` extension directly: upstream
`SessionStorage` owns HDF5 persistence and buffering, and public `Recordable`
implementations own native tracks. The project samples immutable pre-action and
successor state, binds the causal transaction and appends only committed rows
through its `ExplicitFrameSampler`. Replay uses upstream `SessionReader` and
`EpisodeReplayer`; the project verifies snapshot/asset/visual identities and
materializes the three canonical camera roles without physics advancement.
Isaac Lab `RecorderManager` and Mimic/SkillGen remain upstream workflow candidates
for generation; they do not own the selected human recorder. The backend and
source-profile selection live in the resolved contract. Physical qualification
and D1 admission require their registered evidence.

See `SOURCE_REFERENCES.md` for the first-party references used during this hardening pass.
