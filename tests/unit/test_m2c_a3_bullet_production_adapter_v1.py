from __future__ import annotations

import hashlib
from pathlib import Path
import struct
from typing import Any

import pytest

from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    A3BulletFloat64BuildManifestV1,
    A3AttachedObjectGeometryV1,
    A3ControlledPandaGeometryReceiptV1,
    A3FileBindingV1,
    A3ProductionClosureUnavailable,
    A3ReadOnlyFKProviderV1,
    A3RigidTransformV1,
    A3ShapePayloadV1,
    CANONICAL_BUILD_FLAGS,
    CONTROLLED_PANDA_URDF_PATH,
    CONTROLLED_PANDA_URDF_SHA256,
    EXPECTED_AUDITED_BULLET_HEADERS,
    FLOAT64_COLLISION_LIBRARY_PATH,
    FLOAT64_LINEAR_MATH_LIBRARY_PATH,
    LINK2_STL_PATH,
    LINK2_STL_SHA256,
    LINK4_STL_PATH,
    LINK4_STL_SHA256,
    NATIVE_ADAPTER_PATH,
    NATIVE_CORE_PATH,
    build_controlled_panda_geometry_v1,
    build_self_collision_world_from_fk_v1,
    inspect_a3_production_closure_v1,
    produce_read_only_fk_receipt_v1,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    EXPECTED_BULLET_FLOAT64_COLLISION_SHA256,
    EXPECTED_BULLET_FLOAT64_LINEAR_MATH_SHA256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIGEST = "a" * 64


def _rehash(model: Any, field: str):
    dumped = model.model_dump(mode="json")
    dumped[field] = canonical_sha256({key: value for key, value in dumped.items() if key != field})
    return type(model).model_validate(dumped)


def _binding(path: str, sha256: str = DIGEST) -> A3FileBindingV1:
    return A3FileBindingV1(path=path, sha256=sha256)


def _manifest() -> A3BulletFloat64BuildManifestV1:
    model = A3BulletFloat64BuildManifestV1.model_construct(
        bullet_package_version="3.24+dfsg-2.1build1",
        scalar_abi="float64",
        compiler=_binding("/usr/bin/x86_64-linux-gnu-g++-13"),
        compiler_version="Ubuntu 13.3.0-6ubuntu2~24.04",
        build_flags=CANONICAL_BUILD_FLAGS,
        native_core=_binding(NATIVE_CORE_PATH),
        native_adapter=_binding(NATIVE_ADAPTER_PATH),
        audited_bullet_headers=tuple(
            _binding(path, digest) for path, digest in EXPECTED_AUDITED_BULLET_HEADERS.items()
        ),
        complete_transitive_compile_manifest=_binding("artifacts/a3/compiler.inputs.json"),
        bullet_collision_library=_binding(
            FLOAT64_COLLISION_LIBRARY_PATH,
            EXPECTED_BULLET_FLOAT64_COLLISION_SHA256,
        ),
        bullet_linear_math_library=_binding(
            FLOAT64_LINEAR_MATH_LIBRARY_PATH,
            EXPECTED_BULLET_FLOAT64_LINEAR_MATH_SHA256,
        ),
        native_shared_object=_binding("artifacts/a3/libm2c_a3_bullet_float64.so"),
        immutable_build_container_digest="sha256:" + "b" * 64,
        absolute_float64_rpath_only=True,
        no_fast_math=True,
        build_manifest_sha256="0" * 64,
    )
    return _rehash(model, "build_manifest_sha256")


def _payload(link: str, child_index: int) -> A3ShapePayloadV1:
    data = {
        "schema_version": "A3ShapePayloadV1",
        "link_path": link,
        "child_index": child_index,
        "shape_kind": "BOX",
        "shape_parameters": (0.1, 0.1, 0.1),
        "decoded_vertices_xyz_m": (),
        "hull_construction_tolerance_m": 1e-7,
        "outward_padding_m": 0.002,
        "collision_margin_m": 0.04,
        "every_decoded_stl_vertex_retained": False,
        "conservative_outer_envelope": True,
        "geometry_equality_claimed": False,
    }
    return A3ShapePayloadV1(**data, payload_sha256=canonical_sha256(data))


