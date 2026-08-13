from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[2]
REQUEST = ROOT / "docs/decisions/M2C-S4-A3-CONTINUOUS-SELF-COLLISION-ADR-REQUEST.md"
URDF = ROOT / "robot_ws/src/xh_sim/urdf/panda_controlled.urdf"
REQUEST_SHA256 = "7f0dc91d250d75b69095bed651328d6c3ba5a923b803a5ae8b56ff30c2fb977c"
URDF_SHA256 = "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8"


def _text() -> str:
    return REQUEST.read_text(encoding="utf-8")


def _evidence() -> dict[str, object]:
    blocks = re.findall(r"```json\n(.*?)\n```", _text(), re.DOTALL)
    assert len(blocks) == 1
    payload = json.loads(blocks[0])
    assert isinstance(payload, dict)
    return payload


def test_entire_request_bytes_and_local_urdf_are_frozen() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", REQUEST_SHA256)
    assert hashlib.sha256(REQUEST.read_bytes()).hexdigest() == REQUEST_SHA256
    assert hashlib.sha256(URDF.read_bytes()).hexdigest() == URDF_SHA256


def test_post_implementation_audit_is_not_authorization() -> None:
    text = _text()
    payload = _evidence()

    assert "POST-IMPLEMENTATION-AUDIT / NOT APPROVED" in text
    assert "REQUEST FOR HUMAN DECISION; NOT AN APPROVED ADR" in text
    assert "Decision recorded by this request: **NONE**" in text
    assert payload["timing"] == "POST_IMPLEMENTATION_AUDIT"
    assert payload["approved_adr"] is False
    assert payload["selected_option"] is None
    assert payload["authorization"] == {
        "code_change": False,
        "geometry_replacement": False,
        "binding_addendum": False,
        "source_binding": False,
        "deployment": False,
        "collection": False,
        "training": False,
        "smoke": False,
        "model_rollout": False,
        "q_b_evaluation": False,
        "physical_execution": False,
        "reinterpret_existing_evidence": False,
    }
    for boundary in (
        "Does this request authorize code or geometry replacement?: **NO**",
        "Does this request set any S4 source-level binding?: **NO**",
        "BLOCKED / NOT APPROVED / NO_PHYSICAL_EXECUTION",
        "all\nfour `None` bindings remain unchanged",
    ):
        assert boundary in text


def test_robot_mesh_and_bullet_bytes_are_exactly_bound() -> None:
    payload = _evidence()
    assert payload["robot_asset"] == {
        "relative_path": "robot_ws/src/xh_sim/urdf/panda_controlled.urdf",
        "sha256": URDF_SHA256,
        "collision_element_count": 14,
        "box_count": 11,
        "cylinder_count": 1,
        "mesh_count": 2,
    }

    meshes = {item["path"]: item for item in payload["mesh_assets"]}
    assert set(meshes) == {
        "/opt/ros/jazzy/share/moveit_resources_panda_description/meshes/collision/link2.stl",
        "/opt/ros/jazzy/share/moveit_resources_panda_description/meshes/collision/link4.stl",
    }
    assert meshes[next(path for path in meshes if path.endswith("link2.stl"))] == {
        "host": "node2",
        "path": (
            "/opt/ros/jazzy/share/moveit_resources_panda_description/meshes/collision/link2.stl"
        ),
        "sha256": "370f7605a0fae3529db169ded50f52f171024aa792d4d773bc84197301f6a039",
        "size_bytes": 15084,
        "mode_octal": "0644",
        "nlink": 1,
        "triangle_count": 300,
        "unique_vertex_count": 152,
        "convex_hull_vertex_count": 152,
        "convex_hull_facet_count": 300,
        "closed_mesh_edge_incidence_values": [2],
        "non_supporting_triangle_face_count": 39,
        "max_two_sided_triangle_plane_distance_m": 0.0004687523208006362,
        "convex_hull_volume_m3": 0.00300430300848,
        "oriented_mesh_volume_m3": 0.00300425409289,
        "convex_hull_minus_mesh_volume_m3": 4.891558626120979e-08,
        "relative_convex_hull_volume_increase": 1.628184178592562e-05,
        "strictly_convex_under_audit": False,
    }
    assert meshes[next(path for path in meshes if path.endswith("link4.stl"))] == {
        "host": "node2",
        "path": (
            "/opt/ros/jazzy/share/moveit_resources_panda_description/meshes/collision/link4.stl"
        ),
        "sha256": "0180ebb5772ec9840cb049750cffb29a9ddc90311752a16ea34757782ef9e48d",
        "size_bytes": 15084,
        "mode_octal": "0644",
        "nlink": 1,
        "triangle_count": 300,
        "unique_vertex_count": 152,
        "convex_hull_vertex_count": 152,
        "convex_hull_facet_count": 300,
        "closed_mesh_edge_incidence_values": [2],
        "non_supporting_triangle_face_count": 29,
        "max_two_sided_triangle_plane_distance_m": 0.000464047136033791,
        "convex_hull_volume_m3": 0.00237399354433,
        "oriented_mesh_volume_m3": 0.00237380691791,
        "convex_hull_minus_mesh_volume_m3": 1.8662641138337752e-07,
        "relative_convex_hull_volume_increase": 7.861285546861829e-05,
        "strictly_convex_under_audit": False,
    }

    bindings = {item["path"]: item["sha256"] for item in payload["byte_bindings"]}
    expected = {
        "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btConvexCast.h": (
            "5eca7f5931c6f954dc4d8b58ff75ec58112c46f96783b1c8de5a117c663a6c6b"
        ),
        "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btContinuousConvexCollision.h": (
            "7ba73189495d70659b257899352f3688585d8bff536db11f8c86cfa6931fe2e4"
        ),
        "/usr/include/bullet/LinearMath/btTransformUtil.h": (
            "add9774d16afa59c5cf0529df82133712cad28411e952b9c4cc00ffa8bfa37ee"
        ),
        "/usr/lib/x86_64-linux-gnu/libBulletCollision.so.3.24": (
            "a356d9ef207a31737b91a39c4c75a43b05a49cde51891cfa13b4b1c71c223f0a"
        ),
        "/usr/lib/x86_64-linux-gnu/libLinearMath.so.3.24": (
            "31c7e0d2d17efc3924613bf561a645a4258f2d8df54167c162c490ed7fe84fea"
        ),
        "/usr/lib/x86_64-linux-gnu/libBulletCollision-float64.so.3.24": (
            "baa16598bc6a54aa51c825af6680807b548decb33ff11f469ac24c09f54826c2"
        ),
        "/opt/ros/jazzy/lib/libmoveit_collision_detection_bullet.so.2.12.4": (
            "4b3a6d8673e59b4c2c68189b1e649d3fb6c3412d6689e3eebdbf5c955e303106"
        ),
    }
    for path, digest in expected.items():
        assert bindings[path] == digest
    assert len(bindings) == 20


