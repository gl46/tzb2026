#!/usr/bin/env python3
"""Build the 6-case Teacher causal suite for human visual review.

CPU-only. Emits:
  - data/manifests/teacher-causal-suite.jsonl
  - data/manifests/teacher-causal-suite-requests.json
  - reports/teacher-causal-suite-manual-review.md

Does not download weights or run GPU inference.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "teacher-causal-suite.yaml"
OUT_MANIFEST = ROOT / "data" / "manifests" / "teacher-causal-suite.jsonl"
OUT_REQUESTS = ROOT / "data" / "manifests" / "teacher-causal-suite-requests.json"
OUT_REVIEW = ROOT / "reports" / "teacher-causal-suite-manual-review.md"

# Evaluation action layout (relative comparison only; not official Franka mapping).
# values[t] = [dx, dy, dz, droll, dpitch, dyaw, gripper]
# units: m, rad, gripper in [0,1] where 0=open 1=closed
DIMS = ["dx", "dy", "dz", "droll", "dpitch", "dyaw", "gripper"]
FPS = 10.0
HOLD = 8
T_SHORT = 24
T_MED = 40
T_LONG = 56


def zeros(n: int) -> list[list[float]]:
    return [[0.0] * 7 for _ in range(n)]


def set_gripper(rows: list[list[float]], value: float) -> list[list[float]]:
    out = [list(r) for r in rows]
    for r in out:
        r[6] = value
    return out


def segment(n: int, dx=0.0, dy=0.0, dz=0.0, gripper=0.0) -> list[list[float]]:
    step = [dx / n, dy / n, dz / n, 0.0, 0.0, 0.0, gripper]
    return [list(step) for _ in range(n)]


def concat(*parts: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for p in parts:
        out.extend(p)
    return out


def traj(values: list[list[float]], skill: str, summary: str) -> dict[str, Any]:
    return {
        "schema_version": "ActionTrajectoryV0",
        "embodiment": "franka_panda_eval",
        "representation": "ee_delta",
        "coordinate_frame": "world",
        "units": "m_rad_gripper01",
        "fps": FPS,
        "values": values,
        "dimension_names": DIMS,
        "normalization_method": "identity",
        "normalization_revision": "eval-v0",
        "source_skill": skill,
        "source_policy": "causal_suite_v0",
        "action_summary": summary,
        "duration_s": round(len(values) / FPS, 2),
        "num_frames": len(values),
    }


def build_actions() -> dict[str, dict[str, Any]]:
    """One explicit action trajectory per variant_id."""
    open_g, close_g = 0.0, 1.0

    # C1: hold pose, gripper open
    c1 = traj(set_gripper(zeros(T_SHORT), open_g), "OBSERVE", "hold_pose_open_gripper")

    # C2: pure lateral ±10 cm
    c2_left = traj(
        concat(segment(T_SHORT, dy=-0.10, gripper=open_g)),
        "MOVE",
        "ee_delta_y_-0.10_open",
    )
    c2_right = traj(
        concat(segment(T_SHORT, dy=+0.10, gripper=open_g)),
        "MOVE",
        "ee_delta_y_+0.10_open",
    )

    # C3: approach → (close|open) → lift 12 cm
    approach = segment(16, dz=-0.08, gripper=open_g)
    lift = segment(16, dz=+0.12, gripper=close_g)
    lift_open = segment(16, dz=+0.12, gripper=open_g)
    dwell_close = set_gripper(zeros(HOLD), close_g)
    dwell_open = set_gripper(zeros(HOLD), open_g)
    c3_close = traj(concat(approach, dwell_close, lift), "GRASP", "approach_close_lift")
    c3_open = traj(concat(approach, dwell_open, lift_open), "MOVE", "approach_open_lift")

    # C4: approach offset +4 cm in Y, close, lift (should empty-grasp)
    approach_miss = segment(16, dy=+0.04, dz=-0.08, gripper=open_g)
    c4 = traj(concat(approach_miss, dwell_close, lift), "GRASP", "approach_offset_0.04_close_lift")

    # C5: place variants from an already-grasped prior (language + trajectory)
    # upright into r2c3: move then release open
    place_move = segment(20, dx=0.12, dy=-0.05, dz=0.02, gripper=close_g)
    release = set_gripper(zeros(HOLD), open_g)
    backoff = segment(12, dz=+0.06, gripper=open_g)
    c5_r2c3 = traj(concat(place_move, release, backoff), "PLACE", "place_bin_r2c3_upright_release")
    outside = segment(20, dx=0.18, dy=0.12, dz=0.00, gripper=close_g)
    c5_out = traj(concat(outside, release, backoff), "PLACE", "place_outside_release")
    # sideways: add yaw delta while moving above bin, then release
    side = []
    for i in range(20):
        side.append([0.12 / 20, -0.05 / 20, 0.04 / 20, 0.0, 0.0, (1.57 / 20), close_g])
    c5_side = traj(concat(side, release, backoff), "PLACE", "place_above_sideways_release")

    # C6 recovery contrast from a failed state prior
    press = concat(segment(16, dz=-0.06, gripper=close_g), set_gripper(zeros(HOLD), close_g))
    c6_press = traj(press, "PLACE", "recovery_press_down")
    recovery = concat(
        segment(12, dz=+0.08, gripper=open_g),  # backoff
        segment(12, dy=-0.03, gripper=open_g),  # re-center
        segment(12, dz=-0.08, gripper=open_g),  # re-approach
        set_gripper(zeros(HOLD), close_g),  # regrasp
        segment(12, dz=+0.10, gripper=close_g),  # lift
        segment(16, dx=0.10, dy=-0.04, gripper=close_g),  # move to bin
        set_gripper(zeros(HOLD), open_g),  # place
    )
    c6_rec = traj(recovery, "REGRASP", "recovery_backoff_regrasp_place")

    return {
        "hold_open": c1,
        "move_left_10cm": c2_left,
        "move_right_10cm": c2_right,
        "approach_close_lift": c3_close,
        "approach_open_lift": c3_open,
        "offset_close_lift": c4,
        "place_bin_r2c3_upright": c5_r2c3,
        "place_outside_bin_release": c5_out,
        "place_above_bin_sideways_release": c5_side,
        "press_down_again": c6_press,
        "backoff_regrasp_place": c6_rec,
    }


SCENE = {
    "scene_id": "industrial-table-cylinder-bin-v0",
    "description_zh": (
        "工业桌面俯视/斜视固定相机。桌上有一根竖直立着的金属圆柱零件，"
        "右侧有分格料箱（可见第2排第3格），背景墙面与桌面纹理保持固定。"
        "画面中有一只 Franka Panda 机械臂与平行夹爪，初始夹爪张开，位于零件上方附近。"
    ),
    "camera": "fixed third-person industrial RGB, no camera motion",
    "objects": {
        "cylinder": "upright metal cylinder on table, graspable",
        "bin": "partitioned bin with visible row2-col3 cell",
        "table": "static workbench",
        "arm": "Franka Panda with two-finger gripper, initially open",
    },
    "initial_rgb_uri": "pending://shared/industrial-table-cylinder-bin-v0/rgb.png",
    "depth_uri": "pending://shared/industrial-table-cylinder-bin-v0/depth.png",
    "notes": "All paired variants under one case MUST share this exact initial frame.",
}


PROMPTS = {
    "hold_open": "Predict the future video if the robot holds still with gripper open.",
    "move_left_10cm": "Predict the future video if the end-effector moves 10 cm left; gripper stays open; no grasp.",
    "move_right_10cm": "Predict the future video if the end-effector moves 10 cm right; gripper stays open; no grasp.",
    "approach_close_lift": "Predict the future video: approach cylinder, close gripper, lift. Object should rise only if grasped.",
    "approach_open_lift": "Predict the future video: same approach and lift path, but gripper remains open (no grasp).",
    "offset_close_lift": "Predict the future video: approach 4 cm beside the cylinder, close gripper, lift (empty grasp).",
    "place_bin_r2c3_upright": "Predict the future video: place grasped upright cylinder into bin row2 col3, then release.",
    "place_outside_bin_release": "Predict the future video: move grasped cylinder outside the bin and release.",
    "place_above_bin_sideways_release": "Predict the future video: hold cylinder sideways above bin, then release.",
    "press_down_again": "From a failed placement state, predict future if the robot only presses down again.",
    "backoff_regrasp_place": "From the same failed state, predict future if robot backs off, regrasps, then places normally.",
}


REVIEW_EXPECT = {
    "C1_static_hold": [
        "臂几乎不动",
        "零件不漂移/瞬移",
        "料箱与背景稳定",
        "不要自动演抓取剧情",
    ],
    "C2_left_right_opposite": [
        "左/右臂运动方向明显相反",
        "其他物体基本不动",
        "两边都不要退化成同款抓取动画",
    ],
    "C3_grasp_vs_no_grasp": [
        "闭合抬升：圆柱应被带起",
        "张开抬升：圆柱应留在桌面",
        "不能两种都把圆柱带走",
    ],
    "C4_empty_grasp_offset": [
        "零件留在桌上",
        "夹爪空载抬起",
        "不要自动修正成成功抓取",
    ],
    "C5_place_pose_variants": [
        "A 进入第2排第3格且较竖直",
        "B 落在料箱外",
        "C 横放/碰撞/不稳，而不是完美竖直入格",
    ],
    "C6_recovery_after_failure": [
        "失败状态不要被瞬间洗白",
        "A 盲压与 B 回退重抓路径明显不同",
        "B 应出现后退-调整-再抓-放置结构",
    ],
}


def main() -> int:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    actions = build_actions()
    samples: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []

    for case in cfg["cases"]:
        case_id = case["case_id"]
        for variant in case["variants"]:
            vid = variant["variant_id"]
            if vid not in actions:
                raise KeyError(f"missing action builder for {vid}")
            action = actions[vid]
            sample_id = f"{case_id}__{vid}"
            sample = {
                "schema_version": "BakeoffSampleV0",
                "sample_id": sample_id,
                "initial_rgb_uri": SCENE["initial_rgb_uri"],
                "depth_uri": SCENE["depth_uri"],
                "language_task": PROMPTS[vid],
                "action_trajectory_uri": f"manifest://teacher-causal-suite/{sample_id}/action.json",
                "action_mapping_revision": cfg["action_mapping_revision"],
                "gazebo_future_uri": f"pending://teacher-causal-suite/{sample_id}/gazebo_future",
                "simulator_hard_label_uri": f"pending://teacher-causal-suite/{sample_id}/supervision",
                "scene_id": SCENE["scene_id"],
                "failure_type": {
                    "C1_static_hold": None,
                    "C2_left_right_opposite": None,
                    "C3_grasp_vs_no_grasp": None if "close" in vid else "no_grasp_counterfactual",
                    "C4_empty_grasp_offset": "empty_grasp",
                    "C5_place_pose_variants": None,
                    "C6_recovery_after_failure": "post_failure_recovery",
                }[case_id],
                "case_id": case_id,
                "variant_id": vid,
                "title": case["title"],
                "priority": case["priority"],
            }
            samples.append(sample)

            req = {
                "schema_version": "TeacherRequestV0",
                "request_id": sample_id,
                "candidate_model": "COMPARE_BWM_AND_COSMOS3_NANO",
                "checkpoint_revision": "local-compare",
                "prompt": PROMPTS[vid],
                "seed": 20260717,
                "action_domain": cfg["action_domain"],
                "action_mapping_revision": cfg["action_mapping_revision"],
                "generation_parameters": {
                    "num_frames_hint": action["num_frames"],
                    "fps_hint": FPS,
                    "human_review_only": True,
                    "shared_initial_frame": True,
                },
                "conditioning_scene": SCENE,
                "action_trajectory": action,
                "human_pass_criteria": case["pass_criteria"],
                "human_fail_modes": case["fail_modes"],
                "review_checklist_zh": REVIEW_EXPECT[case_id],
            }
            requests.append(req)

    OUT_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    OUT_MANIFEST.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in samples) + "\n", encoding="utf-8")
    OUT_REQUESTS.write_text(json.dumps({"suite_id": cfg["suite_id"], "scene": SCENE, "requests": requests}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Human review sheet
    lines = [
        "# Teacher causal suite — manual review",
        "",
        "用途：同一初始画面下，分别用 **BWM** 与 **Cosmos3-Nano** 跑下列请求，导出视频后人工对照。",
        "不要先看画质；优先看动作因果。",
        "",
        "## 共享场景",
        "",
        SCENE["description_zh"],
        "",
        f"- scene_id: `{SCENE['scene_id']}`",
        f"- initial_rgb_uri: `{SCENE['initial_rgb_uri']}`（请换成真实同一帧 PNG）",
        f"- action mapping: `{cfg['action_mapping_revision']}`（仅相对比较，非官方 Franka 映射）",
        "",
        "## 动作约定",
        "",
        "- 表示：世界坐标系 EE 增量 `[dx,dy,dz,droll,dpitch,dyaw,gripper]`",
        "- 单位：米 / 弧度 / gripper∈[0,1]（0=开，1=合）",
        f"- fps: {FPS}",
        "- 成对用例必须共用同一初始 RGB",
        "",
        f"生成文件：`{OUT_MANIFEST.relative_to(ROOT)}`，`{OUT_REQUESTS.relative_to(ROOT)}`",
        "",
        "## 审核表",
        "",
        "| case | variant | 你应看到 | BWM pass? | Nano pass? | 备注 |",
        "|---|---|---|---|---|---|",
    ]
    for req in requests:
        checklist = "；".join(req["review_checklist_zh"])
        lines.append(
            f"| {req['request_id'].split('__')[0]} | `{req['request_id'].split('__')[1]}` | {checklist} |  |  |  |"
        )

    lines += [
        "",
        "## 六项说明（喂模型时用）",
        "",
    ]
    for case in cfg["cases"]:
        lines.append(f"### {case['case_id']} — {case['title']}")
        lines.append("")
        lines.append(f"目的：{case['purpose']}")
        lines.append("")
        for variant in case["variants"]:
            vid = variant["variant_id"]
            act = actions[vid]
            lines.append(f"- **{vid}**")
            lines.append(f"  - prompt: {PROMPTS[vid]}")
            lines.append(f"  - action_summary: `{act['action_summary']}`")
            lines.append(f"  - frames: {act['num_frames']} ({act['duration_s']}s @ {FPS}fps)")
            # compact action sketch
            head = act["values"][0]
            mid = act["values"][len(act["values"]) // 2]
            tail = act["values"][-1]
            lines.append(f"  - action head/mid/tail: `{head}` / `{mid}` / `{tail}`")
        lines.append("")
        lines.append("人工通过标准：")
        for item in REVIEW_EXPECT[case["case_id"]]:
            lines.append(f"- [ ] {item}")
        lines.append("")

    lines += [
        "## 推荐审核顺序",
        "",
        "1. C1 静止（先验乱演直接淘汰感）",
        "2. C2 左右相反（可控性）",
        "3. C3 抓/不抓（最关键）",
        "4. C4 抓空（是否讨好式改写失败）",
        "5. C5 放置三变体",
        "6. C6 失败恢复对照",
        "",
        "## 输出命名建议",
        "",
        "```",
        "reports/teacher-compare/<model>/<case_id>__<variant_id>/pred.mp4",
        "reports/teacher-compare/<model>/<case_id>__<variant_id>/meta.json",
        "```",
        "",
        "meta.json 建议字段：model, revision, seed, latency_ms, peak_vram_mb, request_id。",
        "",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "OK",
                "samples": len(samples),
                "requests": len(requests),
                "manifest": str(OUT_MANIFEST.relative_to(ROOT)),
                "requests_json": str(OUT_REQUESTS.relative_to(ROOT)),
                "review_md": str(OUT_REVIEW.relative_to(ROOT)),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
