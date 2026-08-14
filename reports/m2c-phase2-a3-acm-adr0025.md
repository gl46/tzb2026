# M2C Phase-2 A3 ACM source audit

Status: **PASS_EXACT_TWO_ACM_PAIRS_HAVE_OFFICIAL_UPSTREAM_SRDF_EVIDENCE**

The controlled Panda SRDF changed by exactly two `disable_collisions` pairs and
removed none. Both additions satisfy ADR-0025 §2 criterion (a), using the
byte-bound node2 MoveIt Panda SRDF:

- `panda_hand`–`panda_link7`, controlled/upstream reason `Adjacent`;
- `panda_link2`–`panda_link4`, controlled/upstream reason `Never`.

The official SRDF is
`/opt/ros/jazzy/share/moveit_resources_panda_moveit_config/config/panda.srdf`
from `ros-jazzy-moveit-resources-panda-moveit-config`
`3.1.0-1noble.20260615.174424`, SHA-256
`1150719ea9d81139418198a50faea17e155323547d056c4edcb7ecc82fd8d317`.
The revised controlled SRDF SHA-256 is
`9e139275cb11f0403abf10894f1424b80a5024e94f7d4e6fadb8bb637017edda`.

No wildcard/category disable, mesh criterion (b), collision margin, outward
padding, hull geometry, or threshold change was used. This was a query-only
source audit: no Isaac startup, physical action, target write, simulation step,
scene mutation, training, Teacher, or privileged policy input occurred.

Replay:

```bash
ssh node2 'cat /opt/ros/jazzy/share/moveit_resources_panda_moveit_config/config/panda.srdf' | PYTHONPATH=src:scripts uv run python scripts/m2c/audit_a3_acm_adr0025.py --upstream-srdf - --project-root . --expected-json reports/m2c-phase2-a3-acm-adr0025.json
```
