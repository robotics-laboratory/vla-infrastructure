# BENCHMARK_POLICY.md

## Benchmark ownership

A benchmark upstream owns, as applicable:

```text
task definitions
reset protocol
difficulty split
seed policy
success condition
episode horizon
episode count
metric aggregation
allowed observation/action contract
launcher/runtime requirements
```

The project adapts only the edges needed to connect the policy.

## Official result rule

If a comparability-affecting protocol element changes, label the result `custom benchmark-derived evaluation`, not an official/comparable benchmark score.

## [[gate:B0]] Benchmark integration readiness

Prove a reproducible mechanism for:

```text
official/native benchmark integration
+ minimal processors
+ execution profile
+ result artifact policy
```

This does not claim a selected benchmark run.

## [[gate:B1]] Selected benchmark run

Mandatory only when `requirements.capabilities.selected_benchmark` is true. Pin exact benchmark revision/protocol and retain raw artifacts.
