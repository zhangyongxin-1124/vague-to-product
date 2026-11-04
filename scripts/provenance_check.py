#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""provenance_check.py — 开源发布前的原创性自查（零依赖，Python 3.8+）

用途：在把本技能包推到公开仓库前，机器化确认"没有夹带第三方代码或文本"。
不是为了证明清白，而是为了让清白可被反复验证。

用法：
    python scripts/provenance_check.py            # 人类可读报告
    python scripts/provenance_check.py --json     # 机器可读（CI 用）
    python scripts/provenance_check.py --strict   # 有提醒也算失败

退出码：0 = 通过；1 = 存在错误（阻断发布）；2 = 缺文件等环境问题
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _skill_name() -> str:
    """从 SKILL.md 读取技能名，避免移植后标题与实际技能不符。"""
    try:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        m = re.search(r"^name:\s*(\S+)", text, re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return ROOT.name

# 允许出现的标准库模块（新增依赖必须显式加进白名单，加不动就说明不该加）
STDLIB_OK = {
    "__future__", "argparse", "base64", "collections", "configparser", "csv",
    "datetime", "difflib", "functools", "hashlib", "io", "itertools", "json",
    "math", "os", "pathlib", "random", "re", "shutil", "socket", "stat",
    "string", "subprocess", "sys", "tempfile", "textwrap", "time", "typing",
    "unicodedata", "urllib", "uuid", "warnings", "zipfile", "importlib",
    "argparse", "json", "datetime", "hashlib", "sqlite3",
}

# 外链只能指向这些域：官方站 / 许可证标准站 / 示例域
URL_OK_SUFFIX = (".gov.cn", ".org.cn", "opensource.org", "json-schema.org",
                 "example.org", "ec.europa.eu", "ccopyright.com.cn")

# 版权与搬运痕迹
COPYRIGHT_RE = re.compile(
    r"(copyright\s*\(c\)|copyright\s*©|spdx-license-identifier|"
    r"licensed under the|all rights reserved|"
    r"本(文|文档)(转载|摘录)自|转载自[:：]|来源[:：]\s*http)",
    re.I,
)

# 本项目自身的著作权人。写有自己署名的主体声明属正常声明，不算"第三方版权痕迹"。
# 换权利人时同步改这里，否则 LICENSE 与 CHANGELOG 会被自己的检查判为违规。
SELF_HOLDERS = ("张勇鑫", "Zhang Yongxin")

# ≥60 字符的纯英文散文行（中文原创文档里出现成段英文多为复制残留）
ENGLISH_PROSE_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 ,.'\"()\-/:;!?]{58,}\s*$")

# 网页复制痕迹
HTML_RESIDUE = ("&nbsp;", "&amp;", "&quot;", "&#", "<br>", "<br/>", "<br />",
                "<!--", "-->", "<div", "<span")

# 不可见字符
INVISIBLE = {"\u200b": "零宽空格", "\u200c": "零宽非连接符",
             "\u00a0": "不间断空格", "\ufeff": "BOM"}

SCAN_SUFFIX = {".md", ".py", ".json", ".txt", ".yaml", ".yml"}
SKIP_DIRS = {"__pycache__", ".git", ".kbtest", ".kb"}
# 这些文件本身就是许可/声明文本或检测规则，按各自规则单独校验，不参与通用扫描
EXEMPT = {"LICENSE", "PROVENANCE.md", "provenance_check.py"}


def iter_files():
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in SCAN_SUFFIX:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        # 仓库内若误存了本地知识库，跳过（另由 gitignore 兜底）
        if "/.kb" in p.as_posix():
            continue
        yield p


def rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def check():
    errors, warns, notes = [], [], []

    files = list(iter_files())
    if not files:
        return [], [("ENV", "未扫描到任何文件，检查运行目录")], []

    # 1. 第三方依赖（标准库 + 仓库内本地模块之外的都算外部依赖）
    imports = set()
    for p in files:
        if p.suffix != ".py":
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*(?:from|import)\s+([A-Za-z_][\w.]*)", line)
            if m:
                imports.add(m.group(1).split(".")[0])
    local_mods = {p.stem for p in files if p.suffix == ".py"}
    extra = sorted(m for m in imports if m not in STDLIB_OK and m not in local_mods)
    stdlib_count = len([m for m in imports if m in STDLIB_OK])
    if extra:
        errors.append(("DEP", f"出现非标准库依赖：{', '.join(extra)}（需确认其许可证与署名义务）"))
    else:
        notes.append(f"依赖检查：标准库 {stdlib_count} 个 + 本地模块 "
                     f"{len(imports & local_mods)} 个，无第三方包")

    # 2..6 逐文件扫描
    for p in files:
        name = rel(p)
        if p.name in EXEMPT:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")

        for i, line in enumerate(text.splitlines(), 1):
            if COPYRIGHT_RE.search(line) and not any(h in line for h in SELF_HOLDERS):
                errors.append(("COPY", f"{name}:{i} 出现第三方版权/来源标记：{line.strip()[:70]}"))

            for frag in HTML_RESIDUE:
                if frag in line:
                    warns.append(("HTML", f"{name}:{i} 含网页复制痕迹「{frag}」"))
                    break

            if p.suffix == ".md" and ENGLISH_PROSE_RE.match(line):
                warns.append(("EN", f"{name}:{i} 出现 ≥60 字符英文长句，疑似复制残留"))

            for ch, label in INVISIBLE.items():
                if ch in line:
                    warns.append(("INVIS", f"{name}:{i} 含{label}"))

        for url in re.findall(r"https?://[^\s)\"'<>\]]+", text):
            host_part = url.split("//", 1)[-1]
            if not any(k in host_part for k in URL_OK_SUFFIX):
                warns.append(("URL", f"{name} 外链不在白名单：{url}"))

    # 7. 规则库来源可追溯
    seed = ROOT / "kb_seed"
    if seed.is_dir():
        total, unlabeled = 0, 0
        for f in sorted(seed.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
            except Exception as exc:  # noqa: BLE001
                errors.append(("JSON", f"{f.name} 解析失败：{exc}"))
                continue
            for r in data.get("rules", []):
                total += 1
                if not r.get("source"):
                    unlabeled += 1
        if unlabeled:
            warns.append(("SRC", f"规则库 {total} 条中有 {unlabeled} 条缺 source 字段（无法自证来源）"))
        else:
            notes.append(f"规则库来源：{total} 条全部标注 source")

    # 8. 必备声明文件
    for must in ("LICENSE", "PROVENANCE.md", "README.md", "SKILL.md"):
        if not (ROOT / must).exists():
            errors.append(("MISS", f"缺少必备文件 {must}"))

    return errors, warns, notes


def main() -> int:
    ap = argparse.ArgumentParser(description="开源发布前原创性自查")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true", help="提醒也视为失败")
    args = ap.parse_args()

    errors, warns, notes = check()
    ok = not errors and not (args.strict and warns)

    if args.json:
        print(json.dumps({
            "ok": ok,
            "errors": [{"code": c, "msg": m} for c, m in errors],
            "warnings": [{"code": c, "msg": m} for c, m in warns],
            "notes": notes,
        }, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    print("=" * 64)
    print(f"原创性自查报告 · {_skill_name()}")
    print("=" * 64)
    if notes:
        print("\n[已通过]")
        for n in notes:
            print(f"  ✓ {n}")
    if errors:
        print(f"\n[错误 {len(errors)}]（必须修掉）")
        for c, m in errors:
            print(f"  ✗ [{c}] {m}")
    if warns:
        print(f"\n[提醒 {len(warns)}]（建议核查）")
        for c, m in warns[:30]:
            print(f"  ! [{c}] {m}")
        if len(warns) > 30:
            print(f"  …… 另有 {len(warns) - 30} 条")

    print("\n" + "-" * 64)
    if ok:
        print("结论：通过。未发现第三方代码或受版权文本的搬运痕迹。")
        print("注：本检查为机器化痕迹筛查，不替代法律意见。")
    else:
        print("结论：未通过。修掉错误项后再发布。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
