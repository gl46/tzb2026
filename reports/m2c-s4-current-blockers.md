# M2C S4 current blockers

- Status: **BLOCKED_UNMEASURED_IMPLEMENTATION_AND_EVIDENCE_REQUIRED**
- Checked HEAD: `d47f3055ca54f84d46e30f44745b279740179fe7`
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

ADR-0024 §4 sets the accepted project evidence bar and explicitly rescinds the
`V3_HOST_RUNTIME_LAUNCHER_BINDING` precondition. The code-level binding and its
direct-call lock have therefore been removed rather than silently retained.
Collection is still unavailable because there is no active outcome-blind
selected-key preregistration; ADR-0024 §5 permits creating Batch-04 only after
the V4 associator contract passes local tests.

ADR-0024 selects Option A for public re-identification and freezes its complete
input, hypothesis, assignment, ambiguity and lifecycle contract. The remaining
work is implementation and local verification, followed by a separate wholly
new outcome-blind Batch-04 preregistration; old evidence remains unchanged.

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

ADR-0024 selects A3 Option A with bounded delegation. The implementation must
record every numeric value and source in the Phase-2 binding addendum and stay
within the human-set conservative bounds; it does not weaken executor geometry
or existing evidence.

ADR-0024 selects active-session B0 Option B: every invalid pointer/mapping/cell
or preflight rejection terminates with `NO_PHYSICAL_EXECUTION`, stays in the
denominator and cannot count strict-pure. The fallback wrapper/A.5 requirement
is withdrawn; the independent B0 comparison arm remains byte-identical.

The accepted directive removes the B0-wrapper and trusted-host-signature
preconditions, but does not fabricate the still-missing exact-plan execution
and deployment evidence. The entry-gate schema update, contract smoke, binding
addendum and remaining source bindings are therefore still pending. No unlock
config was generated.

## Boundaries and verification

- Teacher use: **false**; Nano/BWM/Super remain CANDIDATE /
  CANDIDATE_LICENSE_PENDING / PARKED.
- Privileged simulator truth as policy input: **false**.
- B0, M2B evidence, safety/IK/collision/controller/schema gates: unchanged.
- Additional collection after Batch-03: **false**.
- Active Batch-04 preregistration / extra host-runtime launcher precondition:
  **absent / not required by ADR-0024**.
- Training / physical SMOKE / formal Q-B evaluation: **false / false / false**.
- V3 authorization/history regression after applying ADR-0024 §4: **55
  passed**.
- Failures: no product-test failure; the outcome is a deliberate fail-closed
  blocker. The S6 preregistration was restored to its frozen `01786e2c…`
  bytes; its focused 10-test replay and the 555-test M2C suite are green.

Next command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:scripts .venv/bin/python -m pytest \
  -q -p no:cacheprovider tests/unit/test_m2c_public_track_associator_v2.py \
  tests/unit/test_m2c_public_tracks_v4.py
```
