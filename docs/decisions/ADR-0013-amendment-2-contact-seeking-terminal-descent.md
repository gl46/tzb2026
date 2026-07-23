# ADR-0013 Amendment 2: Contact-seeking terminal descent

Date: 2026-07-24 (Asia/Shanghai)  
Status: **APPROVED — project owner authorized resolution in Codex conversation**

## Decision

The fixed-height M1B top-down terminal descent may be replaced by a staged,
straight vertical contact-seeking descent. At each 5 mm waypoint, MoveIt must
execute a normal collision-aware Cartesian action and the actuator-internal
broker must observe a continuous 100 ms, three-sample, bilateral contact
window on exactly one cylinder. This physical window is the sole stop signal.

The search starts at the existing 270 mm precontact offset and is bounded at
60 mm. No target pose, supervision label, entity identity, or simulator truth
may be used to select a stop point. A missing or unilateral contact window
fails closed: no close and no attach are allowed. The normal post-close
bilateral gate remains mandatory and unchanged.

## Revalidation

1. Run reset-isolated zero and Z-offset calibration probes with the new
   primitive.
2. Only if the probe observes the prescribed physical windows, re-run the
   complete 81-trial tolerance envelope with this exact primitive.
3. Re-run the unchanged offline p90 comparison. Only a `GO` permits the
   ADR-0013 round-trip and wrong-object acceptance drills.

