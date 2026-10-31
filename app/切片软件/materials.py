# -*- coding: utf-8 -*-
"""耗材知识库：**两个形态共用一份**。

原来这套只长在第一形态（`SliceApp.MATERIAL_INFO`）里：切片时认得出耗材、
会给出建议、还能把耗材预设选对；但挂件（第二形态）完全没有这一层，
所以你在挂件气泡里问"abs要不要封箱"只会得到"没认出来"。

这一份里有三样东西：

  * `MATERIAL_INFO` —— 16 个材料族：显示名 / 一句短提示 / 完整建议
  * `identify()`    —— 认材料：中文别名 → 英文关键字 → 变体（碳纤维/丝绸/
                       夜光…）→ 编辑距离兜底（ptg、pegt 这类同音）
  * `answer()`      —— 常见问题的回答：把"材料 + 问的是什么"拼成一句人话。
                       问的是哪一类（封箱/烘干/喷嘴/床温/翘边…）用主题表匹配

写这些建议的原则：**只写能站得住的**。数值优先用材料包装/官方参数为准的
说法，拿不准的不编（宁可回"以耗材包装标注为准"）。
"""

import re

# —— 用户怎么说 → 材料族 ——
MATERIAL_CN = {
    '聚乳酸': 'pla', '玉米料': 'pla', '玉米淀粉': 'pla',
    '柔性': 'tpu', '软胶': 'tpu', '软料': 'tpu', '弹性料': 'tpu',
    '橡胶': 'tpu', '软胶料': 'tpu',
    '工程塑料': 'abs',
}

# —— 材料族：(显示名, 短提示[一行], 完整建议) ——
MATERIAL_INFO = {
    'pla': ('PLA', '', '常规PLA：纹理钢板直接打，无需箱体。'),
    'tpu': ('TPU', 'TPU吸湿强，建议干燥箱、速度放慢',
            'TPU柔性料吸湿强：建议干燥箱/打印前烘干（50-70°C数小时），'
            '打印速度放慢，喷嘴≥0.4mm。'),
    'petg': ('PETG', 'PETG易吸湿，建议打印前烘干',
             'PETG易吸湿：打印前建议烘干（约65°C 6-8h），'
             '纹理钢板附着好，注意拉丝。'),
    'abs': ('ABS', 'ABS建议密闭箱体、注意通风',
            'ABS建议密闭箱体防翘边并注意通风，床温约100°C。'),
    'pla-silk': ('丝绸PLA', '丝绸料怕潮，建议干燥箱',
                 '丝绸料怕潮：建议用干燥箱/密封干燥保存，'
                 '打印前55°C烘干6-8h；光泽对回抽敏感。'),
    'pla-cf': ('碳纤维PLA', '碳纤维耐磨，建议≥0.4mm硬化喷嘴',
               '含碳纤维耐磨：建议硬化钢喷嘴、≥0.4mm（勿用0.2mm），'
               '保持干燥，用后清理。'),
    'petg-cf': ('碳纤维PETG', '碳纤维耐磨，建议≥0.4mm硬化喷嘴',
                '含碳纤维耐磨：建议硬化钢喷嘴、≥0.4mm（勿用0.2mm），'
                '打印前烘干。'),
    'abs-gf': ('玻纤ABS', '玻纤耐磨，建议≥0.4mm硬化喷嘴',
               '含玻纤耐磨：建议硬化钢喷嘴、≥0.4mm，密闭箱体并通风。'),
    'pla-marble': ('大理石PLA', '大理石含石粉，建议硬化喷嘴',
                   '含石粉颗粒：对喷嘴有磨损，建议硬化喷嘴；'
                   '保持干燥。'),
    'pla-glow': ('夜光/荧光PLA', '夜光料磨耗大，建议0.4-0.6mm硬化喷嘴',
                 '含发光/荧光粉体磨耗大：建议硬化钢喷嘴（最好0.6mm），'
                 '注意AMS齿轮磨损；打印后光照补能。'),
    'pla-wood': ('木质PLA', '木质含木粉，建议≥0.4mm硬化喷嘴',
                 '含木粉：建议≥0.4mm硬化喷嘴，注意防堵头；'
                 '保持干燥。'),
    'pla-metal': ('金属PLA', '金属含金属粉，建议≥0.4mm硬化喷嘴',
                  '含金属粉：建议≥0.4mm硬化喷嘴；保持干燥。'),
    'pla-matte': ('哑光PLA', '',
                  '哑光料表面易显层纹，可适当减小层高；一般无需箱体。'),
    'pla-translucent': ('透光PLA', '',
                        '透光料怕水汽：建议干燥后打印；'
                        '壁厚/层高影响透光效果。'),
    'pla-galaxy': ('星空PLA', '',
                   '含闪光颗粒：对喷嘴略有磨损，建议硬化喷嘴。'),
    'pla-sparkle': ('闪粉PLA', '',
                    '含闪粉颗粒：对喷嘴略有磨损，建议硬化喷嘴。'),
    # 用户 2026-10-16 问的就是这个（"petg透明"）—— 以前 PETG 的变体词
    # 只有 PLA 那一支认识，问"透明"会被当成普通 PETG 答
    'petg-translucent': ('PETG 透明', '透明料想通透：慢一点、层高低一点',
                         'PETG 透明（官方叫 Translucent）：还是 PETG 一族，'
                         '吸湿照样要注意（打印前建议烘干约65°C）；'
                         '想要更透可以速度放慢、层高小一点。'),
    # 用户 2026-10-16 顺手测出来的：问「pa-cf 选哪个预设」被当成"碳纤维PLA"
    # —— 材料库里根本没有 PA / PC 这两族（`identify` 认不出来就退回 PLA）。
    'pa': ('PA（尼龙）', '尼龙吸湿极强，务必烘干',
           'PA/尼龙：吸湿极强，打印前建议充分烘干（约70-80°C、8小时以上），'
           '打完密封干燥保存，具体数值以耗材标注为准。'),
    'pa-cf': ('碳纤维PA（尼龙）', '碳纤尼龙务必烘干、硬化喷嘴',
              'PA-CF：尼龙吸湿极强，打印前务必充分烘干；含碳纤维，'
              '要用硬化钢喷嘴（≥0.4mm），具体数值以耗材标注为准。'),
    'pc': ('PC', 'PC 要高喷嘴/床温，注意密闭',
           'PC：喷嘴和热床温度都比 PLA/PETG 高不少，一般要密闭箱体，'
           '具体数值以耗材标注为准。'),
}

