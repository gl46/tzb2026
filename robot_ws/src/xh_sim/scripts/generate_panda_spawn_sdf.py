#!/usr/bin/env python3
"""Generate and verify the M1A Gazebo-only Panda SDF spawn representation.

ADR-0009 keeps ``panda_controlled.urdf`` as the single robot specification for
MoveIt and robot_state_publisher.  Gazebo receives a fresh SDF generated from
that URDF because the ``ros_gz_sim create -topic`` conversion path loses the
leader name of the SDF mimic constraint on this platform.

The generator intentionally has no Gazebo control API.  It performs a local,
deterministic description conversion, validates the allowed representation
delta, and writes the SDF plus a manifest consumed by runtime gates.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


MIMIC_FOLLOWER = "panda_finger_joint1"
MIMIC_MASTER = "panda_finger_joint2"
# The controlled URDF and public protocol retain q1 == q2, with positive
# values opening both fingers. The generated SDF deliberately retains the
# same direct multiplier and source axes. Rejected Bullet compensation probes
# are documented in ADR-0009 rather than retained in the production path.
SEMANTIC_MIMIC_MULTIPLIER = 1.0
BULLET_SDF_MIMIC_MULTIPLIER = 1.0
EPSILON = 1e-8


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text(element: ET.Element | None, default: str = "") -> str:
    return element.text.strip() if element is not None and element.text else default


def pose_values(element: ET.Element | None) -> list[float]:
    values = [float(value) for value in text(element, "0 0 0 0 0 0").split()]
    if len(values) != 6:
        raise ValueError(f"expected 6 pose values, got {values}")
    return values


def origin_values(element: ET.Element | None) -> list[float]:
    if element is None:
        return [0.0] * 6
    xyz = [float(value) for value in element.attrib.get("xyz", "0 0 0").split()]
    rpy = [float(value) for value in element.attrib.get("rpy", "0 0 0").split()]
    if len(xyz) != 3 or len(rpy) != 3:
        raise ValueError(f"invalid URDF origin {element.attrib}")
    return xyz + rpy


def identity() -> list[list[float]]:
    return [[1.0 if row == column else 0.0 for column in range(4)] for row in range(4)]


def multiply(first: list[list[float]], second: list[list[float]]) -> list[list[float]]:
    return [
        [sum(first[row][index] * second[index][column] for index in range(4)) for column in range(4)]
        for row in range(4)
    ]


def transform(values: list[float]) -> list[list[float]]:
    x, y, z, roll, pitch, yaw = values
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    # URDF/SDF RPY uses fixed-axis roll, pitch, yaw, equivalently Rz * Ry * Rx.
    rotation = [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]
    output = identity()
    for row in range(3):
        for column in range(3):
            output[row][column] = rotation[row][column]
    output[0][3], output[1][3], output[2][3] = x, y, z
    return output


def matrix_error(first: list[list[float]], second: list[list[float]]) -> float:
    return max(abs(first[row][column] - second[row][column]) for row in range(4) for column in range(4))


def normalized_xml(element: ET.Element) -> str:
    copy = deepcopy(element)
    for node in copy.iter():
        if node.text is not None:
            node.text = " ".join(node.text.split())
        if node.tail is not None:
            node.tail = None
        node.attrib = dict(sorted(node.attrib.items()))
    return ET.tostring(copy, encoding="unicode", short_empty_elements=True)


def child(parent: ET.Element, tag: str) -> ET.Element:
    value = parent.find(tag)
    if value is None:
        raise ValueError(f"missing <{tag}> in <{parent.tag}>")
    return value


def values_close(first: list[float], second: list[float], *, label: str) -> None:
    if len(first) != len(second) or any(abs(a - b) > EPSILON for a, b in zip(first, second)):
        raise ValueError(f"{label} mismatch: {first} != {second}")


def parse_vector(value: str) -> list[float]:
    return [float(item) for item in value.split()]


def remove_detachable_plugin(urdf_root: ET.Element) -> None:
    removed = 0
    for gazebo in urdf_root.findall("gazebo"):
        for plugin in list(gazebo.findall("plugin")):
            if plugin.attrib.get("name") == "gz::sim::systems::DetachableJoint":
                gazebo.remove(plugin)
                removed += 1
    if removed != 1:
        raise ValueError(f"calibration SDF expected one detachable-joint plugin, removed {removed}")


def source_joint_contract(urdf_root: ET.Element) -> dict[str, dict]:
    contract: dict[str, dict] = {}
    for joint in urdf_root.findall("joint"):
        name = joint.attrib["name"]
        if joint.attrib["type"] == "fixed":
            continue
        axis = child(joint, "axis").attrib.get("xyz", "0 0 1")
        limit = child(joint, "limit")
        contract[name] = {
            "type": joint.attrib["type"],
            "axis": parse_vector(axis),
            "lower": float(limit.attrib["lower"]),
            "upper": float(limit.attrib["upper"]),
            "effort": float(limit.attrib["effort"]),
            "velocity": float(limit.attrib["velocity"]),
        }
    return contract


def sdf_joint_contract(sdf_model: ET.Element) -> dict[str, dict]:
    contract: dict[str, dict] = {}
    for joint in sdf_model.findall("joint"):
        if joint.attrib.get("type") == "fixed":
            continue
        axis = child(joint, "axis")
        limit = child(axis, "limit")
        contract[joint.attrib["name"]] = {
            "type": joint.attrib["type"],
            "axis": parse_vector(text(child(axis, "xyz"))),
            "lower": float(text(child(limit, "lower"))),
            "upper": float(text(child(limit, "upper"))),
            "effort": float(text(child(limit, "effort"))),
            "velocity": float(text(child(limit, "velocity"))),
        }
    return contract


def verify_joint_contract(urdf_root: ET.Element, sdf_model: ET.Element) -> dict:
    source = source_joint_contract(urdf_root)
    generated = sdf_joint_contract(sdf_model)
    if set(source) != set(generated):
        raise ValueError(f"generated SDF non-fixed joint set mismatch: {set(source) ^ set(generated)}")
    for name in sorted(source):
        if source[name]["type"] != generated[name]["type"]:
            raise ValueError(f"joint type mismatch for {name}")
        values_close(source[name]["axis"], generated[name]["axis"], label=f"{name} axis")
        for field in ("lower", "upper", "effort", "velocity"):
            if abs(source[name][field] - generated[name][field]) > EPSILON:
                raise ValueError(f"joint {name} {field} mismatch")
    return {"verified": True, "joint_count": len(source), "units": "SI: metres and radians"}


def urdf_zero_transforms(urdf_root: ET.Element) -> dict[str, list[list[float]]]:
    pending = list(urdf_root.findall("joint"))
    transforms = {"world": identity()}
    while pending:
        remaining = []
        progressed = False
        for joint in pending:
            parent = child(joint, "parent").attrib["link"]
            child_link = child(joint, "child").attrib["link"]
            if parent not in transforms:
                remaining.append(joint)
                continue
            transforms[child_link] = multiply(transforms[parent], transform(origin_values(joint.find("origin"))))
            progressed = True
        if not progressed:
            names = [joint.attrib.get("name", "unnamed") for joint in remaining]
            raise ValueError(f"could not resolve URDF zero transforms for {names}")
        pending = remaining
    return transforms


def sdf_zero_transforms(sdf_model: ET.Element) -> dict[str, list[list[float]]]:
    frames: dict[str, tuple[str, list[float]]] = {
        "__model__": ("", [0.0] * 6),
        "world": ("", [0.0] * 6),
    }
    for tag in ("joint", "link", "frame"):
        for element in sdf_model.findall(tag):
            name = element.attrib["name"]
            pose = element.find("pose")
            if pose is None:
                reference = element.attrib.get("attached_to", "__model__")
                values = [0.0] * 6
            else:
                reference = pose.attrib.get("relative_to", element.attrib.get("attached_to", "__model__"))
                values = pose_values(pose)
            frames[name] = (reference, values)

    output: dict[str, list[list[float]]] = {}
    resolving: set[str] = set()

    def resolve(name: str) -> list[list[float]]:
        if name in output:
            return output[name]
        if name in resolving:
            raise ValueError(f"cycle while resolving SDF frame {name}")
        if name not in frames:
            raise ValueError(f"unknown SDF frame {name}")
        resolving.add(name)
        reference, values = frames[name]
        resolved = transform(values) if not reference else multiply(resolve(reference), transform(values))
        resolving.remove(name)
        output[name] = resolved
        return resolved

    for name in frames:
        resolve(name)
    return output


def verify_zero_transforms(urdf_root: ET.Element, sdf_model: ET.Element) -> dict:
    source = urdf_zero_transforms(urdf_root)
    generated = sdf_zero_transforms(sdf_model)
    missing = sorted(name for name in source if name != "world" and name not in generated)
    if missing:
        raise ValueError(f"generated SDF misses source link frames {missing}")
    errors = {name: matrix_error(matrix, generated[name]) for name, matrix in source.items() if name != "world"}
    maximum = max(errors.values(), default=0.0)
    if maximum > EPSILON:
        raise ValueError(f"SDF zero-pose transform mismatch: max matrix error {maximum}")
    return {"verified": True, "frame_count": len(errors), "max_matrix_error": maximum}


def geometry_signature(geometry: ET.Element) -> tuple:
    if len(geometry) != 1:
        raise ValueError("geometry must contain exactly one shape")
    shape = geometry[0]
    def numbers(value: str) -> tuple[float, ...]:
        return tuple(round(float(item), 12) for item in value.split())

    if shape.tag == "box":
        return "box", numbers(shape.attrib.get("size", text(shape.find("size"))))
    if shape.tag == "cylinder":
        radius = shape.attrib.get("radius", text(shape.find("radius")))
        length = shape.attrib.get("length", text(shape.find("length")))
        return "cylinder", (round(float(radius), 12), round(float(length), 12))
    if shape.tag == "sphere":
        radius = shape.attrib.get("radius", text(shape.find("radius")))
        return "sphere", (round(float(radius), 12),)
    if shape.tag == "mesh":
        uri = shape.attrib.get("filename", text(shape.find("uri"))).replace("package://", "model://")
        scale = numbers(shape.attrib.get("scale", text(shape.find("scale"), "1 1 1")))
        return "mesh", (uri, *scale)
    raise ValueError(f"unsupported collision geometry {shape.tag}")


def urdf_collision_contract(urdf_root: ET.Element) -> Counter:
    transforms = urdf_zero_transforms(urdf_root)
    output: Counter = Counter()
    for link in urdf_root.findall("link"):
        link_transform = transforms.get(link.attrib["name"])
        if link_transform is None:
            continue
        for collision in link.findall("collision"):
            absolute = multiply(link_transform, transform(origin_values(collision.find("origin"))))
            rounded = tuple(round(value, 8) for row in absolute for value in row)
            output[(geometry_signature(child(collision, "geometry")), rounded)] += 1
    return output


def sdf_collision_contract(sdf_model: ET.Element) -> Counter:
    transforms = sdf_zero_transforms(sdf_model)
    output: Counter = Counter()
    for link in sdf_model.findall("link"):
        link_transform = transforms[link.attrib["name"]]
        for collision in link.findall("collision"):
            absolute = multiply(link_transform, transform(pose_values(collision.find("pose"))))
            rounded = tuple(round(value, 8) for row in absolute for value in row)
            output[(geometry_signature(child(collision, "geometry")), rounded)] += 1
    return output


def verify_collisions(urdf_root: ET.Element, sdf_model: ET.Element) -> dict:
    source, generated = urdf_collision_contract(urdf_root), sdf_collision_contract(sdf_model)
    if source != generated:
        missing = list((source - generated).elements())[:3]
        added = list((generated - source).elements())[:3]
        raise ValueError(f"collision geometry/transform mismatch; missing={missing}, added={added}")
    return {"verified": True, "collision_count": sum(source.values())}


def urdf_sensor_contract(urdf_root: ET.Element) -> dict[str, dict]:
    transforms = urdf_zero_transforms(urdf_root)
    output: dict[str, dict] = {}
    for gazebo in urdf_root.findall("gazebo"):
        reference = gazebo.attrib.get("reference")
        for sensor in gazebo.findall("sensor"):
            name = sensor.attrib["name"]
            if name in output or reference not in transforms:
                raise ValueError(f"invalid source sensor {name}")
            output[name] = {
                "type": sensor.attrib.get("type"),
                "topic": text(sensor.find("topic")),
                "update_rate": float(text(sensor.find("update_rate"), "0")),
                "reference_transform": transforms[reference],
            }
    return output


def sdf_sensor_contract(sdf_model: ET.Element) -> dict[str, dict]:
    transforms = sdf_zero_transforms(sdf_model)
    output: dict[str, dict] = {}
    for link in sdf_model.findall("link"):
        for sensor in link.findall("sensor"):
            name = sensor.attrib["name"]
            if name in output:
                raise ValueError(f"duplicate generated sensor {name}")
            output[name] = {
                "type": sensor.attrib.get("type"),
                "topic": text(sensor.find("topic")),
                "update_rate": float(text(sensor.find("update_rate"), "0")),
                "reference_transform": transforms[link.attrib["name"]],
            }
    return output


def verify_sensors(urdf_root: ET.Element, sdf_model: ET.Element) -> dict:
    source, generated = urdf_sensor_contract(urdf_root), sdf_sensor_contract(sdf_model)
    if set(source) != set(generated):
        raise ValueError(f"sensor name mismatch: {set(source) ^ set(generated)}")
    for name in source:
        for field in ("type", "topic"):
            if source[name][field] != generated[name][field]:
                raise ValueError(f"sensor {name} {field} mismatch")
        if abs(source[name]["update_rate"] - generated[name]["update_rate"]) > EPSILON:
            raise ValueError(f"sensor {name} update rate mismatch")
        if matrix_error(source[name]["reference_transform"], generated[name]["reference_transform"]) > EPSILON:
            raise ValueError(f"sensor {name} reference transform mismatch")
    return {"verified": True, "sensor_count": len(source), "sensor_names": sorted(source)}


def plugin_contract(urdf_root: ET.Element) -> set[tuple[str, str]]:
    return {
        (plugin.attrib.get("name", ""), plugin.attrib.get("filename", ""))
        for gazebo in urdf_root.findall("gazebo") for plugin in gazebo.findall("plugin")
    }


def verify_plugins(urdf_root: ET.Element, sdf_model: ET.Element) -> dict:
    source = plugin_contract(urdf_root)
    generated = {(plugin.attrib.get("name", ""), plugin.attrib.get("filename", "")) for plugin in sdf_model.findall("plugin")}
    if source != generated:
        raise ValueError(f"plugin mismatch: source={source}, generated={generated}")
    return {"verified": True, "plugins": sorted("|".join(item) for item in source)}


def remove_mimics(sdf_model: ET.Element) -> int:
    removed = 0
    for axis in sdf_model.findall("./joint/axis"):
        for mimic in list(axis.findall("mimic")):
            axis.remove(mimic)
            removed += 1
    return removed


def inject_canonical_mimic(sdf_model: ET.Element) -> None:
    joint = next((item for item in sdf_model.findall("joint") if item.attrib.get("name") == MIMIC_FOLLOWER), None)
    if joint is None:
        raise ValueError(f"generated SDF lacks {MIMIC_FOLLOWER}")
    axis = child(joint, "axis")
    mimic = ET.Element("mimic", {"joint": MIMIC_MASTER, "axis": "axis"})
    ET.SubElement(mimic, "multiplier").text = f"{BULLET_SDF_MIMIC_MULTIPLIER:g}"
    ET.SubElement(mimic, "offset").text = "0"
    ET.SubElement(mimic, "reference").text = "0"
    axis.insert(1, mimic)


def verify_mimic(urdf_root: ET.Element, sdf_model: ET.Element) -> dict:
    source = next((joint for joint in urdf_root.findall("joint") if joint.attrib.get("name") == MIMIC_FOLLOWER), None)
    if source is None or source.find("mimic") is None or source.find("mimic").attrib.get("joint") != MIMIC_MASTER:
        raise ValueError("URDF master/follower contract is not PANDA_MIMIC_Q2_MASTER")
    if source.find("mimic").attrib.get("multiplier") != "1":
        raise ValueError("controlled URDF must retain the q1=q2 positive-open semantic multiplier")
    matches = []
    for joint in sdf_model.findall("joint"):
        for mimic in joint.findall("./axis/mimic"):
            matches.append((joint.attrib.get("name"), mimic))
    if len(matches) != 1 or matches[0][0] != MIMIC_FOLLOWER:
        raise ValueError(f"generated SDF mimic set is invalid: {[name for name, _ in matches]}")
    mimic = matches[0][1]
    if mimic.attrib != {"joint": MIMIC_MASTER, "axis": "axis"}:
        raise ValueError(f"generated SDF mimic attributes are invalid: {mimic.attrib}")
    values = {item.tag: text(item) for item in mimic}
    if values != {"multiplier": f"{BULLET_SDF_MIMIC_MULTIPLIER:g}", "offset": "0", "reference": "0"}:
        raise ValueError(f"generated SDF mimic numeric contract is invalid: {values}")
    return {
        "verified": True,
        "follower": MIMIC_FOLLOWER,
        "master": MIMIC_MASTER,
        "semantic_multiplier": SEMANTIC_MIMIC_MULTIPLIER,
        "sdf_multiplier": BULLET_SDF_MIMIC_MULTIPLIER,
        "offset": 0.0,
        "reference": 0.0,
    }


def verify_ros2_control_contract(urdf_root: ET.Element, sdf_model: ET.Element) -> dict:
    """Require q2 to be the only controller command path for the SDF mimic."""

    def hand_interfaces(root: ET.Element) -> dict:
        ros2_control = child(root, "ros2_control")
        joints = {
            joint.attrib.get("name"): joint
            for joint in ros2_control.findall("joint")
        }
        q1 = joints.get(MIMIC_FOLLOWER)
        q2 = joints.get(MIMIC_MASTER)
        if q1 is None or q2 is None:
            raise ValueError("ros2_control lacks the q1/q2 hand declarations")
        forbidden = [
            param.attrib.get("name")
            for param in q1.findall("param")
            if param.attrib.get("name") in {"mimic", "multiplier"}
        ]
        if forbidden:
            raise ValueError(
                "q1 ros2_control must remain state-only; forbidden parameters: "
                + ", ".join(sorted(forbidden))
            )
        if q1.attrib.get("mimic") != "false":
            raise ValueError(
                "q1 ros2_control must explicitly opt out of structural URDF mimic parsing"
            )
        q1_commands = [item.attrib.get("name") for item in q1.findall("command_interface")]
        q1_states = [item.attrib.get("name") for item in q1.findall("state_interface")]
        q2_commands = [item.attrib.get("name") for item in q2.findall("command_interface")]
        q2_states = [item.attrib.get("name") for item in q2.findall("state_interface")]
        if q1_commands or q1_states != ["position", "velocity"]:
            raise ValueError(f"q1 must export only position/velocity state, got commands={q1_commands}, states={q1_states}")
        if q2_commands != ["position"] or q2_states != ["position", "velocity"]:
            raise ValueError(f"q2 command/state contract is invalid: commands={q2_commands}, states={q2_states}")
        q1_initial = text(q1.find("state_interface[@name='position']/param[@name='initial_value']"))
        q2_initial = text(q2.find("state_interface[@name='position']/param[@name='initial_value']"))
        if q1_initial != "0.02" or q2_initial != "0.02":
            raise ValueError(f"hand initial values must remain 0.02 m, got q1={q1_initial}, q2={q2_initial}")
        return {
            "q1_command_interfaces": q1_commands,
            "q1_state_interfaces": q1_states,
            "q1_forbidden_mimic_parameters": forbidden,
            "q1_structural_mimic_opt_out": q1.attrib.get("mimic"),
            "q1_initial_value_m": float(q1_initial),
            "q2_command_interfaces": q2_commands,
            "q2_state_interfaces": q2_states,
            "q2_initial_value_m": float(q2_initial),
        }

    source = hand_interfaces(urdf_root)
    generated = hand_interfaces(sdf_model)
    if source != generated:
        raise ValueError("generated SDF ros2_control hand contract differs from the controlled URDF")
    return {"verified": True, **source}


def detachable_plugins(root: ET.Element) -> list[ET.Element]:
    return [
        plugin for gazebo in root.findall("gazebo") for plugin in gazebo.findall("plugin")
        if plugin.attrib.get("name") == "gz::sim::systems::DetachableJoint"
    ]


def inject_per_object_detachables(urdf_root: ET.Element, scene_supervision: Path) -> list[str]:
    """Replace the M1A cube constraint with ADR-0013's N object constraints."""
    payload = json.loads(scene_supervision.read_text(encoding="utf-8"))
    objects = payload.get("simulator_supervision", {}).get("objects", [])
    names = [str(item.get("actual_sim_entity_id", "")) for item in objects]
    if not names or any(not name.startswith("cylinder_") for name in names) or len(set(names)) != len(names):
        raise ValueError("beta scene supervision must contain unique cylinder_* object names")
    original = detachable_plugins(urdf_root)
    if len(original) != 1:
        raise ValueError(f"beta SDF expected one source detachable plugin, found {len(original)}")
    owner = next(gazebo for gazebo in urdf_root.findall("gazebo") if original[0] in list(gazebo))
    owner.remove(original[0])
    for name in names:
        plugin = ET.SubElement(owner, "plugin", {"filename": "gz-sim-detachable-joint-system", "name": "gz::sim::systems::DetachableJoint"})
        ET.SubElement(plugin, "parent_link").text = "panda_link7"
        ET.SubElement(plugin, "child_model").text = name
        ET.SubElement(plugin, "child_link").text = "link"
        ET.SubElement(plugin, "detach_topic").text = f"/xh/m1b/{name}/detach"
        ET.SubElement(plugin, "attach_topic").text = f"/xh/m1b/{name}/attach"
        ET.SubElement(plugin, "output_topic").text = f"/xh/m1b/{name}/grasp_state"
    return names


