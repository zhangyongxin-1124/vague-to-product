#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_docs.py — 发版文档一致性校验（零依赖，纯标准库）

用法：
    python _check_docs.py                          校验源码与两份文档
    python _check_docs.py --zip dist/<包名>.zip    连发布包内文档一起比对

用户规则：每次上传 / 发布新版本，README 与 使用说明 必须与代码完全一致；
本脚本是自动化保障，全部 PASS 才允许发版。发版顺序固定为：
  改代码 → 更新两份文档 → 跑校验 → 组装发布包 → 再跑带 --zip 的校验 →
  提交推送 → 上传 / 替换 Release 附件。

校验维度：版本号 / 功能清单 / 命令清单 / 默认参数 / 环境变量 / 路径格式 /
行为描述 / 章节编号与交叉引用 / 免责声明 / 禁止条款 / 统一问题编码 /
包内文档新鲜度（--zip）。
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -> {detail}" if not ok and detail else ""))


def read(rel: str) -> str:
    p = ROOT / rel
    if not p.is_file():
        return ""
    return io.open(p, encoding="utf-8-sig").read()


def norm(s: str) -> str:
    """统一换行，用于包内与仓库文档的逐字比对。"""
    return s.replace("\r\n", "\n").replace("\r", "\n")


def frontmatter_version(text: str) -> str:
    m = re.search(r"(?m)^version:\s*([^\s]+)", text)
    return m.group(1).strip() if m else ""


def expect(text: str, keywords: list[str], tag: str) -> None:
    for kw in keywords:
        check(f"{tag} 含「{kw}」", kw in text)


# ---------------------------------------------------------------- 事实源

SKILL = read("SKILL.md")
_name_m = re.search(r"(?m)^name:\s*([^\s]+)", SKILL)
NAME = _name_m.group(1).strip() if _name_m else ROOT.name
VERSION = frontmatter_version(SKILL)
PEER_VERSION = {"vague-to-product": "1.3.0", "fuzzy-reverse-flow": "2.3.0"}.get(NAME, "")
PEER_NAME = {"vague-to-product": "fuzzy-reverse-flow", "fuzzy-reverse-flow": "vague-to-product"}.get(NAME, "")

README = read("README.md")
TXT = read("使用说明.txt")
CHANGELOG = read("CHANGELOG.md")
PROVENANCE = read("PROVENANCE.md")
LICENSE = read("LICENSE")

# 两份文档都必须覆盖的关键词（与代码事实一一对应）
COMMON = [
    f"v{VERSION}", f"v{PEER_VERSION}",
    "能力档 A", "能力档 B", "能力档 C", "网页聊天", "手机", "降级",
    "12 项调用前自检清单",
    "完整免责声明",
    "内容性质", "时效风险", "强制人工核验", "不替代测试", "责任边界", "使用边界", "署名保留",
    "禁止封装为公开 SaaS", "公开 SaaS 产品化", "对外经营性 API", "127.0.0.1",
    "RFE_KB", "RFE_SCRIPT", "V2P_HOME", "V2P_PROJECT",
    "只读种子库", "可写本地库", "kb_seed", "~/.workbuddy/reverse-engine", "使用说明.txt",
    "rfe migrate --check", "rfe migrate", "rfe doctor", "rfe meta --set-review",
    "schema_version=2", "GitHub Release", "SHA256", "_check_docs.py --zip",
    "V2P-QG", "V2P-OR", "RFE-RL", "RFE-PT", "RFE-DR", "references/issue-codes.md",
    "RFE-DR-101", "RFE-DR-102", "91-180", "180 天",
    "张勇鑫", "P2-3", "本期不实施",
]


