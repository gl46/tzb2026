# ADR-0024 Phase-2 binding addendum candidate — CONTRACT_SMOKE_ONLY

- Status: **CONTRACT_SMOKE_ONLY / BLOCKED_UNMEASURED**
- Checkpoint: **2026-08-20 (Asia/Shanghai)**
- Production binding authorized: **false**
- Physical or formal evidence produced: **false**
- Teacher used: **false**
- Privileged simulator truth used as policy input: **false**

This file is a machine-audited candidate, not an accepted binding addendum and
not a production configuration. It records the locally testable portion of
ADR-0024 Phase-2 while all four compatibility/entry assignments remain literal
`None`. It must not be renamed or reinterpreted as
`ADR-0022-BINDING-ADDENDUM.md`; that formal artifact can exist only after real
deployment and eight-skill evidence satisfies the project evidence bar.

## What the local contract smoke proves

- `M2CExactPlanPrimitiveBundleV1` binds ADR-0022 plus the superseding accepted
  ADR-0024, keeps each exact phase immutable, preflights all phases before an
  executor call, and never replans, inserts, retries, or changes a failed plan.
- A.3 decodes the exact controlled Panda URDF/SRDF and only the byte-bound
  link2/link4 STL assets; it expands every collision element into canonical
  children, retains every decoded STL vertex for the conservative hull, and
  binds all numeric configuration, geometry, FK inputs/outputs, native source,
  headers, compiler flags, float64 libraries, build manifest, and receipts.
- The flat native ABI is query-only, rejects unknown/non-finite/degenerate
  shapes, separately checks start/end distance, and never treats an ambiguous
  `calcTimeOfImpact == false` as clear without an independent conservative
  motion-disc certificate.
- ADR-0024 section 2 is the only runtime rejection policy: invalid mapping,
  stale pointer, invalid cell, failed gate, or failed preflight terminates as
  `NO_PHYSICAL_EXECUTION`. It is not a hold, retry, substitute skill, or B0
  action and can never be relabelled `B0_FALLBACK`.

These are contract properties only. They do not prove a native build, real FK,
Isaac startup, physical safety, execution success, model-owned success, or
entry readiness.

The real-Isaac exact-plan executor implementation is present and contract
tested. It calls only the hash-frozen execution helpers and cannot select a
yaw, centreline, retry, fallback, or replacement command at runtime. This does
not make it deployable: its reviewed deployment binding remains absent, and
the real episode lifecycle/capture source is not bound.

The eight-skill plan-synthesis implementation is now present at
`src/xh_agent/policy/qrm_lite/formal_exact_plan_synthesis_v1.py`. Its contract
suite constructs `GRASP`, `LIFT`, `MOVE`, `PLACE`, `RELEASE`, `REOBSERVE`,
`REASSOCIATE_TARGET`, and `REGRASP` from the replayed public observation, the
frozen runtime mapping, and one query-only active-session state. It freezes a
single public free-gap yaw, one contact centreline, every waypoint/gripper
target/step count, all allowlist digests, and zero retries before returning a
plan. Side/oblique grasp geometry, stale or crossed state, absent attachment,
missing registry destination, and unsafe free-gap geometry all reject without
producing a plan. The exact numeric candidate is
`configs/m2c_exact_plan_synthesis_candidate_v1.json`; its transitive source
closure is `configs/m2c_exact_plan_synthesis_dependencies_v1.json` and its
implementation base commit is `d00c1a4e6ac29049125e2ed62ae479d4d3397bb0`.

The query-only composition contract is also present at
`src/xh_agent/policy/qrm_lite/formal_isaac_plan_synthesis_query_v1.py`. It
creates one fresh single-use articulation/pose provider per decision while
sharing the persistent scene-owner mutation counter, binds the active-session
read receipt and complete scene inventory into the plan state, and rejects any
crossed session, target, attachment, timestamp, or mutation. Simulator paths
are explicitly gate-only and never exposed to Qwen or used to select a skill
or public pointer.

This closes the generic query-source implementation/schema portion only. The
repository still has no reviewed producer for the public-track-to-collision-
path A.3 safety binding; the bridge deliberately does not guess that mapping.
There is also no reviewed production deployment receipt or eight-skill
physical evidence, so the candidate remains non-executable and the production
bindings remain `None`.

The generic formal V4 episode-I/O contract is now implemented at
`src/xh_agent/policy/qrm_lite/formal_isaac_episode_io_v4.py`. One shared
persistent scene owner must provide the public failure-boundary evidence, all
eight ordered public captures and the final public evaluation. Each lifecycle
transition is single-use and fail-closed, capture-prefix replay is exact, and
the source tree plus immutable Git commit are verified before the owner is
contacted. This closes the lifecycle/capture schema and composition gap only:
there is no reviewed real-Isaac deployment binding, real scene owner or HTTP
backend-factory binding, so the adapter remains non-executable and produces no
physical evidence.

