# -*- coding: utf-8 -*-
"""拓竹百科：把"参数是什么、在哪、建议多少"做成两个形态共用的一份数据。

设计要点：
  * 两个形态**共用同一份文件**——挂件是独立进程，走共享 JSON 比 IPC 简单可靠
  * `where` 是**给用户看的路径**（"质量页 → 层高"），不是控件坐标。
    因为实测 Bambu 的设置面板大量是自绘控件，UIA 只认到 9 个文本、6 行参数，
    靠控件定位做不出覆盖全量的引导；文字路径不受这个限制
  * 词条只写**确认过的**内容，没确认就留空，不编

扩展方式：往 ENTRIES 里加词条；键名用 Bambu 的英文参数键（layer_height）
或用户会说的中文名（层高）都行，lookup() 两种都能查。
"""

_RE_CJK = None            # 懒加载，见 _has_cn()

# —— 通用词：单个词指不到具体参数，只命中它们时**不猜**，改反问 ——
# 实测「填充在哪」会被答成「速度页 → 抖动（XY轴） → 填充」（infill_jerk），
# 「速度」会命中速度表里的某个单元格——答错比不答更糟
GENERIC_WORDS = {
    '填充', '速度', '温度', '风扇', '层数', '图案', '厚度', '宽度', '长度',
    '密度', '流量', '加速度', '线宽', '角度', '方向', '类型', '支撑',
    '回抽', '接缝', '裙边', '外墙', '内壁', '外壁', '首层', '顶层', '底层',
    '顶面', '底面', '空驶', '冷却', '打印', '参数', '设置',
}

# 通用词 → 可能指向的参数（用来反问"你要哪个？"）

# —— 路径格式统一 ——
# 规则：每段都必须是**界面上真实的文字**，不给它加我们自己的后缀。
# 界面上那一栏叫「质量」，不叫「质量页」；那一块叫「层高」，不叫「层高分组」。
_TAB_ALIAS = {          # 我们以前用过的叫法 → 界面上的真实叫法
    # ★ 这里以前是反的：把「耗材丝」改写成「耗材」。但界面上根本没有叫
    # 「耗材」的一栏 —— UIA 里明明白白有「耗材丝」这个控件，官方语言包
    # （Tab.cpp 的 Filament）也译作「耗材丝」。方向反了的结果是 30 多条
    # 路径都在让用户去找一个不存在的栏目名（2026-09-12 全量体检抓出来的）。
    '耗材设置': '耗材丝', '耗材': '耗材丝', '耗材丝页': '耗材丝',
    '打印机设置': '打印机',
}
_DROP_TAIL = ('分组', '页')      # 段尾这些字是我们自己加的


def norm_path(s):
    """把 "质量页 → 层高分组 → 第一行" 规范成 "质量 → 层高 → 第 1 行"。

    三件事：
      * 去掉段尾的「页」「分组」（界面上没这两个字）
      * 统一页签叫法（耗材设置/耗材丝 → 耗材）
      * 折叠重复段（"支撑 → 支撑 → 支撑类型" → "支撑 → 支撑类型"）
    """
    raw = (s or '').strip()
    if not raw:
        return ''
    if '→' not in raw:
        return _TAB_ALIAS.get(raw, raw)
    out = []
    for seg in raw.split('→'):
        seg = seg.strip()
        if not seg:
            continue
        seg = _TAB_ALIAS.get(seg, seg)
        for tail in _DROP_TAIL:
            if len(seg) > len(tail) and seg.endswith(tail):
                seg = seg[:-len(tail)].strip()
        seg = re.sub(r'^第\s*(\d+)\s*行$', r'第 \1 行', seg)
        if seg and (not out or out[-1] != seg):
            out.append(seg)
    return ' → '.join(out)
RELATED = {
    '填充': ('sparse_infill_density', 'sparse_infill_pattern',
             'sparse_infill_speed', 'infill_direction'),
    '密度': ('sparse_infill_density', 'bottom_surface_density',
             'top_surface_density'),
    '速度': ('outer_wall_speed', 'inner_wall_speed', 'sparse_infill_speed',
             'travel_speed', 'initial_layer_speed'),
    '打印速度': ('outer_wall_speed', 'inner_wall_speed',
                 'sparse_infill_speed', 'travel_speed'),
    '温度': ('nozzle_temperature', 'hot_plate_temp',
             'nozzle_temperature_initial_layer'),
    '风扇': ('fan_min_speed', 'fan_max_speed', 'auxiliary_fan'),
    '层数': ('wall_loops', 'top_shell_layers', 'bottom_shell_layers'),
    '图案': ('sparse_infill_pattern', 'top_surface_pattern',
             'bottom_surface_pattern'),
    '线宽': ('line_width', 'outer_wall_line_width', 'inner_wall_line_width',
             'initial_layer_line_width'),
    '支撑': ('enable_support', 'support_type', 'support_threshold_angle',
             'support_base_pattern'),
    '回抽': ('retraction_length', 'retraction_speed'),
    '外墙': ('outer_wall_speed', 'outer_wall_line_width'),
    '外壁': ('outer_wall_speed', 'outer_wall_line_width'),
    '内壁': ('inner_wall_speed', 'inner_wall_line_width'),
    '接缝': ('seam_position', 'seam_gap'),
    '裙边': ('brim_width', 'brim_type', 'brim_object_gap'),
    '加速度': ('default_acceleration', 'outer_wall_acceleration',
               'travel_acceleration', 'initial_layer_acceleration'),
    '冷却': ('fan_min_speed', 'fan_max_speed', 'slow_down_layer_time'),
    '首层': ('initial_layer_print_height', 'initial_layer_speed',
             'nozzle_temperature_initial_layer'),
}

# 表格里的"格子参数"：界面上没有一行的名字是自己的（X/Y/Z 列的加速度、
# 10%~100% 的悬垂速度），拿标签去搜必然落空。这里给它们一个**人能看懂
# 的名字**，路径精确到"哪一格"，挂件报位置时就不用含糊其辞。
_AXIS = (('x', 'X'), ('y', 'Y'), ('z', 'Z'), ('e', 'E'))
CELL_NAMES = {}
CELL_PATHS = {}
for _pfx, _nm in (('machine_max_acceleration', '最大加速度'),
                  ('machine_max_jerk', '最大加加速度'),
                  ('machine_max_speed', '最大速度')):
    for _a, _an in _AXIS:
        CELL_NAMES['%s_%s' % (_pfx, _a)] = '%s %s 轴' % (_nm, _an)
        CELL_PATHS['%s_%s' % (_pfx, _a)] = '%s 轴' % _an
