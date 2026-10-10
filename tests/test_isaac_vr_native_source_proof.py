"""CPU checks for result-driven source selection and geometry rejection."""
from collections import OrderedDict
import importlib.util
import io
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from isaac_vr_native_source_proof import (
    NativeSourceProof, OpticalPublication, compare_geometry, decode_stamp, semantic_matrix, stamp_matrix,
    prepare_source_proof_stage, publication_log,
)

STAMP, BODY, CAMERA = "/Stamp", "/Robot/link", "/Robot/link/Camera"


def sample(publication_id=7):
    body = np.eye(4)
    body[3, :3] = [0.4, 0.2, 1.1]
    camera = body.copy()
    camera[3, :3] += [0.1, 0.05, -0.2]
    source = dict(publication_id=publication_id, physics_step=publication_id * 4,
                  reset_epoch=2, body_matrices={BODY: body}, camera_matrices={CAMERA: camera})
    result = dict(role="left_wrist", frame_identifier={"frameNumber": 901}, result_geometry=dict(
        semantic_token_rows=((STAMP, "native_source_proof"), (BODY, "robot")),
        semantic_world_matrices=np.array([stamp_matrix(publication_id), body], dtype=np.float32),
        camera_view=np.linalg.inv(camera)))
    return source, result


def test_stamp_float32_roundtrip_and_reject_interpolated_stamp():
    for publication_id in [1, 7, 255, 4095, 65535]:
        assert decode_stamp(stamp_matrix(publication_id).astype(np.float32)) == publication_id
    matrix = stamp_matrix(7)
    matrix[0, 0] += 0.5 / 65536
    with pytest.raises(ValueError, match="Nonintegral"):
        decode_stamp(matrix)


def test_exact_path_lookup_does_not_assume_semantic_row_order():
    source, result = sample()
    assert np.allclose(semantic_matrix(result, BODY), source["body_matrices"][BODY])
    result["result_geometry"]["semantic_token_rows"] = ((BODY,), (BODY,))
    with pytest.raises(ValueError, match="Expected one"):
        semantic_matrix(result, BODY)


def test_body_mismatch_rejected_even_with_matching_stamp_and_camera():
    source, result = sample()
    assert compare_geometry(result, source, STAMP, CAMERA, 5e-5)["geometry_matched"]
    result["result_geometry"]["semantic_world_matrices"][1, 3, 0] += 0.003
    row = compare_geometry(result, source, STAMP, CAMERA, 5e-5)
    assert not row["geometry_matched"]
    assert BODY in row["failed_paths"]


def test_missing_body_and_wrong_camera_cannot_pass():
    source, result = sample()
    result["result_geometry"]["semantic_token_rows"] = ((STAMP,), ("/WrongBody",))
    result["result_geometry"]["camera_view"][3, 0] += 0.01
    row = compare_geometry(result, source, STAMP, CAMERA, 5e-5)
    assert not row["geometry_matched"]
    assert len(row["failed_paths"]) == 2


def proof_for_test():
    proof = NativeSourceProof.__new__(NativeSourceProof)
    proof.thread, proof.closed, proof.error = threading.get_ident(), False, None
    proof.camera_paths, proof.stamp_path = {"left_wrist": CAMERA}, STAMP
    proof.tolerance, proof.history = 5e-5, OrderedDict()
    proof.optical = None
    proof.geometry_samples = 0
    proof.compact_logging = False
    proof.batch_reads = False
    proof.skip_redundant_sync = False
    proof.clock_only = False
    proof.proof_scope = "full_native_body_camera"
    proof.attribute_probe = proof.attribute_tag_owned = proof.attribute_only = proof.identity_only = False
    proof._check_native_view = lambda phase: None
    proof.stream = io.StringIO()
    proof.counts = dict(matched=0, mismatched=0, unresolved=0)
    proof.counts.update(attribute_clock_matched=0, attribute_clock_failed=0)
    return proof


def test_observe_selects_rendered_publication_not_latest_or_counter_offset():
    proof = proof_for_test()
    source, result = sample(7)
    latest, _ = sample(13)
    proof.history[7] = dict(source=source, observed_roles=set())
    proof.history[13] = dict(source=latest, observed_roles=set())
    row = proof.observe(result)
    assert row["geometry_matched"] and row["physics_step"] == 28
    assert row["publication_id"] == 7
    assert proof.history[7]["observed_roles"] == {"left_wrist"}
    assert not proof.history[13]["observed_roles"]
    assert row["dataset_admissible"] is False
    assert row["optical_alignment_proven"] is False
    rows = [json.loads(line) for line in proof.stream.getvalue().splitlines()]
    assert rows[-1]["publication_id"] == 7
    assert rows[0]["kind"] == "result_geometry_sample"
    assert rows[0]["result_geometry"]["semantic_token_rows"][0][0] == STAMP


