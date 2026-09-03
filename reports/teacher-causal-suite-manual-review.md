# Teacher causal suite — manual review

用途：同一初始画面下，分别用 **BWM** 与 **Cosmos3-Nano** 跑下列请求，导出视频后人工对照。
不要先看画质；优先看动作因果。

## 共享场景

工业桌面俯视/斜视固定相机。桌上有一根竖直立着的金属圆柱零件，右侧有分格料箱（可见第2排第3格），背景墙面与桌面纹理保持固定。画面中有一只 Franka Panda 机械臂与平行夹爪，初始夹爪张开，位于零件上方附近。

- scene_id: `industrial-table-cylinder-bin-v0`
- initial_rgb_uri: `pending://shared/industrial-table-cylinder-bin-v0/rgb.png`（请换成真实同一帧 PNG）
- action mapping: `EVAL_EE_DELTA_WORLD_M_GRIPPER_V0`（仅相对比较，非官方 Franka 映射）

## 动作约定

- 表示：世界坐标系 EE 增量 `[dx,dy,dz,droll,dpitch,dyaw,gripper]`
- 单位：米 / 弧度 / gripper∈[0,1]（0=开，1=合）
- fps: 10.0
- 成对用例必须共用同一初始 RGB

生成文件：`data/manifests/teacher-causal-suite.jsonl`，`data/manifests/teacher-causal-suite-requests.json`

## 审核表

| case | variant | 你应看到 | BWM pass? | Nano pass? | 备注 |
|---|---|---|---|---|---|
| C1_static_hold | `hold_open` | 臂几乎不动；零件不漂移/瞬移；料箱与背景稳定；不要自动演抓取剧情 |  |  |  |
| C2_left_right_opposite | `move_left_10cm` | 左/右臂运动方向明显相反；其他物体基本不动；两边都不要退化成同款抓取动画 |  |  |  |
| C2_left_right_opposite | `move_right_10cm` | 左/右臂运动方向明显相反；其他物体基本不动；两边都不要退化成同款抓取动画 |  |  |  |
| C3_grasp_vs_no_grasp | `approach_close_lift` | 闭合抬升：圆柱应被带起；张开抬升：圆柱应留在桌面；不能两种都把圆柱带走 |  |  |  |
| C3_grasp_vs_no_grasp | `approach_open_lift` | 闭合抬升：圆柱应被带起；张开抬升：圆柱应留在桌面；不能两种都把圆柱带走 |  |  |  |
| C4_empty_grasp_offset | `offset_close_lift` | 零件留在桌上；夹爪空载抬起；不要自动修正成成功抓取 |  |  |  |
| C5_place_pose_variants | `place_bin_r2c3_upright` | A 进入第2排第3格且较竖直；B 落在料箱外；C 横放/碰撞/不稳，而不是完美竖直入格 |  |  |  |
| C5_place_pose_variants | `place_outside_bin_release` | A 进入第2排第3格且较竖直；B 落在料箱外；C 横放/碰撞/不稳，而不是完美竖直入格 |  |  |  |
| C5_place_pose_variants | `place_above_bin_sideways_release` | A 进入第2排第3格且较竖直；B 落在料箱外；C 横放/碰撞/不稳，而不是完美竖直入格 |  |  |  |
| C6_recovery_after_failure | `press_down_again` | 失败状态不要被瞬间洗白；A 盲压与 B 回退重抓路径明显不同；B 应出现后退-调整-再抓-放置结构 |  |  |  |
| C6_recovery_after_failure | `backoff_regrasp_place` | 失败状态不要被瞬间洗白；A 盲压与 B 回退重抓路径明显不同；B 应出现后退-调整-再抓-放置结构 |  |  |  |

## 六项说明（喂模型时用）

### C1_static_hold — 静止对照

目的：detect free-running video prior when action is null

- **hold_open**
  - prompt: Predict the future video if the robot holds still with gripper open.
  - action_summary: `hold_pose_open_gripper`
  - frames: 24 (2.4s @ 10.0fps)
  - action head/mid/tail: `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]`

人工通过标准：
- [ ] 臂几乎不动
- [ ] 零件不漂移/瞬移
- [ ] 料箱与背景稳定
- [ ] 不要自动演抓取剧情

### C2_left_right_opposite — 同一画面左右相反动作

目的：opposite EE lateral deltas must reverse arm motion

- **move_left_10cm**
  - prompt: Predict the future video if the end-effector moves 10 cm left; gripper stays open; no grasp.
  - action_summary: `ee_delta_y_-0.10_open`
  - frames: 24 (2.4s @ 10.0fps)
  - action head/mid/tail: `[0.0, -0.004166666666666667, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[0.0, -0.004166666666666667, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[0.0, -0.004166666666666667, 0.0, 0.0, 0.0, 0.0, 0.0]`
- **move_right_10cm**
  - prompt: Predict the future video if the end-effector moves 10 cm right; gripper stays open; no grasp.
  - action_summary: `ee_delta_y_+0.10_open`
  - frames: 24 (2.4s @ 10.0fps)
  - action head/mid/tail: `[0.0, 0.004166666666666667, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.004166666666666667, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.004166666666666667, 0.0, 0.0, 0.0, 0.0, 0.0]`

