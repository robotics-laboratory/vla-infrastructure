"""CPU verifier for opt-in live Mesh phase/ghost probe; never creates a Renderer."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw
import mesh_freshness as marker


def ideal_frame(source, role):
    image = Image.new("RGB", (960, 600), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    x = marker.position(source)
    draw.rectangle((x-9, marker.Y-9, x+9, marker.Y+9), fill="white")
    bits = [(source >> i) & 1 for i in range(12)] + [role & 1, (role >> 1) & 1, 1, 0]
    for cell, bit in enumerate(bits):
        x, y = 300 + 24 * cell, 512 if bit else 552
        draw.rectangle((x-5, y-5, x+5, y+5), fill="white")
    return np.asarray(image).copy()


def self_test():
    from pxr import Gf, Usd, UsdGeom
    stage = Usd.Stage.CreateInMemory()
    cameras = [f"/World/Camera{role}" for role in range(3)]
    for role, path in enumerate(cameras):
        camera = UsdGeom.Camera.Define(stage, path)
        camera.CreateFocalLengthAttr(2.208)
        camera.CreateHorizontalApertureAttr(5.76)
        camera.CreateVerticalApertureAttr(3.24)
        camera.CreateVisibilityAttr("invisible")
        camera.AddTranslateOp().Set(Gf.Vec3d(1, 2, 3))
        stage.DefinePrim(f"/Live30/Camera{role}", "RenderProduct")
    marker.inject(stage, cameras)
    meshes = [prim for prim in stage.Traverse() if prim.IsA(UsdGeom.Mesh)]
    assert len(meshes) == 54
    assert all(marker.classify(str(prim.GetPath()), cameras) for prim in meshes)
    assert all(UsdGeom.Imageable(prim).ComputeVisibility() == "inherited" for prim in meshes)
    for prim in meshes:
        item = marker.classify(str(prim.GetPath()), cameras)
        camera = UsdGeom.Camera(stage.GetPrimAtPath(cameras[item["temporal_role"]]))
        intrinsics = [camera.GetFocalLengthAttr().Get(), camera.GetHorizontalApertureAttr().Get(), camera.GetVerticalApertureAttr().Get()]
        camera_world = np.array(camera.ComputeLocalToWorldTransform(Usd.TimeCode.Default()))
        mesh_world = np.array(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()))
        assert np.allclose(mesh_world @ np.linalg.inv(camera_world), marker.local_matrix(item["temporal_kind"], item["temporal_role"], intrinsics, 0))
        if item["temporal_kind"] == "marker":
            points = np.c_[np.asarray(UsdGeom.Mesh(prim).GetPointsAttr().Get()), np.ones(4)] @ mesh_world @ np.linalg.inv(camera_world)
            focal_pixels = 960 * intrinsics[0] / intrinsics[1]
            pixels = np.c_[480 + focal_pixels * points[:, 0] / -points[:, 2], 300 - focal_pixels * points[:, 1] / -points[:, 2]]
            assert np.allclose(pixels.min(0), [90, 520]) and np.allclose(pixels.max(0), [110, 540])
    for role in range(3):
        assert marker.decode(ideal_frame(17, role), 17, role, 16)["passed"]
        assert not marker.decode(ideal_frame(16, role), 17, role, 16)["passed"]
        image = ideal_frame(17, role)
        old = ideal_frame(16, role)
        x = marker.position(16)
        image[marker.Y-9:marker.Y+10, x-9:x+10] = old[marker.Y-9:marker.Y+10, x-9:x+10] // 4
        assert not marker.decode(image, 17, role, 16)["passed"]
    return dict(passed=True, cases=["USD54Mesh_visible_despite_hidden_camera", "explicit_camera_publication_binding", "ideal_current", "stale_source_rejected", "quarter_intensity_old_position_ghost_rejected"], no_gpu=True)


def verify(input_dir, output, retained_helper=None):
    global marker
    seed_path = input_dir / "mirror/seed.json"
    seed = json.loads(seed_path.read_text())
    if not seed.get("mesh_freshness"):
        raise ValueError("Run did not enable Mesh freshness probe")
    pinned_path = seed["mesh_freshness"]["helper_path"]
    helper_path = retained_helper or Path(pinned_path)
    digest = hashlib.sha256(helper_path.read_bytes()).hexdigest()
    if digest != seed["helper_hashes"][pinned_path]:
        raise ValueError("Verifier helper differs from pinned run source; use retained helper")
    spec = importlib.util.spec_from_file_location("retained_mesh_freshness", helper_path)
    marker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(marker)
    rows_path = input_dir / "mirror/worker-rows.jsonl"
    expected = [json.loads(line)["source_id"] for line in rows_path.read_text().splitlines()]
    if expected != list(range(len(expected))):
        raise ValueError("Source sequence is not consecutive from zero")
    result = dict(schema="live30_discontinuous_mesh_phase_v1", input=str(input_dir), diagnostic_only=True,
                  dataset_admissible=False, physical=False, passed=False, roles=[], commands=[],
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  helper_sha256=digest, worker_rows_sha256=hashlib.sha256(rows_path.read_bytes()).hexdigest(),
                  limitations=["Camera-relative diagnostic Mesh phase, not arbitrary robot body pose equivalence.",
                               "Emissive marker does not establish temporal history behavior of every material.",
                               "CPU decode and verification are excluded from recording throughput."])
    output.parent.mkdir(parents=True, exist_ok=True)
    for role in range(3):
        video = input_dir / f"mirror/media/role{role}/stream.h264"
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        decoded, errors, measurements = 0, [], []
        previous = None
        try:
            while True:
                buffer = bytearray()
                while len(buffer) < 960*600*3:
                    part = proc.stdout.read(960*600*3 - len(buffer))
                    if not part:
                        break
                    buffer.extend(part)
                if not buffer:
                    break
                if len(buffer) != 960*600*3 or decoded >= len(expected):
                    raise RuntimeError("Partial or extra decoded frame")
                image = np.frombuffer(buffer, np.uint8).reshape(600, 960, 3)
                measurement = marker.decode(image, expected[decoded], role, previous)
                measurements.append(measurement)
                if not measurement["passed"]:
                    errors.append(measurement)
                if decoded in [16, 17, 64, 95, 96, 111, 112, 127, 128]:
                    Image.fromarray(image[488:578]).save(output.parent / f"mesh-role{role}-source{decoded:04d}.png")
                previous = expected[decoded]
                decoded += 1
            proc.stdout.close()
            stderr = proc.stderr.read().decode()
            code = proc.wait(timeout=30)
            if code:
                raise RuntimeError(stderr)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        changes = [m for m in measurements if m["changed_position"]]
        result["commands"].append(dict(command=command, returncode=code, stderr=stderr))
        result["roles"].append(dict(role=role, frames=decoded, passed=decoded==len(expected) and not errors,
            video_sha256=hashlib.sha256(video.read_bytes()).hexdigest(), errors=errors, measurements=measurements,
            transitions=len(changes), maximum_old_roi_normalized=max((m["previous_roi_normalized"] for m in changes), default=None),
            maximum_centroid_error_px=max((m["centroid_error_px"] or 0 for m in measurements), default=None)))
        output.write_text(json.dumps(result, indent=2)+"\n")
    result["passed"] = all(role["passed"] for role in result["roles"])
    output.write_text(json.dumps(result, indent=2)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--retained-helper", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
    else:
        if args.input is None or args.output is None:
            parser.error("--input and --output required")
        receipt = verify(args.input, args.output, args.retained_helper)
        print(json.dumps({k:v for k,v in receipt.items() if k != "roles"}, indent=2))
        print(json.dumps([{k:v for k,v in role.items() if k not in ["measurements", "errors"]} for role in receipt["roles"]], indent=2))
        raise SystemExit(0 if receipt["passed"] else 1)
