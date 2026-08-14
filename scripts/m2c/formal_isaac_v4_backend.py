#!/usr/bin/env python3
# ruff: noqa: E402
"""Real Isaac 6 backend for the M2C formal split runner.

The frozen V4 probe is loaded as a module after its exact SHA-256 is checked.
Only its accepted scene/public RGB-D setup is called; its scripted ``main`` is
never run.  Physical action helpers are deliberately not called: the frozen V4
helpers select yaw/centerline while actuating and no human ADR freezes an
exact-plan-aware wrapper.  Every request is remapped again in this process and
fails closed before physical execution when no such wrapper exists.

This file must run under ``/isaac-sim/python.sh``.  Importing it with ordinary
CPython is intentionally unsupported because a non-Isaac process must never
be able to manufacture formal physical receipts.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any
import time
import uuid

from xh_agent.data.isaac_m1b import M1B_URDF_SHA256, sha256_file
from xh_agent.data_engine.isaac.public_failure_predicates import (
    PublicTrackSnapshotV2,
    snapshots_from_perception_results,
)
from xh_agent.grasp.free_gap import select_free_gap_yaw_from_xy
from xh_agent.perception.interfaces import PerceptionInputV1
from xh_agent.policy.qrm_lite.contracts import PerceptionTrackV1
from xh_agent.policy.qrm_lite.a3_scene_environment_v1 import (
    IMPLEMENTATION_REPO_PATH as A3_SCENE_ENVIRONMENT_IMPLEMENTATION_REPO_PATH,
    IsaacSceneRigidPrimReadOnlySourceV1,
    build_a3_scene_collision_geometry_v1,
)
from xh_agent.policy.qrm_lite.formal_isaac_mutation_counter_v1 import (
    FormalIsaacActiveSessionMutationCounterV1,
    build_formal_isaac_mutation_counter_activation_v1,
)
from xh_agent.policy.qrm_lite.formal_public_role_selector_v2 import (
    select_public_journal_roles_v2,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    FormalPublicObservationV2,
    ExactExecutionPlanV2,
    IsaacCaptureRequestV2,
    IsaacCaptureResponseV2,
    IsaacEndpointBindingV2,
    IsaacExecuteRequestV2,
    IsaacExecuteResponseV2,
    IsaacFinalizeRequestV2,
    IsaacFinalizeResponseV2,
    IsaacStartRequestV2,
    IsaacStartResponseV2,
    PublicAssetInlineV2,
    PublicRoleBindingV2,
    canonical_sha256,
    physical_receipt_sha256,
    validate_isaac_execute_request_mapping_v2,
)
from xh_agent.policy.qrm_lite.model_owned_chain_v2 import PhysicalSkillReceiptV2
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)
from xh_agent.policy.qrm_lite.public_tracks_v2 import canonical_track_slots
from xh_agent.policy.qrm_lite.skill_registry_v2 import RuntimeSkillRegistryV2


FROZEN_V4_PROBE_SHA256 = "6623b1ce1dc5b289e1166ce7a59ea742fa6de2c3595d4818ab65ef03f0553f87"
FROZEN_PUBLIC_RGBD_CAPTURE_HELPER = "_capture_m2b_public_rgbd"
FORMAL_REGISTERED_ACTIONS = frozenset(
    {
        "B0_PUBLIC_GEOMETRY_GRASP",
        "B0_CARTESIAN_LIFT",
        "B0_PUBLIC_GEOMETRY_MOVE",
        "B0_PUBLIC_GEOMETRY_PLACE",
        "B0_RELEASE",
        "HOLD_AND_CAPTURE_PUBLIC_RGBD",
        "PUBLIC_TRACK_REASSOCIATION",
        "B0_PUBLIC_GEOMETRY_REGRASP",
    }
)


class IsaacPreflightRejected(RuntimeError):
    """An official non-mutating pre-execution gate rejected an action."""


def _load_frozen_v4_probe(path: Path) -> ModuleType:
    if not path.is_file() or sha256_file(path) != FROZEN_V4_PROBE_SHA256:
        raise ValueError("frozen V4 Isaac probe SHA-256 mismatch")
    module_spec = importlib.util.spec_from_file_location(
        "_m2c_formal_frozen_v4_probe",
        path,
    )
    if module_spec is None or module_spec.loader is None:
        raise ImportError("frozen V4 Isaac probe cannot be loaded")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    if module.ACTUATION_PROBE_SOURCE_SHA256 != FROZEN_V4_PROBE_SHA256:
        raise ValueError("executing frozen V4 module reports a different source hash")
    for required in (
        "simulation_app",
        FROZEN_PUBLIC_RGBD_CAPTURE_HELPER,
        "_step_gripper",
        "_setup_m2b_public_rgbd",
    ):
        if not hasattr(module, required):
            raise AttributeError(f"frozen V4 probe is missing {required}")
    return module


def _sim_time_ns(probe: ModuleType) -> int:
    value = int(
        probe.SimulationManager.get_num_physics_steps()
        * probe.SimulationManager.get_physics_dt()
        * 1_000_000_000
    )
    return max(value, 1)


def _now_after(
    probe: ModuleType,
    floor: int,
    mutation_counter: FormalIsaacActiveSessionMutationCounterV1 | None = None,
) -> int:
    if mutation_counter is not None:
        mutation_counter.record_simulation_steps()
    probe.simulation_app.update()
    return max(_sim_time_ns(probe), floor + 1)


def _as_numpy_bytes(probe: ModuleType, depth: Any) -> bytes:
    import io

    stream = io.BytesIO()
    probe.np.save(stream, depth, allow_pickle=False)
    return stream.getvalue()


def _png_bytes(probe: ModuleType, rgb: Any) -> bytes:
    import io

    stream = io.BytesIO()
    probe.Image.fromarray(rgb, mode="RGB").save(stream, format="PNG")
    return stream.getvalue()


def _public_track(snapshot: PublicTrackSnapshotV2) -> PerceptionTrackV1:
    return PerceptionTrackV1(
        track_id=snapshot.track_id,
        category=(
            f"industrial_cylinder:{snapshot.visual_color}"
            if snapshot.visual_color
            else "industrial_cylinder:unknown"
        ),
        confidence=snapshot.confidence,
        pose_xyzquat=[*snapshot.position_world_m, 1.0, 0.0, 0.0, 0.0],
    )


class FormalIsaacV4BackendV2:
    """One persistent Kit process, one scene, one formal episode."""

    def __init__(
        self,
        *,
        frozen_v4_probe_path: Path,
        stage_path: Path,
        sdf_path: Path,
        supervision_path: Path,
        urdf_path: Path,
        capture_root: Path,
        endpoint_binding: IsaacEndpointBindingV2,
        runtime_registry_sha256: str,
        public_role_selector_sha256: str,
        stage_sha256: str,
    ) -> None:
        # Defense in depth: this class can be instantiated directly under
        # Isaac Python, bypassing the HTTP service entrypoint.  Reject before
        # resolving inputs or importing the frozen probe (which starts Kit).
        require_pre_freeze(M2CExperimentAction.FORMAL_ISAAC_SERVICE)
        self.frozen_v4_probe_path = frozen_v4_probe_path.resolve()
        self.stage_path = stage_path.resolve()
        self.sdf_path = sdf_path.resolve()
        self.supervision_path = supervision_path.resolve()
        self.urdf_path = urdf_path.resolve()
        self.capture_root = capture_root.resolve()
        self.binding = endpoint_binding
        self.runtime_registry_sha256 = runtime_registry_sha256
        self.public_role_selector_sha256 = public_role_selector_sha256
        self.stage_sha256 = stage_sha256
        for path in (
            self.stage_path,
            self.sdf_path,
            self.supervision_path,
            self.urdf_path,
        ):
            if not path.is_file():
                raise FileNotFoundError(path)
        if sha256_file(self.urdf_path) != M1B_URDF_SHA256:
            raise ValueError("formal Isaac backend URDF hash differs from M1B")
        if sha256_file(self.stage_path) != self.stage_sha256:
            raise ValueError("formal Isaac backend stage SHA-256 mismatch")
        # Loading starts the one real Isaac SimulationApp.  V4's main() is not
        # called, so no scripted decision or action is executed.
        self.probe = _load_frozen_v4_probe(self.frozen_v4_probe_path)
        self._validate_probe_cli_bindings()
        self._initialize_scene_once()
        self._initialize_a3_query_sources()

        self.run_id: str | None = None
        self.session_id: str | None = None
        self.failure_observed_at_ns = 0
        self.previous_completed_at_ns = 0
        self.active_capture: IsaacCaptureResponseV2 | None = None
        self.active_public_snapshots: list[PublicTrackSnapshotV2] = []
        self.previous_public_snapshots: list[PublicTrackSnapshotV2] = []
        self.current_task_target_snapshot: PublicTrackSnapshotV2 | None = None
        self.executed_responses: list[IsaacExecuteResponseV2] = []
        self._active_exact_plan: ExactExecutionPlanV2 | None = None

    def _validate_probe_cli_bindings(self) -> None:
        probe = self.probe
        expected = {
            "stage": self.stage_path,
            "sdf": self.sdf_path,
            "supervision": self.supervision_path,
            "urdf": self.urdf_path,
        }
        for name, path in expected.items():
            if Path(getattr(probe.ARGS, name)).resolve() != path:
                raise ValueError(f"frozen V4 module argv differs at --{name}")
        if not probe.ARGS.m2b_capture_public_rgbd:
            raise ValueError("formal endpoint requires V4 public RGB-D capture")
        if probe.ARGS.m2b_task_target_public_color != "yellow":
            raise ValueError("formal endpoint requires the frozen yellow public target selector")
        if probe.ARGS.m2b_injected_public_grasp_color != "red":
            raise ValueError("formal endpoint requires the frozen red public blocker selector")
        if probe.ARGS.target_object != "cylinder_01":
            raise ValueError(
                "formal V4 primitive must bind the accepted blocker calibration entity"
            )
        if probe.ARGS.m2b_task_target_object != "cylinder_04":
            raise ValueError("formal V4 evaluator must bind the accepted task target entity")
        if probe.ARGS.m2c_scripted_safe_place_bin_cell is not None:
            raise ValueError("formal endpoint forbids scripted destination CLI input")
        if probe.SCENE.source_sdf_sha256 != sha256_file(self.sdf_path):
            raise ValueError("frozen V4 scene contract reports a different SDF hash")
        if probe.SCENE.source_supervision_sha256 != sha256_file(self.supervision_path):
            raise ValueError("frozen V4 scene contract reports a different supervision hash")

    def _initialize_scene_once(self) -> None:
        p = self.probe
        self.capture_root.mkdir(parents=True, exist_ok=False)
        context = p.omni.usd.get_context()
        if not context.open_stage(str(self.stage_path)):
            raise RuntimeError(f"failed to open Isaac stage: {self.stage_path}")
        for _ in range(5):
            p.simulation_app.update()
        self.stage = context.get_stage()
        if self.stage.GetPrimAtPath("/Render").IsValid():
            self.stage.RemovePrim("/Render")
            p.simulation_app.update()
        if p.UsdGeom.GetStageMetersPerUnit(self.stage) != 1.0:
            raise RuntimeError("Isaac M1B stage must use metres")
        for path in ("/World/Robot", p.HAND_PATH, p.LEFT_FINGER_PATH, p.RIGHT_FINGER_PATH):
            if not self.stage.GetPrimAtPath(path).IsValid():
                raise RuntimeError(f"official Franka stage is missing {path}")
        official_asset_contract = p._json_native_usd_metadata(
            self.stage.GetPrimAtPath("/World/Robot").GetCustomDataByKey(
                "xhM1BOfficialAssetContract"
            )
        )
        if (
            not isinstance(official_asset_contract, dict)
            or official_asset_contract.get("provenance")
            != "NVIDIA_ISAAC_SIM_6_OFFICIAL_FRANKA_PANDA_USD"
            or official_asset_contract.get("local_simplified_robot_used") is not False
            or official_asset_contract.get("variants")
            != {"Gripper": "Default", "Mesh": "Performance"}
        ):
            raise RuntimeError("formal stage lacks the frozen official Default Franka contract")

        self.public_rgbd = p._setup_m2b_public_rgbd(self.stage, self.capture_root)
        if self.public_rgbd is None:
            raise RuntimeError("frozen V4 public RGB-D runtime was not created")
        p.SimulationManager.setup_simulation(dt=1.0 / 60.0, device=p.ARGS.physics_device)
        self.robot = p.Franka(robot_path="/World/Robot", create_robot=False)
        contact_paths = [path for _, path in p.CONTACT_FILTERS]
        self.hand_prim = p.RigidPrim(p.HAND_PATH)
        self.left_finger_prim = p.RigidPrim(
            p.LEFT_FINGER_PATH,
            contact_filter_paths=contact_paths,
            max_contact_count=max(64, len(contact_paths) * 16),
        )
        self.right_finger_prim = p.RigidPrim(
            p.RIGHT_FINGER_PATH,
            contact_filter_paths=contact_paths,
            max_contact_count=max(64, len(contact_paths) * 16),
        )
        self.left_sensor = p.ContactSensor(
            p.Contact.create(
                f"{p.LEFT_FINGER_PATH}/m2c_formal_contact_sensor",
                min_threshold=0.0,
                max_threshold=1_000_000.0,
                radius=-1.0,
            )
        )
        self.right_sensor = p.ContactSensor(
            p.Contact.create(
                f"{p.RIGHT_FINGER_PATH}/m2c_formal_contact_sensor",
                min_threshold=0.0,
                max_threshold=1_000_000.0,
                radius=-1.0,
            )
        )
        self.sensors = {"left": self.left_sensor, "right": self.right_sensor}
        for sensor in self.sensors.values():
            sensor.add_raw_contact_data_to_frame()
        report = p.PhysxSchema.PhysxContactReportAPI.Apply(self.stage.GetPrimAtPath("/World/Robot"))
        report.CreateThresholdAttr().Set(0.0)
        p._enable_contact_reporting_on_colliders(
            self.stage,
            (p.LEFT_FINGER_PATH, p.RIGHT_FINGER_PATH),
        )
        self.contact_collector = p._PhysxContactCollector()
        p.simulation_app.update()
        p.omni.timeline.get_timeline_interface().play()
        p.SimulationManager.initialize_physics()
        p.simulation_app.update()

        stiffness, damping = self.robot.get_dof_gains()
        stiffness = p.np.asarray(p._array_or_list(stiffness), dtype=p.np.float32)
        damping = p.np.asarray(p._array_or_list(damping), dtype=p.np.float32)
        stiffness[:, p.OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX] = (
            p.ISAACLAB_FRANKA_HAND_STIFFNESS_N_PER_M
        )
        damping[:, p.OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX] = (
            p.ISAACLAB_FRANKA_HAND_DAMPING_N_S_PER_M
        )
        self.robot.set_dof_gains(stiffnesses=stiffness, dampings=damping)
        efforts = p.np.asarray(
            p._array_or_list(self.robot.get_dof_max_efforts()),
            dtype=p.np.float32,
        )
        efforts[:, p.OFFICIAL_FRANKA_ACTUATED_FINGER_DOF_INDEX] = p.SOURCE_GRIPPER_MAX_EFFORT_N
        self.robot.set_dof_max_efforts(efforts)
        self.robot.reset_to_default_pose()
        p._step_gripper(self.robot, 0.04, steps=60)
        self.clear_hand_position, self.clear_hand_orientation = p._live_pose(self.hand_prim)
        self.scene_dynamic_prims = {
            model.name: p.RigidPrim(f"/World/M1B/{model.name}/{model.links[0].name}")
            for model in p.SCENE.dynamic_models
        }
        stability = p._wait_for_natural_scene_stability(self.scene_dynamic_prims)
        if not stability["passed"]:
            raise RuntimeError("formal scene failed the frozen natural stability gate")

    def _initialize_a3_query_sources(self) -> None:
        """Bind the complete scene to one getter-only post-stability source."""

        p = self.probe
        project_root = Path(__file__).resolve().parents[2]
        scene_geometry = build_a3_scene_collision_geometry_v1(
            sdf_path=self.sdf_path,
            supervision_path=self.supervision_path,
            expected_sdf_sha256=sha256_file(self.sdf_path),
            expected_supervision_sha256=sha256_file(self.supervision_path),
            expected_scene_seed=int(p.ARGS.seed),
        )
        prims_by_path: dict[str, Any] = {}
        for source in scene_geometry.source_links:
            if not self.stage.GetPrimAtPath(source.link_path).IsValid():
                raise RuntimeError(
                    f"formal scene lacks A.3 collision-bearing link {source.link_path}"
                )
            if source.dynamic:
                try:
                    prim = self.scene_dynamic_prims[source.model_name]
                except KeyError as exc:
                    raise RuntimeError(
                        "formal scene dynamic A.3 source differs from frozen scene"
                    ) from exc
            else:
                prim = p.RigidPrim(source.link_path)
            prims_by_path[source.link_path] = prim
        runtime_types = {
            f"{type(prim).__module__}.{type(prim).__qualname__}" for prim in prims_by_path.values()
        }
        if len(runtime_types) != 1:
            raise RuntimeError("formal A.3 scene prim runtime types differ")

        activation = build_formal_isaac_mutation_counter_activation_v1(
            project_root=project_root,
            scene_owner_path=Path(__file__).resolve(),
            stage_sha256=self.stage_sha256,
            sdf_sha256=scene_geometry.source_sdf.sha256,
            supervision_sha256=scene_geometry.source_supervision.sha256,
            activated_at_ns=time.time_ns(),
        )
        mutation_counter = FormalIsaacActiveSessionMutationCounterV1(
            activation=activation,
        )
        scene_source_path = project_root / A3_SCENE_ENVIRONMENT_IMPLEMENTATION_REPO_PATH
        source_configuration_sha256 = canonical_sha256(
            {
                "schema_version": "FormalIsaacA3ScenePoseSourceConfigurationV1",
                "scene_geometry_receipt_sha256": scene_geometry.receipt_sha256,
                "mutation_counter_activation_receipt_sha256": activation.receipt_sha256,
                "stage_sha256": self.stage_sha256,
                "rigid_prim_runtime_type": next(iter(runtime_types)),
                "collision_link_paths": tuple(sorted(prims_by_path)),
            }
        )
        self.a3_scene_geometry = scene_geometry
        self.a3_mutation_counter_activation = activation
        self.a3_mutation_counter = mutation_counter
        self.a3_scene_pose_source = IsaacSceneRigidPrimReadOnlySourceV1(
            implementation_path=scene_source_path,
            implementation_sha256=sha256_file(scene_source_path),
            configuration_sha256=source_configuration_sha256,
            rigid_prim_runtime_type=next(iter(runtime_types)),
            prims_by_path=prims_by_path,
            mutation_counter_source=mutation_counter,
            now_ns=time.time_ns,
            real_runtime_provider=True,
            contract_test_only=False,
        )

    def start(self, request: IsaacStartRequestV2) -> IsaacStartResponseV2:
        if self.run_id is not None:
            raise RuntimeError("real Isaac backend supports one start per process")
        if sha256_file(self.sdf_path) != request.sdf_sha256:
            raise ValueError("start SDF hash differs from loaded Isaac scene")
        if sha256_file(self.supervision_path) != request.supervision_sha256:
            raise ValueError("start supervision hash differs from loaded Isaac scene")
        if request.runtime_registry_sha256 != self.runtime_registry_sha256:
            raise ValueError("start registry hash differs from Isaac-side registry")
        self.run_id = request.run_id
        self.session_id = f"{request.run_id}-{uuid.uuid4().hex}"
        # PATH_BLOCKED is established from the first public capture and the
        # registered public free-gap geometry predicate, never entity truth.
        initial = self._capture_public(decision_index=-1, label="failure_boundary")
        roles = select_public_journal_roles_v2(initial["snapshots"])
        task_track = next(
            (
                track
                for track in initial["snapshots"]
                if track.track_id == roles.task_target_track_id
            ),
            None,
        )
        if task_track is None:
            raise RuntimeError("public target selector is absent at PATH_BLOCKED boundary")
        neighbors = [
            track.position_world_m[:2]
            for track in initial["snapshots"]
            if track.track_id != task_track.track_id
        ]
        gap = select_free_gap_yaw_from_xy(
            task_track.position_world_m[:2],
            neighbors,
            source="PUBLIC_RGBD_PATH_BLOCKED_FAILURE_BOUNDARY",
        )
        if gap["clearance_ok"] is not False:
            raise RuntimeError("loaded scene did not expose public PATH_BLOCKED geometry")
        self.previous_public_snapshots = list(initial["snapshots"])
        self.current_task_target_snapshot = task_track
        self.failure_observed_at_ns = int(initial["captured_at_ns"])
        self.previous_completed_at_ns = self.failure_observed_at_ns
        return IsaacStartResponseV2(
            run_id=request.run_id,
            session_id=self.session_id,
            start_request_sha256=canonical_sha256(request),
            failure_observed_at_ns=self.failure_observed_at_ns,
            endpoint_binding_sha256=canonical_sha256(self.binding),
            implementation_sha256=self.binding.implementation_sha256,
            physical_backend_sha256=self.binding.physical_backend_sha256,
        )

    def _capture_public(self, *, decision_index: int, label: str) -> dict[str, Any]:
        p = self.probe
        self.a3_mutation_counter.record_simulation_steps()
        p.rep.orchestrator.step(
            rt_subframes=1,
            delta_time=1.0 / 60.0,
            pause_timeline=False,
        )
        rgb_raw = self.public_rgbd["annotators"]["rgb"].get_data()
        depth_raw = self.public_rgbd["annotators"]["depth"].get_data()
        rgb = p.np.asarray(rgb_raw["data"] if isinstance(rgb_raw, dict) else rgb_raw)
        depth = p.np.asarray(
            depth_raw["data"] if isinstance(depth_raw, dict) else depth_raw,
            dtype=p.np.float32,
        )
        width, height = self.public_rgbd["resolution"]
        if rgb.shape[:2] != (height, width) or depth.shape != (height, width):
            raise RuntimeError(f"public RGB-D shape mismatch: {rgb.shape}, {depth.shape}")
        rgb = rgb[:, :, :3].astype(p.np.uint8)
        rgb_bytes = _png_bytes(p, rgb)
        depth_bytes = _as_numpy_bytes(p, depth)
        captured_at_ns = _now_after(
            p,
            self.previous_completed_at_ns,
            self.a3_mutation_counter,
        )
        rgb_sha = hashlib.sha256(rgb_bytes).hexdigest()
        depth_sha = hashlib.sha256(depth_bytes).hexdigest()
        base = f"formal/{self.run_id or 'prestart'}/{decision_index:02d}-{label}"
        public_results = self.public_rgbd["baseline"].infer(
            PerceptionInputV1(
                frame_id="m2b_policy_rgbd_optical",
                timestamp_ns=captured_at_ns,
                rgb_uri=f"dataset://{base}.png",
                depth_uri=f"dataset://{base}.npy",
                camera_intrinsics=self.public_rgbd["intrinsics"],
                camera_frame="m2b_policy_rgbd_optical",
            ),
            depth,
            rgb,
        )
        snapshots = snapshots_from_perception_results(
            public_results,
            self.public_rgbd["camera_to_world_optical"],
        )
        public_tracks = [_public_track(snapshot) for snapshot in snapshots]
        slots = canonical_track_slots(public_tracks)
        capture_core = {
            "decision_index": decision_index,
            "captured_at_ns": captured_at_ns,
            "rgb_sha256": rgb_sha,
            "depth_sha256": depth_sha,
            "public_tracks": [track.model_dump(mode="json") for track in public_tracks],
            "previous_physical_completed_at_ns": self.previous_completed_at_ns,
            "source": "ISAAC_REPLICATOR_PUBLIC_RGBD",
        }
        return {
            **capture_core,
            "capture_receipt_sha256": canonical_sha256(capture_core),
            "rgb_bytes": rgb_bytes,
            "depth_bytes": depth_bytes,
            "snapshots": snapshots,
            "public_tracks": public_tracks,
            "canonical_slots": list(slots.track_ids),
            "rgb_uri": f"dataset://{base}.png",
            "depth_uri": f"dataset://{base}.npy",
        }

    def capture(self, request: IsaacCaptureRequestV2) -> IsaacCaptureResponseV2:
        self._require_session(request.run_id, request.session_id)
        if self.active_capture is not None:
            raise RuntimeError("real Isaac backend already owns an active capture")
        captured = self._capture_public(
            decision_index=request.decision_index,
            label="policy_input",
        )
        roles = select_public_journal_roles_v2(captured["snapshots"])
        observation = FormalPublicObservationV2(
            observation_id=f"{self.session_id}-observation-{request.decision_index}",
            captured_at_ns=captured["captured_at_ns"],
            previous_physical_completed_at_ns=self.previous_completed_at_ns,
            rgb=PublicAssetInlineV2(
                uri=captured["rgb_uri"],
                sha256=captured["rgb_sha256"],
                media_type="image/png",
                data_base64=base64.b64encode(captured["rgb_bytes"]).decode("ascii"),
            ),
            depth=PublicAssetInlineV2(
                uri=captured["depth_uri"],
                sha256=captured["depth_sha256"],
                media_type="application/x-npy",
                data_base64=base64.b64encode(captured["depth_bytes"]).decode("ascii"),
            ),
            capture_receipt_sha256=captured["capture_receipt_sha256"],
            perception_tracks=captured["public_tracks"],
            canonical_slots=captured["canonical_slots"],
        )
        response = IsaacCaptureResponseV2(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation=observation,
            public_roles=PublicRoleBindingV2(
                blocker_track_id=roles.blocker_track_id,
                task_target_track_id=roles.task_target_track_id,
                selector_contract_sha256=self.public_role_selector_sha256,
            ),
        )
        self.active_capture = response
        self.active_public_snapshots = list(captured["snapshots"])
        return response

    def execute(
        self,
        request: IsaacExecuteRequestV2,
        registry: RuntimeSkillRegistryV2,
    ) -> IsaacExecuteResponseV2:
        self._require_session(request.run_id, request.session_id)
        capture = self.active_capture
        if capture is None or request.observation_id != capture.observation.observation_id:
            raise RuntimeError("execution has no matching real public capture")

        self._active_exact_plan = None
        plan_error: str | None = None

        def ensure_plan(
            action: str,
            parameters: dict[str, Any],
        ) -> ExactExecutionPlanV2:
            nonlocal plan_error
            if action not in FORMAL_REGISTERED_ACTIONS:
                raise IsaacPreflightRejected(f"unimplemented registered action: {action}")
            if self._active_exact_plan is None:
                try:
                    self._active_exact_plan = self._construct_exact_execution_plan(
                        request,
                        action,
                        parameters,
                    )
                except Exception as exc:
                    plan_error = f"{type(exc).__name__}: {exc}"
                    raise
            return self._active_exact_plan

        def gate(name: str) -> Any:
            def check(action: str, parameters: dict[str, Any]) -> tuple[bool, str]:
                try:
                    plan = ensure_plan(action, parameters)
                except Exception as exc:
                    return False, f"exact execution plan unavailable: {type(exc).__name__}: {exc}"
                details = [
                    f"phase={phase.phase_index}:{phase.phase_name} "
                    + str(getattr(phase.gates, f"{name}_detail"))
                    for phase in plan.phases
                ]
                return True, "; ".join(details)

            return check

        def exact_plan_getter(
            action: str,
            parameters: dict[str, Any],
        ) -> ExactExecutionPlanV2:
            return ensure_plan(action, parameters)

        mapping = validate_isaac_execute_request_mapping_v2(
            request,
            registry,
            ik_check=gate("ik"),
            collision_check=gate("collision"),
            controller_check=gate("controller"),
            safety_check=gate("safety"),
            exact_plan_getter=exact_plan_getter,
        )
        if plan_error is not None:
            exact_plan_trace_found = False
            for entry in mapping.gate_trace:
                if entry.get("gate") == "exact_plan":
                    entry.update(status="INVALID", detail=plan_error)
                    exact_plan_trace_found = True
                    break
            if not exact_plan_trace_found:
                mapping.gate_trace.append(
                    {
                        "gate": "exact_plan",
                        "status": "INVALID",
                        "detail": plan_error,
                    }
                )
        if mapping.status != "VALID":
            # No hash-frozen unchanged-B0 action wrapper exists in this
            # deployment.  Calling the locally authored hold controller would
            # falsely label a new formal primitive as B0.  Therefore INVALID is
            # terminal and explicitly records that no physical fallback ran.
            started = max(time.time_ns(), capture.observation.captured_at_ns + 1)
            completed = max(time.time_ns(), started + 1)
            receipt = PhysicalSkillReceiptV2(
                receipt_id=f"{self.session_id}-not-executed-{request.decision_index}",
                receipt_sha256="0" * 64,
                executed_skill="NO_PHYSICAL_EXECUTION",
                execution_source="NO_PHYSICAL_EXECUTION",
                physically_executed=False,
                started_at_ns=started,
                completed_at_ns=completed,
                schema_gate="PASS",
                stale_track_gate="PASS",
                frame_unit_gate="PASS",
                ik_gate="NOT_RUN",
                collision_gate="NOT_RUN",
                controller_gate="NOT_RUN",
                safety_gate="NOT_RUN",
                collision_or_safety_violation=False,
                fallback_reason=(
                    "PHYSICAL_FALLBACK_NOT_EXECUTED:NO_HASH_FROZEN_UNCHANGED_B0_"
                    "ACTION_WRAPPER; "
                    + (
                        mapping.rejection_reason.value
                        if mapping.rejection_reason is not None
                        else "INVALID_MAPPING"
                    )
                ),
            )
            receipt.receipt_sha256 = physical_receipt_sha256(receipt)
            response = IsaacExecuteResponseV2(
                run_id=request.run_id,
                session_id=request.session_id,
                decision_index=request.decision_index,
                observation_id=request.observation_id,
                inference_response_sha256=request.inference_response_sha256,
                mapping=mapping,
                requested_skill_was_physically_executed=False,
                physical_skill_receipts=[receipt],
            )
            self.previous_public_snapshots = list(self.active_public_snapshots)
            self.previous_completed_at_ns = completed
            self.active_capture = None
            self.active_public_snapshots = []
            self.executed_responses.append(response)
            return response

        plan = self._active_exact_plan
        if plan is None:
            raise RuntimeError("VALID mapping lost its immutable exact execution plan")
        plan_sha256 = canonical_sha256(plan)
        if not any(
            entry.get("gate") == "exact_plan"
            and entry.get("status") == "PASS"
            and entry.get("plan_sha256") == plan_sha256
            for entry in mapping.gate_trace
        ):
            raise RuntimeError("VALID mapping is not bound to the exact plan hash")
        plan_is_physical = any(
            phase.command
            in {
                "CARTESIAN_POSE",
                "GRIPPER_POSITION",
                "ATTACH_CONTACT_ENTITY",
                "REMOVE_ATTACHMENT",
            }
            for phase in plan.phases
        )
        started = max(time.time_ns(), capture.observation.captured_at_ns + 1)
        controller = self._execute_exact_plan(plan)
        completed = max(time.time_ns(), started + 1)
        receipt = PhysicalSkillReceiptV2(
            receipt_id=f"{self.session_id}-physical-{request.decision_index}",
            receipt_sha256="0" * 64,
            executed_skill=str(mapping.canonical_skill),
            execution_source="MODEL_SELECTED_REGISTERED_SKILL",
            physically_executed=plan_is_physical,
            started_at_ns=started,
            completed_at_ns=completed,
            schema_gate="PASS",
            stale_track_gate="PASS",
            frame_unit_gate="PASS",
            ik_gate="PASS",
            collision_gate=("PASS" if controller["collision_passed"] else "REJECTED"),
            controller_gate=("PASS" if controller["controller_passed"] else "REJECTED"),
            safety_gate=("PASS" if controller["safety_passed"] else "REJECTED"),
            collision_or_safety_violation=not (
                controller["collision_passed"] and controller["safety_passed"]
            ),
            fallback_reason=None,
        )
        receipt.receipt_sha256 = physical_receipt_sha256(receipt)
        response = IsaacExecuteResponseV2(
            run_id=request.run_id,
            session_id=request.session_id,
            decision_index=request.decision_index,
            observation_id=request.observation_id,
            inference_response_sha256=request.inference_response_sha256,
            mapping=mapping,
            exact_execution_plan=plan,
            exact_execution_plan_sha256=plan_sha256,
            executed_exact_execution_plan_sha256=plan_sha256,
            requested_skill_was_physically_executed=plan_is_physical,
            physical_skill_receipts=[receipt],
        )
        self.previous_public_snapshots = list(self.active_public_snapshots)
        self.previous_completed_at_ns = completed
        self.active_capture = None
        self.active_public_snapshots = []
        self.executed_responses.append(response)
        return response

    def _construct_exact_execution_plan(
        self,
        request: IsaacExecuteRequestV2,
        runtime_action: str,
        parameters: dict[str, Any],
    ) -> ExactExecutionPlanV2:
        """Construct a plan only when every future command is pre-bindable.

        The frozen V4 grasp helper selects yaw/centerline while actuating and
        accepts no precomputed plan.  The locally authored formal motions are
        not an ADR-approved unchanged-B0 wrapper either.  Physical actions are
        therefore rejected here until a human ADR freezes an exact-plan-aware
        primitive.  Logical capture/reassociation cannot satisfy a formal
        physical-skill receipt and are also rejected by this physical API.
        """
        del request, parameters
        raise IsaacPreflightRejected(
            "no ADR-approved exact-plan physical primitive is frozen for "
            f"{runtime_action}; frozen V4 selects execution parameters during "
            "actuation, local formal motions are not unchanged B0 wrappers, and "
            "logical sensor/track operations are not physical skills"
        )

    def _execute_exact_plan(self, plan: ExactExecutionPlanV2) -> dict[str, bool]:
        """No physical executor is authorized until a human ADR freezes one."""

        raise RuntimeError(
            "exact physical executor is unavailable; VALID mapping is unreachable "
            f"for plan {canonical_sha256(plan)}"
        )

    @staticmethod
    def _controller_result(
        controller: bool,
        collision: bool,
        safety: bool,
    ) -> dict[str, bool]:
        return {
            "controller_passed": bool(controller),
            "collision_passed": bool(collision),
            "safety_passed": bool(safety),
        }

    def finalize(self, request: IsaacFinalizeRequestV2) -> IsaacFinalizeResponseV2:
        self._require_session(request.run_id, request.session_id)
        if len(self.executed_responses) != 8:
            raise RuntimeError("real Isaac finalize requires eight executed cycles")
        # The exact-plan mainline intentionally cannot complete the physical
        # chain until an ADR-approved primitive exists, so formal finalize is
        # unreachable.  Keep the evaluator public-only and fail closed if an
        # external caller nevertheless reaches it.
        self._capture_public(decision_index=8, label="final_evaluation")
        return IsaacFinalizeResponseV2(
            run_id=request.run_id,
            session_id=request.session_id,
            evaluated_at_ns=_now_after(
                self.probe,
                self.previous_completed_at_ns,
                self.a3_mutation_counter,
            ),
            final_task_success=False,
        )

    def _require_session(self, run_id: str, session_id: str) -> None:
        if run_id != self.run_id or session_id != self.session_id:
            raise ValueError("request differs from active real Isaac session")

    def close(self) -> None:
        """Close the single SimulationApp after the HTTP server terminates."""

        settings = self.probe.PHYSICS_SETTINGS
        before = self.probe.DISABLE_CONTACT_PROCESSING_BEFORE
        if before is not None:
            settings.set_bool(self.probe.DISABLE_CONTACT_PROCESSING_SETTING, bool(before))
        self.probe.simulation_app.close()
