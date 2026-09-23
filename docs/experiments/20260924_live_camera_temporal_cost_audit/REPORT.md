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
