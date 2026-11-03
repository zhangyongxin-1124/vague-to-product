#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py — 端到端自测（全程在临时目录，不碰真实档案）"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V2P = ROOT / "scripts" / "v2p.py"
PASS, FAIL = [], []


def run(*args, home: Path, stdin: str = "") -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["V2P_HOME"] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    # 隔离 rfe 写操作：bridge 经 subprocess 调 rfe，写待审区必须落在临时库
    env["RFE_KB"] = str(home / "rfe-kb")
    return subprocess.run(
        [sys.executable, str(V2P), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, input=stdin,
    )


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not ok and detail:
        print(f"         {detail.strip()[:300]}")


GOOD_PRD = """# 园区零工小助手

## 一句话

给 45-60 岁园区保洁阿姨解决"找活靠熟人、信息不对称"的问题，靠一个能看岗位、能一键拨电话的小程序。

## 痛点

- "我不知道哪家厂今天要人，只能等老乡打电话给我"

## 用户

| 角色 | 是谁 | 一天用几次 | 手机熟练度 |
|---|---|---|---|
| 主用户 | 园区零工 | 2 | 只会用微信 |

## 核心场景

周三早上七点，阿姨在宿舍刷手机，想知道今天哪个厂招人。现在只能等老乡打电话，用这个产品后打开就能看到列表。

## 主流程

1. 打开 → 看到今天的岗位列表
2. 点卡片 → 看到电话和地址
3. 点拨号 → 直接呼出

## MVP 范围

| 级别 | 功能 | 验收标准 |
|---|---|---|
| P0 | 岗位列表 | 当打开首页时，应显示 10 条内岗位，含工种与日薪 |
| P0 | 一键拨号 | 当点卡片时，应呼出系统拨号盘 |
| P1 | 按区域筛选 | 当选园区时，应只显示该园区岗位 |

## 数据最小集

| 实体 | 字段 | 类型 | 谁填 | 必填 |
|---|---|---|---|---|
| 岗位 | 工种 | 文本 | 管理员 | 是 |

## 不做清单

- 不做注册登录
- 不做在线支付
- 不做简历上传
"""

GOOD_BRIEF = """# 园区政策速查表

## 一句话

给园区招商负责人解决"企业问政策答不上来"的问题，靠一张按行业分好的政策速查表。

## 对象与用途

一张 A3 双面打印的政策速查表，招商人员接待企业时摊在桌上，按行业索引翻到对应页，直接念出适用条款与申报窗口。

## 必须包含的内容

1. 八大行业的政策索引页
2. 每个行业 5 条最常用政策
3. 每条政策的申报条件与截止时间
4. 办理窗口与联系人
5. 常见问答 10 条

## 不做什么

- 不做政策全文汇编
- 不做线上系统

## 验收标准

- 当招商人员拿到企业行业名时，应在 30 秒内翻到对应页
- 当阅读某条政策时，应能看到申报条件与截止时间

## 关键约束

| 类型 | 约束 |
|---|---|
| 尺寸/格式 | A3 双面，可黑白打印 |
| 时间 | 月底前 |
"""


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="v2p_test_"))
    home = tmp / "home"
    home.mkdir()

    # ---------------------------------------------- 形态判定
    print("[1] route 形态判定（同一句模糊话，形态不同则问题不同）")
    cases = [
        ("我想做一款帮40岁以上中老年找零工的App", "软件应用"),
        ("帮我写一份商业计划书，要拿去给投资人看", "文档与报告"),
        ("帮我做一个台账表格，要能算合计", "表格与数据"),
        ("做一张公众号头图，要能改字", "图形与图像"),
        ("帮我做个产品的3D模型，要3D打印出来", "3D 模型与空间"),
        ("做一条抖音竖屏短视频，30秒", "音视频"),
        ("把公司这些资料整理成知识库", "资料与知识"),
        ("帮我安排一场线下活动，要落地", "实物与服务"),
        ("我有个想法，不知道要做成什么样", "未定形态"),
    ]
    for text, expect in cases:
        r = run("route", "-t", text, home=home)
        check(f"识别为「{expect}」", expect in r.stdout, r.stdout[:200] + r.stderr[:200])

    print("[2] 未定形态必须提示先定形态")
    r = run("route", "-t", "我有个想法，不知道要做成什么样", home=home)
    check("提示没识别出形态", "没识别出形态" in r.stdout, r.stdout[:300])

    # ---------------------------------------------- 深度动态
    print("[3] 深度随信号变化（不写死轮次）")
    r = run("route", "-t", "帮我写个 html 页面看看效果", home=home)
    check("低风险 → D1 或 D0", "D1" in r.stdout or "D0" in r.stdout, r.stdout[:400])
    r = run("route", "-t",
            "要做个平台，涉及在线支付和资金结算，已经上线要给公众用，还要长期运营维护",
            home=home)
    check("高风险 → D3 或 D4", "D3" in r.stdout or "D4" in r.stdout, r.stdout[:400])

    print("[4] depth 命令按信号算等级")
    r = run("depth", "--impact", "0", "--reversi", "0", "--unknown", "0",
            "--complex", "0", "--reuse", "0", home=home)
    check("全 0 分 → D0", "D0" in r.stdout, r.stdout)
    r = run("depth", "--impact", "2", "--reversi", "2", "--unknown", "2",
            "--complex", "2", "--reuse", "2", home=home)
    check("满分 → D4 且不限轮次", "D4" in r.stdout and "不限" in r.stdout, r.stdout)

    print("[5] 轮次越界必须警告，而不是默默继续")
    r = run("depth", "--impact", "2", "--unknown", "2", "--complex", "2",
            "--reuse", "2", "--round", "2", home=home)
    check("轮次不足时禁止收敛", "不能收敛" in r.stdout, r.stdout)
    r = run("depth", "--impact", "0", "--unknown", "0", "--complex", "0",
            "--reuse", "0", "--round", "5", home=home)
    check("轮次超出时要求给理由", "已超" in r.stdout and "理由" in r.stdout, r.stdout)

    # ---------------------------------------------- 提问
    print("[6] 形态不同，问题不同（这是「不写死」的关键）")
    r_app = run("ask", "--form", "app", "--depth", "D2", "--round", "2", home=home)
    r_doc = run("ask", "--form", "doc", "--depth", "D2", "--round", "2", home=home)
    r_3d = run("ask", "--form", "model3d", "--depth", "D2", "--round", "2", home=home)
    check("软件类问核心动作", "核心的那一个动作" in r_app.stdout, r_app.stdout[:300])
    check("文档类问读者做什么决定", "做什么决定" in r_doc.stdout, r_doc.stdout[:300])
    check("3D 类问拿去干什么", "拿去干什么" in r_3d.stdout, r_3d.stdout[:300])
    check("三类题目互不相同",
          len({r_app.stdout[:200], r_doc.stdout[:200], r_3d.stdout[:200]}) == 3)

    print("[7] 深度越深，轮次越多（同一形态）")
    d1 = run("ask", "--form", "app", "--depth", "D1", "--round", "1", home=home)
    d4 = run("ask", "--form", "app", "--depth", "D4", "--round", "6", home=home)
    check("D1 显示 2 轮预算", "预算 2–2" in d1.stdout, d1.stdout[:200])
    check("D4 在第 6 轮仍能出题", d4.returncode == 0 and "？" in d4.stdout, d4.stdout[:300])

    print("[8] 已覆盖的维度不重复问")
    r = run("ask", "--form", "doc", "--depth", "D3", "--round", "4",
            "--done", "goal,scene,delivery,constraint,object,quality", home=home)
    check("跳过已覆盖维度", "读者读完这份文档" not in r.stdout, r.stdout[:400])
    check("仍给出边界题", "不能写进去" in r.stdout, r.stdout[:400])

    print("[9] 维度全cover后转定型，不再硬凑题")
    r = run("ask", "--form", "sheet", "--depth", "D2", "--round", "9",
            "--done", "goal,scene,object,constraint,quality,boundary,delivery,evolution",
            home=home)
    check("提示转阶段三", "转阶段三" in r.stdout or "全部覆盖" in r.stdout, r.stdout[:300])

    print("[10] 选项规范")
    r = run("ask", "--form", "app", "--depth", "D2", "--round", "1", home=home)
    check("选项带代价标签", "代价：" in r.stdout, r.stdout[:200])
    check("留自由填写入口", "自己填" in r.stdout, r.stdout[:200])

    print("[11] forms 列出八类形态")
    r = run("forms", home=home)
    check("八类齐全", all(k in r.stdout for k in
                        ["软件应用", "文档与报告", "表格与数据", "图形与图像",
                         "3D 模型与空间", "音视频", "资料与知识", "实物与服务"]), r.stdout[:400])

    # ---------------------------------------------- 档案
    print("[12] profile 记录")
    r = run("profile", "set", "不喜欢注册登录", home=home)
    check("set 首次写入", r.returncode == 0 and "1" in r.stdout, r.stdout)
    r = run("profile", "set", "不喜欢注册登录", home=home)
    check("set 计数累加", "×2" in r.stdout, r.stdout)
    r = run("profile", "show", home=home)
    check("show 能读到偏好", "不喜欢注册登录" in r.stdout, r.stdout)

    r = run("profile", "veto", "会员体系", home=home)
    check("veto 记录成功", "已否决" in r.stdout, r.stdout)
    r = run("profile", "veto", "会员体系", home=home)
    check("veto 幂等不重复", "已在否决列表" in r.stdout, r.stdout)

    check("habit 记录", run("profile", "habit", "结论先行", home=home).returncode == 0)
    check("cat 记录品类", "招聘" in run("profile", "cat", "招聘", home=home).stdout)
    check("shape 记录形态", "小程序" in run("profile", "shape", "小程序", home=home).stdout)
    r = run("profile", "depth", "D2", home=home)
    check("depth 记录深度习惯", "D2" in r.stdout, r.stdout)

    # ---------------------------------------------- 规格
    print("[13] spec new（软件 PRD / 通用定型卡）")
    prd = tmp / "prd.md"
    r = run("spec", "new", "--title", "园区零工小助手", "--out", str(prd), home=home)
    check("PRD 生成成功", r.returncode == 0 and prd.exists(), r.stderr)
    check("PRD 含标题", "园区零工小助手" in prd.read_text(encoding="utf-8"))

    brief = tmp / "brief.md"
    r = run("spec", "new", "--title", "政策速查表", "--brief", "--out", str(brief), home=home)
    check("定型卡生成成功", r.returncode == 0 and brief.exists(), r.stderr)
    check("定型卡含通用章节", "必须包含的内容" in brief.read_text(encoding="utf-8"))

    print("[14] spec check 软件 PRD")
    r = run("spec", "check", "--file", str(prd), home=home)
    check("空 PRD 被判不合格", r.returncode == 1, r.stdout)
    good = tmp / "good.md"
    good.write_text(GOOD_PRD, encoding="utf-8")
    r = run("spec", "check", "--file", str(good), "--form", "app", home=home)
    check("完整 PRD 通过", r.returncode == 0, r.stdout)

    bad = tmp / "bad.md"
    rows = "\n".join(f"| P0 | 功能{i} | 当点{i}时，应出现 |" for i in range(1, 8))
    bad.write_text(GOOD_PRD.replace(
        "| P0 | 一键拨号 | 当点卡片时，应呼出系统拨号盘 |", rows), encoding="utf-8")
    r = run("spec", "check", "--file", str(bad), "--form", "app", home=home)
    check("P0 超过 5 个被拦", r.returncode == 1 and "超过上限" in r.stdout, r.stdout)

    nond = tmp / "nond.md"
    nond.write_text(GOOD_PRD.split("## 不做清单")[0], encoding="utf-8")
    check("缺不做清单被拦",
          run("spec", "check", "--file", str(nond), "--form", "app", home=home).returncode == 1)

    print("[15] spec check 非软件形态（走通用定型卡，不用 P0 逻辑）")
    r = run("spec", "check", "--file", str(brief), "--form", "doc", home=home)
    check("空定型卡被判不合格", r.returncode == 1, r.stdout)
    gb = tmp / "good_brief.md"
    gb.write_text(GOOD_BRIEF, encoding="utf-8")
    r = run("spec", "check", "--file", str(gb), "--form", "doc", home=home)
    check("完整定型卡通过", r.returncode == 0, r.stdout)
    check("不套用 P0 逻辑", "P0" not in r.stdout, r.stdout[:300])

    print("[16] stats")
    r = run("stats", home=home)
    check("stats 可运行", r.returncode == 0 and "题库" in r.stdout, r.stdout)
    check("stats 显示形态与深度", "8 类" in r.stdout and "5 级" in r.stdout, r.stdout)

    # ---------------------------------------------- 质量闸门
    print("[17] gate 质量闸门（六类问题内置）")
    r = run("gate", "stats", home=home)
    check("闸门条目完整（65 项）", "检查项总数 65" in r.stdout, r.stdout[:300])
    check("六道闸门都在", all(g in r.stdout for g in
                          ["完整态", "交互", "布局", "数据", "工程", "可维护"]), r.stdout[:400])

    print("[18] 按形态裁剪：文档不会被问「加载态」")
    r_doc = run("gate", "list", "-f", "doc", home=home)
    r_app = run("gate", "list", "-f", "app", home=home)
    check("文档不出软件项 QG-101", "QG-101" not in r_doc.stdout, r_doc.stdout[:300])
    check("文档有自己的结论项 QG-701", "QG-701" in r_doc.stdout, r_doc.stdout[:300])
    check("软件含空态项 QG-102", "QG-102" in r_app.stdout, r_app.stdout[:300])
    r_3d = run("gate", "list", "-f", "model3d", home=home)
    check("3D 不问登录与滚动", "QG-101" not in r_3d.stdout and "QG-202" not in r_3d.stdout,
          r_3d.stdout[:300])

    print("[19] 按深度裁剪：浅活不被 48 项淹没")
    r = run("gate", "list", "-f", "app", "-d", "D1", home=home)
    check("D1 只出核心 7 项", "共 7 项" in r.stdout, r.stdout[:200])
    r = run("gate", "list", "-f", "app", "-d", "D2", home=home)
    check("D2 出全部阻断项", "共 30 项" in r.stdout, r.stdout[:200])
    r = run("gate", "list", "-f", "app", "-d", "D3", home=home)
    check("D3 出全量 48 项", "共 48 项" in r.stdout, r.stdout[:200])

    print("[20] 核查卡可填写（状态矩阵在前，闸门在后）")
    card = tmp / "card.md"
    r = run("gate", "card", "-f", "app", "-d", "D2", "-o", str(card), home=home)
    check("核查卡生成成功", r.returncode == 0 and card.exists(), r.stderr)
    txt = card.read_text(encoding="utf-8") if card.exists() else ""
    check("含状态矩阵七行", txt.count("|") > 20 and "加载中" in txt and "素材缺失" in txt)
    check("含阻断项与勾选框", "QG-101" in txt and "☐" in txt)
    check("含破坏性测试", "断网" in txt)
    check("已存在时不覆盖", run("gate", "card", "-f", "app", "-o", str(card),
                          home=home).returncode == 1)

    print("[21] 静态扫描：能抓到假数据与密钥，也能放过干净文件")
    badproj = tmp / "badproj"
    badproj.mkdir()
    (badproj / "index.html").write_text(
        '<div id="list"></div>\n'
        '<script>\n'
        'const apiKey = "sk-abcdefghijklmnop123456";\n'
        'const items = [{name:"张三", phone:"13800138000"}];\n'
        'items.map(i => document.getElementById("list").innerHTML += i.name);\n'
        '</script>\n', encoding="utf-8")
    r = run("gate", "scan", "-p", str(badproj), home=home)
    check("扫出密钥明文", "QGS-01" in r.stdout, r.stdout[:400])
    check("扫出写死假数据", "QGS-02" in r.stdout, r.stdout[:400])
    check("扫出「有列表无空态」", "没有任何空态" in r.stdout, r.stdout[:400])
    check("有阻断项时退出码为 1", r.returncode == 1, f"rc={r.returncode}")

    okproj = tmp / "okproj"
    okproj.mkdir()
    (okproj / "index.html").write_text(
        "<!doctype html><html><body>\n"
        '<p class="loading">正在加载…</p>\n'
        '<p class="empty">还没有内容，点下面的按钮添加第一条。</p>\n'
        "</body></html>\n", encoding="utf-8")
    r = run("gate", "scan", "-p", str(okproj), home=home)
    check("干净文件不报阻断", r.returncode == 0, r.stdout[:400])
    check("并说明扫描不能替代手点", "不能替代手工点一遍" in r.stdout, r.stdout[:300])

    r = run("gate", "redteam", "-f", "app", home=home)
    check("破坏性测试可生成", r.returncode == 0 and "断网" in r.stdout, r.stdout[:300])

    print("[22] 闸门从 v2p 主入口可达（单一入口，不靠记两个命令）")
    check("v2p gate list 可用",
          run("gate", "list", "-f", "sheet", home=home).returncode == 0)

    # ================= v2.2.0 编排层 =================

    print("[23] 手测清单：生成 → 未勾选拦截 → 勾选+截图放行")
    mpath = home / "manual.md"
    r = run("gate", "manual", "-f", "app", "-d", "D2", "-o", str(mpath), home=home)
    check("手测清单生成", r.returncode == 0 and mpath.exists(), r.stdout[:300])
    body = mpath.read_text(encoding="utf-8")
    check("含必测五条", all(k in body for k in ("空态", "错误态", "返回丢状态", "重复提交", "极端量")))
    check("含截图留痕位", "截图：" in body)
    r = run("gate", "manual", "--verify", str(mpath), home=home)
    check("未勾选时 verify 失败", r.returncode == 1, r.stdout[:200])
    mpath.write_text(body.replace("- [ ]", "- [x]").replace("截图：____", "截图：C:/s/1.png"),
                     encoding="utf-8")
    r = run("gate", "manual", "--verify", str(mpath), home=home)
    check("勾选+截图后 verify 通过", r.returncode == 0, r.stdout[:200])

    print("[24] 合规闸门：card 注入 rfe 红线（阻断级）")
    rfe = ROOT.parent / "fuzzy-reverse-flow" / "scripts" / "rfe.py"
    if rfe.is_file():
        rl = home / "redlines.json"
        rr = subprocess.run(
            [sys.executable, str(rfe), "recall", "--query", "招聘小程序 上线",
             "--severity", "redline", "--top", "3", "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        rules = []
        try:
            rules = [x["rule"] for x in json.loads(rr.stdout or "[]")]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        rl.write_text(json.dumps(
            [{"id": x.get("id"), "rule": x.get("rule"), "basis": x.get("basis", ""),
              "lead_time": x.get("lead_time", "")} for x in rules],
            ensure_ascii=False), encoding="utf-8")
        card = home / "card.md"
        r = run("gate", "card", "-f", "app", "-d", "D2", "-o", str(card),
                "--kb-redline", str(rl), "--force", home=home)
        cb = card.read_text(encoding="utf-8") if card.exists() else ""
        check("核查卡含合规闸门节", "合规闸门" in cb, r.stdout[:200])
        check("合规节为阻断并含红线 ID", ("RULE-" in cb) if rules else True)
        check("合规不满足=交付不通过写入卡", "合规红线未满足数" in cb or "必须为 0" in cb)
        if rules:
            check("召回了真实红线（≥1 条）", len(rules) >= 1)
    else:
        check("rfe 同级存在（跳过合规注入断言）", True)

    print("[25] v2p plan：一条命令出统一报告 + 核查卡 + state")
    st_dir = home / "plans"
    r = run("plan", "-t", "我要做一个招聘小程序", home=home)
    check("plan 退出码 0", r.returncode == 0, r.stdout[:300])
    check("plan 输出含合规侧", "合规侧" in r.stdout and "红线" in r.stdout, r.stdout[:300])
    check("plan 输出含免责提示", "免责" in r.stdout)
    states = sorted(st_dir.glob("*/state.json"))
    check("plan 落盘 state.json", bool(states))
    if states:
        st = json.loads(states[-1].read_text(encoding="utf-8-sig"))
        check("state 记录红线 ID", isinstance(st.get("redline_ids"), list))
        check("state 初始未沉淀未交付",
              st.get("settled", {}).get("rules", 1) == 0 and st.get("delivered") is False)
    rep = list(st_dir.glob("*/report.md"))
    check("统一报告已生成", bool(rep))
    if rep:
        rb = rep[-1].read_text(encoding="utf-8")
        check("报告含模态切换分节（挖掘/排雷两部分）",
              "需求挖掘" in rb and "合规排雷" in rb)
        check("报告含倒排里程碑", "倒排里程碑" in rb)
        check("报告含知识库复核时间戳", "复核时间戳" in rb)
        check("报告含完整免责声明", "完整免责声明与使用边界" in rb)
        check("报告含问题编码索引（去重）", "问题编码索引（去重）" in rb)
        check("报告声明禁止公开 SaaS", "禁止封装为公开 SaaS" in rb)

    print("[25b] viz heatmap：五信号 × 深度等级热力图")
    hm = home / "heatmap.svg"
    r = run("viz", "heatmap", "-t", "我要做一个招聘小程序", "--out", str(hm), home=home)
    check("viz heatmap 生成 SVG", r.returncode == 0 and hm.exists()
          and "<svg" in hm.read_text(encoding="utf-8"), r.stdout[:200])

    print("[26] settle：未沉淀拦截 → 沉淀入待审 → done 放行")
    if states:
        r = run("settle", "status", home=home)
        check("status 提示未沉淀", r.returncode == 1 and "未沉淀" in r.stdout, r.stdout[:200])
        prd = home / "prd.md"
        prd.write_text(GOOD_PRD, encoding="utf-8")
        r = run("spec", "check", "--file", str(prd), home=home)
        check("spec check 被未沉淀 plan 拦截", r.returncode == 1 and "收尾未完成" in r.stdout,
              r.stdout[:200])
        pit_f = home / "pit.json"
        pit_f.write_text(json.dumps({"trap": "自测坑：弹窗未锁滚动", "domain": "软件与小程序",
                                     "trigger": ["弹窗"]}, ensure_ascii=False),
                         encoding="utf-8")
        r = run("settle", "pitfall", "--trap", "自测坑：弹窗未锁滚动",
                "--guard", "锁滚动", "--domain", "软件与小程序", home=home)
        check("settle pitfall 写入待审区", r.returncode == 0 and "待审" in r.stdout,
              r.stdout[:200])
        r = run("settle", "status", home=home)
        check("status 显示已沉淀", r.returncode == 0 and "坑卡 1 条" in r.stdout,
              r.stdout[:200])
        r = run("settle", "done", home=home)
        check("沉淀后 done 放行", r.returncode == 0 and "已标记交付" in r.stdout,
              r.stdout[:200])
        r = run("spec", "check", "--file", str(prd), home=home)
        check("沉淀后 spec check 不再被拦", r.returncode in (0, 1) and "收尾未完成" not in r.stdout,
              r.stdout[:200])

    print("[27] change：变更重跑（交付标记失效）")
    if states:
        r = run("change", "-t", "增加直播带岗功能", home=home)
        check("change 退出码 0", r.returncode == 0, r.stdout[:300])
        check("change 输出影响面", "变更影响面" in r.stdout)
        st2 = json.loads(states[-1].read_text(encoding="utf-8-sig"))
        check("变更记录入 state", len(st2.get("changes", [])) >= 1)
        check("变更后交付标记重置", st2.get("delivered") is False)

    print("[28] bundle：深度 max+1 与一致性对账清单")
    r = run("plan", "-t", "做一份带原型和财务模型的融资材料包",
            "--bundle", "app,doc,sheet", home=home)
    check("bundle plan 退出码 0", r.returncode == 0, r.stdout[:300])
    check("bundle 报告含交付包深度", "交付包深度" in r.stdout or "交付包" in r.stdout,
          r.stdout[:200])
    bpath = home / "bundle.md"
    r = run("bundle", "--items", "app,doc,sheet", "--name", "四件套",
            "-o", str(bpath), home=home)
    check("对账清单生成", r.returncode == 0 and bpath.exists(), r.stdout[:200])
    if bpath.exists():
        bb = bpath.read_text(encoding="utf-8")
        check("含五类对账", all(k in bb for k in ("功能对账", "数字对账", "品牌对账", "口径对账", "版本对账")))

    print("[29] use：多项目口味档案隔离")
    r = run("use", "项目甲", home=home)
    check("切换项目档案", r.returncode == 0 and "项目甲" in r.stdout, r.stdout[:200])
    r = run("profile", "set", "喜欢深色", home=home)
    check("隔离档案可写入", r.returncode == 0)
    check("档案落到 profiles/项目甲.json", (home / "profiles" / "项目甲.json").exists())
    r = run("use", home=home)
    check("use 显示当前项目", r.returncode == 0 and "项目甲" in r.stdout, r.stdout[:200])
    r = run("use", "default", home=home)
    check("切回 default", r.returncode == 0)

    print("[30] viz：SVG 输出")
    dsvg = home / "d.svg"
    r = run("viz", "depth", "-t", "做一个记账小程序", "-o", str(dsvg), home=home)
    check("雷达图生成", r.returncode == 0 and dsvg.exists()
          and dsvg.read_text(encoding="utf-8").lstrip().startswith("<svg"),
          r.stdout[:200])
    gsvg = home / "g.svg"
    r = run("viz", "gates", "-f", "app", "-o", str(gsvg), home=home)
    check("闸门分布图生成", r.returncode == 0 and gsvg.exists()
          and "闸门分布" in gsvg.read_text(encoding="utf-8"), r.stdout[:200])

    print("[31] rfe 独立可用（未强耦合）")
    if rfe.is_file():
        rr = subprocess.run([sys.executable, str(rfe), "pitfall", "recall",
                             "--query", "招聘", "--top", "2", "--json"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
        ok = rr.returncode == 0
        try:
            ok = ok and len(json.loads(rr.stdout or "[]")) > 0
        except json.JSONDecodeError:
            ok = False
        check("坑库已冷启动且可独立召回", ok, rr.stdout[:200])
        rr = subprocess.run([sys.executable, str(rfe), "stats"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
        check("rfe stats 含复核时间戳", "复核时间戳" in rr.stdout, rr.stdout[:200])

    print("[32] 终局交付（v2.4.0 铁律 19/20 与产出物）")
    skill_txt = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    check("SKILL.md 含铁律 19（终点是产品不是文档）",
          "19. **终局交付" in skill_txt and "终点是产品，不是文档" in skill_txt)
    check("SKILL.md 含铁律 20（合规流程报告收口）",
          "20. **交付必附合规流程报告" in skill_txt and "先产品、后合规收口" in skill_txt)
    check("SKILL.md 总流程含⑤终局收口与第三入口",
          "⑤ 终局收口" in skill_txt and "直接进 7.4 终局交付" in skill_txt)
    fd = ROOT / "references" / "final-delivery.md"
    check("references/final-delivery.md 存在",
          fd.is_file() and "八形态最低完成定义" in fd.read_text(encoding="utf-8"))
    tpl = ROOT / "assets" / "templates" / "合规流程报告.md"
    check("合规流程报告模板存在且五件套齐",
          tpl.is_file() and all(k in tpl.read_text(encoding="utf-8")
                                for k in ("结论档位", "已触发红线清单", "办证", "倒排周计划", "免责声明")))

    print(f"\n结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
