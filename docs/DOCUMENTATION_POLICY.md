# Documentation policy

## Sources of truth

- [NORMATIVE_MODEL](NORMATIVE_MODEL.md): rules, facts, evidence and conflict behavior.
- [INDEX](INDEX.yaml): per-file classification, lifecycle, ownership and navigation.
- [Resolved contract](../configs/resolved_contract.yaml): selected facts, artifact
  identities, evidence claims and gate bindings/states.
- [Gate rules](../configs/gate_rules.yaml): acceptance requirements and dependencies.
- [MANIFEST_POLICY](MANIFEST_POLICY.md): selective integrity membership and refresh.

## Find the owner before creating a file

Use the [reading map](README.md) and relevant current INDEX owner. Extend an
existing maintained guide or plan when the audience, purpose and lifecycle match.
Create a file for a distinct maintained responsibility, design decision, scoped
experiment, migration, incident or frozen run record. Do not create a report per
small edit, duplicate settings/status tables, or reports summarizing other reports.
An upstream audit may be a section of its task bundle instead of another loose file.

Before creation choose kind, status, stable owner, mutability, destination and any
navigation gate IDs. Owner is a topic/role, never a username, branch or worktree.
INDEX is explicit: every tracked Markdown anywhere and every tracked file under
`docs/`, including non-Markdown bundle members and INDEX itself, needs one entry.
No globs, duplicate keys or automatic registration. Runtime files outside that
scope keep their existing owners; extensions alone do not make them documentation.

## Kinds and destinations for new files

| Kind | Destination | Lifecycle |
|---|---|---|
| normative, policy | `docs/<NAME>.md` | Maintained current rules |
| operations | `docs/operations/` | Maintained operator instructions |
| template | `docs/templates/` | Maintained blank procedures; not evidence |
| design | `docs/design/` | Current proposal or frozen historical decision |
| plan | `docs/plans/` | Maintained scoped work plan |
| evidence | `docs/evidence/<gate>/<bundle>/` | Frozen proof records and small outputs |
| experiment | `docs/experiments/<id>/` | Maintained plan; separate frozen run outputs |
| migration | `docs/migrations/<id>/` | Maintained plan; separate frozen migration records |
| incident | `docs/incidents/<id>/` | Append observations; freeze completed records |
| reference | `docs/reference/` | Maintained reference or historical snapshot |
| generated | `docs/<NAME>.md` | Explicitly generated view; never hand-edit |

`docs/README.md` and `docs/INDEX.yaml` are explicit navigation exceptions.
Do not create directories until a file needs them. New documentation outside these
routes, including loose `docs/project/*.md`, is rejected. Existing paths present
at the audited baseline `98fb74f278e91a7f29a3b00f44a4a2284a053607` are grandfathered
individually from Git inventory. A new INDEX entry does not grant a path exception.
Existing current owners at those paths may still be maintained.

Use stable descriptive maintained filenames without dates. Use `YYYYMMDD_topic`
for bundles and a timestamp/unique suffix for distinct runs; do not use `latest`,
`final2` or chat step numbers as identity. Existing naming is retained.

One run, incident or migration has one bundle, even when it affects several gates.
Link the same artifacts rather than copying outputs between gate directories.
Keep scope, command, exact inputs/source/config identity, environment/profile,
results, limitations and external locators together. Small bundles may use one
README/REPORT; an audit is optional when already covered there. Preserve failures.
An evidence bundle's gate path is navigation, not acceptance.

## Lifecycle, corrections and supersession

`current` means a maintained owner; `historical` means a frozen scoped record and
requires `mutable: false`. A current immutable decision is also permitted.
Historical status does not cancel evidence applicability within its tested scope.
Classification as immutable does not prove authenticity or repair old corruption.
Generated runtime output becomes frozen evidence when retained as a run record;
it is not a regeneratable status view.

Do not edit a historical body because its command, pin, path or status is old.
Changing a command/path inside a saved log changes evidence bytes. A historical
source manifest identifies the tested source and need not match current HEAD.
A historical output manifest must match exactly the output bytes it names.

Corrections and new results use new records with explicit provenance. Preserve
originals and failed attempts. `superseded_by` routes readers to a document; it
does not rewrite old results or transfer gate acceptance. Archive logically first
through classification; moving a frozen file requires a separate preservation and
locator review, not routine tidying. Never work inside an archive or apply its
AGENTS snapshot as current guidance.

