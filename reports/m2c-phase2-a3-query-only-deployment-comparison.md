# M2C Phase-2 A.3 query-only deployment comparison

Status: `PASS_DEPLOYMENT_QUERY_REPLAY_BLOCKED_STATIC_HOME_COLLISION`

The deployment/permission path is working. The corrected run used the pinned
Isaac 6 image with `/isaac-sim/python.sh` as the explicit entry point, completed
the query-only FK/native Bullet replay, and published a create-only receipt.
The evidence directory was writable only for the container UID while the
receipt was produced and was frozen read-only afterwards.

No accepted receipt loaded Kit or Isaac, started a scene, wrote an articulation
target, stepped simulation, mutated a scene, ran training, used Teacher, or
used privileged truth as policy input.

## Frozen comparison

- before receipt SHA-256: `a4035dc3fd122fcbbbe077d235d6c0276634b40cb7d4fdfd7aab5d69a697d602`;
- after receipt SHA-256: `6515bec6249318596a6023e92556cfbf2351c9bd0b1bd43fe8d635800b02cbb6`;
- same runtime image and same repeated home/open joint-state sequence;
- before: 61 clear child pairs, 15 collision rejections;
- after: 73 clear child pairs, 3 collision rejections;
- query failures: zero in both accepted runs.

The remaining non-ACM pairs are hand-link7, link2-link4, and link5-link7.
They do not involve either finger, so the historical MoveIt report's 0.02 m
finger state versus the smoke's 0.04 m finger state cannot explain them.
The historical no-motion MoveIt check reports the same seven arm joints clear,
but it does not override the fail-closed Bullet result.

Consequently, permission/deployment is no longer the blocker; the static A.3
self-collision preflight remains blocked. No production binding is set and no
formal execution is authorized.

## Replay

```text
PYTHONPATH=src:scripts .venv/bin/python scripts/m2c/audit_phase2_a3_query_only_deployment_comparison.py --project-root . --before-receipt /Users/gl/tzb-m2c-evidence/m2c-phase2-a3-query-only-smoke-fcccc9c/query-only-deployment-smoke.json --after-receipt /Users/gl/tzb-m2c-evidence/m2c-phase2-a3-query-only-smoke-7ea1b43/query-only-deployment-smoke.json --expected-json reports/m2c-phase2-a3-query-only-deployment-comparison.json
```

One next command:

```text
.venv/bin/pytest -q tests/unit/test_m2c_phase2_a3_query_only_deployment_comparison.py
```
