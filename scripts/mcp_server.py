#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mcp_server.py — vague-to-product 本地 MCP Server（stdio 传输，零依赖，v2.5.0）

设计边界（与 SKILL.md「使用边界」一致）：
  - 仅本地 stdio 运行（标准输入/输出逐行 JSON-RPC 2.0），**无网络监听、无云端 API**；
    允许自用与内网复用，禁止包装为公开 SaaS / 对外经营性 API。
  - 只读工具集：不提供 settle / profile 等写入命令，杜绝远端注入污染知识库。
  - 子进程调用 scripts/v2p.py，30 秒超时，输出截断 8000 字符。

暴露工具（MCP tools）：
  v2p_route       形态判定 + 深度评分 + 必挖点 + 第一轮问题
  v2p_gate_list   按形态 × 深度给出交付闸门清单
  v2p_issue_codes 统一问题编码对照表
  v2p_disclaimer  完整免责声明 7 条
  v2p_selfcheck   12 项调用前自检清单

客户端配置示例（任一支持 stdio MCP 的宿主）：
  command: python
  args:    ["<技能目录>/scripts/mcp_server.py"]

协议：逐行 JSON-RPC（每行一条，不含内嵌换行）；支持
  initialize / notifications/initialized / ping / tools/list / tools/call / shutdown。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SERVER_NAME = "vague-to-product"
SERVER_VERSION = "2.7.0"
PROTOCOL_VERSION = "2024-11-05"
MAX_OUT = 8000
TIMEOUT = 30

SKILL_ROOT = Path(__file__).resolve().parent.parent
V2P_CLI = SKILL_ROOT / "scripts" / "v2p.py"
BRIDGE = SKILL_ROOT / "scripts" / "bridge.py"
ISSUE_CODES_DOC = SKILL_ROOT / "references" / "issue-codes.md"
SELF_CHECK_DOC = SKILL_ROOT / "README.md"

# 只读白名单：除以下形态外，gate/其他写命令一律拒绝（防注入污染知识库）
ALLOWED_GATE_FORMS = {"app", "web", "mp", "doc", "sheet", "graphic", "3d", "av", "thing", "none"}


