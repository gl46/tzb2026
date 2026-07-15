from __future__ import annotations

from pathlib import Path

from xh_agent.contracts.models import BakeoffSampleV0


FAILURES = [None, "empty_grasp", "slip", "obstacle", "release_failure"]


def main() -> int:
    output = Path("data/manifests/teacher-bakeoff-phase1.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    samples = []
    for index in range(20):
        failure = FAILURES[index % len(FAILURES)]
        sample = BakeoffSampleV0(
            sample_id=f"placeholder-{index + 1:02d}", initial_rgb_uri=f"pending://scene/{index + 1}/rgb",
            depth_uri=f"pending://scene/{index + 1}/depth", language_task="pick and place configured object",
            action_trajectory_uri=f"pending://scene/{index + 1}/action", action_mapping_revision="PENDING_OFFICIAL_MAPPING",
            gazebo_future_uri=f"pending://scene/{index + 1}/future", simulator_hard_label_uri=f"pending://scene/{index + 1}/supervision",
            scene_id=f"seed-{202607 + index}", failure_type=failure,
        )
        samples.append(sample.model_dump_json())
    output.write_text("\n".join(samples) + "\n", encoding="utf-8")
    print(f"wrote {len(samples)} placeholders to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
