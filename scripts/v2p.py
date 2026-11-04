#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v2p.py — 模糊需求挖掘与产出生成器（Vague to Product）CLI

零依赖，仅用 Python 标准库（3.8+）。

设计要点：挖掘深度不写死。由「产出形态 × 深度信号」动态决定轮次与维度。
  形态 forms     8 类产出（软件/文档/表格/图形/3D/音视频/资料/实物）
  维度 dims      8 个可插拔追问维度（目标/场景/对象/约束/质量/边界/交付/演化）
  深度 depth     5 级（D0 直达 ~ D4 分层深挖），由 5 个信号打分得出

子命令：
  route -t <模糊想法>              判定形态 + 初判深度 + 该形态必挖点
  depth --impact 2 --unknown 1 ... 按信号算深度等级与轮次预算
  ask --form doc --depth D2 --round 2 [--done goal,scene]
                                   按形态×深度×轮次取题（跳过已覆盖维度）
  forms                            列出全部形态与必挖点
  profile ...                      口味档案（show / set / veto / habit / cat / shape）
  spec new --title X [--brief]     生成 PRD 骨架 / 通用产出定型卡
  spec check --file X [--form doc] 检查能否交付
  stats                            档案与题库统计

环境变量：
  V2P_HOME   档案目录（默认 ~/.workbuddy/v2p）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
TPL_PRD = SKILL_ROOT / "templates" / "一页纸PRD.md"
TPL_BRIEF = SKILL_ROOT / "templates" / "产出定型卡.md"


def _home() -> Path:
    env = os.environ.get("V2P_HOME", "").strip()
    base = Path(env) if env else Path.home() / ".workbuddy" / "v2p"
    base.mkdir(parents=True, exist_ok=True)
    return base


def current_project() -> str:
    """当前项目档案名：环境变量 V2P_PROJECT > current_project 文件 > default。
    多项目并行时口味互不串数据（v2.2.0）。"""
    env = os.environ.get("V2P_PROJECT", "").strip()
    if env:
        return env
    f = _home() / "current_project"
    if f.exists():
        return f.read_text(encoding="utf-8").strip() or "default"
    return "default"


def _profile_path() -> Path:
    proj = current_project()
    if proj == "default":
        legacy = _home() / "taste-profile.json"
        if legacy.exists():
            return legacy          # 兼容 v2.1 及更早的单档案
        p = _home() / "profiles" / "default.json"
    else:
        p = _home() / "profiles" / f"{proj}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


EMPTY_PROFILE = {
    "version": 2,
    "profile": {
        "偏好": {},
        "被否决的方案": [],
        "常做品类": [],
        "表述习惯": "",
        "常用形态": {},
        "深度习惯": {},
    },
}


def load_profile() -> dict:
    p = _profile_path()
    if not p.exists():
        return json.loads(json.dumps(EMPTY_PROFILE))
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return json.loads(json.dumps(EMPTY_PROFILE))
    base = json.loads(json.dumps(EMPTY_PROFILE))
    prof = data.get("profile", data)
    if isinstance(prof, dict):
        for k, v in prof.items():
            if k in base["profile"]:
                base["profile"][k] = v
    return base


def save_profile(data: dict) -> None:
    _profile_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# ================================================================ 形态层
# kw 命中即计分；must 为必挖维度（不挖到就是猜）；trap 为该形态最常见的错配

FORMS = {
    "app": {
        "name": "软件应用",
        "range": "小程序 / 网页 / H5 / 桌面工具 / App / 游戏 / 插件 / 自动化脚本",
        "kw": ["app", "App", "APP", "小程序", "网页", "网站", "系统", "软件", "工具",
               "平台", "H5", "游戏", "插件", "脚本", "自动化", "后台", "客户端",
               "计算器", "管理", "打卡", "预约", "商城", "助手"],
        "must": ["object", "quality", "boundary"],
        "common_depth": "D4",
        "trap": "用户说 App，实际只需要一个能打开的单页；差 5 倍成本与 1 个月备案。",
    },
    "doc": {
        "name": "文档与报告",
        "range": "报告 / 方案 / 商业计划书 / 合同 / 说明书 / 手册 / 白皮书 / 公文 / 简历",
        "kw": ["文档", "报告", "方案", "计划书", "bp", "BP", "商业计划", "合同", "协议",
               "说明书", "手册", "白皮书", "公文", "简历", "策划", "总结", "申请",
               "可行性", "研究", "标书", "报价单", "文案", "通知", "通告", "纪要",
               "邮件", "汇报", "提纲", "议程", "函", "制度", "章程", "复盘"],
        "must": ["object", "quality", "boundary"],
        "common_depth": "D2",
        "trap": "把文档当软件做 PRD，列一堆 P0 功能——文档的验收标准是「读者能据此做决定」。",
    },
    "sheet": {
        "name": "表格与数据",
        "range": "台账 / 报表 / 预算模型 / 对比矩阵 / 数据清洗 / 数据集",
        "kw": ["表格", "excel", "Excel", "台账", "预算", "报表", "对账", "数据表",
               "清单", "统计表", "矩阵", "数据集", "csv", "CSV", "透视", "公式"],
        "must": ["object", "quality", "constraint"],
        "common_depth": "D2",
        "trap": "先画表头再想用途——一行代表什么没定，后面每个公式都会返工。",
    },
    "visual": {
        "name": "图形与图像",
        "range": "图表 / 信息图 / 海报 / 插画 / LOGO / 封面 / UI 界面 / 主视觉",
        "kw": ["图", "图表", "海报", "插画", "logo", "LOGO", "标志", "封面", "界面",
               "UI", "ui", "主视觉", "头图", "banner", "配色", "图标", "信息图",
               "排版", "照片", "绘画", "漫画"],
        "must": ["object", "quality", "delivery"],
        "common_depth": "D2",
        "trap": "只说「好看点」，不给尺寸与使用场景——尺寸错一次，全部重做。",
    },
    "model3d": {
        "name": "3D 模型与空间",
        "range": "产品模型 / 场景 / 建筑空间 / 打印件 / 游戏资产 / 结构件",
        "kw": ["3d", "3D", "模型", "建模", "三维", "渲染", "stl", "STL", "obj", "OBJ",
               "blender", "Blender", "cad", "CAD", "打印", "开模", "展厅", "空间设计"],
        "must": ["object", "quality", "delivery"],
        "common_depth": "D2",
        "trap": "不问「拿去干什么」就开做——打印件要封闭实体，游戏要低面数，两者的模型不通用。",
    },
    "media": {
        "name": "音视频",
        "range": "短视频 / 漫剧 / 动画 / 宣传片 / 播客 / 口播 / 配乐 / 直播脚本",
        "kw": ["视频", "短片", "动画", "漫剧", "短视频", "音频", "播客", "配音", "配乐",
               "直播", "剪辑", "分镜", "口播", "宣传片", "抖音", "视频号", "b站"],
        "must": ["object", "quality", "boundary"],
        "common_depth": "D2",
        "trap": "先定「要 3 分钟」再做内容——平台和用途决定时长，反过来会白做。",
    },
    "material": {
        "name": "资料与知识",
        "range": "资料汇编 / 知识库 / 课程 / 教材 / 素材库 / 档案整理 / 笔记体系",
        "kw": ["资料", "知识库", "课程", "教材", "素材", "档案", "整理", "汇编",
               "笔记", "百科", "手册", "规范", "文档库", "培训", "教程", "清单"],
        "must": ["object", "boundary", "evolution"],
        "common_depth": "D2",
        "trap": "只做分类不做检索——不解决「3 秒找到」，整理完还是没人用。",
    },
    "physical": {
        "name": "实物与服务",
        "range": "硬件 / 包装 / 打样 / 模具 / 场地活动 / 服务流程 SOP / 门店",
        "kw": ["实物", "硬件", "打样", "开模", "模具", "包装", "样品", "生产", "量产",
               "采购", "物料", "bom", "BOM", "活动", "落地", "门店", "sop", "SOP",
               "流程", "现场", "展台", "装修"],
        "must": ["object", "constraint", "quality"],
        "common_depth": "D3",
        "trap": "不问数量级就报价——1 件打样和 1000 件量产，工艺路线完全不同。",
    },
    "unknown": {
        "name": "未定形态",
        "range": "用户只给了感觉，还没说清要什么",
        "kw": [],
        "must": ["object"],
        "common_depth": "D2",
        "trap": "急着归类——形态错了，后面所有问题都在错的方向上深挖。第一轮只解决「要什么形态」。",
    },
}

