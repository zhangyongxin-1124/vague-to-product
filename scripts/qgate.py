#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qgate.py — 交付质量闸门（Quality Gate），零依赖，仅 Python 标准库。

为什么存在：需求挖得再准，交付物只覆盖「正常路径」就等于没做完。
本模块把 6 类常见崩坏点做成可核对、可扫描、可复现的闸门。

用法：
    python qgate.py list --form app
    python qgate.py card --form app --out 核查卡.md
    python qgate.py redteam --form app
    python qgate.py scan --path ./我的项目
    python qgate.py stats
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 六道闸门

GATES = [
    ("state", "完整态", "只做「顺利且齐全」这一种情况，是业余感的第一来源"),
    ("interaction", "交互", "能用但难用：点了没反应、返回丢状态、浮层打架"),
    ("layout", "布局", "局部正确、整体打架：这里好看，换个尺寸就散"),
    ("data", "数据", "看着正常，真实输入一来就露馅：假数据、字段错位、算错"),
    ("engineering", "工程", "本地好好的，换个环境就炸：密钥泄露、构建失败"),
    ("maintain", "可维护", "改一处崩三处，而且回不去"),
]

SEV_LABEL = {"block": "阻断", "warn": "提醒"}

# forms: all = 全部形态；其余为适用形态
CHECKS = [
    # ---------------- 一、完整态 ----------------
    dict(id="QG-101", gate="state", sev="block", forms=["app"],
         name="加载中", ask="点了按钮、数据还没回来时，屏幕上是什么？",
         test="把网络切到慢速，点主按钮，看 300ms 内有没有任何反应",
         fix="按钮立即进入加载并禁用；列表区域给骨架或「正在找…」，不要留空白"),
    dict(id="QG-102", gate="state", sev="block", forms=["app"],
         name="没有数据", ask="一条数据都没有时，用户看到什么？能做什么？",
         test="清空数据后打开首页/列表页",
         fix="一句人话说明为什么空 + 一个能立刻做的动作（发布第一条 / 换个筛选条件）"),
    dict(id="QG-103", gate="state", sev="block", forms=["app"],
         name="出错", ask="接口失败时，用户看到的是中文解释还是空白？",
         test="断网点查询，或在代码里故意让接口返回 500",
         fix="说清「哪一步失败了 + 可以怎么办 + 一个重试按钮」，禁止只抛 undefined"),
    dict(id="QG-104", gate="state", sev="block", forms=["app"],
         name="保存成功", ask="保存后用户怎么知道成了？",
         test="点保存，不看数据，只问身边人「成了吗，你怎么知道」",
         fix="明确回执（提示条 / 按钮变「已保存」/ 列表里立刻出现那条）"),
    dict(id="QG-105", gate="state", sev="block", forms=["app"],
         name="不该点的不能点", ask="条件不满足时，按钮是变灰还是照样能点？",
         test="空表单直接点提交；没选行时点删除",
         fix="不可用时禁用并说明原因；已点过的按钮锁定，防重复提交"),
    dict(id="QG-106", gate="state", sev="warn", forms=["app"],
         name="极端数量", ask="0 条、1 条、1 万条时分别长什么样？",
         test="灌 1 条和 1 万条数据各看一次；只看首屏和滚动到底",
         fix="0 条走空态；1 万条走分页或虚拟滚动；总数显示用千分位"),
    dict(id="QG-107", gate="state", sev="warn", forms=["app", "visual", "media"],
         name="素材加载失败", ask="图片/字体/视频没加载出来时是什么样？",
         test="把图床地址改错，或断网后打开",
         fix="占位块 + 主色块 + 失败文字；不要留破图标，也不要撑破布局"),

    # ---------------- 二、交互 ----------------
    dict(id="QG-201", gate="interaction", sev="block", forms=["app"],
         name="弹窗被遮住", ask="所有浮层（弹窗/下拉/提示）同时出现时谁在上面？",
         test="先开弹窗，再点弹窗里的下拉；再开第二个弹窗",
         fix="统一层级表（页面 0 / 吸顶 10 / 浮层 100 / 弹窗 1000 / 全局提示 2000），禁止随手写 9999"),
    dict(id="QG-202", gate="interaction", sev="block", forms=["app"],
         name="背景乱滚", ask="弹窗打开时，背后那层还能滚吗？关掉后回到原位了吗？",
         test="打开长列表页的弹窗，滚动滚轮/手指，关闭后再看位置",
         fix="打开时锁 body 滚动并补滚动条宽度；关闭后恢复原 scrollTop"),
    dict(id="QG-203", gate="interaction", sev="warn", forms=["app"],
         name="键盘焦点乱飞", ask="只用 Tab 键能走完主流程吗？弹窗打开后焦点在哪？",
         test="不用鼠标，全程 Tab + Enter 走一遍主流程",
         fix="弹窗打开时焦点移入并限制在内部；关闭后还给触发按钮；可点元素用真按钮"),
    dict(id="QG-204", gate="interaction", sev="block", forms=["app", "sheet"],
         name="表单校验打架", ask="出错提示出现在哪？改了之后会消失吗？",
         test="故意全部填错提交一次，再逐项改对",
         fix="提示贴着对应字段、改对即消；同一规则只写一处；提交成功后清空或明确保留"),
    dict(id="QG-205", gate="interaction", sev="block", forms=["app"],
         name="重复提交", ask="网络慢时连点三次提交，会发三次请求吗？",
         test="把网速调慢，连点主按钮 3 次，数后台记录",
         fix="点击即禁用 + 请求去重 + 服务端幂等键，三样至少做前两样"),
    dict(id="QG-206", gate="interaction", sev="block", forms=["app"],
         name="刷新就白屏", ask="在二级页面按 F5，或把链接发给别人直接打开，能出来吗？",
         test="复制详情页地址，新开无痕窗口直接粘贴访问",
         fix="配好单页路由回退（找不到路径回首页）；或改用带 hash 的路由"),
    dict(id="QG-207", gate="interaction", sev="warn", forms=["app"],
         name="返回丢状态", ask="从详情返回列表，筛选、页码、滚动位置还在吗？",
         test="列表滚到第 5 屏 → 点进详情 → 返回",
         fix="把筛选与页码放进地址栏或缓存；返回时恢复滚动位置"),
    dict(id="QG-208", gate="interaction", sev="block", forms=["app"],
         name="手机键盘遮挡", ask="键盘弹出后，正在输入的框还在屏幕里吗？",
         test="真机点最后一个输入框，等键盘弹起",
         fix="输入框滚动到可视区；容器用动态视口高度，别写死 100vh"),

    # ---------------- 三、布局 ----------------
    dict(id="QG-301", gate="layout", sev="block", forms=["app", "visual"],
         name="手机横向滚动", ask="最窄的手机（375 宽）上会不会左右晃？",
         test="浏览器设备模式选 375×667，看有没有横向滚动条",
         fix="图片与表格加最大宽度约束；长单词与 URL 允许断行；不要用固定 px 宽"),
    dict(id="QG-302", gate="layout", sev="warn", forms=["all"],
         name="长文本撑爆", ask="标题 60 个字、URL、英文长单词，会不会把卡片顶破？",
         test="把标题改成 60 个汉字 + 一段 URL 再刷新",
         fix="标题限 2 行截断 + 完整内容放在详情；正文加 word-break"),
    dict(id="QG-303", gate="layout", sev="warn", forms=["app"],
         name="高度写死", ask="内容多一条、少一条，卡片会不会截断或空一大块？",
         test="数据从 3 条切到 10 条，再切回 1 条",
         fix="高度由内容撑开，只给最小高度；列表用自适应而不是固定行高"),
    dict(id="QG-304", gate="layout", sev="warn", forms=["app"],
         name="对齐靠猜", ask="同一列的间距是同一套数值吗？",
         test="量三个卡片的间距，看是不是 8/12/16 这类倍数",
         fix="定一套间距刻度（4 的倍数），禁止出现 7、13、23 这种随手数"),
    dict(id="QG-305", gate="layout", sev="warn", forms=["app", "visual", "doc"],
         name="字体图标缺失", ask="图标字体没加载时，是不是满屏方框？",
         test="断网或屏蔽字体域名后刷新",
         fix="图标改用内联 SVG；或加字体加载失败兜底，至少不显示方框"),
    dict(id="QG-306", gate="layout", sev="block", forms=["app", "visual"],
         name="暗色看不清", ask="切到深色模式，文字还看得见吗？",
         test="系统切成深色，逐页扫一遍",
         fix="颜色全部走变量；深色下背景提亮一档、文字反色，不要只用纯黑纯白"),
    dict(id="QG-307", gate="layout", sev="warn", forms=["app", "visual"],
         name="图片变形", ask="头像、封面被拉长了吗？裁切点在人脸上吗？",
         test="换一张竖图、一张横图分别看头像与封面",
         fix="头像定比例 + 居中裁切；封面用 object-fit: cover 并给焦点位置"),
    dict(id="QG-308", gate="layout", sev="block", forms=["app"],
         name="被自己盖住", ask="吸顶栏会盖住第一行内容吗？底部按钮盖住最后一条吗？",
         test="列表滚到顶看第一条，滚到底看最后一条",
         fix="给容器留出顶栏/底栏的等高空隙；别用绝对定位硬压"),
    dict(id="QG-309", gate="layout", sev="warn", forms=["app"],
         name="改一处全变", ask="改一个按钮，别处跟着变了吗？",
         test="给主按钮换颜色，看还有哪些地方被一起改了",
         fix="样式分层：全局只放变量与重置，组件样式加作用域，禁止用标签选择器写业务样式"),

    # ---------------- 四、数据 ----------------
    dict(id="QG-401", gate="data", sev="block", forms=["app", "sheet"],
         name="写死的假数据", ask="页面里的「张三」「13800138000」是写死的吗？",
         test="搜代码里的中文姓名与手机号；再把数据源换成空",
         fix="假数据只放在单独的种子文件里，且能被真实数据整体替换"),
    dict(id="QG-402", gate="data", sev="block", forms=["app", "sheet"],
         name="字段对不上", ask="前端读的字段名，和接口给的完全一致吗？",
         test="打印一次真实接口返回，逐个字段对一遍",
         fix="接口层做一次映射与默认值兜底；字段名差异只在一个地方处理"),
    dict(id="QG-403", gate="data", sev="block", forms=["app", "sheet"],
         name="时间错乱", ask="时间显示是 Invalid Date 吗？差 8 小时吗？",
         test="拿一条刚创建的数据，对比页面时间与手机时间",
         fix="统一存 ISO 或时间戳，只在展示层转本地时区；不要用字符串直接 new Date"),
    dict(id="QG-404", gate="data", sev="block", forms=["app", "sheet"],
         name="金额算错", ask="0.1 + 0.2 会不会算出 0.30000000000000004？",
         test="输入 0.1 与 0.2 相加；再算 100 件单价 19.9 的合计",
         fix="金额一律以「分」为整数存储与计算，只在显示时除 100，不用浮点累加"),
    dict(id="QG-405", gate="data", sev="warn", forms=["all"],
         name="编码乱码", ask="中文变问号了吗？emoji 变方块了吗？",
         test="输入「测试😀」「𠮷」与一段繁体，看存进去再读出来是否一致",
         fix="全链路统一 UTF-8；数据库字符集与连接串一起检查；导出文件加 BOM"),
    dict(id="QG-406", gate="data", sev="block", forms=["app"],
         name="后发先到", ask="快速切三个标签，回来的数据会串台吗？",
         test="网速调慢，快速点 A→B→C 三个分类，看最后显示的是不是 C",
         fix="每次请求带序号或取消上一个；只接受最新一次的结果"),
    dict(id="QG-407", gate="data", sev="block", forms=["app"],
         name="请求风暴", ask="输入框每敲一个字就发一次请求吗？",
         test="打开开发者工具的网络面板，在搜索框连打 6 个字",
         fix="输入防抖 300ms + 结果缓存 + 取消过期请求"),
    dict(id="QG-408", gate="data", sev="warn", forms=["app"],
         name="改了不刷新", ask="改完数据回到列表，看到的还是旧值吗？",
         test="改一条记录 → 返回列表 → 再进详情，三步对照",
         fix="写入后让相关缓存失效；列表以服务端返回为准，不要只在本地改"),
    dict(id="QG-409", gate="data", sev="block", forms=["app"],
         name="只藏了按钮", ask="隐藏入口就等于没权限了吗？",
         test="用低权限账号直接请求管理接口（改一个 id 或换路径）",
         fix="权限判断放服务端每个接口；前端隐藏只是顺手，不是安全措施"),

    # ---------------- 五、工程 ----------------
    dict(id="QG-501", gate="engineering", sev="block", forms=["app"],
         name="依赖打架", ask="装的库版本互不兼容吗？别人能装上吗？",
         test="删掉依赖目录重装一次；换台机器再装一次",
         fix="锁定版本；只留一份锁文件；新增依赖前先确认与现有版本兼容"),
    dict(id="QG-502", gate="engineering", sev="block", forms=["all"],
         name="密钥泄露", ask="密钥写在前端代码或仓库里了吗？",
         test="全局搜 sk-、key、secret、token；再打开浏览器控制台看网络请求",
         fix="密钥只放服务端环境变量；已泄露的立刻作废重发，改代码不算修好"),
    dict(id="QG-503", gate="engineering", sev="warn", forms=["app"],
         name="换浏览器就崩", ask="Safari / 旧版 Chrome / 微信内置浏览器能开吗？",
         test="在 iPhone 上真机打开一次，重点试日期、滚动、输入框",
         fix="日期用统一解析函数；避免新语法不转译；滚动问题改用原生滚动"),
    dict(id="QG-504", gate="engineering", sev="block", forms=["app"],
         name="能跑不能发", ask="本地能跑，打包能过吗？上线后能开吗？",
         test="本地执行一次完整构建，再把产物用本地服务打开",
         fix="构建与运行同环境验证；注意文件路径大小写；静态资源用相对路径"),
    dict(id="QG-505", gate="engineering", sev="warn", forms=["app"],
         name="越用越卡", ask="停留十分钟后风扇响不响？",
         test="连续切换页面 20 次，看内存曲线是否一路上涨",
         fix="监听与定时器在卸载时清理；长列表销毁离屏项"),
    dict(id="QG-506", gate="engineering", sev="block", forms=["app"],
         name="请求发个不停", ask="打开一个页面，网络面板会不会一直冒出请求？",
         test="打开网络面板，静置 30 秒，数请求条数",
         fix="检查依赖数组与状态更新条件；避免在渲染中写状态"),
    dict(id="QG-507", gate="engineering", sev="warn", forms=["app"],
         name="首屏太重", ask="第一次打开要等几秒？",
         test="清缓存 + 限速到 3G，计时到内容出现",
         fix="删掉为一个小功能引入的大库；图片压缩并按需加载"),
    dict(id="QG-508", gate="engineering", sev="block", forms=["app"],
         name="一错全白", ask="某个模块报错，整页是不是白屏？",
         test="故意让一个子模块抛错，看页面其余部分是否还在",
         fix="加错误边界与兜底 UI；关键区块单独容错"),

    # ---------------- 六、可维护 ----------------
    dict(id="QG-601", gate="maintain", sev="block", forms=["all"],
         name="不存在的接口", ask="用到的函数、字段、库，真的存在吗？",
         test="逐个点开所用方法的官方文档；或直接跑一遍看报错",
         fix="不确定的写法先用最小例子验证；禁止凭记忆调用没验证过的 API"),
    dict(id="QG-602", gate="maintain", sev="warn", forms=["app"],
         name="两种写法并存", ask="同类页面是不是一个用 A 一个用 B？",
         test="找两个功能相似的页面，对比数据请求与样式写法",
         fix="定一份最简约定（怎么取数、怎么排版、怎么提示），新页面照抄旧页面"),
    dict(id="QG-603", gate="maintain", sev="warn", forms=["app"],
         name="复制粘贴的组件", ask="同样的卡片写了几遍？改一处漏几处？",
         test="改一次卡片样式，数需要改几个文件",
         fix="抽成一个组件，参数化差异项；重复第三次就必须抽"),
    dict(id="QG-604", gate="maintain", sev="block", forms=["all"],
         name="改一个坏三个", ask="改完这处，别处还好吗？",
         test="改完立刻把主流程重新走一遍，不看代码看页面",
         fix="一次只改一件事；改完必回归主流程；改不动就回退重来"),
    dict(id="QG-605", gate="maintain", sev="warn", forms=["app", "material"],
         name="出问题只能猜", ask="线上报错时，你怎么知道错在哪？",
         test="故意触发一个错误，看有没有可读的日志或提示",
         fix="关键动作打日志 + 全局错误捕获；至少把错误信息留在控制台"),
    dict(id="QG-606", gate="maintain", sev="block", forms=["all"],
         name="能被越权与注入", ask="用户输入会被当代码执行吗？拼进数据库语句吗？",
         test="在输入框填 <script>alert(1)</script> 与 ' OR 1=1--",
         fix="输出转义、参数化查询、服务端校验；不信任任何客户端输入"),
    dict(id="QG-607", gate="maintain", sev="block", forms=["all"],
         name="改坏了回不去", ask="这版不行，能退回上一版吗？",
         test="看有没有版本记录；试着回退一次",
         fix="每次可交付版本打一个标记；改前先留一份能跑的备份"),

    # ---------------- 非软件形态的等价闸门 ----------------
    dict(id="QG-701", gate="state", sev="block", forms=["doc"],
         name="读了不知道结论", ask="第一页有没有直接给出结论或建议？",
         test="把文档给别人，只让他读 30 秒，问「所以呢」",
         fix="开头一段写结论与建议动作，后面才是论证"),
    dict(id="QG-702", gate="state", sev="block", forms=["doc"],
         name="数字没有出处", ask="每个关键数字后面有没有来源或「待核实」？",
         test="逐个圈出数字，问自己这个数从哪来",
         fix="标来源与日期；查不到就写待核实，不要估一个凑数"),
    dict(id="QG-703", gate="layout", sev="warn", forms=["doc"],
         name="篇幅不对", ask="这文档是给谁看的，他要读多久？",
         test="按目标读者的耐心算页数：内部 1–3 页，汇报 10–15 页",
         fix="删掉不支撑结论的段落；能放附件的放附件"),
    dict(id="QG-704", gate="data", sev="block", forms=["doc"],
         name="前后不一致", ask="正文、表格、结论里的同一个数一致吗？",
         test="把同一个指标在全文所有出现处列出来对比",
         fix="关键数字只定义一次，其余引用同一处"),
    dict(id="QG-705", gate="state", sev="block", forms=["sheet"],
         name="空与错值", ask="有空行、#N/A、#DIV/0!、文本型数字吗？",
         test="筛选空值；看有没有绿色三角与错误值",
         fix="空值有明确含义（未填/不适用）；错误值用 IFERROR 兜底"),
    dict(id="QG-706", gate="data", sev="block", forms=["sheet"],
         name="口径不统一", ask="金额含税吗？日期是发生还是入账？",
         test="随机抽 3 行，问自己这列的单位与口径",
         fix="在表头或说明页写死口径；同一列不混用两种口径"),
    dict(id="QG-707", gate="engineering", sev="warn", forms=["sheet"],
         name="公式一拉就错", ask="插入一行后，合计还包含它吗？",
         test="在中间插一行、删一行，看合计与引用是否跟着变",
         fix="用整列引用或结构化引用；避免写死行号与跨表硬编码"),
    dict(id="QG-708", gate="layout", sev="warn", forms=["visual"],
         name="缩小就糊", ask="在目标尺寸下（手机/打印/A3）还看得清吗？",
         test="缩到实际使用尺寸，眯眼看主标题与关键数字",
         fix="层级只留三层；小字要么放大要么删；导出前检查实际像素"),
    dict(id="QG-709", gate="maintain", sev="block", forms=["visual", "media"],
         name="素材侵权", ask="图片、字体、音乐、人物肖像有权使用吗？",
         test="逐个素材追来源：自摄/购买/免费可商用/不明",
         fix="不明来源一律替换；商用字体与音乐须有授权凭证"),
    dict(id="QG-710", gate="layout", sev="block", forms=["model3d"],
         name="打不出来", ask="模型是封闭实体吗？壁厚够吗？单位对吗？",
         test="用切片软件跑一次，看有没有破面与悬空",
         fix="补面、加壁厚、统一毫米；导出一份切片预览图"),
    dict(id="QG-711", gate="data", sev="block", forms=["model3d"],
         name="尺寸不对", ask="文件里的 1 单位等于现实几毫米？",
         test="导入切片软件，看尺寸与实际件是否一致",
         fix="建模前定单位；导出时确认比例；交付附尺寸说明"),
    dict(id="QG-712", gate="state", sev="block", forms=["media"],
         name="三秒留不住人", ask="开头三秒给了继续看的理由吗？",
         test="只播前三秒，问身边人想不想继续看",
         fix="开头直接给冲突/结果/反常识结论，不要从片头字幕开始"),
    dict(id="QG-713", gate="engineering", sev="warn", forms=["media"],
         name="字幕与音画不同步", ask="字幕对得上说话吗？结尾有明确动作吗？",
         test="静音看一遍，再关字幕听一遍",
         fix="按语义断句而非按字数；结尾给一个具体动作"),
    dict(id="QG-714", gate="state", sev="block", forms=["material"],
         name="三秒找不到", ask="拿一个真问题来搜，能三秒找到吗？",
         test="让别人用他自己的问题找一次，计时",
         fix="按「人会怎么找」建目录；加一页索引或检索表"),
    dict(id="QG-715", gate="maintain", sev="block", forms=["material"],
         name="没人维护", ask="三个月后谁负责更新？",
         test="问自己这个问题，答不出就是没定",
         fix="写明维护人与更新频率；命名带日期与版本"),
    dict(id="QG-716", gate="engineering", sev="block", forms=["physical"],
         name="报不出价", ask="BOM 每一项都能找到供应商与单价吗？",
         test="拿 BOM 直接去问价，看有几项卡住",
         fix="补规格、数量、材质、工艺；一项不全就询不到价"),
    dict(id="QG-717", gate="state", sev="block", forms=["physical"],
         name="没法验收", ask="交付时按什么逐项打勾？不合格怎么处理？",
         test="拿验收单去现场，看能不能只靠它判断合格与否",
         fix="每条验收项写成可测的（尺寸/数量/外观/功能），并写明不合格处置"),
]

