#!/usr/bin/env python3
"""Build the pinned Gate C PIPER-X as deterministic MuJoCo MJCF artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco

from isaac_s1_runtime import materialize_gate_c_urdf


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "f6642ce0d7872c686f29c99e9e10cd23d1d49313"
BUILDER_REVISION = "piper_x_gate_c_to_mujoco_scene_v28"
ARM_RELATIVE_DIR = Path("piper_x") / SOURCE_COMMIT
EMPTY_SCENE_NAME = "piper_x_bimanual_empty_v1.xml"
TASK_SCENE_NAME = "dual_cube_to_matching_plates_v1.xml"
ARM_JOINTS = tuple(f"joint{index}" for index in range(1, 7))
BASES = {"left": (0.233, 0.300, 0.825), "right": (0.233, -0.300, 0.825)}
HOME_DEG = {
    "left": (-20.0, 90.0, -50.0, 0.0, 0.0, 0.0),
    "right": (20.0, 90.0, -50.0, 0.0, 0.0, 0.0),
}


class MujocoBuildError(RuntimeError):
    """Raised when the pinned input or generated model violates the build contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(source: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(source), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _verify_source(source: Path) -> None:
    try:
        head = _git(source, "rev-parse", "HEAD")
        dirty = _git(source, "status", "--porcelain", "--untracked-files=no", "--", "piper_x")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MujocoBuildError(f"source is not a readable Git checkout: {source}") from exc
    if head != SOURCE_COMMIT:
        raise MujocoBuildError(f"source HEAD is {head}, expected {SOURCE_COMMIT}")
    if dirty:
        raise MujocoBuildError("pinned piper_x source contains tracked modifications")


def _write_xml(root: ET.Element, path: Path) -> None:
    ET.indent(root, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _stl_name(filename: str) -> str:
    name = Path(filename).name
    return f"{Path(name).stem}.stl" if name.lower().endswith(".dae") else name


def _materialize_meshes(
    source: Path, urdf_root: ET.Element, mesh_dir: Path
) -> list[dict[str, str]]:
    names = sorted({_stl_name(mesh.attrib["filename"]) for mesh in urdf_root.findall(".//mesh")})
    mesh_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, str]] = []
    for name in names:
        source_path = source / "piper_x" / "meshes" / name
        output_path = mesh_dir / name
        if not source_path.is_file():
            raise MujocoBuildError(f"missing pinned STL mesh: {source_path}")
        shutil.copyfile(source_path, output_path)
        source_digest = _sha256(source_path)
        if _sha256(output_path) != source_digest:
            raise MujocoBuildError(f"copied mesh hash mismatch: {name}")
        records.append({"path": f"meshes/{name}", "sha256": source_digest})
    return records


def _add_mujoco_urdf_extension(root: ET.Element) -> None:
    if root.find("mujoco") is not None:
        raise MujocoBuildError("unexpected existing MuJoCo extension in pinned URDF")
    extension = ET.SubElement(root, "mujoco")
    ET.SubElement(
        extension,
        "compiler",
        {"discardvisual": "false", "fusestatic": "false", "strippath": "false"},
    )


