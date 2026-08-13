from __future__ import annotations

import hashlib
import math
from pathlib import Path
import shutil

import pytest

from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    build_controlled_panda_geometry_v1,
    build_self_collision_world_from_fk_v1,
    produce_read_only_fk_receipt_v1,
)
from xh_agent.policy.qrm_lite.controlled_panda_fk_v1 import (
    CONTROLLED_PANDA_URDF_PATH,
    CONTROLLED_PANDA_URDF_SHA256,
    EXECUTOR_JOINT_NAMES,
    EXPECTED_LINK_PATHS,
    IMPLEMENTATION_REPO_PATH,
    ControlledPandaFKUnavailable,
    ControlledPandaReadOnlyFKProviderV1,
    expand_controlled_panda_executor_states_v1,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOME_STATE = (0.0, -0.5, 0.0, -1.5, 0.0, 1.0, 0.0, 0.02, 0.02)


def _provider() -> ControlledPandaReadOnlyFKProviderV1:
    return ControlledPandaReadOnlyFKProviderV1(project_root=PROJECT_ROOT)


def test_provider_binds_exact_source_urdf_topology_and_query_only_contract() -> None:
    provider = _provider()

    assert provider.query_only is True
    assert provider.real_runtime_provider is True
    assert provider.implementation_path == str(PROJECT_ROOT / IMPLEMENTATION_REPO_PATH)
    assert (
        provider.implementation_sha256
        == hashlib.sha256((PROJECT_ROOT / IMPLEMENTATION_REPO_PATH).read_bytes()).hexdigest()
    )
    assert len(provider.configuration_sha256) == 64
    assert hashlib.sha256((PROJECT_ROOT / CONTROLLED_PANDA_URDF_PATH).read_bytes()).hexdigest() == (
        CONTROLLED_PANDA_URDF_SHA256
    )


def test_fk_covers_every_collision_link_and_keeps_world_base_and_mimic_geometry() -> None:
    provider = _provider()
    second = (0.2, -0.7, 0.1, -1.7, 0.3, 1.2, -0.4, 0.03, 0.03)

    output = provider.query_link_transforms(
        joint_names=EXECUTOR_JOINT_NAMES,
        joint_state_sequence=(HOME_STATE, second),
        link_paths=EXPECTED_LINK_PATHS,
    )

    assert tuple(output) == EXPECTED_LINK_PATHS
    assert all(len(sequence) == 2 for sequence in output.values())
    for transform in output["/World/Robot/panda_link0"]:
        assert transform.translation_world_m == (-0.35, 0.0, 0.45)
        assert transform.rotation_world_wxyz == (1.0, 0.0, 0.0, 0.0)
    left = output["/World/Robot/panda_leftfinger"]
    right = output["/World/Robot/panda_rightfinger"]
    for state_index in range(2):
        assert math.isclose(
            math.dist(
                left[state_index].translation_world_m,
                right[state_index].translation_world_m,
            ),
            2.0 * (HOME_STATE, second)[state_index][-1],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        assert math.isclose(
            sum(value * value for value in left[state_index].rotation_world_wxyz),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )


def test_preflight_arm_and_gripper_samples_expand_to_exact_nine_dof_states() -> None:
    arm_names = tuple(f"panda_joint{index}" for index in range(1, 8))
    expanded = expand_controlled_panda_executor_states_v1(
        arm_joint_names=arm_names,
        arm_joint_state_sequence=(HOME_STATE[:7], (0.1, -0.6, 0.2, -1.6, 0.1, 1.1, -0.1)),
        gripper_position_sequence_m=(0.02, 0.03),
    )

    assert expanded == (
        HOME_STATE,
        (0.1, -0.6, 0.2, -1.6, 0.1, 1.1, -0.1, 0.03, 0.03),
    )
    with pytest.raises(ControlledPandaFKUnavailable, match="arm/gripper state coverage"):
        expand_controlled_panda_executor_states_v1(
            arm_joint_names=arm_names,
            arm_joint_state_sequence=(HOME_STATE[:7], HOME_STATE[:7]),
            gripper_position_sequence_m=(0.02,),
        )


@pytest.mark.skipif(
    not Path("/Users/gl/tzb-m2c-evidence/m2c-phase2-a3-native-build-v3/meshes/link2.stl").is_file(),
    reason="external original STL evidence is absent",
)
def test_real_provider_receipt_builds_complete_query_only_collision_world() -> None:
    evidence = Path("/Users/gl/tzb-m2c-evidence/m2c-phase2-a3-native-build-v3")
    states = (
        HOME_STATE,
        (0.1, -0.6, 0.2, -1.6, 0.1, 1.1, -0.1, 0.03, 0.03),
    )
    geometry = build_controlled_panda_geometry_v1(
        project_root=PROJECT_ROOT,
        link2_stl_path=evidence / "meshes/link2.stl",
        link4_stl_path=evidence / "meshes/link4.stl",
    )
    receipt = produce_read_only_fk_receipt_v1(
        bound_plan_sha256="b" * 64,
        geometry=geometry,
        joint_names=EXECUTOR_JOINT_NAMES,
        joint_state_sequence=states,
        provider=_provider(),
    )
    world = build_self_collision_world_from_fk_v1(
        geometry=geometry,
        fk_receipt=receipt,
        require_real_runtime_provider=True,
    )

    assert receipt.real_runtime_provider is True
    assert receipt.contract_test_only is False
    assert receipt.executor_state_count == 2
    assert len(receipt.link_sequences) == 12
    assert len(world.children) == 14
    assert len(world.transforms) == 14
    assert world.executor_state_count == 2
    assert geometry.formal_evidence is False
    assert receipt.formal_evidence is False


@pytest.mark.parametrize(
    ("joint_names", "states", "link_paths", "message"),
    (
        (
            tuple(reversed(EXECUTOR_JOINT_NAMES)),
            (HOME_STATE, HOME_STATE),
            EXPECTED_LINK_PATHS,
            "joint order",
        ),
        (
            EXECUTOR_JOINT_NAMES,
            (HOME_STATE[:-1] + (0.021,), HOME_STATE),
            EXPECTED_LINK_PATHS,
            "mimic relation",
        ),
        (
            EXECUTOR_JOINT_NAMES,
            ((3.0, *HOME_STATE[1:]), HOME_STATE),
            EXPECTED_LINK_PATHS,
            "exceeds limit",
        ),
        (
            EXECUTOR_JOINT_NAMES,
            (HOME_STATE,),
            EXPECTED_LINK_PATHS,
            "state coverage",
        ),
        (
            EXECUTOR_JOINT_NAMES,
            (HOME_STATE, HOME_STATE),
            EXPECTED_LINK_PATHS[:-1],
            "link-path coverage",
        ),
    ),
)
def test_provider_fails_closed_on_incomplete_or_inconsistent_executor_state(
    joint_names: tuple[str, ...],
    states: tuple[tuple[float, ...], ...],
    link_paths: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ControlledPandaFKUnavailable, match=message):
        _provider().query_link_transforms(
            joint_names=joint_names,
            joint_state_sequence=states,
            link_paths=link_paths,
        )


def test_provider_rejects_tampered_or_symlinked_robot_description(tmp_path: Path) -> None:
    implementation = tmp_path / IMPLEMENTATION_REPO_PATH
    urdf = tmp_path / CONTROLLED_PANDA_URDF_PATH
    implementation.parent.mkdir(parents=True)
    urdf.parent.mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / IMPLEMENTATION_REPO_PATH, implementation)
    shutil.copyfile(PROJECT_ROOT / CONTROLLED_PANDA_URDF_PATH, urdf)
    urdf.write_bytes(urdf.read_bytes().replace(b"panda_joint1", b"panda_jointX", 1))
    with pytest.raises(ControlledPandaFKUnavailable, match="URDF digest"):
        ControlledPandaReadOnlyFKProviderV1(project_root=tmp_path)

    urdf.unlink()
    urdf.symlink_to(PROJECT_ROOT / CONTROLLED_PANDA_URDF_PATH)
    with pytest.raises(OSError):
        ControlledPandaReadOnlyFKProviderV1(project_root=tmp_path)
