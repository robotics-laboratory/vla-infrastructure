"""Fail-closed source packet and published-output checks, without a simulator."""

import copy
import json

import pytest

from tools import isaac_vr_live_dataset as live


@pytest.fixture
def packets(tmp_path):
    stream = tmp_path / "stream.h264"
    stream.write_bytes(b"123456")
    rows = [
        dict(
            packet_index=i,
            encoder_packet_timestamp=i,
            submitted_source_tag=i,
            offset=2 * i,
            length=2,
        )
        for i in range(3)
    ]
    return stream, rows


def test_all_source_packets_include_terminal(packets):
    stream, rows = packets
    live.validate_packets(rows, 3, stream)
    with pytest.raises(ValueError, match="terminal"):
        live.validate_packets(rows[:-1], 3, stream)


@pytest.mark.parametrize(
    "field", ["packet_index", "encoder_packet_timestamp", "submitted_source_tag"]
)
def test_stale_or_reordered_packet_identity_rejected(packets, field):
    stream, rows = packets
    rows[1][field] = 0
    with pytest.raises(ValueError, match="ordinals"):
        live.validate_packets(rows, 3, stream)


@pytest.mark.parametrize("corruption", ["hole", "empty", "truncated", "unindexed"])
def test_exact_bitstream_coverage_required(packets, corruption):
    stream, rows = packets
    if corruption == "hole":
        rows[1]["offset"] += 1
    elif corruption == "empty":
        rows[-1]["length"] = 0
    else:
        stream.write_bytes(b"12345" if corruption == "truncated" else b"1234567")
    with pytest.raises(ValueError, match="byte"):
        live.validate_packets(rows, 3, stream)


@pytest.fixture
def published(tmp_path):
    output = tmp_path / "dataset"
    output.mkdir()
    labels = output / "labels.parquet"
    labels.write_bytes(b"bounded immutable label fixture")
    source = tmp_path / "native.hdf5"
    source.write_bytes(b"bounded native source fixture")
    prepared = tmp_path / "prepared.json"
    prepared.write_text("{}")
    receipt = dict(
        schema=live.SCHEMA,
        frames=2,
        dataset_admissible=False,
        source=dict(bound_sources=live.hash_files([source])),
        prepared_sha256=live.hash_files([prepared]),
        files=live.common._dataset_file_digests(output),
    )
    receipt["manifest_sha256"] = live.common._canonical_sha256(receipt)
    path = output / "live-materialization.json"
    path.write_text(json.dumps(receipt))
    return output, labels, source, prepared, path


def test_published_output_remains_experimental(published):
    output, *_ = published
    assert live.verify_manifest(output) == dict(passed=True, frames=2, dataset_admissible=False)


@pytest.mark.parametrize("index", [1, 2, 3])
def test_changed_labels_source_or_prepared_proof_rejected(published, index):
    published[index].write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        live.verify_manifest(published[0])


def test_mutated_manifest_does_not_hide_changed_labels(published):
    output, labels, _, _, path = published
    labels.write_bytes(b"changed labels")
    receipt = copy.deepcopy(json.loads(path.read_text()))
    receipt["files"] = [
        f
        for f in live.common._dataset_file_digests(output)
        if f["path"] != "live-materialization.json"
    ]
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="self-hash"):
        live.verify_manifest(output)