def test_evicted_or_unknown_source_is_unresolved_without_fallback():
    proof = proof_for_test()
    _, result = sample(7)
    row = proof.observe(result)
    assert not row["geometry_matched"]
    assert "not in retained" in row["unresolved"]


@pytest.mark.parametrize("form", ["class", "inherited", "instance", "observer"])
@pytest.mark.parametrize("skip_sync", [False, True])
def test_hook_preserves_existing_forward_and_observes_after_publication(form, skip_sync, tmp_path):
    calls = []

    class Manager:
        @classmethod
        def forward(cls):
            calls.append("native_forward")

    proof = proof_for_test()
    proof.skip_redundant_sync = skip_sync
    if form == "inherited":
        class Child(Manager):
            pass
        manager = Child
    elif form == "instance":
        manager = Manager()
    elif form == "observer":
        manager = Manager
        manager.forward = lambda: calls.append("native_forward")
    else:
        manager = Manager
    proof.manager = manager
    proof.env = SimpleNamespace(sim=SimpleNamespace(get_physics_step_count=lambda: 44))
    proof.rt = SimpleNamespace(SynchronizeToFabric=lambda: calls.append("population_sync"))
    proof._publish = lambda step: calls.append(("source", step))
    owned, original = "forward" in vars(manager), vars(manager).get("forward")
    proof.layer, proof.output = None, tmp_path
    proof._install()
    try:
        manager.forward()
        assert calls == ([] if skip_sync else ["population_sync"]) + ["native_forward", ("source", 44)]
        assert proof.previous_forward is original
    finally:
        proof.close()
    assert ("forward" in vars(manager)) == owned
    assert vars(manager).get("forward") is original
    manager.forward()
    assert calls[-1] == "native_forward"


def test_explicit_initial_population_sync_is_not_disabled_by_opt_in():
    calls = []
    proof = proof_for_test()
    proof.skip_redundant_sync = True
    proof.rt = SimpleNamespace(SynchronizeToFabric=lambda: calls.append("population_sync"))
    proof._sync_to_fabric()
    assert calls == ["population_sync"]


def test_hook_latches_source_boundary_change(tmp_path):
    class Manager:
        @classmethod
        def forward(cls):
            pass

    proof = proof_for_test()
    proof.output = tmp_path
    proof.manager = Manager
    steps = iter([44, 45])
    proof.env = SimpleNamespace(sim=SimpleNamespace(get_physics_step_count=lambda: next(steps)))
    proof.rt = SimpleNamespace(SynchronizeToFabric=lambda: None)
    proof._publish = lambda step: None
    original = vars(Manager)["forward"]
    proof._install()
    try:
        with pytest.raises(RuntimeError, match="Source boundary changed"):
            Manager.forward()
        with pytest.raises(RuntimeError, match="source proof failed"):
            proof.raise_if_failed()
    finally:
        Manager.forward = original


def test_manager_without_namespace_emits_diagnostic_before_fail_closed(tmp_path):
    class Manager:
        __slots__ = ()

        def forward(self):
            raise AssertionError("Inspection must not publish")

    proof = proof_for_test()
    proof.output, proof.manager = tmp_path, Manager()
    proof.env = SimpleNamespace(sim=SimpleNamespace())
    with pytest.raises(TypeError, match="manager-type.json"):
        proof._install()
    row = json.loads((tmp_path / "manager-type.json").read_text())
    assert "namespace_unavailable" in row
    assert row["manager_is_class"] is False
    assert row["forward"]["qualname"].endswith("Manager.forward")


def test_resolvable_string_resolves_public_class_and_restores_descriptor(tmp_path, monkeypatch):
    calls = []

    class Manager:
        @classmethod
        def forward(cls):
            calls.append("native")

    class ResolvableString(str):
        __slots__ = ()

        def __getattr__(self, name):
            return getattr(Manager, name)

    def resolve(reference):
        assert reference == "test.physics:Manager" and type(reference) is str
        return Manager

    monkeypatch.setitem(sys.modules, "isaaclab.utils.string", SimpleNamespace(string_to_callable=resolve))
    proxy = ResolvableString("test.physics:Manager")
    proof = proof_for_test()
    proof.manager, proof.output, proof.layer = proxy, tmp_path, None
    proof.env = SimpleNamespace(sim=SimpleNamespace(get_physics_step_count=lambda: 12))
    proof.rt = SimpleNamespace(SynchronizeToFabric=lambda: None)
    proof._publish = lambda step: calls.append(step)
    original = vars(Manager)["forward"]
    proof._install()
    try:
        proxy.forward()
        assert calls == ["native", 12] and proof.manager is Manager
    finally:
        proof.close()
    assert vars(Manager)["forward"] is original
    proxy.forward()
    assert calls[-1] == "native"


def test_preparation_rejects_live_physics_before_loading_usd():
    sim = SimpleNamespace(physics_sim_view=SimpleNamespace(is_valid=True))
    with pytest.raises(RuntimeError, match="no existing physics view"):
        prepare_source_proof_stage(sim)


