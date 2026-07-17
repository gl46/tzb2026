# M1B-alpha captured RGB-D dataset

On 2026-07-17, node2 generated and captured one RGB-D/camera-info observation
for each of 200 independently seeded `IndustrialCylinderBenchmarkV1` worlds.
The captured manifest contains 140 train, 30 validation and 30 held-out test
scene seeds. Each complete frame has its seed-specific SDF, a separate
offline-only supervision JSON, RGB PPM, 32FC1 depth bytes, camera intrinsics
and recording timestamps. The maximum intra-frame RGB/depth/camera skew was
198 ms, within the configured 200 ms window.

One first attempt (seed 1133) failed because no depth message arrived during
the window. It was retried under a separate Gazebo partition and succeeded;
the original worker log is preserved on node2. Raw frames, SDFs, supervision,
rosbags and logs remain Git-ignored.
