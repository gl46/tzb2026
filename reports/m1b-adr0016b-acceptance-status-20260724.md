# M1B ADR-0016b acceptance status (2026-07-24)

Status: **`GO — ADR-0013 acceptance 3 and 4 PASS`**.

The current-geometry public perception gate is measured `GO`: held-out p90
X/Y/Z is 2.295 / 4.793 / 2.080 mm, versus unchanged 0.6-times-envelope limits
of 9 / 9 / 3 mm.  This supersedes the old 50 mm × 100 mm `NO_GO` audit and
authorizes only fresh public-perception-driven acceptance records.

The matching beta spawn evidence is
`reports/m1b-adr0013-per-object-spawn-provenance.json`: the remote generated
SDF manifest verified 11 per-cylinder detachable contracts, with only the
finger mimic and detachable plugin blocks differing from the source model.

## Acceptance 3 — physical round-trip

The fresh industrial-world record is
`reports/m1b-adr0013-current-geometry-attached-roundtrip.json` (SHA-256
`30c103a07e9dbfdeb388a3c6315365e5adaf55937da02053cb3871756addac35`).

- The production selection was public track `track-349bcd6a`; no simulator
  truth was an online policy input.
- The evaluator mirrored that public collision ID to `panda_link7` only after
  the broker had physically attached its internal entity.
- Attached motion executed and converged; link/object moved 28.523 / 28.503
  mm with only 0.0077 mm relative drift.
- Detach was observed, the physical hand was released, and the decouple move
  executed with a 34.511 mm relative-change measurement.

The reset physical non-coupling source record SHA-256 is
`163c11ba555d4b151070f767f8d05bef653205277bd698c95b31382d34fd7861`.
The public selection and production-grasp source records are SHA-256
`953173297a0dd4ba3a50da81b8c74a07a0f90a4c4fa2be1ee58af6ee43f55425` and
`24e96196c778b8021c49817a8c914b34a7c43e96a5efdc771c5502f3350f09bf`.

## Acceptance 4 — live WRONG_OBJECT drill

The fresh drill is
`reports/m1b-adr0013-current-geometry-wrong-object-drill.json` (SHA-256
`62e45bca91156a40e071a759e0c8311a9ab8eb5a36013fdc6a40bf984dd3bfc7`).

- The pre-actuation public task target was `track-edec3eae`; the deliberately
  commanded non-target public track was `track-349bcd6a`.
- The broker honestly attached `cylinder_03`; this identifier stays inside
  actuation/evaluation records and never selected a public target.
- A public collision-checked 100 mm lift and home-observation retreat exposed
  the table without detach.  Three post-grasp public RGB-D observations each
  recovered 9 tracks.  Their only persistent vacancy was
  `track-349bcd6a`.
- Before reading supervision, public identity comparison produced
  `WRONG_OBJECT` and triggered
  `Reobserve → SafePlaceNonTarget → ReassociateTarget → Approach → Regrasp`.
  The later evaluator record scored `wrong_object=true`. Its episode record
  includes static-TF frame names, numeric transform values, and chain SHA-256
  `3749611ee229c40b0109edcfbec3f3d7f7d80b3e7baf9b59cd25bd2eb0046573`.

The reset, intended-target selection, deliberately commanded selection,
production grasp, and public lift/retreat source-record SHA-256 values are,
respectively, `c64024015fcb59a45ce744f59e55e1d653c6f8f3883b97fe6161a5a4b713d5d8`,
`c053b0610dda6b551cd0d94e74ad70310e91105499d756ed123a6e7705c23ac2`,
`c478ca81ffb39803db9b314012cfaee349d1de4d7317796809496ad7892b3a7e`,
`7999bdc365e0280b4a701cb7fc3014b78cd46087a18bb5ef11117c9501df0f77`, and
`59f1ae4277d40ff0fcc5a4f44142ed818b8e634d00948dfa4c032b9dbafc3628`.

The former diagnostic acceptance files remain historical only; they are not
used by this conclusion.
