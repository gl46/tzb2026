# M2C S4 public-track re-identification — human ADR request

- Status: **HUMAN DECISION REQUIRED — NOT APPROVED**
- Written: 2026-08-13 (Asia/Shanghai)
- Timing disclosure: **POST-OUTCOME**. This request was written after the
  scene-16073 TRAIN collection outcome and after inspecting its public RGB-D
  captures, public tracks, physical receipt, and frozen public predicate.
- Parents: `ADR-0020-m2c-coarse-intent-v2-model-owned-chain.md` and
  `ADR-0021-m2c-public-semantic-candidate-contract.md`
- Decision recorded by this request: **NONE**
- Teacher used to produce this request: **false**

This document is a request for one mutually exclusive human choice. It is not
an accepted ADR and does **not** authorize code changes, data collection,
training, SMOKE, model rollout, Q-B evaluation, physical execution, threshold
tuning, or reinterpretation of any existing evidence. Until a separate human
ADR is accepted, PATH_BLOCKED collection under a changed tracker remains
blocked.

## Byte-bound post-outcome evidence

The finding below is bound to the exact create-once scene-16073 probe. Decimal
values are copied from or deterministically recomputed from its public records;
they are diagnostic evidence, not authorization to choose a new threshold.

```json
{
  "schema_version": "M2CS4PublicTrackReidADRRequestEvidenceV1",
  "timing": "POST_OUTCOME",
  "outcome_observed_before_request": true,
  "scene_seed": 16073,
  "probe": {
    "relative_evidence_path": "batch03-01/train/m2c-s4-v3-train-a101b1d9d220dfd6f293d1eab337e412b29b48a61759b5baef1ef8b2ad6ba5d2/probe/actuation-probe.json",
    "sha256": "f190bb44c1533ec4b4a37cbaf84955485fee073ee91e0f9d112a1b8009a057cb"
  },
  "tracker_v1": {
    "source_component": "public_temporal_tracker_v1",
    "maximum_association_distance_m": 0.12,
    "matching_fields": [
      "category",
      "visual_color",
      "position_3d"
    ]
  },
  "public_track_positions_world_m": {
    "step_05_predicate_reference_track_e91f94dc": [
      -0.14005755300078382,
      0.13408813104562534,
      0.47628142647265137
    ],
    "step_07_pre_lift_track_e91f94dc": [
      -0.11682349276180826,
      0.1225642649557751,
      0.5053438567809407
    ],
    "after_lift_original_site_detection_track_e91f94dc": [
      -0.15403995402420922,
      0.1413586115731421,
      0.4601678988026292
    ],
    "after_lift_carried_detection_track_e4beb00e": [
      -0.12088295459187304,
      0.10607088798171405,
      0.678816859790435
    ]
  },
  "association_diagnostics_m": {
    "step_07_to_original_site_detection": 0.06147486993014053,
    "step_07_to_carried_detection": 0.17430259174059995
  },
  "frozen_public_predicate": {
    "maximum_original_site_motion_m": 0.03,
    "step_05_to_original_site_detection_m": 0.02253914815279092,
    "hand_vertical_lift_m": 0.16424095630645752,
    "target_hand_xy_error_m": 0.034575710801854835,
    "predicates": [],
    "final_task_success": false
  },
  "physical_receipt": {
    "status": "LIFTED",
    "object_lift_m": 0.16423627734184265,
    "follow_error_m": 0.004680934429056637
  },
  "authorization": {
    "approved_adr": false,
    "code_change": false,
    "collection": false,
    "training": false,
    "smoke": false,
    "model_rollout": false,
    "q_b_evaluation": false,
    "physical_execution": false,
    "reinterpret_existing_evidence": false
  }
}
```

The V1 association is deterministic from its current contract. The original-
site yellow detection is 0.06147486993014053 m from the preceding e91f94dc
position and therefore falls inside the unchanged 0.12 m association gate.
The carried yellow detection is 0.17430259174059995 m away and receives the new
ID e4beb00e. Thus the nearer original-site detection receives e91f94dc.