#: 材料族里的变体词 → 官方预设名里对应的英文写法
_VARIANT_EN = {'cf': 'CF', 'gf': 'GF', 'silk': 'Silk', 'matte': 'Matte',
               'translucent': 'Translucent', 'wood': 'Wood',
               'marble': 'Marble', 'glow': 'Glow', 'sparkle': 'Sparkle',
               'galaxy': 'Galaxy', 'metal': 'Metal'}

_PRESETS = None


def _presets():
    """项目里已有的**官方耗材预设名**（如 `Bambu PETG Translucent`）。

    来源是参数清单 `bambu_wiki_catalog.json`：结构是
    `filament → <机器预设> → default → <耗材预设名>`，最里层的键就是官方
    预设名（形如 `Bambu PETG Translucent @BBL X1C 0.6 nozzle`）。
    不另手写一份：手写的迟早跟真实预设名对不上（用户 2026-10-16：
    「petg透明是在bambu是选择什么呀？」问的就是预设名）。
    """
    global _PRESETS
    if _PRESETS is None:
        names = set()
        try:
            import json
            import bambu_wiki as _w
            with open(_w._data_file('bambu_wiki_catalog.json'),
                      encoding='utf-8') as f:
                cat = json.load(f)

            def walk(node, depth):
                if depth > 4 or not isinstance(node, dict):
                    return
                for k, v in node.items():
                    ks = str(k)
                    # 耗材预设名的特征：`Bambu XXX @BBL …`（机器预设没有 @）
                    if ks.lower().startswith('bambu ') and ' @' in ks:
                        names.add(ks.split(' @')[0].strip())
                    walk(v, depth + 1)
            walk(cat.get('filament'), 0)
        except Exception:                                  # noqa: BLE001
            pass
        _PRESETS = sorted(names)
    return _PRESETS


