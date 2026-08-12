"""Non-configurable M2C experiment hard-freeze gate.

The human goal fixes 2026-09-01 in Asia/Shanghai as the first instant at
which no new M2C experiment may start.  This module intentionally reads no
environment variable, config file, CLI flag, local timezone, or caller-supplied
timestamp.  The sole production decision is made from ``time.time_ns()``.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


M2C_TIMEZONE_NAME = "Asia/Shanghai"
M2C_HARD_FREEZE_LOCAL_ISO = "2026-09-01T00:00:00+08:00"
M2C_HARD_FREEZE_UNIX_NS = 1_788_192_000_000_000_000


class M2CExperimentAction(str, Enum):
    TRAINING = "TRAINING"
    ISAAC_COLLECTION = "ISAAC_COLLECTION"
    SMOKE = "SMOKE"
    Q_B_EVALUATION = "Q_B_EVALUATION"
    S5_EXECUTION = "S5_EXECUTION"
    S6_EXECUTION = "S6_EXECUTION"
    FORMAL_MODEL_SERVICE = "FORMAL_MODEL_SERVICE"
    FORMAL_ISAAC_SERVICE = "FORMAL_ISAAC_SERVICE"


class M2CHardFreezeError(RuntimeError):
    """Raised when a new M2C experiment is not allowed to start."""


def _freeze_datetime() -> datetime:
    try:
        timezone = ZoneInfo(M2C_TIMEZONE_NAME)
    except ZoneInfoNotFoundError as exc:
        raise M2CHardFreezeError(
            "M2C_HARD_FREEZE_CLOCK_INVALID:Asia/Shanghai timezone data unavailable"
        ) from exc
    except Exception as exc:
        raise M2CHardFreezeError(
            "M2C_HARD_FREEZE_CLOCK_INVALID:Asia/Shanghai timezone data unavailable"
        ) from exc
    freeze = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone)
    if freeze.isoformat() != M2C_HARD_FREEZE_LOCAL_ISO:
        raise M2CHardFreezeError("M2C_HARD_FREEZE_CLOCK_INVALID:Asia/Shanghai offset mismatch")
    if int(freeze.timestamp() * 1_000_000_000) != M2C_HARD_FREEZE_UNIX_NS:
        raise M2CHardFreezeError("M2C_HARD_FREEZE_CLOCK_INVALID:hard-freeze epoch mismatch")
    return freeze


def require_pre_freeze(
    action: M2CExperimentAction,
) -> datetime:
    """Allow ``action`` only before the fixed Asia/Shanghai hard freeze.

    Invalid clock/timezone inputs fail closed instead of being interpreted as
    local time.  There is deliberately no timestamp/configuration override in
    this API; tests replace the system clock function at the module boundary.
    """

    if not isinstance(action, M2CExperimentAction):
        raise M2CHardFreezeError("M2C_HARD_FREEZE_ACTION_INVALID")
    freeze = _freeze_datetime()
    try:
        observed_ns = time.time_ns()
        if type(observed_ns) is not int or observed_ns <= 0:
            raise ValueError("system time_ns is not a positive integer")
        # Compare the integer clock directly at the boundary so float
        # rounding cannot admit an instant on/after the freeze.
        if observed_ns >= M2C_HARD_FREEZE_UNIX_NS:
            raise M2CHardFreezeError(
                "M2C_HARD_FREEZE_ACTIVE:"
                f"{action.value}:new experiment execution forbidden on/after "
                f"{M2C_HARD_FREEZE_LOCAL_ISO}"
            )
        seconds, nanoseconds = divmod(observed_ns, 1_000_000_000)
        current = datetime.fromtimestamp(seconds, tz=freeze.tzinfo).replace(
            microsecond=nanoseconds // 1_000
        )
        offset = current.utcoffset()
        if current.tzinfo is None or offset is None:
            raise ValueError("timezone-aware datetime required")
        current_shanghai = current.astimezone(freeze.tzinfo)
    except M2CHardFreezeError:
        raise
    except Exception as exc:
        raise M2CHardFreezeError(
            "M2C_HARD_FREEZE_CLOCK_INVALID:timezone-aware valid wall clock required"
        ) from exc
    if current_shanghai >= freeze:
        raise M2CHardFreezeError(
            "M2C_HARD_FREEZE_ACTIVE:"
            f"{action.value}:new experiment execution forbidden on/after "
            f"{M2C_HARD_FREEZE_LOCAL_ISO}"
        )
    return current_shanghai
