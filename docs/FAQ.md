# 常见问题速答（FAQ）

> 按症状找答案；找不到就到 GitHub Issues 提问（模板在 `.github/ISSUE_TEMPLATE/`）。

**Q1 技能装进 AI 后，AI 完全没反应，像没装一样？**
先跑 `python scripts/selftest.py` 确认技能本身完好；再确认你放对目录（WorkBuddy 是 `~/.workbuddy/skills/`，Codex 是 `~/.codex/skills/`）并重启了工具。网页版 AI 属 C 档降级：必须把系统提示词粘进对话才生效。

**Q2 AI 直接开始写东西，不按流程追问？**
在对话里明确说："用 vague-to-product 技能，先做形态判定和深度评分，按轮次问我问题。"C 档模式下提示词可能被长对话稀释，建议每 10 轮重发一次系统提示词。

**Q3 问了几轮之后 AI 忘了之前的回答？**
网页聊天上下文太长会截断。把上一轮结论复制进新对话开头再继续；有 A 档环境的建议直接用 WorkBuddy/Codex（档案会落盘，不存在遗忘）。

**Q4 我很急，能不能少问点？**
可以，说"少问点，直接做"即进入**快速模式**：追问压缩到最少两轮、其余用默认假设兜底，直接产出（精度略降，产出会标注"快速模式产物"）。详见 SKILL.md 5.1。

**Q5 产出做到一半停了，只给了我一份需求文档？**
v2.4.0 起铁律 19 已定死终点是产品。若宿主 AI 违反，回复一句："继续铁律 19：按 PRD 产出最终产品，再做合规收口。"持续违反说明宿主能力不足，换 A 档平台。

**Q6 它给的合规建议可信吗？会不会害我违规？**
所有红线/办证清单都是**经验总结，不构成法律意见**。每份报告强制附免责 7 条与"必须人工核实"提示；动手前向官方渠道复核（信息源清单见 fuzzy-reverse-flow 的 `references/regulation-watch.md`）。

**Q7 知识库（经验本）存在哪？会传到网上吗？**
本地 `~/.workbuddy/reverse-engine`（可用环境变量 RFE_KB 改），永不联网上传。删除该目录即清空全部经验。

**Q8 多个项目会互相串味吗？**
不会。`v2p use 项目A` 按项目隔离口味档案；经验写回有"待审区"机制，人工确认才转正。

**Q9 想把它包装成在线服务卖钱行不行？**
不行。明确禁止公开 SaaS 产品化、对外经营性 API、面向公众的付费服务；允许自用与内网使用（服务化只能绑定 127.0.0.1 环回）。详见 README 0.4。

**Q10 MCP 接入怎么配？**
本地 stdio 模式，零依赖、无网络监听：在支持 MCP 的客户端配置里加 `python <技能目录>/scripts/mcp_server.py` 为 stdio server，提供 v2p_route / v2p_gate_list / v2p_issue_codes / v2p_disclaimer 四个只读工具。配置示例见 `使用说明.txt` 第 8 节。

**Q11 命令一敲就说"不是内部或外部命令"？**
Python 没加进 PATH。重装 Python 并勾选 "Add Python to PATH"，或用完整路径 `C:\Python3x\python.exe scripts\v2p.py ...`。

**Q12 报告里那些 V2P-QG / RFE-DR 编码是什么意思？**
统一问题编码，方便跨工具对账。对照表见 `references/issue-codes.md`（如 RFE-DR-101 = 季度复核到期，RFE-DR-103 = 法规类规则超 90 天未核实）。