DIMS = ["goal", "scene", "object", "constraint", "quality", "boundary",
        "delivery", "evolution"]
DIM_NAME = {
    "goal": "目标", "scene": "场景", "object": "对象", "constraint": "约束",
    "quality": "质量", "boundary": "边界", "delivery": "交付", "evolution": "演化",
}

# ================================================================ 深度层
# 五个信号，各 0–2 分，合计 0–10。分数越高，说明挖得越深才安全。

SIGNALS = [
    ("impact", "影响半径", [
        (0, "只影响自己"),
        (1, "影响少数他人（客户/同事）"),
        (2, "影响公众 / 涉及钱 / 涉及法律"),
    ]),
    ("reversi", "不可逆性", [
        (0, "改起来便宜（草稿/原型）"),
        (1, "改动有成本（已给人看过）"),
        (2, "改不动（已发布/已投产/已开模/已签约）"),
    ]),
    ("unknown", "未知量", [
        (0, "用户很清楚要什么"),
        (1, "部分模糊，说得清场景说不清做法"),
        (2, "用户自己也不知道，只有感觉"),
    ]),
    ("complex", "复杂度", [
        (0, "单一静态产出"),
        (1, "多部件/多素材/多来源"),
        (2, "交互系统/多角色/多约束联动"),
    ]),
    ("reuse", "复用性", [
        (0, "一次性，用完就丢"),
        (1, "自用，会反复用"),
        (2, "给别人用 / 要卖 / 要长期维护"),
    ]),
]
SIGNAL_LABEL = {k: n for k, n, _ in SIGNALS}

LEVELS = [
    (0, 1, "D0", "直达", 1, 1, "信息已够，先给一版再看反应；不要问，直接做。"),
    (2, 3, "D1", "标准", 2, 2, "两轮：定位 + 边界。适合单一形态、自用、改起来便宜。"),
    (4, 5, "D2", "深挖", 3, 5, "三到五轮：加对象层与质量层。适合要交给别人、有多约束。"),
    (6, 7, "D3", "深度", 5, 8, "五到八轮：加约束层与演化层，逐项验红线。适合涉钱、涉合规、要维护。"),
    (8, 10, "D4", "分层深挖", 8, 99, "不限轮次，分批推进：每 3 轮出一次阶段产出给用户验收，再继续。"),
]
LEVEL_INDEX = {row[2]: row for row in LEVELS}


def level_of(score: int):
    for lo, hi, code, name, rmin, rmax, act in LEVELS:
        if lo <= score <= hi:
            return code, name, rmin, rmax, act
    return "D4", "分层深挖", 8, 99, LEVELS[-1][6]


def infer_form(text: str):
    """返回 (形态键, 命中词列表, 次选形态键)。全不中 → unknown。"""
    scores = []
    for key, f in FORMS.items():
        hits = [k for k in f["kw"] if k in text]
        if hits:
            scores.append((len(hits), key, hits))
    if not scores:
        return "unknown", [], ""
    scores.sort(reverse=True)
    top_n, top_key, top_hits = scores[0]
    second = scores[1][1] if len(scores) > 1 and scores[1][0] >= top_n - 1 else ""
    return top_key, top_hits, second


FORM_DEFAULT_COMPLEX = {"doc": 0, "sheet": 0, "visual": 0, "material": 1,
                        "media": 1, "model3d": 1, "app": 2, "physical": 2,
                        "unknown": 1}

_INFER_RULES = {
    "impact": [
        (2, ["支付", "交易", "资金", "多人", "平台", "公众", "监管", "法律", "签约",
             "投资", "融资", "合规", "资质", "放款", "医疗", "药品"]),
        (1, ["客户", "对外", "上线", "发布", "团队", "公司", "收费", "卖", "领导",
             "汇报", "评审"]),
    ],
    "reversi": [
        (2, ["量产", "开模", "投产", "已上架", "已发布", "印刷", "已签", "排期已定"]),
        (1, ["定稿", "已给客户", "已报批", "交期", "打样", "打板", "试产", "送审"]),
    ],
    "unknown": [
        (2, ["不知道", "随便", "看着办", "都行", "大概", "类似", "感觉", "有点",
             "帮我看看", "你定", "想法"]),
    ],
    "reuse": [
        (2, ["长期", "每天", "持续", "维护", "卖给", "对外", "复用", "团队", "运营"]),
        (0, ["一次", "临时", "就用一次", "这次", "试试"]),
    ],
}


def infer_signals(text: str, form: str) -> dict:
    """从原话粗判信号；用户可用 --impact 等显式覆盖。"""
    sig = {"impact": 0, "reversi": 0, "unknown": 1, "reuse": 1,
           "complex": FORM_DEFAULT_COMPLEX.get(form, 1)}
    for key, rules in _INFER_RULES.items():
        for score, kws in rules:
            if any(k in text for k in kws):
                sig[key] = max(sig.get(key, 0), score)
    # 原话够长且具体 → 未知量下调
    if sig["unknown"] >= 1 and len(text) >= 60 and not any(
            k in text for k in ["不知道", "随便", "看着办", "都行"]):
        sig["unknown"] = 0
    return sig


def total_score(sig: dict) -> int:
    return sum(int(sig.get(k, 0)) for k, _, _ in SIGNALS)


# ================================================================ 题库层
# 每题：dim（维度）、q（问题）、opts（选项+代价）、rec（推荐项）、hint

def Q(dim, q, opts, rec=0, hint="", multi=False):
    return {"dim": dim, "q": q, "opts": opts, "rec": rec, "hint": hint, "multi": multi}


UNIVERSAL = [
    Q("goal", "这东西做出来，你第一件事要拿它干嘛？", [
        ("自己用，解决自己的麻烦", "零成本可先做"),
        ("给一个具体的人用", "要问清他的习惯"),
        ("给客户/合作方用", "要能对外展示"),
        ("卖给一批人（要商业化）", "需资质+运营，成本最高"),
        ("存档备查，不一定有人用", "按规范做，别过度设计"),
    ], 0),
    Q("scene", "上一次你需要这东西，是什么时候？当时怎么解决的？", [
        ("说得出具体某天和细节", "需求真实，照这个场景做"),
        ("只记得大概，说不清细节", "需要往下追一层"),
        ("想不起有这回事", "警惕：可能不是真需求，先做最小验证"),
        ("这是全新的，没发生过", "按推演做，先小成本试"),
    ], 0),
    Q("delivery", "最终交给谁、以什么方式交？", [
        ("只有我自己，能用就行", "最省，可跳过格式要求"),
        ("交给一个具体的人（客户/领导）", "要问他的验收习惯"),
        ("发给一群人/客户群", "要统一格式，不能有个人痕迹"),
        ("公开发布/上架", "要过审、要版权、要排版"),
    ], 0),
    Q("constraint", "什么时候必须拿到？", [
        ("今天/明天就要", "先出可用草稿，别追求完整"),
        ("这周", "能做到 80%"),
        ("这个月", "可以迭代两轮"),
        ("不急，先做对", "先深挖再动手"),
    ], 0),
]