for _k, _pct in (('overhang_1_4_speed', '10%'),
                 ('overhang_2_4_speed', '25%'),
                 ('overhang_3_4_speed', '50%'),
                 ('overhang_4_4_speed', '75%'),
                 ('overhang_totally_speed', '100%')):
    CELL_NAMES[_k] = '悬垂速度 %s' % _pct
    CELL_NAMES['filament_' + _k] = '悬垂速度 %s（耗材侧）' % _pct
    # 路径末段必须是**界面上能看到的字**。这一格在「悬垂速度」那张表里，
    # 表头是 10%/25%/50%/75%/100% —— 说「10% 那一格」用户还能猜，
    # 说「悬垂速度（10% 那一列）」才是指着界面的字在说。
    CELL_PATHS[_k] = '悬垂速度（%s 那一列）' % _pct
    CELL_PATHS['filament_' + _k] = '悬垂速度（%s 那一列）' % _pct
CELL_NAMES['machine_max_printed_mass'] = '最大打印质量'
# 「这一行」是占位词，等于没说；让路径退回分组名（末段用参数自己的中文名）
CELL_NAMES['filament_bridge_speed'] = '桥接速度（耗材侧）'
CELL_NAMES['filament_enable_overhang_speed'] = '悬垂降速开关（耗材侧）'


def _junk_key(k):
    """参数清单里混进来的"预设名"——它们不是参数，别摆给用户看。

    例：GM012、Bambu Lab P1S 0.4 nozzle。扫描参数时按"配置项"抓的，
    机器预设的名字也长得像配置项。
    """
    if ' ' in k:
        return True
    if _has_cn(k) is False and k.replace('_', '').isupper():
        return True
    return False


def _has_cn(s):
    """字符串里有没有汉字。用来判断"这是界面标签"还是"这是英文键"。"""
    global _RE_CJK
    if _RE_CJK is None:
        import re
        _RE_CJK = re.compile(r'[\u4e00-\u9fff]')
    return bool(_RE_CJK.search(s or ''))


import re

ENTRIES = {
    # ---- 质量 ----
    'layer_height': {
        'cn': '层高', 'label': '层高', 'field': 0, 'layer': 'process',
        'where': '质量 → 层高 → 第 1 行',
        'desc': '每一层的厚度。质量与速度的平衡点：越薄越精细、越慢。',
        'range': '0.08–0.28 mm（0.4 喷嘴）；常用 0.2'},
    'initial_layer_print_height': {
        'cn': '首层层高', 'label': '层高', 'field': 1, 'layer': 'process',
        'where': '质量 → 层高 → 第 2 行（首层）',
        'desc': '只有第一层的厚度，决定附着力。一般等于或略大于层高。',
        'range': '0.2–0.3 mm'},
    'line_width': {
        'cn': '默认线宽', 'label': '线宽', 'field': 0, 'layer': 'process',
        'where': '质量 → 线宽 → 默认',
        'desc': '默认挤出线宽，通常取喷嘴直径的 1.0–1.25 倍。',
        'range': '0.4–0.5 mm（0.4 喷嘴）'},
    'outer_wall_line_width': {
        'cn': '外墙线宽', 'label': '线宽', 'field': 2, 'layer': 'process',
        'where': '质量 → 线宽 → 外墙',
        'desc': '只有外轮廓那一圈用这个线宽，调细一点表面更细腻。',
        'range': '0.4–0.45 mm'},
    'wall_loops': {
        'cn': '墙层数', 'label': '墙层数', 'field': 0, 'layer': 'process',
        'where': '强度 → 墙 → 墙层数',
        'desc': '外轮廓绕几圈。圈数越多越结实，也越费时间。',
        'range': '2–4（常用 2 或 3）'},
    'sparse_infill_density': {
        'cn': '稀疏填充密度', 'label': '稀疏填充', 'field': 0,
        'layer': 'process',
        'where': '强度 → 稀疏填充 → 稀疏填充密度',
        'desc': '内部填充的疏密。承力件调高，摆件 10–15% 就够。',
        'range': '0–100%（常用 15%）'},
    'sparse_infill_pattern': {
        'cn': '稀疏填充图案', 'label': '稀疏填充', 'field': 1,
        'layer': 'process',
        'where': '强度 → 稀疏填充 → 稀疏填充图案',
        'desc': '填充的走线形状。网格通用；螺旋（gyroid）各向同性更结实；'
                '蜂窝省时间。',
        'range': '网格 / 螺旋 / 蜂窝 / 立方体…'},
    'top_shell_layers': {
        'cn': '顶部外壳层数', 'label': '顶部外壳', 'field': 0,
        'layer': 'process',
        'where': '强度 → 顶部/底部外壳 → 顶部外壳层数',
        'desc': '顶面实心层的层数，太少会透出填充纹理（俗称"露填充"）。',
        'range': '3–5'},
    'bottom_shell_layers': {
        'cn': '底部外壳层数', 'label': '底部外壳', 'field': 0,
        'layer': 'process',
        'where': '强度 → 顶部/底部外壳 → 底部外壳层数',
        'desc': '底面实心层层数，影响底面平整度和强度。',
        'range': '3–5'},

    # ---- 支撑 ----
    'enable_support': {
        'cn': '支撑', 'label': '支撑', 'field': None, 'layer': 'process',
        # ★ 界面上这一行叫「开启支撑」，不是「启用支撑」（官方 label_cn 也是
        #   开启支撑）。以前写错这一个字，搜索永远搜不到，才会连试好几轮、
        #   最后落在模糊匹配上（用户报的"搜了 3 次还找错地方"就是这个）。
        'where': '支撑 → 开启支撑',
        'desc': '悬空结构下方自动加可拆的支撑。有悬垂才需要开。',
        'range': '开 / 关'},
    'support_type': {
        'cn': '支撑类型', 'label': '支撑', 'field': None, 'layer': 'process',
        'where': '支撑 → 支撑类型',
        'desc': '树状支撑省料、接触面小、好拆；普通支撑更稳但费料。',
        'range': '树状（自动）/ 普通（自动）'},
    'support_threshold_angle': {
        'cn': '支撑阈值角度', 'label': '支撑阈值角', 'field': 0,
        'layer': 'process',
        'where': '支撑 → 支撑阈值角度',
        'desc': '倾斜超过这个角度才需要支撑。调大则支撑更少。',
        'range': '30–55°（常用 45°）'},
    'support_on_build_plate_only': {
        'cn': '仅在打印板上支撑', 'label': '支撑', 'field': None,
        'layer': 'process',
        # 界面上这一行叫「仅在打印板生成」（官方 label_cn 一致，2026-10-11 实测搜得到）
        'where': '支撑 → 仅在打印板生成',
        'desc': '支撑只从打印板长起来，不在模型表面生根，拆完表面更干净。',
        'range': '开 / 关'},

    # ---- 附着 / 裙边 ----
    'brim_type': {
        'cn': 'Brim 类型', 'label': 'Brim', 'field': None, 'layer': 'process',
        'where': '其他 → 热床粘接 → Brim类型',
        'desc': '在模型底部加一圈外扩的裙边增加附着力，防翘边。',
        'range': '自动 / 外圈 / 内圈 / 无'},
    'brim_width': {
        'cn': 'Brim 宽度', 'label': 'Brim', 'field': 1, 'layer': 'process',
        # 界面上没有空格：「Brim宽度」（写成「Brim 宽度」搜不到）
        'where': '其他 → 热床粘接 → Brim宽度',
        'desc': '裙边往外扩多少。越大附着力越强，也越费料越难撕。',
        'range': '3–10 mm'},

    # ---- 温度 ----
    'nozzle_temperature': {
        'cn': '喷嘴温度', 'label': '喷嘴', 'field': 0, 'layer': 'filament',
        'where': '耗材丝 → 打印温度 → 喷嘴（其他层）',
        'desc': '正常打印时喷嘴的温度。不同耗材差很多，改动前先确认耐温。',
        'range': 'PLA 190–230 / PETG 230–260 / ABS 240–280 ℃'},
    'nozzle_temperature_initial_layer': {
        'cn': '首层喷嘴温度', 'label': '喷嘴', 'field': 1, 'layer': 'filament',
        'where': '耗材丝 → 打印温度 → 喷嘴（首层）',
        'desc': '只有第一层的喷嘴温度，稍高一点有助于附着。',
        'range': '比正常高 5–10 ℃'},
    'hot_plate_temp': {
        'cn': '热床温度', 'label': '热床', 'field': 0, 'layer': 'filament',
        # 界面上这一行不叫「热床」——是「光面PEI打印板 / 高温打印板」那张表的
        # 「其他层」列（源码行名，见 tab_row）
        'where': '耗材丝 → 打印温度 → 光面PEI打印板 / 高温打印板（其他层）',
        'desc': '打印板温度，直接影响附着和翘边。',
        'range': 'PLA 55–65 / PETG 70–80 / ABS 90–110 ℃'},

    # ---- 风扇 ----
    'fan_min_speed': {
        'cn': '风扇最小速度', 'label': '风扇', 'field': 0, 'layer': 'filament',
        'where': '冷却模式 → 部件冷却风扇 → 最小风扇速度阈值',
        'desc': '最小风扇转速。太高易翘边，太低散热不足。',
        'range': 'PLA 20–100% / PETG 20–50% / ABS 0–20%'},
    'fan_max_speed': {
        'cn': '风扇最大速度', 'label': '风扇', 'field': 1, 'layer': 'filament',
        'where': '冷却模式 → 部件冷却风扇 → 最大风扇速度阈值',
        'desc': '允许的最大风扇转速，通常只在悬垂/桥接时拉满。',
        'range': 'PLA 100% / PETG 50–80% / ABS 20–40%'},

    # ---- 速度 ----
    'outer_wall_speed': {
        'cn': '外墙速度', 'label': '外墙', 'field': 0, 'layer': 'process',
        'where': '速度 → 其他层速度 → 外墙',
        'desc': '外轮廓的打印速度。调慢最明显地提升表面质量。',
        'range': '50–120 mm/s'},
    'sparse_infill_speed': {
        'cn': '稀疏填充速度', 'label': '稀疏填充', 'field': 0,
        'layer': 'process',
        'where': '速度 → 其他层速度 → 稀疏填充',
        'desc': '内部填充速度，一般可以比外墙快很多。',
        'range': '150–270 mm/s'},
    'initial_layer_speed': {
        'cn': '首层速度', 'label': '首层', 'field': 0, 'layer': 'process',
        'where': '速度 → 首层速度 → 首层',
        'desc': '第一层的速度。慢一点附着更牢，别超过 60。',
        'range': '30–60 mm/s'},

    # ---- 其它 ----
    'seam_position': {
        'cn': '接缝位置', 'label': '接缝', 'field': None, 'layer': 'process',
        'where': '质量 → 接缝',
        'desc': '外墙起止点的位置，决定那条可见竖缝藏在哪里。',
        'range': '对齐 / 最近 / 背面 / 随机'},
    'ironing_type': {
        'cn': '熨烫', 'label': '熨烫', 'field': None, 'layer': 'process',
        'where': '质量 → 熨烫',
        'desc': '顶层再走一遍不出料的热喷嘴，把表面烫平。慢，但效果好。',
        'range': '不熨烫 / 仅顶面 / 仅最顶面'},
    'print_sequence': {
        'cn': '打印顺序', 'label': '打印顺序', 'field': None,
        'layer': 'process',
        'where': '其他 → 特殊模式 → 打印顺序',
        'desc': '逐件打印（打完一个再打下一个）vs 逐层打印（所有件同层一起走）。',
        'range': '逐层 / 逐件'},
}

