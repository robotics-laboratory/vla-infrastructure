# MIGRATION_V4_3_V5_1_TO_V5_2.md

## v5.2 is standalone

Old packs are not required to understand v5.2. Existing projects may import old accepted evidence.

## Migration states

```text
not_required
in_progress
complete
```

Fresh projects use `mode: fresh`, `state: not_required`.

Migrated projects use `from_v4_3` or `from_v5_1`.

## Required inventory

Before migration is complete:

1. register old contract as artifact;
2. inventory old evidence IDs by domain;
3. preserve or explicitly invalidate every inventoried evidence item;
4. normalize legacy source aliases;
5. map old environment/profile facts to structured v5.2 records;
6. rerun v5.2 validator.

The validator rejects silently dropped inventoried evidence.

## Legitimate reopen reasons

```text
contradiction
invalidated_evidence
unsupported_dependency
upstream_bug
safety_change
hardware_change
environment_breakage
other
```

## Do not reset known facts

Migration is additive. Do not replace a supported resolved value with `null` unless evidence was invalidated or the field is deliberately reopened.

## Legacy source aliases

Aliases such as `real:vr_teleop`, `isaac:vr_teleop`, `isaac:generated` may appear only in migration inventory. After migration, canonical source records use `runtime` and `source_class` separately.
