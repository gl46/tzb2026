# M2C Phase-2 A.3 native build audit

- Status: `PASS_QUERY_ONLY_NATIVE_BUILD_AND_GEOMETRY_REPLAY`
- Builder image ID: `sha256:01d3c57bde2ce5ff1655ab5739d0729ae7ea035be2ac56bd391a4357e3c4307e`
- Native shared object SHA-256: `2231cee659b15875fc0bed011f339ac9962168981d228f3f08c6189929ce9c23`
- Native build receipt file SHA-256: `20753793c3a6c3f7f534a7b4f0a42c96c1a746d28ef7b72b4c3f6325733a4842`
- Adapter build manifest file SHA-256: `6285988b8aea7f5e3bdff0f3b215e483ff59a350cff5ff7aaf4a638bb12c65e3`
- Complete compiler-input manifest SHA-256: `7f4f3e47272f4d5557063a026dbfa713caa69eec39ecdf9e27aeb4aa88e11875`
- Controlled-Panda geometry receipt SHA-256: `a74f647faeeba297c54cc3e290d5c2576c2b14f605d50754701aab9887544c01`
- The report records all 14 per-shape Bullet 3.24 constructor margins; each
  primitive uses its own `setSafeMargin` value rather than the governed-type
  maximum, while both convex hulls retain `0.04 m`.
- Teacher used: **false**
- Privileged truth used as policy input: **false**
- Isaac started: **false**
- Physical execution performed: **false**
- Training performed: **false**
- Production binding set: **false**

## What changed

The node2 account could read the governed Bullet 3.24 float64 libraries,
headers, and the two original Panda STL assets, but it did not have permission
to use the host Docker socket and passwordless sudo was unavailable. No system
group, ACL, or sudo policy was changed.

The build instead used the existing immutable labserver build image as a
network-disabled Docker base. Byte-verified Bullet headers and float64
libraries were copied from node2 into an isolated build context. The resulting
builder image ran with `--network none --read-only`; only the create-only
output directory was writable. This closes the original asset/native-build
availability blockers without widening host permissions.

This v5 rebuild binds the corrected per-shape Bullet 3.24 shipped margins:
`0.0055074 m` for the largest governed Panda box, `0.008 m` for its cylinder,
and `0.04 m` for convex hulls. The separate outward padding remains exactly
`0.002 m`; no penetration, contact, ambiguity, or fail-closed gate was relaxed.

## Replay result

The independent audit verifies exactly ten read-only evidence files, the
builder image ID, canonical receipt self-hashes, every actual compiler input,
all twelve governed Bullet header hashes, the two expected float64 libraries,
and the exact dynamic `NEEDED`/RUNPATH set. It also parses the governed
URDF/SRDF plus both original STL files into exactly 14 collision children:
11 boxes, one cylinder, and two conservative convex hulls.

This is a query-only capability result. It is not physical evidence and does
not authorize a Phase-2 binding.

## Remaining blockers

- `EIGHT_SKILL_REAL_ISAAC_PHASE_VALIDATION_MISSING`
- `IMMUTABLE_DEPLOYMENT_COMMIT_CONTAINER_IMPORT_ASSET_CLOSURE_MISSING`
- `REAL_EXACT_PLAN_ISAAC_EXECUTOR_MISSING`
- `REAL_QUERY_ONLY_FK_PROVIDER_BINDING_MISSING`
- `REAL_SESSION_ENDPOINT_STARTUP_AND_HOST_HMAC_ATTESTATION_MISSING`

## One next command

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/m2c/audit_phase2_a3_native_build.py --project-root . --evidence-root /Users/gl/tzb-m2c-evidence/m2c-phase2-a3-native-build-v5 --expected-json reports/m2c-phase2-a3-native-build.json
```
