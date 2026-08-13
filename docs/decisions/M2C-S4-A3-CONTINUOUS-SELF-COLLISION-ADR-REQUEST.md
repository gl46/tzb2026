# M2C S4 A.3 continuous self-collision — human ADR request

- Status: **POST-IMPLEMENTATION-AUDIT / NOT APPROVED**
- Decision type: **REQUEST FOR HUMAN DECISION; NOT AN APPROVED ADR**
- Date: 2026-08-13 (Asia/Shanghai)
- Governing decisions:
  `ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md` and
  `ADR-0022-m2c-exact-plan-primitives-and-b0-wrapper.md`
- Scope: ADR-0022 A.3 continuous self-collision geometry and algorithm only
- Recommendation: **Option B**
- Decision recorded by this request: **NONE**

This request was written after the non-actuating A.3 preflight contract had
been implemented and after a read-only audit of the installed node2
MoveIt/Bullet stack. It was not preceded or accompanied by physical
execution. The timing is disclosed so this request cannot be treated as a
pre-registration or used to approve existing code retroactively.

This request authorizes **no code**, **no collision-geometry replacement**,
**no binding addendum**, **no source-level binding**, **no deployment**, **no
SMOKE**, **no collection**, **no training**, **no model rollout**, and **no
Q-B evaluation**. It is not Phase-2 closure evidence. All four S4 unlock
bindings remain `None` unless a later accepted human ADR, complete
implementation, independent review, binding addendum, and contract smoke
satisfy their existing requirements.

## Why a human decision is required

The frozen controlled Panda URDF has fourteen collision elements: eleven
boxes, one cylinder, and two binary STL meshes. The two meshes are close to
convex but are not strictly convex under the post-implementation audit below.
Converting them to `btConvexHullShape` would create a conservative outer
envelope, but it would change the frozen collision geometry and can introduce
false rejections. ADR-0022 did not silently authorize that geometry change.

The installed Bullet 3.24 API exposes
`btContinuousConvexCollision::calcTimeOfImpact(fromA, toA, fromB, toB,
result)`, which can query simultaneous linear and angular motion for a pair of
strictly convex shapes. A direct child-pair loop can therefore avoid the
installed MoveIt `CollisionEnvBullet` limitation that continuous objects are
only checked against static objects. That API does not accept a non-convex
mesh as an exact convex shape, and a compound must be decomposed into its
convex children.

There is a second approximation boundary. The exact executor interpolates in
joint space, whereas one convex cast between two link-frame endpoints follows
Bullet's rigid-transform interpolation. A link's actual FK path over a joint
segment is generally curved. A valid conservative implementation therefore
needs a frozen deterministic joint-space subdivision rule and a proven error
envelope covering the difference between every true link path and every cast
segment. No authoritative values for that subdivision or error envelope are
available in the current evidence. This request does not invent them.

## Byte-bound post-implementation audit evidence

The following JSON block is evidence, not authorization. Paths are exact
paths observed during the audit. The two mesh paths are on `node2`; their
bytes are not vendored into this repository. A later implementation must
create a deployment closure that independently reopens and verifies every
required byte before use.