def _binary_stl() -> bytes:
    triangles = (
        ((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0)),
        ((0.0, 0.0, 0.0), (0.0, 0.1, 0.0), (0.0, 0.0, 0.1)),
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.1), (0.1, 0.0, 0.0)),
        ((0.1, 0.0, 0.0), (0.0, 0.0, 0.1), (0.0, 0.1, 0.0)),
    )
    raw = b"contract".ljust(80, b"\0") + struct.pack("<I", len(triangles))
    for triangle in triangles:
        flat = tuple(value for vertex in triangle for value in vertex)
        raw += struct.pack("<12fH", 0.0, 0.0, 1.0, *flat, 0)
    return raw


def test_build_manifest_pins_float64_libraries_headers_and_flags() -> None:
    manifest = _manifest()

    assert manifest.scalar_abi == "float64"
    assert "-DBT_USE_DOUBLE_PRECISION" in manifest.build_flags
    assert "-fno-fast-math" in manifest.build_flags
    assert manifest.bullet_collision_library.sha256 == (EXPECTED_BULLET_FLOAT64_COLLISION_SHA256)

    dumped = manifest.model_dump(mode="json")
    dumped["build_flags"][-1] = "-ffast-math"
    dumped["build_manifest_sha256"] = canonical_sha256(
        {key: value for key, value in dumped.items() if key != "build_manifest_sha256"}
    )
    with pytest.raises(ValueError, match="build flags"):
        A3BulletFloat64BuildManifestV1.model_validate(dumped)


def test_shape_payload_retains_every_hull_vertex_and_rejects_omission() -> None:
    vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    data = {
        "schema_version": "A3ShapePayloadV1",
        "link_path": "/World/Robot/link2",
        "child_index": 0,
        "shape_kind": "CONVEX_HULL",
        "shape_parameters": (1.0,),
        "decoded_vertices_xyz_m": vertices,
        "hull_construction_tolerance_m": 1e-7,
        "outward_padding_m": 0.002,
        "collision_margin_m": 0.04,
        "every_decoded_stl_vertex_retained": True,
        "conservative_outer_envelope": True,
        "geometry_equality_claimed": False,
    }
    payload = A3ShapePayloadV1(**data, payload_sha256=canonical_sha256(data))
    assert payload.decoded_vertices_xyz_m == vertices

    tampered = payload.model_dump(mode="json")
    tampered["every_decoded_stl_vertex_retained"] = False
    tampered["payload_sha256"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "payload_sha256"}
    )
    with pytest.raises(ValueError, match="omitted"):
        A3ShapePayloadV1.model_validate(tampered)


def test_controlled_panda_parser_rejects_mesh_hash_before_geometry_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The local repository intentionally lacks the two production STL assets.
    # Copying contract bytes to their path must not let them masquerade as the
    # byte-bound originals.
    link2, link4 = tmp_path / "link2.stl", tmp_path / "link4.stl"
    link2.write_bytes(_binary_stl())
    link4.write_bytes(_binary_stl())

    with pytest.raises(A3ProductionClosureUnavailable, match="byte binding differs"):
        build_controlled_panda_geometry_v1(
            project_root=PROJECT_ROOT,
            link2_stl_path=link2,
            link4_stl_path=link4,
            contract_test_only=True,
        )


