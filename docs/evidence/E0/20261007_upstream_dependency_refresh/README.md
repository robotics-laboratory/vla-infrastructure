# Upstream checks and core decoder compatibility

This frozen bundle records the separate-branch repairs and candidate checks.
The combined project suite ran on clean
`f764cd8e0ae7b20731d7063f53cfd58576bf3905`, based on trusted
`beaedfd1116577fd4d8026232cfb96cba0b030fa`. The final evidence-registration
change is checked separately; this record does not claim a physical test of a
later commit. Exact commands, source hashes, output hashes and limitations are
in [checks.json](checks.json).

## Results and scope

| Check | Result | Retained output |
|---|---|---|
| Complete core suite in frozen codec candidate | 777 PASS, 28 native tests deselected, 0 skipped; 4 subtests PASS | [raw combined log](project_validation.log) |
| Native unit suite in exact Isaac61 SDK | 28 PASS, 0 skipped | Same combined log |
| Core spec/closure/editable origin/metadata/decoder import | PASS, no conflicts | [core dependencies](core_dependencies.json) |
| Current and legacy SDK identity/metadata | PASS, exact six and eleven retained conflicts | [current](isaac61_dependencies.json), [legacy](legacy_dependencies.json) |
| Native TorchCodec and explicit LeRobotDataset backend | Three-row CPU round-trip PASS | [decoder proof](codec_decode.json), [probe](codec_probe.py) |
| Native SVGA AV1 dataset, explicit TorchCodec backend | All 60 rows and 180 camera frames read; pixels, labels and timestamps equal to PyAV | [AV1 proof](codec_av1_decode.json), [probe](codec_av1_probe.py) |
| First/sibling startup failure injection | 63 recorder tests PASS | [scope/hashes](recording_start_checks.json), [test output](recording_start_tests.txt) |
| Changed Python Ruff, spec references, selective manifest and trusted historical preservation | PASS; 110 reviewed manifest paths, all 481 trusted frozen files preserved | Summary and source identity in checks.json |

The full run retains eight upstream warnings in its raw output. Scoped MyPy
checks introduce no new errors, but four launcher and five materializer baseline
errors remain. This is not a repository-wide clean type-check claim.

## Specification identity and locator preservation

The old artifact `core_uv_lock__other_0a0ed027` changes only its locator from
root `uv.lock` to [baseline_uv.lock](baseline_uv.lock). Its SHA-256 remains
`4e3c9fce53777794b6815eb509b10799da889c986e42e01147f134dd21bc9fb6`.
The paired [baseline_pyproject.toml](baseline_pyproject.toml) is copied exactly
from the trusted base. Historical artifact/evidence identities retain those
bytes and their tested scope.

The selected current lock/spec receive new artifact identities. Package-version
drift is limited to TorchCodec: Linux x86_64 selects 0.5, normalized from the
0.5.0 constraint, against retained Torch 2.7.1. The universal resolver also
selects 0.5 for its macOS arm64 fork; macOS, Windows and Linux ARM were not
qualified. Existing core/SDK installations were not changed in place.
Candidate creation and earlier attempts are in
[codec_provenance.json](codec_provenance.json); the original native decoder
failure is retained in [previous_codec_failure.json](previous_codec_failure.json)
with [its probe](previous_codec_probe.py). Raw outputs keep their original
absolute locators. The checked-in probe copies retain the corresponding bytes
and hashes; no saved command is rewritten to the new locator.

The ABI choice follows the upstream
[TorchCodec/PyTorch compatibility matrix](https://github.com/meta-pytorch/torchcodec#compatibility-with-torch-versions)
and the pinned
[LeRobot 0.6.1 dependency constraints](https://github.com/huggingface/lerobot/blob/v0.6.1/pyproject.toml).
The native test runner reuses stdlib unittest and the project's SDK verifier.
The dependency checker delegates resolution/closure checks to uv. The writer
optimization configures the public
[LeRobot dataset API](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/datasets/lerobot_dataset.py).

## Streaming comparison

The [benchmark record](streaming_benchmark.json) retains the original ABBA,
the excluded overlapping run and the clean post-guard AB comparison. Both modes
use the same AV1 configuration and full QA on 60 synthetic frames, three
960x600 cameras and four CPU cores, in the recorded baseline core environment
with explicit PyAV. The [benchmark script](streaming_benchmark.py),
[staged output](staged_encoding.json), [streaming output](streaming_encoding.json)
and original [staged](staged_encoding.log)/[streaming](streaming_encoding.log)
logs are retained verbatim. Upstream trailing spaces in those two logs are
preserved through narrowly scoped Git attributes.

After the encoded-frame count/time-grid guard, elapsed time was
6.95 versus 5.29 seconds (23.9% lower), while peak RSS was
1847 versus 2428 MiB (31.5% higher). Temporary PNG count changed from 180 to 0.
Disk peaks are sampled lower bounds, including the final output size when needed;
they are not exact peak-storage measurements. First/middle/last decoded frames
in every role matched exactly. The full reader QA covered all 180 camera frames.
The default remains staged encoding; streaming is opt-in.

## Remaining qualification

No Kit session, physical motion, headset test or D1 admission ran here. The exact
SDK metadata exceptions are drift baselines, not vendor ABI qualification.
Physical S2 proof retains its original revision. New Kit startup-failure/moving
parity checks, physical recording-source qualification, D1 admission,
long-episode encoding/resource checks, public upstream replacement hooks and
batch-render content qualification remain separate work in the maintained
[remediation plan](../../../plans/ISAAC_VR_RECORDING_REMEDIATION.md).
Historical authenticity/debt and remote artifact URIs were not independently
resolved. Early cache/sandbox failures are recorded as observed attempts;
where a full raw log was not captured, checks.json reports that observation
without inventing one.
