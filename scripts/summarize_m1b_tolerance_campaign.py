#!/usr/bin/env python3
"""Summarize the bounded, calibration-only M1B tolerance campaign."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trial_success(record: dict[str, object]) -> bool:
    attach = record.get("attach", {})
    return bool(
        record.get("baseline_perception_free")
        and record.get("bilateral_same_entity_contact")
        and isinstance(attach, dict)
        and attach.get("state_confirmed")
    )


def summarize(worklist: dict[str, object], raw_dir: Path) -> dict[str, object]:
    planned = worklist.get("trials", [])
    if not isinstance(planned, list) or len(planned) != 81:
        raise ValueError("worklist must contain exactly 81 planned trials")
    summaries: list[dict[str, object]] = []
    by_point: dict[tuple[str, float], list[bool]] = defaultdict(list)
    for index, expected in enumerate(planned):
        raw_path = raw_dir / f"trial-{index:03d}.json"
        if not raw_path.is_file():
            raise ValueError(f"missing raw trial evidence: {raw_path}")
        record = json.loads(raw_path.read_text(encoding="utf-8"))
        if record.get("provenance") != "CALIBRATION_ONLY_INITIALIZATION":
            raise ValueError(f"trial {index} has invalid provenance")
        if record.get("trial") != expected:
            raise ValueError(f"trial {index} does not match immutable worklist")
        if not record.get("baseline_perception_free"):
            raise ValueError(f"trial {index} is not the perception-free tolerance baseline")
        axis, offset = str(expected["axis"]), float(expected["offset_m"])
        success = trial_success(record)
        by_point[(axis, offset)].append(success)
        summaries.append({
            "trial_index": index, "axis": axis, "offset_m": offset,
            "repetition": int(expected["repetition"]), "scene_seed": int(expected["scene_seed"]),
            "object_slot": int(expected["object_slot"]), "success": success,
            "raw_evidence_path": str(raw_path), "raw_evidence_sha256": sha256(raw_path),
        })
    point_results: dict[str, dict[str, object]] = {}
    for (axis, offset), results in sorted(by_point.items()):
        if len(results) != 3:
            raise ValueError(f"{axis}/{offset} has {len(results)} repetitions, expected 3")
        point_results[f"{axis}:{offset:+.3f}"] = {
            "axis": axis, "offset_m": offset, "successes": sum(results), "attempts": len(results),
            "pass": sum(results) >= 2,
        }
    envelope: dict[str, float | None] = {}
    for axis in ("x", "y", "z"):
        magnitudes = sorted({abs(float(item["offset_m"])) for item in point_results.values() if item["axis"] == axis})
        accepted: float | None = None
        for magnitude in magnitudes:
            required_offsets = {0.0} if magnitude == 0.0 else {-magnitude, magnitude}
            if all(
                bool(point_results[f"{axis}:{offset:+.3f}"]["pass"])
                for offset in required_offsets
            ) and all(
                bool(point_results[f"{axis}:{offset:+.3f}"]["pass"])
                for smaller in magnitudes if smaller <= magnitude
                for offset in ({0.0} if smaller == 0.0 else {-smaller, smaller})
            ):
                accepted = magnitude
            else:
                break
        envelope[axis] = accepted
    return {
        "schema_version": "M1BToleranceEnvelopeV1",
        "status": "COMPLETE_CALIBRATION_ONLY",
        "trial_count": len(summaries), "success_predicate": "bilateral_same_entity_contact_and_observed_attach",
        "point_pass_rule": "at_least_2_of_3", "monotonic_closure": "both_signed_offsets_and_all_smaller_magnitudes_pass",
        "tolerance_envelope_m": envelope, "point_results": point_results, "trials": summaries,
        "truth_boundary": "settled simulator truth was calibration-only initialization; raw contact/broker/attach evidence is production-path evidence.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worklist", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(json.loads(args.worklist.read_text(encoding="utf-8")), args.raw_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "trial_count": result["trial_count"], "tolerance_envelope_m": result["tolerance_envelope_m"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