# 中文名 → 英文键 的反查表（用户会直接说"层高"）
_BY_CN = {}
for _k, _v in ENTRIES.items():
    _BY_CN.setdefault(_v.get('cn') or _k, _k)

_CN_INDEX = None


def cn_index():
    """中文界面名 → 英文键，**覆盖全部官方参数**（不只手写那几十条）。

    为什么必须有：手写的 `_BY_CN` 只有几十条，而用户嘴里说的是**界面上的中文**
    （「开启支撑」）。查不到的时候就落到"按中文名匹配参数清单"那条路上，而
    那条路匹配出来的词条**key 是空的** —— 于是 tab_path / 行号 / 路径全部落空。
    实测「开启支撑」就栽在这：词条查得到、可就是定位不了。
    """
    global _CN_INDEX
    if _CN_INDEX is None:
        idx = {}
        for k, off in _load_official().items():
            for nm in ((off.get('label_cn') or '').strip(),
                       (off.get('label') or '').strip()):
                if nm:
                    idx.setdefault(nm, k)
        _CN_INDEX = idx
    return _CN_INDEX

# 用户嘴里的话 → 官方参数键。
#
# 官方标签是印刷体（「稀疏填充密度」「喷嘴温度」「桥接」），用户说的是
# 口语（「填充密度」「喷头温度」），两者对不上。实测「填充密度设50%」
# 「回抽长度在哪」「蜂窝和3d蜂窝」都因为差一两个字被判定成"没认出来"。
# 这里只收**确认过指向唯一参数**的说法，模糊的（只说"密度""brim"）不收，
# 答错比不答更糟。
ALIASES = {
    # —— 2026-09-12 新人实测补：他们说"裙边/外壁/回抽/接缝/底部层数"，
    # 我们库里是"Brim/外墙/回抽长度/接缝位置/底部外壳层数"，差一两个字
    # 就完全认不出（30 句新人提问里 37% 栽在这上面）
    '裙边': 'brim_width', '裙边宽': 'brim_width', '裙边宽度': 'brim_width',
    '裙边类型': 'brim_type', '底部裙边': 'brim_width',
    '回抽': 'retraction_length', '回抽量': 'retraction_length',
    '接缝': 'seam_position', '接缝位置': 'seam_position',
    '底部层数': 'bottom_shell_layers', '底层数': 'bottom_shell_layers',
    '顶部层数': 'top_shell_layers', '顶层数': 'top_shell_layers',
    '顶面层数': 'top_shell_layers', '底面层数': 'bottom_shell_layers',
    '外壁速度': 'outer_wall_speed', '内壁速度': 'inner_wall_speed',
    '外壁线宽': 'outer_wall_line_width', '内壁线宽': 'inner_wall_line_width',
    '外壁': 'outer_wall_speed', '内壁': 'inner_wall_speed',
    '支撑角度': 'support_threshold_angle',
    '支撑阈值角': 'support_threshold_angle',
    '支撑密度': 'support_base_pattern_spacing',
    '筏层': 'raft_layers', '底座': 'raft_layers', '底盘': 'raft_layers',
    '流量比例': 'filament_flow_ratio', '流量': 'filament_flow_ratio',
    '象脚补偿': 'elefant_foot_compensation',
    '首层线宽': 'initial_layer_line_width',
    '空驶': 'travel_speed', '空驶速度': 'travel_speed',
    '加速度': 'default_acceleration',
    '尺寸补偿': 'xy_contour_compensation',
    '圆孔补偿': 'xy_hole_compensation',
    '墙数': 'wall_loops', '墙层数': 'wall_loops',
    '填充重叠': 'infill_wall_overlap', '填充与墙重叠': 'infill_wall_overlap',
    '首层温度': 'nozzle_temperature_initial_layer',
    '首层喷嘴温度': 'nozzle_temperature_initial_layer',
    '热床': 'hot_plate_temp',
    '冷却': 'fan_min_speed', '风扇': 'fan_min_speed',
    '辅助风扇': 'auxiliary_fan',
    'Z轴抬升': 'z_hop', 'Z抬升': 'z_hop',

    '填充密度': 'sparse_infill_density',
    '填充率': 'sparse_infill_density',
    '填充图案': 'sparse_infill_pattern',
    '填充形状': 'sparse_infill_pattern',
    '蜂窝': 'sparse_infill_pattern',
    '3d蜂窝': 'sparse_infill_pattern',
    '螺旋填充': 'sparse_infill_pattern',
    '网格填充': 'sparse_infill_pattern',
    '喷头温度': 'nozzle_temperature',
    '喷头': 'nozzle_temperature',
    '首层高': 'initial_layer_print_height',
    '首层高度': 'initial_layer_print_height',
    '初始层高': 'initial_layer_print_height',
    '回抽长度': 'retraction_length',
    '回抽距离': 'retraction_length',
    '回抽速度': 'retraction_speed',
    '支撑类型': 'support_type',
    '支撑图案': 'support_base_pattern',
    'brim宽度': 'brim_width',
    'brim宽': 'brim_width',
    '顶层': 'top_shell_layers',
    '顶面层数': 'top_shell_layers',
    '底面层数': 'bottom_shell_layers',
    '墙数': 'wall_loops',
    '外墙线宽': 'outer_wall_line_width',
    '内墙线宽': 'inner_wall_line_width',
    '外墙速度': 'outer_wall_speed',
    '内墙速度': 'inner_wall_speed',
    '支撑速度': 'support_speed',
    '逐件打印': 'print_sequence',
    '接缝位置': 'seam_position',
    '底部外壳': 'bottom_shell_layers',
    '顶部外壳': 'top_shell_layers',
    '桥接速度': 'bridge_speed',
    '喷嘴上限': 'nozzle_temperature_range_high',
    '喷嘴温度上限': 'nozzle_temperature_range_high',
    '喷嘴温度下限': 'nozzle_temperature_range_low',
    '热床温度': 'hot_plate_temp',
    '填充速度': 'sparse_infill_speed',
    '顶面速度': 'top_surface_speed',
    '首层速度': 'initial_layer_speed',
    '空驶速度': 'travel_speed',
    '填缝速度': 'gap_infill_speed',
}


