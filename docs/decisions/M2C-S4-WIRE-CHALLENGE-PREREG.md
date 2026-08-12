# M2C S4 formal wire challenge pre-registration

- Status: **PRE-REGISTERED; DOES NOT AUTHORIZE EXECUTION**
- Date: 2026-08-13 (Asia/Shanghai)
- Observation timing: **written before any formal Q-B physical result**
- Teacher used: **false**
- Privileged simulator truth used as policy input: **false**

This document freezes one public, single-use challenge nonce and run identity
for each of the three already frozen S4 physical-prerequisite SMOKE keys.  The
machine-readable source is `configs/m2c_s4_wire_challenges.json`.

The challenge is deliberately public and is not an authentication key.  Its
only purpose is to prevent a previously signed transcript for the same scene
from being transplanted into a later formal receipt.  The challenge must be
carried by the signed Isaac start request, every signed Qwen request, both
host-local authentication attestations, the formal runner evidence, and the
outer physical-integration receipt.

Each challenge may be consumed by at most one formal attempt.  A rejected,
partial, or unsuccessful attempt still consumes it.  A replacement challenge
requires a new pre-registration commit made before observing the replacement
attempt.  No challenge may be selected, regenerated, or edited after seeing a
physical or model outcome.

This pre-registration does not relax any existing blocker.  In particular it
does not set the formal runner, deployment closure, unchanged-B0 wrapper, or
offline authentication verifier bindings; does not approve either outstanding
physical ADR request; and does not authorize training, SMOKE, or Q-B evaluation.

Endpoint HMAC secrets remain separate and host-local.  The node2 verifier may
read only the Qwen HMAC secret; the labserver verifier may read only the Isaac
HMAC secret.  Their Ed25519 attestation private keys must be controlled by an
independent evidence authority and may not be present in the repository,
runner environment, model service, or Isaac service.  Until a human provisions
and freezes both public trust roots and custody procedure, all signed
attestations remain ineligible for formal entry.