人工通过标准：
- [ ] 左/右臂运动方向明显相反
- [ ] 其他物体基本不动
- [ ] 两边都不要退化成同款抓取动画

### C3_grasp_vs_no_grasp — 抓取与不抓取反事实

目的：gripper close must be causal for object lift

- **approach_close_lift**
  - prompt: Predict the future video: approach cylinder, close gripper, lift. Object should rise only if grasped.
  - action_summary: `approach_close_lift`
  - frames: 40 (4.0s @ 10.0fps)
  - action head/mid/tail: `[0.0, 0.0, -0.005, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]` / `[0.0, 0.0, 0.0075, 0.0, 0.0, 0.0, 1.0]`
- **approach_open_lift**
  - prompt: Predict the future video: same approach and lift path, but gripper remains open (no grasp).
  - action_summary: `approach_open_lift`
  - frames: 40 (4.0s @ 10.0fps)
  - action head/mid/tail: `[0.0, 0.0, -0.005, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.0, 0.0075, 0.0, 0.0, 0.0, 0.0]`

人工通过标准：
- [ ] 闭合抬升：圆柱应被带起
- [ ] 张开抬升：圆柱应留在桌面
- [ ] 不能两种都把圆柱带走

### C4_empty_grasp_offset — 抓空测试

目的：offset miss must remain a failure, not auto-corrected success

- **offset_close_lift**
  - prompt: Predict the future video: approach 4 cm beside the cylinder, close gripper, lift (empty grasp).
  - action_summary: `approach_offset_0.04_close_lift`
  - frames: 40 (4.0s @ 10.0fps)
  - action head/mid/tail: `[0.0, 0.0025, -0.005, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]` / `[0.0, 0.0, 0.0075, 0.0, 0.0, 0.0, 1.0]`

人工通过标准：
- [ ] 零件留在桌上
- [ ] 夹爪空载抬起
- [ ] 不要自动修正成成功抓取

### C5_place_pose_variants — 放置位置与姿态测试

目的：place cell/outside/sideways must not all become perfect upright bin insert

- **place_bin_r2c3_upright**
  - prompt: Predict the future video: place grasped upright cylinder into bin row2 col3, then release.
  - action_summary: `place_bin_r2c3_upright_release`
  - frames: 40 (4.0s @ 10.0fps)
  - action head/mid/tail: `[0.006, -0.0025, 0.001, 0.0, 0.0, 0.0, 1.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.0, 0.005, 0.0, 0.0, 0.0, 0.0]`
- **place_outside_bin_release**
  - prompt: Predict the future video: move grasped cylinder outside the bin and release.
  - action_summary: `place_outside_release`
  - frames: 40 (4.0s @ 10.0fps)
  - action head/mid/tail: `[0.009, 0.006, 0.0, 0.0, 0.0, 0.0, 1.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.0, 0.005, 0.0, 0.0, 0.0, 0.0]`
- **place_above_bin_sideways_release**
  - prompt: Predict the future video: hold cylinder sideways above bin, then release.
  - action_summary: `place_above_sideways_release`
  - frames: 40 (4.0s @ 10.0fps)
  - action head/mid/tail: `[0.006, -0.0025, 0.002, 0.0, 0.0, 0.0785, 1.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.0, 0.005, 0.0, 0.0, 0.0, 0.0]`

人工通过标准：
- [ ] A 进入第2排第3格且较竖直
- [ ] B 落在料箱外
- [ ] C 横放/碰撞/不稳，而不是完美竖直入格

### C6_recovery_after_failure — 失败后的恢复动作

目的：recovery policy must differ from blind re-press after failure states

- **press_down_again**
  - prompt: From a failed placement state, predict future if the robot only presses down again.
  - action_summary: `recovery_press_down`
  - frames: 24 (2.4s @ 10.0fps)
  - action head/mid/tail: `[0.0, 0.0, -0.00375, 0.0, 0.0, 0.0, 1.0]` / `[0.0, 0.0, -0.00375, 0.0, 0.0, 0.0, 1.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]`
- **backoff_regrasp_place**
  - prompt: From the same failed state, predict future if robot backs off, regrasps, then places normally.
  - action_summary: `recovery_backoff_regrasp_place`
  - frames: 80 (8.0s @ 10.0fps)
  - action head/mid/tail: `[0.0, 0.0, 0.006666666666666667, 0.0, 0.0, 0.0, 0.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]` / `[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]`

人工通过标准：
- [ ] 失败状态不要被瞬间洗白
- [ ] A 盲压与 B 回退重抓路径明显不同
- [ ] B 应出现后退-调整-再抓-放置结构

## 推荐审核顺序

1. C1 静止（先验乱演直接淘汰感）
2. C2 左右相反（可控性）
3. C3 抓/不抓（最关键）
4. C4 抓空（是否讨好式改写失败）
5. C5 放置三变体
6. C6 失败恢复对照

## 输出命名建议

```
reports/teacher-compare/<model>/<case_id>__<variant_id>/pred.mp4
reports/teacher-compare/<model>/<case_id>__<variant_id>/meta.json
```

meta.json 建议字段：model, revision, seed, latency_ms, peak_vram_mb, request_id。