## A.3 delegated numeric configuration

The candidate binds configuration digest
`8c6ba840339bca5a84ccd805b0c068439d59812eb0c3ecc9bdd809f1341d4bb5`:

- Bullet 3.24 scalar ABI `float64`; `BT_USE_DOUBLE_PRECISION`, no fast-math;
- hull construction tolerance `1e-7 m`;
- outward-only post-construction padding `0.002 m`;
- primitive margins reproduce Bullet 3.24's shipped `setSafeMargin` formula
  per concrete shape instance; the exact governed-Panda maxima are
  `0.0055074 m` for boxes and `0.008 m` for the cylinder, while each convex
  hull uses the shipped `0.04 m`; every payload independently proves it is no
  smaller than its actual constructor default;
- allowed penetration `0.0 m` and contact rejection threshold `0.001 m`;
- TOI interval `[0,1]`, rejection-biased comparison tolerance `1e-7`;
- native/declared maximum iterations `64`; exhaustion rejects;
- subdivision cap `4096`, using each child maximum angular-motion radius and
  the pair's smallest conservative radius; cap/ambiguity rejects;
- query timeout `5,000,000,000 ns`.

The machine config binds the exact source and asset digests. The original STL
bytes and pinned Bullet float64 runtime were replayed in the independent
query-only build report `reports/m2c-phase2-a3-native-build.json`. Builder image
`sha256:01d3c57b…` produced native module `2231cee6…`; the controlled Panda
URDF/SRDF and both STL files replay to exactly 14 collision children. This
closes the asset/native-build availability blockers, but it is not physical
evidence and does not make formal execution eligible.

The controlled-Panda read-only FK implementation is complete at the
contract/equivalence layer. A separately compiled node2 verifier using ROS
Jazzy `kdl_parser` and Orocos KDL 1.5.1 compared 12 frozen states across all
12 collision-bearing link frames (144 transforms). Maximum translation error
was `2.5438405243138006e-16 m`; maximum relative-quaternion orientation error
was `5.147892387644517e-16 rad`, both below the frozen `1e-12` tolerances.
The exact report is `reports/m2c-phase2-a3-controlled-panda-fk.json`. This
closes provider implementation/numeric equivalence, not its immutable
deployment/session binding.

ADR-0025 section 2 authorizes exactly two start-state ACM additions. The
controlled SRDF adds `panda_hand`–`panda_link7` with reason `Adjacent` and
`panda_link2`–`panda_link4` with reason `Never`; it removes no pair. Each
addition uses criterion `A_OFFICIAL_UPSTREAM_SRDF` against node2 path
`/opt/ros/jazzy/share/moveit_resources_panda_moveit_config/config/panda.srdf`,
SHA-256
`1150719ea9d81139418198a50faea17e155323547d056c4edcb7ecc82fd8d317`,
package `ros-jazzy-moveit-resources-panda-moveit-config` version
`3.1.0-1noble.20260615.174424`, package-deb SHA-256
`f9ae0802676e10b6532d73ad7657d53b40fa6a8106b4ffdc6e13e80f36794917`.
Neither pair uses original-mesh criterion (b), so no kinematic-permanence claim
is needed. There is no wildcard/category disable and no margin, padding, hull,
or threshold change. The exact source audit is
`reports/m2c-phase2-a3-acm-adr0025.json`.

The corrected query-only deployment path was then byte-replayed under the
pinned Isaac 6 container image without loading Kit or Isaac. The create-only
receipt SHA-256 is
`146e2b25a02ecfd87fc04bcb88cf56d43a965dd3b6f39ab18b7786ec666b4be1`.
All 74 governed child-pair requests were clear, with zero collision rejections
and zero query failures; `static_state_preflight_clear=true`. The audit is
`reports/m2c-phase2-a3-acm-smoke.json`. This closes the specific static-start
ACM blocker and the query-only native path. It is not an execution
authorization: every real bound plan must still pass the full plan-specific
A.3 replay before any command, and the real eight-skill/deployment evidence
listed below remains absent.

The preflight coordinator now defines `ExactPlanA3DeploymentBindingV2`. It
implements ADR-0024 section 4 directly: trusted-host signatures and launcher
attestation are not prerequisites. The reviewed binding instead covers the
accepted ADR, addendum and unlock config, immutable implementation commit and
container, exact plan source set, complete A.3 configuration, query callback,
session-audit implementation, and host-local HMAC verifier. A successful
authorization still claims no physical action; the real session-bound phase
and bundle receipts plus post-execution HMAC replay remain required evidence.

The candidate also contains a single-use all-phase callback composition. It
enforces runtime-snapshot -> query-only path -> swept-collision -> planned
attachment order for every phase, poisons on retry or active-session mutation,
and requires attached-object geometry on every subsequent motion phase. Its
collision interface deliberately requires both complete continuous-self and
complete robot/environment scene coverage; the standalone Bullet self-CCD
provider cannot satisfy that interface by itself.