@pytest.mark.parametrize("replaced", [False, True])
def test_publication_rejects_invalid_or_replaced_original_physics_view(replaced):
    proof = proof_for_test()
    proof.physics_view = SimpleNamespace(is_valid=replaced)
    current = SimpleNamespace(is_valid=True) if replaced else proof.physics_view
    proof.env = SimpleNamespace(sim=SimpleNamespace(physics_sim_view=current))
    with pytest.raises(RuntimeError, match="after_native_forward"):
        NativeSourceProof._check_native_view(proof, "after_native_forward")
    assert json.loads(proof.stream.getvalue())["phase"] == "after_native_forward"


spec = importlib.util.spec_from_file_location('mesh_decode_test', Path(__file__).resolve().parents[1] / 'docs/experiments/20261009_live_camera_recording_30hz/temporal_physics/mesh_freshness.py')
marker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(marker)
ROLES = ('left_wrist', 'right_wrist', 'scene')


def optical_image(publication, role, ghost=False):
    pixels = np.full((600, 960, 4), 30, dtype=np.uint8)
    pixels[..., 3] = 255
    bits = [(publication >> bit) & 1 for bit in range(12)] + [role & 1, (role >> 1) & 1, 1, 0]
    for cell, bit in enumerate(bits):
        x, y = 300 + 24 * cell, 512 if bit else 552
        pixels[y-6:y+6, x-6:x+6, :3] = 230
    x, y = marker.position(publication), marker.Y
    pixels[y-10:y+10, x-10:x+10, :3] = 230
    if ghost:
        old_x = 180 if x == 100 else 100
        pixels[y-10:y+10, old_x-10:old_x+10, :3] = 150
    return pixels


def observer():
    proof = OpticalPublication.__new__(OpticalPublication)
    proof.roles, proof.marker, proof.previous_decoded = ROLES, marker, {}
    return proof


def optical_result(publication, role, **kw):
    return dict(role=ROLES[role], rgba=SimpleNamespace(numpy=lambda: optical_image(publication, role, **kw)))


@pytest.mark.parametrize('role', range(3))
def test_all_roles_are_independently_decoded(role):
    row = observer().observe(optical_result(17, role), dict(publication_id=17, geometry_matched=True))
    assert row['decoded_source'] == 17 and row['decoded_role'] == role
    assert row['optical_and_geometry_matched'] and not row['dataset_admissible']


def test_pixels_disagree_with_semantic_stamp():
    row = observer().observe(optical_result(18, 0), dict(publication_id=17, geometry_matched=True))
    assert row['decoded_source'] == 18
    assert not row['optical_and_geometry_matched']


def test_wrong_role_and_missing_initial_source_are_failures():
    frame = optical_result(17, 1)
    frame['role'] = 'left_wrist'
    assert not observer().observe(frame, dict(publication_id=17, geometry_matched=True))['optical_and_geometry_matched']
    assert not observer().observe(optical_result(0, 0), dict(geometry_matched=False))['optical_and_geometry_matched']


def test_previous_image_ghost_and_body_mismatch_rejected():
    proof = observer()
    proof.observe(optical_result(17, 0), dict(publication_id=17, geometry_matched=True))
    row = proof.observe(optical_result(18, 0, ghost=True), dict(publication_id=18, geometry_matched=True))
    assert row['changed_position'] and row['previous_roi_normalized'] > .08
    assert not row['optical_and_geometry_matched']
    assert not proof.observe(optical_result(19, 0), dict(publication_id=19, geometry_matched=False))['optical_and_geometry_matched']


def test_compact_publication_preserves_source_and_hashes_native_state_and_cameras():
    from copy import deepcopy
    source, _ = sample()
    source.update(published_ns=123, native_body_pose_xyzw=np.zeros((27, 7)),
                  q=np.zeros((2, 9)), dq=np.zeros((2, 9)))
    before = deepcopy(source)
    full, compact = publication_log(source), publication_log(source, True)
    assert full["body_matrices"] is source["body_matrices"]
    assert not {"body_matrices", "camera_matrices", "q", "dq", "native_body_pose_xyzw"} & compact.keys()
    assert compact["physics_step"] == source["physics_step"]
    assert compact["source_state_sha256"] == publication_log(before, True)["source_state_sha256"]
    for key in ("q", "dq", "native_body_pose_xyzw"):
        changed = deepcopy(before)
        changed[key].flat[0] += 1
        assert publication_log(changed, True)["source_state_sha256"] != compact["source_state_sha256"]
        assert np.array_equal(source[key], before[key])
    changed = deepcopy(before)
    changed["camera_matrices"][CAMERA][3, 0] += .01
    assert publication_log(changed, True)["source_state_sha256"] != compact["source_state_sha256"]