```json
{
  "schema_version": "M2CS4A3ContinuousSelfCollisionADRRequestEvidenceV1",
  "timing": "POST_IMPLEMENTATION_AUDIT",
  "approved_adr": false,
  "selected_option": null,
  "recommendation": "B",
  "authorization": {
    "code_change": false,
    "geometry_replacement": false,
    "binding_addendum": false,
    "source_binding": false,
    "deployment": false,
    "collection": false,
    "training": false,
    "smoke": false,
    "model_rollout": false,
    "q_b_evaluation": false,
    "physical_execution": false,
    "reinterpret_existing_evidence": false
  },
  "robot_asset": {
    "relative_path": "robot_ws/src/xh_sim/urdf/panda_controlled.urdf",
    "sha256": "6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8",
    "collision_element_count": 14,
    "box_count": 11,
    "cylinder_count": 1,
    "mesh_count": 2
  },
  "mesh_assets": [
    {
      "host": "node2",
      "path": "/opt/ros/jazzy/share/moveit_resources_panda_description/meshes/collision/link2.stl",
      "sha256": "370f7605a0fae3529db169ded50f52f171024aa792d4d773bc84197301f6a039",
      "size_bytes": 15084,
      "mode_octal": "0644",
      "nlink": 1,
      "triangle_count": 300,
      "unique_vertex_count": 152,
      "convex_hull_vertex_count": 152,
      "convex_hull_facet_count": 300,
      "closed_mesh_edge_incidence_values": [2],
      "non_supporting_triangle_face_count": 39,
      "max_two_sided_triangle_plane_distance_m": 0.0004687523208006362,
      "convex_hull_volume_m3": 0.00300430300848,
      "oriented_mesh_volume_m3": 0.00300425409289,
      "convex_hull_minus_mesh_volume_m3": 4.891558626120979e-08,
      "relative_convex_hull_volume_increase": 1.628184178592562e-05,
      "strictly_convex_under_audit": false
    },
    {
      "host": "node2",
      "path": "/opt/ros/jazzy/share/moveit_resources_panda_description/meshes/collision/link4.stl",
      "sha256": "0180ebb5772ec9840cb049750cffb29a9ddc90311752a16ea34757782ef9e48d",
      "size_bytes": 15084,
      "mode_octal": "0644",
      "nlink": 1,
      "triangle_count": 300,
      "unique_vertex_count": 152,
      "convex_hull_vertex_count": 152,
      "convex_hull_facet_count": 300,
      "closed_mesh_edge_incidence_values": [2],
      "non_supporting_triangle_face_count": 29,
      "max_two_sided_triangle_plane_distance_m": 0.000464047136033791,
      "convex_hull_volume_m3": 0.00237399354433,
      "oriented_mesh_volume_m3": 0.00237380691791,
      "convex_hull_minus_mesh_volume_m3": 1.8662641138337752e-07,
      "relative_convex_hull_volume_increase": 7.861285546861829e-05,
      "strictly_convex_under_audit": false
    }
  ],
  "mesh_audit_provenance": {
    "input_format": "binary STL",
    "numeric_type": "IEEE-754 float64 audit arithmetic",
    "numpy_version": "1.26.4",
    "scipy_version": "1.11.4",
    "convex_hull_implementation": "scipy.spatial.ConvexHull with qhull_options=Qt",
    "supporting_face_test_tolerance_m": 1e-08,
    "two_sided_metric_definition": "For each oriented input triangle plane, compute signed distances of every unique mesh vertex. A triangle is non-supporting when vertices occur on both sides beyond the stated tolerance. The reported distance is max over those triangles of min(-minimum_signed_distance, maximum_signed_distance).",
    "volume_definition": "Convex-hull volume from scipy.spatial.ConvexHull; oriented closed-mesh volume from the absolute sum of centroid-shifted signed tetrahedron volumes."
  },
  "byte_bindings": [
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btConvexCast.h",
      "sha256": "5eca7f5931c6f954dc4d8b58ff75ec58112c46f96783b1c8de5a117c663a6c6b"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btContinuousConvexCollision.h",
      "sha256": "7ba73189495d70659b257899352f3688585d8bff536db11f8c86cfa6931fe2e4"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btGjkConvexCast.h",
      "sha256": "3409007ce88c742edba270851d8122fead8c766febf2de193525e0cc2a4694db"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btSubSimplexConvexCast.h",
      "sha256": "74ffb324a2268abeca5c6757c09b238240be5de12a10f7443652df3f52d1c876"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btVoronoiSimplexSolver.h",
      "sha256": "5771fe6eb5b51e91ca83c00c746216b821920b7a147875e01422add194e81805"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/NarrowPhaseCollision/btGjkEpaPenetrationDepthSolver.h",
      "sha256": "bc5e3baf33e296de9367c247b25b9cd8803decee3d57896f87ec161568bedff0"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/CollisionShapes/btConvexShape.h",
      "sha256": "8d636b8b1ef7ec75926d48b03a4a448a44373ecf362329ce2150586bae4fb0c9"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/CollisionShapes/btConvexHullShape.h",
      "sha256": "209211f19fa98cc6a085d95266c4c15ee8a2bf3be5cc29403d858e8f26e97929"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/CollisionShapes/btBoxShape.h",
      "sha256": "8ec85f0c79e746088a186979c174a1ec5007a150e5281030f2e8321e4c1eeac7"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/CollisionShapes/btCylinderShape.h",
      "sha256": "097a80dbf01b8f5add103a0802ffab1201c285e7aaaf2aef8d94c17c193f6167"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/BulletCollision/CollisionShapes/btCompoundShape.h",
      "sha256": "34413f9e250e66ec5f12f9c6e96c16b5f9eb06e842961c08085475b4c1478357"
    },
    {
      "host": "node2",
      "path": "/usr/include/bullet/LinearMath/btTransformUtil.h",
      "sha256": "add9774d16afa59c5cf0529df82133712cad28411e952b9c4cc00ffa8bfa37ee"
    },
    {
      "host": "node2",
      "path": "/usr/lib/x86_64-linux-gnu/libBulletCollision.so.3.24",
      "sha256": "a356d9ef207a31737b91a39c4c75a43b05a49cde51891cfa13b4b1c71c223f0a",
      "scalar_abi": "float32"
    },
    {
      "host": "node2",
      "path": "/usr/lib/x86_64-linux-gnu/libLinearMath.so.3.24",
      "sha256": "31c7e0d2d17efc3924613bf561a645a4258f2d8df54167c162c490ed7fe84fea",
      "scalar_abi": "float32"
    },
    {
      "host": "node2",
      "path": "/usr/lib/x86_64-linux-gnu/libBulletCollision-float64.so.3.24",
      "sha256": "baa16598bc6a54aa51c825af6680807b548decb33ff11f469ac24c09f54826c2",
      "scalar_abi": "float64"
    },
    {
      "host": "node2",
      "path": "/usr/lib/x86_64-linux-gnu/libLinearMath-float64.so.3.24",
      "sha256": "5d3fe859ad08f78fac1e51ed85dddd9e39da501a0d566e86e00da5565d9e5343",
      "scalar_abi": "float64"
    },
    {
      "host": "node2",
      "path": "/opt/ros/jazzy/include/moveit_core/moveit/collision_detection_bullet/collision_env_bullet.hpp",
      "sha256": "854490de97d56df89776e19dcf4d6d002581c97999d6ac2cb3c7d632f68e05a3"
    },
    {
      "host": "node2",
      "path": "/opt/ros/jazzy/include/moveit_core/moveit/collision_detection_bullet/bullet_integration/bullet_cast_bvh_manager.hpp",
      "sha256": "61983e8368a2bc27b177878e938b3ef586df5e613572129122777330001bed9c"
    },
    {
      "host": "node2",
      "path": "/opt/ros/jazzy/include/moveit_core/moveit/collision_detection_bullet/bullet_integration/bullet_utils.hpp",
      "sha256": "6cbe046d26efaae309a9f84984f9583c95cc0457c3bb871bdea71a7afd852b14"
    },
    {
      "host": "node2",
      "path": "/opt/ros/jazzy/lib/libmoveit_collision_detection_bullet.so.2.12.4",
      "sha256": "4b3a6d8673e59b4c2c68189b1e649d3fb6c3412d6689e3eebdbf5c955e303106"
    }
  ],
  "installed_versions": {
    "bullet": "3.24+dfsg-2.1build1",
    "moveit_core": "2.12.4",
    "moveit_resources_panda_description": "3.1.0"
  },
  "licenses": {
    "xh_sim": "Apache-2.0",
    "moveit_core": "BSD-3-Clause",
    "moveit_resources_panda_description": "BSD",
    "bullet_core": "Zlib; distribution contains separately identified third-party license subsets"
  }
}
```

