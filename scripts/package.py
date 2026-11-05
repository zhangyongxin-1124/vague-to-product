#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""package.py — vague-to-product 可分发技能包（零依赖，v2.2.0 从 fuzzy-reverse-flow 移植）

用法：
    python scripts/package.py            # 溯源检测 → 打包到 dist/<name>-v<version>.zip
    python scripts/package.py --list     # 只列会打包哪些文件
    python scripts/package.py --no-check # 跳过溯源检测（不建议）

强制排除：__pycache__ / dist / .git / 本地知识库与私人档案（examples/ 案例库自 v2.5.0 起随包分发）
可复现：zip 内时间戳固定为 1980-01-01，同一份源码两次打包 SHA256 一致。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS.parent

EXCLUDE_DIRS = {"__pycache__", ".git", ".github", "dist", "node_modules", ".vscode", ".idea",
                "kb_local"}
EXCLUDE_GLOBS = (".kb", ".kb*", "*.pyc", "*.pyo", "*.tmp", ".DS_Store", "Thumbs.db",
                 "*.bak", "*.bak-*")

# WorkBuddy 开放平台（技能市场上架）要求的 SKILL.md frontmatter 必填字段
MARKET_REQUIRED = ["name", "display_name", "display_name_en", "description",
                   "description_zh", "description_en", "version", "author"]

# 技能根目录允许出现的散文件（其余散落产物一律不打包）
ROOT_ALLOW = {"SKILL.md", "README.md", "README_EN.md", "使用说明.txt",
              "LICENSE", "CHANGELOG.md", "PROVENANCE.md", "_check_docs.py"}

REQUIRED = ["SKILL.md", "README.md", "README_EN.md", "使用说明.txt", "LICENSE", "CHANGELOG.md",
            "PROVENANCE.md", "_check_docs.py", "references/issue-codes.md",
            "scripts/v2p.py", "scripts/qgate.py", "scripts/orchestrate.py",
            "scripts/bridge.py", "scripts/selftest.py", "scripts/mcp_server.py",
            "scripts/gate_verify.py", "scripts/release.py",
            "references/quick-mode.md", "references/output-templates.md",
            "docs/quick-start.md", "docs/FAQ.md", "docs/安装演示脚本-3分钟.md",
            "docs/冷启动行动清单.md",
            "templates/交付自查清单.md", "examples/README.md",
            "examples/01-闹钟App-从一句话到PRD与终局交付.md",
            "examples/02-娱乐小程序-逆向施工图摘要.md",
            "examples/03-实体店-社区奶茶店可行性推演.md",
            "examples/04-文档类-商业计划书十页成稿.md",
            "examples/05-表格类-小卖部进销存台账.md",
            "examples/06-两次失败复盘-从一堆md到PC网页到三道关卡.md"]

FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_frontmatter(text: str) -> dict:
    meta = {}
    if not text.startswith("---"):
        return meta
    for line in text.split("\n")[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


def structure_check() -> int:
    bad = 0
    for rel in REQUIRED:
        p = SKILL_ROOT / rel
        if not p.is_file():
            log(f"  [缺失] {rel}")
            bad += 1
    for py in sorted((SKILL_ROOT / "scripts").glob("*.py")):
        r = subprocess.run([sys.executable, "-m", "py_compile", str(py)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            log(f"  [编译失败] {py.name}:\n{r.stderr.strip()[:400]}")
            bad += 1
    meta = parse_frontmatter((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
    if not meta.get("version"):
        log("  [缺失] SKILL.md 无 version")
        bad += 1
    log(f"结构检查：{'通过' if not bad else f'{bad} 项问题'}（版本 {meta.get('version', '?')}）")
    return bad


def market_check() -> int:
    """上架 WorkBuddy 技能市场所需的 frontmatter 字段检查。"""
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    meta = parse_frontmatter(text)
    bad = 0
    for f in MARKET_REQUIRED:
        if not meta.get(f):
            log(f"  [市场必填缺失] {f}")
            bad += 1
    desc = meta.get("description", "")
    if desc and len(desc) > 1200:
        log(f"  [警告] description 长度 {len(desc)}，市场展示可能被截断")
    # 平台用严格 YAML 解析：值内含 ': ' 的裸标量会解析失败，须加引号。
    # yaml 为可选增强（缺失则降级跳过），动态导入以保持"零依赖"承诺。
    try:
        yaml = __import__("yaml")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
        if not m:
            log("  [YAML] frontmatter 缺失")
            bad += 1
        else:
            try:
                data = yaml.safe_load(m.group(1))
                if not isinstance(data, dict):
                    log("  [YAML] frontmatter 未解析为键值映射")
                    bad += 1
            except yaml.YAMLError as e:
                log(f"  [YAML] 严格解析失败: {str(e)[:160]}")
                bad += 1
    except ImportError:
        log("  [提示] 未安装 PyYAML，跳过严格 YAML 校验（pip install pyyaml 后更稳）")
    log(f"市场字段检查：{'通过' if not bad else f'{bad} 项问题'}")
    return bad


def verify_zip(zip_path: Path, name: str) -> int:
    """回读校验：顶层目录唯一 + 中文文件名按 UTF-8 存储。"""
    bad = 0
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        tops = {n.split("/")[0] for n in names}
        if tops != {name}:
            log(f"  [顶层目录异常] 期望 {name}，实际 {tops}")
            bad += 1
        if f"{name}/SKILL.md" not in names:
            log("  [缺少] SKILL.md 不在包根目录")
            bad += 1
        for i in infos:
            has_zh = any(ord(c) > 127 for c in i.filename)
            if not has_zh:
                continue
            if not (i.flag_bits & 0x800):
                log(f"  [编码] 中文名缺少 UTF-8 标志位：{i.filename}")
                bad += 1
            elif all(ord(c) < 256 for c in i.filename):
                log(f"  [编码] 疑似乱码：{i.filename}")
                bad += 1
        zh = sum(1 for n in names if any("\u4e00" <= c <= "\u9fff" for c in n))
        log(f"回读校验：{len(infos)} 条目，其中含中文名的 {zh} 个"
            f" — {'通过' if not bad else f'{bad} 项问题'}")
    return bad


def iter_files():
    for p in sorted(SKILL_ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(SKILL_ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if any(p.match(g) for g in EXCLUDE_GLOBS):
            continue
        # 根目录只允许白名单内的散文件：v2p spec new 等命令默认写到 cwd，
        # 若在技能根目录被触发会留下 -PRD.md / -定型卡.md，不能进发布包。
        if len(rel.parts) == 1 and rel.name not in ROOT_ALLOW:
            log(f"  [跳过根目录散文件] {rel.name}")
            continue
        yield p, rel


def pack(dist: Path, name: str, version: str) -> Path:
    dist.mkdir(exist_ok=True)
    out = dist / f"{name}-v{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p, rel in iter_files():
            zi = zipfile.ZipInfo(f"{name}/" + str(rel).replace("\\", "/"),
                                 date_time=FIXED_DATE)
            zi.external_attr = 0o644 << 16
            z.writestr(zi, p.read_bytes())
    return out


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(prog="package")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--no-check", action="store_true")
    args = ap.parse_args()

    meta = parse_frontmatter((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
    name = meta.get("name", "").strip() or SKILL_ROOT.name
    version = meta.get("version", "0.0.0")

    if args.list:
        n = 0
        for p, rel in iter_files():
            print(f"  {rel}")
            n += 1
        log(f"共 {n} 个文件")
        return 0

    log(f"打包 {name} v{version}")
    if not args.no_check:
        log("— 溯源检测 —")
        r = subprocess.run([sys.executable, str(SCRIPTS / "provenance_check.py")])
        if r.returncode != 0:
            log("溯源检测未通过，停止打包（可用 --no-check 跳过，不建议）。")
            return 1
        log("— 结构检查 —")
        if structure_check():
            return 1
        log("— 市场字段检查 —")
        if market_check():
            return 1

    out = pack(SKILL_ROOT / "dist", name, version)
    log(f"已生成：{out}")
    log(f"SHA256：{sha256(out)}")
    log("— 回读校验 —")
    if verify_zip(out, name):
        log("回读校验未通过：包内编码或目录结构有问题，请勿上传。")
        return 1
    log("可复现构建：再次打包 SHA256 应一致；分发前建议解压实测 + 跑 selftest。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