def test_compact_logging_only_reduces_geometry_samples_not_body_camera_validation():
    from copy import deepcopy
    source, result = sample(7)
    full, compact = proof_for_test(), proof_for_test()
    compact.compact_logging = True
    for proof in (full, compact):
        proof.history[7] = dict(source=deepcopy(source), observed_roles=set())
    for index in range(6):
        changed = deepcopy(result)
        if index == 4:
            changed["result_geometry"]["semantic_world_matrices"][1, 3, 0] += .01
        if index == 5:
            changed["result_geometry"]["camera_view"][3, 0] += .01
        a, b = full.observe(changed), compact.observe(changed)
        assert a == b
        assert a["geometry_matched"] == (index < 4)
    assert full.counts == compact.counts
    assert full.geometry_samples == 6 and compact.geometry_samples == 3
    assert len(compact.history[7]["source"]["body_matrices"]) == 1


def test_batch_preserves_bits_shapes_and_ownership_with_one_host_conversion(monkeypatch):
    import torch
    from isaac_vr_native_source_proof import _host, _host_batch
    tensors = [torch.arange(84, dtype=torch.float32).reshape(1, 12, 7),
               torch.arange(84, dtype=torch.float32).reshape(1, 7, 12).transpose(1, 2),
               *(torch.arange(7, dtype=torch.float32).reshape(1, 7) for _ in range(3)),
               *(torch.arange(9, dtype=torch.float32).reshape(1, 9) for _ in range(4))]
    tensors[0].reshape(-1)[:4] = torch.tensor([0., -0., float("inf"), float("nan")])
    expected = [_host(t) for t in tensors]
    calls, original = [], torch.Tensor.cpu

    def cpu(tensor, *args, **kwargs):
        calls.append(tensor.numel())
        return original(tensor, *args, **kwargs)

    monkeypatch.setattr(torch.Tensor, "cpu", cpu)
    actual = _host_batch([SimpleNamespace(torch=tensors[0]), *tensors[1:]])
    assert calls == [sum(t.numel() for t in tensors)]
    for source, wanted, got in zip(tensors, expected, actual, strict=True):
        assert got.shape == wanted.shape and got.dtype == wanted.dtype
        assert got.tobytes() == wanted.tobytes()
        source.fill_(99)
        assert got.tobytes() == wanted.tobytes()


def test_batch_dlpack_native_cpu_arrays_and_hash_equal_individual_reads():
    from isaac_vr_native_source_proof import _host, _host_batch
    values = [np.arange(189, dtype=np.float32).reshape(27, 7),
              np.arange(18, dtype=np.float32).reshape(2, 1, 9),
              np.arange(18, dtype=np.float32).reshape(2, 1, 9) / 10]
    individual, batched = [_host(v) for v in values], _host_batch(values)
    hashes = []
    for poses, q, dq in (individual, batched):
        source, _ = sample()
        source.update(published_ns=123, native_body_pose_xyzw=poses, q=list(q), dq=list(dq))
        hashes.append(publication_log(source, True)["source_state_sha256"])
    assert hashes[0] == hashes[1]


def test_batch_rejects_unsupported_values_dtype_and_device_before_packing():
    import torch
    from isaac_vr_native_source_proof import _host_batch
    with pytest.raises(ValueError, match="at least one"):
        _host_batch([])
    with pytest.raises(TypeError, match="Torch or DLPack"):
        _host_batch([object()])
    for wrong in (torch.ones(7, dtype=torch.float64), torch.ones(7, device="meta")):
        with pytest.raises(ValueError, match="homogeneous float32"):
            _host_batch([torch.ones(7, dtype=torch.float32), wrong])


@pytest.mark.parametrize("damage", [None, "stamp", "camera", "scope"])
def test_clock_scope_checks_actual_stamp_and_camera_without_body_claim(damage):
    source, result = sample()
    source.update(proof_scope="publication_clock_camera", body_matrices={})
    result["result_geometry"]["semantic_token_rows"] = ((STAMP,),)
    result["result_geometry"]["semantic_world_matrices"] = np.array([stamp_matrix(7)], dtype=np.float32)
    if damage == "stamp":
        result["result_geometry"]["semantic_world_matrices"][0, 3, 0] += .01
    elif damage == "camera":
        result["result_geometry"]["camera_view"][3, 0] += .01
    proof = proof_for_test()
    proof.clock_only = True
    proof.proof_scope = "publication_clock_camera"
    if damage == "scope":
        source["proof_scope"] = "full_native_body_camera"
    proof.history[7] = dict(source=source, observed_roles=set())
    row = proof.observe(result)
    assert row["geometry_matched"] == (damage is None)
    assert row["proof_scope"] == "publication_clock_camera"
    assert row["body_geometry_checked"] is False
    assert row.get("compared_bodies", 0) == 0
    assert row["dataset_admissible"] is False