Mixed historical-body/current-redirect reports are frozen as a whole. Maintain the
separate current owner selected by INDEX, not the report's historical body.
The old scene specification and XR backlog are historical proposals whose remaining
applicability is tracked in the [governance plan](plans/DOCUMENTATION_GOVERNANCE.md).

## Storage and registration

A Git file is versioned bytes; documentation explains; an artifact identifies a
reproducible input/output; evidence asserts a typed check/observation with scope.
These are distinct roles, not a requirement that every file have all four.

Git holds rules, guides, small reports, configs, provenance, selected test outputs
and bounded representative images. SDKs, environments, datasets, checkpoints,
bulk video/frames/traces and runtime state belong outside Git under `/data`.
Durable proof must have retention separate from disposable caches; preserve
existing locators pending a scoped relocation decision.

- Index every documentation file in coverage, including bundle attachments.
- Register an artifact when its exact identity supports a resolved fact,
  reproducibility requirement or evidence. Record locator, kind and digest there.
- Register evidence when a check/observation supports a gate, resolved decision or
  reopening. Preserve PASS/FAIL, command, tested revision, environment and scope.
- A completed worksheet/test result used as gate proof normally needs file,
  artifact and evidence; the blank template does not. Supporting outputs can share
  an evidence entry. Attach IDs to affected gates when required by their rules.
- Do not rewrite a proof artifact's old identity to describe new bytes. Preserve
  old inputs/results and register a new identity for the new proof. Locator-only
  moves require a recorded mapping and verification of unchanged bytes/references.
- Actual execution, registration of someone else's summary and independent
  verification are different provenance. Do not invent missing raw logs or execution
  timestamps, or qualify a later commit using a previous commit's PASS.

INDEX stores no hashes, pins, gate states, evidence results or duplicated registries.
Its optional `gates` field is navigation scope only. Artifact/evidence associations
are read from the contract. An unreferenced object is not automatically disposable.

## Navigation checks

Use standard relative Markdown links/images to local sources. Under an explicit
heading `Sources of truth`, every documentation target must be current; elsewhere
links to historical evidence are permitted. Authority is never inferred from prose.
Use registered machine-reference tokens for gate/profile/source IDs, including
in nested current guides. Code examples and historical commands are not link targets.

## Integrity and finish checks

Absence from root MANIFEST does not permit evidence mutation. Presence does not
make a maintained guide immutable. Preserve selected membership and order; adding
members requires explicit review. Refresh root hashes only with the canonical
generator after legitimate selected-file edits. Never refresh historical bundle
hashes to conceal transformed evidence. Root manifest, registered artifacts and
historical bundle integrity are separate scopes.

From the existing declared core environment, without installing dependencies:

```sh
python tools/lint_docs.py
python tools/lint_docs.py --base <trusted-commit>
python tools/lint_spec_references.py
python tools/validate_resolved_contract.py configs/resolved_contract.yaml
python -m pytest -q tests/test_docs_governance.py tests/test_validator_baseline.py tests/test_validator_negative.py
python tools/generate_manifest.py generate
python tools/generate_manifest.py verify
git diff --check
```

Generate root MANIFEST only when selected bytes legitimately changed. All linter
commands are read-only. Stage new intended files by exact path before coverage
validation; never use broad staging to hide unrelated WIP. Run relevant topic,
Ruff and type checks as well. Normal offline pytest discovery includes governance
tests; no separate CI platform is required.

The reviewer/checking command supplies `--base`, which must resolve to an ancestor
commit. With a base INDEX, immutable/historical entries and their classifications
are protected using that trusted copy, including against removal from the new
INDEX or changes of status/mutable. Without a base INDEX, the only bootstrap base
is the audited commit above: newly classified existing historical/immutable files
must retain its exact bytes. This initial classification itself requires review;
it cannot recover omitted pre-governance intent. Git history must include the
baseline object for explicit grandfathered-path checking.

Without `--base`, the linter prints historical preservation NOT CHECKED; its exit
zero covers static checks only. A full pre-merge check requires the trusted base.
Preservation is relative to that base, not authentication of historical bundles.
Known debt is reported separately and retained in the governance plan. The linter
does not read `/data`, run hardware, fetch URLs, validate external artifacts,
check link anchors, or infer physical/gate readiness. Contract artifact validation
can require external storage: report performed/unavailable/not checked separately.