GATE_INDEX = {k: (n, d) for k, n, d in GATES}

# 核心项：深度 D0/D1 只查这些，避免为一张通知填 48 项
CORE_IDS = {
    "app": ["QG-101", "QG-102", "QG-103", "QG-104", "QG-105", "QG-205", "QG-502"],
    "doc": ["QG-701", "QG-702", "QG-704", "QG-703"],
    "sheet": ["QG-705", "QG-706", "QG-707", "QG-404"],
    "visual": ["QG-301", "QG-306", "QG-708", "QG-709"],
    "model3d": ["QG-710", "QG-711", "QG-107"],
    "media": ["QG-712", "QG-713", "QG-709"],
    "material": ["QG-714", "QG-715", "QG-405"],
    "physical": ["QG-716", "QG-717", "QG-502"],
    "unknown": ["QG-302", "QG-502", "QG-607"],
}
# 深度 → 查多少：浅活只查核心，正常的查全部阻断项，深的查全量
DEPTH_POLICY = {"D0": "core", "D1": "core", "D2": "block", "D3": "all", "D4": "all"}


def apply_depth(rows: list, form: str, depth: str) -> list:
    mode = DEPTH_POLICY.get((depth or "").upper(), "all")
    if mode == "core":
        keep = set(CORE_IDS.get(form, []))
        return [r for r in rows if r["id"] in keep]
    if mode == "block":
        return [r for r in rows if r["sev"] == "block"]
    return rows

