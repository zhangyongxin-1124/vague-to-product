# PROVENANCE — vague-to-product 溯源声明

> 本文件逐项声明技能包内每个部分的来源，用于自证原创、支持合规再分发。
> 检测工具：`scripts/provenance_check.py`（与 fuzzy-reverse-flow 同源，8 项痕迹筛查）。

## 1. 版权

- 著作权人：张勇鑫（Zhang Yongxin）
- 许可证：MIT（见 LICENSE）
- 版本：v2.2.0（2026-11-03）

## 2. 代码来源

| 文件 | 来源 | 说明 |
|---|---|---|
| `scripts/v2p.py` | 原创原创 | 挖掘引擎（形态×维度×深度三层正交），v2.0.0 起逐步演进 |
| `scripts/qgate.py` | 原创 | 六道交付质量闸门 + 手测清单 + 静态扫描，v2.1.0 新增 |
| `scripts/orchestrate.py` | 原创 | v2.2.0 编排层：plan/settle/change/bundle/use/viz |
| `scripts/bridge.py` | 原创 | v2.2.0 单向桥接：v2p → rfe（subprocess 调用，JSON 解析） |
| `scripts/package.py` | 自有移植 | 从 fuzzy-reverse-flow v1.1.1 的 package.py 移植适配（同一著作权人） |
| `scripts/provenance_check.py` | 自有移植 | 从 fuzzy-reverse-flow v1.1.1 移植（同一著作权人） |
| `scripts/selftest.py` | 原创 | 72 项断言自测（v2.2.0 扩展） |
| `v2p.cmd` / `rfe.cmd` | 原创 | PATH 入口转发（纯 ASCII） |

## 3. 方法论与思想来源

| 思想 | 来源 | 表达 |
|---|---|---|
| 状态矩阵先于实现（动手前填 7 态） | 原创方法论 | `references/quality-gates.md` |
| 五信号深度分级（D0–D4） | 原创方法论 | `references/depth-governor.md` |
| 形态×维度×深度正交 | 原创方法论 | `references/output-forms.md` |
| 行为回溯提问法 | 通用访谈实践（UX interview 常识，无单一出处） | `references/question-bank.md` 全部题目为原创措辞 |
| 思想/表达二分法合规 | 中国著作权法通用原则 | 仅用于自查，不复制任何条文文本 |

未编译、未复制任何第三方开源项目的内容、代码、文档或清单。
第三方概念（如「MVP」「PRD」）为行业通用词汇，不构成表达复制。

## 4. 数据文件

| 文件 | 来源 |
|---|---|
| `assets/templates/*.md` | 原创（一页纸 PRD / 产出定型卡 / 交付质量核查卡 / MVP 功能分级表） |
| `assets/templates/taste-profile.json` | 原创（口味档案 schema） |
| `assets/templates/冷启动坑卡.json` | 原创；内容来自著作权人本人真实项目踩坑记录（某笔记小程序、某招聘小程序、通用工程实践，项目名已脱敏），无第三方数据 |

## 5. 引用的外部规范（仅名称引用，非文本复制）

- GB/T 9704（公文格式）——名称提及
- 微信小程序官方文档行为约束——按官方公开口径转述，未复制文档文本
- 《网络招聘服务管理规定》《个人信息保护法》等法规——规则库中仅以"规则语句 + 官方核实入口"形式表达

## 6. 复核

- 每季度用 `provenance_check.py` 全量复扫一次
- 引入任何第三方内容前，必须先确认许可证允许再分发，并在本文件登记