def _contract_geometry() -> A3ControlledPandaGeometryReceiptV1:
    payloads = tuple(_payload(f"/World/Robot/link{index}", 0) for index in range(14))
    children = []
    from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import A3ConvexChildV1

    identity = A3RigidTransformV1(
        translation_world_m=(0.0, 0.0, 0.0),
        rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
    )
    for payload in payloads:
        data = {
            "schema_version": "A3ConvexChildV1",
            "link_path": payload.link_path,
            "child_index": 0,
            "shape_kind": "BOX",
            "local_transform": identity.model_dump(mode="json"),
            "shape_parameters_sha256": payload.payload_sha256,
            "source_asset_path": "contract.urdf",
            "source_asset_sha256": DIGEST,
            "source_vertex_count": 0,
            "decoded_vertices_sha256": None,
            "smallest_conservative_radius_m": 0.05,
            "maximum_angular_motion_radius_m": 0.13,
            "collision_margin_m": 0.04,
            "outward_padding_m": 0.002,
            "conservative_outer_envelope": True,
            "geometry_equality_claimed": False,
        }
        children.append(A3ConvexChildV1(**data, child_sha256=canonical_sha256(data)))
    ordered = sorted(zip(children, payloads), key=lambda item: item[0].link_path)
    data = {
        "schema_version": "A3ControlledPandaGeometryReceiptV1",
        "robot_description": _binding(
            CONTROLLED_PANDA_URDF_PATH, CONTROLLED_PANDA_URDF_SHA256
        ).model_dump(mode="json"),
        "semantic_collision_matrix": _binding("contract.srdf").model_dump(mode="json"),
        "mesh_bindings": (
            _binding(LINK2_STL_PATH, LINK2_STL_SHA256).model_dump(mode="json"),
            _binding(LINK4_STL_PATH, LINK4_STL_SHA256).model_dump(mode="json"),
        ),
        "children": [item[0].model_dump(mode="json") for item in ordered],
        "shape_payloads": [item[1].model_dump(mode="json") for item in ordered],
        "acm_link_pairs": (),
        "expected_collision_child_count": 14,
        "all_compounds_expanded": True,
        "unknown_or_concave_shape_rejects": True,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
        "contract_test_only": True,
        "formal_evidence": False,
    }
    return A3ControlledPandaGeometryReceiptV1(**data, receipt_sha256=canonical_sha256(data))


class _FK(A3ReadOnlyFKProviderV1):
    def __init__(self, path: Path, *, omit: bool = False) -> None:
        self.implementation_path = str(path)
        self.implementation_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        self.configuration_sha256 = DIGEST
        self.real_runtime_provider = False
        self.query_only = True
        self.omit = omit

    def query_link_transforms(self, *, joint_names, joint_state_sequence, link_paths):
        identity = A3RigidTransformV1(
            translation_world_m=(0.0, 0.0, 0.0),
            rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
        )
        result = {path: (identity,) * len(joint_state_sequence) for path in link_paths}
        if self.omit:
            result.pop(next(iter(result)))
        return result


def test_fk_receipt_cross_binds_all_links_states_and_contract_never_becomes_real(
    tmp_path: Path,
) -> None:
    provider_path = tmp_path / "fk.py"
    provider_path.write_text("# query-only fixture\n")
    geometry = _contract_geometry()
    receipt = produce_read_only_fk_receipt_v1(
        bound_plan_sha256="b" * 64,
        geometry=geometry,
        joint_names=("joint1",),
        joint_state_sequence=((0.0,), (0.1,)),
        provider=_FK(provider_path),
    )
    world = build_self_collision_world_from_fk_v1(
        geometry=geometry,
        fk_receipt=receipt,
        require_real_runtime_provider=False,
    )
    assert len(world.children) == 14
    assert world.executor_state_count == 2
    with pytest.raises(A3ProductionClosureUnavailable, match="production binding"):
        build_self_collision_world_from_fk_v1(
            geometry=geometry,
            fk_receipt=receipt,
            require_real_runtime_provider=True,
        )
    with pytest.raises(A3ProductionClosureUnavailable, match="link coverage"):
        produce_read_only_fk_receipt_v1(
            bound_plan_sha256="b" * 64,
            geometry=geometry,
            joint_names=("joint1",),
            joint_state_sequence=((0.0,), (0.1,)),
            provider=_FK(provider_path, omit=True),
        )


