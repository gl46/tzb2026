# M1B-alpha captured RGB-D dataset

On 2026-07-17, node2 generated and captured one RGB-D/camera-info observation
for each of 200 independently seeded non-overlapping V2
`IndustrialCylinderBenchmarkV1` worlds.
The captured manifest contains 140 train, 30 validation and 30 held-out test
scene seeds. Each complete frame has its seed-specific SDF, a separate
offline-only supervision JSON, RGB PPM, 32FC1 depth bytes, camera intrinsics
and recording timestamps. The maximum intra-frame RGB/depth/camera skew was
198 ms, within the configured 200 ms window.

Several first attempts had missing RGB, depth or camera-info messages during
the window. The finite three-attempt recorder retried those seeds under
isolated Gazebo/DDS partitions; every completed manifest entry contains all
three channels. The original worker logs, raw frames, SDFs, supervision,
rosbags and videos remain Git-ignored on node2.