FORM_Q = {
    "unknown": [
        Q("object", "你要的最终东西，最接近下面哪一类？", [
            ("能用、能点的软件（小程序/网页/App）", "要定功能与数据"),
            ("一份文档或报告", "要定读者与结论"),
            ("一张表 / 一套数据", "要定行与字段"),
            ("图（海报/图表/界面/插画）", "要定用途与尺寸"),
            ("3D 模型 / 空间", "要定用途与精度"),
            ("音视频", "要定平台与时长"),
            ("一堆资料的整理 / 知识库", "要定结构与检索"),
            ("实物、活动或一套流程", "要定数量与场地"),
        ], 0, hint="这一题不答，后面所有问题都可能白问。"),
        Q("object", "它交出去以后，别人拿它干什么？", [
            ("照着做（执行）", "要步骤与标准"),
            ("做决定（批不批/买不买）", "要结论与依据"),
            ("看个效果（演示/说服）", "要好看与抓重点"),
            ("存着备用（查/追溯）", "要完整与好检索"),
            ("只是自己看着舒服", "按自己习惯来"),
        ], 0),
    ],
    "app": [
        Q("object", "它最核心的那一个动作是什么？（只选一个）", [
            ("录入/记录一条信息", "表单要极简，3 个字段以内"),
            ("查到一个结果", "搜索与筛选是重点"),
            ("算一个数/出一张表", "计算逻辑要先定死"),
            ("看一个状态/进度", "展示与提醒是重点"),
            ("把东西发给别人", "分享链路与格式是重点"),
            ("匹配两方（发布+接单）", "要做双边与审核，成本翻倍"),
        ], 0),
        Q("object", "数据最终存在哪里、谁能看到？", [
            ("只在这台设备，不联网", "最简单，可离线"),
            ("要跨设备打开", "要账号或分享链接"),
            ("要给多人看/多人改", "要权限与冲突处理"),
            ("要长期留存、不能丢", "要备份与导出"),
        ], 0),
        Q("constraint", "谁来维护它？", [
            ("我自己，改文件就行", "不做后台，成本最低"),
            ("要能自己点着改", "要做管理页"),
            ("一次做完就不动", "数据写死也可以"),
            ("自动化跑，不用人管", "要做定时任务与异常处理"),
        ], 0),
        Q("quality", "什么程度算「能用」？", [
            ("3 步内走完主流程", "信息架构优先"),
            ("手机上能点、能转发", "要做响应式与分享"),
            ("断网也能用", "要本地存储"),
            ("能导出给别人", "要文件格式与兼容"),
        ], 0),
        Q("boundary", "下面哪些你明确不要？", [
            ("不要注册登录", "省账号体系与隐私同意"),
            ("不要在线支付", "省支付资质与分账"),
            ("不要多人协作", "省权限与冲突"),
            ("不要消息推送", "省模板消息与订阅"),
            ("不要后台管理", "内容我直接改文件"),
        ], 0, multi=True),
        Q("scene", "你会在什么场景下打开它？", [
            ("电脑前，一次用十几分钟", "可以做重一点"),
            ("手机上，边走边用，几秒钟", "要大按钮、少输入"),
            ("当着别人的面演示", "界面要好看，容错要高"),
            ("每天固定时间批量处理", "要能导入导出"),
        ], 0),
        Q("evolution", "以后会不会加人、加数据、加功能？", [
            ("永远只有我用", "怎么快怎么来"),
            ("以后可能给两三个人", "留个账号位就行"),
            ("会持续加功能", "结构要留扩展余地"),
            ("要卖给别人用", "现在就得想多租户与合规"),
        ], 0),
    ],
    "doc": [
        Q("object", "读者读完这份文档，要做什么决定或动作？", [
            ("批预算/批立项", "要成本与收益，结论放最前"),
            ("签字/盖章", "要条款清楚、责任分明"),
            ("投钱/投资", "要市场、模型、退出"),
            ("照着执行", "要步骤、责任人、时间"),
            ("存档/备查", "要完整、可追溯"),
        ], 0),
        Q("object", "读者最想知道的那一件事是什么？", [
            ("这事能不能做", "先给结论与前提"),
            ("要花多少钱/多久", "先给数字与区间"),
            ("风险在哪", "先给红线与最坏情况"),
            ("具体怎么做", "先给路径与清单"),
            ("为什么是它而不是别的", "先给对比"),
        ], 0),
        Q("object", "篇幅和深度要多少？", [
            ("1 页纸，只要结论", "写多了一定没人看"),
            ("3–5 页，结论+要点", "最常见"),
            ("10 页以上，要完整", "要目录与附录"),
            ("越全越好，我要拿去交差", "按评审标准凑章节"),
        ], 0),
        Q("quality", "什么算过关？", [
            ("能被直接签字/提交", "格式与用语要正式"),
            ("能过评审会", "要经得起追问，数据要有来源"),
            ("能拿去讲", "要有图和一句话结论"),
            ("我自己看得懂就行", "不用讲究格式"),
        ], 0),
        Q("constraint", "有没有必须遵守的模板、口径或术语？", [
            ("有，我给你模板", "严格按模板，不加不减"),
            ("要按行业/监管惯例", "按该行业通用结构写"),
            ("要引用权威来源", "每个数字都要有出处"),
            ("没有，你看着办", "用通用结构"),
        ], 0),
        Q("delivery", "最终以什么形式交？", [
            ("Word，要能打印签字", "注意页边距与页码"),
            ("PDF，发人不让改", "注意字体嵌入"),
            ("PPT，要讲", "一页一个观点"),
            ("网页/在线文档，能协作", "注意权限"),
        ], 0),
        Q("boundary", "哪些内容绝对不能写进去？", [
            ("不写未核实的数字", "宁可留空标注待核"),
            ("不写内部成本/毛利", "对外版本要脱敏"),
            ("不点名具体客户/员工", "用代称"),
            ("不写承诺性表述（保证/一定）", "改为条件式"),
            ("没有限制", "正常写"),
        ], 0, multi=True),
    ],
    "sheet": [
        Q("object", "这张表里，一行代表什么？", [
            ("一笔收支/一张单", "要日期、金额、对方、备注"),
            ("一个人/一个客户", "要唯一标识，防重复"),
            ("一个项目/一个订单", "要状态字段"),
            ("一天/一个月", "要时间序列，方便看趋势"),
            ("一个商品/SKU", "要规格与库存"),
        ], 0, hint="这一题不定，后面每个公式都会返工。"),
        Q("object", "要算出哪些数？", [
            ("合计/小计", "最基础"),
            ("占比/结构", "要分类维度"),
            ("同比/环比/趋势", "要历史数据"),
            ("排名/TOP N", "要排序规则"),
            ("不用算，只是记录", "可以极简"),
        ], 0),
        Q("object", "数据从哪来、怎么进表？", [
            ("我手工一条条填", "表单要顺手，能回车下一条"),
            ("从别的系统导出再粘", "要能容错、清洗"),
            ("别人填，我汇总", "要防错填，加校验"),
            ("自动抓/自动同步", "要做接口或脚本"),
        ], 0),
        Q("quality", "谁看这张表，他看什么？", [
            ("我自己看总数", "一屏能看到关键数"),
            ("老板看趋势", "要图表"),
            ("会计要对平", "要能勾稽、不能有尾差"),
            ("客户看明细", "要能导出成他习惯的格式"),
        ], 0),
        Q("constraint", "数据量大概多少？", [
            ("几十行", "手工都行"),
            ("几百行", "要筛选与冻结窗格"),
            ("上万行", "要数据库或透视"),
            ("不确定，可能暴涨", "先按可扩展设计"),
        ], 0),
        Q("boundary", "结构以后要不要改？", [
            ("列固定，不改", "可以写死公式"),
            ("以后要加列", "公式要留余量"),
            ("要多表关联", "要设计主键与关联"),
            ("要给别人用，不能让他改坏", "要保护与说明"),
        ], 0),
        Q("delivery", "最终要什么？", [
            ("一个能直接填的 xlsx", "带下拉与校验"),
            ("一张能打印的报表", "排版优先"),
            ("一份可导入系统的 CSV", "字段名要严格"),
            ("一套模板+填写说明", "别人要照着填"),
        ], 0),
    ],
    "visual": [
        Q("object", "这张图最终用在哪？", [
            ("手机竖屏（朋友圈/公众号/短视频封面）", "9:16 或 3:4"),
            ("PPT/网页内页（横版）", "16:9"),
            ("印刷海报/展架（A4/A3）", "要出血与 CMYK"),
            ("头像/图标（正方形）", "小尺寸要能看清"),
            ("产品界面（UI）", "要成套，不只是单张"),
        ], 0, hint="尺寸与场景不先定，做得再好看也会被废掉。"),
        Q("quality", "风格参照哪一个？", [
            ("极简、留白多、黑白灰", "靠排版不靠装饰"),
            ("国潮/传统纹样", "要纹样素材与配色"),
            ("科技感、深色、渐变", "注意别太花"),
            ("手绘/插画风", "要统一笔触"),
            ("就按我给的参考图", "以参考为准，别自由发挥"),
        ], 0),
        Q("object", "要不要可编辑？", [
            ("只要一张图片", "最快"),
            ("要能改字", "要留文字层或给可编辑文件"),
            ("要分层源文件", "文件大，但能二次改"),
            ("要能换配色/换尺寸复用", "要做成模板"),
        ], 0),
        Q("boundary", "有没有不能出现的元素？", [
            ("不用真人照片", "避免肖像权"),
            ("不用特定品牌色/字体", "避免侵权与混淆"),
            ("不放二维码/联系方式", "视平台规则"),
            ("文字不能用某几种字体", "商用字体要授权"),
            ("没有限制", "正常做"),
        ], 0, multi=True),
        Q("delivery", "这次要几张？", [
            ("先出 1 张看方向", "定了再批量"),
            ("一组 3–5 张", "要统一风格"),
            ("成套 10 张以上", "要先定规范再铺"),
            ("要能用于印刷的成品文件", "出血、300dpi"),
        ], 0),
        Q("object", "画面里必须出现哪些信息？", [
            ("只要一个主标题", "字要大"),
            ("标题+一句说明", "有主次"),
            ("标题+说明+联系方式", "信息多，要分区"),
            ("是一组数据要可视化", "先定图表类型"),
        ], 0),
    ],
    "model3d": [
        Q("object", "这个模型拿去干什么？", [
            ("只是看看/演示", "精度中等即可"),
            ("渲染出效果图", "要材质与光照"),
            ("3D 打印出实物", "要封闭实体、壁厚"),
            ("进游戏/引擎", "要低面数、UV、骨骼"),
            ("开模/生产", "要工程精度与公差"),
        ], 0, hint="用途决定拓扑。不问这题就开做，八成交付时不能用。"),
        Q("object", "尺寸和比例有依据吗？", [
            ("有实物尺寸，我提供", "按图做，标明单位"),
            ("按场景估一个合理值", "要标明是估算"),
            ("要放进某个空间（房间/展台）", "要参考环境尺寸"),
            ("无所谓，好看就行", "自由发挥"),
        ], 0),
        Q("quality", "做到什么程度？", [
            ("白模，能看出形状", "最快"),
            ("带材质贴图", "要配色与纹理"),
            ("要能动（动画/绑定）", "成本翻倍"),
            ("要照片级渲染图", "要灯光与后期"),
        ], 0),
        Q("boundary", "哪些部分不能改？", [
            ("外形尺寸固定", "只能做内部"),
            ("接口/安装位固定", "要配合现有件"),
            ("内部结构不管，只要外观", "省一半工作"),
            ("品牌元素必须保留", "按 VI 来"),
            ("没有限制", "自由"),
        ], 0, multi=True),
        Q("delivery", "要什么文件？", [
            ("STL/3MF（打印）", "单位是毫米"),
            ("OBJ/FBX（通用/引擎）", "注意面数与轴向"),
            ("STEP/IGES（工程）", "要精确尺寸"),
            ("只要几张渲染图", "不用给源文件"),
        ], 0),
        Q("constraint", "你用什么软件打开它？", [
            ("不知道，给通用的", "给 OBJ + 预览图"),
            ("Blender", "给 .blend"),
            ("CAD（SolidWorks/UG）", "给 STEP"),
            ("切片软件（Cura/Bambu）", "给 STL"),
        ], 0),
    ],
    "media": [
        Q("object", "成片在哪放、给谁看？", [
            ("抖音/视频号（竖屏，划走率高）", "前 3 秒必须抓人"),
            ("B 站/YouTube（横屏，能讲长）", "可以慢热"),
            ("内部培训/汇报", "信息准确优先"),
            ("展会/门店循环播放", "没声音也要看得懂"),
        ], 0, hint="平台先定，时长和节奏才有依据。"),
        Q("object", "多长？", [
            ("15–30 秒", "一个点，不要转折"),
            ("1 分钟", "一个问题+一个答案"),
            ("3 分钟", "能讲一个小故事"),
            ("10 分钟以上", "要分章节"),
        ], 0),
        Q("object", "手上有哪些素材？", [
            ("有完整文稿/脚本", "直接进分镜"),
            ("有素材，没脚本", "先剪结构再补拍"),
            ("什么都没有", "要先写脚本再生成"),
            ("只有参考片，想做成那样", "先拆参考片结构"),
        ], 0),
        Q("quality", "什么算能交？", [
            ("能发出去不丢人", "画质与字幕过关"),
            ("能带来咨询/转化", "要留钩子与行动指引"),
            ("能过平台审核", "避开敏感表述与画面"),
            ("内部看懂就行", "不追求包装"),
        ], 0),
        Q("boundary", "不能出现什么？", [
            ("不出现真人/不用真人声音", "用虚拟形象或配音"),
            ("不用未授权音乐/字体", "用可商用素材"),
            ("不承诺效果/不夸大", "合规表述"),
            ("不出现某品牌/竞品", "避免对比风险"),
            ("没有限制", "正常做"),
        ], 0, multi=True),
        Q("delivery", "要什么交付？", [
            ("成片 MP4", "直接能发"),
            ("分镜脚本+提示词", "我自己生成"),
            ("配音稿+字幕文件", "我自己剪"),
            ("素材包（图/音/片段）", "我后期组装"),
        ], 0),
    ],
    "material": [
        Q("object", "这些资料最终给谁用、解决什么问题？", [
            ("自己查，怕以后忘", "能搜到就行"),
            ("教别人/带新人", "要有顺序与例子"),
            ("给客户看，建立专业感", "要整理得体面"),
            ("存档备查，应对检查", "要完整可追溯"),
        ], 0),
        Q("object", "资料从哪来？", [
            ("我自己写的/积累的", "要归类与去重"),
            ("网上收集的", "要标来源，注意版权"),
            ("纸质/扫描件", "要先 OCR 与校对"),
            ("别人给的，格式很乱", "要先清洗"),
        ], 0),
        Q("object", "按什么结构组织？", [
            ("按主题分类", "最常用"),
            ("按时间线", "适合过程记录"),
            ("按项目/客户", "适合业务"),
            ("按问题（FAQ 式）", "适合查询"),
        ], 0),
        Q("quality", "怎么算好用？", [
            ("3 秒能找到要找的", "要目录+搜索+命名规范"),
            ("新人能自学上手", "要导读与示例"),
            ("能对外发布", "要脱敏与授权"),
            ("我自己不丢就行", "能备份即可"),
        ], 0),
        Q("boundary", "有没有不能公开的内容？", [
            ("有内部信息（成本/客户名单）", "要分层，做两版"),
            ("有个人信息", "要脱敏，注意合规"),
            ("有别人版权的内容", "要标来源或替换"),
            ("都可以公开", "正常整理"),
        ], 0, multi=True),
        Q("evolution", "以后谁维护、多久更新一次？", [
            ("只有我，想起来才更", "结构要简单，别做重"),
            ("团队共用，要有人负责", "要版本与责任人"),
            ("定期更新（每周/每月）", "要固定模板与流程"),
            ("一次做完就不动", "可以做静态文档"),
        ], 0),
    ],
    "physical": [
        Q("object", "最终要交出去的是什么？", [
            ("一个样品/打样", "先验证外观与手感"),
            ("小批量（10–100 件）", "要考虑工艺与良率"),
            ("量产（1000 件以上）", "要模具、认证、供应链"),
            ("一场活动/一次落地", "要场地、流程、人手"),
            ("一套服务流程/SOP", "要角色、动作、标准"),
        ], 0),
        Q("constraint", "有没有硬约束（尺寸/场地/接口/预算）？", [
            ("有，我提供图纸或场地条件", "按条件做"),
            ("有大致预算区间", "先按预算反推方案"),
            ("有交期死线", "先定能做的范围"),
            ("都没有，先看方案", "给两档方案对比"),
        ], 0),
        Q("quality", "什么算合格？", [
            ("能通过安全/强制认证", "要查适用标准"),
            ("客户验收通过", "按验收单做"),
            ("自己能卖得动", "要成本与卖点"),
            ("先看效果，不追求完美", "做最小样"),
        ], 0),
        Q("boundary", "哪些不能碰？", [
            ("不涉及食品接触", "否则要食品级材料与检测"),
            ("不做儿童用品", "否则要 3C 与更严标准"),
            ("不改现有结构", "只能做表面"),
            ("不新增供应商", "用现有料"),
            ("没有限制", "正常做"),
        ], 0, multi=True),
        Q("delivery", "要什么交付物？", [
            ("BOM + 图纸", "能直接询价"),
            ("实物样品", "能上手"),
            ("执行方案（时间/人/物料）", "能落地"),
            ("供应商对比表", "能决策"),
        ], 0),
    ],
}

