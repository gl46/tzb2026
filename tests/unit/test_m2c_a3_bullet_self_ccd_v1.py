from __future__ import annotations

import hashlib
import math
from pathlib import Path
import struct
from typing import Any

import pytest

from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    A3BulletNumericConfigurationV1,
    A3ChildPairCCDReceiptV1,
    A3ChildPairCCDResultV1,
    A3ConvexChildV1,
    A3LinkChildTransformSequenceV1,
    A3RigidTransformV1,
    A3SelfCollisionRejected,
    A3SelfCollisionWorldV1,
    BULLET_CONVEX_HULL_SHIPPED_MARGIN_M,
    CONTROLLED_PANDA_BOX_SHIPPED_MARGIN_MAX_M,
    CONTROLLED_PANDA_CYLINDER_SHIPPED_MARGIN_MAX_M,
    EXPECTED_BULLET_FLOAT64_COLLISION_SHA256,
    EXPECTED_BULLET_FLOAT64_LINEAR_MATH_SHA256,
    build_child_pair_ccd_request_v1,
    canonical_a3_bullet_numeric_configuration_v1,
    decode_binary_stl_vertices_v1,
    verify_child_pair_ccd_receipt_v1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import canonical_sha256


DIGEST = "a" * 64


def _rehash(model: Any, field: str):
    dumped = model.model_dump(mode="json")
    dumped[field] = canonical_sha256({key: value for key, value in dumped.items() if key != field})
    return type(model).model_validate(dumped)


def _transform(x: float) -> A3RigidTransformV1:
    return A3RigidTransformV1(
        translation_world_m=(x, 0.0, 0.0),
        rotation_world_wxyz=(1.0, 0.0, 0.0, 0.0),
    )


def _child(
    link: str,
    index: int,
    radius: float = 0.02,
    maximum_angular_motion_radius_m: float = 0.2,
) -> A3ConvexChildV1:
    model = A3ConvexChildV1.model_construct(
        link_path=link,
        child_index=index,
        shape_kind="BOX",
        local_transform=_transform(0.0),
        shape_parameters_sha256=DIGEST,
        source_asset_path="robot.urdf",
        source_asset_sha256=DIGEST,
        source_vertex_count=0,
        decoded_vertices_sha256=None,
        smallest_conservative_radius_m=radius,
        maximum_angular_motion_radius_m=maximum_angular_motion_radius_m,
        collision_margin_m=0.04,
        outward_padding_m=0.002,
        conservative_outer_envelope=True,
        geometry_equality_claimed=False,
        child_sha256="0" * 64,
    )
    return _rehash(model, "child_sha256")


def _world(*, distance: float = 0.05, acm: bool = False) -> A3SelfCollisionWorldV1:
    left = _child("/World/Robot/link_a", 0)
    right = _child("/World/Robot/link_b", 0)
    model = A3SelfCollisionWorldV1.model_construct(
        children=(left, right),
        transforms=(
            A3LinkChildTransformSequenceV1(
                link_path=left.link_path,
                child_index=0,
                transforms=(_transform(0.0), _transform(distance)),
            ),
            A3LinkChildTransformSequenceV1(
                link_path=right.link_path,
                child_index=0,
                transforms=(_transform(1.0), _transform(1.0)),
            ),
        ),
        acm_link_pairs=((left.link_path, right.link_path),) if acm else (),
        attached_object_paths=(),
        executor_state_count=2,
        world_sha256="0" * 64,
    )
    return _rehash(model, "world_sha256")


def _rotation_world(angle_rad: float) -> A3SelfCollisionWorldV1:
    left = _child("/World/Robot/link_a", 0, radius=0.02, maximum_angular_motion_radius_m=0.2)
    right = _child("/World/Robot/link_b", 0)
    rotation = A3RigidTransformV1(
        translation_world_m=(0.0, 0.0, 0.0),
        rotation_world_wxyz=(math.cos(angle_rad / 2.0), 0.0, 0.0, math.sin(angle_rad / 2.0)),
    )
    model = A3SelfCollisionWorldV1.model_construct(
        children=(left, right),
        transforms=(
            A3LinkChildTransformSequenceV1(
                link_path=left.link_path,
                child_index=0,
                transforms=(_transform(0.0), rotation),
            ),
            A3LinkChildTransformSequenceV1(
                link_path=right.link_path,
                child_index=0,
                transforms=(_transform(1.0), _transform(1.0)),
            ),
        ),
        acm_link_pairs=(),
        attached_object_paths=(),
        executor_state_count=2,
        world_sha256="0" * 64,
    )
    return _rehash(model, "world_sha256")