def _run_v2p(argv: list[str]) -> str:
    if not V2P_CLI.is_file():
        return f"[v2p-mcp] 找不到 {V2P_CLI}"
    try:
        r = subprocess.run([sys.executable, str(V2P_CLI), *argv],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT, cwd=str(SKILL_ROOT))
        out = (r.stdout or r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return f"[v2p-mcp] v2p.py 执行超时（>{TIMEOUT}s）"
    if len(out) > MAX_OUT:
        out = out[:MAX_OUT] + f"\n…（截断，原文 {len(out)} 字符）"
    return out or "[v2p-mcp] 无输出"


def _read_text(p: Path, limit: int = MAX_OUT) -> str:
    if not p.is_file():
        return f"[v2p-mcp] 文件缺失：{p}"
    t = p.read_text(encoding="utf-8-sig")
    return t if len(t) <= limit else t[:limit] + f"\n…（截断，原文 {len(t)} 字符）"


def tool_route(args: dict) -> str:
    idea = str(args.get("idea", "")).strip()
    if not idea:
        return "[v2p-mcp] 参数 idea 不能为空"
    return _run_v2p(["route", "-t", idea])


def tool_gate_list(args: dict) -> str:
    form = str(args.get("form", "app")).strip().lower()
    if form not in ALLOWED_GATE_FORMS:
        return f"[v2p-mcp] form 必须是 {sorted(ALLOWED_GATE_FORMS)} 之一"
    argv = ["gate", "list", "-f", form]
    depth = str(args.get("depth", "")).strip().upper()
    if depth:
        if depth not in {"D0", "D1", "D2", "D3", "D4"}:
            return "[v2p-mcp] depth 必须是 D0–D4"
        argv += ["-d", depth]
    return _run_v2p(argv)


def tool_issue_codes(_args: dict) -> str:
    return _read_text(ISSUE_CODES_DOC)


def tool_disclaimer(_args: dict) -> str:
    sys.path.insert(0, str(SKILL_ROOT / "scripts"))
    try:
        import bridge  # noqa: PLC0415
        lines = list(getattr(bridge, "DISCLAIMER_SECTIONS", []))
        if lines:
            return "\n".join(lines)
    except Exception as e:  # pragma: no cover
        return f"[v2p-mcp] 免责声明加载失败：{e}"
    return _read_text(BRIDGE)


def tool_selfcheck(_args: dict) -> str:
    readme = _read_text(SELF_CHECK_DOC, limit=100_000)
    # 只取「零、使用前提」的 12 项自检清单，避免整篇 README 灌入上下文
    start = readme.find("12 项调用前自检清单")
    if start == -1:
        start = readme.find("### 0.2")
    if start == -1:
        return "[v2p-mcp] 未找到自检清单，请直接阅读 README.md 0.2 节"
    seg = readme[start:start + 4000]
    end = seg.find("### 0.3")
    return seg[:end].strip() if end > 0 else seg.strip()


TOOLS = [
    {"name": "v2p_route", "description": "形态判定+深度评分+必挖点+第一轮问题（对应 v2p route）",
     "inputSchema": {"type": "object", "properties": {"idea": {"type": "string", "description": "用户的模糊想法原文"}},
                     "required": ["idea"]}},
    {"name": "v2p_gate_list", "description": "按形态×深度给出交付闸门清单（对应 v2p gate list，只读）",
     "inputSchema": {"type": "object", "properties": {
         "form": {"type": "string", "enum": sorted(ALLOWED_GATE_FORMS)},
         "depth": {"type": "string", "enum": ["D0", "D1", "D2", "D3", "D4"]}}}},
    {"name": "v2p_issue_codes", "description": "统一问题编码对照表（V2P-QG/V2P-OR/RFE-RL/RFE-PT/RFE-DR）",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "v2p_disclaimer", "description": "完整免责声明 7 条（每份交付必须附带）",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "v2p_selfcheck", "description": "12 项调用前自检清单（README 0.2 节）",
     "inputSchema": {"type": "object", "properties": {}}},
]

HANDLERS = {"v2p_route": tool_route, "v2p_gate_list": tool_gate_list,
            "v2p_issue_codes": tool_issue_codes, "v2p_disclaimer": tool_disclaimer,
            "v2p_selfcheck": tool_selfcheck}


def _reply(msg_id, result=None, error=None) -> None:
    body = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result
    sys.stdout.write(json.dumps(body, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle(msg: dict) -> None:
    method = msg.get("method", "")
    msg_id = msg.get("id")
    if method == "initialize":
        _reply(msg_id, {"protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}})
    elif method == "notifications/initialized":
        pass  # 通知无需应答
    elif method == "ping":
        _reply(msg_id, {})
    elif method == "tools/list":
        _reply(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = str(params.get("name", ""))
        handler = HANDLERS.get(name)
        if handler is None:
            _reply(msg_id, None, {"code": -32602, "message": f"未知工具：{name}"})
            return
        try:
            text = handler(params.get("arguments") or {})
            _reply(msg_id, {"content": [{"type": "text", "text": text}]})
        except Exception as e:  # pragma: no cover
            _reply(msg_id, None, {"code": -32603, "message": f"工具执行失败：{e}"})
    elif method == "shutdown":
        _reply(msg_id, {})
        raise SystemExit(0)
    elif msg_id is not None:
        _reply(msg_id, None, {"code": -32601, "message": f"未知方法：{method}"})


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _reply(None, None, {"code": -32700, "message": "JSON 解析失败"})
            continue
        try:
            _handle(msg)
        except SystemExit:
            return 0
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