def lookup(name):
    """按英文键或中文名查词条；返回 settings_guide 兼容的字典。"""
    orig = (name or '').strip()
    key = orig
    if not key:
        return None
    # 口语别名先在入口翻译成官方键，后面的路径/说明/定位才有一致的数据
    alias = ALIASES.get(key)
    if alias:
        key = alias
    item = ENTRIES.get(key)
    if item is None:
        # 用户说的中文名 → 手写词条的英文键。**要记下来**：后面的
        # tab_path / 行号白名单都要英文键，只有中文名的话全查不到
        # （「层高」就是因此一直没被 ROW_VERIFIED 命中过）
        # ★ 手写表查不到就查**全量**中文索引（官方 label_cn）——「开启支撑」
        #   这种只有官方名字、没手写词条的说法就靠这一步落到英文键上。
        _ek = _BY_CN.get(key, '') or cn_index().get(key, '')
        item = ENTRIES.get(_ek)
        if item is not None:
            key = _ek
        elif _ek and (_from_catalog(_ek) or _from_official(_ek)):
            key = _ek
    if item is None:
        item = _from_catalog(key)
    if item is None:
        item = _from_official(key)          # 官方源码里的 711 个参数
    if item is None:
        return None
    out = dict(item)
    out.setdefault('key', key)
    # 官方源码里的页签/单位/说明优先补进来（比手写的更权威）
    off = _official(key) or _official(out.get('label') or '')
    if off:
        # 界面标签必须是中文串：UIA 是拿它去中文界面里搜控件的。
        # 扫描出来的参数清单（catalog）有一半没有中文名，label 会退化成
        # 英文键（bridge_speed），拿它去搜中文界面 100% 落空——
        # 官方源码里有中文标签就用官方的。
        newlbl = (off.get('label_cn') or '').strip()
        if newlbl and not _has_cn(out.get('label')):
            out['label'] = newlbl
        cat = (off.get('cat_cn') or '').strip()
        lab = (off.get('label_cn') or off.get('label') or '').strip()
        if not out.get('where') and cat and lab:
            out['where'] = cat + ' → ' + lab
        if not out.get('desc') and off.get('desc_cn'):
            out['desc'] = off['desc_cn']
        if not out.get('range') and (off.get('min') or off.get('max')):
            out['range'] = '%s – %s %s' % (off.get('min', ''), off.get('max', ''),
                                           off.get('unit', ''))
        out.setdefault('unit', off.get('unit', ''))
        out.setdefault('category_cn', off.get('cat_cn', ''))
    if alias and not (out.get('cn') or '').strip():
        # 用户说的那个词就是最好的名字：官方对 retraction_length 只给了
        # 半截标签「长度」，回答写成【回抽长度】才说得通
        out['cn'] = orig
    if not (out.get('cn') or '').strip() and CELL_NAMES.get(key):
        out['cn'] = CELL_NAMES[key]
    # ★ `cn` 统一补全：官方 / 参数清单来的词条，中文名有时只落在
    #   `label_cn` 或 `label` 上，`cn` 是**空串**。而挂件和 intent 都按
    #   `cn` 取名字，拿到空串就当成"没认出来" —— 实测
    #   「把支撑打开，悬垂降速关掉」整句因此掉进了症状库（回了一堆
    #   翘边/桥接的建议，就是不执行）。这一处补全，两个消费方一起好。
    if not (out.get('cn') or '').strip():
        for _f in ('label_cn', 'label'):
            _v = (out.get(_f) or '').strip()
            if _has_cn(_v):
                out['cn'] = _v
                break
    if key not in ENTRIES:
        # 路径优先级：手写词条（带"第一行/第二行"这种细节）> Tab.cpp 的
        # 真实界面结构 > PrintConfig 的 category（Slic3r 老分组，会把
        # Brim 说成在「支撑」页）
        page, group = tab_path(key)
        if page:
            last = (CELL_PATHS.get(key)
                    or tab_row(key)
                    or CELL_NAMES.get(key)
                    or (out.get('cn') or '').strip()
                    or ((out.get('label') or '').strip()
                        if _has_cn(out.get('label')) else ''))
            # 最后一个字说不出来就只报到分组：源码里这些行本来就没有行名
            # （X/Y/Z 列的加速度、10%/25% 的悬垂速度），硬凑一个名字等于编
            out['where'] = ' → '.join([x for x in (page, group, last) if x])
    if not out.get('where'):
        # 官方源码里没有 category，就是界面上没有这一项（内部参数，
        # 只能通过预设/切片参数改）。明确写出来，别让用户以为是我们没查。
        out['where'] = '不在 Bambu 界面上（内部参数，用切片参数 key=value 改）'
    # 最后统一过一遍格式：每段都用界面上真实的字（不带"页""分组"），
    # 重复段折叠掉（"支撑 → 支撑 → 支撑类型" → "支撑 → 支撑类型"）
    out['where'] = norm_path(out['where'])
    if not (out.get('label') or '').strip():
        out['label'] = key
    out.setdefault('field', 0)
    out.setdefault('desc', '')
    out.setdefault('range', '')
    out.setdefault('where', '')
    out['key'] = key
    return out


