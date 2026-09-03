from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from m2c.build_formal_isaac_production_recipe_v4 import (
    FormalIsaacProductionSceneSelectionV1,
    _synthesis_configuration,
)
from xh_agent.policy.qrm_lite.a3_bullet_self_ccd_v1 import (
    canonical_a3_bullet_numeric_configuration_v1,
)
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    A3SceneCollisionGeometryReceiptV1,
    build_a3_scene_collision_geometry_v1,
    canonical_a3_scene_pose_source_configuration_sha256_v3,
)
from xh_agent.policy.qrm_lite.controlled_panda_fk_v1 import (
    ControlledPandaReadOnlyFKProviderV1,
)
from xh_agent.policy.qrm_lite.exact_plan_preflight_v1 import (
    ExactPlanPreflightConfigurationV1,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    canonical_json_bytes,
    canonical_sha256,
)


ROOT = Path(__file__).resolve().parents[2]
SELECTION = ROOT / "configs/m2c_formal_isaac_scene25514_selection_v1.json"
PREFLIGHT = ROOT / "configs/m2c_exact_plan_preflight_production_scene25514_v1.json"
SYNTHESIS = ROOT / "configs/m2c_exact_plan_synthesis_production_scene25514_v1.json"
ASSETS = Path("/Users/gl/tzb-m2c-evidence/m2c-s4-scene25514-prep-v1")
NATIVE_MANIFEST = Path(
    "/Users/gl/tzb-m2c-evidence/m2c-s4-scene25016-articulation-binding-v1/"
    "a3/output/a3-bullet-build-manifest.json"
)


