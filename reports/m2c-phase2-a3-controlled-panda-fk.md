# M2C Phase-2 A.3 controlled-Panda FK comparison

- Status: **PASS_QUERY_ONLY_FK_MATCHES_INDEPENDENT_NODE2_KDL**
- Production binding set: **false**
- Formal execution eligible: **false**
- Isaac started / physical execution / training: **false / false / false**
- Teacher / privileged truth policy input: **false / false**

`ControlledPandaReadOnlyFKProviderV1` now provides deterministic, pure
double-precision transforms for all twelve collision-bearing robot links from
the exact controlled URDF. Its input is the complete executor state in the
explicit order `panda_joint1..7`, `panda_finger_joint1`,
`panda_finger_joint2`; the two finger values must obey the frozen mimic
relation. Missing links, reordered joints, limit violations, inconsistent
finger states, symlinks, and URDF byte drift all reject before a collision
query.

The provider was compared on node2 against a separate C++ program using ROS
Jazzy `kdl_parser` and Orocos KDL 1.5.1. The evidence freezes twelve states,
including home, zero, interior configurations, gripper endpoints, and joint
limit boundaries. Every state covers all twelve collision link frames: 144
state/link rows total.

| Metric | Observed maximum | Audit tolerance |
|---|---:|---:|
| translation error | `2.5438405243138006e-16 m` | `1e-12 m` |
| orientation error | `5.147892387644517e-16 rad` | `1e-12 rad` |

The comparison uses the relative-quaternion vector norm near identity, rather
than `acos(dot)`, to avoid magnifying harmless last-bit rounding. The original
A.3 STL evidence was also replayed locally: a real-provider FK receipt covers
all twelve link sequences and builds the full 14-child query-only collision
world. None of these receipts claim physical evidence.

External evidence is frozen read-only at
`/Users/gl/tzb-m2c-evidence/m2c-phase2-a3-controlled-panda-fk-kdl-v1`.
It contains the exact URDF, verifier and builder source, compiled verifier,
manifest, and 144-row CSV. The KDL parser library SHA is `3eeabbfc…`, Orocos
KDL SHA is `c826b6c2…`, and verifier binary SHA is `5499dfb0…`.

This closes implementation and independent numeric validation of the FK
provider. It does not close deployment binding, a real Isaac exact-plan
executor, eight-skill phase evidence, immutable session closure, or endpoint
startup/HMAC evidence; all production bindings remain `None`.

## One next command

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/m2c/audit_controlled_panda_fk_v1.py --project-root . --evidence-root /Users/gl/tzb-m2c-evidence/m2c-phase2-a3-controlled-panda-fk-kdl-v1 --expected-json reports/m2c-phase2-a3-controlled-panda-fk.json
```
