# IMPLEMENTATION_PLAN.md — v5.2

v5.2 is standalone. Migrated evidence satisfies a gate only if it meets v5.2 requirements.

Recommended dependency order:

```text
[[gate:M0]]
 |
 +-> [[gate:E0]]
 +-> [[gate:A]]
 +-> [[gate:B]]
 +-> [[gate:C]]
        |
        v
     [[gate:D0]]
        |
        +--------------------------+
        |                          |
        v                          v
      SIM                        REAL
        |                          |
     [[gate:S0]]                [[gate:R0]]
        |                          |
     [[gate:S1]]                [[gate:R1]]
      /   |   \                    |
     /    |    \                [[gate:R1B]]
[[gate:S2]] [[gate:G1]]             |
   |             |               [[gate:R2]]
[[gate:D1]]      |                  |
   \             /                  |
    [[gate:D2a]]                    |
         |                          |
     [[gate:M1]]                    |
      /       \                     |
[[gate:E1]] [[gate:E2]]             |
      \       /                     |
       [[gate:E3]]                  |
             \                      /
              \                    /
               [[gate:D2b]]
                    |
                 [[gate:DM]]
                    |
                 [[gate:DQ]]
                    |
           [ [[gate:T0]] if required ]
                    |
                 [[gate:HIL]]
                    |
                 [[gate:R3]]
```

Benchmark branch:

```text
[[gate:B0]]
   |
[ [[gate:B1]] if selected benchmark required ]
```

## Per-gate workflow

1. read `NORMATIVE_MODEL.md` and `../configs/gate_rules.yaml`;
2. verify prerequisites;
3. use declared [[profile:offline_tests]] or the gate-specific profile;
4. inspect pinned upstream before code;
5. register evidence/artifacts;
6. update only facts supported by evidence;
7. move gate state only as far as evidence permits;
8. run validator, spec-reference linter and relevant tests;
9. commit gate separately.

## Physical boundary

Codex may prepare commands and analyze logs. It must not infer unobserved physical success. Motion requires explicit human authorization for the exact action.
