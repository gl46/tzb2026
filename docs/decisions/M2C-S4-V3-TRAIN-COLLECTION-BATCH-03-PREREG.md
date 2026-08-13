# M2C S4 V3 TRAIN collection batch 03 pre-registration

- Status: frozen before observing or executing any selected batch-03 result
- Written: 2026-08-13 10:05 Asia/Shanghai
- Pre-registration source commit: `373c9ddc18e64c856964f362d87b5a68f5d2ba0b`
- Authorized unchanged runtime commit: `60b9578f3a20aab434d3bcb8d03e63c21ea09f01`
- Authority: `ADR-0021-m2c-public-semantic-candidate-contract.md`

The committed V3 collection audit records eight unique attempted TRAIN keys.
Their identities, but not their outcomes or terminal classifications, are the
only new exclusion input. This pre-registration is after those eight-key
observations and before any result for the three keys selected below.

## Frozen outcome-blind selection

Read `training_keys` in the frozen V3 manifest's existing order. Skip every
record whose `scene_seed` is in the audited eight-key identity set. Select the
first remaining record for each `sdf_sha256` not yet represented in this batch,
and stop after three selections. The deterministic result is:

| Scene | Failure | Matched key | SDF SHA-256 | Supervision SHA-256 |
| ---: | ---: | --- | --- | --- |
| 16073 | 160737 | `m2c-s4-v3-train-a101b1d9d220dfd6f293d1eab337e412b29b48a61759b5baef1ef8b2ad6ba5d2` | `769d539378a899420e55c172a34c01cfaef19c1a83fe3eded3f7a4ba190c825d` | `1266a35231ff24d9c18537452561f36da821619929d03599d1a14830977568a0` |
| 16085 | 160857 | `m2c-s4-v3-train-cc4279699767f13fca822086bd65fe206cc229a0beb7374fed1632f225697c19` | `2bd5a27d6d3a2ff42152024e4fbd9a68749840c153f3fe68e5b27085e58b1615` | `405eb17ee743f9f6e5c7b2bc491ce400fa3fcdff606404a7366aa20334e6a80e` |
| 16102 | 161027 | `m2c-s4-v3-train-87da40d69271e42d64f250fc946621ce3b2a4b548290530055cd33e3e431fa21` | `e30efb66aef4ff948e48551cb26d03990c14b6bb25813b9a8fd6e8b7c9831cf7` | `edb6791ad67a595ba65a5a84a85adb79199c6b5b580537e5f7735a592fe736f1` |

Each selected matched key may be attempted at most once. No retry,
replacement, or outcome-conditioned extension is authorized. The batch stops
after these three attempts regardless of their results.

## Scope

Only scripted public physical-supervision collection for frozen `role=TRAIN`,
`split=train` records is authorized. Teacher use, model rollout, training
execution, Q-B evaluation, and privileged truth as policy input remain
forbidden. This document performs no collection and changes no runtime.

## Machine-checked freeze

```json
{
  "schema_version": "M2CS4V3TrainCollectionBatch03PreregV1",
  "registered_after_observed_unique_train_keys": 8,
  "registered_before_any_selected_key_result": true,
  "selected_key_result_observed_before_registration": false,
  "preregistration_source_commit": "373c9ddc18e64c856964f362d87b5a68f5d2ba0b",
  "authorized_runtime_commit": "60b9578f3a20aab434d3bcb8d03e63c21ea09f01",
  "manifest": {
    "path": "configs/m2c_s4_v3_training_keys.json",
    "file_sha256": "b5a2da566f4086724e99cea1664aeeac3b91344a68b72be84bcf6c5d0ddad65c",
    "embedded_manifest_sha256": "4f9841fe379e2bfab56e9cb9d173f3c717f4017fc3ac43271ab9e86e040a9dbb"
  },
  "attempt_identity_audit": {
    "path": "reports/m2c-s4-v3-path-blocked-train-collection.json",
    "file_sha256": "c505ec6517d7a766768f72cd14fc49d1919cff234dc2d8fbee1877104b41480d",
    "schema_version": "M2CS4V3TrainCollectionAuditV1",
    "unique_train_keys_attempted": 8
  },
  "attempted_scene_seed_exclusions": [
    16012,
    16022,
    16025,
    16026,
    16047,
    16063,
    16066,
    16081
  ],
  "selection_rule": "manifest_order_first_unattempted_per_sdf_v1",
  "selection_inputs": ["manifest_order", "attempted_key_identity", "sdf_sha256"],
  "selection_uses_attempt_outcomes": false,
  "maximum_selected_keys": 3,
  "stop_after_selected_keys": 3,
  "attempt_each_selected_key_at_most_once": true,
  "retry_authorized": false,
  "replacement_authorized": false,
  "collection_executed_by_preregistration": false,
  "runtime_changed_by_preregistration": false,
  "scope": {
    "role": "TRAIN",
    "split": "train",
    "scripted_public_physical_supervision_collection": true,
    "teacher_used": false,
    "model_rollout": false,
    "training_execution": false,
    "q_b_evaluation": false,
    "privileged_truth_policy_input": false
  },
  "selected_keys": [
    {
      "scene_seed": 16073,
      "failure_seed": 160737,
      "matched_key": "m2c-s4-v3-train-a101b1d9d220dfd6f293d1eab337e412b29b48a61759b5baef1ef8b2ad6ba5d2",
      "sdf_sha256": "769d539378a899420e55c172a34c01cfaef19c1a83fe3eded3f7a4ba190c825d",
      "supervision_sha256": "1266a35231ff24d9c18537452561f36da821619929d03599d1a14830977568a0"
    },
    {
      "scene_seed": 16085,
      "failure_seed": 160857,
      "matched_key": "m2c-s4-v3-train-cc4279699767f13fca822086bd65fe206cc229a0beb7374fed1632f225697c19",
      "sdf_sha256": "2bd5a27d6d3a2ff42152024e4fbd9a68749840c153f3fe68e5b27085e58b1615",
      "supervision_sha256": "405eb17ee743f9f6e5c7b2bc491ce400fa3fcdff606404a7366aa20334e6a80e"
    },
    {
      "scene_seed": 16102,
      "failure_seed": 161027,
      "matched_key": "m2c-s4-v3-train-87da40d69271e42d64f250fc946621ce3b2a4b548290530055cd33e3e431fa21",
      "sdf_sha256": "e30efb66aef4ff948e48551cb26d03990c14b6bb25813b9a8fd6e8b7c9831cf7",
      "supervision_sha256": "edb6791ad67a595ba65a5a84a85adb79199c6b5b580537e5f7735a592fe736f1"
    }
  ]
}
```