The `max_two_sided_triangle_plane_distance_m` value is the explicitly defined
audit diagnostic above; it is not a certified Hausdorff distance and must not
be relabelled as one. Likewise, the convex-hull volume comparison is evidence
that the mesh is not exactly its convex hull, not a tolerance proposal.

## Mutually exclusive options

The approver must select exactly one of A, B, or C. No option is selected by
this request. A hybrid, partial selection, or omitted numeric field is not an
approval.

### A — authorize a conservative convex-hull envelope and bounded pairwise Bullet CCD

Authorize replacing only the two byte-bound STL collision shapes with the
convex hull of every decoded STL vertex, solely for A.3 preflight. The hull is
a conservative outer envelope; it may reject a physically clear path and may
never be used to claim geometry equality. The exact executor geometry, B0,
and previously recorded evidence remain unchanged.

The approving ADR must also authorize and freeze a direct child-by-child
`btContinuousConvexCollision` implementation for every non-ACM robot-link and
attached-object pair. Compound shapes must be expanded into all convex child
pairs. Any unknown, concave, malformed, non-finite, unbound, or unsupported
shape fails the whole plan before actuation. Initial overlap, both endpoints,
and every subdivision boundary require separate frozen discrete checks.

Option A is incomplete unless the human supplies every numeric value and its
authoritative provenance below. `UNSET_HUMAN_REQUIRED` is deliberately not a
number and does not authorize a default, library constant, measured guess, or
implementation-selected value.

