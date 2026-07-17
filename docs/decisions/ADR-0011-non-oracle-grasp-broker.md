# ADR-0011: Non-oracle grasp broker contract

Date: 2026-07-17

`ADR-0005` is already reserved for MoveIt/Gazebo model unification. This ADR
adds no model/control change; it defines a data boundary.

The high-level policy carries only `track-<hash>` from RGB-D perception. The
actuation-internal broker may map verified physical contact to a
DetachableJoint entity, but returns only `grasp_success`, generic tactile state
and a re-observed carried track. `actual_sim_entity_id` and wrong-object truth
are evaluator-only supervision fields. No entity name is part of the public
feedback contract.
