# Rex-Omni vs LocateAnything-VP 同 held-out 公平对照:不可行说明 v1

- 日期:2026-09-02 11:2x
- 结论人:tzb-fe(协调会话),依据 two-shot-canonical-gate 30 分钟只读可行性核查
- 触发:用户 11:0x 指出 chxy 空闲;job 登记 `locateanything-visual-prompt-lora-v1.json` §"the_benchmark_gap_that_must_not_be_papered_over" 要求在同一 held-out 上跑 Rex-Omni 做公平对照

## 结论

**不可构造,闭合为接口/任务不相容。** 未启 GPU,未做适配器。

## 依据

Rex-Omni 的 visual prompting 接口只接受**单张输入图 + 该图内的框**:

- 官方教程 `tutorials/visual_prompting_example/visual_prompt_example.py`:`images=image` + `visual_prompt_boxes=visual_prompts`,一个 inference item 只有一张图
- `rex_omni/wrapper.py`:batch 只是 `images[i]` 与同 item 的 boxes 配对,boxes 按该图宽高归一;无 reference/source image + target image 双图入口
- 项目页 https://rex-omni.github.io/ 定义为 "bounding boxes in the input image"

来源:
- https://github.com/IDEA-Research/Rex-Omni/blob/master/tutorials/visual_prompting_example/visual_prompt_example.py
- https://github.com/IDEA-Research/Rex-Omni/blob/master/rex_omni/wrapper.py
- https://rex-omni.github.io/

我们的 held-out 任务是**跨图类别级** visual prompt:参考裁剪来自图 A,在图 B 中找同类别全部实例(`sample_encoding.human_template`:`<image-1>\nDetect all the objects … category set: <image-2>`)。Rex-Omni 的接口没有这个任务形态。

## 交付口径

- deck 与材料中 LocateAnything-VP **只与自身 baseline 对照**(0/2000 → 739/2000),**不提 Rex-Omni**——与 job 登记 §benchmark_gap 的"Without that, the only honest statement is about our own before/after, with no Rex-Omni comparison at all" 一致,与用户既有字面禁令(无同 benchmark 结果不得提该模型)一致。
- 若被问"为什么不和 Rex-Omni 比":答"Rex-Omni 的 visual prompt 接口是同图内框提示,不支持跨图类别级任务,同条件对照不可构造"。
- 不做的:改 Rex 的接口、拼接双图、把 A 的裁剪贴进 B——任何一种都不是"同条件",都会被外审问倒。

## 未触碰

`/home/fx/rex-omni-pointing-v1/` 未被 two-shot-canonical-gate 触碰;chxy GPU 未启用;无新工件除本文件。