# 状态矩阵：写第一行代码/第一段正文之前必须先填
STATE_MATRIX = {
    "app": [
        ("加载中", "数据还没回来（首次进入 / 点了按钮 / 下拉刷新）"),
        ("没有数据", "一条都没有；或筛选后为空"),
        ("出错", "请求失败 / 超时 / 无权限"),
        ("成功", "保存、提交、删除完成之后"),
        ("不可用", "条件不满足，按钮不该能点"),
        ("极端量", "1 条、1 万条、超长文本"),
        ("素材缺失", "图片/字体加载失败"),
    ],
    "doc": [
        ("完整", "资料齐全时的正常版本"),
        ("缺项", "某块数据拿不到，怎么标注"),
        ("超量", "内容超出预期篇幅，怎么取舍"),
        ("异常", "被质疑数字来源时怎么答"),
    ],
    "sheet": [
        ("完整", "数据齐全"),
        ("空值", "没填 / 不适用 / 待补，三者怎么区分"),
        ("错误值", "#N/A、除零、文本型数字"),
        ("超量", "一万行时公式与打开速度"),
    ],
    "visual": [
        ("完整", "元素齐全"),
        ("缺字", "标题超长 / 字体缺失"),
        ("缩略", "在小尺寸下是否还成立"),
        ("异常", "图片加载失败"),
    ],
    "model3d": [
        ("完整", "可打印/可渲染"),
        ("破面", "非封闭实体"),
        ("尺寸", "单位与比例错"),
        ("超限", "超出打印幅面"),
    ],
    "media": [
        ("完整", "成片"),
        ("开头", "前三秒抓不住人"),
        ("缺素材", "某段缺画面/缺配音"),
        ("异常", "字幕不同步、音乐无授权"),
    ],
    "material": [
        ("完整", "资料齐全"),
        ("缺档", "关键文件缺失"),
        ("超量", "文件过多找不到"),
        ("过期", "旧版本混在新版本里"),
    ],
    "physical": [
        ("完整", "样品/成品"),
        ("缺料", "某物料断供"),
        ("超量", "数量级变化导致工艺变化"),
        ("不合格", "验收不通过怎么处置"),
    ],
    "unknown": [
        ("完整", "正常情况"),
        ("缺项", "拿不到的部分"),
        ("超量", "超出预期"),
        ("异常", "出错时"),
    ],
}