def test_scope_cannot_silently_omit_full_body_inventory():
    source, result = sample()
    source["body_matrices"] = {}
    with pytest.raises(ValueError, match="inventory disagrees"):
        compare_geometry(result, source, STAMP, CAMERA, 5e-5)
    source["proof_scope"] = "unknown"
    with pytest.raises(ValueError, match="Unknown"):
        compare_geometry(result, source, STAMP, CAMERA, 5e-5)


@pytest.mark.parametrize("clock_only", [False, True])
@pytest.mark.parametrize("attribute_only", [False, True])
def test_stage_preparation_clock_only_never_labels_physical_bodies(clock_only, attribute_only, monkeypatch):
    from contextlib import nullcontext
    labels, session = [], SimpleNamespace(subLayerPaths=[])
    bodies = [SimpleNamespace(GetPath=lambda p=p: p, HasAPI=lambda api: True) for p in ("/Left", "/Right")]
    layer = SimpleNamespace(identifier="proof-layer")
    stage = SimpleNamespace(Traverse=lambda: bodies, GetSessionLayer=lambda: session,
                            GetPrimAtPath=lambda path: False if path.endswith("Stamp") else path)
    authored = []
    cube = SimpleNamespace(CreateSizeAttr=lambda value: None,
                           AddTransformOp=lambda: SimpleNamespace(Set=lambda matrix: None),
                           GetPrim=lambda: SimpleNamespace(CreateAttribute=lambda name, dtype, custom:
                               SimpleNamespace(Set=lambda value: authored.append((name, dtype, value)))))
    monkeypatch.setitem(sys.modules, "pxr", SimpleNamespace(
        Gf=SimpleNamespace(Matrix4d=lambda value: value),
        Sdf=SimpleNamespace(Layer=SimpleNamespace(CreateAnonymous=lambda name: layer),
                            ValueTypeNames=SimpleNamespace(Int="Int")),
        Usd=SimpleNamespace(EditContext=lambda *args: nullcontext()),
        UsdGeom=SimpleNamespace(Cube=SimpleNamespace(Define=lambda *args: cube)),
        UsdPhysics=SimpleNamespace(RigidBodyAPI=object())))
    monkeypatch.setitem(sys.modules, "isaacsim.core.experimental.utils.semantics",
                        SimpleNamespace(add_labels=lambda prim, **kwargs: labels.append(prim)))
    prepare_source_proof_stage(SimpleNamespace(physics_sim_view=None, stage=stage),
                               clock_only=clock_only, attribute_only=attribute_only)
    assert labels == ([] if attribute_only else [False] if clock_only else ["/Left", "/Right", False])
    assert layer.customLayerData["clock_only"] == (clock_only or attribute_only)
    assert layer.customLayerData["attribute_only"] == attribute_only
    assert authored == ([("vla:publicationId", "Int", 0)] if attribute_only else [])


def test_clock_publication_reads_only_robot_poses_and_checks_all_three_camera_mounts(monkeypatch):
    poses = np.zeros((24, 7), dtype=np.float32)
    poses[:, 0], poses[:, 6] = np.arange(24) / 32, 1
    local = np.eye(4)
    local[3, :3] = [.125, .25, .5]
    monkeypatch.setitem(sys.modules, "usdrt", SimpleNamespace(
        Gf=SimpleNamespace(Matrix4d=lambda *x: np.asarray(x).reshape(4, 4)), Sdf=SimpleNamespace(Path=str)))
    monkeypatch.setitem(sys.modules, "pxr", SimpleNamespace(UsdGeom=SimpleNamespace(XformCache=lambda:
        SimpleNamespace(ComputeRelativeTransform=lambda *args: (local.copy(), False),
                        GetLocalToWorldTransform=lambda prim: local.copy()))))
    calls = []

    def forbidden():
        raise AssertionError("Clock-only must not read q/dq or prop poses")

    def links(index):
        calls.append(index)
        return poses[index*12:(index+1)*12].reshape(1, 12, 7)

    proof = proof_for_test()
    proof.clock_only, proof.proof_scope = True, "publication_clock_camera"
    proof.counts["publications"], proof.capacity = 0, 256
    proof.hierarchy = SimpleNamespace(set_world_xform=lambda *args: None, update_world_xforms=lambda: None)
    proof.views = [SimpleNamespace(get_link_transforms=lambda i=i: links(i),
                                  get_dof_positions=forbidden, get_dof_velocities=forbidden) for i in range(2)]
    proof.props = [SimpleNamespace(root_view=SimpleNamespace(get_transforms=forbidden)) for _ in range(3)]
    proof.robot_body_paths = [f"/body{i}" for i in range(24)]
    proof.body_paths = [*proof.robot_body_paths, "/prop0", "/prop1", "/prop2"]
    proof.render_body_paths = proof.body_paths[:25]
    proof.stage = SimpleNamespace(GetPrimAtPath=lambda path: path)
    proof.camera_mounts = {"/left": ("/body0", local.copy()), "/right": ("/body12", local.copy()),
                           "/scene": (None, local.copy())}
    proof.env = SimpleNamespace(camera=SimpleNamespace(reset_epoch=2))
    proof._publish(28)
    source = proof.history[1]["source"]
    assert calls == [0, 1]
    assert source["native_body_pose_xyzw"].tobytes() == poses.tobytes()
    assert source["body_matrices"] == {} and "q" not in source and "dq" not in source
    assert source["proof_scope"] == "publication_clock_camera" and not source["body_geometry_checked"]
    assert source["physics_step"] == 28 and source["reset_epoch"] == 2
    assert set(source["camera_matrices"]) == {"/left", "/right", "/scene"}
    assert np.array_equal(source["camera_matrices"]["/scene"], local)
    assert source["camera_matrices"]["/right"][3, 0] == local[3, 0] + poses[12, 0]
    assert publication_log(source, True)["source_state_hash_schema"] == "named_native_pose_camera_arrays_v1"
    local[3, 0] += .01
    with pytest.raises(RuntimeError, match="camera mount changed"):
        proof._publish(32)
    assert len(proof.history) == 1


