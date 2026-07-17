# M1B-alpha perception status

`GeometricRGBDBaseline` performed a unit-tested finite-depth segmentation,
metric back-projection, orientation-state rule and public track generation.
It was then run against a live Gazebo snapshot at
`/home/gl/xh-202607-world-agent-codex-m1b/data/episodes/m1b-alpha-sync-v2-20260717/`.
The RGB-D geometric path returned four public tracks with no simulator entity
identifier in `perception-rgbd.json`.

The held-out evaluator then ran this same online pipeline on 30 real test
scenes. It produced at least one output in all cases, but median absolute
track-count error was 6.5 and every emitted orientation was `tilted`. This is
not a passing perception result and target/position/orientation correspondence
metrics are deliberately `null` pending validated camera/extrinsic truth
association.

The optional Grounding DINO adapter is deliberately fail-closed. An isolated
PyTorch CUDA dependency attempt stalled while downloading `nvidia-cudnn-cu12`
and was terminated before any model weight or GPU inference; no revision/hash,
pretrained result or fine-tuned checkpoint is claimed. The executable fallback
is `geometric_rgbd_v1`.