REDTEAM = {
    "app": [
        "断网，然后点主按钮 —— 看有没有反应、说的什么",
        "把详情页地址复制到无痕窗口直接打开 —— 会不会白屏",
        "列表滚到第 5 屏 → 进详情 → 返回 —— 位置还在吗",
        "输入 60 个汉字 + 一个超长网址 + 一个 emoji 再保存",
        "网速调慢，连点提交 3 次 —— 后台有几条记录",
        "手机系统字体调到最大 —— 有没有文字被切掉",
        "横屏再竖屏 —— 有没有错位",
        "用另一个账号，直接改地址里的 id 访问别人的数据",
        "把系统时区改成 UTC —— 时间显示还对不对",
        "让接口返回空数组 —— 页面是不是一片空白",
        "打开控制台 —— 有没有红字、有没有密钥明文",
        "点最后一个输入框，等键盘弹起 —— 框还在视野里吗",
    ],
    "doc": [
        "只读 30 秒，问「所以呢」—— 答得出结论吗",
        "随机圈 5 个数字，逐个问来源",
        "把同一个指标的所有出现处列出来，对一遍",
        "发给一个不懂这行的人，让他复述你要他做什么",
        "打印出来看 —— 表格有没有被切断、字号是否可读",
    ],
    "sheet": [
        "在中间插一行 —— 合计与公式有没有跟着变",
        "筛出所有空值 —— 是未填还是不适用",
        "把某列改成文本型数字 —— 求和还对不对",
        "灌到 1 万行 —— 打开与计算还快吗",
        "换一个人按说明填 3 行 —— 他能填对吗",
    ],
    "visual": [
        "缩到实际使用尺寸看主标题",
        "换成最长的标题文案",
        "屏蔽字体域名后打开",
        "打印成黑白看层级是否还成立",
    ],
    "model3d": [
        "用切片软件跑一遍，看破面与悬空",
        "量一遍关键尺寸，与实物对比",
        "换一个软件打开，看单位是否一致",
        "按目标工艺检查最小壁厚",
    ],
    "media": [
        "只播前三秒，问想不想继续看",
        "静音看一遍",
        "关字幕听一遍",
        "听到结尾，看有没有明确动作",
    ],
    "material": [
        "让别人用自己的问题找一次，计时",
        "搜一个三个月前的老文件",
        "看最新版本与旧版本是否混在一起",
        "问维护人是谁",
    ],
    "physical": [
        "拿 BOM 去询价，看几项卡住",
        "拿验收单现场逐项打勾",
        "数量 ×10 后工艺是否要变",
        "问清关键尺寸公差",
    ],
    "unknown": [
        "断网后用一次",
        "输入最长与最短的内容",
        "让一个没听过这事的人用一次",
    ],
}


