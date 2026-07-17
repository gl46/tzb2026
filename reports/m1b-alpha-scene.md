# M1B-alpha industrial scene

`IndustrialCylinderBenchmarkV1` is a new standalone SDF and does not modify the
frozen M1A cube/bin world. It provides two incoming zones, visible normal,
inverted and tilted cylinders, a 2×3 partition bin, a table and RGB-D sensor.
The configuration declares all required randomization dimensions and future
geometry reservations. Runtime launch evidence is recorded separately; no
static SDF is treated as a successful Gazebo episode.
