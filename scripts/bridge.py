#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bridge.py — v2p → rfe 单向桥接层（零依赖，仅 Python 标准库）

职责边界（v2.2.0 编排契约）：
  - v2p 是主人，按需调用 rfe 的能力拿结果，再整合输出一份报告
  - rfe 不反向调用 v2p（单向依赖，避免双向耦合）
  - 用户只敲 v2p 命令，感知不到 rfe 的存在

定位 rfe.py 的顺序：
  1. 环境变量 RFE_SCRIPT
  2. 源码目录：../../fuzzy-reverse-flow/scripts/rfe.py
  3. 安装目录：~/.workbuddy/skills/fuzzy-reverse-flow/scripts/rfe.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_RFE_CACHE: Path | None = None


def find_rfe() -> Path | None:
    global _RFE_CACHE
    if _RFE_CACHE is not None:
        return _RFE_CACHE
    env = os.environ.get("RFE_SCRIPT", "").strip()
    cands = []
    if env:
        cands.append(Path(env))
    here = Path(__file__).resolve().parent
    cands.append(here.parent.parent / "fuzzy-reverse-flow" / "scripts" / "rfe.py")
    cands.append(Path.home() / ".workbuddy" / "skills" / "fuzzy-reverse-flow" / "scripts" / "rfe.py")
    for c in cands:
        if c.is_file():
            _RFE_CACHE = c
            return c
    return None


def rfe_run(argv: list) -> subprocess.CompletedProcess:
    rfe = find_rfe()
    if rfe is None:
        raise FileNotFoundError(
            "找不到 rfe.py（已尝试 RFE_SCRIPT 环境变量、同级 fuzzy-reverse-flow 目录、"
            "~/.workbuddy/skills 安装目录）。合规排雷与坑库能力需要 fuzzy-reverse-flow。")
    return subprocess.run(
        [sys.executable, str(rfe)] + argv,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)


def _loads_json(proc: subprocess.CompletedProcess):
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def recall(query: str, top: int = 8, severity: str = "") -> list:
    """召回领域规则。返回 [{rule:{...}, score:...}]，rfe 不可用或为空时返回 []。"""
    argv = ["recall", "--query", query, "--top", str(top), "--json"]
    if severity:
        argv += ["--severity", severity]
    try:
        data = _loads_json(rfe_run(argv))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    return data or []


def infer_domain(query: str) -> list:
    """猜领域。返回 rfe infer --json 的原始输出（结构由 rfe 决定）。"""
    try:
        data = _loads_json(rfe_run(["infer", "--text", query, "--json"]))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    return data if isinstance(data, list) else ([data] if data else [])


def pitfall_recall(query: str, top: int = 5) -> list:
    """召回历史坑。返回 [{pitfall:{...}, score:...}]。"""
    try:
        data = _loads_json(rfe_run(["pitfall", "recall", "--query", query,
                                    "--top", str(top), "--json"]))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    return data or []


def redlines(query: str, top: int = 10) -> list:
    """只取 redline 级规则（合规闸门的数据源）。"""
    rows = recall(query, top=top, severity="redline")
    return [r["rule"] for r in rows if isinstance(r, dict) and r.get("rule")]


def kb_review_stamp() -> str:
    """知识库复核时间戳（免责输出用）。rfe 不可用返回占位。"""
    try:
        proc = rfe_run(["meta"])
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "rfe 不可用，无法读取复核时间戳"
    line = ""
    for ln in (proc.stdout or "").splitlines():
        if "复核时间戳" in ln:
            line = ln.strip()
            break
    return line or "复核时间戳：未知"


def write_pending(kind: str, payload: dict) -> tuple:
    """把沉淀内容写入 rfe 待审区。kind: rule | pitfall。
    返回 (ok, 消息)。"""
    argv = (["add", "--pending"] if kind == "rule"
            else ["pitfall", "add", "--pending"])
    import tempfile
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            tmp = f.name
        proc = rfe_run(argv + ["--file", tmp])
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode == 0, out
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        return False, f"写入待审区失败：{e}"
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


DISCLAIMER = (
    "免责提示：本报告中的规则与检查项为经验性总结，不构成法律、合规或投资意见；"
    "政策与平台规则会变动，重要决策请咨询专业机构并以官方口径为准；"
    "自动化检查只是必要条件，不能替代人工测试与人工核验；"
    "本工具仅授权自用与内网复用，禁止封装为公开 SaaS 或对外经营性 API。"
)

# 完整免责声明（逐条），每份报告尾部强制附带；与 README / 使用说明.txt 保持一致
DISCLAIMER_SECTIONS = [
    "1. 内容性质：全部规则、红线、坑卡与检查项为作者及贡献者的经验性总结，非法律意见、非监管口径、非投资建议。",
    "2. 时效风险：法律法规、平台审核规则、资质要求会变动；报告所附「知识库复核时间戳」只表示上次人工复核日期，不保证当下仍有效。",
    "3. 强制人工核验：任何「通过 / 阻断」结论都是自动化的必要条件判断，上线、签约、投放、发布前必须由具备资质的人员向官方渠道逐条核实。",
    "4. 不替代测试：静态扫描与手测清单不能替代真实环境测试、灰度验证与人工验收；交付必须保留人工核验环节。",
    "5. 责任边界：使用者对基于本报告作出的决策独立承担责任；作者不对任何直接或间接损失负责。",
    "6. 使用边界：本项目仅授权自用与内网团队复用；禁止封装为公开 SaaS、对外经营性 API 或任何面向不特定公众的付费服务。",
    "7. 署名保留：依据 MIT License，转载、修改与再分发必须保留「Copyright (c) 2026 张勇鑫 (Zhang Yongxin)」及许可声明。",
]

# 统一问题编码前缀：两套工具所有告警全局唯一，避免同码不同义与重复告警
ISSUE_PREFIX = {
    "qgate": "V2P-QG",        # 交付质量闸门检查项（原 QG-xxx）
    "orchestrate": "V2P-OR",  # 编排层冲突 / 状态告警
    "rule": "RFE-RL",         # 规则库红线 / 阻断规则
    "pitfall": "RFE-PT",      # 踩坑记忆
    "doctor": "RFE-DR",       # 知识库自检诊断
}