_OFFICIAL = None

_TABS = None


def _load_tabs():
    """官方 Tab.cpp 提取的真实界面结构：参数键 → 页签/分组。"""
    global _TABS
    if _TABS is None:
        try:
            import json
            with open(_data_file('bambu_wiki_tabs.json'),
                      encoding='utf-8') as f:
                _TABS = json.load(f)
        except (OSError, ValueError):
            _TABS = {}
    return _TABS


def tab_path(key):
    """这个参数在界面里的（页签, 分组）。不在界面上就返回两个空串。"""
    t = _load_tabs().get((key or '').strip()) or {}
    page = (t.get('page_cn') or t.get('page') or '').strip()
    group = (t.get('group_cn') or t.get('group') or '').strip()
    return page, group


def tab_row(key):
    """这一行的中文行名（源码里 `line = { L("行名") }` 那种）。

    表格里的一行往往管着两个输入框（首层/其他层），行名比参数名更接近
    用户眼睛看到的东西：hot_plate_temp → 「光面PEI打印板/高温打印板」。
    """
    t = _load_tabs().get((key or '').strip()) or {}
    return (t.get('row_cn') or t.get('row') or '').strip()


def in_ui(key):
    """参数是不是真的能在 Bambu 界面上找到（Tab.cpp 说了算）。"""
    return bool(_load_tabs().get((key or '').strip()))


_GROUPS = None


def group_names():
    """界面上所有分组标题的名字（来自 Tab.cpp 的 group_cn）。

    用来认"某一行落在哪个分组里"：界面上"够宽够靠左"的东西不止分组标题
    （容器面板、预设名那一行都算），但它们**不在这个集合里**，一卡就干净了。
    """
    global _GROUPS
    if _GROUPS is None:
        _GROUPS = {(t.get('group_cn') or t.get('group') or '').strip()
                   for t in _load_tabs().values()}
        _GROUPS.discard('')
    return _GROUPS


def _data_file(name):
    """找随程序一起分发的数据文件。

    打包成 exe 后模块在 PYZ 里，__file__ 指向 _internal 目录，但不同
    PyInstaller 版本对 __file__/__cached__ 的处理不一致——三个位置都试，
    否则会静默退回"只有 26 条手写词条"的状态（挂件看起来还能用，
    但其实丢掉了 711 个官方参数）。
    """
    import os
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.path.join(here, name)]
    base = getattr(sys, '_MEIPASS', '')
    if base:
        cands.append(os.path.join(base, name))
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    cands.append(os.path.join(exe_dir, name))
    for p in cands:
        if os.path.isfile(p):
            return p
    return cands[0]


def _load_official():
    """官方源码提取的 711 个参数（页签/标签/说明/单位/范围）。"""
    global _OFFICIAL
    if _OFFICIAL is None:
        try:
            import json
            p = _data_file('bambu_wiki_paths.json')
            with open(p, encoding='utf-8') as f:
                _OFFICIAL = json.load(f)
        except (OSError, ValueError):
            _OFFICIAL = {}
    return _OFFICIAL


def _official(key):
    if not key:
        return None
    return _load_official().get(key.strip())


def _from_official(key):
    off = _official(key)
    if not off:
        return None
    # 官方语言包里有一批参数页签/标签是**一个空格**（supports_enable、
    # pad_*、hollowing_* 这些 Bambu 没放进界面的遗留参数）。不 strip 的话
    # 会拼出「 页 →  」这种路径，回答就成了「它在：页 →」。
    cat = (off.get('cat_cn') or off.get('category') or '').strip()
    lbl = (off.get('label_cn') or off.get('label') or '').strip()
    # label 用中文：UI 定位是拿这个去中文界面里找控件的
    return {'key': key, 'label': lbl or key,
            'cn': (off.get('label_cn') or '').strip(), 'field': 0,
            'where': norm_path(('%s → %s' % (cat, lbl)) if (cat and lbl)
                               else ''),
            'desc': off.get('desc_cn') or off.get('tooltip') or '',
            'range': off.get('unit') or ''}


_CATALOG_INDEX = None


