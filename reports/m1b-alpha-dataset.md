# M1B-alpha dataset status

The seed-disjoint manifest generator was exercised with 200 fixture records;
its 30 test seeds are a split-validation fixture, not a claim that 200 Gazebo
RGB-D samples or labels exist. The proposed held-out condition is reflective
material plus camera offset. No raw dataset is committed.

The missing evidence is actual per-seed Gazebo RGB/depth capture, masks/bboxes,
camera parameters and separate supervision labels. Until that exists,
`dataset_samples` and `heldout_scenes` remain zero in the authoritative status.
