"""Runtime evidence gates for controller-backed motion."""

from .continuity import ContinuityResult, JointSample, check_joint_continuity
from .motion_execution import MotionSegmentEvidence, evaluate_motion_segment

__all__ = [
    "ContinuityResult",
    "JointSample",
    "MotionSegmentEvidence",
    "check_joint_continuity",
    "evaluate_motion_segment",
]
