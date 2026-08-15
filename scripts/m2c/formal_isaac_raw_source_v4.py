#!/usr/bin/env python3
"""Real-Isaac raw public-frame source for the formal V4 scene owner.

This adapter starts exactly one copy of the already accepted V4 scene setup,
but exposes only unassociated public RGB-D detections, byte-bound RGB/depth,
and public robot proprioception.  It never exposes simulator entity identity,
TaskSpec pointers, a planner, model output, Teacher data, or outcome truth.

The adapter records a public proprioception sample after every Kit update made
through the frozen probe.  A completed model operation is committed separately
from the controller receipt and is consumed exactly once by the next capture;
this is the sole source of ADR-0024 HAND_CARRY skill eligibility.
"""

from __future__ import annotations

import base64
from pathlib import Path
import time
from typing import Any, Literal

from xh_agent.data.isaac_m1b import M1B_URDF_SHA256, sha256_file
from xh_agent.perception.public_track_associator_v2 import (
    LastPhysicallyExecutedPublicSkillV2,
    PublicBBoxOrMaskV2,
    PublicDetectionAttributesV2,
    PublicRGBDDetectionV2,
    PublicRobotProprioceptionV2,
)
from xh_agent.policy.qrm_lite.formal_isaac_persistent_scene_v4 import (
    FormalIsaacRawPublicFrameV4,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v2 import (
    PublicAssetInlineV2,
    canonical_sha256,
)
from xh_agent.policy.qrm_lite.formal_split_runner_v4 import (
    IsaacExecuteRequestV4,
    ModelDecisionExecutionReceiptV4,
)
from xh_agent.policy.qrm_lite.m2c_hard_freeze import (
    M2CExperimentAction,
    require_pre_freeze,
)

from m2c.formal_isaac_v4_backend import (
    FormalIsaacV4BackendV2,
    _load_frozen_v4_probe,
)


IMPLEMENTATION_REPO_PATH = "scripts/m2c/formal_isaac_raw_source_v4.py"
PUBLIC_CAMERA_FRAME = "m2b_policy_rgbd_optical"
PUBLIC_WORLD_FRAME = "world"
# This is the unchanged public closed-hand threshold used by the frozen M1B
# actuation probe and the accepted V4 collection implementation.  It is a
# proprioceptive classification only; it is never inferred from contact,
# attachment, simulator identity, or outcome truth.
PUBLIC_GRIPPER_CLOSED_MAX_WIDTH_M = 0.002


def implementation_sha256_v4() -> str:
    return sha256_file(Path(__file__))


class FormalIsaacRawPublicFrameSourceV4Real:
    """Single-scene, fail-closed production raw-frame source."""

    real_isaac: Literal[True] = True
    mocked_physics: Literal[False] = False

    def __init__(
        self,
        *,
        frozen_v4_probe_path: Path,
        stage_path: Path,
        sdf_path: Path,
        supervision_path: Path,
        urdf_path: Path,
        capture_root: Path,
        stage_sha256: str,
    ) -> None:
        require_pre_freeze(M2CExperimentAction.FORMAL_ISAAC_SERVICE)
        self.implementation_sha256 = implementation_sha256_v4()
        scene = object.__new__(FormalIsaacV4BackendV2)
        scene.frozen_v4_probe_path = frozen_v4_probe_path.resolve()
        scene.stage_path = stage_path.resolve()
        scene.sdf_path = sdf_path.resolve()
        scene.supervision_path = supervision_path.resolve()
        scene.urdf_path = urdf_path.resolve()
        scene.capture_root = capture_root.resolve()
        scene.stage_sha256 = stage_sha256
        for path in (scene.stage_path, scene.sdf_path, scene.supervision_path, scene.urdf_path):
            if not path.is_file():
                raise FileNotFoundError(path)
        if sha256_file(scene.urdf_path) != M1B_URDF_SHA256:
            raise ValueError("formal V4 raw source URDF hash differs from M1B")
        if sha256_file(scene.stage_path) != stage_sha256:
            raise ValueError("formal V4 raw source stage SHA-256 mismatch")
        scene.probe = _load_frozen_v4_probe(scene.frozen_v4_probe_path)
        scene._validate_probe_cli_bindings()
        scene._initialize_scene_once()
        scene._initialize_a3_query_sources()
        # ``_capture_public`` is a reviewed sensor helper from the legacy V2
        # backend.  V4 deliberately does not call V2 ``start`` or ``execute``,
        # but the helper still reads these three bookkeeping fields.
        scene.run_id = None
        scene.session_id = None
        scene.previous_completed_at_ns = 0
        self._scene = scene
        self._proprioception: list[PublicRobotProprioceptionV2] = []
        self._last_timestamp_ns = 0
        self._last_policy_capture_at_ns: int | None = None
        self._active_identity: tuple[str, str] | None = None
        self._next_capture_index = -1
        self._next_execution_index = 0
        self._pending_public_skill: LastPhysicallyExecutedPublicSkillV2 | None = None
        self._last_execution_completed_at_ns = 0
        self._closed = False
        self._install_update_recorder()

    def _install_update_recorder(self) -> None:
        app = self._scene.probe.simulation_app
        original = app.update
        if getattr(app, "_m2c_v4_public_update_wrapped", False):
            raise RuntimeError("formal V4 public update recorder was already installed")

        def update_and_record(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            self._record_proprioception_sample()
            return result

        try:
            app.update = update_and_record
            app._m2c_v4_public_update_wrapped = True
        except Exception as exc:
            raise RuntimeError("formal V4 cannot install complete public update recorder") from exc
        if app.update is not update_and_record:
            raise RuntimeError("formal V4 public update recorder assignment was not retained")

    def _ordered_now_ns(self) -> int:
        value = int(time.time_ns())
        if value <= self._last_timestamp_ns:
            value = self._last_timestamp_ns + 1
        self._last_timestamp_ns = value
        return value

    def _record_proprioception_sample(self) -> None:
        robot = self._scene.robot
        if not robot.is_physics_tensor_entity_valid():
            return
        timestamp_ns = self._ordered_now_ns()
        position, orientation_wxyz = self._scene.probe._live_pose(self._scene.hand_prim)
        finger_positions = self._scene.probe._array_or_list(robot.get_dof_positions())[0][-2:]
        width_m = float(sum(float(value) for value in finger_positions))
        self._proprioception.append(
            PublicRobotProprioceptionV2(
                timestamp_ns=timestamp_ns,
                world_frame=PUBLIC_WORLD_FRAME,
                end_effector_position_world_m=[float(value) for value in position],
                end_effector_orientation_world_xyzw=[
                    float(orientation_wxyz[1]),
                    float(orientation_wxyz[2]),
                    float(orientation_wxyz[3]),
                    float(orientation_wxyz[0]),
                ],
                gripper_width_m=width_m,
                gripper_closed=bool(width_m <= PUBLIC_GRIPPER_CLOSED_MAX_WIDTH_M),
            )
        )

    def _interval_samples(
        self,
        *,
        capture_index: int,
        captured_at_ns: int,
    ) -> tuple[PublicRobotProprioceptionV2, ...]:
        if capture_index <= 0:
            return (self._proprioception[-1],)
        start = self._last_policy_capture_at_ns
        if start is None:
            raise RuntimeError("formal V4 public proprioception lacks the previous capture")
        samples = tuple(
            item for item in self._proprioception if start <= item.timestamp_ns <= captured_at_ns
        )
        if (
            len(samples) < 2
            or samples[0].timestamp_ns != start
            or samples[-1].timestamp_ns != captured_at_ns
        ):
            raise RuntimeError("formal V4 public proprioception interval is incomplete")
        return samples

    @staticmethod
    def _detection(result: Any, *, timestamp_ns: int) -> PublicRGBDDetectionV2:
        return PublicRGBDDetectionV2(
            timestamp_ns=timestamp_ns,
            frame_id=PUBLIC_CAMERA_FRAME,
            category=str(result.category),
            attributes=PublicDetectionAttributesV2(
                visual_color=result.attributes.get("visual_color")
            ),
            position_3d=[float(value) for value in result.position_3d],
            confidence=float(result.confidence),
            bbox_or_mask=PublicBBoxOrMaskV2(
                x=int(result.bbox_or_mask.x),
                y=int(result.bbox_or_mask.y),
                width=int(result.bbox_or_mask.width),
                height=int(result.bbox_or_mask.height),
            ),
            visibility=float(result.visibility),
            covariance_or_quality={
                str(key): float(value) for key, value in result.covariance_or_quality.items()
            },
        )

    def capture_raw_public_frame_v4(
        self,
        *,
        run_id: str,
        session_id: str,
        capture_index: int,
        label: Literal["FAILURE_BOUNDARY", "POLICY_INPUT", "FINAL_EVALUATION"],
        previous_execution_completed_at_ns: int,
    ) -> FormalIsaacRawPublicFrameV4:
        require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
        if self._closed:
            raise RuntimeError("formal V4 raw source is closed")
        if label == "FAILURE_BOUNDARY":
            if self._active_identity is not None or capture_index != -1:
                raise ValueError("formal V4 raw failure boundary is single-use")
            self._active_identity = (run_id, session_id)
            self._next_capture_index = 0
        elif (
            self._active_identity != (run_id, session_id)
            or capture_index != self._next_capture_index
            or (label == "POLICY_INPUT" and not 0 <= capture_index <= 7)
            or (label == "FINAL_EVALUATION" and capture_index != 8)
            or previous_execution_completed_at_ns != self._last_execution_completed_at_ns
            or (capture_index >= 0 and self._next_execution_index != capture_index)
        ):
            raise ValueError("formal V4 raw capture crosses persistent scene history")
        if capture_index == 0 and self._pending_public_skill is not None:
            raise ValueError("formal V4 first policy capture has a prior physical skill")
        if label == "FAILURE_BOUNDARY":
            self._scene.run_id = run_id
            self._scene.session_id = session_id
        self._scene.previous_completed_at_ns = previous_execution_completed_at_ns
        captured = self._scene._capture_public(
            decision_index=capture_index,
            label=label.lower(),
        )
        if not self._proprioception:
            raise RuntimeError("formal V4 capture produced no public proprioception sample")
        captured_at_ns = self._proprioception[-1].timestamp_ns
        if captured_at_ns <= previous_execution_completed_at_ns:
            raise RuntimeError("formal V4 public capture did not follow prior execution")
        samples = self._interval_samples(
            capture_index=capture_index,
            captured_at_ns=captured_at_ns,
        )
        detections = tuple(
            self._detection(item, timestamp_ns=captured_at_ns)
            for item in captured["unassociated_public_results"]
        )
        rgb = PublicAssetInlineV2(
            uri=str(captured["rgb_uri"]),
            sha256=str(captured["rgb_sha256"]),
            media_type="image/png",
            data_base64=base64.b64encode(captured["rgb_bytes"]).decode("ascii"),
        )
        depth = PublicAssetInlineV2(
            uri=str(captured["depth_uri"]),
            sha256=str(captured["depth_sha256"]),
            media_type="application/x-npy",
            data_base64=base64.b64encode(captured["depth_bytes"]).decode("ascii"),
        )
        payload: dict[str, Any] = {
            "schema_version": "FormalIsaacRawPublicFrameV4",
            "run_id": run_id,
            "session_id": session_id,
            "capture_index": capture_index,
            "label": label,
            "previous_execution_completed_at_ns": previous_execution_completed_at_ns,
            "captured_at_ns": captured_at_ns,
            "capture_source_implementation_sha256": self.implementation_sha256,
            "detections": [item.model_dump(mode="json") for item in detections],
            "proprioception_samples": [item.model_dump(mode="json") for item in samples],
            "last_physically_executed_public_skill": (
                self._pending_public_skill.model_dump(mode="json")
                if self._pending_public_skill is not None
                else None
            ),
            "rgb": rgb.model_dump(mode="json"),
            "depth": depth.model_dump(mode="json"),
            "real_isaac": True,
            "mocked_physics": False,
            "teacher_used": False,
            "privileged_truth_policy_input": False,
        }
        frame = FormalIsaacRawPublicFrameV4(
            **payload,
            frame_receipt_sha256=canonical_sha256(payload),
        )
        if label == "POLICY_INPUT":
            self._last_policy_capture_at_ns = captured_at_ns
            self._next_capture_index += 1
        elif label == "FINAL_EVALUATION":
            self._next_capture_index = 9
        else:
            self._last_execution_completed_at_ns = captured_at_ns
        self._pending_public_skill = None
        return frame

    def commit_public_execution_v4(
        self,
        *,
        request: IsaacExecuteRequestV4,
        receipt: ModelDecisionExecutionReceiptV4,
    ) -> None:
        require_pre_freeze(M2CExperimentAction.Q_B_EVALUATION)
        if (
            self._closed
            or self._active_identity != (request.run_id, request.session_id)
            or request.decision_index != self._next_execution_index
            or self._next_capture_index != request.decision_index + 1
            or self._pending_public_skill is not None
            or receipt.receipt_id != f"{request.session_id}-execution-{request.decision_index}"
            or receipt.started_at_ns <= request.observation.captured_at_ns
            or self._last_policy_capture_at_ns is None
            or receipt.started_at_ns <= self._last_policy_capture_at_ns
            or receipt.completed_at_ns <= receipt.started_at_ns
            or receipt.execution_source != "MODEL_SELECTED_REGISTERED_SKILL"
            or receipt.outcome != "PASS"
        ):
            raise ValueError("formal V4 raw execution commit crosses active history")
        if receipt.robot_actuation_executed:
            self._pending_public_skill = LastPhysicallyExecutedPublicSkillV2(
                skill_name=receipt.selected_skill,
                started_at_ns=receipt.started_at_ns,
                completed_at_ns=receipt.completed_at_ns,
            )
        self._last_execution_completed_at_ns = receipt.completed_at_ns
        self._scene.previous_completed_at_ns = receipt.completed_at_ns
        self._next_execution_index += 1

    @property
    def scene_runtime(self) -> FormalIsaacV4BackendV2:
        """Expose the single scene only to the reviewed production assembler."""

        return self._scene

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._scene.close()
