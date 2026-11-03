# 三步装好卡（小白版图文指引）

> 目标：完全不懂命令行的人，跟着做 10 分钟内装好。装完请翻 `docs/FAQ.md`。

## 第 0 步 · 准备（一次性，约 5 分钟）

1. 电脑上装好 Python（去 python.org 下载，安装时勾选 "Add Python to PATH"）。
2. 下载技能包：打开本项目的 GitHub Releases 页，下载最新版 ZIP，解压到一个你记得住的文件夹（例如 `F:\Workbuddy数据储存库\vague-to-product`）。
3. 验证：打开命令行（Windows 按 Win+R，输入 `cmd` 回车），输入 `python --version`，能显示版本号即 OK。

## 第 1 步 · 装进你的 AI 工具

按你用的工具挑一个（三个都装也行，互不影响）：

### WorkBuddy
1. 把整个 `vague-to-product` 文件夹复制到 `C:\Users\你的用户名\.workbuddy\skills\` 下；
2. 重启 WorkBuddy，新对话里说"用 vague-to-product，我想做个 XX"。

### Codex CLI
1. 复制到 `C:\Users\你的用户名\.codex\skills\vague-to-product\`；
2. 复制 `prompts/` 里的提示词文件到 `C:\Users\你的用户名\.codex\prompts\`（如仓库含 prompts/）；
3. 命令行输入 `codex`，对话里说"用 v2p 技能：我想做个 XX"。

### DeepSeek / 其他网页版 AI
1. 打开 `使用说明.txt`，复制"系统提示词"一节全文；
2. 粘贴到对话第一条消息，再发你的需求（此为 C 档降级模式，能力有折扣，详见 README 0.1 节）。

## 第 2 步 · 验证装好了

在新对话里输入一句话：**"我想做一个帮老人找零工的 App"**。
装成功的标志：AI 先回答形态判定和深度评分、**先给带选项的问题**（而不是直接开写或空泛反问）。

## 装不上怎么办

- 三分钟自查：`python scripts/selftest.py`（在技能文件夹里运行），全部"通过"说明技能本身没问题，问题出在 AI 工具接入方式；
- 再不行去 `docs/FAQ.md` 找同款症状；
- 还不行，到 GitHub Issues 提一条（模板已备好，照着填即可）。
