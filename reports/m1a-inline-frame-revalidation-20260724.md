# M1A inline-hand-frame revalidation (2026-07-24)

Status: **`CONTACT_GATED_CONSTRAINT_VERIFIED`**.

The ADR-0016 local-finger-axis correction and the measured symmetric-close
tolerance were revalidated in a fresh, reset-isolated M1A S3 batch on node2.
This is a new evidence record; it does not alter the historical
`m1a-runtime-grasp-v1` manifest.

| Measure | Observed result |
| --- | --- |
| Run ID | `m1a-inline-frame-final-20260724-0240` |
| URDF SHA-256 | `6678ff409d60f074283805879f53edaa939ead34f97a5a961ee67f6229b44ba8` |
| Reset-isolated episodes | 10 |
| Complete contact-gated pick/place successes | 9 |
| Required threshold | at least 8 of 10 |
| Runtime-blocked episodes | 0 |
| Positively verified releases | 9 |
| Direct object pose writes | 0 |

The one rejection was `CONTACT_CLOSURE_FAILURE`: its bilateral-contact and
simulation-timestamp windows were incomplete, so the client did not send an
attach request. It is retained as a failure, not reclassified as success.

The corrected top-down family placed the cube on the inline hand's local
`+Z` finger line. For the first final-run episode, the physical close stopped
at 31.519 mm per finger after a 27.000 mm command. The action used the
predeclared 8.5 mm contact-stall tolerance (31.5 mm measured contact surface,
3 mm engine allowance, 1 mm contract allowance), reported controller success,
and then independently passed bilateral same-entity contact, corridor, speed,
and attach-state checks.

Raw local logs: `logs/m1a-inline-frame-final-20260724-0240-s3-episode-1.log`
through `logs/m1a-inline-frame-final-20260724-0240-s3-episode-10.log`.
The structured batch result is retained locally in `reports/m1a-contact-gate.json`
(SHA-256 `de20bd90bd8033850deb5d0898481f04c5ab68e632e321ec81c1aa74adb4cc7a`).