def _u(s: str) -> str:
    return (s or "").strip()


def checks_for(form: str, gate: str = "", sev: str = "") -> list:
    order = {k: i for i, (k, _, _) in enumerate(GATES)}
    out = []
    for c in CHECKS:
        if "all" not in c["forms"] and form not in c["forms"]:
            continue
        if gate and c["gate"] != gate:
            continue
        if sev and c["sev"] != sev:
            continue
        out.append(c)
    out.sort(key=lambda c: (order.get(c["gate"], 99), c["id"]))
    return out


def cmd_list(args) -> int:
    form = args.form
    rows = apply_depth(checks_for(form, args.gate, args.sev), form, args.depth)
    if not rows:
        print(f"形态 {form} 在给定筛选下没有检查项。")
        return 0
    print(f"形态 {form} · 共 {len(rows)} 项"
          f"（阻断 {sum(1 for r in rows if r['sev'] == 'block')} / "
          f"提醒 {sum(1 for r in rows if r['sev'] == 'warn')}）\n")
    cur = ""
    for c in rows:
        if c["gate"] != cur:
            cur = c["gate"]
            name, why = GATE_INDEX[cur]
            print(f"── {name}（{cur}）：{why}")
        print(f"  [{SEV_LABEL[c['sev']]}] {c['id']}  {c['name']}")
        print(f"        问：{c['ask']}")
        print(f"        验：{c['test']}")
        print(f"        修：{c['fix']}")
    return 0


