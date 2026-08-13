# M2C Phase-2 A.3 native build audit

- Status: `PASS_QUERY_ONLY_NATIVE_BUILD_AND_GEOMETRY_REPLAY`
- Builder image ID: `sha256:ae10eb6cf7eda37d34e394079c7638fc153b3f12314206ad0cab6d0cddc9fc22`
- Native shared object SHA-256: `916a6bd694f7452cbc60c1ba6230aed1b5fa79e496212f7e4f317e71eae0251a`
- Native build receipt file SHA-256: `39db568adce5b37c2191c1c43a3de77ba9aa6ab459fa4fb04200f374d97a5e23`
- Adapter build manifest file SHA-256: `6065bb1cefcb01520c1196e157a6d95708a03f55df56fc4fa953708fd438ba67`
- Complete compiler-input manifest SHA-256: `10cd6cd71e91e7b7ded8b4984ab99a8e6c625b4a18740a0714d23de29061fc7c`
- Controlled-Panda geometry receipt SHA-256: `6e25fd5f32e664fb28be6e0c1a4a426eaa851979336d600a487b08dd60ceff23`
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
PYTHONPATH=src:scripts .venv/bin/python scripts/m2c/audit_phase2_a3_native_build.py --project-root . --evidence-root /Users/gl/tzb-m2c-evidence/m2c-phase2-a3-native-build-v3 --expected-json reports/m2c-phase2-a3-native-build.json
```
