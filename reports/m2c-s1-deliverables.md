# M2C S1 submission deliverables

- status: **PASS**
- source episode: `m2b-match-432a8e20f3b3829a17c0da5ee81a5f6b3dd3eef440ddf51efa7d604c2f9a89a9:QRM_COARSE_FC`
- task-success RGB-D: `/Users/gl/tzb-m2c-evidence/m2c-s1/task-success-rgbd/manifest.json`; task_success=True
- RGB/depth SHA-256: `2ffbf55d29bd74c3e6e86d379f908541887aafb4b34af80d36ff69add90d0396` / `73c2379ebb0f82ce91bc8a382524a937938b6e13b55f34e96b2c6f49cde9ca28`
- WRONG_OBJECT video: `/Users/gl/tzb-m2c-evidence/m2c-s1/m2c-s1-wrong-object-recovery.mp4`; `963b18c6e3b7396766929efb4113f4e47183e2edb60a5dee406c7a478a24eb4b`
- attribution video: `/Users/gl/tzb-m2c-evidence/m2c-s1/m2c-s1-m2b-attribution.mp4`; `17183a5e20a2def1afa3e9c8471e1eee031c904cadd8536e554f153a3f11d79c`
- attribution: model=1, fixed B0 continuation=2
- final task success / pure model success: True / False
- capture disclosure: sparse synchronized retained RGB-D evidence, not continuous camera recording
- Teacher used: no; kill-rule events: none
- privileged truth used as policy input: no

## Task report

- changed files:
  - `Makefile`
  - `docs/competition/submission-checklist.md`
  - `reports/m2c-s1-deliverables.json`
  - `reports/m2c-s1-deliverables.md`
  - `reports/m2c-s1-verification.json`
  - `scripts/m2c/export_s1_evidence.py`
  - `tests/unit/test_m2c_s1_evidence.py`
- tests: 375 passed, 0 failed
- failures:
  - The first standalone B0-freeze recheck omitted scripts from PYTHONPATH and stopped with ModuleNotFoundError before evaluating evidence; it was rerun with the project PYTHONPATH and passed 12/12 B0 files, 116/116 index entries, and zero M2B report mismatches.
- blockers:
  - none
- next command: `make m2c-s2`