def test_options_are_exactly_exclusive_and_b_is_recommended() -> None:
    text = _text()
    payload = _evidence()
    headings = re.findall(r"^### ([A-Z]) — (.+)$", text, re.MULTILINE)

    assert [letter for letter, _ in headings] == ["A", "B", "C"]
    assert headings == [
        (
            "A",
            "authorize a conservative convex-hull envelope and bounded pairwise Bullet CCD",
        ),
        (
            "B",
            "require exact original-geometry continuous self-collision and remain blocked (recommended)",
        ),
        ("C", "require another complete human-specified A.3 contract"),
    ]
    assert payload["recommendation"] == "B"
    assert "The approver must select exactly one of A, B, or C" in text
    assert "Selected option: `NONE` (`A | B | C`, exactly one required)" in text


def test_option_a_has_no_guessed_numeric_authority() -> None:
    text = _text()
    option_a = text.split("### A —", 1)[1].split("### B —", 1)[0]

    assert option_a.count("`UNSET_HUMAN_REQUIRED`") >= 17
    assert "does **not** recommend A" in option_a
    assert "must not\nbe relabelled as one" in text
    assert "does not authorize a default, library constant, measured guess" in text
    for required in (
        "convex-hull construction tolerance (m)",
        "collision shape margin per shape type (m)",
        "allowed penetration (m)",
        "maximum CCD iterations",
        "CCD convergence epsilon",
        "per-arm-joint subdivision limit (rad)",
        "maximum link translation chord error (m)",
        "maximum link rotation interpolation error (rad)",
        "conservative error inflation applied to each child (m)",
        "non-finite, iteration-exhaustion, degeneracy and initial-overlap semantics",
    ):
        assert required in option_a


def test_teacher_truth_b0_and_old_evidence_boundaries_are_preserved() -> None:
    text = _text()
    for boundary in (
        "does not modify, weaken, wrap, or reinterpret B0",
        "Teacher labels, Teacher soft outputs, and Teacher runtime components are\n  forbidden",
        "Privileged simulator entity/prim identity, perfect pose, collision truth",
        "may not\n  become policy input",
        "Old S2 V4, B0, scripted, SMOKE, model, or Q-B evidence retains its original\n  meaning",
        "Nothing in this request may relabel old evidence",
        "No fixture, mock, discrete-only check, endpoint-only check",
    ):
        assert boundary in text
