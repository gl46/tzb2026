"""Alpha Flow head freeze status.

Flow remains in-tree for reproducibility but is not a formal Beta-1 model.
"""

from __future__ import annotations

FLOW_STATUS = "IMPLEMENTED_NOT_SELECTED"
FLOW_SELECTED_FOR_BETA1 = False
FLOW_RATIONALE = (
    "Alpha offline eval did not show Flow outperforming MLP residual under the same split; "
    "Beta-1 freezes Flow and compares Q1 vs Q2 FailureContext instead."
)


def flow_is_selected() -> bool:
    return FLOW_SELECTED_FOR_BETA1
