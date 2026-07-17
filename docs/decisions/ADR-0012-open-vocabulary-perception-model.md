# ADR-0012: Open-vocabulary semantic proposal adapter

Date: 2026-07-17

## Decision

Use a pluggable Grounding DINO adapter for optional 2-D text-conditioned
semantic proposals, with the geometric RGB-D baseline as mandatory fallback.

## Candidate review

| Candidate | License | Small-scale path | Decision |
| --- | --- | --- | --- |
| Grounding DINO | Apache-2.0 code license | frozen-backbone detector head | selected adapter, not installed yet |
| OWL-ViT | Apache-2.0 repository/model-card dependent | Transformers fine-tuning | not selected: adds a second runtime path |
| SAM-family only | model-specific | masks but no target text selection alone | insufficient as the sole semantic component |

The adapter downloads no weights by default. Its configured limit is 20 GiB;
the required recording is model revision/hash, source URL, installed package
versions and a license review before a real run. No Teacher, world model, Qwen
or VLA is selected.

## Rationale

The selected component cannot enter control directly. It may label a 2-D region;
RGB-D geometry remains the source of 3-D position and pose state.