This is not accurately described as V1 emitting a retained ghost with no
current detection: e91f94dc labels a current-frame public detection. The direct
scene-16073 defect is that category/color/static-nearest-neighbour association
cannot distinguish that detection from the same-colored object transported by
the gripper. Separately, V1 stores timestamps and historical tracks without a
defined lifecycle; that issue should also be specified before a V2 exists, but
pruning history alone would not fix this episode because e91f94dc was present
in the immediately preceding capture.

The public predicate behaved as frozen and fail-closed. Its reference-to-
original-site distance is 0.02253914815279092 m, inside the unchanged 0.03 m
original-site gate, so it returned no success predicates despite the physical
`LIFTED` receipt. The receipt must not be used to backfill public success.

## Mutually exclusive human choices

The approver must select exactly one of A, B, or C. No combination or inferred
default is permitted.

### A — PublicTrackAssociatorV2 with public-only motion association (recommended)

Authorize a new, versioned tracker whose purpose remains public perception,
not success inference. An accepted ADR selecting A must freeze the following
complete contract before implementation or any new run.

#### Exact allowed inputs

Only these inputs may enter association or ambiguity resolution:

1. From the current and retained prior public RGB-D detections:
   `timestamp_ns`, `frame_id`, opaque prior `track_id`, perceived `category`,
   perceived `attributes.visual_color`, public RGB-D centroid `position_3d`,
   `confidence`, `bbox_or_mask`, `visibility`, and public component-quality
   fields already present in `covariance_or_quality`.
2. Public sensor protocol metadata needed to compare those values: declared
   camera frame, metric units, and the already approved camera-to-world
   calibration transform plus its immutable hash.
3. Time-aligned robot proprioception: end-effector position and orientation in
   the declared world frame, gripper width/closed state, proprioception
   timestamp, and the displacement between the two public captures.
4. The last physically executed public skill name and its start/end timestamp,
   only to select an ADR-frozen motion hypothesis. It may not convey an object
   identity, contact entity, task outcome, or evaluator label.

Everything else is forbidden. In particular V2 may not read or derive Gazebo/
Isaac entity or prim IDs, attached-entity IDs, simulator object poses, semantic
or instance render truth, contact-entity identity, injected-failure truth,
task-success truth, evaluator role truth, `task_target_track_id`, TaskSpec
target identity, supervision labels, Teacher output, or any Teacher runtime
state. It may not use the scene seed or matched-key outcome as an input.

#### Deterministic and fail-closed matching contract

The accepted ADR must state, before code exists:

- strict timestamp monotonicity, maximum retained age/missed-capture policy,
  frame/unit/calibration-hash equality, and removal of expired tracks;
- the exact static and hand-displacement motion hypotheses and the conditions
  under which each is eligible;
- every numeric gate, cost term, quantization rule, assignment algorithm, and
  complete tie-break order;
- deterministic one-to-one global matching between prior tracks and current
  detections;
- an explicit ambiguity margin. Any edge or global assignment within that
  margin of another admissible identity assignment is ambiguous: no old ID is
  assigned to the implicated detection, the old ID is absent from the fresh
  observation, and downstream stale-pointer handling remains fail-closed;
- unmatched detections receive deterministic new public IDs; expired or
  unmatched prior tracks are never emitted as current observations;
- no TaskSpec-, policy-choice-, receipt-, or outcome-conditioned override.

This request deliberately does not supply new numeric gates. Selecting values
from the observed 0.06147486993014053 m and 0.17430259174059995 m distances
would be post-outcome fitting. The human ADR must pre-register all values and
their provenance independently. The existing V1 0.12 m gate and the public
predicate's 0.03 m gate remain unchanged for V1 and old evidence.

#### Required version and evidence isolation

Approval of A must allocate, at minimum, distinct revisions
`PublicTrackAssociatorV2`, `PathBlockedPublicObservationV4`,
`PublicTrackCandidateV4`, and `M2C_Q012_V4`; exact-load guards must reject
cross-revision checkpoints and observations. `PublicTrackCandidateV3`,
`M2C_Q012_V3`, V1 track IDs, all existing probes, and scene-16073's
`final_task_success=false` retain their original meaning and bytes. No replay
may be reported as a new physical outcome.

