# M2C S3 Dataset V3

- Verdict: **PASS_S3_FULL_CLASS_COVERAGE**.
- Valid/quarantined episodes: 312/0.
- Failure counts: `{'EMPTY_GRASP': 101, 'WRONG_OBJECT': 100, 'RELEASE_FAILURE': 111}`.
- Successful recovery counts: `{'EMPTY_GRASP': 101, 'WRONG_OBJECT': 100, 'RELEASE_FAILURE': 111}`.
- Split-group leakage: `[]`.
- Collection attempts rejected by frozen predicates: 68; every rejection is retained in the JSON report.
- Accepted-evidence audit: 150/150 records; strict predicates 150/150; SHA matches 150/150; collision gates checked 557; violations 0.

## Evidence boundary

- Remote evidence tree: `/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1`; read-only: `True`.
- Evidence ledger: `/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1/evidence-sha256.txt`; SHA-256 `0b1142aaf802378f719a32aa28fa671447f97231067b55e27a07fa4749306f8f`; 5404 files bound.
- Worker status `/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1/worker0/worker-status.json`: SHA-256 `bb7e28fd7c4cc11898c4eb4a119781910accd81a3de4c1cb461a3a0861641b60`, accepted `{'EMPTY_GRASP': 25, 'RELEASE_FAILURE': 25, 'WRONG_OBJECT': 25}`, records `99`.
- Worker status `/var/tmp/xh-data/isaac-industrial/m2c/s3-failure-evidence-v1/worker1/worker-status.json`: SHA-256 `c901a29dfdf512838a5c58c90bf3b29b24ce97a84d264ac42e84848c96573141`, accepted `{'EMPTY_GRASP': 25, 'RELEASE_FAILURE': 25, 'WRONG_OBJECT': 25}`, records `119`.
- Teacher used: no; Teacher kill-rule events: none.
- Privileged simulator truth used as policy input: no.
- The world-model mainline was not replaced.
- PATH_BLOCKED remains raw evaluator evidence only; it is not a model training label and no new skill label was created.

## Task report

- Changed/generated files:
  - `artifacts/m2c/dataset-v3.jsonl` (SHA-256 `48924a208c0ab417384f09bbef45073a10f58c9aac16cc64089409288401f35b`)
  - `artifacts/m2c/dataset-v3-quarantine.jsonl` (SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`)
  - `artifacts/m2c/path-blocked-raw-v1.jsonl` (SHA-256 `704cc5790ca6c5f0694664195130585b7420660b6c99b29afc342b83ef5908d5`)
  - `reports/m2c-s3-evidence-freeze.json` (SHA-256 `bb21eea0064637b985f2df7a832e2f8b6c0d0a6c60360e4380ec70c04bdf9c00`)
  - `reports/m2c-s3-dataset-v3.md`
- Tests: full class-coverage gate, 150/150 strict physical/public acceptance re-audit, recursive collision/safety gate audit, strict episode validation, accepted-evidence SHA binding, zero packaging quarantine, and split-group leakage check.
- Failures: 68 collection attempts were rejected and retained with explicit reasons; packaging quarantine is 0.
- Blocker: Q-B remains forbidden until a separate human expressivity ADR is committed; this S3 result does not authorize Q-B.
- Next command: `sed -n '1,240p' docs/decisions/M2C-QB-EXPRESSIVITY-PREREG.md`.
