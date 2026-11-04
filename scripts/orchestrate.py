#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrate.py — v2p 编排层：plan / settle / change / bundle / use / viz（v2.2.0）

编排契约（与报告《逆向推理技能工具功能报告与演进建议》一致）：
  - v2p 当主人，按需调用 rfe 的能力拿结果，再整合输出一份报告
  - rfe 不反向调用 v2p（单向依赖）；两套工具仍可独立使用
  - 沉淀（settle）只写 rfe 的存储并先进待审区，不是调用 rfe 的业务推理
  - 模态切换在本层完成：挖掘阶段「多问少猜」，排雷阶段「少问多推」，
    两套 SKILL.md 的铁律不进同一个上下文，由本层在阶段交界处切换

零依赖，仅 Python 标准库。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import bridge  # noqa: E402


def _load_v2p():
    spec = importlib.util.spec_from_file_location("v2p_mod", SCRIPTS / "v2p.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_qgate():
    spec = importlib.util.spec_from_file_location("qgate_mod", SCRIPTS / "qgate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _home() -> Path:
    env = os.environ.get("V2P_HOME", "").strip()
    base = Path(env) if env else Path.home() / ".workbuddy" / "v2p"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _plans_dir() -> Path:
    p = _home() / "plans"
    p.mkdir(parents=True, exist_ok=True)
    return p


def issue_code(kind: str, raw) -> str:
    """统一问题编码：跨 v2p / rfe 全局唯一；已带前缀的原样返回，避免重复加前缀。"""
    prefix = bridge.ISSUE_PREFIX.get(kind, "V2P-OR")
    val = str(raw or "").strip()
    if val.upper().startswith(("V2P-", "RFE-")):
        return val
    return f"{prefix}-{val}" if val else f"{prefix}-UNKNOWN"


def _slugify(text: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", (text or "").strip())[:24].strip("-")
    return s or "plan"


def _latest_state() -> Path | None:
    states = sorted(_plans_dir().glob("*/state.json"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    return states[0] if states else None


DISCLAIMER = bridge.DISCLAIMER


# ================================================================ plan

def _bundle_forms(spec: str) -> list:
    out = []
    for tok in re.split(r"[+,，、\s]+", spec or ""):
        tok = tok.strip().lower()
        if tok:
            out.append(tok)
    return out


def _milestone_lines(redlines: list) -> list:
    """倒排里程碑骨架：从红线的提前期反推起点。"""
    leads = []
    for r in redlines:
        lt = (r.get("lead_time") or "").strip()
        if lt:
            leads.append(f"{issue_code('rule', r.get('id'))}（{lt}）：{r.get('rule', '')[:46]}…")
    lines = [
        "## 倒排里程碑（骨架，交付日往回排）",
        "",
        "1. D 日交付/上线 → 2. 交付前 2 周：核查卡全绿 + 手测清单留痕 → "
        "3. 交付前 1 月：内容/数据/资质材料就位",
    ]
    if leads:
        lines.append("")
        lines.append("资质提前期（决定项目最短工期，从 D 日往回扣）：")
        for l in leads:
            lines.append(f"   - {l}")
        lines.append("")
        lines.append("   ⚠ 倒排的含义：先看最长提前期，若「今天 + 最长提前期 > 期望上线日」，")
        lines.append("   诚实的结论不是压缩流程，而是调整上线日。")
    else:
        lines.append("   （本形态未召回带提前期的资质规则；若涉及办证/备案，"
                     "仍按「1–2 个月提前期」估算）")
    lines.append("")
    lines.append("> 单独跑 `rfe recall --query \"<行业>\"` 可看每条红线的完整推导与依据。")
    return lines


def cmd_plan(args) -> int:
    v2p = _load_v2p()
    text = (args.text or "").strip()
    if not text:
        print("请用 -t 传入用户的原话，如：v2p plan -t \"我要做一个招聘小程序\"")
        return 2

    bundle = _bundle_forms(args.bundle) if args.bundle else []
    if bundle:
        scores = {}
        for f in bundle:
            if f not in v2p.FORMS:
                print(f"未知形态「{f}」，可用：{'、'.join(k for k in v2p.FORMS if k != 'unknown')}")
                return 2
            sig = v2p.infer_signals(text, f)
            scores[f] = v2p.total_score(sig)
        top_score = max(scores.values())
        score = min(10, top_score + 1)  # 复合交付天然更复杂：max+1
        form_label = "交付包(" + " + ".join(v2p.FORMS[f]["name"] for f in bundle) + ")"
        primary = max(scores, key=lambda k: scores[k])
        sig = v2p.infer_signals(text, primary)
        code, name, rmin, rmax, act = v2p.level_of(score)
        slug = _slugify(text)[:16] or "bundle"
    else:
        form, hits, second = v2p.infer_form(text)
        f = v2p.FORMS[form]
        sig = v2p.infer_signals(text, form)
        score = v2p.total_score(sig)
        code, name, rmin, rmax, act = v2p.level_of(score)
        form_label = f"{f['name']}（{form}）"
        primary = form
        slug = _slugify(text)

    # ---- 静默调用 rfe（用户感知不到）：少问多推模态 ----
    reds = bridge.redlines(text, top=10)
    pits = bridge.pitfall_recall(text, top=5)
    stamp = bridge.kb_review_stamp()

    pdir = _plans_dir() / f"{date.today().isoformat()}-{slug}"
    pdir.mkdir(parents=True, exist_ok=True)

    # 核查卡（合规节注入）
    qg = _load_qgate()
    red_file = pdir / "redlines.json"
    red_file.write_text(json.dumps(
        [{"id": r.get("id"), "rule": r.get("rule"), "basis": r.get("basis", ""),
          "lead_time": r.get("lead_time", "")} for r in reds],
        ensure_ascii=False, indent=2), encoding="utf-8")
    card_out = pdir / "核查卡.md"
    card_args = argparse.Namespace(
        form=primary, gate="", depth=code, out=str(card_out), force=True,
        kb_redline=str(red_file))
    qg.cmd_card(card_args)

    # 统一报告
    rep: list = [
        f"# 联合推演报告 · {text}",
        "",
        f"> 生成：{date.today().isoformat()}　形态：{form_label}　深度：{code}（{score}/10）"
        f"　轮次预算：{rmin}–{rmax if rmax < 99 else '∞'}",
        f"> 知识库{stamp}",
        f"> 问题编码：V2P-QG-*（质量闸门）｜RFE-RL-*（规则红线）｜RFE-PT-*（坑卡）｜RFE-DR-*（库自检）｜V2P-OR-*（编排告警）",
        "",
        "---",
        "",
        "## 第一部分 · 需求挖掘（v2p：多问少猜）",
        "",
        f"- 形态：{form_label}",
        f"- 深度：{code} {name}；做法：{act}",
        f"- 必挖维度：{'、'.join(v2p.DIM_NAME[d] for d in v2p.FORMS[primary]['must'])}",
        f"- 最常见错配：{v2p.FORMS[primary]['trap']}",
        "",
    ]
    if bundle:
        rep += ["### 交付包深度", ""]
        for f, s in scores.items():
            rep.append(f"- {v2p.FORMS[f]['name']}（{f}）：{s}/10")
        rep += [f"- 合并深度取最大值 +1 → {code}（复合交付天然更复杂）", ""]
    rep += ["### 第一轮先问这 4 个", ""]
    qs = v2p._pick_questions(primary, 1, set())
    for i, item in enumerate(qs[:4], 1):
        rep.append(f"{i}. **{item['q']}**")
        for j, o in enumerate(item.get("opts", [])[:4]):
            rep.append(f"   {'ABCD'[j]}. {o[0] if isinstance(o, tuple) else o}")
    rep += [
        "",
        "（后续轮次用 `v2p ask -f %s -d %s --round N` 取题；答案回来重算深度）" % (primary, code),
        "",
        "---",
        "",
        "## 第二部分 · 合规排雷（rfe：少问多推，已静默召回）",
        "",
    ]
    if reds:
        rep += [f"召回红线 {len(reds)} 条，**全部为阻断项**，不满足任何一条 = 不能上线：", ""]
        for r in reds:
            lead = f"（提前期 {r['lead_time']}）" if r.get("lead_time") else ""
            rep.append(f"- **{issue_code('rule', r.get('id'))}** {r.get('rule')}{lead}")
            if r.get("basis"):
                rep.append(f"  依据：{r['basis']}")
    else:
        rep += ["- 未召回该领域红线。仍按通用四件事自查：主体资质 / 备案许可 / 个人信息 / 内容与广告。",
                "- 如需更准，补充行业关键词重跑，或单独 `rfe recall --query \"...\"`。"]
    raw_rows = bridge.recall(text, top=20, severity="blocker")
    shown = {issue_code("rule", r.get("id")) for r in reds}  # 统一编码去重：红线节已展示的不再重复
    blockers = [row["rule"] for row in raw_rows
                if issue_code("rule", row.get("rule", {}).get("id")) not in shown]
    rep += ["", "### 资源底线与风险（blocker 级，红线之外补充）", ""]
    if blockers:
        for b in blockers:
            rep.append(f"- **{issue_code('rule', b.get('id'))}** [{b.get('domain')}｜{b.get('subdomain', '')}] {b.get('rule', '')}")
            if b.get("lead_time"):
                rep.append(f"  提前期：{b['lead_time']}")
            if b.get("note"):
                rep.append(f"  提醒：{b['note']}")
    else:
        rep.append("- 无新增 blocker 级召回。")
    rep += ["", "---", ""]
    rep += _milestone_lines(reds)
    if pits:
        rep += ["", "## 历史坑预警（来自你自己的踩坑库）", ""]
        for pr in pits:
            p = pr.get("pitfall", {})
            rep.append(f"- **{issue_code('pitfall', p.get('id'))}** [{p.get('domain')}] {p.get('trap')}")
            if p.get("guard"):
                rep.append(f"  预防：{p['guard']}")
    rep += [
        "",
        "---",
        "",
        "## 交付时你需要拿出的东西",
        "",
        f"1. 需求规格（`v2p spec new --title X` 生成骨架，`v2p spec check` 验收）",
        f"2. 核查卡：{card_out}　（质量阻断 0 + 合规红线 0 才算过）",
        f"3. 手测清单：`v2p gate manual -f {primary} -d {code} --out 手测清单.md`　（测完 --verify 留痕）",
        f"4. 沉淀：`v2p settle pitfall ...` + `v2p settle rule ...`（先入待审区）→ `v2p settle done`",
        f"5. 交付自查（铁律 21 / 阶段产出 D）：按 templates/交付自查清单.md 生成一页"
        f"「你要怎么自己验证」（通用 5 项 + 按形态追加，逐条=具体动作+预期结果），与成品一并交付",
        f"6. 形态核对（v2.6.0 / 铁律 19 收紧）：交付清单第一项必须是用户目标形态的"
        f"「本体实物」（app=可安装包或可直接运行的入口；doc=成稿文件；sheet=成品表…），"
        f"PRD/合规报告/自查清单只作附属件排其后——产物里只有 .md 文档 = 未完成，禁止收口",
        f"7. 设备匹配（v2.6.0 新增）：本体必须能在用户指定的目标设备上打开——"
        f"用户说手机APP，交付=APK / 微信小程序工程（可导入开发者工具真机预览）/ "
        f"已部署的移动端 Web App URL 三选一；PC 本地端口网页 ≠ 手机APP；"
        f"最终消息第一段写清「东西在哪、怎么打开」，文档列表排后面",
        "",
        "---",
        "",
        "## 问题编码索引（去重）",
        "",
    ]
    uniq_codes = sorted(set(re.findall(
        r"(?:V2P|RFE)-[A-Z]{2,3}-[A-Z0-9-]+", chr(10).join(rep))))
    if uniq_codes:
        for _c in uniq_codes:
            rep.append(f"- `{_c}`")
        rep += ["", f"共 {len(uniq_codes)} 个唯一编码；同一问题在红线节、资源底线节与倒排里程碑节只引用，不重复告警。", ""]
    else:
        rep += ["- 本次未召回带编码的规则或坑卡（知识库为空或查询无命中）。", ""]
    rep += [
        "---",
        "",
        "## 完整免责声明与使用边界",
        "",
        f"> 生成日期：{date.today().isoformat()}　{stamp}",
        "",
    ]
    for _line in bridge.DISCLAIMER_SECTIONS:
        rep += [_line, ""]
    rep += [
        "---",
        "",
        f"> {DISCLAIMER}",
        f"> {stamp}",
    ]
    report_out = pdir / "report.md"
    report_out.write_text("\n".join(rep) + "\n", encoding="utf-8")

    state = {
        "version": 1,
        "text": text,
        "form": primary,
        "bundle": bundle,
        "depth": code,
        "score": score,
        "redline_ids": [r.get("id") for r in reds],
        "created_at": str(date.today()),
        "settled": {"rules": 0, "pitfalls": 0},
        "delivered": False,
        "changes": [],
        "dir": str(pdir),
    }
    (pdir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # stdout 摘要
    print(f"\n【联合推演】{text}")
    print(f"  形态：{form_label}　深度：{code}（{score}/10）"
          + (f"　交付包：{' + '.join(bundle)}" if bundle else ""))
    print(f"  需求侧：必挖 {'、'.join(v2p.DIM_NAME[d] for d in v2p.FORMS[primary]['must'])}；"
          f"第一轮 4 题见报告")
    print(f"  合规侧：召回红线 {len(reds)} 条（全部阻断）"
          + (f"，其中资质提前期 {sum(1 for r in reds if r.get('lead_time'))} 条含工期约束"
             if reds else "（未命中，按通用四件事自查）"))
    print(f"  坑预警：{len(pits)} 条历史坑命中")
    print(f"\n  产物：")
    print(f"   - 统一报告：{report_out}")
    print(f"   - 核查卡（含合规闸门）：{card_out}")
    print(f"\n  下一步：按报告第一轮问题挖掘 → spec new/check → gate card/manual →"
          f" settle → done")
    print(f"  需求变更时：v2p change -t \"改了什么\"（自动重跑合规与工期推演）")
    print(f"\n  > {DISCLAIMER}")
    return 0


# ================================================================ settle

def cmd_settle(args) -> int:
    if args.action == "status":
        st_path = _latest_state()
        if not st_path:
            print("还没有任何 plan（v2p plan -t \"...\"）。沉淀以 plan 为单位记账。")
            return 0
        st = json.loads(st_path.read_text(encoding="utf-8-sig"))
        s = st.get("settled", {})
        print(f"最近 plan：{st.get('text','')[:40]}（{st_path.parent.name}）")
        print(f"  已沉淀：规则 {s.get('rules',0)} 条 / 坑卡 {s.get('pitfalls',0)} 条"
              f"　已标记交付：{'是' if st.get('delivered') else '否'}")
        if not st.get("delivered") and (s.get("rules", 0) + s.get("pitfalls", 0)) == 0:
            print("  ⚠ 未沉淀任何规则/坑卡。settle 是交付强制收尾步骤：")
            print("     本次踩的坑、验证过的经验不写回，下次还要重踩一遍。")
            print("     v2p settle pitfall --trap \"...\" --guard \"...\"")
            return 1
        return 0

    st_path = _latest_state()
    if args.action == "rule":
        payload = {"rule": args.text or "", "domain": args.domain or "通用",
                   "severity": args.severity or "advisory",
                   "type": args.type or "compliance",
                   "source": "settle", "provenance": "user-input"}
        if not payload["rule"].strip():
            print("规则正文不能为空：v2p settle rule -t \"如果…那么必须…\" --domain 通用")
            return 2
        ok, msg = bridge.write_pending("rule", payload)
        print(msg or ("已写入待审区" if ok else "写入失败"))
        if ok and st_path:
            st = json.loads(st_path.read_text(encoding="utf-8-sig"))
            st["settled"]["rules"] = int(st["settled"].get("rules", 0)) + 1
            st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        print("（新规则先进待审区，确认无误后：rfe pitfall approve --id <ID>）")
        return 0 if ok else 1

    if args.action == "pitfall":
        payload = {"trap": args.trap or "", "domain": args.domain or "通用",
                   "symptom": args.symptom or "", "guard": args.guard or "",
                   "fallback": args.fallback or "",
                   "trigger": [t for t in re.split(r"[,，;；\s]+", args.trigger or "") if t],
                   "source": "settle"}
        if not payload["trap"].strip():
            print("坑描述不能为空：v2p settle pitfall --trap \"...\" --guard \"...\"")
            return 2
        ok, msg = bridge.write_pending("pitfall", payload)
        print(msg or ("已写入待审区" if ok else "写入失败"))
        if ok and st_path:
            st = json.loads(st_path.read_text(encoding="utf-8-sig"))
            st["settled"]["pitfalls"] = int(st["settled"].get("pitfalls", 0)) + 1
            st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        print("（新坑卡先进待审区，确认无误后：rfe pitfall approve --id <ID>）")
        return 0 if ok else 1

    if args.action == "done":
        if not st_path:
            print("没有可标记的 plan。")
            return 2
        st = json.loads(st_path.read_text(encoding="utf-8-sig"))
        s = st.get("settled", {})
        if (s.get("rules", 0) + s.get("pitfalls", 0)) == 0 and not args.skip:
            print("✗ 拒绝标记交付：本次 plan 还没有任何沉淀。")
            print("  settle 是交付强制收尾步骤（可用真实踩坑/规则回写待审区）；")
            print("  确实无任何可沉淀内容时，用 v2p settle done --skip 并在报告注明原因。")
            return 1
        st["delivered"] = True
        if args.skip:
            st["settled_skip_reason"] = args.skip
        st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        print(f"✓ 已标记交付：{st.get('text','')[:40]}")
        print("  收尾提醒：核查卡阻断项应为 0、手测清单 --verify 应通过、"
              "合规红线应全部满足。")
        return 0
    return 2


# ================================================================ change

def cmd_change(args) -> int:
    st_path = _latest_state()
    if not st_path:
        print("没有可变更的 plan（先 v2p plan -t \"...\"）。")
        return 2
    st = json.loads(st_path.read_text(encoding="utf-8-sig"))
    note = (args.text or "").strip()
    if not note:
        print("请说明改了什么：v2p change -t \"增加直播招聘功能，面向蓝领\"")
        return 2
    old_ids = set(st.get("redline_ids", []))
    text = st.get("text", "") + " " + note
    # 变更召回 = 旧原话召回 ∪ 新文本召回（合并去重，避免新关键词把旧红线挤出 top-N）
    seen, reds = set(), []
    for q in dict.fromkeys([st.get("text", ""), text]):
        for r in bridge.redlines(q, top=12):
            rid = r.get("id")
            if rid and rid not in seen:
                seen.add(rid)
                reds.append(r)
    new_ids = [r.get("id") for r in reds]
    added = [r for r in reds if r.get("id") not in old_ids]
    removed = sorted(old_ids - set(new_ids))
    v2p = _load_v2p()
    sig = v2p.infer_signals(text, st.get("form", "app"))
    score = v2p.total_score(sig)
    code, name, rmin, rmax, _ = v2p.level_of(score)

    st.setdefault("changes", []).append(
        {"date": str(date.today()), "note": note,
         "added_redlines": [r.get("id") for r in added],
         "removed_redlines": removed, "new_depth": code})
    st["redline_ids"] = new_ids
    st["depth"] = code
    st["delivered"] = False  # 需求变了，之前的交付标记失效
    st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")

    print(f"\n【变更影响面】{note}")
    print(f"  深度重评：{code}（{score}/10）——{'较之前上升' if code != st.get('depth', code) else '与之前持平'}"
          if False else
          f"  深度重评：{code}（{score}/10），轮次预算 {rmin}–{rmax if rmax < 99 else '∞'}")
    if added:
        print(f"  ⚠ 新增红线 {len(added)} 条（变更引入的新合规要求）：")
        for r in added:
            lead = f"（提前期 {r['lead_time']}）" if r.get("lead_time") else ""
            print(f"    - {issue_code('rule', r.get('id'))} {r.get('rule','')[:56]}…{lead}")
    else:
        print("  合规面无新增红线。")
    if removed:
        print(f"  解除红线 {len(removed)} 条：{', '.join(removed)}"
              "（请人工确认是真的解除了，不是改叫法了）")
    leads = [r for r in reds if r.get("lead_time")]
    if leads:
        print(f"  工期推演：仍有 {len(leads)} 条红线带提前期，倒排起点以最长为准；")
        print("  变更后原排期作废，请按「交付日 - 最长提前期」重算。")
    print(f"  交付标记已重置：需求变更后原「已交付」状态失效，需重新走核查与沉淀。")
    print(f"\n  > {DISCLAIMER}")
    return 0


# ================================================================ bundle 一致性

BUNDLE_CHECKS = [
    ("功能对账", "文档/汇报里承诺的每一条功能，是否都能在原型/代码里指出对应实现？逐条对照，差异写进「待办」而不是口头解释。"),
    ("数字对账", "文档里的用户数、成本、定价、预测，与表格模型里的数是否同源？改一处必须全局搜一遍。"),
    ("品牌对账", "视频/图片/文档里的产品名、Logo、配色、slogan 是否与主视觉一致？截图并排比对。"),
    ("口径对账", "各产出对同一概念的称呼是否一致（用户/客户/会员；GMV/流水/营收）？混用会让读者以为是两件事。"),
    ("版本对账", "所有产出的版本号、日期是否一致？封面写 v1.0 正文写 v1.1 是低级错误的高发区。"),
]


def cmd_bundle(args) -> int:
    items = _bundle_forms(args.items)
    if len(items) < 2:
        print("交付包至少两个产出物：--items app,doc,sheet")
        return 2
    name = args.name or "交付包"
    lines = [
        f"# 一致性对账清单 · {name}",
        "",
        f"> 生成：{date.today().isoformat()}　产出物：{' + '.join(items)}",
        "> 复合交付最常见的翻车不是「某件做得差」，而是「几件之间互相矛盾」。",
        "> 每一项都要逐条对照并留痕，不允许「应该一致」。",
        "",
    ]
    for i, (title, how) in enumerate(BUNDLE_CHECKS, 1):
        lines += [f"## {i}. {title}", "", how, "", "| 检查点 | 结论 | 证据/截图 |", "|---|---|---|"]
        for f in items:
            lines.append(f"| {f} |  |  |")
        lines.append("")
    lines += [
        "## 结论",
        "",
        "- 不一致项：____（**必须为 0 才能整体交付**；改不动就先改文档口径）",
        "- 本次整体交付顺序：____",
        "",
        f"> {DISCLAIMER}",
    ]
    text = "\n".join(lines) + "\n"
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print(f"已生成：{p}")
    else:
        print(text)
    return 0


# ================================================================ use（多项目隔离）

def cmd_use(args) -> int:
    cur = _home() / "current_project"
    if not args.name:
        name = "default"
        if cur.exists():
            name = cur.read_text(encoding="utf-8").strip() or "default"
        print(f"当前项目档案：{name}")
        profs = sorted((_home() / "profiles").glob("*.json")) if (_home() / "profiles").exists() else []
        if profs:
            print("已有档案：" + "、".join(p.stem for p in profs))
        print("切换：v2p use <项目名>（各项目口味互相隔离，不再串数据）")
        return 0
    name = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", args.name.strip()) or "default"
    cur.write_text(name, encoding="utf-8")
    (_home() / "profiles").mkdir(exist_ok=True)
    print(f"已切换项目档案：{name}")
    print(f"  口味档案将存到 {_home() / 'profiles' / (name + '.json')}")
    print("  （环境变量 V2P_PROJECT 可临时覆盖，优先级高于此设置）")
    return 0


# ================================================================ viz（轻量可视化）

def _svg_wrap(inner: str, w: int, h: int) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" font-family="sans-serif">\n'
            f'<rect width="{w}" height="{h}" fill="#ffffff"/>\n{inner}\n</svg>\n')


def cmd_viz(args) -> int:
    if args.what == "depth":
        v2p = _load_v2p()
        text = (args.text or "").strip()
        if not text:
            print("v2p viz depth -t \"原话\"")
            return 2
        form, _, _ = v2p.infer_form(text)
        sig = v2p.infer_signals(text, form)
        score = v2p.total_score(sig)
        code = v2p.level_of(score)[0]
        sigs = [(label, int(sig.get(k, 0))) for k, label, _ in v2p.SIGNALS]
        cx, cy, R = 300, 210, 150
        n = len(sigs)
        pts, grid = [], []
        for ring in (0.33, 0.66, 1.0):
            rp = " ".join(f"{cx + R * ring * __import__('math').cos(2*__import__('math').pi*i/n - __import__('math').pi/2):.1f},"
                          f"{cy + R * ring * __import__('math').sin(2*__import__('math').pi*i/n - __import__('math').pi/2):.1f}"
                          for i in range(n))
            grid.append(f'<polygon points="{rp}" fill="none" stroke="#d0d7e2" stroke-width="1"/>')
        for i, (label, v) in enumerate(sigs):
            ang = 2 * __import__("math").pi * i / n - __import__("math").pi / 2
            r = R * (v / 2 if v else 0.02)
            pts.append(f"{cx + r * __import__('math').cos(ang):.1f},{cy + r * __import__('math').sin(ang):.1f}")
            lx, ly = cx + (R + 26) * __import__("math").cos(ang), cy + (R + 26) * __import__("math").sin(ang)
            grid.append(f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" font-size="13" fill="#333">{label} {v}/2</text>')
        inner = (
            '<text x="300" y="34" text-anchor="middle" font-size="18" font-weight="bold" fill="#1a4d8f">'
            f'深度评分 {score}/10 → {code}</text>'
            + "".join(grid)
            + f'<polygon points="{" ".join(pts)}" fill="rgba(26,77,143,0.25)" stroke="#1a4d8f" stroke-width="2"/>'
        )
        svg = _svg_wrap(inner, 600, 430)
        out = Path(args.out) if args.out else Path.cwd() / f"v2p-depth-{code}.svg"
        out.write_text(svg, encoding="utf-8")
        print(f"已生成深度雷达图：{out}")
        return 0

    if args.what == "gates":
        qg = _load_qgate()
        form = args.form
        rows = qg.checks_for(form)
        by_gate = {}
        for c in rows:
            by_gate.setdefault(c["gate"], [0, 0])
            by_gate[c["gate"]][0] += 1
            if c["sev"] == "block":
                by_gate[c["gate"]][1] += 1
        W, bar_h, gap = 640, 30, 12
        H = 60 + len(by_gate) * (bar_h + gap) + 40
        parts = [f'<text x="20" y="34" font-size="17" font-weight="bold" fill="#1a4d8f">'
                 f'质量闸门分布 · {qg.FORM_LABEL.get(form, form)}（{len(rows)} 项）</text>']
        max_n = max(v[0] for v in by_gate.values()) or 1
        y = 56
        for g, (n_total, n_block) in by_gate.items():
            gname, _ = qg.GATE_INDEX[g]
            w = 380 * n_total / max_n
            parts.append(f'<text x="20" y="{y + 20}" font-size="13" fill="#333">{gname}</text>')
            parts.append(f'<rect x="120" y="{y}" width="{w:.0f}" height="{bar_h}" rx="4" fill="#c9d9ef"/>')
            parts.append(f'<rect x="120" y="{y}" width="{380 * n_block / max_n:.0f}" height="{bar_h}" rx="4" fill="#c62828"/>')
            parts.append(f'<text x="{120 + w + 10:.0f}" y="{y + 20}" font-size="12" fill="#555">'
                         f'{n_total} 项（阻断 {n_block}）</text>')
            y += bar_h + gap
        parts.append(f'<text x="20" y="{H - 12}" font-size="11" fill="#888">'
                     '浅色=全部项，深色=阻断项。阻断必须清零才可交付。</text>')
        svg = _svg_wrap("".join(parts), W, H)
        out = Path(args.out) if args.out else Path.cwd() / f"v2p-gates-{form}.svg"
        out.write_text(svg, encoding="utf-8")
        print(f"已生成闸门分布图：{out}")
        return 0
    if args.what == "heatmap":
        v2p = _load_v2p()
        text = (args.text or "").strip()
        form, _, _ = v2p.infer_form(text) if text else ("app", [], None)
        sig = v2p.infer_signals(text, form) if text else {}
        levels = ["D0", "D1", "D2", "D3", "D4"]
        keys = [k for k, _, _ in v2p.SIGNALS]
        labels = [lab for _, lab, _ in v2p.SIGNALS]
        cell, gap, left, top = 96, 8, 150, 78
        W = left + len(levels) * (cell + gap) + 30
        H = top + len(keys) * (cell + gap) + 76
        parts = [
            '<text x="20" y="30" font-size="17" font-weight="bold" fill="#1a4d8f">'
            '五信号 × 深度等级 关注热力图</text>',
            f'<text x="20" y="52" font-size="12" fill="#666">'
            f'形态：{v2p.FORMS[form]["name"]}　颜色越深＝该深度下该信号需投入的追问权重越高</text>',
        ]
        for j, lv in enumerate(levels):
            x = left + j * (cell + gap)
            parts.append(f'<text x="{x + cell / 2:.0f}" y="{top - 12}" text-anchor="middle" '
                         f'font-size="13" font-weight="bold" fill="#333">{lv}</text>')
        for i, (k, lab) in enumerate(zip(keys, labels)):
            y = top + i * (cell + gap)
            parts.append(f'<text x="20" y="{y + cell / 2 + 5:.0f}" font-size="13" fill="#333">{lab}</text>')
            base = int(sig.get(k, 0) or 0)
            for j in range(len(levels)):
                w = min(1.0, (base / 2) * (0.30 + 0.175 * j))
                rr = int(238 + (26 - 238) * w)
                gg = int(243 + (77 - 243) * w)
                bb = int(250 + (143 - 250) * w)
                fg = "#ffffff" if w > 0.55 else "#1f2d3d"
                x = left + j * (cell + gap)
                parts.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="6" '
                             f'fill="rgb({rr},{gg},{bb})" stroke="#d0d7e2"/>')
                parts.append(f'<text x="{x + cell / 2:.0f}" y="{y + cell / 2 + 5:.0f}" '
                             f'text-anchor="middle" font-size="14" fill="{fg}">{w:.2f}</text>')
        ly = top + len(keys) * (cell + gap) + 18
        parts.append(f'<text x="20" y="{ly}" font-size="11" fill="#888">'
                     '权重 = 信号得分(0-2)/2 × 深度系数(0.30→1.00)；仅作追问优先级参考，非合规结论。</text>')
        svg = _svg_wrap("".join(parts), W, H)
        out = Path(args.out) if args.out else Path.cwd() / "v2p-heatmap.svg"
        out.write_text(svg, encoding="utf-8")
        print(f"已生成信号热力图：{out}")
        return 0
    print("未知图类型，可用：depth / gates / heatmap")
    return 2


# ================================================================ 入口

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="v2p-orchestrate", description="v2p 编排层")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("plan", help="统一入口：挖掘计划 + 合规红线 + 倒排计划，一份输出")
    s.add_argument("--text", "-t", required=True, help="用户的原话")
    s.add_argument("--bundle", default="", help="交付包形态，如 app,doc,sheet")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("settle", help="交付沉淀：rule / pitfall / status / done")
    s.add_argument("action", choices=["rule", "pitfall", "status", "done"])
    s.add_argument("--text", "-t", default="", help="规则正文（如果…那么必须…）")
    s.add_argument("--trap", default="", help="坑：怎么踩的")
    s.add_argument("--symptom", default="", help="坑：当时现象")
    s.add_argument("--guard", default="", help="坑：以后怎么防")
    s.add_argument("--fallback", default="", help="坑：踩了怎么兜底")
    s.add_argument("--trigger", default="", help="坑：触发词，逗号分隔")
    s.add_argument("--domain", default="通用")
    s.add_argument("--severity", default="advisory", choices=["redline", "blocker", "advisory"])
    s.add_argument("--type", default="compliance",
                   choices=["compliance", "resource", "risk", "path"])
    s.add_argument("--skip", default="", help="done 时确无沉淀的说明理由")
    s.set_defaults(func=cmd_settle)

    s = sub.add_parser("change", help="需求变更：自动重跑合规与工期推演")
    s.add_argument("--text", "-t", required=True, help="改了什么")
    s.set_defaults(func=cmd_change)

    s = sub.add_parser("bundle", help="交付包一致性对账清单")
    s.add_argument("--name", default="")
    s.add_argument("--items", required=True, help="如 app,doc,sheet")
    s.add_argument("--out", "-o", default="")
    s.set_defaults(func=cmd_bundle)

    s = sub.add_parser("use", help="切换/查看项目口味档案（多项目隔离）")
    s.add_argument("name", nargs="?", default="")
    s.set_defaults(func=cmd_use)

    s = sub.add_parser("viz", help="轻量可视化：depth / gates / heatmap")
    s.add_argument("what", choices=["depth", "gates", "heatmap"])
    s.add_argument("--text", "-t", default="")
    s.add_argument("--form", "-f", default="app")
    s.add_argument("--out", "-o", default="")
    s.set_defaults(func=cmd_viz)
    return ap


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