def cmd_card(args) -> int:
    form = args.form
    rows = apply_depth(checks_for(form, args.gate), form, args.depth)
    name = FORM_LABEL.get(form, form)
    tag = f"　深度 {args.depth.upper()}（按深度裁剪：{DEPTH_POLICY.get(args.depth.upper(), 'all')}）" if args.depth else ""
    lines = [
        f"# 交付质量核查卡 · {name}",
        "",
        f"> 生成时间：{_now()}　适用形态：`{form}`　检查项：{len(rows)}{tag}",
        "> 用法：**左边先填「我打算怎么处理」，右边交付前打勾。**",
        "> 填不出来的那一行，就是你还没想清的需求——回到挖掘阶段补，不要跳过。",
        "",
        "## 一、状态矩阵（写第一行之前就要填）",
        "",
        "| 情况 | 用户看到什么 | 能做什么 |",
        "|---|---|---|",
    ]
    for label, desc in STATE_MATRIX.get(form, STATE_MATRIX["unknown"]):
        lines.append(f"| **{label}**（{desc}） |  |  |")
    lines += ["", "## 二、闸门逐项核对", ""]
    cur = ""
    for c in rows:
        if c["gate"] != cur:
            cur = c["gate"]
            gname, why = GATE_INDEX[cur]
            lines += ["", f"### {gname}　_{why}_", "",
                      "| 检查项 | 我打算怎么处理 | 通过 |", "|---|---|---|"]
        mark = "**阻断**" if c["sev"] == "block" else "提醒"
        lines.append(
            f"| {c['id']} {c['name']}（{mark}）<br><sub>{c['ask']}<br>验：{c['test']}</sub> |  | ☐ |")
    lines += [
        "",
        "## 三、破坏性测试（照着做，不要想象）",
        "",
    ]
    for i, step in enumerate(REDTEAM.get(form, REDTEAM["unknown"]), 1):
        lines.append(f"{i}. ☐ {step}")

    # ---- 合规闸门（第 0 道）：来自 rfe 知识库的红线，全部为阻断 ----
    n_red = 0
    if getattr(args, "kb_redline", None):
        try:
            raw = Path(args.kb_redline).read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            rules = data if isinstance(data, list) else data.get("rules", [])
        except (OSError, json.JSONDecodeError) as e:
            rules = []
            lines += ["", f"> ⚠ 合规规则文件读取失败（{e}），本节为空不等于无风险。", ""]
        rules = [r for r in rules if isinstance(r, dict) and r.get("rule")]
        if rules:
            n_red = len(rules)
            lines += [
                "",
                "## 〇、合规闸门（来自 rfe 知识库，全部为阻断）",
                "",
                "> 质量满分也可能上线即被下架：这一节由 `v2p plan` 自动注入，",
                "> 不满足任何一条 = 交付不通过，与质量闸门同级。",
                "",
                "| 合规红线 | 我打算怎么处理 | 满足 |",
                "|---|---|---|",
            ]
            for r in rules:
                rid = r.get("id", "?")
                lead = f"（提前期 {r['lead_time']}）" if r.get("lead_time") else ""
                lines.append(
                    f"| {rid} {r.get('rule')}<br><sub>依据：{r.get('basis', '待核实')}{lead}</sub> |  | ☐ |")
            lines += [
                "",
                f"- 合规红线未满足数：____　（**必须为 0 才能交付**）",
                "",
            ]

    lines += [
        "",
        "## 四、结论",
        "",
        "- 阻断项未通过数：____　（**必须为 0 才能交付**）",
    ]
    if n_red:
        lines.append("- 合规红线未满足数：____　（**必须为 0，合规不满足 = 交付不通过**）")
    lines += [
        "- 提醒项未通过数：____　（写清为什么不修）",
        "- 本次明确没做的：____",
        "",
        "> 阻断项 > 0 时，正确说法是「还没做完」，不是「基本能用」。",
        "> 本核查卡为经验性清单，不构成法律意见；合规事项请以官方口径与专业咨询为准。",
    ]
    text = "\n".join(lines) + "\n"
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and not args.force:
            print(f"已存在：{p}（加 --force 覆盖）")
            return 1
        p.write_text(text, encoding="utf-8")
        print(f"已生成：{p}")
        print(f"  检查项 {len(rows)} 项，其中阻断 {sum(1 for r in rows if r['sev'] == 'block')} 项")
    else:
        print(text)
    return 0


def cmd_redteam(args) -> int:
    form = args.form
    steps = REDTEAM.get(form, REDTEAM["unknown"])[: args.n]
    print(f"【破坏性测试 · {FORM_LABEL.get(form, form)}】共 {len(steps)} 步，按顺序做，每步只观察不解释\n")
    for i, s in enumerate(steps, 1):
        print(f"{i:>2}. {s}")
    print("\n判据：任何一步出现「白屏 / 没反应 / 数据错 / 文字被切 / 报错看不懂」，都算未通过。")
    return 0


# ---------------------------------------------------------------- 手测清单（半自动 + 强制留痕）

# 静态扫描永远扫不出的五类问题，必须人点；排序即优先级。
MUST_MANUAL = [
    ("空态", "把数据清空后打开主页面：用户看到什么？能做什么？"),
    ("错误态", "断网或让接口失败一次：出现的是中文解释还是白屏/undefined？"),
    ("返回丢状态", "列表滚到中间 → 进详情 → 返回：筛选、页码、滚动位置还在吗？"),
    ("重复提交", "网速调慢后连点提交按钮 3 次：后台是 1 条还是 3 条？"),
    ("极端量", "灌 1 条和 1000 条数据各看一次：首屏与滚到底是否正常？"),
]


def _manual_lines(form: str, depth: str) -> list:
    rows = apply_depth(checks_for(form), form, depth or "")
    blocks = [r for r in rows if r["sev"] == "block"]
    lines = [
        f"# 手测清单 · {FORM_LABEL.get(form, form)}",
        "",
        f"> 生成时间：{_now()}　适用形态：`{form}`　"
        f"阻断项 {len(blocks)} 个 + 必测 {len(MUST_MANUAL)} 条",
        "> 静态扫描扫不出「点了没反应」，这一页就是补盲区的：每条都要真点一遍。",
        "> 留痕要求：勾选 `[x]` 前必须填截图路径；没截图 = 没测过。",
        "",
        "## 一、必测五条（静态扫描的盲区，按顺序做）",
        "",
    ]
    for i, (name, how) in enumerate(MUST_MANUAL, 1):
        lines.append(f"{i}. - [ ] **{name}**：{how}")
        lines.append(f"   截图：____（路径）　结果：符合 / 不符合（现象：____）")
    lines += ["", "## 二、阻断项逐条手测", ""]
    for c in blocks:
        lines.append(f"- [ ] **{c['id']} {c['name']}**　{c['ask']}")
        lines.append(f"  验法：{c['test']}")
        lines.append(f"  截图：____　结果：符合 / 不符合（现象：____）")
    warn_rows = [r for r in rows if r["sev"] == "warn"]
    if warn_rows:
        lines += ["", "## 三、提醒项（不勾完也可以交付，但要写明为什么不修）", ""]
        for c in warn_rows:
            lines.append(f"- [ ] {c['id']} {c['name']}　备注：____")
    lines += [
        "",
        "## 四、结论",
        "",
        f"- 必测未通过数：____　阻断项未通过数：____　（**必须为 0 才能交付**）",
        "- 未勾选且未说明原因的：____",
        "",
        "> 任何一项「不符合」，正确说法是「还没做完」，不是「基本能用」。",
    ]
    return lines