def _native_arm_xml(import_urdf: Path, mesh_dir: Path) -> ET.Element:
    urdf_root = ET.parse(import_urdf).getroot()
    adjacent_bodies: list[tuple[str, str]] = []
    for urdf_joint in urdf_root.findall("joint"):
        parent_element = urdf_joint.find("parent")
        child_element = urdf_joint.find("child")
        if (
            parent_element is not None
            and child_element is not None
            and parent_element.attrib["link"] != "world"
        ):
            adjacent_bodies.append((parent_element.attrib["link"], child_element.attrib["link"]))
    for mesh in urdf_root.findall(".//mesh"):
        mesh.attrib["filename"] = str((mesh_dir / _stl_name(mesh.attrib["filename"])).resolve())
    _add_mujoco_urdf_extension(urdf_root)
    _write_xml(urdf_root, import_urdf)

    native = ET.fromstring(mujoco.MjSpec.from_file(str(import_urdf)).to_xml())
    native.attrib["model"] = "piper_x_gate_c_mujoco"
    compiler = native.find("compiler")
    if compiler is None:
        raise MujocoBuildError("MuJoCo import lost its compiler element")
    native.insert(
        list(native).index(compiler) + 1,
        ET.Element("option", {"cone": "elliptic", "impratio": "10"}),
    )
    for mesh in native.findall("./asset/mesh"):
        mesh.attrib["file"] = f"meshes/{Path(mesh.attrib['file']).name}"
    for body in native.findall(".//worldbody//body"):
        body.attrib["gravcomp"] = "1"

    contact = ET.SubElement(native, "contact")
    for parent_name, child_name in adjacent_bodies:
        ET.SubElement(
            contact,
            "exclude",
            {
                "name": f"{parent_name}_{child_name}_adjacent",
                "body1": parent_name,
                "body2": child_name,
            },
        )

    gripper_base = native.find(".//body[@name='gripper_base']")
    if gripper_base is None:
        raise MujocoBuildError("MuJoCo import lost gripper_base")
    ET.SubElement(gripper_base, "site", {"name": "tcp", "pos": "0 0 0", "size": "0.003"})
    gripper_joint = gripper_base.find("./body[@name='gripper_link']/joint[@name='gripper']")
    if gripper_joint is None:
        raise MujocoBuildError("MuJoCo import lost gripper compatibility joint")
    gripper_joint.set("armature", "0.1")
    gripper_joint.set("damping", "2")
    for index in (1, 2):
        finger = gripper_base.find(f"./body[@name='gripper_link{index}']")
        if finger is None:
            raise MujocoBuildError(f"MuJoCo import lost gripper_link{index}")
        finger_joint = finger.find(f"./joint[@name='gripper_joint{index}']")
        if finger_joint is None:
            raise MujocoBuildError(f"MuJoCo import lost gripper_joint{index}")
        finger_joint.set("actuatorfrcrange", "-8 8")
        finger_joint.set("armature", "0.1")
        finger_joint.set("damping", "2")
        # Aperture and common-mode mechanics are represented by orthogonal
        # tendons below.  Do not add per-finger springs here: they also preload
        # the aperture coordinate and can overwhelm the bounded actuator.
        for imported_geom in finger.findall("geom"):
            imported_geom.set("contype", "0")
            imported_geom.set("conaffinity", "0")
        ET.SubElement(
            finger,
            "geom",
            {
                "name": f"gripper_pad{index}",
                "type": "box",
                "pos": "0 -0.043 0.001",
                # Match the source finger mesh's measured -28..+28 mm width;
                # keep the contact insert thin and planar.
                "size": "0.028 0.033 0.001",
                "rgba": "0 0 0 0",
                # This plane represents only the inner grasp surface.  Its
                # large rectangular proxy must not collide generically with
                # the table; the task scene declares the intended pad/cube
                # pairs explicitly below.
                "contype": "0",
                "conaffinity": "0",
                "condim": "6",
                "friction": "1.5 0.005 0.0001",
                "solref": "0.02 1",
                "solimp": "0.9 0.95 0.001",
                "density": "0",
            },
        )
    tendon = ET.SubElement(native, "tendon")
    aperture = ET.SubElement(
        tendon,
        "fixed",
        {"name": "gripper_aperture", "limited": "true", "range": "0 0.1"},
    )
    ET.SubElement(aperture, "joint", {"joint": "gripper_joint1", "coef": "1"})
    ET.SubElement(aperture, "joint", {"joint": "gripper_joint2", "coef": "-1"})
    center = ET.SubElement(
        tendon,
        "fixed",
        {
            "name": "gripper_center",
            # q1+q2 is constrained softly below. Keeping it as a named tendon
            # makes the common coordinate explicit without a second actuator.
        },
    )
    ET.SubElement(center, "joint", {"joint": "gripper_joint1", "coef": "1"})
    ET.SubElement(center, "joint", {"joint": "gripper_joint2", "coef": "1"})
    equality = ET.SubElement(native, "equality")
    ET.SubElement(
        equality,
        "tendon",
        {
            "name": "gripper_center_constraint",
            "tendon1": "gripper_center",
            "polycoef": "0 0 0 0 0",
            "solref": "0.02 1",
            "solimp": "0.9 0.95 0.001",
        },
    )

    joint_ranges = {
        joint.attrib["name"]: joint.attrib["range"]
        for joint in native.findall(".//joint")
        if "name" in joint.attrib and "range" in joint.attrib
    }
    actuator = ET.SubElement(native, "actuator")
    for joint_name in ARM_JOINTS:
        ET.SubElement(
            actuator,
            "position",
            {
                "name": f"{joint_name}_position",
                "joint": joint_name,
                "kp": "400",
                "kv": "40",
                "ctrllimited": "true",
                "ctrlrange": joint_ranges[joint_name],
                "forcerange": "-100 100",
            },
        )
    ET.SubElement(
        actuator,
        "general",
        {
            "name": "gripper_aperture_position",
            "tendon": "gripper_aperture",
            "ctrllimited": "true",
            "ctrlrange": "0 0.1",
            "forcerange": "-8 8",
            "biastype": "affine",
            # The passive centre tendon is orthogonal to q1-q2, so the aperture
            # servo uses an ordinary unbiased position law.
            "gainprm": "1250",
            "biasprm": "0 -1250 -30",
        },
    )
    return native