def preset_for(family):
    """材料族 → Bambu Studio 里最该选的那个**预设名**（找不到返回 ''）。"""
    fam = str(family or '').lower().split('-')
    base = fam[0].upper()
    want = [base]
    if len(fam) > 1 and fam[1] in _VARIANT_EN:
        want.append(_VARIANT_EN[fam[1]])
    pool = [n for n in _presets()
            if all(w.lower() in n.lower() for w in want)]
    if not pool:
        return ''
    if len(want) > 1:
        return sorted(pool, key=len)[0]        # 变体明确的：取最短的那个
    basic = [n for n in pool if n.lower().endswith(' basic')]
    return sorted(basic or pool, key=len)[0]

def _dl_distance(a, b):
    """Damerau-Levenshtein 编辑距离：支持插入/删除/替换/换位。"""
    a, b = (a or '').lower(), (b or '').lower()
    la, lb = len(a), len(b)
    if not la:
        return lb
    if not lb:
        return la
    # 换位那一项要用 d[i-2][j-2]，所以得留住**前两行**——
    # 只留一行的话 `pteg`→`petg` 会算成 2（第一形态那边有 85 个断言盯着，
    # 差一格就会挂）
    prev2 = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] \
                    and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[lb]


def identify(text):
    """认耗材。返回 dict 或 None。

    字段：family / display / short / advice / fuzzy（同音模糊匹配来的，
    置信度低一点，提示时要说明）
    """
    if not text:
        return None
    t = text.lower()
    base = None
    for cn, b in MATERIAL_CN.items():
        if cn in text:
            base = b
            break
    if base is None:
        for key in ('tpu', 'pla', 'petg', 'abs'):
            if key in t:
                base = key
                break
    if base is None:
        # PA（尼龙）/ PC：用**带边界**的写法认，"pa" 直接子串匹配会误伤
        # （"parts"、"space" 里都有 pa）—— 这是实测踩过的坑
        if re.search(r'pa6|pa12|paht|ppa|pa[-_ ]?cf|pa[-_ ]?gf|\bpa\b', t):
            base = 'pa'
        elif re.search(r'\bpc\b', t):
            base = 'pc'
    # 变体（碳纤维/丝绸/夜光…）——顺序跟第一形态原来那份一致，别打乱：
    # 先看 pet-cf（它同时决定 base），再看碳纤/cf，最后才是其它变体
    variant = None
    if re.search(r'pet[\s\-]?cf', t):
        base, variant = 'petg', 'cf'
    elif '碳纤' in text or 'cf' in t:
        variant = 'cf'
    elif '丝绸' in text or '丝光' in text:
        variant = 'silk'
    elif '大理石' in text:
        variant = 'marble'
    elif '夜光' in text or '荧光' in text:
        variant = 'glow'
    elif '玻纤' in text or '玻璃纤维' in text or 'gf' in t:
        variant = 'gf'
    elif '木质' in text or '木头' in text or '木纹' in text:
        variant = 'wood'
    elif '金属' in text:
        variant = 'metal'
    elif '哑光' in text or '磨砂' in text:
        variant = 'matte'
    elif '透明' in text or '半透明' in text or '透光' in text:
        variant = 'translucent'
    elif '星空' in text or '星云' in text:
        variant = 'galaxy'
    elif '闪粉' in text or '闪光' in text or '闪闪' in text:
        variant = 'sparkle'
    if base is None and variant is None:
        for alias in ('pet', 'ptg', 'pegt', 'pctg'):
            if alias in t:
                base = 'petg'
                break
    fuzzy = False
    if base is None and variant is None:
        for tok in re.findall(r'[a-zA-Z]{3,6}', t):
            best, bd = None, 99
            for cand in ('pla', 'petg', 'abs', 'tpu'):
                d = _dl_distance(tok.lower(), cand)
                if d < bd:
                    best, bd = cand, d
            if best and bd <= 1:
                base, fuzzy = best, True
                break
    if base is None:
        if variant is None:
            return None
        base = 'abs' if variant == 'gf' else 'pla'
    fam = base
    if variant == 'cf':
        fam = {'pla': 'pla-cf', 'petg': 'petg-cf'}.get(base)
        if not fam and base == 'abs':
            fam = 'abs-gf'
        if not fam and base == 'pa':
            fam = 'pa-cf'
        fam = fam or base
    elif variant == 'gf':
        fam = {'abs': 'abs-gf'}.get(base, base)
    elif variant:
        # 变体专属条目存在就用它（PETG 透明 / PLA 丝绸…）；
        # 没有就退回基础料（PETG 的丝光这种我们没单独写建议）
        cand = base + '-' + variant
        fam = cand if cand in MATERIAL_INFO else (
            ('pla-' + variant) if base == 'pla' else base)
    info = MATERIAL_INFO.get(fam)
    if not info:
        return None
    return {'family': fam, 'display': info[0], 'short': info[1],
            'advice': info[2], 'fuzzy': fuzzy}