def test_attached_object_requires_complete_children_transforms_and_touch_allowlist() -> None:
    payload = _payload("/World/M1B/object", 0)
    from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
        A3ConvexChildV1,
        A3LinkChildTransformSequenceV1,
    )

    identity = A3RigidTransformV1(
        translation_world_m=(0.0, 0.0, 0.0),
        rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
    )
    child_data = {
        "schema_version": "A3ConvexChildV1",
        "link_path": payload.link_path,
        "child_index": 0,
        "shape_kind": "BOX",
        "local_transform": identity.model_dump(mode="json"),
        "shape_parameters_sha256": payload.payload_sha256,
        "source_asset_path": "attached-object.json",
        "source_asset_sha256": DIGEST,
        "source_vertex_count": 0,
        "decoded_vertices_sha256": None,
        "smallest_conservative_radius_m": 0.05,
        "maximum_angular_motion_radius_m": 0.13,
        "collision_margin_m": 0.04,
        "outward_padding_m": 0.002,
        "conservative_outer_envelope": True,
        "geometry_equality_claimed": False,
    }
    child = A3ConvexChildV1(**child_data, child_sha256=canonical_sha256(child_data))
    transform = A3LinkChildTransformSequenceV1(
        link_path=payload.link_path,
        child_index=0,
        transforms=(identity, identity),
    )
    data = {
        "schema_version": "A3AttachedObjectGeometryV1",
        "attached_object_path": payload.link_path,
        "attachment_receipt_sha256": DIGEST,
        "children": (child.model_dump(mode="json"),),
        "shape_payloads": (payload.model_dump(mode="json"),),
        "transforms": (transform.model_dump(mode="json"),),
        "allowed_touch_link_pairs": (
            tuple(sorted((payload.link_path, "/World/Robot/panda_leftfinger"))),
        ),
        "executor_state_count": 2,
        "complete_compound_expansion": True,
        "query_only": True,
        "articulation_target_writes": 0,
        "simulation_steps": 0,
        "scene_mutations": 0,
    }
    receipt = A3AttachedObjectGeometryV1(**data, receipt_sha256=canonical_sha256(data))
    assert receipt.children == (child,)

    tampered = receipt.model_dump(mode="json")
    tampered["allowed_touch_link_pairs"] = [
        ["/World/Robot/panda_leftfinger", "/World/Robot/panda_rightfinger"]
    ]
    tampered["receipt_sha256"] = canonical_sha256(
        {key: value for key, value in tampered.items() if key != "receipt_sha256"}
    )
    with pytest.raises(ValueError, match="touch allowlist"):
        A3AttachedObjectGeometryV1.model_validate(tampered)


def test_local_production_inspection_is_explicitly_not_available_and_non_actuating() -> None:
    receipt = inspect_a3_production_closure_v1(project_root=PROJECT_ROOT)

    assert receipt.status == "NOT_AVAILABLE"
    assert "PINNED_NATIVE_BUILD_MANIFEST_AND_SHARED_OBJECT" in receipt.missing_requirements
    assert "REAL_QUERY_ONLY_FK_PROVIDER_BINDING" in receipt.missing_requirements
    assert not receipt.real_isaac_started
    assert not receipt.physical_execution_performed
    assert not receipt.formal_execution_eligible


def test_native_sources_are_flat_float64_query_only_and_fail_closed() -> None:
    core = (PROJECT_ROOT / NATIVE_CORE_PATH).read_text(encoding="utf-8")
    adapter = (PROJECT_ROOT / NATIVE_ADAPTER_PATH).read_text(encoding="utf-8")

    assert '#error "ADR-0024 A.3 requires a Bullet float64 build"' in core
    assert "static_assert(sizeof(btScalar) == sizeof(double)" in adapter
    assert "hull_is_nondegenerate" in adapter
    assert "shipped_margin_for_shape" in adapter
    assert "collision_margin_m < shipped_margin" in adapter
    assert "vertex_count < 4" in adapter
    assert "m2c_a3_flat_child_pair_ccd_v1" in adapter
    assert "*failure_code = -200" in adapter
    forbidden = ("omni.", "SimulationContext", "set_joint", "apply_action", "step(")
    assert not any(token in core + adapter for token in forbidden)