| Required frozen parameter | Human-approved value | Required provenance |
|---|---|---|
| Bullet scalar ABI (`float32` or `float64`) | `UNSET_HUMAN_REQUIRED` | exact package, headers, binaries, compiler flags and ABI closure |
| convex-hull construction tolerance (m) | `UNSET_HUMAN_REQUIRED` | audited hull implementation and source/hash |
| convex-hull post-construction padding (m) | `UNSET_HUMAN_REQUIRED` | safety argument tied to bound geometry |
| collision shape margin per shape type (m) | `UNSET_HUMAN_REQUIRED` | Bullet/config source and validation |
| allowed penetration (m) | `UNSET_HUMAN_REQUIRED` | safety owner approval |
| contact-distance threshold (m) | `UNSET_HUMAN_REQUIRED` | algorithm/config source |
| accepted TOI fraction interval and comparison tolerance | `UNSET_HUMAN_REQUIRED` | numeric analysis and regression cases |
| maximum CCD iterations | `UNSET_HUMAN_REQUIRED` | bound implementation and failure analysis |
| CCD convergence epsilon | `UNSET_HUMAN_REQUIRED` | bound implementation and scale analysis |
| per-arm-joint subdivision limit (rad) | `UNSET_HUMAN_REQUIRED` | joint-space path proof |
| per-gripper-joint subdivision limit (m) | `UNSET_HUMAN_REQUIRED` | gripper path proof |
| maximum link translation chord error (m) | `UNSET_HUMAN_REQUIRED` | FK/Jacobian or interval bound over all joint limits |
| maximum link rotation interpolation error (rad) | `UNSET_HUMAN_REQUIRED` | FK/Jacobian or interval bound over all joint limits |
| conservative error inflation applied to each child (m) | `UNSET_HUMAN_REQUIRED` | proof that it dominates path and numeric error |
| maximum transform rotation per cast segment (rad) | `UNSET_HUMAN_REQUIRED` | Bullet interpolation/robustness evidence |
| maximum transform translation per cast segment (m) | `UNSET_HUMAN_REQUIRED` | Bullet interpolation/robustness evidence |
| non-finite, iteration-exhaustion, degeneracy and initial-overlap semantics | `UNSET_HUMAN_REQUIRED` | explicit fail-closed decision |
| exact ACM and attached-object touch allowlist | `UNSET_HUMAN_REQUIRED` | accepted safety configuration digest |

