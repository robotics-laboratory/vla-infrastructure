# Selective manifest operations

The root `MANIFEST.sha256` protects an explicitly reviewed set of repository files.
It is not a complete Git inventory, an artifact registry or gate acceptance evidence
by itself. Registered artifact identities remain governed by `NORMATIVE_MODEL.md`.

## Historical basis

The initial instruction pack (`670be9b`) protected 12 paths. Core setup added four
in `ea927c1`; `8b9af6c` added `.python-version`. The v5.2 migration (`9e94c9b`)
expanded the set to 58, including normative documents, contract/schema/gate rules,
selected source/tests, migration evidence and the immutable v4.3 archive. It did
not protect every tracked path. The root cleanup (`8767dd8`) renamed 17 entries
in place instead of sorting again. Later additions were explicit selections:
`d2780da6` added ten temporal/EVAL paths, `1590fd2e` three hardware paths, and
`43e75947` three recording paths. The contracts tip `0a0ed02` has 74 entries;
the migrated master `682ee93` retains 58. No general rule for automatically
including new tools, tests, configs, images or reports can be recovered.

## Reviewed membership and order

`configs/manifest_paths.txt` is the explicit ordered source of membership.
The reviewed set was explicitly approved on 2026-09-20: the 58 paths of `682ee93`,
then the 16 additional contracts-line selections in their existing order, then
16 current authoritative/integrity paths in the approved order: exactly 90 paths.
The last group protects the selected Kit1103 specs, runtime/preview implementation
and manifest maintenance files. On 2026-09-21 the authoritative current operator
guide `docs/project/RUN_VR_OPERATIONS.md` was explicitly added at the user's
request, bringing the set to 91 paths. No other tracked file is implicitly included.
Add/remove individual paths in this list through review; never derive membership
from globs or `git ls-files`. Comments start with `#`.

`configs/environments/isaac_release_3_0_0.yaml` is protected as historical
provenance, not as an active runtime selection. The approved
`configs/environments/isaac1103/` files describe the active target.

Generation preserves the list order, including historically appended entries.
Output is lowercase SHA256, two spaces, a repository-relative POSIX path and LF.
The manifest never hashes itself. The archived v4.3 manifest is an ordinary selected
file: hash its bytes; do not regenerate it or recursively follow its entries.

Files absent from the list are outside its scope, regardless of whether Git tracks
or ignores them. Neither generation nor verification searches directories.
Adding the tool, its tests or this policy does not implicitly expand membership.

## Explicit implementation safeguards

Historical selected entries are regular files; no symlink or image entry was
observed. Symlink behavior cannot be recovered from that history. The tool therefore
rejects all symlink components (including the list and output), special files,
absolute/traversing paths and known local/cache/runtime directories. These are
fail-closed safeguards, not claims about an undocumented historical generator.
Regular file bytes are hashed without decoding, so a *reviewed* binary/image may
be selected. No images or bulk captures are automatically selected.

## Canonical commands

Run from the repository root with the declared core environment's Python. No
dependency installation is needed; the tool uses only the Python standard library.

```sh
python tools/generate_manifest.py generate
python tools/generate_manifest.py verify
sha256sum -c MANIFEST.sha256
```

`generate` refreshes only reviewed paths and atomically replaces the root manifest
after all reads succeed. `verify` is read-only and checks exact membership, order,
format and file hashes against the reviewed list. `sha256sum -c` is the historical
byte verifier; alone it does not detect omitted required paths or duplicate entries.
Missing files or unsafe paths fail rather than silently shrinking the protected set.
Verification never claims coverage outside the reviewed list. A hash refresh does
not requalify runtime behavior or revise historical evidence identities.
