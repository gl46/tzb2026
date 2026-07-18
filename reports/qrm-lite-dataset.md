# QRM-Lite alpha dataset

- samples: 120
- episodes: 120
- train/val: 108/12
- synthetic: 100 (geometric fixtures, not Gazebo truth)
- from real logs: 20
- failure counts: `{"EMPTY_GRASP": 36, "RELEASE_FAILURE": 17, "UNKNOWN": 26, "UNSTABLE_PLACEMENT": 20, "DROP_OR_SLIP": 21}`
- manifest: `data/qrm_lite/manifests/alpha-dataset.json`
- jsonl: `data/qrm_lite/manifests/alpha-dataset.jsonl`

Split is by episode_id, not random adjacent frames.
Online observations do not include simulator perfect poses.