The approving ADR must freeze the deterministic subdivision algorithm itself,
not only a step count: start/end inclusion, per-joint rounding, mimic-joint
handling, fixed-joint child transforms, FK implementation, ordering, maximum
subdivision count, timeout, and behavior at the cap. It must prove that the
inflated casts cover the complete joint-space trajectory between every
adjacent executor sample. It must also freeze complete evidence receipts for
every segment and pair, including both shape digests, four transforms, ACM
decision, TOI result, numeric configuration digest, and failure code.

No number from the audit block, Bullet header, existing preflight fixture, or
old experiment may be copied into this table without a human-approved source
and rationale. Because those values are presently unavailable, this request
does **not** recommend A.

### B — require exact original-geometry continuous self-collision and remain blocked (recommended)

Do not authorize either STL-to-convex-hull replacement or any other collision
geometry substitution. Require a reviewed query-only implementation that
checks the exact byte-bound original link2/link4 geometry, all primitive
elements, all compounds, and every eligible attached object over the complete
joint-space trajectory, including moving-versus-moving self collision.

Until that implementation has frozen source, dependency and asset closure;
complete numeric tolerances and failure semantics; adversarial tests; active-
session input binding; and a human-approved binding addendum, every affected
phase remains `INVALID / NO_PHYSICAL_EXECUTION`. Discrete subsampling, endpoint
checks, a convex hull, or a claim that the measured concavity is small does
not satisfy B.

B is recommended because it preserves the accepted geometry semantics and
does not ask the human to approve numeric bounds for which this audit has no
authoritative provenance. It may keep S4 blocked indefinitely; that is an
explicit and acceptable fail-closed outcome.

### C — require another complete human-specified A.3 contract

Reject both A and B and provide a different complete A.3 contract in a new or
superseding human ADR. The contract must identify exact geometry semantics,
full continuous self-collision coverage, attached-object behavior, joint-path
coverage, every numeric margin/tolerance/timeout, algorithms and source
digests, immutable evidence schema, active-session inputs, failure behavior,
licenses, deployment closure, and its relationship to ADR-0022.

An implementation suggestion, named library, partial parameter list, or
permission to “use conservative settings” is not a complete C selection. The
system remains blocked until the complete contract is accepted and verified.

## Non-negotiable boundaries for every option

- This request does not modify, weaken, wrap, or reinterpret B0.
- No existing safety gate may be removed, bypassed, weakened, or converted
  from fail-closed to best-effort.
- The model-owned path remains separate from unchanged-B0 attribution.
- Teacher labels, Teacher soft outputs, and Teacher runtime components are
  forbidden. Teacher kill rules remain active; this audit used no Teacher.
- Privileged simulator entity/prim identity, perfect pose, collision truth,
  contact truth, attachment truth, success truth, or final task truth may not
  become policy input. Query-only preflight evidence remains audit/gate data,
  never model observation.
- A geometry or collision implementation cannot replace world-model
  prediction and selection.
- Old S2 V4, B0, scripted, SMOKE, model, or Q-B evidence retains its original
  meaning. Nothing in this request may relabel old evidence as exact-plan,
  continuous-self-collision, model-owned, successful, failed, or entry-
  eligible evidence.
- No fixture, mock, discrete-only check, endpoint-only check, or generated
  receipt can satisfy a real physical/deployment binding.

## Human approval fields

- Selected option: `NONE` (`A | B | C`, exactly one required)
- Accepted ADR path and immutable commit: `NONE`
- Option A numeric table complete with provenance: `NO`
- Exact geometry semantics approved: `NO`
- Continuous joint-path error bound approved: `NO`
- Exact implementation/dependency/container/assets approved: `NO`
- Active-session input and attestation contract approved: `NO`
- Phase-2 binding addendum approved: `NO`
- Does this request authorize code or geometry replacement?: **NO**
- Does this request set any S4 source-level binding?: **NO**
- Does this request authorize collection, training, SMOKE, model rollout, or
  Q-B evaluation?: **NO**
- Approver/date: `UNSET`

## Current result

`BLOCKED / NOT APPROVED / NO_PHYSICAL_EXECUTION`

The next authorized activity is human review of exactly one option. In the
absence of that decision, the existing fail-closed implementation and all
four `None` bindings remain unchanged.
