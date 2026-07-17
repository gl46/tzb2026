# M1B-alpha perception status

`GeometricRGBDBaseline` performed a unit-tested finite-depth segmentation,
metric back-projection, orientation-state rule and public track generation.
It was then run against a live Gazebo snapshot at
`/home/gl/xh-202607-world-agent-codex-m1b/data/episodes/m1b-alpha-sync-v2-20260717/`.
The RGB-D geometric path returned four public tracks with no simulator entity
identifier in `perception-rgbd.json`.

This is pipeline evidence only, not an accuracy result: the six-part scene
returned four candidates and all were classified `tilted`. It has not been
matched to offline truth or evaluated on held-out scenes.

The optional Grounding DINO adapter is deliberately fail-closed: no weights,
revision/hash, pretrained result or fine-tuned checkpoint has been claimed.
The executable fallback is `geometric_rgbd_v1`.