def _receipt(request, *, status: str = "CLEAR", real: bool = False, failure: int | None = None):
    results = tuple(
        A3ChildPairCCDResultV1(
            pair_index=index,
            status=status,
            discrete_start_clear=True,
            discrete_end_clear=True,
            continuous_query_completed=status == "CLEAR",
            time_of_impact=0.5 if status == "REJECT_COLLISION" else None,
            failure_code=failure,
            iteration_count=4,
        )
        for index in range(len(request.segments))
    )
    model = A3ChildPairCCDReceiptV1.model_construct(
        request_sha256=request.request_sha256,
        backend_implementation_sha256=DIGEST,
        bullet_collision_library_sha256=EXPECTED_BULLET_FLOAT64_COLLISION_SHA256,
        bullet_linear_math_library_sha256=EXPECTED_BULLET_FLOAT64_LINEAR_MATH_SHA256,
        scalar_abi="float64",
        results=results,
        status="PASS" if status == "CLEAR" else "REJECT",
        real_native_backend=real,
        contract_test_only=not real,
        formal_evidence=False,
        query_only=True,
        articulation_target_writes=0,
        simulation_steps=0,
        scene_mutations=0,
        teacher_used=False,
        privileged_truth_policy_input=False,
        receipt_sha256="0" * 64,
    )
    return _rehash(model, "receipt_sha256")


def _binary_stl(vertices: tuple[tuple[float, float, float], ...]) -> bytes:
    assert len(vertices) == 3
    return (
        b"fixture".ljust(80, b"\0")
        + struct.pack("<I", 1)
        + struct.pack("<12fH", 0.0, 0.0, 1.0, *vertices[0], *vertices[1], *vertices[2], 0)
    )


def test_numeric_configuration_is_within_every_adr0024_bound() -> None:
    config = canonical_a3_bullet_numeric_configuration_v1()

    assert config.scalar_abi == "float64"
    assert config.convex_hull_construction_tolerance_m <= 1e-6
    assert config.convex_hull_outward_padding_m >= 0.002
    assert config.box_collision_margin_m == CONTROLLED_PANDA_BOX_SHIPPED_MARGIN_MAX_M
    assert config.cylinder_collision_margin_m == CONTROLLED_PANDA_CYLINDER_SHIPPED_MARGIN_MAX_M
    assert config.convex_hull_collision_margin_m == BULLET_CONVEX_HULL_SHIPPED_MARGIN_M
    assert config.allowed_penetration_m == 0.0
    assert config.contact_distance_threshold_m >= 0.001
    assert config.toi_comparison_tolerance <= 1e-6
    assert config.maximum_ccd_iterations >= 32
    assert config.iteration_exhaustion_rejects
    assert len(config.provenance) == 15


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("convex_hull_construction_tolerance_m", 2e-6),
        ("convex_hull_outward_padding_m", 0.001),
        ("allowed_penetration_m", 0.001),
        ("contact_distance_threshold_m", 0.0009),
        ("toi_comparison_tolerance", 2e-6),
        ("maximum_ccd_iterations", 31),
        ("box_collision_margin_m", CONTROLLED_PANDA_BOX_SHIPPED_MARGIN_MAX_M - 1e-9),
        (
            "cylinder_collision_margin_m",
            CONTROLLED_PANDA_CYLINDER_SHIPPED_MARGIN_MAX_M - 1e-9,
        ),
        ("convex_hull_collision_margin_m", BULLET_CONVEX_HULL_SHIPPED_MARGIN_M - 1e-9),
    ],
)
def test_out_of_bound_numeric_value_is_rejected(field: str, value: object) -> None:
    dumped = canonical_a3_bullet_numeric_configuration_v1().model_dump(mode="json")
    dumped[field] = value
    dumped["configuration_sha256"] = canonical_sha256(
        {key: item for key, item in dumped.items() if key != "configuration_sha256"}
    )
    with pytest.raises(ValueError):
        A3BulletNumericConfigurationV1.model_validate(dumped)


