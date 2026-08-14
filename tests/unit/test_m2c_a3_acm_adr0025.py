from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

from m2c import audit_a3_acm_adr0025 as audit
from xh_agent.policy.qrm_lite.a3_bullet_production_adapter_v1 import (
    CONTROLLED_PANDA_SRDF_SHA256,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / audit.CONFIG_PATH
SRDF = ROOT / "robot_ws/src/xh_sim/config/m1a_panda.srdf"


def _canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _pair_map(raw: bytes) -> dict[tuple[str, str], str]:
    root = ET.fromstring(raw)
    return {
        tuple(sorted((item.attrib["link1"], item.attrib["link2"]))): item.attrib["reason"]
        for item in root.findall("disable_collisions")
    }


def test_configuration_and_controlled_srdf_bind_exact_two_adr0025_pairs() -> None:
    config = json.loads(CONFIG.read_text())
    core = dict(config)
    embedded = core.pop("configuration_sha256")
    assert embedded == _canonical(core)
    assert (
        config["accepted_adr"]["sha256"]
        == audit._load_configuration(ROOT)[0]["accepted_adr"]["sha256"]
    )
    assert config["pair_count"] == 2
    assert config["wildcard_or_category_disable_allowed"] is False
    assert CONTROLLED_PANDA_SRDF_SHA256 == hashlib.sha256(SRDF.read_bytes()).hexdigest()

    baseline = subprocess.run(
        [
            "git",
            "show",
            f"{config['controlled_srdf']['baseline_commit']}:{config['controlled_srdf']['path']}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    baseline_pairs = _pair_map(baseline)
    current_pairs = _pair_map(SRDF.read_bytes())
    assert set(current_pairs) - set(baseline_pairs) == {
        ("panda_hand", "panda_link7"),
        ("panda_link2", "panda_link4"),
    }
    assert set(baseline_pairs) - set(current_pairs) == set()
    assert current_pairs[("panda_hand", "panda_link7")] == "Adjacent"
    assert current_pairs[("panda_link2", "panda_link4")] == "Never"


def test_each_pair_uses_only_official_upstream_criterion_a() -> None:
    config = json.loads(CONFIG.read_text())
    assert config["official_upstream_srdf"] == {
        "host_role": "NODE2_QUERY_ONLY_BUILD_HOST",
        "package": "ros-jazzy-moveit-resources-panda-moveit-config",
        "package_version": "3.1.0-1noble.20260615.174424",
        "package_deb_sha256": ("f9ae0802676e10b6532d73ad7657d53b40fa6a8106b4ffdc6e13e80f36794917"),
        "path": ("/opt/ros/jazzy/share/moveit_resources_panda_moveit_config/config/panda.srdf"),
        "sha256": "1150719ea9d81139418198a50faea17e155323547d056c4edcb7ecc82fd8d317",
        "package_xml_sha256": ("b53f7a2faa2a0bd2ea28c592c90c95e66473236d95854a8592a0abf7b84780e1"),
    }
    assert {
        (item["link1"], item["link2"], item["upstream_reason"])
        for item in config["authorized_pairs"]
    } == {
        ("panda_hand", "panda_link7", "Adjacent"),
        ("panda_link2", "panda_link4", "Never"),
    }
    assert all(
        item["adr0025_criterion"] == "A_OFFICIAL_UPSTREAM_SRDF"
        and item["original_mesh_check_used"] is False
        and item["kinematic_permanence_claim_required"] is False
        for item in config["authorized_pairs"]
    )


def test_audit_rejects_unbound_upstream_bytes() -> None:
    with pytest.raises(audit.A3ACMAuditError, match="upstream SRDF binding"):
        audit.build_report(upstream_srdf=b"<robot name='panda'/>", project_root=ROOT)


def test_runtime_allowlists_match_revised_srdf() -> None:
    source = (ROOT / "scripts/m1a_moveit_execution_client.py").read_text()
    gate = (ROOT / "scripts/run_moveit_execution_gate.sh").read_text()
    assert '("panda_hand", "panda_link7")' in source
    assert '("panda_link2", "panda_link4")' in source
    assert '["panda_hand", "panda_link7"]' in gate
    assert '["panda_link2", "panda_link4"]' in gate
