# P0 constrained pick-place status

- Status: `VERIFIED_CONSTRAINED_PICK_PLACE` on `node2`.
- Initial / carried / final cube xyz: `[0.22, 0.12, 0.49999]` / `[0.527276, -0.041895, 0.507916]` / `[0.541972, -0.064194, 0.506301]`.
- Object inside bin after settle: **True**.
- Grasp is an explicit Gazebo DetachableJoint constraint, not a verified finger-contact grasp.
- Robot-link collisions are disabled for this primitive controller model; object/bin collisions remain physical.