@pytest.mark.parametrize("attribute_id", [7, 8, 0, None, True])
def test_native_attribute_probe_must_match_independent_semantic_publication(attribute_id):
    proof = proof_for_test()
    proof.attribute_probe = True
    source, result = sample(7)
    result["attribute_publication_id"] = attribute_id
    proof.history[7] = dict(source=source, observed_roles=set())
    row = proof.observe(result)
    assert row["attribute_clock_matched"] == (attribute_id == 7)
    assert row["geometry_matched"] == (attribute_id == 7)
    assert row["body_geometry_checked"] is True
    assert proof.counts["attribute_clock_matched"] == (attribute_id == 7)
    assert proof.counts["attribute_clock_failed"] == (attribute_id != 7)
    assert not row["dataset_admissible"]


def test_attribute_decoder_rejects_uninitialized_wrong_type_and_shape():
    path = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/native_live/render_callback.py"
    spec = importlib.util.spec_from_file_location("native_attribute_decode_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = dict(attributeData=np.array([7], dtype=np.int32).view(np.uint8), attributeDataType="int32",
                attributeBufferSize=4, attributeWidth=1, attributeHeight=1)
    assert module.decode_attribute_publication(data) == 7
    for changes in [dict(attributeDataType="float32"), dict(attributeBufferSize=8),
                    dict(attributeWidth=2), dict(attributeData=np.array([0], dtype=np.int32).view(np.uint8))]:
        with pytest.raises(ValueError):
            module.decode_attribute_publication({**data, **changes})