def _catalog_index():
    """参数清单（491 个）的 键→(层, 数据) 索引。

    原来每次 lookup 都重新读+解析一遍 242KB 的 JSON，挂件列一次词条就
    解析 26 遍；缓存成一份。
    """
    global _CATALOG_INDEX
    if _CATALOG_INDEX is None:
        idx = {}
        try:
            import json
            p = _data_file('bambu_wiki_catalog.json')
            with open(p, encoding='utf-8') as f:
                cat = json.load(f)
            for layer, items in cat.items():
                for k, v in items.items():
                    if _junk_key(k):
                        continue          # 预设名 / 机器串，不是参数
                    idx[k] = (layer, v)
        except (OSError, ValueError):
            pass
        _CATALOG_INDEX = idx
    return _CATALOG_INDEX


def _from_catalog(key):
    """词条里没有的，退回扫描出来的参数清单（只有名字和默认值）。"""
    got = _catalog_index().get(key)
    if not got:
        return None
    layer, data = got
    cn = (data.get('cn') or '').strip()
    return {'key': key, 'cn': cn, 'label': cn or key, 'field': 0,
            'layer': layer, 'default': data.get('default'),
            'where': '', 'desc': '', 'range': ''}


def all_entries():
    """返回全部词条，供百科界面列表用。"""
    return [lookup(k) for k in ENTRIES]


def find_in_text(text):
    """在一句话里找参数名。中文名、英文键、官方标签都认。

    挂件原来是"遍历 8 个硬编码参数名看谁在句子里"，所以用户说
    "外墙线宽"、"回抽长度" 这种一律回"我还不知道这个参数"。
    这里改成拿全量参数表（711 个）+ 口语别名去匹配，取命中名字最长的
    那个——「外墙线宽」不能被「线宽」截胡，「首层高」不能被「层高」截胡
    （答错比不答更糟）。

    两条闸门，都是为了"宁可不认，也别认错"：
      * 命中 2 个字的名字，必须占整句的 40% 以上（防「默认加速度」
        被 2 字的「默认」截胡）
      * 英文键要 4 个字符以上才认（用户直接打键名时才会那么长）
    """
    t = (text or '').strip()
    if not t:
        return None
    direct = lookup(t)
    if direct:
        return direct
    tl = t.lower()
    found = {}          # 命中的字面 → (字数, 键, 是否人工维护)

    def add(nm, key, curated=False):
        nm = (nm or '').strip()
        if len(nm) < 2:
            return
        # 统一用小写比对：中文不受影响，还能让「Brim宽度」认出「brim宽度」
        needle = nm.lower()
        if needle not in tl:
            return
        if curated:
            # 人工维护的名字（层高 / 支撑 / 熨烫 / 填充密度）就是用户真会
            # 说的词，2 个字也认
            pass
        elif len(needle) < 3 and len(needle) / max(1, len(t)) < 0.5:
            # 参数表里的 2 字标签不认死理：占整句不到一半就放弃，
            # 免得「默认加速度」被 2 字的「默认」截胡
            return
        elif not _has_cn(needle) and len(needle) < 4:
            # 英文键要 4 个字母以上（用户直接打键名才会那么长），
            # 否则 abs / bed 这种短键在中文句子里乱命中
            return
        old = found.get(needle)
        if old is None or len(needle) > old[0] or (
                len(needle) == old[0] and curated and not old[2]):
            found[needle] = (len(needle), key, curated)

    for k, v in ENTRIES.items():
        add(v.get('cn') or k, k, True)
    for alias, k in ALIASES.items():
        # 命中别名时用**别名本身**去查：lookup() 会把它翻译成官方键，
        # 顺便把 cn 填成用户说的那个词（否则 nozzle_temperature_range_high
        # 这种官方没给中文名的，取出来 cn 是空的，调用方就当成"没认出来"）
        add(alias, alias, True)
    for k, (layer, data) in _catalog_index().items():
        add(data.get('cn'), k)
    for k, v in _load_official().items():
        add(v.get('label_cn'), k)
        add(v.get('label'), k)
        if len(k) >= 4:
            add(k, k)
    if not found:
        return None
    needle, best = max(found.items(), key=lambda kv: (kv[1][0], kv[1][2]))
    # 只命中了"通用词"就不猜具体参数：实测「填充在哪」会被答成
    # 「速度页 → 抖动（XY轴） → 填充」（infill_jerk）——答错比不答更糟。
    # 交给调用方反问一句"填充相关的有：密度/图案/速度/方向，你要哪个？"
    # 只对"非人工别名"生效：裙边/回抽/接缝 这些是我们**特意**映射的，
    # 该直接答；而「填充」「速度」这种碰巧撞上某个参数标签的才要反问
    if not best[2] and needle.strip().lower() in GENERIC_WORDS:
        return None
    return lookup(best[1])


def answer(item):
    """把词条组织成一句人话（挂件气泡里用的就是它）。"""
    if not item:
        return ''
    name = item.get('cn') or item.get('label_cn') or item.get('label') or ''
    desc = (item.get('desc') or '').strip()
    where = (item.get('where') or '').strip()
    key = item.get('key') or ''
    rng = (item.get('range') or '').strip()
    parts = []
    if desc:
        parts.append(desc)
    if rng:
        parts.append('建议：' + rng)
    if '不在 Bambu 界面上' in where:
        parts.append(f'Bambu 界面里没有这一项。要改的话，'
                     f'在拓竹助手的「参数需求」里写 {key}=值')
    elif where:
        parts.append('它在：' + where)
    return '【%s】' % name + '\n'.join(parts) if parts else '【%s】' % name


_LABEL_INDEX = None
_LABEL_NAMES = None


def _cn_of(key):
    """参数键 → 界面上的中文名（优先参数清单，其次官方语言包）。"""
    item = (_catalog_index().get(key) or (None, {}))[1]
    if item.get('cn'):
        return item['cn']
    return (_load_official().get(key) or {}).get('label_cn') or ''


def _label_bucket(label):
    """共用这个界面标签的参数：{参数键: 中文名}。

    按参数**键**去重（手写词条和官方数据会给同一个参数各记一次，按条数算
    会把「层高」数成 3 处，而界面上其实只有 2 行）。
    """
    global _LABEL_INDEX, _LABEL_NAMES
    if _LABEL_INDEX is None:
        buckets = {}

        def note(nm, key, cn=None):
            nm = (nm or '').strip()
            if nm:
                buckets.setdefault(nm, {})[key] = (cn or '').strip() or key

        for k, v in _load_official().items():
            note(v.get('label_cn'), k, _cn_of(k))
        for k, v in ENTRIES.items():
            note(v.get('label'), k, v.get('cn'))
        for k, (layer, data) in _catalog_index().items():
            note(data.get('cn'), k, data.get('cn'))
        _LABEL_NAMES = {k: dict(v) for k, v in buckets.items()}
        _LABEL_INDEX = {k: len(v) for k, v in buckets.items()}
    return _LABEL_NAMES.get((label or '').strip(), {})


