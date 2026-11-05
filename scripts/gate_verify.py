#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_verify.py — 终局交付三道关卡（可执行版，v2.7.0 内置）。

把 SKILL.md 7.4.1 的三道关卡从条文升级为可执行核验：
  关卡1 形态本体：产物清单第一项必须是用户目标形态的「本体实物」（非 .md）
  关卡2 设备匹配：本体必须能在用户指定的目标设备上打开（手机APP→三选一合格形态）
  关卡3 呈现顺序：交付消息第一段必须先讲"东西在哪、怎么打开"，.md 只能排后面

用法：
  python scripts/gate_verify.py --form 手机APP --delivery 交付消息.md --products 目录A 目录B ...
  python scripts/gate_verify.py --form 文档   --delivery 交付消息.md --products .
  python scripts/gate_verify.py --selftest    # 内置正反用例自检

退出码：0=全过；1=有 FAIL（禁止收口，回阶段④）；2=参数错误。
判定细则见 references/final-delivery.md 2.3/2.4 节。
"""
import argparse
import re
import sys
from pathlib import Path

# 形态映射表（v2.6.0 SKILL.md 7.4.1）：目标原话 → 合格本体判定器
FORM_KEYWORDS = {
    "手机APP": ["手机APP", "手机app", "手机上用", "装个APP", "掌上", "移动端APP", "手机端"],
    "桌面软件": ["电脑软件", "桌面应用", "电脑上用", "exe"],
    "小程序": ["小程序", "微信小程序"],
    "网页": ["网页", "网站", "web", "Web"],
}
DOC_EXTS = {".md", ".markdown"}
# 各形态的本体扩展名 / 特征文件
FORM_BODY = {
    "通用app": [".apk", ".exe", ".dmg", ".ipa", ".appimage"],
    "web入口": [".html", ".htm"],
    "小程序工程": ["app.json", "project.config.json"],
}
# 手机APP 合格本体（SKILL.md 7.4.1 形态映射表三选一）
MOBILE_OK = {
    "apk": lambda p: p.suffix.lower() == ".apk",
    "mini_program": lambda p: (p / "app.json").is_file() and (p / "project.config.json").is_file(),
    "mobile_web": lambda p: False,  # 由 _check_mobile_web 单独判定（需 URL 或含 viewport 的 index.html）
}


def classify_form(form_arg: str) -> str:
    """把 --form 参数归一到标准形态名。"""
    f = form_arg.strip().lower()
    if any(k.lower() in f for k in FORM_KEYWORDS["手机APP"]):
        return "手机APP"
    if any(k.lower() in f for k in FORM_KEYWORDS["桌面软件"]):
        return "桌面软件"
    if any(k.lower() in f for k in FORM_KEYWORDS["小程序"]):
        return "小程序"
    if any(k.lower() in f for k in FORM_KEYWORDS["网页"]):
        return "网页"
    return "通用"


def collect_files(product_dirs):
    files = []
    for d in product_dirs:
        p = Path(d)
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            skip = {".git", "node_modules", "__pycache__", "dist", ".workbuddy"}
            for f in p.rglob("*"):
                if f.is_file() and not any(s in f.parts for s in skip):
                    files.append(f)
    return files


def gate1_form(files):
    """关卡1：存在非 .md 的本体实物。返回 (ok, body_files, doc_files)。"""
    docs = [f for f in files if f.suffix.lower() in DOC_EXTS]
    body = [f for f in files if f.suffix.lower() not in DOC_EXTS]
    return bool(body), body, docs


def _looks_mobile_web(html_path: Path) -> bool:
    try:
        t = html_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(re.search(r'<meta[^>]+name="viewport"', t))


def gate2_device(form: str, body_files, product_dirs):
    """关卡2：设备匹配。返回 (ok, detail_dict)。"""
    detail = {}
    if form == "手机APP":
        apk = [f for f in body_files if f.suffix.lower() == ".apk"]
        detail["APK 安装包"] = bool(apk)
        mp = [d for d in product_dirs if Path(d).is_dir()
              and (Path(d) / "app.json").is_file() and (Path(d) / "project.config.json").is_file()]
        detail["小程序工程（app.json+project.config.json）"] = bool(mp)
        mw = [f for f in body_files if f.suffix.lower() in (".html", ".htm") and _looks_mobile_web(f)]
        detail["移动端 Web（含 viewport 的 index.html，须部署出 URL 后交付）"] = bool(mw)
        ok = any(detail.values())
        return ok, detail
    # 其他形态：本体存在即视为匹配（通用兜底）
    return True, {"通用本体": bool(body_files)}


def gate3_presentation(delivery_text: str, form: str):
    """关卡3：呈现顺序。返回 (ok, detail_dict)。"""
    checks = {}
    text = delivery_text or ""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    open_words = ("打开", "扫码", "浏览器", "导入", "安装", "访问", "下载", "点击", "预览")
    checks["首行指向本体入口（URL/APK/工程/index.html）"] = any(
        k in first_line for k in ("http", "URL", "APK", "apk", "index.html", "project.config.json", "微信开发者工具"))
    checks["首行含打开方式动词"] = any(w in first_line for w in open_words)
    md_pos = text.find(".md")
    body_pos = min([p for p in (text.find("http"), text.find("index.html"),
                                text.find("APK"), text.find("apk")) if p >= 0], default=-1)
    checks["文档列表排在本体之后"] = md_pos == -1 or body_pos == -1 or body_pos < md_pos
    return all(checks.values()), checks


def run_gate(form_arg, delivery_file, product_dirs):
    form = classify_form(form_arg)
    files = collect_files(product_dirs)
    fails = []

    ok1, body, docs = gate1_form(files)
    print(f"[关卡1 形态本体] 本体实物: {[f.name for f in body][:5] or '无'} | 附属 .md: {len(docs)} 份")
    if not ok1:
        fails.append("关卡1：产物清单里没有非 .md 的本体实物——只有文档 = 未完成，回阶段④（铁律 19）")

    ok2, d2 = (False, {})
    if ok1:
        ok2, d2 = gate2_device(form, body, product_dirs)
        for k, v in d2.items():
            print(f"[关卡2 设备匹配:{form}] {k}: {'✓' if v else '✗'}")
        if not ok2:
            fails.append(f"关卡2：{form} 的合格本体三选一（APK/小程序工程/已部署移动端Web URL）一个都不满足——PC 本地端口网页 ≠ 手机APP（7.4.1 形态映射表）")

    delivery_text = ""
    if delivery_file and Path(delivery_file).is_file():
        delivery_text = Path(delivery_file).read_text(encoding="utf-8", errors="replace")
    ok3, d3 = gate3_presentation(delivery_text, form)
    for k, v in d3.items():
        print(f"[关卡3 呈现顺序] {k}: {'✓' if v else '✗'}")
    if not ok3:
        fails.append("关卡3：交付消息第一段必须先讲「东西在哪、怎么打开」（URL/二维码/导入步骤+真机自测指引），.md 文档只能排后面")

    print("-" * 56)
    if fails:
        print("⛔ 交付关卡未通过，禁止收口：")
        for m in fails:
            print("  - " + m)
        print("处理：回阶段④继续把合格本体做出来（铁律 19 / 7.4.1）。")
        return 1
    print(f"✅ 三道关卡全过（形态={form}），允许收口。")
    return 0


def selftest():
    """内置正反用例：正向=临时目录造一个含 viewport 的 index.html；反向=只有 .md。"""
    import tempfile
    base = Path(tempfile.mkdtemp(prefix="gate_selftest_"))
    # 正向
    good = base / "good"; good.mkdir()
    (good / "index.html").write_text('<html><head><meta name="viewport" content="width=device-width"></head><body>ok</body></html>', encoding="utf-8")
    (good / "交付消息.md").write_text("手机打开即用（本体入口 URL）：https://example.com\n附属文档：PRD.md\n", encoding="utf-8")
    rc1 = run_gate("手机APP", good / "交付消息.md", [good])
    # 反向
    bad = base / "bad"; bad.mkdir()
    (bad / "PRD.md").write_text("# PRD\n", encoding="utf-8")
    (bad / "合规流程报告.md").write_text("# 合规\n", encoding="utf-8")
    (bad / "交付消息.md").write_text("本地访问 http://localhost:3100 查看效果。\n文档产物：PRD.md\n", encoding="utf-8")
    rc2 = run_gate("手机APP", bad / "交付消息.md", [bad])
    ok = rc1 == 0 and rc2 == 1
    print("=" * 56)
    print("✅ 自检通过：正向放行、负向拦截" if ok else "⛔ 自检失败：关卡逻辑异常")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="终局交付三道关卡核验")
    ap.add_argument("--form", help="用户目标形态原话，如：手机APP / 小程序 / 文档")
    ap.add_argument("--delivery", help="交付消息文件路径（.md/.txt）")
    ap.add_argument("--products", nargs="*", default=["."], help="产物目录或文件（可多个）")
    ap.add_argument("--selftest", action="store_true", help="运行内置正反用例自检")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(selftest())
    if not args.form:
        ap.error("需要 --form（用户目标形态原话）")
    sys.exit(run_gate(args.form, args.delivery, args.products))


if __name__ == "__main__":
    main()