def main() -> int:
    ap = argparse.ArgumentParser(prog="_check_docs")
    ap.add_argument("--zip", dest="zip_path", default="", help="发布包路径，连包内文档一起比对")
    args = ap.parse_args()

    print(f"仓库：{NAME}  版本：{VERSION}  配套 {PEER_NAME} {PEER_VERSION}")
    print("\n[1] 版本与文件齐备")
    check("SKILL.md 有版本号", bool(VERSION), VERSION)
    check("README.md 存在", bool(README))
    check("使用说明.txt 存在（发版必检文档）", bool(TXT))
    check("CHANGELOG.md 存在", bool(CHANGELOG))
    check("PROVENANCE.md 存在", bool(PROVENANCE))
    check("LICENSE 存在", bool(LICENSE))
    m = re.search(r"## \[([^\]]+)\]", CHANGELOG)
    check("CHANGELOG 首个版本条目 == 当前版本", bool(m) and m.group(1) == VERSION,
          f"CHANGELOG 首个={m.group(1) if m else '无'} 期望={VERSION}")
    check("PROVENANCE 版本号 == 当前版本", f"版本：v{VERSION}" in PROVENANCE)
    check("LICENSE 含 MIT 与张勇鑫署名", "MIT License" in LICENSE and "张勇鑫" in LICENSE)
    check("README 显式声明当前版本", f"当前版本 **v{VERSION}**" in README)
    check("使用说明.txt 头部版本 == 当前版本", f"版本：v{VERSION}" in TXT)
    check("使用说明.txt 配套版本 == 配套仓库版本", f"v{PEER_VERSION}" in TXT)

    print("\n[2] 代码事实（默认参数 / 行为描述 / 功能清单）")
    if NAME == "fuzzy-reverse-flow":
        rfe = read("scripts/rfe.py")
        check("rfe.py 定义 SCHEMA_VERSION = 2", "SCHEMA_VERSION = 2" in rfe)
        check("rfe.py 注册 migrate 子命令", 'add_parser("migrate"' in rfe)
        check("rfe.py 声明只读种子库不写入", "只读种子库" in rfe and "永不写入" in rfe)
        check("rfe.py doctor 输出 RFE-DR 编码", "[RFE-DR-001]" in rfe and "[RFE-DR-102]" in rfe)
        check("rfe.py 默认知识库路径一致", "reverse-engine" in rfe)
    else:
        bridge = read("scripts/bridge.py")
        orch = read("scripts/orchestrate.py")
        v2p = read("scripts/v2p.py")
        check("bridge.py 定义 ISSUE_PREFIX", "ISSUE_PREFIX" in bridge)
        check("bridge.py 完整免责声明 7 条", len(re.findall(r'^\s+"\d\. ', bridge, re.M)) >= 7)
        check("bridge.py 含禁止公开 SaaS", "禁止封装为公开 SaaS" in bridge)
        check("orchestrate.py 实现 issue_code", "def issue_code" in orch)
        check("orchestrate.py 含 heatmap 分支", '"heatmap"' in orch and "信号热力图" in orch)
        check("orchestrate.py 报告带去重编码索引", "问题编码索引（去重）" in orch)
        check("orchestrate.py 报告带完整免责章节", "完整免责声明与使用边界" in orch)
        check("v2p.py viz choices 含 heatmap", '"heatmap"' in v2p)

    print("\n[3] 两份文档：功能清单 / 环境变量 / 路径 / 行为描述")
    expect(README, COMMON, "README")
    expect(TXT, COMMON, "使用说明.txt")

    print("\n[4] 章节编号与交叉引用")
    for i in range(1, 6):
        check(f"README 含 0.{i} 小节", f"### 0.{i}" in README)
    for a in "ABCD":
        check(f"README 含 附录 {a}", f"## 附录 {a}" in README)
    check("README 交叉引用 0.3 节", "0.3 节" in README)
    for a in "ABCD":
        check(f"README 交叉引用 附录 {a}", f"附录 {a}" in README)
    for i in range(0, 11):
        check(f"使用说明.txt 含【{i}】节", f"【{i}" in TXT)
    n_readme = len(re.findall(r"(?m)^\s*\d+\.\s*□", README))
    n_txt = len(re.findall(r"(?m)^\s*\d+\.\s*□", TXT))
    check("README 自检清单恰 12 项", n_readme == 12, f"实际 {n_readme}")
    check("使用说明.txt 自检清单恰 12 项", n_txt == 12, f"实际 {n_txt}")
    check("README 免责恰 7 条概念", all(k in README for k in
          ["内容性质", "时效风险", "强制人工核验", "不替代测试", "责任边界", "使用边界", "署名保留"]))
    check("使用说明.txt 免责恰 7 条概念", all(k in TXT for k in
          ["内容性质", "时效风险", "强制人工核验", "不替代测试", "责任边界", "使用边界", "署名保留"]))

    print("\n[5] 禁止条款与边界（硬约束）")
    for d, tag in ((README, "README"), (TXT, "使用说明.txt")):
        check(f"{tag} 明确禁止公开 SaaS 产品化", "公开 SaaS 产品化" in d and "禁止" in d)
        check(f"{tag} 明确仅内网环回 127.0.0.1", "127.0.0.1" in d)
        check(f"{tag} 声明 P2-3 本期不实施", "P2-3" in d and "本期不实施" in d)
        check(f"{tag} 声明规则非法律意见", "非法律意见" in d or "不构成法律" in d)

    if args.zip_path:
        print("\n[6] 发布包内文档新鲜度（--zip）")
        zp = Path(args.zip_path)
        check("发布包存在", zp.is_file(), str(zp))
        if zp.is_file():
            check("发布包文件名含当前版本", VERSION in zp.name, zp.name)
            try:
                with zipfile.ZipFile(zp) as z:
                    names = z.namelist()
                    prefix = f"{NAME}/"
                    for rel in ("README.md", "使用说明.txt", "SKILL.md", "CHANGELOG.md", "LICENSE"):
                        check(f"包内存在 {rel}", prefix + rel in names, prefix + rel)
                    for rel, local in (("README.md", README), ("使用说明.txt", TXT)):
                        key = prefix + rel
                        if key in names:
                            inner = z.read(key).decode("utf-8-sig")
                            check(f"包内 {rel} 与仓库逐字一致（非旧版）", norm(inner) == norm(local))
                    key = prefix + "SKILL.md"
                    if key in names:
                        check("包内 SKILL.md 版本 == 当前版本",
                              frontmatter_version(z.read(key).decode("utf-8-sig")) == VERSION)
                    key = prefix + "CHANGELOG.md"
                    if key in names:
                        check("包内 CHANGELOG 含当前版本条目",
                              f"[{VERSION}]" in z.read(key).decode("utf-8-sig"))
                    check("包内无 __pycache__ / .git / dist 残留",
                          not any(("__pycache__" in n or "/.git/" in n or n.startswith(prefix + "dist/"))
                                  for n in names))
            except zipfile.BadZipFile as e:
                check("发布包可正常解压", False, str(e))

    print(f"\n结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
        print("\n⛔ 校验未全通过，禁止发版。")
        return 1
    print("✅ 全部 PASS，允许发版。")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