def cmd_manual(args) -> int:
    if args.verify:
        p = Path(args.verify)
        if not p.exists():
            print(f"找不到清单文件：{p}")
            return 2
        raw = p.read_text(encoding="utf-8", errors="replace")
        boxes = re.findall(r"- \[([ xX✓])\]", raw)
        unchecked = len(boxes) - sum(1 for b in boxes if b.strip())
        # 截图留痕：勾选了的行，其后 3 行内应有非占位截图路径
        lines = raw.splitlines()
        no_shot = 0
        for i, ln in enumerate(lines):
            if re.match(r"^\s*- \[[xX✓]\]", ln) or re.match(r"^\s*\d+\. - \[[xX✓]\]", ln):
                ctx = "\n".join(lines[i:i + 3])
                if "截图：____" in ctx or "截图：\u3000\u3000\u3000\u3000" in ctx:
                    no_shot += 1
        print(f"校验对象：{p}")
        print(f"  勾选 {len(boxes) - unchecked} / 共 {len(boxes)} 项；"
              f"未勾选 {unchecked} 项；已勾但缺截图 {no_shot} 项")
        if len(boxes) == 0:
            print("  ✗ 清单里没有任何勾选框——还没有人测过。")
            return 1
        if unchecked or no_shot:
            print("  ✗ 未通过：存在未勾选项或已勾但缺截图路径（没截图 = 没测过）。")
            return 1
        print("  ✓ 通过：全部勾选且截图留痕完整。注意：这仍是人工核验的留痕，不等于自动测试。")
        return 0

    form = args.form
    lines = _manual_lines(form, args.depth)
    text = "\n".join(lines) + "\n"
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and not args.force:
            print(f"已存在：{p}（加 --force 覆盖）")
            return 1
        p.write_text(text, encoding="utf-8")
        n_box = text.count("- [ ]")
        print(f"已生成：{p}")
        print(f"  共 {n_box} 个勾选框（必测 5 条 + 阻断/提醒项）。"
              f"测完跑 v2p gate manual --verify \"{p}\" 校验留痕。")
    else:
        print(text)
    return 0


# ---------------------------------------------------------------- 静态扫描

SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv",
             "venv", ".idea", ".vscode", "coverage", "target"}
CODE_EXT = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue",
            ".wxml", ".wxss", ".json", ".py", ".sql", ".yaml", ".yml"}
TEXT_EXT = CODE_EXT | {".md", ".txt"}

RULES = [
    # (id, 级别, 正则, 说明, 适用后缀)
    ("QGS-01", "block", r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|"
                         r"(?:api[_-]?key|secret|access[_-]?token|appsecret)\s*[:=]\s*[\"'][^\"'\s]{12,})",
     "疑似密钥明文", CODE_EXT),
    ("QGS-02", "block", r"(张三|李四|王五|13800138000|12345678901|test@example\.com|admin123)",
     "疑似写死的假数据（真实数据一到就露馅）", CODE_EXT),
    ("QGS-03", "warn", r"TODO|FIXME|XXX:|待补|占位",
     "未完成标记", CODE_EXT),
    ("QGS-04", "warn", r"z-index\s*:\s*(?:[0-9]{4,}|9999)",
     "层级数值过大，早晚打架", {".css", ".wxss", ".html", ".vue", ".jsx", ".tsx"}),
    ("QGS-05", "warn", r"!important",
     "强制覆盖样式，通常是样式失控的信号", {".css", ".wxss", ".html", ".vue"}),
    ("QGS-06", "warn", r"height\s*:\s*\d{2,4}px",
     "写死高度，内容一多就截断", {".css", ".wxss", ".vue", ".html", ".htm"}),
    ("QGS-07", "warn", r"new Date\(\s*[\"'][^\"']{0,12}[\"']\s*\)",
     "字符串直接解析日期，Safari 会失败", {".js", ".jsx", ".ts", ".tsx", ".vue", ".html"}),
    ("QGS-08", "warn", r"console\.log\(",
     "调试输出残留", CODE_EXT),
    ("QGS-09", "warn", r"http://(?!localhost|127\.0\.0\.1)",
     "非加密外链，上线可能被拦", TEXT_EXT),
    ("QGS-10", "block", r"(eval\(|innerHTML\s*=|document\.write\()",
     "直接执行/写入字符串，XSS 高危", {".js", ".jsx", ".ts", ".tsx", ".vue", ".html"}),
    ("QGS-11", "warn", r"(select|insert|update|delete)[^;]{0,80}\+\s*\w",
     "SQL 拼接，注入风险", {".js", ".ts", ".py", ".php", ".java"}),
    ("QGS-12", "warn", r"font-size\s*:\s*(?:1[0-2]|[0-9])px",
     "字号偏小（移动端建议 ≥14px / ≥28rpx）", {".css", ".wxss", ".vue"}),
]

EMPTY_HINTS = ("空", "empty", "no data", "nodata", "loading", "加载", "skeleton", "骨架")
LIST_HINTS = ("wx:for", "v-for", ".map(", "<li", ".foreach")


def _iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in TEXT_EXT:
                yield p


