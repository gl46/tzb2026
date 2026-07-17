# M1B-alpha non-Oracle perception evidence

The online RGB-D pipeline runs `GeometricRGBDBaseline` with independent RGB
colour-prototype masks. It accepts only `PerceptionInputV1` RGB, depth and
camera intrinsics, returns public hashed track IDs, category, 3D camera-frame
position, orientation state, confidence and relations, and neither imports nor
reads simulator supervision.

On 200 real V2 Gazebo captures, train-only calibration selected RGB cosine
similarity 0.95. On the independent 30-scene held-out split, the calibrated
pipeline achieved 96.7% valid output, zero median count error, 91.5% matched
track recall, 96.7% public-calibration leftmost target selection, and 2.17 cm
median 3D position error. The offline evaluator loads static camera calibration
and label files only after inference for association.

The old 0.97 setting recorded 6.0 median count error and 40.0% leftmost target
selection on the same held-out set, establishing a real post-training gain.
Orientation accuracy is only 37.1% because uniform normal/inverted cylinders
have no distinguishable end marker; Beta treats it as low confidence.

The optional Apache-2.0 GroundingDINO adapter is installed in an isolated
environment but has no downloaded checkpoint: its official Hugging Face
configuration URL timed out after 15 seconds. No pretrained or fine-tuned
GroundingDINO result is claimed. The executable fallback is the calibrated
RGB-D pipeline above.