def test_attribute_probe_retains_empty_layout_diagnostic_before_rejection():
    path = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/native_live/render_callback.py"
    spec = importlib.util.spec_from_file_location("native_attribute_empty_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    probe = module.NativeResultConsumer.__new__(module.NativeResultConsumer)
    probe.attribute_probe_diagnostics = []
    probe._attribute_probe_stream = io.StringIO()
    probe._attribute_templates = ("ProbePR", "ProbePP")
    probe.sd = SimpleNamespace(get_node_attributes=lambda name, ports, path: {"inputs:attribute": "vla:publicationId"})
    attrs = {"attributeData": SimpleNamespace(get_upstream_connections=lambda: [])}
    empty = dict(attributeData=np.array([], dtype=np.uint8), attributeDataType="uint8",
                 attributeBufferSize=0, attributeWidth=0, attributeHeight=0,
                 renderResults=123, renderProductPath="/Render/Product")
    for index in range(20):
        probe._record_attribute_diagnostic(empty, "left_wrist", {"frameNumber": index}, attrs)
        with pytest.raises(ValueError):
            module.decode_attribute_publication(empty)
    rows = [json.loads(line) for line in probe._attribute_probe_stream.getvalue().splitlines()]
    assert len(rows) == 16 and rows[0]["frame_identifier"]["frameNumber"] == 0
    assert rows[0]["consumer"]["attributeData"] == []
    assert rows[0]["consumer"]["attributeDataType"] == "uint8"
    assert set(rows[0]["native_nodes"]) == {"ProbePR", "ProbePP"}


@pytest.mark.parametrize("alteration", [None, "camera", "unknown_id", "boolean_id", "mixed_scope"])
def test_attribute_only_source_selection_needs_exact_history_and_native_camera(alteration):
    proof = proof_for_test()
    proof.attribute_only = proof.attribute_probe = proof.clock_only = True
    proof.proof_scope = "publication_attribute_camera"
    source, result = sample(7)
    source.update(proof_scope=proof.proof_scope, body_matrices={})
    # No semantic table is available in this mode; no implicit fallback may use it.
    result["result_geometry"] = {"camera_view": result["result_geometry"]["camera_view"]}
    result["attribute_publication_id"] = 7
    proof.history[7] = dict(source=source, observed_roles=set())
    if alteration == "camera":
        result["result_geometry"]["camera_view"][3, 0] += .01
    elif alteration == "unknown_id":
        result["attribute_publication_id"] = 8
    elif alteration == "boolean_id":
        result["attribute_publication_id"] = True
    elif alteration == "mixed_scope":
        source["proof_scope"] = "publication_clock_camera"
    row = proof.observe(result)
    assert row["geometry_matched"] == (alteration is None)
    assert not row["body_geometry_checked"] and not row["dataset_admissible"]
    if alteration is None:
        assert row["physics_step"] == 28 and row["publication_id"] == 7
        assert row["attribute_clock_matched"] and row["compared_bodies"] == 0
        assert row["attribute_clock_reference"] == "retained_publication_history"
        assert publication_log({**source, "published_ns": 1}, True)["source_state_hash_schema"] == "named_native_pose_camera_arrays_v1"


def test_attribute_only_comparison_rejects_different_attribute_and_full_inventory():
    source, result = sample(7)
    source.update(proof_scope="publication_attribute_camera", body_matrices={})
    result["attribute_publication_id"] = 8
    assert not compare_geometry(result, source, STAMP, CAMERA, 5e-5)["geometry_matched"]
    source["body_matrices"] = {BODY: np.eye(4)}
    with pytest.raises(ValueError, match="inventory"):
        compare_geometry(result, source, STAMP, CAMERA, 5e-5)


@pytest.mark.parametrize("identity_only", [False, True])
def test_attribute_only_callback_graph_has_camera_and_no_semantic_exporter(monkeypatch, identity_only):
    path = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/native_live/render_callback.py"
    spec = importlib.util.spec_from_file_location("native_attribute_graph_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registered, checked = {}, []

    class SD:
        @staticmethod
        def Get():
            return SimpleNamespace(activate_node_template=lambda *a: None,
                                   get_node_attributes=lambda name, ports, path: dict.fromkeys(ports))

        @staticmethod
        def is_node_template_registered(name):
            checked.append(name)
            return True

        @staticmethod
        def register_node_template(template, template_name):
            registered[template_name] = template

        NodeConnectionTemplate = staticmethod(lambda name, **kw: (name, kw))
        NodeTemplate = staticmethod(lambda stage, node_type, connections, attrs:
                                   (stage, node_type, connections, attrs))

    og = SimpleNamespace(get_registered_nodes=lambda: ['omni.replicator.nv.FabricReader'],
                         register_node_type=lambda *a: None)
    import types
    omni = types.ModuleType('omni')
    omni.graph = types.ModuleType('omni.graph')
    omni.graph.core = og
    omni.replicator = types.ModuleType('omni.replicator')
    omni.replicator.core = types.ModuleType('omni.replicator.core')
    for name, value in {'omni': omni, 'omni.graph': omni.graph, 'omni.graph.core': og,
                        'omni.replicator': omni.replicator, 'omni.replicator.core': omni.replicator.core,
                        'warp': SimpleNamespace(),
                        'omni.gpu_foundation_factory': SimpleNamespace(TextureFormat=object),
                        'omni.syntheticdata': SimpleNamespace(SyntheticData=SD,
                            SyntheticDataStage=SimpleNamespace(ON_DEMAND=1, AUTO=2))}.items():
        monkeypatch.setitem(sys.modules, name, value)
    consumer = module.NativeResultConsumer(dict(left='/left', right='/right', scene='/scene'),
                                           lambda result: None, attribute_only=True, identity_only=identity_only)
    assert consumer.attribute_probe and not consumer.geometry
    assert consumer.camera_geometry == (not identity_only)
    assert ('PostRenderProductCamera' in checked) == (not identity_only)
    assert not any('Mapping' in name or 'Filter' in name for name in checked)
    assert not any('Mapping' in item[1] or 'PrimPaths' in item[1] for item in registered.values())
    cameras = [v for v in registered.values() if v[1] == 'omni.syntheticdata.SdRenderProductCamera']
    assert len(cameras) == (0 if identity_only else 1)
    if cameras:
        assert any(name.startswith('NativeLdrPointer_') for name, _ in cameras[0][2])
    pp = next(v for name, v in registered.items() if name.startswith('NativeAttribute_') and not name.endswith('PR'))
    assert any(name.startswith('NativeIdentifier_') for name, _ in pp[2])


@pytest.mark.parametrize("attribute_id", [7, 8, 0, True, None])
def test_identity_only_join_does_not_claim_geometry_and_rejects_unknown_source(attribute_id):
    proof = proof_for_test()
    proof.identity_only = proof.attribute_only = proof.attribute_probe = proof.clock_only = True
    proof.proof_scope = "publication_attribute"
    source = dict(publication_id=7, physics_step=28, reset_epoch=2, published_ns=1,
                  proof_scope=proof.proof_scope, body_matrices={})
    proof.history[7] = dict(source=source, observed_roles=set())
    result = dict(role="left_wrist", frame_identifier={"frameNumber": 901},
                  attribute_publication_id=attribute_id)
    row = proof.observe(result)
    assert row["history_join_matched"] == (type(attribute_id) is int and attribute_id == 7)
    assert not row["geometry_matched"] and not row["camera_geometry_checked"]
    assert not row["body_geometry_checked"] and not row["dataset_admissible"]
    assert proof.counts["matched"] == (type(attribute_id) is int and attribute_id == 7)
    compact = publication_log(source, True)
    assert compact["source_state_sha256"] is None and compact["camera_paths"] == []
    if type(attribute_id) is int and attribute_id == 7:
        assert row["physics_step"] == 28 and row["attribute_clock_matched"]


def test_identity_only_publication_has_no_native_pose_read_or_hierarchy_mutation(monkeypatch):
    monkeypatch.setitem(sys.modules, "usdrt", SimpleNamespace(Gf=object(), Sdf=object()))
    monkeypatch.setitem(sys.modules, "pxr", SimpleNamespace(UsdGeom=object()))
    proof = proof_for_test()
    proof.identity_only = proof.attribute_only = proof.attribute_probe = proof.clock_only = True
    proof.proof_scope = "publication_attribute"
    proof.counts["publications"], proof.capacity = 0, 256
    proof.env = SimpleNamespace(camera=SimpleNamespace(reset_epoch=2))
    written = []
    proof.attribute_clock = SimpleNamespace(Set=lambda value: written.append(value) or True)
    # No views, props, hierarchy or camera mounts are installed: touching any fails.
    proof._publish(28)
    assert written == [1] and proof.attribute_last_written == 1
    source = proof.history[1]["source"]
    assert source["physics_step"] == 28 and source["reset_epoch"] == 2
    assert source["proof_scope"] == "publication_attribute"
    assert not source["camera_geometry_checked"] and not source["body_geometry_checked"]
    assert not any(key in source for key in ("native_body_pose_xyzw", "q", "dq", "camera_matrices"))


def test_identity_optical_source_check_does_not_promote_geometry_quality():
    optical = OpticalPublication.__new__(OpticalPublication)
    optical.roles, optical.previous_decoded = ("left_wrist",), {}
    optical.marker = SimpleNamespace(decode=lambda image, publication, role, **kw:
        dict(confident=True, decoded_role=role, decoded_source=publication, passed=True))
    row = optical.observe(dict(role="left_wrist", rgba=np.zeros((1, 1, 4), dtype=np.uint8)),
                          dict(publication_id=7, history_join_matched=True, geometry_matched=False))
    assert row["optical_and_source_matched"]
    assert not row["geometry_matched"] and not row["optical_and_geometry_matched"]
    assert not row["dataset_admissible"]


@pytest.mark.parametrize("cache_helpers", [False, True])
def test_callback_helpers_cache_accessors_not_mutable_values_and_detach_before_clear(cache_helpers):
    path = Path(__file__).resolve().parents[1] / "docs/experiments/20261009_live_camera_recording_30hz/native_live/render_callback.py"
    spec = importlib.util.spec_from_file_location("native_helper_cache_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    consumer = module.NativeResultConsumer.__new__(module.NativeResultConsumer)
    constructed, reads, detached = [], [], []

    class Helper:
        def __init__(self, attr):
            self.attr = attr
            constructed.append(attr)

        def get(self):
            reads.append(self.attr["value"])
            return self.attr["value"]

    consumer.og = SimpleNamespace(AttributeValueHelper=Helper)
    consumer.closed, consumer.cache_helpers = False, cache_helpers
    consumer._value_helpers, consumer._attrs, consumer._streams = {}, {}, {}
    scalar, array = {"value": 1}, {"value": np.array([1], dtype=np.uint8)}
    attrs = dict(source=scalar, array=array)
    first = consumer._read_values('/node', attrs)
    scalar["value"], array["value"] = 2, np.array([2], dtype=np.uint8)
    second = consumer._read_values('/node', attrs)
    assert first['source'] == 1 and second['source'] == 2
    assert first['array'].tolist() == [1] and second['array'].tolist() == [2]
    assert len(reads) == 4 and len(constructed) == (2 if cache_helpers else 4)
    consumer._attached, consumer._templates = ['/product'], []
    consumer._consumer_name, consumer._registered, consumer._attribute_probe_stream = 'consumer', False, None

    def detach(*args, **kwargs):
        detached.append(bool(consumer._value_helpers))

    consumer.sd = SimpleNamespace(deactivate_node_template=detach)
    consumer.close()
    assert detached == [cache_helpers] and not consumer._value_helpers
    with pytest.raises(RuntimeError, match='detached'):
        consumer._read_values('/node', attrs)
    assert len(reads) == 4