def _home_qpos() -> list[float]:
    radians = 3.141592653589793 / 180.0
    result: list[float] = []
    for side in ("left", "right"):
        result.extend(value * radians for value in HOME_DEG[side])
        result.extend((0.05, 0.025, -0.025))
    return result


def _home_ctrl() -> list[float]:
    radians = math.pi / 180.0
    result: list[float] = []
    for side in ("left", "right"):
        result.extend(value * radians for value in HOME_DEG[side])
        result.append(0.05)
    return result


def _vector_text(values: tuple[float, ...] | list[float]) -> str:
    return " ".join(f"{value:.12g}" for value in values)


def _look_at_xyaxes(
    eye: tuple[float, float, float],
    target: tuple[float, float, float],
    up: tuple[float, float, float],
) -> str:
    def normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
        length = math.sqrt(sum(value * value for value in vector))
        if length == 0.0:
            raise MujocoBuildError("camera look-at vector must be nonzero")
        return tuple(value / length for value in vector)  # type: ignore[return-value]

    def cross(
        left: tuple[float, float, float], right: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        return (
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        )

    forward = normalize(tuple(target[index] - eye[index] for index in range(3)))
    right = normalize(cross(forward, up))
    corrected_up = normalize(cross(right, forward))
    return _vector_text((*right, *corrected_up))


def _add_task_scene(empty_scene: ET.Element) -> ET.Element:
    scene = copy.deepcopy(empty_scene)
    scene.attrib["model"] = "piper_x_dual_cube_to_matching_plates_v1"
    visual = scene.find("visual")
    if visual is None:
        visual = ET.SubElement(scene, "visual")
    quality = visual.find("quality")
    if quality is None:
        quality = ET.SubElement(visual, "quality")
    quality.attrib["offsamples"] = "1"
    worldbody = scene.find("worldbody")
    if worldbody is None:
        raise MujocoBuildError("bimanual scene lost worldbody")

    ET.SubElement(
        worldbody,
        "geom",
        {
            "name": "floor",
            "group": "1",
            "type": "plane",
            "size": "3 3 0.1",
            "rgba": "0.12 0.14 0.16 1",
            "friction": "0.8 0.005 0.0001",
        },
    )
    ET.SubElement(
        worldbody,
        "geom",
        {
            "name": "table",
            "group": "1",
            "type": "box",
            "pos": "0.725 0 0.775",
            "size": "0.5 0.5 0.05",
            "rgba": "0.53 0.49 0.43 1",
            "friction": "0.8 0.005 0.0001",
        },
    )
    ET.SubElement(
        worldbody,
        "geom",
        {
            "name": "backdrop",
            "group": "1",
            "type": "box",
            "pos": "1.55 0 1.15",
            "size": "0.03 1.5 1.15",
            "rgba": "0.18 0.21 0.25 1",
            "contype": "0",
            "conaffinity": "0",
        },
    )
    for side, y, color in (
        ("left", 0.17, "0.10 0.42 0.92 1"),
        ("right", -0.17, "0.96 0.36 0.10 1"),
    ):
        ET.SubElement(
            worldbody,
            "geom",
            {
                "name": f"{side}_plate",
                "group": "1",
                "type": "cylinder",
                "pos": f"0.72 {y} 0.831",
                "size": "0.07 0.004",
                "rgba": color,
                "friction": "0.8 0.005 0.0001",
            },
        )
        cube = ET.SubElement(
            worldbody,
            "body",
            {"name": f"{side}_cube", "pos": f"0.52 {y} 0.847"},
        )
        ET.SubElement(cube, "freejoint", {"name": f"{side}_cube_free"})
        ET.SubElement(
            cube,
            "geom",
            {
                "name": f"{side}_cube_geom",
                "group": "1",
                "type": "box",
                "size": "0.02 0.02 0.02",
                "mass": "0.035",
                "rgba": color,
                "friction": "0.8 0.005 0.0001",
            },
        )

    # Explicit pad/cube pairs avoid MuJoCo's generic geom-parameter mixing for
    # the only contacts that must sustain a grasp.  They do not add sticky or
    # welded contacts: the cube remains a free body governed by Coulomb
    # friction and the aperture tendon force.
    contact = scene.find("contact")
    if contact is None:
        contact = ET.SubElement(scene, "contact")
    for side in ("left", "right"):
        for index in (1, 2):
            ET.SubElement(
                contact,
                "pair",
                {
                    "name": f"{side}_pad{index}_cube_contact",
                    "geom1": f"{side}_gripper_pad{index}",
                    "geom2": f"{side}_cube_geom",
                    "condim": "6",
                    "friction": "1.5 1.5 0.005 0.0001 0.0001",
                    "solref": "0.02 1",
                    "solimp": "0.9 0.95 0.001",
                },
            )
    wrist_fovy = math.degrees(2.0 * math.atan((20.955 * 480.0 / 640.0) / (2.0 * 18.0)))
    for side in ("left", "right"):
        gripper = scene.find(f".//body[@name='{side}_gripper_base']")
        if gripper is None:
            raise MujocoBuildError(f"task scene lost {side}_gripper_base")
        ET.SubElement(
            gripper,
            "camera",
            {
                "name": f"{side}_wrist",
                "pos": "0.1 0 0.05",
                # MuJoCo cameras look along local -Z. The gripper approach
                # direction is local +Z, so keep +X image-right and flip +Y.
                "xyaxes": "1 0 0 0 -1 0",
                "fovy": f"{wrist_fovy:.12g}",
            },
        )

    scene_eye = (0.10, 0.05, 1.43)
    scene_target = (0.65, 0.0, 0.88)
    scene_fovy = math.degrees(2.0 * math.atan(math.tan(math.radians(60.0) / 2.0) / (4.0 / 3.0)))
    ET.SubElement(
        worldbody,
        "camera",
        {
            "name": "scene",
            "pos": _vector_text(scene_eye),
            "xyaxes": _look_at_xyaxes(scene_eye, scene_target, (0.0, 0.0, 1.0)),
            "fovy": f"{scene_fovy:.12g}",
        },
    )
    ET.SubElement(
        worldbody,
        "light",
        {
            "name": "cool_fill",
            "pos": "0.2 0.8 2.3",
            "dir": "0.2 -0.2 -1",
            "directional": "true",
            "diffuse": "0.62 0.68 0.78",
            "ambient": "0.16 0.18 0.22",
            "specular": "0.08 0.08 0.08",
        },
    )
    ET.SubElement(
        worldbody,
        "light",
        {
            "name": "warm_key",
            "pos": "0.35 -0.75 2.4",
            "dir": "0.25 0.2 -1",
            "directional": "true",
            "diffuse": "1 0.91 0.78",
            "ambient": "0 0 0",
            "specular": "0.2 0.18 0.15",
        },
    )

    old_keyframe = scene.find("keyframe")
    if old_keyframe is not None:
        scene.remove(old_keyframe)
    cube_qpos = [0.52, 0.17, 0.847, 1.0, 0.0, 0.0, 0.0, 0.52, -0.17, 0.847, 1.0, 0.0, 0.0, 0.0]
    keyframe = ET.SubElement(scene, "keyframe")
    ET.SubElement(
        keyframe,
        "key",
        {
            "name": "home",
            "qpos": _vector_text([*_home_qpos(), *cube_qpos]),
            "ctrl": _vector_text(_home_ctrl()),
        },
    )
    return scene


def _build_scenes(arm_path: Path, empty_scene_path: Path, task_scene_path: Path) -> None:
    spec = mujoco.MjSpec()
    spec.modelname = "piper_x_bimanual_empty_v1"
    spec.option.timestep = 1.0 / 240.0
    spec.option.gravity = (0.0, 0.0, -9.81)
    spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    for side, position in BASES.items():
        frame = spec.worldbody.add_frame(name=f"{side}_mount", pos=position)
        child = mujoco.MjSpec.from_file(str(arm_path))
        spec.attach(child, prefix=f"{side}_", frame=frame)
    spec.compile()

    scene = ET.fromstring(spec.to_xml())
    option = scene.find("option")
    if option is None:
        raise MujocoBuildError("serialized bimanual scene lost its option element")
    option.attrib["timestep"] = f"{1.0 / 240.0:.17g}"
    # Use MuJoCo's recommended grasping model: an elliptic friction cone with
    # harder friction dimensions.  The NoSlip post-pass is intentionally left
    # disabled because the acquisition-and-roll regression exposed instability
    # in this bilateral, moving multi-contact grasp.
    option.attrib["cone"] = "elliptic"
    option.attrib["impratio"] = "10"
    mesh_dir = arm_path.parent / "meshes"
    for mesh in scene.findall("./asset/mesh"):
        relative = os.path.relpath(
            mesh_dir / Path(mesh.attrib["file"]).name, empty_scene_path.parent
        )
        mesh.attrib["file"] = Path(relative).as_posix()
    keyframe = ET.SubElement(scene, "keyframe")
    ET.SubElement(
        keyframe,
        "key",
        {"name": "home", "qpos": " ".join(f"{value:.17g}" for value in _home_qpos())},
    )
    _write_xml(scene, empty_scene_path)
    model = mujoco.MjModel.from_xml_path(str(empty_scene_path))
    if (model.nq, model.nu, model.neq) != (18, 14, 2):
        raise MujocoBuildError(
            f"unexpected bimanual dimensions nq={model.nq}, nu={model.nu}, neq={model.neq}"
        )
    task_scene = _add_task_scene(scene)
    _write_xml(task_scene, task_scene_path)
    task_model = mujoco.MjModel.from_xml_path(str(task_scene_path))
    if (task_model.nq, task_model.nv, task_model.nu, task_model.neq) != (32, 30, 14, 2):
        raise MujocoBuildError(
            "unexpected task dimensions "
            f"nq={task_model.nq}, nv={task_model.nv}, nu={task_model.nu}, neq={task_model.neq}"
        )


def build(source: Path, output_root: Path) -> dict[str, object]:
    _verify_source(source)
    arm_dir = output_root / ARM_RELATIVE_DIR
    empty_scene_path = output_root / "scenes" / EMPTY_SCENE_NAME
    task_scene_path = output_root / "scenes" / TASK_SCENE_NAME
    arm_path = arm_dir / "piper_x.xml"
    manifest_path = arm_dir / "manifest.json"
    mesh_dir = arm_dir / "meshes"

    with tempfile.TemporaryDirectory(prefix="piperx-mujoco-build-", dir="/tmp") as temporary:
        composed_urdf = Path(temporary) / "piper_x_gate_c.urdf"
        composed_digest = materialize_gate_c_urdf(source, composed_urdf)
        urdf_root = ET.parse(composed_urdf).getroot()
        mesh_records = _materialize_meshes(source, urdf_root, mesh_dir)
        arm_xml = _native_arm_xml(composed_urdf, mesh_dir)
        _write_xml(arm_xml, arm_path)

    arm_model = mujoco.MjModel.from_xml_path(str(arm_path))
    if (arm_model.nq, arm_model.nu, arm_model.neq) != (9, 7, 1):
        raise MujocoBuildError(
            f"unexpected single-arm dimensions nq={arm_model.nq}, nu={arm_model.nu}, neq={arm_model.neq}"
        )
    _build_scenes(arm_path, empty_scene_path, task_scene_path)

    license_source = source / "LICENSE"
    license_output = arm_dir / "LICENSE.agx_arm_urdf"
    shutil.copyfile(license_source, license_output)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "builder": {
            "revision": BUILDER_REVISION,
            "path": "tools/build_mujoco_piperx.py",
            "sha256": _sha256(Path(__file__)),
        },
        "runtime": {"mujoco_version": mujoco.__version__},
        "source": {
            "repository": "https://github.com/agilexrobotics/agx_arm_urdf",
            "commit": SOURCE_COMMIT,
            "base_urdf": {
                "path": "piper_x/urdf/piper_x_description.urdf",
                "sha256": _sha256(source / "piper_x/urdf/piper_x_description.urdf"),
            },
            "gripper_xacro": {
                "path": "piper_x/urdf/piper_x_with_gripper_description.xacro",
                "sha256": _sha256(source / "piper_x/urdf/piper_x_with_gripper_description.xacro"),
            },
            "composed_gate_c_urdf_sha256": composed_digest,
            "license_sha256": _sha256(license_source),
        },
        "conversion": {
            "mesh_strategy": "collision_stl_as_initial_visual_v1",
            "discardvisual": False,
            "fusestatic": False,
            "gripper_mapping": "one external aperture drives q1-q2; one soft tendon equality constrains passive q1+q2 common mode; no second finger actuator or compatibility-joint actuator",
            "gripper_collision": "continuous 56x66x2mm planar grasp pads matching the source finger STL width, with condim=6; pads use only explicit task cube pairs so their rectangular proxy cannot create false table contacts; imported finger meshes are visual-only",
            "contact_compliance": "damped MuJoCo default solref=0.02/1 and solimp=0.9/0.95/0.001 for stable bilateral rigid-pad contact",
            "contact_solver": "MuJoCo Newton solver with elliptic friction cones, impratio=10, and NoSlip disabled",
            "gripper_servo": "aperture tendon command gain/bias=1250 kv=30 force=8N; passive centre constraint solref=0.02/1 solimp=0.9/0.95/0.001; physical fingers armature=0.1kg damping=2Ns/m zero joint stiffness",
            "robot_gravcomp": 1.0,
        },
        "outputs": {
            "canonical_mjcf": {"path": "piper_x.xml", "sha256": _sha256(arm_path)},
            "empty_bimanual_mjcf": {
                "path": f"../../scenes/{EMPTY_SCENE_NAME}",
                "sha256": _sha256(empty_scene_path),
            },
            "task_scene_mjcf": {
                "path": f"../../scenes/{TASK_SCENE_NAME}",
                "sha256": _sha256(task_scene_path),
            },
            "license": {"path": license_output.name, "sha256": _sha256(license_output)},
            "meshes": mesh_records,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-checkout", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "assets/mujoco")
    arguments = parser.parse_args()
    build(arguments.source_checkout.resolve(), arguments.output_root.resolve())
    print("MUJOCO PIPER-X MILESTONE 1 BUILD: PASS")
    print(f"SOURCE: {SOURCE_COMMIT}")
    print(f"OUTPUT: {arguments.output_root.resolve() / ARM_RELATIVE_DIR / 'piper_x.xml'}")
    print(f"SCENE: {arguments.output_root.resolve() / 'scenes' / TASK_SCENE_NAME}")


if __name__ == "__main__":
    main()
