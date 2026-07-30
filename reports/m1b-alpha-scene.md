# M1B-alpha industrial scene

`IndustrialCylinderBenchmarkV1` is a new standalone SDF and does not modify the
frozen M1A cube/bin world. It provides two incoming zones, six visible normal,
inverted and tilted cylinders, a 2×3 partition bin, a table and RGB-D sensor.
The configuration declares all required randomization dimensions and future
geometry reservations. A live `node2` launch successfully created the Panda and
its joint/arm/hand controllers; runtime logs are in the isolated remote
worktree. The current SDF is seed-fixed, so it is not yet randomization proof.