def test_scene25514_selection_is_committed_canonical_and_outcome_blind() -> None:
    selection = FormalIsaacProductionSceneSelectionV1.model_validate_json(SELECTION.read_bytes())
    assert SELECTION.read_bytes() == (
        json.dumps(
            selection.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
        + b"\n"
    )
    assert selection.scene_seed == 25514
    assert selection.failure_seed == 255147
    assert selection.matched_key.endswith(
        "5b5cd22a6285fe79e70c03722e0a5d4960afcd26b732d741ad8966148f1cdec6"
    )
    assert selection.model_side_changed is False
    assert selection.teacher_used is False
    assert selection.privileged_truth_policy_input is False
    manifest = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "show",
            f"{selection.source_key_manifest_commit}:{selection.source_key_manifest_path}",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    assert hashlib.sha256(manifest).hexdigest() == selection.source_key_manifest_file_sha256
    payload = json.loads(manifest)
    assert payload["manifest_sha256"] == selection.source_key_manifest_content_sha256
    keys = payload["physical_prerequisite_smoke_keys"]
    assert len(keys) == 1
    assert keys[0]["matched_key"] == selection.matched_key


def test_scene25514_preflight_is_canonical_and_strict() -> None:
    raw = PREFLIGHT.read_bytes()
    data = json.loads(raw)
    assert raw == json.dumps(data, indent=2, sort_keys=True).encode() + b"\n"
    preflight = ExactPlanPreflightConfigurationV1.model_validate(data["preflight_configuration"])
    scene = data["scene_geometry"]
    assert preflight.configuration_sha256 == (
        "7c87ab20226cd99be5d4ca413c05b6a3792df2ba34d1e73a2b4f7999972162a6"
    )
    assert (
        preflight.swept_collision.collision_geometry_sha256
        == (scene["collision_geometry_binding_sha256"])
    )
    assert preflight.swept_collision.algorithm_sha256 == (scene["complete_scene_algorithm_sha256"])
    assert scene["stage_sha256"] == (
        "b78f6b15b96a6cbe257ec35bb6b2f1a87c74d2cf2f8697a90a0000d8dd6a78ca"
    )
    assert data["teacher_used"] is False
    assert data["privileged_truth_policy_input"] is False


def test_scene25514_synthesis_is_exactly_derived_from_preflight() -> None:
    preflight_data = json.loads(PREFLIGHT.read_bytes())
    preflight = ExactPlanPreflightConfigurationV1.model_validate(
        preflight_data["preflight_configuration"]
    )
    expected = _synthesis_configuration(
        project_root=ROOT,
        preflight=preflight,
        scene_sdf_sha256=preflight_data["scene_geometry"]["sdf_sha256"],
    )
    assert SYNTHESIS.read_bytes() == canonical_json_bytes(expected) + b"\n"
    assert expected.configuration_sha256 == (
        "55a5dc93e2aea88932ab942c2787c0780018de7d0204552636eb10bfd48778fd"
    )


@pytest.mark.skipif(
    not all(
        path.exists()
        for path in (
            ASSETS / "scene-25514.sdf",
            ASSETS / "scene-25514.supervision.json",
            NATIVE_MANIFEST,
        )
    ),
    reason="scene25514 source and A.3 native evidence are absent",
)
def test_scene25514_geometry_and_algorithm_replay_from_immutable_bytes() -> None:
    data = json.loads(PREFLIGHT.read_bytes())
    scene = data["scene_geometry"]
    numeric = canonical_a3_bullet_numeric_configuration_v1()
    geometry = build_a3_scene_collision_geometry_v1(
        sdf_path=ASSETS / "scene-25514.sdf",
        supervision_path=ASSETS / "scene-25514.supervision.json",
        expected_sdf_sha256=scene["sdf_sha256"],
        expected_supervision_sha256=scene["supervision_sha256"],
        expected_scene_seed=scene["scene_seed"],
        configuration=numeric,
    )
    geometry_data = geometry.model_dump(mode="json", exclude={"receipt_sha256"})
    geometry_data["source_sdf"]["path"] = "/m2c-evidence/scene/scene-25514.sdf"
    geometry_data["source_supervision"]["path"] = "/m2c-evidence/scene/scene-25514.supervision.json"
    geometry_data["receipt_sha256"] = canonical_sha256(geometry_data)
    geometry = A3SceneCollisionGeometryReceiptV1.model_validate(geometry_data)
    assert geometry.receipt_sha256 == scene["scene_geometry_receipt_sha256"]
    assert len(geometry.children) == scene["external_collision_child_count"] == 8

    active = data["active_session_configuration"]
    source_configuration = canonical_a3_scene_pose_source_configuration_sha256_v3(
        scene_geometry_receipt_sha256=geometry.receipt_sha256,
        mutation_counter_implementation_sha256=(active["mutation_counter_implementation_sha256"]),
        stage_sha256=scene["stage_sha256"],
        dynamic_rigid_prim_runtime_type=active["rigid_prim_runtime_type"],
        static_collision_link_paths=geometry.static_collision_link_paths,
        dynamic_collision_link_paths=geometry.dynamic_collision_link_paths,
    )
    assert source_configuration == scene["scene_pose_source_configuration_sha256"]
    collision_binding = canonical_sha256(
        {
            "schema_version": "A3CompleteSceneCollisionGeometryBindingV2",
            "robot_geometry_receipt_sha256": scene["robot_geometry_receipt_sha256"],
            "scene_geometry_receipt_sha256": geometry.receipt_sha256,
        }
    )
    assert collision_binding == scene["collision_geometry_binding_sha256"]

    fk = ControlledPandaReadOnlyFKProviderV1(project_root=ROOT)
    native = json.loads(NATIVE_MANIFEST.read_bytes())["native_shared_object"]["sha256"]
    algorithm = canonical_sha256(
        {
            "schema_version": "A3CompleteSceneSweptCollisionAlgorithmV2",
            "implementation_sha256": hashlib.sha256(
                (
                    ROOT / "src/xh_agent/policy/qrm_lite/a3_complete_scene_swept_collision_v2.py"
                ).read_bytes()
            ).hexdigest(),
            "collision_geometry_binding_sha256": collision_binding,
            "scene_state_provider_implementation_sha256": hashlib.sha256(
                (ROOT / "src/xh_agent/policy/qrm_lite/a3_scene_environment_v1.py").read_bytes()
            ).hexdigest(),
            "scene_state_provider_configuration_sha256": source_configuration,
            "fk_provider_implementation_sha256": fk.implementation_sha256,
            "fk_provider_configuration_sha256": fk.configuration_sha256,
            "native_backend_implementation_sha256": native,
            "numeric_configuration_sha256": numeric.configuration_sha256,
            "ordinary_environment_motion_model": "FROZEN_PREPLAN_POSE",
            "complete_robot_self_child_pair_product": True,
            "complete_robot_environment_child_pair_product": True,
            "complete_attached_environment_child_pair_product": True,
            "environment_environment_pairs_intentionally_excluded": True,
            "phase_contact_exclusions_source": "EXACT_EXECUTION_PHASE_V2_ALLOWLISTS",
        }
    )
    assert algorithm == scene["complete_scene_algorithm_sha256"]