# 轮次 → 该轮优先维度。深度不同，取到的轮数不同，越深越往后。
ROUND_DIMS = {
    1: ["goal", "scene", "delivery", "constraint"],
    2: ["object", "quality"],
    3: ["boundary", "object"],
    4: ["constraint", "quality"],
    5: ["evolution", "delivery"],
    6: ["object", "boundary"],
    7: ["quality", "constraint"],
    8: ["evolution", "scene"],
}



def _letter(i: int) -> str:
    return chr(65 + i) if i < 26 else f"O{i + 1}"


def _pick_questions(form: str, round_no: int, done: set, limit: int = 4):
    """按轮次优先维度取题，跳过已覆盖维度，避免重复问。

    两条排序法则：
      1) 该形态的必挖维度（must）永远优先——深度再浅也不能漏；
      2) 其次按 ROUND_DIMS 的轮次意图排。
    """
    pool = list(FORM_Q.get(form, []))
    must = set(FORMS.get(form, {}).get("must", []))
    if round_no == 1:
        pool = [q for q in UNIVERSAL if q["dim"] not in done] + [
            q for q in pool if q["dim"] == "object" and q["dim"] not in done]
    else:
        pri = ROUND_DIMS.get(round_no, [])
        rest = [q for q in UNIVERSAL if q["dim"] not in done]
        pool = [q for q in pool if q["dim"] not in done] + rest
        pool.sort(key=lambda q: (
            0 if q["dim"] in must else 1,
            pri.index(q["dim"]) if q["dim"] in pri else 99,
        ))
    out = []
    for q in pool:
        if len(out) >= limit:
            break
        # 同一维度一轮内最多 2 题（避免审问感）
        if sum(1 for x in out if x["dim"] == q["dim"]) >= 2:
            continue
        out.append(q)
    return out


