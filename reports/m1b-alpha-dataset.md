# M1B-alpha dataset status

The seed-disjoint manifest generator and live capture completed 200 real
Gazebo RGB-D/camera samples: 140 train, 30 validation, and 30 held-out test
scene seeds. Every recorded scene has a separately stored supervision JSON;
the online baseline never receives that file. The proposed held-out condition
is reflective material plus camera offset. No raw dataset is committed.

The missing evidence is instance mask/bbox ground truth and validated
camera-extrinsic association for correspondence metrics. See
`reports/m1b-alpha-dataset-capture.md` and
`reports/m1b-alpha-geometric-heldout.json`.