def label_names(label, limit=3):
    """和这个标签同名的都有谁（中文名，去重，最多 limit 个）。

    用来说人话：「层高」在 Bambu 里有「层高」「首层层高」好几处同名。

    ⚠ 只收**短名字**（长度不超过关键词 + 3 个字）。共用同一个界面标签的
    参数里，有的是"同族短名"（支撑 / 支撑类型 / 支撑速度），有的是**一整句话**
    （「仅在打印板上支撑」）。后者放进"好几处同名"里就变成假话 —— 用户当场
    会问"它又不叫支撑"（实测被问过）。句子式的那种干脆不列。
    """
    kw = (label or '').strip()
    names = []
    for _k, cn in _label_bucket(label).items():
        if not cn or cn in names:
            continue
        if kw and (kw not in cn or len(cn) > len(kw) + 3):
            continue
        if cn:
            names.append(cn)
    return names[:limit]


# 已经对着官方界面结构核对过"组里第几个输入框"的参数。
# 判据：官方 Tab.cpp 的组内行顺序 + 界面实测的输入框个数一致
#   Layer height 组：第 1 行 layer_height、第 2 行 initial_layer_print_height
#   （实测这一组 UIA 上正好 2 个输入框，值 0.12 / 0.2）
# 只有在这里面**而且行号对得上**的，才允许在"标签重名"的情况下直接改；
# 没核对过的一律拒改 —— 改错参数比不帮更糟。
ROW_VERIFIED = {
    'layer_height': 0,
    'initial_layer_print_height': 1,
    # 线宽组：源码行序 line_width → initial_layer_line_width →
    # initial_layer_infill_line_width → outer_wall_line_width → inner_wall →
    # top_surface → sparse_infill → internal_solid（第 9 行 support_line_width
    # 没开支撑时不显示）。
    # 实测该组界面值是 [0.42, 0.5, 0.42, 0.45, 0.42, 0.45, 0.42, 0.42]，
    # 和上面这个顺序的预设默认值逐个相等 —— 这是"第几个框"对得上的证据。
    'line_width': 0,
    'initial_layer_line_width': 1,
    'initial_layer_infill_line_width': 2,
    'outer_wall_line_width': 3,
    'inner_wall_line_width': 4,
    'top_surface_line_width': 5,
    'sparse_infill_line_width': 6,
    'internal_solid_infill_line_width': 7,
}


def row_index(key):
    """核对过行号的参数 → 它在那一组里是第几个输入框（0 起）；没核对过返回 None。"""
    return ROW_VERIFIED.get((key or '').strip())


_GROUP_KEYS = None


def _group_keys():
    """(页签, 分组) → 组里各参数的键，**顺序就是界面从上到下的行序**。

    依据（实测核对过，不是猜的）：Tab.cpp 抽出来的 json 里，键的出现顺序
    就是源码里那一行的顺序，而源码顺序 == 界面顺序。三条独立证据：
      * 手写核对过行号的 `ROW_VERIFIED` 10 条，和这里自动推出来的序号
        **逐条相等**（含线宽组 0..7）；
      * 「其他层速度」组推出来的顺序（外墙→内墙→小轮廓→小轮廓阈值→
        稀疏填充→内部实心填充→斜面填充速度→顶面→悬垂降速）和界面截图
        从上到下**完全一致**；
      * 「墙」「层高」两组同样对得上。
    所以"这个参数是组里第几行"这件事**不用再手工维护**，直接从数据推。
    """
    global _GROUP_KEYS
    if _GROUP_KEYS is None:
        out = {}
        for k, t in _load_tabs().items():
            g = ((t.get('page_cn') or t.get('page') or '').strip(),
                 (t.get('group_cn') or t.get('group') or '').strip())
            out.setdefault(g, []).append(k)
        _GROUP_KEYS = out
    return _GROUP_KEYS


def group_keys(key):
    """这个参数所在组里，全部参数的键（按界面行序）。不在界面上返回 []。"""
    t = _load_tabs().get((key or '').strip())
    if not t:
        return []
    g = ((t.get('page_cn') or t.get('page') or '').strip(),
         (t.get('group_cn') or t.get('group') or '').strip())
    return list(_group_keys().get(g) or [])


def row_order(key):
    """这个参数在它那一组里是**第几行**（0 起，按界面从上到下）。

    和 `row_index` 的区别：`row_index` 数的是"第几个输入框"（只核对过 10 条），
    这个是"第几行" —— 行里可能是输入框、勾选框、下拉框，**全部参数都能推**。
    """
    ks = group_keys(key)
    k = (key or '').strip()
    return ks.index(k) if k in ks else None


def group_is_unique(group_name):
    """这个分组名在**所有页签**上只出现一次吗（用来做"不跳转也能定位"的前提）。

    为什么要它：`group_rows()` 是按**组名**在界面上找那一组，而「高级」这种
    名字在好几页都有 —— 不跳转就直接按组名找，可能认到别的页那一组去。
    只有组名全局唯一的（稀疏填充 / 支撑 / 层高 / 线宽…）才敢"不开搜索也动手"。
    """
    g = (group_name or '').strip()
    if not g:
        return False
    return sum(1 for (_page, group) in _group_keys() if group == g) == 1


def label_conflict(label):
    """有多少个参数共用这个界面标签。

    UI Automation 只能按标签找控件，重名时会命中第一个——「层高」和
    「首层层高」标签都是「层高」，要改首层高就可能改到层高上。
    超过 1 就说明这个标签不能用来定位。返回 0 表示没有这个标签。
    """
    global _LABEL_INDEX
    if not label:
        return 0
    return len(_label_bucket(label))


def related(text):
    """这句话里有没有"通用词"；有就返回 (词, [相关参数名…])，否则 None。"""
    t = (text or '').strip()
    if not t:
        return None
    # 命中的词里取最长、且出现位置最靠前的那个：
    # "风扇速度"同时命中「风扇」和「速度」，要选前面那个才不答非所问
    hits = [(w, t.index(w)) for w in RELATED if w in t]
    if not hits:
        return None
    hits.sort(key=lambda x: (-len(x[0]), x[1]))
    for word, _pos in hits:
        if word in t:
            names = []
            for k in RELATED[word]:
                item = lookup(k) or {}
                nm = item.get('cn') or item.get('label') or k
                if nm and nm not in names:
                    names.append(nm)
            if names:
                return word, names[:4]
    return None


def _window(t, size):
    """把整句切成跟候选名字等长的片段，用于编辑距离比较。"""
    if size <= 0 or len(t) <= size:
        return [t]
    return [t[i:i + size] for i in range(len(t) - size + 1)]


_NAME_INDEX = None