def _print_questions(items, prof: dict) -> None:
    vetoed = set(prof.get("被否决的方案", []))
    for i, item in enumerate(items, 1):
        mark_multi = "（可多选）" if item.get("multi") else ""
        print(f"{i}. {item['q']}{mark_multi}")
        for j, (label, cost) in enumerate(item["opts"]):
            mark = "（推荐）" if j == item.get("rec") else ""
            flag = "  ✗ 你否决过类似方案" if label in vetoed else ""
            print(f"   {_letter(j)}. {label}{mark}　—　代价：{cost}{flag}")
        print(f"   {_letter(len(item['opts']))}. 都不是，我自己填：________")
        if item.get("hint"):
            print(f"   ⓘ {item['hint']}")
        print()


# ---------------------------------------------------------------- route

def cmd_route(args) -> int:
    text = args.text.strip()
    if not text:
        print("请用 -t 传入用户的原话")
        return 2
    form, hits, second = infer_form(text)
    f = FORMS[form]
    sig = infer_signals(text, form)
    score = total_score(sig)
    code, name, rmin, rmax, act = level_of(score)

    conf = "高" if len(hits) >= 2 else ("中" if hits else "低")
    print(f"\n【形态判定】{f['name']}（{form}）　置信：{conf}")
    if hits:
        print(f"  命中：{'、'.join(hits[:6])}")
    print(f"  覆盖：{f['range']}")
    if second:
        print(f"  也可能：{FORMS[second]['name']}——若判定错了，后面全白问，先确认这一条")
    if form == "unknown":
        print("  ⚠ 没识别出形态。第一轮只做一件事：问清「最终要什么形态」。")

    print(f"\n【初判深度】{code} {name}（{score}/10）")
    for k, label, _ in SIGNALS:
        v = int(sig.get(k, 0))
        bar = "█" * v + "·" * (2 - v)
        print(f"  {label:<6} {bar} {v}　{_sig_desc(k, v)}")
    print(f"  依据：{_basis(sig)}")
    print(f"\n【轮次预算】{rmin}–{rmax if rmax < 99 else '∞'} 轮，每轮 ≤4 题")
    print(f"  做法：{act}")

    covered, must, missing = simulate_coverage(form, rmax)
    print(f"\n【覆盖预演】按 {code} 走完，必挖的 {len(must)} 个维度中覆盖 "
          f"{len(must & covered)} 个")
    if missing:
        print(f"  ⚠ 会漏：{'、'.join(DIM_NAME[d] for d in sorted(missing, key=DIMS.index))}")
        print("  → 这不是可靠性问题，是深度不够。要么提一级，要么在交付里显式标「按默认假设处理」。")
    else:
        print("  ✓ 必挖维度全部覆盖，可以按此深度开工。")

    cap = f["common_depth"]
    cap_score = LEVEL_INDEX[cap][0]
    if score < cap_score:
        print(f"\n【为什么没到 {cap}】该形态常规要挖到 {cap}，但你给的信息里缺高风险信号。")
        print("  若实际涉及钱/合规/多人/已发布，请补一句，深度会立刻上调。")
    elif score > cap_score + 1:
        print(f"\n【超出常规】该形态通常到 {cap} 就够，你这次到 {code}。")
        print("  确认高分信号是真的（不是保守估计），否则可以降一级省一半时间。")

    print(f"\n【这形态必须挖到的】")
    for d in f["must"]:
        print(f"  · {DIM_NAME[d]}层——不挖到就是猜")
    print(f"\n【最常见的错配】{f['trap']}")

    print(f"\n【第一轮先问这 4 个】\n")
    _print_questions(_pick_questions(form, 1, set()), load_profile()["profile"])
    print("答完回我一句就行，我会按你的答案重算深度，决定要不要继续挖。")
    return 0


