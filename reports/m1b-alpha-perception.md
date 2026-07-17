# M1B-alpha perception status

`GeometricRGBDBaseline` performed a unit-tested finite-depth segmentation,
metric back-projection, orientation-state rule and public track generation.
The test uses a small in-memory depth fixture and is not an industrial
held-out result. The scene's Gazebo RGB-D topics were observed live, but those
depth frames have not yet been fed through the baseline/evaluator.

The optional Grounding DINO adapter is deliberately fail-closed: no weights,
revision/hash, pretrained result or fine-tuned checkpoint has been claimed.
The executable fallback is `geometric_rgbd_v1`.
