# M2B Failure-Rich Isaac Dataset V2 card

## Identity and gate

- version: `isaac-industrial-v2-failure-rich`
- status: `PASS_DATASET_V2_LIMITED_CLASS_COVERAGE`
- generated/valid/quarantined: 162/162/0
- failure counts: `{'EMPTY_GRASP': 51, 'RELEASE_FAILURE': 61, 'WRONG_OBJECT': 50}`
- successful recovery counts: `{'EMPTY_GRASP': 51, 'RELEASE_FAILURE': 61, 'WRONG_OBJECT': 50}`
- split train/val/test: 125/26/11
- split group leakage: `[]`
- dataset SHA-256: `c24e34493ba2226c1aa691c1b1c43993fbecdff5ad74b291e08c4913efc71362`

## Inputs and supervision

- policy-visible inputs are public observations/tracks, robot state, TaskSpec, and FailureContext.
- Teacher soft labels are absent.
- privileged simulator truth is isolated from policy input; residual hard truth is marked training-only.
- failure, predicate residual, and recovery labels are backed by physical Isaac execution evidence.

## Scope and limitations

- This is limited class coverage: each mandatory class clears the reduced 50/25 gate, not the recommended 100/50 gate.
- UNSTABLE_PLACEMENT/WRONG_CELL is not included.
- Coarse recovery supervision and residual-pair supervision are separate datasets; no zero-filled continuous target is fabricated for coarse records.