# ---------------- 常见问题知识库 ----------------
#
# 思路：先认出"在问哪个材料"，再看"问的是哪一类事"（封箱/烘干/喷嘴…），
# 两者拼成一句回答。查不到具体条目就退回那句通用建议——**不编**。

TOPICS = (
    # ★ 放第一位：问"在 Bambu 里选什么/选哪个"问的是**预设名**，
    #   被后面那些主题（烘干/喷嘴…）抢走就会答非所问 —— 实测用户
    #   2026-10-16 问「petg透明是在bambu是选择什么呀？」，结果回的是
    #   「PETG 易吸湿、建议烘干」，完全没回答"选哪个"。
    ('选预设', r'选什么|选哪个|选哪|选择什么|该选|用哪个|怎么选|哪个预设|'
               r'预设.{0,4}(选|哪个|是)|挑哪个|选一下'),
    ('箱体', r'封箱|箱体|封闭|密闭|封闭仓|要不要围|罩起来|保温'),
    ('干燥', r'烘干|干燥|受潮|吸湿|水分|潮了|除湿|干燥箱'),
    ('喷嘴温度', r'喷嘴温度|喷头温度|多少度打印|温度设多少|打多少度'),
    ('喷嘴', r'喷嘴|喷头|硬化|磨损|磨耗|0\.2|0\.4|0\.6|多大口径'),
    ('床温', r'热床|床温|底板|板子|纹理板|pei|低温板|高温板|粘板'),
    ('翘边', r'翘边|翘曲|变形|开裂|裂了|卷边'),
    ('拉丝', r'拉丝|抽丝|挂丝|拉线'),
    ('强度', r'强度|结实|承力|受力|结构件|够不够硬|耐不耐用'),
    ('耐温', r'耐温|耐热|软化|多少度|怕热|阳光'),
    ('AMS', r'ams|多色|换料|换丝|混色'),
    ('速度', r'速度|太快|太慢|慢点|快点|会不会太慢'),
    ('附着力', r'附着|粘不牢|粘不住|不粘|掉下来|脱板|粘太牢|取不下来|'
               r'拆不下来|掰不动|下不来'),
)

# 喷嘴温度：沿用第一形态「参数百科」里已经写给用户的区间，别另编一套
PRINT_TEMP = {
    'pla': '190–230°C（常用 210 左右）',
    'petg': '230–260°C（常用 240-250）',
    'abs': '240–280°C（常用 250-260）',
    'tpu': '200–230°C（慢速打印，按耗材标注为准）',
}

