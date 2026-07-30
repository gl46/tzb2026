#!/usr/bin/env python3
"""Convert a completed ADR-0009 raw capability-audit log into its report."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def marker(raw: str, name: str) -> dict[str, object]:
    match = re.search(rf"^{re.escape(name)}:(\{{.*\}})$", raw, re.MULTILINE)
    if not match:
        return {"status": "NOT_EVALUATED"}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {"status": "MALFORMED_RUNTIME_MARKER"}


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: summarize_m1a_bullet_capability_audit.py RUN_ID RAW_LOG LOCAL_URDF_SHA256")
    run, raw_path, local_sha = sys.argv[1:]
    raw = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", Path(raw_path).read_text(errors="replace"))
    remote_sha = next((line.split(":", 1)[1] for line in raw.splitlines()
                       if line.startswith("SOURCE_SHA:")), None)
    manifest, g1, g2, g3, g4, g5 = (
        marker(raw, name) for name in ("MANIFEST", "GATE1", "GATE2", "GATE3", "GATE4", "GATE5")
    )
    trial = next((item for item in g3.get("trials", [])
                  if item.get("label") == "bilateral_1"), {})
    contacts = trial.get("contacts", {})
    gates = {
        "controller_activation_and_segment": g1.get("success") is True,
        "physical_mimic": (
            g2.get("controls_verified") is True
            and "does not support mimic constraints, so no constraint will be created" not in raw
            and manifest.get("status") == "M1A_SDF_SPAWN_MANIFEST_VERIFIED"
            and manifest.get("mechanical_equivalence", {}).get("mimic_contract", {}).get("verified") is True
            and manifest.get("mechanical_equivalence", {}).get("ros2_control_contract", {}).get(
                "q1_structural_mimic_opt_out"
            ) == "false"
        ),
        "contact_topics": bool(
            contacts.get("left_target")
            and contacts.get("right_target")
            and contacts.get("target_cube_events", 0) > 0
        ),
        "detachable_round_trip": all(
            g4.get(key) is True
            for key in ("initial_detach", "attach", "attached_follow", "detach", "detached_decoupled")
        ),
        "cube_table_stability": g5.get("stable") is True,
    }
    evaluated = {
        "controller_activation_and_segment": "success" in g1,
        "physical_mimic": "controls_verified" in g2,
        "contact_topics": "trials" in g3,
        "detachable_round_trip": "initial_detach" in g4,
        "cube_table_stability": "stable" in g5,
    }
    status = (
        "M1A_BULLET_CAPABILITY_VERIFIED"
        if all(gates.values()) and remote_sha == local_sha
        else "M1A_BULLET_CAPABILITY_BLOCKED"
    )
    interface_count = re.search(r"^\* Found (\d+) interfaces in library file:$", raw, re.MULTILINE)
    data = {
        "run_id": run,
        "status": status,
        "gates": gates,
        "evaluated": evaluated,
        "local_gazebo_urdf_sha256": local_sha,
        "remote_gazebo_urdf_sha256": remote_sha,
        "model_match": remote_sha == local_sha,
        "generated_manifest": manifest,
        "controller_probe": g1,
        "hand_probe": g2,
        "contact_probe": g3,
        "detachable_probe": g4,
        "stability_probe": g5,
        "raw_log": raw_path,
        "installed_versions_retained": "VERSION_INFO_BEGIN" in raw,
        "bullet_plugin_info_retained": "SetMimicConstraintFeature" in raw,
        "bullet_plugin_interface_count": int(interface_count.group(1)) if interface_count else None,
    }
    Path("reports/m1a-bullet-capability-audit.json").write_text(json.dumps(data, indent=2) + "\n")
    Path("reports/m1a-bullet-capability-audit.md").write_text(
        "# M1A Bullet capability audit\n\n"
        + json.dumps({"status": status, "gates": gates, "evaluated": evaluated,
                      "raw_log": raw_path}, indent=2)
        + "\n"
    )
    print(json.dumps({"status": status, "gates": gates, "evaluated": evaluated,
                      "model_match": remote_sha == local_sha}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
