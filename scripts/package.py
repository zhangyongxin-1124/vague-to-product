#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""package.py — vague-to-product 可分发技能包（零依赖，v2.2.0 从 fuzzy-reverse-flow 移植）

用法：
    python scripts/package.py            # 溯源检测 → 打包到 dist/<name>-v<version>.zip
    python scripts/package.py --list     # 只列会打包哪些文件
    python scripts/package.py --no-check # 跳过溯源检测（不建议）

强制排除：__pycache__ / dist / .git / 本地知识库与私人档案
可复现：zip 内时间戳固定为 1980-01-01，同一份源码两次打包 SHA256 一致。
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS.parent

EXCLUDE_DIRS = {"__pycache__", ".git", "dist", "node_modules", ".vscode", ".idea",
                "kb_local", "examples"}
EXCLUDE_GLOBS = (".kb", ".kb*", "*.pyc", "*.pyo", "*.tmp", ".DS_Store", "Thumbs.db")

REQUIRED = ["SKILL.md", "README.md", "LICENSE", "CHANGELOG.md", "PROVENANCE.md",
            "scripts/v2p.py", "scripts/qgate.py", "scripts/orchestrate.py",
            "scripts/bridge.py", "scripts/selftest.py"]

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


def iter_files():
    for p in sorted(SKILL_ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(SKILL_ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if any(p.match(g) for g in EXCLUDE_GLOBS):
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

    out = pack(SKILL_ROOT / "dist", name, version)
    log(f"已生成：{out}")
    log(f"SHA256：{sha256(out)}")
    log("可复现构建：再次打包 SHA256 应一致；分发前建议解压实测 + 跑 selftest。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