After implementation and local tests, any collection requires a separate
outcome-blind preregistration of wholly new TRAIN keys. Those keys must be
identity-disjoint from every attempted V1/V3 TRAIN or SMOKE key and every V4,
S6, matched-evaluation, or other held-out key. The preregistration must bind
the accepted ADR, tracker/runtime/generator/manifest hashes, fixed key order,
stop count, no retry/replacement rule, and must precede every selected-key
outcome. Training or Q-B evaluation requires its existing independent gates;
tracker approval alone does not authorize either.

Trade-off: A addresses the identity contract rather than weakening success
criteria, but it is a formal public-observation/model-input change and requires
new implementation, checkpoints, manifests, audits, and evidence.

### B — no tracker change; stop PATH_BLOCKED collection

Keep `PublicTrackAssociator` V1, all thresholds, predicates, revisions, and
existing evidence unchanged. Stop further PATH_BLOCKED collection, keep S4
blocked, and report that current public re-identification cannot authenticate
the carried target in scene16073 even though the separate physical receipt is
`LIFTED`. No model-success claim may be made from that receipt.

Trade-off: B avoids post-outcome architectural adaptation and preserves the
strongest audit boundary, but leaves Q-B headroom unmeasured under the current
public identity contract.

### C — another explicit human choice

The human may reject A and B and provide a different choice. C is valid only
if the accepted ADR specifies, without ellipsis: exact allowed public fields;
forbidden truth/Teacher/entity fields; complete deterministic matching and
ambiguity behavior; every numeric value and its outcome-independent
provenance; lifecycle, frame, unit, and calibration contracts; schema/runtime/
checkpoint revisions; treatment of old V1 evidence; new-key preregistration;
and exactly which later activities, if any, are authorized. Blank fields mean
not approved. Codex must not infer C from comments or implement a hybrid.

## Non-negotiable boundaries for every choice

- Do not change, tune, or reinterpret the V1 0.12 m association gate, the
  frozen 0.03 m original-site predicate gate, any public predicate, B0, IK,
  collision, controller, schema, stale-pointer, frame/unit, or safety gate to
  make scene16073 pass.
- Do not relabel e4beb00e as e91f94dc in the old capture, replace the frozen
  public predicate with physical truth, or backfill scene16073 as eligible or
  successful. Its probe SHA and `final_task_success=false` remain authoritative
  for that run.
- No simulator/Isaac entity or prim identity, attached-entity receipt, perfect
  object pose, Teacher, or evaluator truth may enter test-time association or
  policy input. Teachers remain unused; Nano/BWM/Super status and kill rules
  are unchanged.
- A tracker cannot replace world-model prediction and selection. Formal model
  changes still require a human ADR and all independent entry gates.

## Human decision record

- Selected option: `NONE` (`A | B | C`, exactly one required)
- Accepted ADR path/commit: `NONE`
- If A: exact numeric gates and independent provenance: `NONE`
- If A: exact assignment/quantization/tie/ambiguity contract: `NONE`
- If C: complete alternative contract: `NONE`
- Authorization for new TRAIN collection: `NO`
- Authorization for training: `NO`
- Authorization for SMOKE/model rollout/Q-B evaluation: `NO`
- Approver/date: `NONE`

Editing this request or filling these lines does not itself constitute
approval. A separate accepted human ADR and human-approved commit are required.

## Task report

- Changed files: this request and its local contract test only.
- Tests: the contract test locks the complete document bytes, probe SHA,
  post-outcome disclosure, distance arithmetic, A/B/C exclusivity, forbidden
  inputs, revision isolation, and non-authorization fields.
- Failures: scene16073 remains `final_task_success=false`; no result is changed.
- Blocker: no accepted human ADR for a public-track identity revision.
- Teacher kill rules: not triggered; no Teacher was used or proposed.
- Next command: a human selects A, B, or a fully specified C in a separate
  accepted ADR; no collection command is authorized by this request.
