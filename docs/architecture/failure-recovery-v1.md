# Failure and recovery v1

The failure injector supports grasp-pose offset, width mismatch, low friction/slip, obstacle,
occlusion, delayed release and moved target. B1 detects empty grasp, slip, blockage and release
failure from explicit events, then allows one controlled recovery (`REOBSERVE`, `BACKOFF`, or
`REGRASP`). The future Student uses prediction-vs-observation residuals and uncertainty to choose
the equivalent recovery, not a hidden simulator ground-truth shortcut.