def prepare_urdf(source: Path, package_share: Path, mode: str, scene_supervision: Path | None = None) -> tuple[ET.Element, list[str]]:
    root = ET.fromstring(source.read_text(encoding="utf-8").replace("$(find xh_sim)", str(package_share)))
    if root.tag != "robot":
        raise ValueError("input must be a URDF robot")
    if mode == "calibration":
        remove_detachable_plugin(root)
    if mode == "beta":
        if scene_supervision is None or not scene_supervision.is_file():
            raise ValueError("beta SDF generation requires --scene-supervision")
        return root, inject_per_object_detachables(root, scene_supervision)
    return root, []


def write_xml(path: Path, root: ET.Element, *, declaration: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=declaration)
    path.write_bytes(path.read_bytes() + b"\n")


def generate(args: argparse.Namespace) -> dict:
    source = Path(args.urdf).resolve()
    package_share = Path(args.package_share).resolve()
    output_sdf = Path(args.output_sdf).resolve()
    output_urdf = Path(args.output_urdf).resolve()
    manifest_path = Path(args.manifest).resolve()
    scene_supervision = Path(args.scene_supervision).resolve() if args.scene_supervision else None
    if not source.is_file() or not package_share.is_dir():
        raise ValueError("URDF and package share paths must exist")
    source_sha = sha256(source)
    urdf_root, beta_objects = prepare_urdf(source, package_share, args.mode, scene_supervision)
    write_xml(output_urdf, urdf_root, declaration=True)

    with tempfile.TemporaryDirectory(prefix="xh-panda-sdf-") as temporary:
        converter_input = Path(temporary) / "panda_resolved.urdf"
        write_xml(converter_input, deepcopy(urdf_root), declaration=True)
        result = subprocess.run(
            ["gz", "sdf", "-p", str(converter_input)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    if result.returncode != 0:
        raise RuntimeError(f"gz sdf -p failed: {result.stderr.strip() or result.stdout.strip()}")
    sdf_root = ET.fromstring(result.stdout)
    sdf_model = child(sdf_root, "model")
    if sdf_model.find("ros2_control") is not None:
        raise ValueError("converter unexpectedly retained ros2_control; update the whitelist before use")
    sdf_model.append(deepcopy(child(urdf_root, "ros2_control")))

    pre_injection = deepcopy(sdf_root)
    if remove_mimics(pre_injection.find("model")) != 1:
        raise ValueError("expected exactly one converter mimic before canonical injection")
    final_root = deepcopy(pre_injection)
    inject_canonical_mimic(child(final_root, "model"))
    final_without_mimic = deepcopy(final_root)
    if remove_mimics(child(final_without_mimic, "model")) != 1 or normalized_xml(pre_injection) != normalized_xml(final_without_mimic):
        raise ValueError("SDF whitelist diff contains a semantic delta beyond the injected mimic")
    final_model = child(final_root, "model")

    joint_evidence = verify_joint_contract(urdf_root, final_model)
    transform_evidence = verify_zero_transforms(urdf_root, final_model)
    collision_evidence = verify_collisions(urdf_root, final_model)
    sensor_evidence = verify_sensors(urdf_root, final_model)
    plugin_evidence = verify_plugins(urdf_root, final_model)
    if args.mode == "beta":
        generated_detachables = [item for item in final_model.findall("plugin") if item.attrib.get("name") == "gz::sim::systems::DetachableJoint"]
        if len(generated_detachables) != len(beta_objects):
            raise ValueError("beta generated SDF detachable plugin count mismatch")
        expected_topics = {f"/xh/m1b/{name}/{suffix}" for name in beta_objects for suffix in ("attach", "detach", "grasp_state")}
        actual_topics = {text(item.find(tag)) for item in generated_detachables for tag in ("attach_topic", "detach_topic", "output_topic")}
        if actual_topics != expected_topics:
            raise ValueError("beta generated SDF detachable topic contract mismatch")
    mimic_evidence = verify_mimic(urdf_root, final_model)
    ros2_control_evidence = verify_ros2_control_contract(urdf_root, final_model)
    generated_ros2_control = child(final_model, "ros2_control")
    if normalized_xml(child(urdf_root, "ros2_control")) != normalized_xml(generated_ros2_control):
        raise ValueError("generated SDF ros2_control contract differs from the controlled URDF")

    write_xml(output_sdf, final_root, declaration=True)
    data = {
        "status": "M1A_SDF_SPAWN_MANIFEST_VERIFIED",
        "mode": args.mode,
        "generator": str(Path(__file__).resolve()),
        "hashes": {
            "source_urdf_sha256": source_sha,
            "prepared_urdf_sha256": sha256(output_urdf),
            "generated_sdf_sha256": sha256(output_sdf),
            "generator_sha256": sha256(Path(__file__).resolve()),
            **({"scene_supervision_sha256": sha256(scene_supervision)} if scene_supervision else {}),
        },
        "outputs": {"urdf": str(output_urdf), "sdf": str(output_sdf)},
        "whitelist_diff": {
            "verified": True,
            "only_delta": {
                "path": f"model/joint[{MIMIC_FOLLOWER}]/axis/mimic",
                "joint": MIMIC_MASTER,
                "axis": "axis",
                "multiplier": BULLET_SDF_MIMIC_MULTIPLIER,
                "semantic_multiplier": SEMANTIC_MIMIC_MULTIPLIER,
                "offset": 0.0,
                "reference": 0.0,
            },
        },
        "per_object_detachables": {"count": len(beta_objects), "objects": beta_objects} if args.mode == "beta" else None,
        "mechanical_equivalence": {
            "joint_limits_and_units": joint_evidence,
            "zero_pose_transforms": transform_evidence,
            "collision_geometry_and_transforms": collision_evidence,
            "sensors": sensor_evidence,
            "plugins": plugin_evidence,
            "ros2_control_contract": ros2_control_evidence,
            "mimic_contract": mimic_evidence,
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


def arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf", required=True)
    parser.add_argument("--package-share", required=True)
    parser.add_argument("--mode", choices=("production", "calibration", "beta"), required=True)
    parser.add_argument("--scene-supervision")
    parser.add_argument("--output-sdf", required=True)
    parser.add_argument("--output-urdf", required=True)
    parser.add_argument("--manifest", required=True)
    return parser


def main() -> int:
    try:
        data = generate(arguments().parse_args())
    except (ET.ParseError, OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"status": "M1A_SDF_SPAWN_MANIFEST_BLOCKED", "reason": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": data["status"], "hashes": data["hashes"], "manifest": "written"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
