# M1B-alpha perception architecture

```text
ONLINE_OBSERVATION: RGB + depth + camera intrinsics
  -> geometric RGB-D components -> PerceptionResultV1 (public track ID, 3-D pose)
  -> optional open-vocabulary semantic proposal -> fusion
  -> Beta-facing policy / planner

ACTUATION_INTERNAL: contact manifold -> DetachableJoint routing -> generic tactile feedback

SIMULATOR_SUPERVISION: entity pose/contact/success -> offline evaluator only
```

The three channels are intentionally different processes/files. Online types
forbid extras, including perfect poses and simulator entity IDs. The evaluator
uses a private `SimulatorLabel` and returns aggregate metrics only.

The dataset split is computed from scene seed, never adjacent image frames.
The held-out combination is reflective material plus a camera offset. The
current recorder preserves a monotonic image/depth/TF/joint/perception timeline
and writes supervision separately.
