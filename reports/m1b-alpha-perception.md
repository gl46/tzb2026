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

ADR-0013's later axis-wise audit was run against those actual captured frames,
not the manifest: all 30 held-out scenes yielded 235 matched public tracks.
Its absolute-error p90 is 9.88 mm / 15.13 mm / 17.30 mm on world X / Y / Z;
normal cylinders alone have a 17.35 mm Z p90. The complete per-track evidence
is in `m1b-alpha-perception-metrics.json`. The complete 81-trial,
perception-free calibration campaign is recorded in
`m1b-tolerance-envelope.json`: no axis passed the signed 2/3 monotonic
closure, so the empirical tolerance envelope is unmeasured on X, Y, and Z.
The actual p90-versus-0.6× comparison consequently records **NO_GO** in
`m1b-perception-reachability-gate.json` with
`TOLERANCE_UNMEASURED:x|y|z`. This is a grasp-primitive/hand-execution
finding, not a relaxation of the perception gate; round-trip and
WRONG_OBJECT acceptance remain unrun.

The optional Apache-2.0 GroundingDINO adapter is installed in an isolated
environment but has no downloaded checkpoint: its official Hugging Face
configuration URL timed out after 15 seconds. No pretrained or fine-tuned
GroundingDINO result is claimed. The executable fallback is the calibrated
RGB-D pipeline above.
