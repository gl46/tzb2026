# M2C S4 V3 TRAIN collection batch 02 pre-registration

- Status: frozen before observing or executing any batch-02 outcome
- Written: 2026-08-13 09:12 Asia/Shanghai
- Source commit: `60b9578f3a20aab434d3bcb8d03e63c21ea09f01`
- Authority: `ADR-0021-m2c-public-semantic-candidate-contract.md`

This is an outcome-blind, collection-only pre-registration. The fact that scene
seeds `16012, 16022, 16025, 16026, 16063` were already attempted is used only
as an identity exclusion; none of their outcomes is a selection input.

## Frozen selection

Read `training_keys` in the frozen V3 manifest's existing order, skip the five
excluded scene seeds, and select the first remaining record for each previously
unselected `sdf_sha256`. Stop as soon as three records have been selected. This
fixed rule selects one record for each of the manifest's three SDF hashes:

| Scene | Failure | Matched key | SDF SHA-256 | Supervision SHA-256 |
| ---: | ---: | --- | --- | --- |
| 16047 | 160477 | `m2c-s4-v3-train-ecda02ee3573edfcf8d67460c55b2d947d3804838d00520c47667e68b56c9739` | `769d539378a899420e55c172a34c01cfaef19c1a83fe3eded3f7a4ba190c825d` | `24e4e47eaa216c0e2d1b680da41ffd99ab78f05a77825a914fa7ba3de541a359` |
| 16066 | 160667 | `m2c-s4-v3-train-0b384127e1af7ca068127252ef4d3d1372b4d4edf0eeb4eef6defe5e6add0295` | `2bd5a27d6d3a2ff42152024e4fbd9a68749840c153f3fe68e5b27085e58b1615` | `de423cc0998e6d76190eed5c3807280f1e7b8ae41a8919ad82a39be80cd0bf2e` |
| 16081 | 160817 | `m2c-s4-v3-train-bbb839d64e2c4e8e80b17b70c13ceb34ce106035e94eb3e2e02b08df75f660c4` | `e30efb66aef4ff948e48551cb26d03990c14b6bb25813b9a8fd6e8b7c9831cf7` | `82c729bef8158ec764bb0c9ce71d1ea6391f2244c914ec0264b6642a2eaed9e7` |

Each fixed matched key may be attempted at most once. There is no retry,
replacement, or outcome-conditioned extension. The batch stops after these
three attempts regardless of their outcomes.

## Scope

Only scripted public physical-supervision collection for records with
`role=TRAIN` and `split=train` is authorized. Teacher use, model rollout,
training execution, Q-B evaluation, and privileged truth as policy input are
not authorized. These attempts therefore cannot be reported as
`pure_model_success_episodes` or any Q-B result.

## Machine-checked freeze

```json
{
  "schema_version": "M2CS4V3TrainCollectionBatch02PreregV1",
  "registered_before_any_batch02_outcome": true,
  "batch02_outcome_observed_before_registration": false,
  "source_commit": "60b9578f3a20aab434d3bcb8d03e63c21ea09f01",
  "manifest": {
    "path": "configs/m2c_s4_v3_training_keys.json",
    "file_sha256": "b5a2da566f4086724e99cea1664aeeac3b91344a68b72be84bcf6c5d0ddad65c",
    "embedded_manifest_sha256": "4f9841fe379e2bfab56e9cb9d173f3c717f4017fc3ac43271ab9e86e040a9dbb"
  },
  "attempted_scene_seed_exclusions": [16012, 16022, 16025, 16026, 16063],
  "selection_rule": "manifest_order_first_unattempted_per_new_sdf_v1",
  "selection_inputs": ["manifest_order", "scene_seed_exclusion", "sdf_sha256"],
  "selection_uses_outcomes": false,
  "stop_after_selected_keys": 3,
  "attempt_each_selected_key_at_most_once": true,
  "retry_or_replacement_authorized": false,
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
  "implementation_sha256": {
    "src/xh_agent/policy/qrm_lite/public_tracks_v3.py": "20d53a15ff94aab63a1e09042b2e546ffc36ceebf94bb3059d34ca651cc05752",
    "src/xh_agent/policy/qrm_lite/path_blocked_supervision_v3.py": "d38e6ba97090b7102cd8791973a656bd802772d472d71a169ba9d987db851d98",
    "scripts/m2c/build_s4_v3_training_manifest.py": "5e426023a7d21fbbe4130215667b565650b493923faa0427ae899820a951f362",
    "scripts/m2c/materialize_s4_s6_scenes.py": "a31e97c10fb4a08836fd1c460a2531de94206898bb92e51616d3d992bd4a2430",
    "scripts/m2c/derive_model_owned_chain_probe.py": "8452a802ebf167266fd3d990f7a81941391a49c70a75c95e8081f19bd4533a3c",
    "scripts/m2c/run_path_blocked_collection_worker.py": "72ea9d95e3d0b57c65ae2d012d67b0c7857ecb95621ab176c9a3f9d23cd7c738",
    "scripts/m2c/package_path_blocked_collection.py": "f7b8712356fd255ad3c6e8925a5d13e470a75b62ba762d749ae90ee4c2d831d5"
  },
  "selected_keys": [
    {
      "scene_seed": 16047,
      "failure_seed": 160477,
      "matched_key": "m2c-s4-v3-train-ecda02ee3573edfcf8d67460c55b2d947d3804838d00520c47667e68b56c9739",
      "sdf_sha256": "769d539378a899420e55c172a34c01cfaef19c1a83fe3eded3f7a4ba190c825d",
      "supervision_sha256": "24e4e47eaa216c0e2d1b680da41ffd99ab78f05a77825a914fa7ba3de541a359"
    },
    {
      "scene_seed": 16066,
      "failure_seed": 160667,
      "matched_key": "m2c-s4-v3-train-0b384127e1af7ca068127252ef4d3d1372b4d4edf0eeb4eef6defe5e6add0295",
      "sdf_sha256": "2bd5a27d6d3a2ff42152024e4fbd9a68749840c153f3fe68e5b27085e58b1615",
      "supervision_sha256": "de423cc0998e6d76190eed5c3807280f1e7b8ae41a8919ad82a39be80cd0bf2e"
    },
    {
      "scene_seed": 16081,
      "failure_seed": 160817,
      "matched_key": "m2c-s4-v3-train-bbb839d64e2c4e8e80b17b70c13ceb34ce106035e94eb3e2e02b08df75f660c4",
      "sdf_sha256": "e30efb66aef4ff948e48551cb26d03990c14b6bb25813b9a8fd6e8b7c9831cf7",
      "supervision_sha256": "82c729bef8158ec764bb0c9ce71d1ea6391f2244c914ec0264b6642a2eaed9e7"
    }
  ]
}
```