def _sig_desc(key: str, v: int) -> str:
    for k, _, table in SIGNALS:
        if k == key:
            for sc, desc in table:
                if sc == v:
                    return desc
    return ""


def _basis(sig: dict) -> str:
    hi = [SIGNAL_LABEL[k] for k, _, _ in SIGNALS if int(sig.get(k, 0)) == 2]
    mid = [SIGNAL_LABEL[k] for k, _, _ in SIGNALS if int(sig.get(k, 0)) == 1]
    parts = []
    if hi:
        parts.append("高风险信号：" + "、".join(hi))
    if mid:
        parts.append("中等：" + "、".join(mid))
    return "；".join(parts) if parts else "无风险信号"


# ---------------------------------------------------------------- depth

def cmd_depth(args) -> int:
    sig = {}
    for k, _, _ in SIGNALS:
        v = getattr(args, k, None)
        sig[k] = int(v) if v is not None else (1 if k in ("unknown", "reuse", "complex") else 0)
    score = total_score(sig)
    code, name, rmin, rmax, act = level_of(score)

    print(f"\n【深度评分】{score}/10 → {code} {name}")
    for k, label, _ in SIGNALS:
        v = int(sig[k])
        print(f"  {label:<6} {'█' * v + '·' * (2 - v)} {v}　{_sig_desc(k, v)}")
    print(f"\n轮次预算：{rmin}–{rmax if rmax < 99 else '∞'} 轮")
    print(f"做法：{act}")

    rnd = args.round
    if rnd is not None:
        print(f"\n【当前在第 {rnd} 轮】")
        if rnd < rmin:
            print(f"  还差 {rmin - rnd} 轮才到 {code} 的下限。不能收敛——现在定稿等于猜。")
        elif rnd > rmax:
            print(f"  已超 {code} 的常规上限（{rmax} 轮）。继续挖只有一个理由：")
            print("  刚刚出现了新的未知（新人群/新约束/新风险）。没有就别挖了，转定型。")
        else:
            print(f"  在预算内，还剩 {rmax - rnd if rmax < 99 else '不限'} 轮。")
            print("  下一轮必须换维度，同一维度连续问超过 2 轮会变成审问。")
    return 0


# ---------------------------------------------------------------- ask

def cmd_ask(args) -> int:
    form = args.form
    if form not in FORM_Q:
        print(f"未知形态「{form}」，可用：{'、'.join(FORM_Q)}")
        return 2
    depth = args.depth
    if depth not in LEVEL_INDEX:
        print(f"未知深度「{depth}」，可用：{'、'.join(LEVEL_INDEX)}")
        return 2
    rnd = args.round if args.round is not None else (int(args.stage) if args.stage else 1)
    done = {d.strip() for d in (args.done or "").split(",") if d.strip()}
    bad = [d for d in done if d not in DIMS]
    if bad:
        print(f"未知维度：{'、'.join(bad)}；可用：{'、'.join(DIMS)}")
        return 2

    _, _, _, dname, rmin, rmax, act = LEVEL_INDEX[depth]
    f = FORMS[form]
    print(f"\n{FORM_NAME_TAG} {f['name']} · {depth} {dname} · 第 {rnd} 轮"
          f"（预算 {rmin}–{rmax if rmax < 99 else '∞'}）")
    if done:
        print(f"已覆盖维度：{'、'.join(DIM_NAME[d] for d in done) if done else '无'}")
    if rnd > rmax:
        print("⚠ 已超该深度常规轮次。继续挖前请说明「新发现了什么未知」，否则应转定型。")
    print()

    items = _pick_questions(form, rnd, done, limit=args.limit)
    if not items:
        print("该形态的维度已全部覆盖——不再问了，转阶段三定型。")
        print("命令：v2p spec new --title <名称> [--brief]")
        return 0
    _print_questions(items, load_profile()["profile"])
    covered = sorted({q["dim"] for q in items}, key=DIMS.index)
    print(f"本轮覆盖维度：{'、'.join(DIM_NAME[d] for d in covered)}")
    print(f"下一轮建议：--round {rnd + 1} --done {','.join(sorted(done | set(covered), key=DIMS.index))}")
    return 0


FORM_NAME_TAG = "【提问】"


def simulate_coverage(form: str, max_rounds: int):
    """模拟按给定轮数走完，会覆盖哪些维度、漏掉哪些必挖维度。"""
    done: set = set()
    for r in range(1, min(max_rounds, 12) + 1):
        items = _pick_questions(form, r, done, 4)
        if not items:
            break
        done |= {q["dim"] for q in items}
    must = set(FORMS.get(form, {}).get("must", []))
    return done, must, must - done


# ---------------------------------------------------------------- forms

def cmd_forms(args) -> int:
    print("\n八类产出形态（深度上限不同，挖法也不同）\n")
    for key, f in FORMS.items():
        print(f"{f['name']}（{key}）　常规深度 {f['common_depth']}")
        print(f"  覆盖：{f['range']}")
        print(f"  必挖：{'、'.join(DIM_NAME[d] for d in f['must'])}")
        print(f"  错配：{f['trap']}\n")
    print(f"追问维度（8 个，按形态挑，不按固定顺序）：{'、'.join(f'{DIM_NAME[d]}({d})' for d in DIMS)}")
    return 0


# ---------------------------------------------------------------- profile

def cmd_profile_show(args) -> int:
    data = load_profile()["profile"]
    print(f"\n档案位置：{_profile_path()}")
    prefs = data.get("偏好", {})
    if not prefs:
        print("\n偏好：（空）——还没有积累，这次对话后会自动写入")
    else:
        print("\n偏好（count 越高越该当默认值）：")
        for k, v in sorted(prefs.items(), key=lambda x: -(x[1].get("count", 0) if isinstance(x[1], dict) else 0)):
            cnt = v.get("count", 0) if isinstance(v, dict) else 0
            last = v.get("last", "-") if isinstance(v, dict) else "-"
            print(f"  · {k}　×{cnt}　最近 {last}")

    veto = data.get("被否决的方案", [])
    print(f"\n被否决（以后不再推荐）：{'、'.join(veto) if veto else '（空）'}")
    cats = data.get("常做品类", [])
    print(f"常做品类：{'、'.join(cats) if cats else '（空）'}")
    habit = data.get("表述习惯", "")
    print(f"表述习惯：{habit or '（未记录）'}")

    shapes = data.get("常用形态", {})
    if shapes:
        top = sorted(shapes.items(), key=lambda x: -x[1])[:3]
        print(f"常用形态：{'、'.join(f'{k}×{v}' for k, v in top)}")

    depths = data.get("深度习惯", {})
    if depths:
        top = sorted(depths.items(), key=lambda x: -x[1])[:3]
        print(f"深度习惯：{'、'.join(f'{k}×{v}' for k, v in top)}")
        print("  （同一形态反复停在某一级，说明该级是他的舒适区，可以从那里起步）")
    print()
    return 0


def cmd_profile_set(args) -> int:
    data = load_profile()
    one = data["profile"]["偏好"]
    key = args.key.strip()
    if not key:
        print("键不能为空")
        return 2
    cur = one.get(key)
    if isinstance(cur, dict):
        cur["count"] = int(cur.get("count", 0)) + args.count
        cur["last"] = date.today().isoformat()
    else:
        one[key] = {"count": args.count, "last": date.today().isoformat()}
    save_profile(data)
    print(f"已记录偏好「{key}」×{one[key]['count']}（累计）")
    return 0