def name_conflict(name):
    """有多少个参数**自己就叫这个名字**。

    实测「风扇速度」有 7 个参数同名（部件冷却/排风扇/…），随便挑一个答
    就是答非所问；这种情况要反问，不要猜。
    """
    global _NAME_INDEX
    nm = (name or '').strip()
    if not nm:
        return 0
    if _NAME_INDEX is None:
        idx = {}
        for k, v in _load_official().items():
            for key in ((v.get('label_cn') or '').strip(),):
                if key:
                    idx[key] = idx.get(key, 0) + 1
        for k, (layer, data) in _catalog_index().items():
            key = (data.get('cn') or '').strip()
            if key:
                idx[key] = idx.get(key, 0) + 1
        for k, v in ENTRIES.items():
            key = (v.get('cn') or '').strip()
            if key:
                idx[key] = idx.get(key, 0) + 1
        _NAME_INDEX = idx
    return _NAME_INDEX.get(nm, 0)


def _dl_distance(a, b):
    """Damerau-Levenshtein（支持换位）：nearest() 用得到，跟 materials
    里那份算法一致（换位要留前两行，否则 pteg→petg 会算成 2）。"""
    a, b = (a or '').lower(), (b or '').lower()
    la, lb = len(a), len(b)
    if not la:
        return lb
    if not lb:
        return la
    prev2, prev = None, list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if (i > 1 and j > 1 and a[i - 1] == b[j - 2]
                    and a[i - 2] == b[j - 1]):
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[lb]


def nearest(text, n=3):
    """认不出时给最接近的几个参数名——别让人对着"不知道"发愣。

    用相似度（SequenceMatcher）而不是"编辑距离≤1"：像「底部层书在哪」
    这种同音错字，编辑距离早就超了，但相似度还有 0.8，够给建议。
    """
    import difflib
    t = (text or '').strip()
    if len(t) < 2:
        return []
    cands = {}
    for k, v in _load_official().items():
        for nm in (v.get('label_cn'), v.get('label')):
            if nm and len(nm) >= 2:
                cands.setdefault(nm, k)
    for k, item in ENTRIES.items():
        if item.get('cn'):
            cands.setdefault(item['cn'], k)
    for a, k in ALIASES.items():
        cands.setdefault(a, k)
    out = []
    for nm, k in cands.items():
        if nm in t:
            out.append((0.0, nm, k))
            continue
        best = 0.0
        for w in _window(t, len(nm)):
            r = difflib.SequenceMatcher(None, nm, w).ratio()
            if r > best:
                best = r
        # 相似度太低就别硬凑候选（"这个参数是什么意思"不该回"你是要找 墙数 吗"）
        if best >= 0.65:
            out.append((1.0 - best, nm, k))
    out.sort(key=lambda x: (x[0], len(x[1])))
    seen, res = set(), []
    for score, nm, _k in out:
        if score > 0.5:
            continue
        if nm in seen:
            continue
        seen.add(nm)
        res.append(nm)
        if len(res) >= n:
            break
    return res


# 目的 → 该动哪几个参数（新人常常说不出参数名，只说"想更快/更结实"）
GOALS = (
    (('快', '提速', '太慢', '时间长', '省时间'),
     ('outer_wall_speed', 'inner_wall_speed', 'sparse_infill_speed',
      'travel_speed')),
    (('结实', '强度', '承力', '不断', '太脆', '老是断', '容易断', '裂'),
     ('wall_loops', 'sparse_infill_density', 'top_shell_layers',
      'bottom_shell_layers')),
    (('表面', '细腻', '光泽', '层纹', '好看', '平整'),
     ('ironing_type', 'seam_position', 'layer_height',
      'outer_wall_line_width')),
    (('省料', '省材料', '轻一点', '空心'),
     ('sparse_infill_density', 'enable_support', 'brim_width')),
    (('翘边', '翘曲', '粘不住', '不粘', '掉下来'),
     ('hot_plate_temp', 'nozzle_temperature_initial_layer',
      'initial_layer_speed', 'brim_width')),
    (('拉丝', '抽丝', '挂丝'), ('retraction_length', 'retraction_speed')),
    (('放大', '缩小', '缩放', '大一点', '小一点'),
     ('xy_contour_compensation', 'xy_hole_compensation')),
)


def goal_of(text):
    """这句话表达的是什么目的？返回 (目的词, [参数名…]) 或 None。"""
    t = (text or '')
    for words, keys in GOALS:
        for w in words:
            if w in t:
                names = []
                for k in keys:
                    item = lookup(k) or {}
                    nm = item.get('cn') or item.get('label') or k
                    if nm:
                        names.append(nm)
                if names:
                    return w, names[:4]
    return None


def can_locate(label, key='', field=None):
    """这个标签能不能可靠地在 Bambu 界面上定位到。返回 (可否, 原因)。

    key 可省；省了就用标签反查参数，好把"标签跟分组标题同名"这层也查掉。
    field 是这个参数在它那一组里排第几个输入框（0 开始）：重名之所以能分开，
    靠的就是它——界面上一个分组标题下面，输入框是按行顺序排的。
    """
    nm = (label or '').strip()
    if not nm:
        return False, '没有界面标签'
    if not _has_cn(nm):
        cell = CELL_NAMES.get((key or '').strip())
        if cell:
            # 表格格子：界面上这一格确实存在，只是没有"一行文字"能搜
            return False, ('这是表格里的一格（%s），按文字定位不到，'
                           '标一次位置我就能改' % cell)
        # 源码里没有独立标签的参数（多数是速度表/加速度表里的单元格），
        # 界面搜不到，拿英文键去搜中文界面更是必然落空
        return False, '界面里没有独立标签（多半在表格里）'
    n = label_conflict(nm)
    if n > 1:
        # 重名，但行号是对着官方界面核对过的 → 说得清"第几个框"，可以改
        vk = (key or '').strip()
        if vk and vk in ROW_VERIFIED:
            want = ROW_VERIFIED[vk]
            if field is None or int(field) == want:
                return True, ''
        return False, '这个标签有 %d 处重名，直接定位可能改错参数' % n
    if n == 0:
        # 计数 0 不是"唯一"，而是"官方标签表里根本没这个中文标签"——
        # 八成是我们只有英文键、没有中文译名，拿它去中文界面搜必然落空
        return False, '官方标签表里查不到这个中文标签'
    # 界面里分组标题和行标签常是同一个词（「层高」分组里第一行也叫
    # 「层高」），UIA 找第一个会点到标题上
    if not key:
        item = lookup(nm) or {}
        key = item.get('key') or ''
    page, group = tab_path(key) if key else ('', '')
    if group and nm == group:
        return False, '和所在分组的标题同名，直接定位会点到标题上'
    if page and nm == page:
        return False, '和页签同名，直接定位会点到页签上'
    return True, ''
