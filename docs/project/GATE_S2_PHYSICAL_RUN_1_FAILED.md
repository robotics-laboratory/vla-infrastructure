# Gate S2 physical Quest run 1 — FAILED/PARTIAL

Date: 2026-09-08

This is immutable historical evidence for the first physical Meta Quest 3 S2
acceptance attempt. It is not PASS evidence and does not accept Gate S2. No CAN
interface or physical PIPER robot was used.

## Exact pre-remediation state

- Repository HEAD before preservation: `74080487cbf8565617c4bf20a04773ae6d455b97`
- Local checkpoint commit containing the exact tested S2 tree:
  `59fa56b7cd415d13a59f644452ffbfa9d89c556b`
- Tested config at that commit: `configs/isaac_s2_runtime.yaml`
- Tested config SHA-256:
  `06ca4eada4603bb3e3b92a055c23146b6b7b4bf7f9fe02e9a5a9df4035446875`
- Processor revision: `piper_x_isaac_s2_bimanual_relative_v1`
- Translation/rotation gains: `10.0/10.0`
- Gripper mode: binary trigger threshold `0.5`
- XR anchor position: `(0.0, 0.0, 0.0)`
- Runtime command: `OMNI_KIT_ACCEPT_EULA=Y python3 tools/launch_isaac_s2.py`

The pre-remediation worktree was dirty at the original HEAD. Its exact diff is
preserved by the checkpoint commit above (22 paths, 2,320 insertions and 69
deletions). The recorded status was:

```text
M configs/environments/isaac_release_3_0_0.yaml
M configs/gate_rules.yaml
A configs/isaac_s2_runtime.yaml
M configs/resolved_contract.schema.json
M configs/resolved_contract.yaml
M docs/ENVIRONMENT_POLICY.md
M docs/migration/V4_3_TO_V5_2_MIGRATION_MATRIX.md
A docs/project/GATE_S0_TELEOP_DEPENDENCY_AMENDMENT.md
M docs/project/GATE_S0_UPSTREAM_AUDIT.md
A docs/project/GATE_S2_DEPENDENCY_RECHECK.txt
A docs/project/GATE_S2_HUMAN_ACCEPTANCE_TEMPLATE.md
A docs/project/GATE_S2_PROCESSOR_TESTS.txt
A docs/project/GATE_S2_RUNTIME_EVIDENCE.txt
A docs/project/GATE_S2_UPSTREAM_AUDIT.md
A tests/test_isaac_s2_processor.py
M tests/test_resolved_contract.py
A tools/isaac_s2_processor.py
A tools/isaac_s2_runtime.py
A tools/isaac_s2_upstream.py
A tools/launch_isaac_s2.py
M tools/run_isaac_s1.py
M tools/validate_resolved_contract.py
```

The temporary pre-checkpoint patch used for cross-checking had SHA-256
`db2702187cc51e82268c71903d9e262543c4f3d7829309031cc63474c295186f`;
the durable rollback source is Git commit `59fa56b7...`, not that temporary file.

The physical checklist was exercised across three connected launches because
the operator intentionally disconnected/restarted while testing recovery. The
launcher default was 18,000 control steps; the operator stopped each process,
so no run produced a passing `result.json` or clean-shutdown claim.

## Retained raw evidence

| Artifact | SHA-256 |
|---|---|
| `/data/ebulochkin/cache/isaac-s2/runs/20260908T140438Z/stdout.log` | `1b3bbd8627a887b36d65a1f12ac3daf97e84375438c8d792a8bb2fd6e7fe0a93` |
| `/data/ebulochkin/cache/isaac-s2/runs/20260908T141455Z/stdout.log` | `dfe4557f411dc7a49f4b7c9afc23f3cfd16c0afd8325debac57ee29502301948` |
| `/data/ebulochkin/cache/isaac-s2/runs/20260908T142313Z/stdout.log` | `88e680bdd32a5e630d686be416b4212c8dcc3d399ee663ee96fdee486ab3c0fa` |
| `/home/ebulochkin/.cloudxr/logs/cxr_server.2026-09-08T140447Z.log` | `9cb7fc220e3b4cf24fd6bdc52b3b1e0319851bbbd8db6f4d5a059ecf0a13ba81` |
| `/home/ebulochkin/.cloudxr/logs/cxr_server.2026-09-08T141504Z.log` | `281b3e87081967421eae5ed195e86b24b5d8e6bc678d62cb9cf2e98232c7b294` |
| `/home/ebulochkin/.cloudxr/logs/cxr_server.2026-09-08T142321Z.log` | `346e0d9fa4541b0a242fbce29751a0430aa604057edad13ae20f1ec7568f6a7d` |

## Human observations

PASS/PARTIAL:

- physical left drove only the simulated left arm and physical right drove
  only the simulated right arm;
- valid tracking and motion drove upstream differential IK correctly;
- normal clutch/rebase, solo control, simultaneous bimanual control,
  gripper routing, reset, and start-screen controls worked;
- both accepted wrist cameras continued reporting valid frames.

FAIL:

- `10.0/10.0` motion gain was far too high;
- no normal/precise sensitivity selection existed;
- trigger-to-gripper behavior was binary, not analog;
- after tracking loss the affected robot drove/pinned downward; recovery used
  a stale controller reference and required manual clutch/repositioning;
- the XR workspace appeared too low for comfortable use.

## Root-cause finding

The pinned `isaacteleop==1.4.98rc1` `Se3RelRetargeter` resets its baseline and
smoothing for a present controller with `GRIP_IS_VALID=false`, but its absent
OptionalTensorGroup (`inp.is_none`) branch only emits zero. It retains the old
wrist pose and filtered delta. A controller that recovers at a different
physical pose is therefore differenced against stale state, and smoothing
continues emitting the residual. This directly explains the observed drive and
pinning. The remediation must invalidate both the relative pose reference and
smoothing state on every unusable-pose path.

Result: **FAILED/PARTIAL**. Gate S2 remains `unresolved`; a complete second
physical Quest run is required after remediation.