def cmd_profile_veto(args) -> int:
    data = load_profile()
    veto = data["profile"].setdefault("被否决的方案", [])
    name = args.name.strip()
    if not name:
        print("方案名不能为空")
        return 2
    if name in veto:
        print(f"「{name}」已在否决列表中")
        return 0
    veto.append(name)
    save_profile(data)
    print(f"已否决「{name}」——以后不再推荐（当前否决 {len(veto)} 项）")
    return 0


def cmd_profile_habit(args) -> int:
    data = load_profile()
    data["profile"]["表述习惯"] = args.text.strip()
    save_profile(data)
    print("已记录表述习惯")
    return 0


def cmd_profile_cat(args) -> int:
    data = load_profile()
    cats = data["profile"].setdefault("常做品类", [])
    for c in args.names:
        c = c.strip()
        if c and c not in cats:
            cats.append(c)
    save_profile(data)
    print(f"常做品类：{'、'.join(cats)}")
    return 0


def cmd_profile_shape(args) -> int:
    data = load_profile()
    shapes = data["profile"].setdefault("常用形态", {})
    shapes[args.name] = int(shapes.get(args.name, 0)) + args.count
    save_profile(data)
    print(f"形态「{args.name}」×{shapes[args.name]}")
    return 0


def cmd_profile_depth(args) -> int:
    data = load_profile()
    depths = data["profile"].setdefault("深度习惯", {})
    depths[args.level] = int(depths.get(args.level, 0)) + args.count
    save_profile(data)
    print(f"深度「{args.level}」×{depths[args.level]}")
    return 0


# ---------------------------------------------------------------- spec

def cmd_spec_new(args) -> int:
    title = args.title.strip() or "未命名产出"
    is_brief = args.brief
    tpl = TPL_BRIEF if is_brief else TPL_PRD
    if tpl.exists():
        body = tpl.read_text(encoding="utf-8")
    else:
        body = "# <产出名>\n"
    body = body.replace("# <产品名>", f"# {title}", 1).replace("# <产出名>", f"# {title}", 1)
    body = body.replace("<产品名>", title).replace("<产出名>", title)
    out = Path(args.out) if args.out else Path.cwd() / f"{title}{'-定型卡' if is_brief else '-PRD'}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not args.force:
        print(f"已存在：{out}\n加 --force 覆盖，或用 --out 指定新路径")
        return 1
    out.write_text(body, encoding="utf-8")
    kind = "产出定型卡" if is_brief else "一页纸 PRD"
    print(f"已生成{kind}：{out}")
    print("下一步：填「一句话」和核心段落，其余可留空；填完跑 v2p spec check")
    return 0


REQUIRED_SOFT = ["一句话", "痛点", "用户", "核心场景", "主流程", "MVP 范围", "不做清单"]
REQUIRED_BRIEF = ["一句话", "对象与用途", "必须包含的内容", "不做什么", "验收标准"]


def _spec_check_impl(args) -> int:
    p = Path(args.file)
    if not p.exists():
        print(f"找不到文件：{p}")
        return 2
    raw = p.read_text(encoding="utf-8", errors="replace")
    form = args.form
    soft = form in ("app", "auto") and "## MVP 范围" in raw
    required = REQUIRED_SOFT if soft else REQUIRED_BRIEF
    errs, warns = [], []

    for sec in required:
        if sec not in raw:
            errs.append(f"缺少章节「{sec}」")

    m = re.search(r"##\s*一句话\s*\n+(.+?)(?:\n#|$)", raw, re.S)
    one = (m.group(1).strip() if m else "")
    if not one or ("<" in one and ">" in one):
        errs.append("「一句话」没填：必须是「给谁 + 什么场景 + 什么问题 + 靠什么动作」")
    else:
        for token in ("给", "靠"):
            if token not in one:
                warns.append(f"「一句话」里没出现「{token}」，可能没写清主体或核心动作")

    left = re.findall(r"<[^<>\n]{2,20}>", raw)
    if left:
        warns.append(f"还有 {len(left)} 处占位符未替换：{'、'.join(sorted(set(left))[:5])}")

    if soft:
        p0_rows = [ln for ln in raw.splitlines() if re.match(r"^\|\s*P0\s*\|", ln.strip())]
        n_p0 = len(p0_rows)
        if n_p0 == 0:
            warns.append("没找到 P0 功能行（表格行应以 | P0 | 开头）")
        elif n_p0 > 5:
            errs.append(f"P0 有 {n_p0} 个，超过上限 5 个——说明没有 MVP")
        m2 = re.search(r"##\s*不做清单\s*\n+(.+?)(?:\n##|$)", raw, re.S)
        todo = (m2.group(1).strip() if m2 else "")
        if not todo or todo.count("…") >= 2 or todo.count("...") >= 2:
            errs.append("「不做清单」是空的或只有占位——没有不做清单就没有 MVP")
    else:
        m2 = re.search(r"##\s*不做什么\s*\n+(.+?)(?:\n##|$)", raw, re.S)
        todo = (m2.group(1).strip() if m2 else "")
        if not todo or todo.count("…") >= 2 or todo.count("...") >= 2:
            errs.append("「不做什么」是空的或只有占位——边界没定，交付必然膨胀")
        m3 = re.search(r"##\s*必须包含的内容\s*\n+(.+?)(?:\n##|$)", raw, re.S)
        body = (m3.group(1).strip() if m3 else "")
        if len(body) < 20:
            errs.append("「必须包含的内容」太短——没有内容清单，产出必然缺项")
        if "对象与用途" in raw:
            m4 = re.search(r"##\s*对象与用途\s*\n+(.+?)(?:\n##|$)", raw, re.S)
            u = (m4.group(1).strip() if m4 else "")
            if len(u) < 15:
                warns.append("「对象与用途」写得太短，可能没想清它拿来干什么")

    if "当" not in raw or "应" not in raw:
        warns.append("没看到「当……应……」格式的验收标准")

    print(f"\n检查对象：{p}（{len(raw)} 字符，按{'软件 PRD' if soft else '通用产出定型卡'}校验）")
    if errs:
        print("\n[错误]（必须修掉）")
        for e in errs:
            print(f"  ✗ {e}")
    if warns:
        print("\n[提醒]")
        for w in warns:
            print(f"  ! {w}")
    if not errs and not warns:
        print("  通过：结构完整、边界明确、验收可测。")
    verdict = "未通过" if errs else "通过"
    print(f"\n结论：{verdict}（{len(errs)} 错 / {len(warns)} 提醒）")
    return 1 if errs else 0