def cmd_scan(args) -> int:
    root = Path(args.path).expanduser()
    if not root.exists():
        print(f"路径不存在：{root}")
        return 2
    if root.is_file():
        files = [root]
    else:
        files = list(_iter_files(root))

    hits = []
    list_no_state = []
    scanned = 0
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        if p.name == "qgate.py":
            continue
        suffix = p.suffix.lower()
        for rid, sev, pat, msg, exts in RULES:
            if suffix not in exts:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if len(line) > 800:
                    continue
                if re.search(pat, line, re.I):
                    hits.append(dict(rule=rid, sev=sev, msg=msg,
                                     file=str(p), line=i, text=line.strip()[:110]))
        # 列表渲染但完全没有空/加载处理
        if suffix in {".html", ".htm", ".wxml", ".vue", ".jsx", ".tsx", ".js"}:
            low = text.lower()
            if any(h in low for h in LIST_HINTS) and not any(e in low for e in EMPTY_HINTS):
                list_no_state.append(str(p))

    # 密钥类只报一次（避免同一文件刷屏）
    seen = set()
    uniq = []
    for h in hits:
        k = (h["rule"], h["file"])
        if h["rule"] == "QGS-01":
            if k in seen:
                continue
            seen.add(k)
        uniq.append(h)

    blocks = [h for h in uniq if h["sev"] == "block"]
    warns = [h for h in uniq if h["sev"] == "warn"]

    if args.json:
        print(json.dumps({"scanned": scanned, "blocks": blocks, "warns": warns,
                          "list_without_state": list_no_state},
                         ensure_ascii=False, indent=2))
        return 1 if blocks or list_no_state else 0

    print(f"扫描 {scanned} 个文本文件\n")
    if blocks:
        print(f"阻断（{len(blocks)}）：")
        for h in blocks:
            print(f"  [{h['rule']}] {h['msg']}")
            print(f"      {h['file']}:{h['line']}  {h['text']}")
    if list_no_state:
        print(f"\n阻断（{len(list_no_state)}）：列表渲染了，但没有任何空态/加载态处理")
        for f in list_no_state[:10]:
            print(f"  {f}")
        if len(list_no_state) > 10:
            print(f"  …… 另有 {len(list_no_state) - 10} 个")
    if warns:
        print(f"\n提醒（{len(warns)}）：")
        for h in warns[:args.limit]:
            print(f"  [{h['rule']}] {h['msg']} — {h['file']}:{h['line']}")
        if len(warns) > args.limit:
            print(f"  …… 另有 {len(warns) - args.limit} 条，用 --limit 调整")
    if not blocks and not warns and not list_no_state:
        print("没有命中已知模式。注意：这只是启发式，**不能替代手工点一遍**。")

    print(f"\n结论：{'未通过' if (blocks or list_no_state) else '无阻断项'}"
          f"（阻断 {len(blocks) + len(list_no_state)} / 提醒 {len(warns)}）")
    return 1 if (blocks or list_no_state) else 0


def cmd_stats(args) -> int:
    print(f"检查项总数 {len(CHECKS)}，覆盖 {len(GATES)} 道闸门\n")
    print("闸门分布：")
    for key, gname, why in GATES:
        n = sum(1 for c in CHECKS if c["gate"] == key)
        print(f"  {gname:<6}{n:>4} 项   {why}")
    print()
    print(f"{'形态':<12}{'项数':>6}{'阻断':>6}{'提醒':>6}")
    for f, label in FORM_LABEL.items():
        rows = checks_for(f)
        if not rows:
            continue
        print(f"{label:<12}{len(rows):>6}"
              f"{sum(1 for r in rows if r['sev'] == 'block'):>6}"
              f"{sum(1 for r in rows if r['sev'] == 'warn'):>6}")
    print(f"\n破坏性测试步骤：{'；'.join(f'{FORM_LABEL[k]} {len(v)}' for k, v in REDTEAM.items())}")
    return 0


FORM_LABEL = {
    "app": "软件应用", "doc": "文档报告", "sheet": "表格数据", "visual": "图形图像",
    "model3d": "3D 模型", "media": "音视频", "material": "资料知识",
    "physical": "实物服务", "unknown": "未定形态",
}


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="qgate",
        description="交付质量闸门（六道质量闸门 + 合规闸门；具体项数见 stats）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="列出某形态适用的检查项")
    s.add_argument("--form", "-f", default="app", choices=list(FORM_LABEL))
    s.add_argument("--gate", "-g", default="",
                   choices=[g[0] for g in GATES] + [""])
    s.add_argument("--sev", "-s", default="", choices=["block", "warn", ""])
    s.add_argument("--depth", "-d", default="",
                   choices=["", "D0", "D1", "D2", "D3", "D4"],
                   help="按挖掘深度裁剪：D0/D1 核心项，D2 全部阻断项，D3+ 全量")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("card", help="生成填空式核查卡（交付前必填）")
    s.add_argument("--form", "-f", default="app", choices=list(FORM_LABEL))
    s.add_argument("--gate", "-g", default="",
                   choices=[g[0] for g in GATES] + [""])
    s.add_argument("--depth", "-d", default="",
                   choices=["", "D0", "D1", "D2", "D3", "D4"])
    s.add_argument("--out", "-o", default="")
    s.add_argument("--force", action="store_true")
    s.add_argument("--kb-redline", default="",
                   help="rfe 召回的红线 JSON 文件（v2p plan 自动注入；"
                        "提供后在核查卡加「合规闸门」节，全部为阻断）")
    s.set_defaults(func=cmd_card)

    s = sub.add_parser("manual", help="手测清单：静态扫描盲区的人工核验留痕")
    s.add_argument("--form", "-f", default="app", choices=list(FORM_LABEL))
    s.add_argument("--depth", "-d", default="",
                   choices=["", "D0", "D1", "D2", "D3", "D4"])
    s.add_argument("--out", "-o", default="")
    s.add_argument("--force", action="store_true")
    s.add_argument("--verify", default="",
                   help="校验已填清单：未勾选或缺截图路径则退出码 1")
    s.set_defaults(func=cmd_manual)

    s = sub.add_parser("redteam", help="生成破坏性测试步骤")
    s.add_argument("--form", "-f", default="app", choices=list(FORM_LABEL))
    s.add_argument("--n", type=int, default=12)
    s.set_defaults(func=cmd_redteam)

    s = sub.add_parser("scan", help="静态扫描已知崩坏模式（启发式）")
    s.add_argument("--path", "-p", required=True)
    s.add_argument("--json", action="store_true")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("stats", help="检查项统计")
    s.set_defaults(func=cmd_stats)
    return ap


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure") and not (os.name == "nt" and sys.stdout.isatty()):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
