# M2C S4 current blockers

- Status: **BLOCKED_UNMEASURED_HUMAN_DIRECTION_REQUIRED**
- Checked HEAD: `2ec9fde20804b43de8819497452b826d42285ee7`
- Q-A: **PASSED**
- Q-B: **UNMEASURED**
- `pure_model_success_episodes`: **null**, not zero
- D1 / D2: **false / false**

## PATH_BLOCKED training entry

The outcome-blind frozen V3 manifest contains 36 TRAIN keys. Across the initial
collection and the separately outcome-blind Batch-02 and Batch-03
preregistrations, 11 unique keys were attempted and 10 byte-verified scripted
eight-step chains were produced. None satisfied the complete unchanged
training-eligibility path: terminal exclusions included public-predicate,
contact-gate, and pregrasp-IK rejection, while two other attempts terminated at
the infrastructure/pre-Kit boundary before producing a chain. Therefore no row
was packaged or marked training-eligible. Training, model rollout, and formal
Q-B evaluation remain unexecuted.

Batch-03 exhausted its fixed three-key, no-retry/no-replacement authorization.
Scene 16073 exposed a public-track association limitation after a physically
successful lift; its frozen public predicate still returned false. The physical
receipt cannot backfill public success. A fourth batch or a changed tracker is
not authorized by current bytes.

The V3 collection worker and packager now require an exact committed,
outcome-blind selected-key preregistration; a create-only global claim; an
immutable Git-tree snapshot and image ID; a stage-bound host capability; and
the claim→launch→one-shot broker entry→terminal→raw→package receipt chain.
Historical V2 and Batch-02/03 evidence remain replayable without being
reinterpreted. There is no active selected-key preregistration for Batch-04.

An additional production lock remains intentionally unset:
`V3_HOST_RUNTIME_LAUNCHER_BINDING=None`. Python code cannot attest the
interpreter and dependencies that executed before its own import, so both the
canonical V3 CLI and direct programmatic worker/packager calls fail closed
until a separately reviewed immutable pre-Python launcher or host container,
complete dependency inventory, and verifier are frozen. This hardening commit
is `2ec9fde20804b43de8819497452b826d42285ee7`; it authorizes no collection.

Human direction is required on
`docs/decisions/M2C-S4-PUBLIC-TRACK-REID-ADR-REQUEST.md` (A/B/C). Option A
requires a complete, outcome-independent PublicTrackAssociatorV2 contract and
then a separate wholly-new TRAIN-key preregistration; option B stops PATH; C
must be equally complete. Code may not infer a choice or numeric thresholds.

## ADR-0022 Phase-2 entry

The exact-plan A.3 contract now recomputes canonical physical-state digests,
checks full cross-phase state continuity, phase allowlists and phase/config
timeouts, and strictly replays every limit, workspace, collision, attachment,
controller and safety predicate. It remains hard-coded
`formal_execution_eligible=false` and lacks a trusted host append-only signing
receipt. The implementation source is bound at
`a177efa148111aa004bb2780378f58ae4d33762474ecbdbaae38a4a70be84713`.

The source-bound Isaac/Lula gateway manifest names nine expected Isaac 6.0.1
image-closure members and records all four production query capabilities as
`NOT_AVAILABLE`. This report binds the gateway implementation source at
`8572c0a3a35a1791dbf8c55707eaf75fa90558ea06d6e0deda490616651ac492`;
it does not claim a live image-root closure replay, a production query callback,
or host evidence. Phase-2 therefore records the single source-audit finding
`SOURCE_AUDIT_PRODUCTION_QUERY_CALLBACK_NOT_AVAILABLE`, without inferring
backend-specific capability claims for which no artifact is bound.

The continuous self-collision geometry and subdivision boundary is a separate
human decision. The post-implementation audit request
`docs/decisions/M2C-S4-A3-CONTINUOUS-SELF-COLLISION-ADR-REQUEST.md` offers
A/B/C and remains `NOT APPROVED`; it authorizes no code, geometry replacement,
source binding, deployment, or execution.

The frozen M2B B0 has no callable that can continue the already-evolved formal
Isaac session. Starting its standalone runner creates a different episode, and
reassembling low-level helpers would be a new B0 implementation. Human
direction is required on
`docs/decisions/M2C-S4-B0-ACTIVE-SESSION-FALLBACK-ADR-REQUEST.md` (A/B/C).

All four source bindings remain literal `None`; no binding addendum or unlock
config was generated.

## Boundaries and verification

- Teacher use: **false**; Nano/BWM/Super remain CANDIDATE /
  CANDIDATE_LICENSE_PENDING / PARKED.
- Privileged simulator truth as policy input: **false**.
- B0, M2B evidence, safety/IK/collision/controller/schema gates: unchanged.
- Additional collection after Batch-03: **false**.
- Active Batch-04 preregistration / host-runtime launcher binding: **absent /
  null**.
- Training / physical SMOKE / formal Q-B evaluation: **false / false / false**.
- V3 authorization/history regression: **56 passed**; S4 entry regression:
  **12 passed**.
- Failures: no product-test failure; the outcome is a deliberate fail-closed
  blocker. The broader M2C run has two failures and five setup errors caused
  only by a separate uncommitted S6 preregistration SHA drift (`2d5e…` actual
  versus frozen `01786…`); those files are outside this report update.

Next command:

```bash
sed -n '1,280p' docs/decisions/M2C-S4-PUBLIC-TRACK-REID-ADR-REQUEST.md && \
  sed -n '1,260p' docs/decisions/M2C-S4-B0-ACTIVE-SESSION-FALLBACK-ADR-REQUEST.md && \
  sed -n '1,360p' docs/decisions/M2C-S4-A3-CONTINUOUS-SELF-COLLISION-ADR-REQUEST.md && \
  sed -n '1,140p' src/xh_agent/policy/qrm_lite/s4_v3_collection_authorization_v1.py
```
