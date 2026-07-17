# M1B-alpha dataset status

The V2 non-overlapping generator and live capture completed 200 real Gazebo
RGB-D/camera samples: 140 train, 30 validation, and 30 held-out test scene
seeds. Every recorded scene has a separately stored supervision JSON; the
online baseline never reads that file. Raw frames remain Git-ignored.

The offline evaluator uses the fixed checked-in camera SDF calibration only
after online prediction to associate public tracks with labels. See
`reports/m1b-alpha-v2-calibrated-heldout.json`.
