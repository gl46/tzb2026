# ADR-0010: M1B alpha/beta split

Date: 2026-07-17

## Context

M1B must not let language execution or recovery obscure the prerequisite
non-oracle RGB-D evidence. `ADR-0004` is already the approved ROS/Gazebo
platform decision, so the requested M1B numbering cannot be reused.

## Decision

Alpha owns the industrial scene, synchronized recording, seed-disjoint data,
perception and offline evaluation. Beta may consume only `PerceptionResultV1`
and generic grasp feedback; it must not introduce a simulator truth dependency.
The Student world-model boundary is unchanged.

## Consequences

`reports/m1b-alpha-status.json` is the explicit Beta gate. A missing live
Gazebo recording or held-out evaluation makes `ready_for_m1b_beta=false`.