def test_strict_binary_stl_decode_rejects_tamper_nan_and_degenerate(tmp_path: Path) -> None:
    valid = tmp_path / "valid.stl"
    # Two triangles give four unique vertices.
    raw = b"fixture".ljust(80, b"\0") + struct.pack("<I", 2)
    raw += struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0)
    raw += struct.pack("<12fH", 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0)
    valid.write_bytes(raw)
    vertices, digest = decode_binary_stl_vertices_v1(
        valid, expected_sha256=hashlib.sha256(raw).hexdigest()
    )
    assert len(vertices) == 4
    assert digest == canonical_sha256(vertices)
    with pytest.raises(A3SelfCollisionRejected, match="SHA-256"):
        decode_binary_stl_vertices_v1(valid, expected_sha256="0" * 64)

    nan_path = tmp_path / "nan.stl"
    nan_raw = _binary_stl(((math.nan, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
    nan_path.write_bytes(nan_raw)
    with pytest.raises(A3SelfCollisionRejected, match="NaN/Inf"):
        decode_binary_stl_vertices_v1(nan_path, expected_sha256=hashlib.sha256(nan_raw).hexdigest())

    degenerate = tmp_path / "degenerate.stl"
    degenerate_raw = _binary_stl(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
    degenerate.write_bytes(degenerate_raw)
    with pytest.raises(A3SelfCollisionRejected, match="fewer than four"):
        decode_binary_stl_vertices_v1(
            degenerate, expected_sha256=hashlib.sha256(degenerate_raw).hexdigest()
        )


def test_request_expands_non_acm_pair_and_subdivides_above_radius() -> None:
    config = canonical_a3_bullet_numeric_configuration_v1()
    world = _world(distance=0.05)

    request = build_child_pair_ccd_request_v1(
        bound_plan_sha256="b" * 64,
        world=world,
        configuration=config,
    )

    assert request.expected_non_acm_child_pair_count == 1
    assert request.expected_executor_segment_count == 1
    assert len(request.segments) == 3  # ceil(0.05 / 0.02)
    assert [item.subdivision_index for item in request.segments] == [0, 1, 2]
    assert all(item.discrete_check_at_start_required for item in request.segments)


def test_rotation_subdivision_uses_maximum_angular_motion_radius() -> None:
    request = build_child_pair_ccd_request_v1(
        bound_plan_sha256="b" * 64,
        world=_rotation_world(math.pi / 2.0),
        configuration=canonical_a3_bullet_numeric_configuration_v1(),
    )

    # ceil((pi/2 * 0.2 m maximum angular-motion radius) / 0.02 m inner radius)
    assert len(request.segments) == 16
    assert {item.subdivision_count for item in request.segments} == {16}


def test_child_rejects_maximum_angular_radius_smaller_than_inner_radius() -> None:
    with pytest.raises(ValueError, match="maximum angular-motion radius"):
        _child(
            "/World/Robot/link_a",
            0,
            radius=0.2,
            maximum_angular_motion_radius_m=0.02,
        )


def test_native_source_never_treats_ambiguous_false_as_clear() -> None:
    source = (
        Path(__file__).parents[2] / "src/xh_agent/policy/qrm_lite/a3_bullet_self_ccd_v1.cpp"
    ).read_text(encoding="utf-8")

    assert "conservative_no_contact_certificate" in source
    assert "*failure_code = -100" in source
    false_branch = source.split("if (hit)", 1)[1]
    assert false_branch.index("conservative_no_contact_certificate") < false_branch.rindex(
        "return 0;"
    )


def test_acm_eliminating_every_pair_rejects_whole_request() -> None:
    with pytest.raises(A3SelfCollisionRejected, match="no non-ACM"):
        build_child_pair_ccd_request_v1(
            bound_plan_sha256="b" * 64,
            world=_world(acm=True),
            configuration=canonical_a3_bullet_numeric_configuration_v1(),
        )


def test_contract_receipt_never_satisfies_real_native_requirement() -> None:
    config = canonical_a3_bullet_numeric_configuration_v1()
    request = build_child_pair_ccd_request_v1(
        bound_plan_sha256="b" * 64,
        world=_world(),
        configuration=config,
    )
    receipt = _receipt(request)

    assert (
        verify_child_pair_ccd_receipt_v1(
            request,
            receipt,
            configuration=config,
            require_real_native_backend=False,
        )
        == receipt
    )
    with pytest.raises(A3SelfCollisionRejected, match="native float64"):
        verify_child_pair_ccd_receipt_v1(
            request,
            receipt,
            configuration=config,
            require_real_native_backend=True,
        )


def test_any_collision_or_query_failure_rejects_whole_request() -> None:
    config = canonical_a3_bullet_numeric_configuration_v1()
    request = build_child_pair_ccd_request_v1(
        bound_plan_sha256="b" * 64,
        world=_world(),
        configuration=config,
    )
    collision = _receipt(request, status="REJECT_COLLISION")
    with pytest.raises(A3SelfCollisionRejected, match="collided or query failed"):
        verify_child_pair_ccd_receipt_v1(
            request,
            collision,
            configuration=config,
            require_real_native_backend=False,
        )
    failure = _receipt(request, status="REJECT_QUERY_FAILURE", failure=-2)
    with pytest.raises(A3SelfCollisionRejected, match="collided or query failed"):
        verify_child_pair_ccd_receipt_v1(
            request,
            failure,
            configuration=config,
            require_real_native_backend=False,
        )


def test_receipt_tamper_is_rejected() -> None:
    config = canonical_a3_bullet_numeric_configuration_v1()
    request = build_child_pair_ccd_request_v1(
        bound_plan_sha256="b" * 64,
        world=_world(),
        configuration=config,
    )
    dumped = _receipt(request).model_dump(mode="json")
    dumped["results"][0]["discrete_start_clear"] = False
    with pytest.raises(ValueError):
        A3ChildPairCCDReceiptV1.model_validate(dumped)
