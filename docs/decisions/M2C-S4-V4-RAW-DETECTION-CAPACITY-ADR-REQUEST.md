# M2C S4 V4 raw public-detection capacity — human ADR request

- Status: **POST-OUTCOME / NOT APPROVED**
- Decision type: **REQUEST FOR HUMAN DECISION; NOT AN APPROVED ADR**
- Date: 2026-08-14 (Asia/Shanghai)
- Governing decisions: `ADR-0021-m2c-public-semantic-candidate-contract.md`
  and `ADR-0024-m2c-s4-unblock-directive.md`
- Scope: the number of unassociated public RGB-D detections accepted by one
  `PublicTrackAssociatorV2` capture; final `PublicTrackCandidateV4` K=8 is out
  of scope and remains unchanged
- Recommendation: **Option A**, with the exact independent raw capacity to be
  supplied by the human approver
- Decision recorded by this request: **NONE**

This request was written after Batch-08 scene 19083 completed its raw eight-step
physical chain. It therefore cannot be treated as a preregistration or used to
retroactively tune a numeric bound. It authorizes **no schema change, no replay,
no packaging, no training, no new collection, no model rollout, and no Q-B
evaluation**. The existing raw evidence and all physical outcomes retain their
original meaning.

## Why a human decision is required

ADR-0021 bounds the *final candidate window* at K=8 after public role ordering.
ADR-0024 separately requires unmatched current detections to receive new public
IDs. The V4 implementation introduced another bound:

```python
detections: list[PublicRGBDDetectionV2] = Field(max_length=8)
```

and the associator deployment receipt repeats `max_current_detections=8`.
That raw-input bound is not the final candidate K. It prevents association and
role ordering from running whenever the public detector produces more than
eight connected components. Changing it touches a schema gate, one of the four
human-escalation categories in ADR-0024 section 4; Codex may not infer a new
number from the observed result.

The public geometric detector has no independent maximum-component contract.
It scans all six public color prototypes, retains every connected component
with 12–2500 pixels, and sorts all resulting public detections. Consequently,
neither K=8 nor the six physical cylinders establishes an honest raw-input
capacity. The observed maximum 13 is post-outcome evidence, not numeric
authority for choosing 13.

## Byte-bound Batch-08 finding

```json
{
  "schema_version": "M2CS4V4RawDetectionCapacityADRRequestEvidenceV1",
  "timing": "POST_OUTCOME",
  "approved_adr": false,
  "selected_option": null,
  "authorization": {
    "schema_change": false,
    "offline_replay": false,
    "package_existing_raw_chain": false,
    "new_collection": false,
    "training": false,
    "model_rollout": false,
    "q_b_evaluation": false,
    "reinterpret_physical_outcome": false
  },
  "batch08": {
    "preregistration_path": "docs/decisions/M2C-S4-V4-TRAIN-COLLECTION-BATCH-08-PREREG.json",
    "preregistration_sha256": "7cbfaf50519957a213a71eb740116cbe1e85df822dd9dfb7d53def9b26e0d827",
    "preregistration_commit": "b90d573e2cbd977c13e96fb97365a66efc235eb9",
    "audit_path": "reports/m2c-s4-v4-batch08-collection.json",
    "audit_sha256": "226761a056c6c3a127784019147e49b3e6e301f72d4b9711e222cd7c939a2894",
    "matched_key": "m2c-s4-v4-train-dc5715316cad6e42faf074a9b6715f76e2df7bd0d267c3cf88037fdc5f8c50a7",
    "scene_seed": 19083,
    "failure_seed": 190837,
    "raw_probe_sha256": "9f3144467f247131240c5e152a8317e578e69c4c29192e0b64e4ddb78e5fef89",
    "raw_capture_detection_counts": [7, 13, 11, 7, 8, 9, 10, 10],
    "first_rejected_capture_index": 1,
    "first_rejected_detection_count": 13,
    "physical_skill_receipt_count": 8,
    "final_task_success": false,
    "final_controller_gate": "REJECTED",
    "final_execution_status": "CONTACT_GATE_REJECTED",
    "collision_or_safety_violations": 0,
    "training_sample_packaged": false,
    "permission_failure": false,
    "teacher_used": false,
    "privileged_truth_policy_input": false
  },
  "frozen_contract": {
    "path": "src/xh_agent/policy/qrm_lite/path_blocked_collection_v4.py",
    "sha256": "1bb916b375e9ac3336911a11e96d11506709b285ac74d8f7579a8cfb5bccd887",
    "raw_detection_max_length": 8,
    "final_candidate_k": 8
  },
  "detector": {
    "path": "src/xh_agent/perception/geometric_rgbd.py",
    "sha256": "01ba1310bc99cf8aabaf954a76ede0708100c7672c88d7c27a7a7fedcecf7e5f",
    "public_color_prototype_count": 6,
    "minimum_component_pixels": 12,
    "maximum_component_pixels": 2500,
    "independent_maximum_component_count": null
  }
}
```