def cmd_gate(args) -> int:
    """转交 qgate：v2p gate <子命令>，保持单一入口。"""
    qpath = Path(__file__).resolve().parent / "qgate.py"
    if not qpath.exists():
        print(f"缺少 {qpath}，无法执行质量闸门。")
        return 2
    import importlib.util

    spec = importlib.util.spec_from_file_location("qgate_mod", qpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.main([a for a in (args.rest or []) if a != "--"])


def _forward_settle(args) -> int:
    argv = ["settle", args.action]
    for opt in ("text", "trap", "symptom", "guard", "fallback", "trigger",
                "domain", "severity", "type", "skip"):
        v = getattr(args, opt, "")
        if v:
            argv += [f"--{opt}", str(v)]
    return _orchestrate(argv)


def _orchestrate(argv: list) -> int:
    """转交编排层：plan / settle / change / bundle / use / viz（v2.2.0 单向联动 rfe）。"""
    opath = Path(__file__).resolve().parent / "orchestrate.py"
    if not opath.exists():
        print(f"缺少 {opath}，无法执行编排命令。")
        return 2
    import importlib.util

    spec = importlib.util.spec_from_file_location("v2p_orch", opath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.main(argv)


def cmd_spec_check(args) -> int:
    # ---- 交付强制收尾：存在未沉淀的 plan 时不允许通过（v2.2.0）----
    try:
        plans = sorted((_home() / "plans").glob("*/state.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if plans:
            st = json.loads(plans[0].read_text(encoding="utf-8-sig"))
            s = st.get("settled", {})
            if not st.get("delivered") and \
                    (s.get("rules", 0) + s.get("pitfalls", 0)) == 0:
                print(f"[交付收尾未完成] 最近 plan「{st.get('text','')[:32]}…」还没有任何沉淀。")
                print("  settle 是交付强制收尾步骤：v2p settle pitfall --trap \"...\" --guard \"...\"")
                print("  完成沉淀后再跑 spec check；确无可沉淀内容用 v2p settle done --skip <理由>。")
                return 1
    except (OSError, json.JSONDecodeError):
        pass
    return _spec_check_impl(args)


def cmd_stats(args) -> int:
    data = load_profile()["profile"]
    prefs = data.get("偏好", {})
    total = sum((v.get("count", 0) if isinstance(v, dict) else 0) for v in prefs.values())
    print(f"档案：{_profile_path()}")
    print(f"偏好条目 {len(prefs)} 条，累计确认 {total} 次")
    print(f"否决方案 {len(data.get('被否决的方案', []))} 项")
    print(f"常做品类 {len(data.get('常做品类', []))} 个")
    if prefs:
        top = sorted(prefs.items(), key=lambda x: -(x[1].get("count", 0) if isinstance(x[1], dict) else 0))[:3]
        print("最强偏好：" + "；".join(k for k, _ in top))
    n_q = len(UNIVERSAL) + sum(len(v) for v in FORM_Q.values())
    print(f"\n题库：通用 {len(UNIVERSAL)} 题 + 形态专属 {n_q - len(UNIVERSAL)} 题 = {n_q} 题")
    print(f"形态 {len(FORMS) - 1} 类 + 未定形态，维度 {len(DIMS)} 个，深度 {len(LEVELS)} 级")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="v2p", description="模糊需求挖掘与产出生成器（挖掘深度随需求动态调整）"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("route", help="判定产出形态 + 初判深度 + 必挖点")
    s.add_argument("--text", "-t", required=True, help="用户的原话")
    s.set_defaults(func=cmd_route)

    s = sub.add_parser("depth", help="按信号算深度等级与轮次预算")
    for k, label, _ in SIGNALS:
        s.add_argument(f"--{k}", type=int, choices=[0, 1, 2], default=None,
                       help=label)
    s.add_argument("--round", type=int, default=None, help="当前第几轮（用于判断是否该收敛）")
    s.set_defaults(func=cmd_depth)

    s = sub.add_parser("ask", help="按形态×深度×轮次取题")
    s.add_argument("--form", "-f", default="app", choices=list(FORM_Q))
    s.add_argument("--depth", "-d", default="D2", choices=list(LEVEL_INDEX))
    s.add_argument("--round", "-r", type=int, default=None)
    s.add_argument("--done", default="", help="已覆盖的维度，逗号分隔，如 goal,scene")
    s.add_argument("--limit", type=int, default=4)
    s.add_argument("--stage", default="", help="（兼容旧版）等价于 --round")
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("forms", help="列出八类形态与必挖点")
    s.set_defaults(func=cmd_forms)

    p = sub.add_parser("profile", help="口味档案管理")
    psub = p.add_subparsers(dest="pcmd", required=True)
    s = psub.add_parser("show", help="查看档案")
    s.set_defaults(func=cmd_profile_show)
    s = psub.add_parser("set", help="记录一条偏好")
    s.add_argument("key")
    s.add_argument("--count", type=int, default=1)
    s.set_defaults(func=cmd_profile_set)
    s = psub.add_parser("veto", help="记录被否决的方案")
    s.add_argument("name")
    s.set_defaults(func=cmd_profile_veto)
    s = psub.add_parser("habit", help="记录表述习惯")
    s.add_argument("text")
    s.set_defaults(func=cmd_profile_habit)
    s = psub.add_parser("cat", help="记录常做品类")
    s.add_argument("names", nargs="+")
    s.set_defaults(func=cmd_profile_cat)
    s = psub.add_parser("shape", help="记录常用形态")
    s.add_argument("name")
    s.add_argument("--count", type=int, default=1)
    s.set_defaults(func=cmd_profile_shape)
    s = psub.add_parser("depth", help="记录常用深度")
    s.add_argument("level", choices=list(LEVEL_INDEX))
    s.add_argument("--count", type=int, default=1)
    s.set_defaults(func=cmd_profile_depth)

    s = sub.add_parser("spec", help="产出规格管理")
    ssub = s.add_subparsers(dest="scmd", required=True)
    t = ssub.add_parser("new", help="生成骨架（默认软件 PRD，--brief 通用定型卡）")
    t.add_argument("--title", required=True)
    t.add_argument("--out", default="")
    t.add_argument("--brief", action="store_true")
    t.add_argument("--force", action="store_true")
    t.set_defaults(func=cmd_spec_new)
    t = ssub.add_parser("check", help="检查能否交付")
    t.add_argument("--file", required=True)
    t.add_argument("--form", default="auto",
                   help="app 走软件 PRD 校验；其他形态走通用定型卡校验")
    t.set_defaults(func=cmd_spec_check)

    s = sub.add_parser("gate", help="交付质量闸门：list / card / manual / redteam / scan / stats")
    s.add_argument("rest", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_gate)

    # ---- 编排层（v2.2.0）：v2p 当主人，单向联动 rfe，用户一条命令 ----
    s = sub.add_parser("plan", help="统一入口：挖掘计划 + 合规红线 + 资源底线 + 倒排计划")
    s.add_argument("--text", "-t", required=True, help="用户的原话")
    s.add_argument("--bundle", default="", help="交付包形态，如 app,doc,sheet")
    s.set_defaults(func=lambda a: _orchestrate(["plan", "-t", a.text] +
                                               (["--bundle", a.bundle] if a.bundle else [])))

    s = sub.add_parser("settle", help="交付强制收尾沉淀：rule / pitfall / status / done")
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
    s.set_defaults(func=_forward_settle)

    s = sub.add_parser("change", help="需求变更：自动重跑合规与工期推演")
    s.add_argument("--text", "-t", required=True, help="改了什么")
    s.set_defaults(func=lambda a: _orchestrate(["change", "-t", a.text]))

    s = sub.add_parser("bundle", help="交付包一致性对账清单")
    s.add_argument("--name", default="")
    s.add_argument("--items", required=True, help="如 app,doc,sheet")
    s.add_argument("--out", "-o", default="")
    s.set_defaults(func=lambda a: _orchestrate(
        ["bundle", "--items", a.items] + (["--name", a.name] if a.name else [])
        + (["--out", a.out] if a.out else [])))

    s = sub.add_parser("use", help="切换/查看项目口味档案（多项目隔离）")
    s.add_argument("name", nargs="?", default="")
    s.set_defaults(func=lambda a: _orchestrate(["use"] + ([a.name] if a.name else [])))

    s = sub.add_parser("viz", help="轻量可视化：depth / gates / heatmap")
    s.add_argument("what", choices=["depth", "gates", "heatmap"])
    s.add_argument("--text", "-t", default="")
    s.add_argument("--form", "-f", default="app")
    s.add_argument("--out", "-o", default="")
    s.set_defaults(func=lambda a: _orchestrate(
        ["viz", a.what]
        + (["-t", a.text] if a.text else [])
        + (["-f", a.form] if a.what == "gates" else [])
        + (["-o", a.out] if a.out else [])))

    s = sub.add_parser("stats", help="档案与题库统计")
    s.set_defaults(func=cmd_stats)
    return ap


def main() -> int:
    if hasattr(sys.stdout, "reconfigure") and not (os.name == "nt" and sys.stdout.isatty()):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