# (主题, 材料族) → 一两句话。只写站得住的；数值以耗材包装/官方参数为准
TOPIC_ANSWER = {
    ('箱体', 'abs'): '要：ABS 怕风吹、怕层间温差，密闭箱体+通风（气味大，'
                     '别在卧室打）能明显减少翘边开裂。',
    ('箱体', 'pla'): '不用：PLA 反而是怕热不怕风，箱体太热会让它变软、'
                     '堵头（热端散热被影响）。',
    ('箱体', 'tpu'): '不用箱体，但建议干燥箱存料——它的问题是吸湿，不是温度。',
    ('箱体', 'petg'): '不用箱体；PETG 怕的是潮气，先烘干比加箱体有用。',
    ('干燥', 'pla'): '普通 PLA 一般不用烘；放久了变脆/有气泡再烘（约45-50°C 4-6h）。',
    ('干燥', 'petg'): '要：PETG 吸湿后拉丝、发白、气泡，打印前约65°C 烘6-8h。',
    ('干燥', 'tpu'): '要：TPU 吸湿最明显，50-70°C 烘数小时，打完马上收干燥箱。',
    ('干燥', 'abs'): '建议烘一下（约70-80°C 4-6h），受潮会有气泡声。',
    ('喷嘴', 'pla-cf'): '不能用0.2：碳纤维磨喷嘴，建议0.4mm以上且用硬化钢喷嘴。',
    ('喷嘴', 'petg-cf'): '不能用0.2：碳纤维磨喷嘴，建议0.4mm以上且用硬化钢喷嘴。',
    ('喷嘴', 'abs-gf'): '不能用0.2：玻纤磨喷嘴，建议0.4mm以上硬化喷嘴。',
    ('喷嘴', 'pla-glow'): '建议0.4-0.6mm硬化喷嘴：荧光粉磨耗大，还可能磨 AMS 齿轮。',
    ('喷嘴', 'pla-wood'): '建议≥0.4mm硬化喷嘴：木粉容易堵头。',
    ('喷嘴', 'pla-metal'): '建议≥0.4mm硬化喷嘴：金属粉会磨损黄铜喷嘴。',
    ('喷嘴', 'pla-marble'): '建议硬化喷嘴：石粉有磨蚀性。',
    ('喷嘴', 'pla-sparkle'): '建议硬化喷嘴：闪粉颗粒有磨蚀性。',
    ('喷嘴', 'tpu'): '建议≥0.4mm：太细容易堵（TPU 挤出阻力大）。',
    ('床温', 'pla'): 'PLA 床温低：纹理PEI/低温板约 35-55°C，靠板子本身粘。',
    ('床温', 'petg'): 'PETG 床温约 60-80°C；粘得太牢反而难拆，别硬掰。',
    ('床温', 'abs'): 'ABS 床温约 100°C，配密闭箱体才压得住翘边。',
    ('翘边', 'abs'): 'ABS 翘边主要靠三件事：密闭箱体、床温约100°C、首层慢一点。',
    ('翘边', 'petg'): 'PETG 翘边少见；真翘多半是床太脏或有油，先擦板。',
    ('翘边', 'pla'): 'PLA 翘边多半是底板不干净/风扇太大，先洗板（洗洁精）。',
    ('拉丝', 'petg'): 'PETG 天生爱拉丝：先烘干，再调回抽（回抽长度/速度），'
                      '必要时关掉"减少回抽"或开z hop。',
    ('拉丝', 'tpu'): 'TPU 尽量少回抽（软料回抽效果差、还易堵），'
                     '主要靠直接驱动+慢速+空驶少。',
    ('强度', 'pla'): 'PLA 硬但脆、耐温低；承力件建议 3-4 层墙 + 25-40% 填充。',
    ('强度', 'petg'): 'PETG 韧性好、耐温比PLA高一点，适合功能件；'
                      '速度别太快，容易糊表面。',
    ('强度', 'abs'): 'ABS 耐温最高、韧性好，适合受力/车内件；必须密闭箱体。',
    ('强度', 'tpu'): 'TPU 只负责"软"和"抗冲击"，别拿它做需要刚性的件。',
    ('耐温', 'pla'): 'PLA 大约60°C就开始软化：晒车里、暖气边会变形。',
    ('耐温', 'petg'): 'PETG 大约70-80°C；比PLA好，但车内夏天仍可能变形。',
    ('耐温', 'abs'): 'ABS 大约90-100°C，是这几类里最耐温的。',
    ('AMS', 'pla-glow'): '夜光料磨耗大，走 AMS 会磨齿轮和管件，尽量少换。',
    ('速度', 'pla'): 'PLA 可以放开跑；想表面好看就"外墙速度"单独降一点。',
    ('速度', 'petg'): 'PETG 慢一点更稳（快了容易糊表面/拉丝）。',
    ('速度', 'abs'): 'ABS 别太快：太快层间没时间粘牢，容易开裂。',
    ('速度', 'tpu'): 'TPU 必须慢（大致 20-40mm/s），软料快了会挤出不足。',
    ('附着力', 'pla'): 'PLA 附着靠干净板面：洗洁精洗纹理板就行，'
                       '翘边再加一点裙边。',
    ('附着力', 'petg'): 'PETG 往往"粘太牢"：用胶棒/胶水当隔离层，'
                        '别硬掰板子。',
    ('附着力', 'abs'): 'ABS 靠热床（约100°C）+箱体，冷了再取件，'
                       '不然容易把底撕坏。',
    ('附着力', 'tpu'): 'TPU 首层慢慢打（首层速度降到 20 左右），'
                       '板面干净就够粘。',
    ('耐温', 'pla-silk'): '丝绸 PLA 和普通 PLA 差不多，60°C 左右开始软化。',
    ('耐温', 'pla-cf'): '碳纤维 PLA 比普通 PLA 略耐温，但也别指望长期高温。',
}