The versioned complete-scene contract now byte-replays the generated SDF and
supervision, rejects every unknown collision-bearing model or unsupported
shape, and expands the frozen V4 scene into six dynamic cylinders plus the
work-table and partition-bin collision primitives. A getter-only scene-state
receipt binds all eight active-session link poses to the same mutation counter
as the robot snapshot. The V2 world composer removes an attached target from
the ordinary environment exactly once, keeps attached-object/environment and
robot/environment pairs in the float64 child-pair product, excludes only
environment/environment pairs and contact pairs already frozen by the exact
phase, and independently replays the aggregate receipt in preflight.

The real-Isaac scene-owner implementation now constructs that exact eight-link
getter-only source after the natural-stability boundary. It activates one
host-owned monotonic mutation counter only after all scene handles exist and
records every subsequent public-capture Kit step before the call. The planned
attached-object resolver separately binds the canonical ATTACH transition
evidence, the complete scene geometry/state receipt, the terminal hand/object
relative transform and every later end-effector path sample. Each complete
scene CCD receipt must embed the corresponding derivation evidence and match
it one-for-one to the attached geometry; missing or self-consistent-but-unbound
geometry rejects before the native query. Unknown initial attachments and any
source mutation also reject. These properties are covered by local contract
tests only. No Isaac process was started, no real scene-state or attached-object
receipt was produced, and the resolver is not yet composed into the unbound
formal V4 HTTP backend factory, so the composition remains non-authorizing.

The V4 host-local HMAC verifier and create-only CLI now replay both sides of a
terminalized episode without any SSH signature, trust root, or signer
principal. They bind the one-shot challenge receipt, formal evidence, exact
Qwen/Isaac audit lifecycle, every authenticated envelope, and variable counts
for one through eight model decisions. This is still contract-only: no real
node2 or labserver receipt exists and the V4 Isaac HTTP backend factory is
unbound. The ADR-0024 V2 readiness verifier is implemented and remains
fail-closed until its exact real-evidence index is supplied.

The S4 entry gate now accepts a versioned V3 physical envelope only by
independently replaying that same Phase-2 evidence index. It cross-binds the
formal V4 run, one-shot challenge, two host-local HMAC receipts, immutable
deployment closure, all eight real-Isaac skill validations, and the frozen
SMOKE identity. The historical V2 path remains unchanged; neither path can
authorize while the two active production bindings remain `None`.

## B0 boundary

`FrozenB0FallbackWrapperV1` and ADR-0022 A.5 are withdrawn by accepted
ADR-0024 section 2. They are not prerequisites and are not callable from the
formal runtime. The M2B B0 freeze remains unchanged as the independent
comparison arm in separate episodes. This candidate modifies neither B0 bytes
nor any safety/IK/collision/controller gate.

## Production bindings

- `FORMAL_PHYSICAL_RUNNER_BINDING = None`
- `FORMAL_DEPLOYMENT_CLOSURE_BINDING = None`
- `FROZEN_B0_RUNTIME_WRAPPER_BINDING = None` (withdrawn compatibility sentinel)
- `OFFLINE_WIRE_AUTHENTICATION_VERIFIER_BINDING = None` (withdrawn compatibility sentinel)

## Blocking evidence

- `EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING`
- `REAL_PUBLIC_TRACK_TO_COLLISION_PATH_A3_SAFETY_BINDING_NOT_BOUND`
- `REVIEWED_EXACT_PLAN_SYNTHESIS_DEPLOYMENT_NOT_BOUND`
- `REVIEWED_REAL_ISAAC_EPISODE_IO_DEPLOYMENT_NOT_BOUND`
- `REAL_FORMAL_V4_ISAAC_HTTP_SERVICE_BACKEND_FACTORY_NOT_BOUND`
- `IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING`
- `COMPLETE_SCENE_ENVIRONMENT_SWEPT_COLLISION_PROVIDER_NOT_BOUND`
- `REAL_ATTACHED_OBJECT_PHASE_GEOMETRY_RESOLVER_NOT_BOUND`
- `REAL_EXACT_PLAN_ISAAC_EXECUTOR_DEPLOYMENT_BINDING_MISSING`
- `REAL_QUERY_ONLY_FK_PROVIDER_DEPLOYMENT_BINDING_MISSING`
- `REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING`
- `TWO_ACTIVE_PRODUCTION_BINDINGS_UNSET`

No training, Isaac scene startup, physical action, Q-B, or S5/S6 evaluation
was performed while generating this candidate. The A3 run was a query-only
contract smoke with zero target writes, simulation steps, or scene mutations.
No Teacher entered the control path; Teacher kill rules remain unchanged.

## One next command

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_adr0024_phase2_candidate.py --project-root .
```
