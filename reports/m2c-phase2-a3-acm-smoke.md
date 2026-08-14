# M2C Phase-2 A3 ACM query-only smoke

Status: **PASS_QUERY_ONLY_A3_ACM_SMOKE_CLEAR**

The ADR-0025 §2 SRDF revision was replayed against the same immutable
query-only A3 deployment closure used by the earlier comparison. All 74
continuous-self-collision requests returned `CLEAR`; there were zero
collision rejections and zero query failures. The static start state is now
clear under the exact two upstream-proven ACM pairs.

This result is query-only. Isaac/Kit was not loaded, and there were zero
articulation target writes, simulation steps, scene mutations, physical
actions, training runs, Q-B evaluations, Teacher uses, or privileged-truth
policy inputs. `formal_execution_eligible` remains false: this closes the
static-home A3 blocker only, not the real eight-skill deployment/evidence
closure.

Evidence:

- immutable implementation commit `f4c0ec89142a041a4651133027ade66bf878c40e`;
- smoke receipt SHA-256 `146e2b25a02ecfd87fc04bcb88cf56d43a965dd3b6f39ab18b7786ec666b4be1`;
- runtime image `sha256:783444c706538aa76cf5126e911ddc5e618779e6105305ad4af4260362a30aa9`;
- native builder image `sha256:01d3c57bde2ce5ff1655ab5739d0729ae7ea035be2ac56bd391a4357e3c4307e`;
- revised controlled SRDF SHA-256 `9e139275cb11f0403abf10894f1424b80a5024e94f7d4e6fadb8bb637017edda`;
- ACM source audit `reports/m2c-phase2-a3-acm-adr0025.json`.

Replay:

```bash
PYTHONPATH=src:scripts uv run python scripts/m2c/audit_phase2_a3_acm_smoke.py --project-root . --smoke-receipt /Users/gl/tzb-m2c-evidence/m2c-phase2-a3-acm-smoke-f4c0ec8/query-only-deployment-smoke.json --expected-json reports/m2c-phase2-a3-acm-smoke.json
```