# 材料之间的区别（选料问答）
COMPARE = {
    frozenset(('pla', 'petg')):
        'PLA 硬、脆、好打、便宜但不耐温（~60°C软化）；'
        'PETG 韧、略耐温（~70-80°C）、易吸湿爱拉丝。'
        '摆件/外观件选 PLA，功能件选 PETG。',
    frozenset(('pla', 'abs')):
        'PLA 好打、精度高、不耐温不耐晒；ABS 耐温（~100°C）、韧、'
        '能抛光，但必须密闭箱体且气味大。'
        '室内摆件 PLA，车里/受力件 ABS。',
    frozenset(('petg', 'abs')):
        'PETG 好打、韧、略耐温，但易吸湿拉丝；ABS 更耐温、可后处理，'
        '但难打（箱体+通风）。',
    frozenset(('pla', 'tpu')):
        'PLA 是硬料，TPU 是软料（能弯、抗冲击）；'
        'TPU 要慢速、少回抽、先烘干。',
    frozenset(('tpu', 'petg')):
        'TPU 软、耐磨、抗冲击；PETG 是硬料。'
        '需要弹性/缓冲选 TPU，需要结构强度选 PETG。',
    frozenset(('pla', 'pla-cf')):
        '碳纤维 PLA 更硬更耐热一点、表面有纹理感，但磨喷嘴'
        '（要硬化喷嘴、≥0.4mm），层间强度不一定更高。',
    frozenset(('pla', 'pla-silk')):
        '丝绸 PLA 靠光泽出效果，打起来比普通 PLA 更挑：怕潮、'
        '回抽要调好，强度略低。',
}


def topic_of(text):
    """这句话在问哪一类事（封箱/烘干/喷嘴…），返回主题名或 None。"""
    t = (text or '').lower()
    for name, pat in TOPICS:
        if re.search(pat, t, re.I):
            return name
    return None


# "X 和 Y 有什么区别"这类才是对比；只说"丝绸PLA注意什么"不算
COMPARE_MARK = re.compile(r'区别|差别|差异|对比|哪个好|哪个更|哪个耐|还是|vs')