Two other Batch-08 selected keys exited with Isaac stage process code 139 and
produced no raw physical chain. They are permanently consumed failures and are
not candidates for replay or replacement. Scene 19083 did execute eight
scripted public physical-supervision skills; its final `REGRASP` receipt is a
controller/contact rejection and `final_task_success=false`. A capacity
decision can only make the already-recorded public observation history
parseable for offline host replay. It cannot turn that physical outcome into a
success or change any safety gate.

## Options

### A — separate raw association capacity from final K=8 (recommended)

Authorize a new exact schema/deployment revision in which:

1. the human approver supplies one exact positive integer
   `max_raw_public_detections`;
2. every unassociated public detection up to that bound is passed to
   `PublicTrackAssociatorV2` without truncation or outcome-dependent filtering;
3. association, lifecycle, ambiguity, and deterministic new-ID rules remain
   exactly those approved in ADR-0024;
4. `PublicTrackCandidateV4` role ordering then truncates associated fresh
   tracks to the unchanged K=8;
5. more than `max_raw_public_detections` remains fail-closed;
6. the raw schema, deployment receipt, host replay, checkpoint metadata, and
   tests all bind the new value and revision;
7. scene 19083 may be replayed **offline only** from immutable raw bytes after
   implementation and tests pass. No physical retry is authorized.

The observed count 13 is explicitly not a recommendation for the numeric
value. The approver must provide the number and its independent provenance.

### B — retain raw capacity 8 and keep S4 blocked

Keep the current schema unchanged. Scene 19083 remains raw physical evidence
that is not eligible for host replay or training packaging. New unchanged-V4
collection is not recommended because ordinary public component splits can
exceed eight and would hit the same gate, but this request does not itself
revoke separately preregistered authority.

### C — another complete human-specified contract

Provide the exact raw-input capacity or deterministic pre-association reduction
rule, its allowed public fields, ordering/tie behavior, revision names,
fail-closed behavior, provenance, and whether existing scene 19083 bytes may be
replayed offline. Any reduction rule must remain independent of TaskSpec target
identity, outcomes, Teacher output, and privileged simulator truth.

## Required approval fields

- Selected option: `NONE` (`A | B | C`, exactly one required)
- If A: exact `max_raw_public_detections`: `NONE` (positive integer required)
- If A: independent numeric provenance: `NONE` (required)
- Does final candidate K remain exactly 8?: `YES` (must remain YES)
- May immutable scene 19083 raw bytes be replayed offline after the revised
  implementation and tests pass?: `NONE` (`YES | NO`, required for A/C)
- Are physical retry/replacement or outcome reinterpretation authorized?: `NO`
- Approver/date: `NONE`

Until these fields are completed in an accepted human ADR, the honest state is
`BLOCKED_RAW_DETECTION_CAPACITY_SCHEMA_DECISION_REQUIRED`, training sample count
remains zero, and pure-model success remains unmeasured (`null`).
