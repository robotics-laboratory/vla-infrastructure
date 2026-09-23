# Live camera temporal and full cost audit

Investigation in progress. No result or architecture qualification is inferred.

## Implementation discipline

Capability: bounded temporal and cost investigation, no gate promotion.
Pinned owners: SimulationContext/PhysxManager, Camera/IsaacRtxRenderer, Replicator
1.13.36, HydraTexture, Kit 110.3, native Episode Recorder in Sim 6.1.
Remaining gap: isolated scheduling selectors, content classification and cost timers.
Reuse: frozen deferred native-geometry probe and batched Camera adapter, canonical
RECORD HDF and causal transactions. No recorder, renderer or robotics framework.
Environment impact: none. Camera private resource access remains experiment-only.

C1 deliberately retains attached RGB annotators: drawable/AOV generation is part
of render-only cost. C2 adds host-requested Camera extraction; C3 adds owned RGB.
The cost workload uses existing committed injected RECORD controls, which bypass
physical XR input and IK; these stages are UNMEASURED for that workload.
Temporal probes activate the XR experience separately and are diagnostic stimuli.

## Exact current RECORD pipeline

Verified in `tools/run_isaac_s1.py:_advance`, `tools/isaac_s2_runtime.py:run_s2`,
`tools/isaac_vr_recording.py:LiveRecording`, `tools/isaac_vr_runtime.py:VRCameraRig`,
and the pinned sources hashed in [source audit](source_audit.json).

```mermaid
sequenceDiagram
  participant L as S2 control loop (30 Hz logical)
  participant R as Native HDF recorder
  participant P as PhysX (120 Hz)
  participant F as Fabric / robot buffers
  participant K as Kit / Hydra / RTX
  participant C as Camera / annotator
  L->>R: O_t = promoted preceding successor (or sample initial O0)
  L->>L: XR input -> processor -> IK -> preclip A_t -> native apply
  loop Four integrations
    L->>P: write target; step(render = F,F,F,T)
    P->>P: simulate(1/120); fetch_results
    opt Fourth integration only
      P->>F: render -> forward kinematics and Fabric
      F->>K: KitVisualizer app.update (playSimulations disabled)
      K-->>K: Hydra/RTX scheduling and product/AOV work
    end
    L->>F: robot.update; record physics generation
    L->>C: rig.update (RECORD: returns; live: invalidate)
    L->>F: object/contact runtime updates
  end
  L->>C: capture_boundary (RECORD: returns; C2+: extract)
  opt C3 owned live payload
    C->>C: GPU host transfer -> numpy owned RGB copy
  end
  L->>R: capture O_(t+1), native/Fabric snapshot and digest
  L->>L: causal complete -> commit -> construct row
  L->>R: append buffered O_t plus A_t and successor identities
  R->>R: flush each 64 committed rows; promote successor to next O_t
```

Current RECORD intentionally calls neither upstream Camera.update nor annotator
extraction: `disable_live_rgb()` makes rig update/capture no-ops, and setup disables
the three Hydra textures and detaches annotators. C1-C3 restore only the selected
camera work at the existing end-of-four-integrations seam. HDF rows still use
snapshot-backed observations; diagnostic RGB is never silently admitted as D0 proof.

`step(render=True)` completes native simulate/fetch **before** invoking render.
`render()` calls physics pre-render, visualizers (including forward), post-render
hooks, then increments Lab's render generation. Thus T1 is not expected to fix a
render-before-fourth-physics defect: that defect is absent in the inspected source.
It moves the render after the final project buffer refresh, which is still a
falsifiable integration-order difference. KitVisualizer suppresses automatic
physics around app.update. Native callback counts, not only Lab counters, must
establish the no-extra-physics invariant.

| Identity / operation | What it establishes | What it does not establish |
|---|---|---|
| Physics generation | completed requested Lab physics integrations | pixels current |
| Native physics callback | actual PhysX integration callback | camera completion |
| Fabric forward count | calls forwarding native kinematics/transforms | independently observable Fabric state version (UNMEASURED) |
| USD state | authored stage values; pose writes to USD disabled with Fabric | live native pose equality |
| Kit update count | application pumps | RTX completion or headset FPS |
| Hydra render request / drawable | scheduling / observed per-product drawable publication | depicted state identity |
| Lab render generation | completed Python render method | native RTX fence or content state |
| RenderProduct path | resource identity and camera mapping | common source time |
| Camera.frame | buffer extraction/frame bookkeeping | freshness of scene content |
| Camera data generation | SensorBase update and completed extraction bookkeeping | native state represented by pixels |
| Annotator extraction | reader output available to Camera | output belongs to state N |
| Owned RGB | independent CPU bytes (2,764,800/tick) | correct temporal binding |
| Control tick | logical decision attempt | dense HDF row index |
| Dataset observation | immutable source snapshot identity and exact causal linkage | live RGB when only state was recorded |

The injected benchmark reuses native target apply, `_advance(4)`, snapshot capture,
causal commit, append and flush. It bypasses teleop and DifferentialIK. Its absolute
Hz is therefore a bounded no-client RECORD result, not human RECORD or headset Hz.

## Temporal-correctness hypotheses

T0 retains FFFT. T1 defers its one render until after four integrations and buffer
updates. T2 replaces that render with native Replicator held-time capture, preceded
by Fabric forward and guarded against timeline physics. T3 changes only
`/app/asyncRendering=false` before initialization. T4 changes only
`/app/useFabricSceneDelegate=false`; native physics remains unchanged. T5 uses
one upstream Camera over three canonical prims via the existing batch adapter.
T6 is permitted only after individual trials discriminate a useful combination.

Replicator's `_set_capture_settings` changes application async to the Replicator
async setting (false in the XR experience), sync material loads, eco mode and some
viewport settings. These are inherent T2 effects, not a pure synchronization-only
intervention. Readbacks identify them; T3 isolates the app async variable.

The reused oracle drives existing native PhysX cubes through four separated states
while holding the canonical articulation targets, holding a state through all four
integrations. It therefore classifies **control-boundary** N..N-3, not an arbitrary
single-substep delay. Diagnostic kinematic cubes and static witness materials are
not task dynamics qualification. Render-only references advance no physics.
Absolute match error and nearest-reference margin both must pass. Unresolved
samples remain in every denominator. Raw views and reference images are retained;
common producer IDs never upgrade an ambiguous classification.

## Adapter size re-audit

The experiment now includes launch/provenance, import-time selectors, native-cube
reference classification, an active-XR native RECORD entry, and offline summaries.
These are bounded diagnostic seams; the existing scene builder, camera renderer,
causal validator, HDF writer and historical native witness assay remain owners.
The corrected oracle deliberately holds wrist/gripper targets fixed because the
old large joint teleports changed the post-physics geometry unpredictably. Moving
wrist/gripper temporal qualification is consequently a separate remaining scope.
The four-state primary classifier is accompanied by optional declared sentinel
holds to detect aliases of the four-state period; repeated-state ambiguity fails
closed and is retained. No production source or dependency is changed.