def _families_in(text, keep_base=False):
    """一句话里出现了哪几个材料（用于"PLA 和 PETG 有什么区别"）。

    keep_base=False：变体比基础料更具体（"丝绸PLA"只算丝绸）——
    否则"丝绸pla注意什么"会被当成"丝绸 vs PLA 的对比"。
    keep_base=True：问区别时要把基础料一起留下（"碳纤维和普通PLA区别"）。
    """
    t = (text or '').lower()
    found = []
    for key, fam in (('tpu', 'tpu'), ('petg', 'petg'), ('abs', 'abs'),
                     ('pla', 'pla')):
        if key in t:
            found.append(fam)
    if '丝绸' in text or '丝光' in text:
        found.append('pla-silk')
    if '碳纤' in text or 'cf' in t:
        found.append('pla-cf')
    if not keep_base:
        if 'pla-silk' in found and 'pla' in found:
            found.remove('pla')
        if 'pla-cf' in found and 'pla' in found:
            found.remove('pla')
    seen, out = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def answer(text):
    """把一句话（耗材相关）变成一段回答；认不出材料就返回 None。

    命中顺序：
      1. 两个材料做对比（"X 和 Y 有什么区别"）
      2. 材料 + 主题（"ABS 要不要封箱"）
      3. 只认出材料（就回那句通用建议）
    """
    raw = text or ''
    info = identify(raw)
    topic = topic_of(raw)
    is_cmp = bool(COMPARE_MARK.search(raw))
    fams = _families_in(raw, keep_base=is_cmp)
    if len(fams) >= 2 and is_cmp:
        # 标签顺序跟着用户说的顺序走（"pla和petg"就别写成"PETG vs PLA"）
        ordered = sorted(fams[:2],
                         key=lambda f: raw.lower().find(
                             {'pla': 'pla', 'petg': 'petg', 'abs': 'abs',
                              'tpu': 'tpu', 'pla-silk': '丝绸',
                              'pla-cf': '碳纤'}.get(f, f)))
        key = frozenset(ordered)
        pair = COMPARE.get(key)
        if not pair:
            a = MATERIAL_INFO.get(ordered[0], ('?',))[0]
            b = MATERIAL_INFO.get(ordered[1], ('?',))[0]
            pair = ('%s 和 %s：%s；%s'
                    % (a, b, MATERIAL_INFO.get(ordered[0], ('', '', ''))[2],
                       MATERIAL_INFO.get(ordered[1], ('', '', ''))[2]))
        return '【%s vs %s】%s' % (MATERIAL_INFO.get(ordered[0], ('?',))[0],
                                  MATERIAL_INFO.get(ordered[1], ('?',))[0],
                                  pair)
    if not info:
        if topic:
            # 没说材料只问事：给通用的那条
            generic = {
                '干燥': 'PLA 一般不用烘；PETG / TPU / ABS 打印前建议烘干'
                        '（PLA约45-50°C、PETG约65°C、ABS约70-80°C，'
                        '具体看耗材包装）。',
                '箱体': '要箱体的是 ABS 类（防翘边）；PLA / PETG / TPU '
                        '不需要，PLA 甚至怕箱体太热。',
                '喷嘴': '含碳纤维/玻纤/夜光/木粉/金属粉的料都要硬化喷嘴'
                        '且≥0.4mm；普通 PLA/PETG/ABS 用标配0.4mm就行。',
                'AMS': '磨耗大的料（碳纤维、玻纤、夜光、金属）尽量少走 '
                       'AMS，会磨齿轮；换料前剪平料头。',
            }.get(topic)
            if generic:
                return '【%s】%s' % (topic, generic)
        return None
    head = '【%s】' % info['display']
    if info.get('fuzzy'):
        head = '【%s（我按 %s 认的，如果不对说一声）】' % (
            info['display'], info['display'])
    if topic == '选预设':
        # 问"在 Bambu 里选什么"= 要**预设名**，别回材料小知识（实测就是这么
        # 答非所问的：问 petg 透明选哪个，回的是"PETG 易吸湿、建议烘干"）。
        fam = info['family']
        nm = preset_for(fam)
        if not nm and '-' in fam:
            # 变体这一档清单里没有（比如 CF 版）——**别拿基础料冒充**，
            # 直接说清楚，再给基础料的预设名
            nb = preset_for(fam.split('-')[0])
            if nb:
                return ('%s预设清单里没看到「%s」这一档；基础料对应的是'
                        '「%s」。%s'
                        % (head, fam.split('-', 1)[1].upper(), nb,
                           info['advice']))
        if nm:
            tail = nm.split(' ', 1)[1] if ' ' in nm else nm
            return ('%s在 Bambu Studio 里选耗材预设「%s」—— 右侧「耗材」那一栏'
                    '的预设下拉里搜「%s」就能找到。'
                    % (head, nm, tail))
    ans = TOPIC_ANSWER.get((topic, info['family']))
    if topic == '喷嘴温度':
        # 温度问的是数值，表里没有就用 PRINT_TEMP（跟参数百科同一套区间）
        base_fam = info['family'].split('-')[0]
        temp = PRINT_TEMP.get(base_fam)
        if temp:
            return head + '%s 的喷嘴温度大致 %s；'\
                          '首层可以比其它层高 5-10°C，'\
                          '换料前先确认耗材耐温。' % (info['display'], temp)
    if ans:
        return head + ans + '（通用建议：' + info['advice'] + '）'
    return head + info['advice']
