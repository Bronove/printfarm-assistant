# -*- coding: utf-8 -*-
"""读图里的文字：用 **Windows 自带的 OCR**（`Windows.Media.Ocr`）。

为什么用它，而不是 tesseract / paddleocr / easyocr：
  * Windows 10/11 自带引擎，中文包在就认中文 —— **不用装东西、不用联网**，
    符合这个项目定的"优先本地"；装 tesseract 要单独下安装包，
    paddleocr 要拉几百 MB 的依赖和模型，都不适合"用户拿到就能用"。
  * 实测这台机器上有 `zh-Hans-CN` 识别器。

用法：
    import ocr
    ok, text, why = ocr.read_text(r'...\\报错截图.png')
    ok, text, why = ocr.read_image(pil_image)      # 直接给内存里的图

⚠ 两个坑（都写了注释，别踩回去）：
  1. `ocr_win.ps1` 必须是**纯 ASCII**：Windows PowerShell 5.1 会把没有 BOM 的
     UTF-8 当 ANSI 读，中文注释会被拆成乱码、甚至把语法带崩。
  2. Windows 的 OCR 认中文是**一个字一个空格**（实测「支 撑 阈 值 角 度」），
     要按 `_clean()` 把中文字之间的空格删掉，不然拿去当输入很难看。
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_SIDE = 2600          # Windows OCR 对超大图不友好：先缩到这个边长以内
TARGET_SIDE = 1600       # 小图先放到这个量级（见 _prep 里的实测数据）
TIMEOUT = 90             # 单张图的兜底上限（正常 1~3 秒）


def _find_ps1():
    """找 `ocr_win.ps1` 的完整路径 —— **打包以后也要找得到**。

    ★ 2026-10-15 真实 bug：打包漏了这个脚本（它是**数据文件**，不写进
      build.ps1 的 --add-data 就进不了安装包），用户贴张图，气泡只回一句
      「这张图我没读出字（缺少 ocr_win.ps1）」—— 功能静默失效，最难查。
      现在按几个可能的位置找一遍；找不到时把找过的目录带进报错里，好排查。
    """
    cands = [HERE]
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        cands.append(meipass)                       # PyInstaller 解包目录
        cands.append(os.path.join(meipass, 'bambu_cli'))
    try:
        cands.append(os.path.dirname(os.path.abspath(sys.executable)))
    except Exception:                               # noqa: BLE001
        pass
    try:
        cands.append(os.getcwd())
    except Exception:                               # noqa: BLE001
        pass
    for d in cands:
        p = os.path.join(d, 'ocr_win.ps1')
        if os.path.isfile(p):
            return p
    return os.path.join(HERE, 'ocr_win.ps1')        # 找不到：报错时看得见路径


PS1 = _find_ps1()

_HAN = '\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff'


_VOCAB = None
_CORPUS = None

#: 最近一次读图时"擦掉了鼠标指针"的说明（read_image 用，给界面显示用）。
LAST_CURSOR_NOTE = ''
#: 擦指针那一步若出错，把原因记在这（功能降级用；自检/排障时能看见）
STRIP_ERR = ''
_CONFUSE = {'夕卜': '外', '囗': '口', '亻': '人', '氵': '水', '冫': '冰',
            '礻': '示', '衤': '衣', '艹': '艹',
            # 「层咼」→「层高」：咼是生僻字，OCR 把小字放大后仍会读出它
            # （2026-10-15 实测）。这是**字级**的确定替换，比"整词纠错"安全。
            '咼': '高', '埴': '填',
            # 2026-10-16 拿 5 段口语 × 5 档字号（25 张图）测出来的**拆字**错法：
            # OCR 会把一个字拆成"偏旁 + 另一半"两个字符，读成一串没人认识的
            # 东西（实测「印」→「E卩」、「温」→「水昷」、「件」→「人牛」、
            # 「份」→「人分」）。这类是**字级确定替换**，不猜、直接换。
            'E卩': '印', '水昷': '温', '人牛': '件', '人分': '份',
            # 品牌/打印板/多色打印的高频拆字与形近误读。只收录实测过的
            # 组合，不做"单字全局替换"，避免把正常中文改坏。
            '托竹': '拓竹', '拓什': '拓竹',
            '扌J': '打', '扌丁': '打', '打即板': '打印板',
            '打印扳': '打印板', '多、色': '多色'}


#: 参数界面上**反复出现的短词**。语料库里的官方名多是「支撑阈值角度」这种长词，
#: 只靠长词做锚点时，OCR 把长词本身读错（「支存支殍阈值角度」）就没法定位、
#: 整段修不动（2026-10-16 实测）。补上这批短词当锚点后，"滑动窗口 + 编辑距离"
#: 能把长段里错的那两个短词各自修回来。
#: 来源：拓竹界面/参数表里的高频两字词，只用于**读图后的纠错**，不影响别处。
_COMMON = ('打开', '关闭', '开启', '启用', '禁用', '角度', '阈值', '宽度',
           '高度', '长度', '速度', '密度', '层高', '层数', '外墙', '内墙',
           '外壁', '内壁', '填充', '支撑', '温度', '风扇', '冷却', '底座',
           '强度', '间隙', '回抽', '首层', '顶层', '稀疏', '实心', '裙边',
           '圆角', '倒角', '桥接', '接触', '附着', '打印', '设置',
           # 日常说法里最常出现、又最容易被 OCR 读歪的量词/单位
           # （实测「毫米」被读成「笔米」「亳米」、「百分之二十」被读成
           #   「白分之二十」—— 用户 2026-10-16：「用词对不对，符不符合
           #   日常交流」）
           '毫米', '厘米', '百分之',
           '合理', '一点', '加宽',
           # 这个软件里用户张口就来的说法（实测被读歪过：帮我**把**→帮我**吧**，
           # 调**到**65度→调**啁**65度）
           '帮我把', '调到', '要把', '两百',
           # 2026-10-17：官方中文站/Wiki 的高频品牌和硬件词。
           # 「打印板」如果不在词表里，OCR 的「打印板」会被纠成「打印机」。
           '拓竹', '打印板', '纹理', '热床', '热端', '喷头',
           '多色', '多色打印', '打印盘', '准备', '预览', '设备')


def _find_data(name):
    """找随包数据文件（源码目录 / PyInstaller 解包目录 / exe 同目录）。"""
    cands = [HERE]
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        cands.extend([meipass, os.path.join(meipass, 'bambu_cli')])
    try:
        cands.append(os.path.dirname(os.path.abspath(sys.executable)))
    except Exception:                                 # noqa: BLE001
        pass
    try:
        cands.append(os.getcwd())
    except Exception:                                 # noqa: BLE001
        pass
    for d in cands:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return ''


def corpus_terms():
    """读取人工筛选的 3D 打印中文语料（官网/Wiki + Bambu Studio 高频词）。

    词表只用于 OCR 纠错与多尺度打分，不参与参数值推断。来源和分类写在
    `ocr_corpus_zh.json`，后续补词只改数据文件，不必再改算法。
    """
    global _CORPUS
    if _CORPUS is not None:
        return _CORPUS
    words = set()
    p = _find_data('ocr_corpus_zh.json')
    if p:
        try:
            import json
            with open(p, encoding='utf-8') as f:
                data = json.load(f)
            for key, vals in data.items():
                if key in ('version', 'updated', 'sources'):
                    continue
                if isinstance(vals, list):
                    for v in vals:
                        v = str(v).strip()
                        if len(v) >= 2 and _has_han(v):
                            words.add(v)
        except Exception:                             # noqa: BLE001
            pass
    _CORPUS = words
    return _CORPUS


def vocab():
    """把项目**已有的参数语料库**拿来做词表（参数名 + 官方界面名 + 口语别名）。

    用户 2026-10-14：「把之前做到的语料库也加入，提高文字识别精准度」——
    我们本来就有 711 个官方参数、几百个中文标签和一张口语别名表，
    拿它当"已知词"去纠正 OCR 的错别字，比通用纠错准得多
    （实测 OCR 把「外墙速度」认成「夕卜墙速度」）。
    """
    global _VOCAB
    if _VOCAB is not None:
        return _VOCAB
    words = set()
    try:
        import bambu_wiki as W
        for k, off in (W._load_official() or {}).items():
            for nm in ((off.get('label_cn') or '').strip(),
                       (off.get('label') or '').strip()):
                if len(nm) >= 2 and _has_han(nm):
                    words.add(nm)
        for k, v in (getattr(W, 'ENTRIES', {}) or {}).items():
            nm = (v.get('cn') or '').strip()
            if len(nm) >= 2:
                words.add(nm)
        for al in (getattr(W, 'ALIASES', {}) or {}):
            if len(al) >= 2 and _has_han(al):
                words.add(al)
    except Exception:                                 # noqa: BLE001
        pass
    # 再补上界面里反复出现的短词：长词当锚点不够用（见 _COMMON 的说明）
    words.update(_COMMON)
    words.update(corpus_terms())
    _VOCAB = words
    return _VOCAB


def _has_han(s):
    return any('\u4e00' <= c <= '\u9fff' for c in (s or ''))


def _dist(a, b, cap):
    """带上限的编辑距离（超过 cap 直接返回 cap+1，省时间）。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (ca != cb))
            best = min(best, cur[j])
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


#: **实测过的错字**：OCR 把"真字"认成了"错字"。只在编辑距离打平时用来决胜。
#: 为什么需要它：编辑距离打平是常事（「层**局**」改成「层**高**」和「层**数**」
#: 都是 1 处不同），而候选词是从 set 里遍历出来的 —— 顺序随机，
#: 2026-10-16 实测就把「层高」挑成了「层数」。不纠正这个，结果会时好时坏。
_MISREAD = {'咼': '高', '局': '高',           # 高 被认错（咼 是生僻字、局 形近）
            '支': '撑', '存': '撑', '殍': '撑',   # 支撑 的 撑 被拆成/认成别的字
            # 2026-10-16 成段口语测出来的形近误读（修词要用它们"定性"，
            # 光靠编辑距离会把「打样」改成「打开」这种正常词也动了 —— 见下）
            '墳': '填', '埴': '填', '笔': '毫', '亳': '毫',
            '白': '百', '怊': '裙', '台': '合', '卢': '点', '宽': '加',
            '啁': '调', '吧': '把',
            '夕卜': '外', '囗': '口', '亻': '人'}


def _misread_bonus(seg, v):
    """seg → v 这一次改写，"纠正了实测错字"的处数（越多说明这个候选越可信）。"""
    b = 0
    for k in range(min(len(seg), len(v))):
        if _MISREAD.get(seg[k]) == v[k]:
            b += 1
    return b


def _best_word(seg, pool, cap=1, same_len=False):
    """在 pool 里挑最像 seg 的词 → (词, 编辑距离)。没有就返回 (None, cap+1)。

    排序规则：**先看编辑距离，打平了再看"_MISREAD 错字表"**（见上）。
    `same_len=True` 时只认**等长**的词（不改变字数，见 correct() 的说明）。
    """
    best, bd, bbon = None, cap + 1, -1
    for v in pool:
        if same_len and len(v) != len(seg):
            continue
        if abs(len(v) - len(seg)) > cap:
            continue
        # 首字差太远就不必试（提速 + 防误改）—— 但**只对 4 字以上的长段**生效。
        # 短段（2~3 字）得放开：实测「墳充」→「填充」、「笔米」→「毫米」这种
        # 整个字被认错的情况，首字恰好就是错的，卡住就永远修不回来。
        # （安全性靠别处兜着：2 字必须命中 `_MISREAD` 实测错字表才允许改。）
        if len(seg) >= 4 and v[0] != seg[0] and v[0] not in seg:
            continue
        d = _dist(seg, v, cap)
        if d > cap:
            continue
        bon = _misread_bonus(seg, v)
        if d < bd or (d == bd and bon > bbon):
            best, bd, bbon = v, d, bon
            if d == 0:
                break
    return best, bd


def correct(text):
    """按参数语料库纠 OCR 的错字：只改"像某个已知词"的连续中文串。

    规则保守（宁可不改）：
      * 只动长度 ≥3 的中文串；
      * 编辑距离必须 ≤ len//3（长词允许错一两字）；
      * 只替换成**词表里真实存在**的那个词。
    """
    t = text or ''
    for bad, good in _CONFUSE.items():                # 部件被拆开的常见情况
        if bad in t:
            t = t.replace(bad, good)
    vs = vocab()
    if not vs:
        return t
    out, buf = [], []

    def flush():
        if not buf:
            return
        w = ''.join(buf)
        buf.clear()
        # ① 整段本来就在词表里 → 不动
        if w in vs:
            out.append(w)
            return
        # ② 先试"**词典纠错分词**"（DP，全局最优）：一段里错两处时，整段比对
        #    会因为超过 1 个编辑距离而放弃（实测「打开支存支殍阈值角度」
        #    → 修不动，参数解析因此丢掉一条）。
        #    ⚠ 门槛给到 2 字而不是 4 字：实测 13px 小图会把「层高」读成
        #    「层局」，两字一段，门槛卡在 4 就永远修不到（2026-10-16 实测）。
        #    安全性由 DP 的代价模型保证 —— 只有"改完总分真的更高"才动。
        if len(w) >= 2:
            seg = _fix_by_segments(w, vs)
            if seg != w:
                out.append(seg)
                return
        if len(w) >= 3 and w not in vs:
            # ⚠ 上限只能给 1：给宽了会把「支撑阈值角度**改成**」整段替换成
            #   「支撑阈值角度」，把"改成"吃掉（实测踩过）。
            # ⚠ 还要求**等长**：允许差一个字的话，「上支撑」会被纠成「支撑」，
            #   把"上"吃掉 —— 改动字数会让后面的参数解析整段错位（2026-10-16）。
            cap = 1
            best, bd = _best_word(w, vs, cap, same_len=True)
            if best and bd <= cap:
                w = best
        out.append(w)

    for ch in t:
        if '\u4e00' <= ch <= '\u9fff':
            buf.append(ch)
        else:
            flush()
            out.append(ch)
    flush()
    return _fix_across_lines(''.join(out), vs)


def _fix_across_lines(t, vs):
    """把**被折行切断的词**拼起来纠一次。

    为什么需要（2026-10-16 实测）：截图里一行放不下就会折行，而折行点常常
    正好落在一个词中间 —— 「裙边**加宽**到8毫米」被折成
    『裙边宽』+『宽到8毫米』两行。分行看，两边都不是词，怎么比对都修不动
    （实测 14/18px 两档都是「宽宽」留在那儿，读起来就是"用词不对"）。

    做法：只在**行尾汉字 + 行首汉字**这一处把两段临时接起来纠，
    纠完按原长度切回两行（纠错本身是**等长替换**，所以切回去是安全的）。
    只处理紧贴换行的这一对，不动行内其它内容 —— 不碰上下文，避免乱改。
    """
    t = t or ''
    if '\n' not in t or not vs:
        return t
    lines = t.split('\n')

    def is_han(ch):
        return '\u4e00' <= ch <= '\u9fff'

    for i in range(len(lines) - 1):
        a, b = lines[i], lines[i + 1]
        if not a or not b or not is_han(a[-1]) or not is_han(b[0]):
            continue
        k1 = len(a)
        while k1 > 0 and is_han(a[k1 - 1]):
            k1 -= 1
        k2 = 0
        while k2 < len(b) and is_han(b[k2]):
            k2 += 1
        r1, r2 = a[k1:], b[:k2]
        if len(r1) + len(r2) < 3:
            continue
        joined = r1 + r2
        fixed = _fix_by_segments(joined, vs)
        if fixed != joined and len(fixed) == len(joined):
            lines[i] = a[:k1] + fixed[:len(r1)]
            lines[i + 1] = fixed[len(r1):] + b[k2:]
    return '\n'.join(lines)


#: 打印机机型短名（用户口语/截图里就这么写）。OCR 常把数字 1 认成字母 l/I：
#: 「P1S」→「pls」「pIs」——用这张表按"归一化后相等"修回来。
MODEL_NAMES = ('A1', 'A1M', 'A2L', 'P1P', 'P1S', 'P2S', 'X1', 'X1C', 'X1E',
               'X2D', 'H2C', 'H2D', 'H2DP', 'H2S')


#: **3D 打印语境的规范词表**：机型 / 材料 / 平台 / 切片术语 / 文件格式。
#:
#: 为什么单独做这一层（用户 2026-10-16：「p1s、pla 这两个能预判用户的词不要
#: 出错，你做的是 3d 打印的软件，好多名词可以通过预判提高 ocr 的准确率」）：
#: 这些东西的**取值是有限集合**（型号就那几个、官方耗材几十种），不像自然
#: 语言那样无穷；而 OCR 的错法又特别固定 —— `1/l/I`、`0/O`、`5/S`、`6/G`、
#: `8/B` 互认，外加相邻字母换位。拿有限集合当先验，等于提前告诉识别
#: "这一片可能出现的就是这些词"，于是 `pls`→**P1S**、`PIA`→**PLA**、
#: `PET6`→**PETG**、`AB5`→**ABS** 都能对上号。
#:
#: 拼写以 Bambu Studio 里的**官方写法**为准（日志里出现的就是这些：
#: `Bambu PLA Basic @BBL P1S 0.4 nozzle`、`Textured PEI Plate`、`G-code`）。
DOMAIN_TERMS = (
    # —— 机型 / 品牌 / 软件 ——
    'Bambu', 'Bambu Lab', 'Bambu Studio', 'BambuStudio', 'Bambu Handy',
    'MakerWorld',
    'OrcaSlicer', 'A1 mini', 'A1M', 'A2L', 'P1P', 'P1S', 'P2S', 'X1 Carbon',
    'X1C', 'X1E', 'X2D', 'H2C', 'H2D', 'H2DP', 'H2S', 'X1', 'A1',
    # —— 耗材（Bambu 官方叫法）——
    'PLA', 'PLA Basic', 'PLA Matte', 'PLA Silk', 'PLA Wood', 'PLA Marble',
    'PLA Sparkle', 'PLA Galaxy', 'PLA Glow', 'PLA Metal', 'PLA Translucent',
    'PLA Tough', 'PLA Aero', 'PLA Lite', 'PLA-CF', 'PLA-GF',
    'PETG', 'PETG Basic', 'PETG HF', 'PETG Translucent', 'PETG-CF', 'PET-CF',
    'ABS', 'ASA', 'PC', 'PA', 'PA6', 'PA12', 'PA6-CF', 'PA6-GF', 'PAHT-CF',
    'PPA-CF', 'PPS-CF', 'TPU', 'TPU 95A', 'TPU for AMS', 'PVA', 'HIPS',
    'Support W', 'Support G', 'BVOH',
    # —— 打印平台（预设名，日志/截图里就是这些）——
    'Textured PEI Plate', 'Smooth PEI Plate', 'Cool Plate',
    'Engineering Plate', 'High Temp Plate', 'Bambu Cool Plate',
    'Bambu Textured PEI Plate', 'PEI', 'PEI Plate',
    # —— 切片术语（界面上常见的英文）——
    'Infill', 'Brim', 'Skirt', 'Support', 'Wall', 'Layer', 'Nozzle', 'Bed',
    'Speed', 'Flow', 'Retraction', 'Ironing', 'Fuzzy Skin', 'Prime Tower',
    'Preset', 'Filament', 'Profile', 'Seam', 'Textured', 'Smooth',
    'Adaptive Layer Height', 'Tree Support', 'Auto Orient', 'Arrange',
    # —— 文件格式 / 硬件 ——
    'STL', 'STEP', '3MF', 'G-code', 'Gcode', 'OBJ', 'AMF', 'PLY', 'DXF',
    'AMS', 'AMS Lite', 'AMS lite', 'MakerWorld',
)


#: OCR 之间的**同形/易混字符**：折叠成同一个字符后才好比对。
#: 只用于**比对**，输出永远用规范拼写（所以不会把 P1S 写成 pls）。
_FOLD_TABLE = str.maketrans({'o': '0', 'l': '1', 'i': '1', '|': '1',
                             '丨': '1',
                             's': '5', 'g': '6', 'b': '8', 'z': '2'})


def _fold(s):
    """比对用的折叠：0/O、1/l/I、5/S、6/G、8/B 看成同一个，空格也去掉。"""
    return (s or '').lower().translate(_FOLD_TABLE).replace(' ', '')


_DOMAIN = None


def _domain():
    """规范词表 → {折叠后的key: 规范拼写}（首次调用时建一次）。"""
    global _DOMAIN
    if _DOMAIN is None:
        m = {}
        for w in DOMAIN_TERMS:
            k = _fold(w)
            if len(k) >= 2 and k not in m:
                m[k] = w
        _DOMAIN = m
    return _DOMAIN


def _near1(a, b):
    """a、b 是不是"改一处以内"（含相邻字母换位）—— 只判 ≤1，不算具体距离。"""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diff = [k for k in range(la) if a[k] != b[k]]
        if len(diff) == 1:
            return True
        # 相邻换位（PEGT ↔ PETG、ASB ↔ ABS 这种）
        return (len(diff) == 2 and diff[1] == diff[0] + 1
                and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = j = 0
    skipped = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        elif skipped:
            return False
        else:
            skipped = True
            j += 1
    return True


def _model_key(s):
    """机型名归一化：l/I→1、o→0、大小写无关（P1S / pls / pIs 都算同一个）。"""
    return _fold(s)


#: 一段文字切成交替的 [英文数字词, 其它] —— 只在"词"上做替换，标点/汉字原样保留。
_TOKEN_RE = re.compile(r'[A-Za-z0-9|丨][A-Za-z0-9\-|丨]*')


def _is_tok(s):
    return bool(_TOKEN_RE.fullmatch(s))


def _is_acronym(w):
    """"缩写/型号"写法：带数字，或全大写字母（PLA、3MF、PEI、P1S）。"""
    return any(c.isdigit() for c in w) or (w.isupper() and w.isalpha())


def _case_only(a, b):
    """a、b 是不是"只有大小写不同"（`nozzle` vs `Nozzle` 这种）。

    词表是拿来纠**认错字**的，不是用来统一大小写的 —— 实测踩过：
    `0.4 nozzle` 被改成了 `0.4 Nozzle`（词表里存的是标题写法）。
    例外：缩写/带数字的规范写法（`pla`→`PLA`、`3mf`→`3MF`）该统一。
    """
    return a != b and a.lower() == b.lower() and not _is_acronym(b)


def fix_domain_tokens(text):
    """把认错的机型/材料/平台/术语修回**规范拼写**（P1S、PLA、PETG、PEI…）。

    三条路，从严到宽（越宽的越要"只有唯一解"才敢动）：
      ① **折叠后完全相等**：`pls`/`pIs`/`P15`/`PIS` → `P1S`，
         `PIA`/`P1A` → `PLA`，`PET6`/`PEGT` → `PETG`，`AB5`/`A8S` → `ABS`；
      ② **连着 2~3 个词一起看**：截图上「Bambu Lab」「Textured PEI Plate」
         「PLA Basic」这类是多词，分开看每个都不像；
         也顺带救回"OCR 在词中间插了空格"的情况（`P 1S` → `P1S`）；
      ③ **全大写词允许错一处以内**（换位/单字）：`ASB`→`ABS`、`TPU`←`TUP`、
         `PETC`→`PETG`。**必须唯一命中**，有两个候选就不动 —— 宁可漏改。

    只动这些"有限集合"里的词，别的一律不碰（普通英文单词、数字、中文
    都不受影响），所以不会把「0.16」「Bed」这类改坏。

    ⚠ 两条踩过的坑（2026-10-16 都实测到了，注释留在对应代码处）：
      * **只是大小写不同就别改**（`0.4 nozzle` 被改成过 `0.4 Nozzle`）；
      * **已经正好是规范写法时，不能再往下走"错一处"那条路**，
        否则 `3MF` 会被改成 `AMF`（差一个字符、又是唯一候选），纯属自伤。
    """
    t = text or ''
    if not t:
        return t
    dm = _domain()
    if not dm:
        return t
    ms = list(_TOKEN_RE.finditer(t))
    out, last, i, n = [], 0, 0, len(ms)
    while i < n:
        hit, span, known = None, 1, False
        for k in (3, 2, 1):                      # 多词优先（长的先占位）
            if i + k > n:
                continue
            ok = True
            for x in range(i, i + k - 1):
                # 中间只允许**空白**：不跨标点、不跨汉字（否则会把两句话粘一起）
                if t[ms[x].end():ms[x + 1].start()].strip() != '':
                    ok = False
                    break
            if not ok:
                continue
            joined = ''.join(m.group(0) for m in ms[i:i + k])
            cand = dm.get(_fold(joined))
            raw = t[ms[i].start():ms[i + k - 1].end()]
            if cand:
                span = k
                # 拿**原文这一段**跟规范写法比（不是拼接后的），否则「P 1S」
                # 这种"词中间被插了空格"会被误判成"已经是规范写法"、空格不改
                if raw == cand:
                    known = True             # 已经是规范写法
                elif _case_only(raw, cand):
                    known = True             # 只是大小写不同 → 别改
                else:
                    hit = cand
                break
            # 多词短语再放宽一档：整个短语错两处以内也算（**唯一命中**才改）。
            # 单靠"错一处"救不回「Texturecl PEI Plate」（它离规范写法差了
            # 一个字母 + 一处 l/d 认错，共 2 处）；但短语越长越不可能撞车，
            # 所以只在折叠后 ≥10 个字时才开这一档，且必须唯一。
            fk = _fold(joined)
            if k >= 2 and len(fk) >= 10:
                near = {w for k2, w in dm.items()
                        if abs(len(k2) - len(fk)) <= 2
                        and _dist(fk, k2, 2) <= 2
                        # ★ **词数必须一样**：否则会把多出来的一整词吃掉。
                        #   实测（2026-10-16）「the cool plate is ready」被改成
                        #   「the Cool Plate ready」—— 拿 3 个词去比「Cool Plate」
                        #   （2 个词），"is" 就这么没了。
                        and len(w.split()) == k}
                if len(near) == 1:
                    hit, span = near.pop(), k
                    break
        if hit is None and not known:
            tok = ms[i].group(0)
            fk = _fold(tok)
            # ③ 允许错一处（换位/单字）：全大写的词 3 个字起，其它 4 个字起
            if len(fk) >= 3 and (tok.isupper() or len(fk) >= 4):
                cands = {w for k2, w in dm.items()
                         if len(k2) == len(fk) and _near1(fk, k2)}
                if not cands:
                    # 等长的没有，再放宽±1 个字（实测「Texturecl」缺了个 t，
                    # 而「Textured」比它短 1；不放宽就永远修不回来）
                    cands = {w for k2, w in dm.items()
                             if abs(len(k2) - len(fk)) == 1 and _near1(fk, k2)}
                cands.discard(tok)
                # 换位（ASB→ABS）比"改一个字母"可信得多，优先。
                # ASB 同时离 ASA 只差一个字母，不区分的话会因为"两个候选"
                # 而整个放弃 —— 实测就是这么漏掉的。
                perm = {w for w in cands if sorted(_fold(w)) == sorted(fk)}
                pool = perm or cands
                if len(pool) == 1:
                    hit = pool.pop()
        if hit is None:
            i += span if known else 1
            continue
        out.append(t[last:ms[i].start()])
        out.append(hit)
        last = ms[i + span - 1].end()
        i += span
    out.append(t[last:])
    return ''.join(out)


def fix_model_names(text):
    """旧名字（记忆/自检里还引用着）：现在统一走 `fix_domain_tokens`。"""
    return fix_domain_tokens(text)


def _fix_one(w, vs, cap=1):
    """一小段汉字按词表纠一次（编辑距离 ≤cap，且必须纠成词表里**真实存在**的词）。"""
    if not w or w in vs:
        return w
    best, bd = _best_word(w, vs, cap)
    return best if (best and bd <= cap) else w


def _has_near_word(w, i, j, vs, need):
    """w[i:j] 里有没有长度 ≥ need 的**精确命中**词表的片段。

    用来判断"这一段其实已经认对了、别去动它"（见 `_fix_by_segments` 的说明）。
    """
    for a in range(i, j):
        for b in range(a + 2, j + 1):
            if b - a >= need and w[a:b] in vs:
                return True
    return False


def _fix_by_segments(w, vs, max_w=6, cap=1):
    """长段纠错：**词典驱动的纠错分词**（带代价的 DP，全局最优）。

    为什么需要它：整段比对的编辑距离上限只能给 1（给大了会把
    「支撑阈值角度**改成**」整段吞成「支撑阈值角度」，实测踩过），于是
    「打开支存支殍阈值角度」这种"一段里错两处"的整段比对直接放弃、修不动。

    为什么不是"贪心切词 + 修残渣"（2026-10-16 当天先试过、当天换掉）：
      它要求先切出一个**完全正确**的词当锚点，可 OCR 恰恰会把那个词本身读错
      （「支撑阈值角度」→「支存支殍阈值角度」），切不出锚点就整段不动。
      退一步改成"滑动窗口 + 不重叠"后仍然会误伤：实测
      「打开支撑支撑阈值角度」被改成了「打开支撑面撑阈值角度」——
      因为窗口 (2,5)「支撑支」离词表的「支撑面」只差 1，它就抢着改了。
      根子在于**逐窗口做局部决策**，没人管整句是否变好。

    现在这版把整句当一个问题一次性求解（就是公开 OCR 后处理里的
    "词典 + 编辑距离纠错 + 打分选优"，pycorrector 那条路子的简化版）：
      * 把 w 切成若干片，每片给分：命中词表的词 = 2×字数；
      * "改一个字就能对上的词" = 2×字数 − 1（改动有代价，所以**只有真的更优才改**）；
      * 对不上任何词的零散字 = 0 分；
      * 用 DP 求**总分开最大**的切法。
    于是「打开支撑支撑阈值角度」（每个词都精确命中，16 分）永远打得过
    "改成支撑面"（14 分），而「支存支殍」那两处（0 分）会被换成 6 分，
    该改的改、不该改的不动 —— 这是 DP 相对局部规则的关键好处。
    只做**等长替换**（除了 ≤3 字的残渣允许差 1 个字）：OCR 的主要错误是
    "认错字"而不是"多字少字"，等长替换不会吞字，最安全。
    """
    n = max(0, len(w))
    if n < 2:
        return w
    by_len = {}
    for v in vs:
        by_len.setdefault(len(v), []).append(v)
    # 预计算每个窗口"改一个字能不能对上词表的词"
    fuzzy = {}
    for L in range(2, min(max_w, n) + 1):
        pool = by_len.get(L)
        if not pool:
            continue
        for i in range(n - L + 1):
            seg = w[i:i + L]
            if seg in vs:
                continue                    # 本来就是个词，不需要"纠"
            # ★ 窗口里已经**精确命中**了一个词、且这个词几乎占满整个窗口时，
            #   不要动它 —— 否则会把认对的词吞掉。实测（2026-10-16）：
            #   「只在打印板上支撑」被改成「只在打印**机**支撑」（把"打印板"
            #   扭成了"打印机"，意思全变）。「支撑支」→「支撑面」也是这一类。
            if _has_near_word(w, i, i + L, vs, L - 1):
                continue
            best, bd = _best_word(seg, pool, cap)
            if best is not None and bd <= cap:
                # ★ 一律要求"这次改写**纠正了 `_MISREAD` 里实测见过的错字**"。
                #   为什么不能只按"编辑距离 ≤1"就改（都要命地踩过）：
                #     * 「打样」（打印行业常用词）被纠成「打开」；
                #     * 「帮我**改**成0.12」被纠成「帮我**把**成0.12」——
                #       因为「帮我改」离「帮我把」也只差一个字（2026-10-16）。
                #   要求命中错字表之后，只有"我们真的见过 OCR 这么读错"的
                #   才改；没见过的宁可放过（漏改只是不够聪明，改错是给出假信息）。
                if not _misread_bonus(seg, best):
                    continue
                fuzzy[(i, i + L)] = best
    NEG = -1e9
    dp = [NEG] * (n + 1)
    back = [None] * (n + 1)                 # (片长, 替换成的文字 或 None=原样)
    dp[0] = 0.0
    for i in range(n):
        if dp[i] <= NEG:
            continue
        # ① 认不出来的孤立字：0 分（但保证任何情况都有路可走）
        if dp[i] > dp[i + 1]:
            dp[i + 1], back[i + 1] = dp[i], (1, None)
        # ② ≤3 字的残渣整段纠一次
        for L in (2, 3):
            if i + L > n:
                continue
            # 同样先排除"这段里已经有认对的词"：实测「打印板」会被纠成
            # 「打印机」（都在词表里、差一个字，但意思完全不同）—— 见上一条注释
            if _has_near_word(w, i, i + L, vs, L - 1):
                continue
            rep = _fix_one(w[i:i + L], vs)
            # 残渣同样只认"实测错字表"（理由见上一条注释）
            if rep != w[i:i + L] and not _misread_bonus(w[i:i + L], rep):
                continue
            # ★ 只认**等长**的纠正：`_fix_one` 允许差一个字，放到这里就成了
            #   "吃掉一个字"的通道 —— 实测（2026-10-16）「上支撑」被纠成
            #   「支撑」，整句「只在打印板上支撑」少了一个"上"。宁可漏改，
            #   不能改动字数：多字少字会让参数解析直接错位。
            if rep != w[i:i + L] and len(rep) == L:
                sc = dp[i] + 2.0 * L - 1
                if sc > dp[i + L]:
                    dp[i + L], back[i + L] = sc, (L, rep)
        # ③ 词表里的词（长词优先，平手时选长的，跟旧行为一致）
        for L in range(min(max_w, n - i), 1, -1):
            j = i + L
            seg = w[i:j]
            if seg in vs:
                sc = dp[i] + 2.0 * L
                if sc > dp[j]:
                    dp[j], back[j] = sc, (L, seg)
            elif (i, j) in fuzzy:
                sc = dp[i] + 2.0 * L - 1
                if sc > dp[j]:
                    dp[j], back[j] = sc, (L, fuzzy[(i, j)])
    # 回溯拼回去
    pieces, j = [], n
    while j > 0:
        step = back[j]
        if step is None:                    # 理论上不会发生，兜底原样返回
            return w
        L, rep = step
        pieces.append(w[j - L:j] if rep is None else rep)
        j -= L
    return ''.join(reversed(pieces))


def _score(txt):
    """给一份识别结果打分：**命中语料库的词越多越好**（长词更值钱）。

    多尺度重试靠它挑结果（见 `read_image`）—— 不用"字多"这种粗糙指标：
    放大后字更多但可能更糊，命中词数才是真的"读对了多少"。
    """
    if not txt:
        return 0
    s = 0
    for w in vocab():
        if len(w) >= 2 and w in txt:
            s += len(w)
    return s * 10 + len(txt)


def _clean(text):
    """把 OCR 结果整成"能直接解析参数"的样子。

    2026-10-15 补了三条（都是实测出来的错，不是想象的）：
      * 全角 ％ 归一成 %（截图里常见，老规则只认半角，于是"30 ％"带着空格过去）；
      * 「外墙速度1 20」→「外墙速度120」（OCR 会把一个数拆成两段，
        不接回去解析出来的值是 **1**，整整差 100 倍，还不报错）；
      * 汉字之间**只有单个**空格才算逐字空格要删掉；连续两个以上是原文
        真有的间隔（「打开支撑  外墙速度」），全删会把两个参数粘一起，
        后一个参数就解析不出来了。
    """
    t = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    # 全角符号先归一，后面的规则才好写
    for a, b in (('％', '%'), ('Ｏ', 'O'), ('　', ' '),
                 # 「×」是乘号，OCR 常把字母 x 认成它（实测 13px 小图把
                 # 「X1C」读成「× 1 C」，机型就丢了）。归一成小写 x 之后
                 # `x 1 C` 能被词表当成 `X1C` 收回来。
                 ('×', 'x')):
        t = t.replace(a, b)
    # 汉字之间：连续 2 个以上空格 = 原文的间隔，压成一个留着；单个空格 = 逐字空格，删
    t = re.sub('(?<=[%s])[ \\t]{2,}(?=[%s])' % (_HAN, _HAN), ' ', t)
    t = re.sub('(?<=[%s])[ \\t](?=[%s])' % (_HAN, _HAN), '', t)
    t = re.sub('(?<=[%s])[ \\t]+(?=[0-9A-Za-z])' % _HAN, '', t)
    t = re.sub('(?<=[0-9A-Za-z])[ \\t]+(?=[%s])' % _HAN, '', t)
    # OCR 常把小数点认成间隔号/中点/逗号（实测「0 · 16」「0 ， 16」「0，16」），
    # 数字夹着的都换回小数点，不然后面解析参数会把这个值当成无效数字直接丢掉
    # （两边的空格也一起吃掉）。逗号是 2026-10-15 加进来的：放大后 OCR
    # 反而更容易把小数点读成中文逗号，实测「层高 0.16」→「层高0 ， 16」。
    t = re.sub(r'(?<=[0-9])[ \\t]*[·．、，,][ \\t]*(?=[0-9])', '.', t)
    # 一个数被拆成两段：「1 20」→「120」。
    # 只接这两种安全情形 —— 左边是**单独一位**数字（1 20 / 3 50），
    # 或者左边已经带着小数点（0.1 6 → 0.16）。
    # 「100 25」这种（左边不是一位）不接：把两个独立的值粘成一个更糟。
    t = re.sub(r'(?<=[0-9]\.)(\d)[ \\t]+(\d+)(?![\d.])', r'\1\2', t)
    t = re.sub(r'(?<![\d.])(\d)[ \\t]+(\d+)(?![\d.])', r'\1\2', t)
    # 单位前的空格也去掉：「25 %」→「25%」
    t = re.sub(r'[ \\t]+([%℃°])', r'\1', t)
    # 中文标点前后的空格也去掉：「层高0.16 ， 层数3」→「层高0.16，层数3」
    # （OCR 会给标点让位，读起来像断句；用户那条截图就是这个样子）
    t = re.sub(r'[ \\t]*([，。、；：！？）】」》…])[ \\t]*', r'\1', t)
    # 一行里全是空格的、以及首尾空行，去掉
    lines = [ln.strip() for ln in t.split('\n')]
    t = '\n'.join(ln for ln in lines if ln).strip()
    # 行首的孤零零标点：OCR 会把截图左上角那个点/逗号/横线单独读出来
    # （2026-10-16 实测：24px 那张读出「． 层高0.16」，多一个符号就多一行垃圾）
    t = re.sub(r'(?m)^[ \t]*[．·、,，。;；:：|｜\-—_~・\'"`]+[ \t]*(?=[0-9A-Za-z\u4e00-\u9fff])',
               '', t)
    # 最后过两遍：① 中文参数语料库纠错（近义词/拆字）
    #              ② 3D 打印词表的规范拼写（pls→P1S、PIA→PLA、PET6→PETG…）
    fixed = fix_domain_tokens(correct(t))
    # 规范词替换会保留原来的词间空格（「P E | 打印板」→「PEI 打印板」）。
    # 在中英文交界处再收一次，让语料里的「纹理PEI打印板」能整体命中。
    fixed = re.sub(r'(?<=[0-9A-Za-z])[ \t]+(?=[%s])' % _HAN, '', fixed)
    fixed = re.sub(r'(?<=[%s])[ \t]+(?=[0-9A-Za-z])' % _HAN, '', fixed)
    return fixed


def available():
    """这台机器上能不能用（True/False + 说明）。"""
    if not os.path.isfile(PS1):
        # 说人话：用户不知道 ocr_win.ps1 是什么。这是安装包不全（打包漏了
        # 数据文件），重装/换新版就好 —— 2026-10-15 的真实反馈。
        return False, '读图功能缺文件（安装包不全，重新装一次就好）'
    if os.name != 'nt':
        return False, '只有 Windows 才有这个引擎'
    return True, ''


#: 鼠标指针可能出现的尺寸（屏上像素）。Windows 默认 32；125%/150%/200% 缩放
#: 分别是 40/48/64，用户还能在辅助功能里再调大，所以铺一串。
CURSOR_SIZES = (32, 40, 48, 56, 64, 80, 96)

_CURSOR_TPL = {}

#: **Windows 默认箭头指针**的形状（32 号那一档实际占 12×18）。
#: 这不是手画的：是在开发机上把系统指针 `IDC_ARROW` 画到白底上、再去掉背景
#: 得到的（`#` = 指针真正画上去的像素），和你在截图里看到的一模一样。
#: ⚠ 为什么**离线写死**、不在运行的时候去问系统要：
#:   打包成 exe 之后 `LoadCursorW` + `DrawIconEx` 那套在冻结环境里没成，
#:   模板取不到 → 擦指针整段悄悄失效（2026-10-16 实测，打包版上就是这个现象）。
#:   写死之后只依赖 numpy，冻结版也稳。
_ARROW_OUT = (
    '#...........', '##..........', '#.#.........', '#..#........',
    '#...#.......', '#....#......', '#.....#.....', '#......#....',
    '#.......#...', '#........#..', '#.........#.', '#..........#',
    '#......#####', '#...#..#....', '#.#.#..#....', '#.......#...',
    '.....#......', '......#.....',
)
_ARROW_CORE = (
    '............', '............', '............', '............',
    '..#.........', '..##........', '..###.......', '..####......',
    '..#####.....', '..######....', '..#######...', '..#####.....',
    '..##.#......', '............', '............', '......#.....',
    '.......#....', '............',
)


def _cursor_masks(size):
    """指针在某个屏上尺寸下的两套掩码 → (轮廓点, 白芯点)。

    系统指针就是把同一份形状整体放大（实测 32→12×18、64→24×36、
    96→36×54，正好整数倍），所以按比例做最近邻放大就够。
    """
    key = int(size)
    if key in _CURSOR_TPL:
        return _CURSOR_TPL[key]
    res = (None, None)
    try:
        import numpy as np
        out = np.array([[c == '#' for c in r] for r in _ARROW_OUT])
        core = np.array([[c == '#' for c in r] for r in _ARROW_CORE])
        f = max(1.0, key / 32.0)
        th = max(1, int(round(out.shape[0] * f)))
        tw = max(1, int(round(out.shape[1] * f)))
        ys = (np.arange(th) * out.shape[0] // th)
        xs = (np.arange(tw) * out.shape[1] // tw)
        res = (out[ys][:, xs], core[ys][:, xs])
    except Exception:                                             # noqa: BLE001
        res = (None, None)
    _CURSOR_TPL[key] = res
    return res


def _spread(ys, xs, want):
    """把点集均匀取 `want` 个出来（先用少量点筛，再全量复核，省时间）。"""
    k = len(ys)
    if k <= want:
        return ys, xs
    step = max(1, k // want)
    return ys[::step][:want], xs[::step][:want]


def _line_bands(gray):
    """按行投影找出**文字行** → [(y0, y1, x0, x1), ...]（原图坐标）。

    为什么要先找行：OCR 是"先把图上的字按行分组再认"，而指针一擦，
    同一行会被切成左右两块（实测「外墙速度 120」变成「外墙速度」+「120」两条）。
    所以判断"指针压住了哪一行"必须在**原图**上按行算，不能等 OCR 分完组再按
    左右位置对 —— 那样两个碎片都不算被压到，反而留在结果里。
    """
    import numpy as np
    rows = (gray < 110).any(axis=1)
    idx = np.nonzero(rows)[0]
    if idx.size == 0:
        return []
    dark = gray < 110
    bands, start, prev = [], int(idx[0]), int(idx[0])
    for r in idx[1:]:
        r = int(r)
        if r - prev <= 2:                     # 行内的小空隙算同一行
            prev = r
        else:
            bands.append((start, prev + 1))
            start = prev = r
    bands.append((start, prev + 1))
    out = []
    for (y0, y1) in bands:
        cols = np.nonzero(dark[y0:y1].any(axis=0))[0]
        out.append((y0, y1, int(cols.min()), int(cols.max()) + 1))
    return out


def _drop_covered(lines, rects, bad_rows):
    """把**被鼠标指针压到**的那些识别行整行丢掉 → (留下的文字, 丢了几行)。

    为什么要丢整行，而不是留着让用户自己看（实测 2026-10-16）：
      指针压住「0.16」的中间，擦掉之后 OCR 会把残留的半个字读成
      「层高0 **“** 3」—— 这里面的 `3` 一旦被参数解析器当数值用，
      就是**悄悄把层高改成 3mm**。宁可这一行什么都没有（用户重截一张
      就对了），也不能给出一个看着像真的、其实是错的值。
    """
    if not bad_rows or len(lines) != len(rects):
        return '\n'.join(lines), 0
    keep, dropped = [], 0
    for i, ln in enumerate(lines):
        y0, y1 = rects[i][1], rects[i][3]
        hit = any(y0 < by1 and by0 < y1 for (by0, by1) in bad_rows)
        if hit:
            dropped += 1
        else:
            keep.append(ln)
    return '\n'.join(keep), dropped


def strip_cursor(image):
    """把图上的**鼠标指针**擦掉 → (新图, 擦掉几处)。

    为什么要在识别**之前**擦（用户 2026-10-16：「不想让他识别光标」）：
    实测把系统箭头贴到一张参数截图上再走 OCR，三种坏结果都有：

    | 情况 | 结果 |
    |---|---|
    | 指针压住数字 | 「层高 0.16」被读成「层高**0.6**」—— **值直接错了** |
    | 指针压在字旁边 | 指针本身被读成一个汉字（「**住**」），混进参数里 |
    | 指针放大到 2 倍 | 整张图**一个字都读不出来** |

    所以指针不是"最多多认一个符号"，它会让识别**又错又少**。做法：
    拿系统指针当模板，在图上找"黑轮廓 + 白芯"的位置（轮廓是黑的、芯是白的，
    跟背景明暗无关，所以亮底/暗底都能找），找到就用**周围的底色**涂掉。
    """
    try:
        import numpy as np
        from PIL import Image
        im = image.convert('RGB')
        gray = np.asarray(im.convert('L'))
        H, W = gray.shape
        # ★ 指针的芯是**纯白**，阈值必须卡在纯白附近（>240），不能是"偏白"。
        #   实测（2026-10-16）：放到 >200 时，整段文字的图上冒出一堆通过校验的
        #   假位置 —— 因为文字的抗锯齿灰边（200~250）也被算成"白"，于是
        #   "白芯是白的"这条就失效了，真被它擦掉并丢掉一整行。
        #   量出来的分界：真指针的白芯比例 0.96~1.00，文字里最多 0.43。
        light = gray > 240
        boxes = []
        raw = []
        for size in CURSOR_SIZES:
            tpl, core = _cursor_masks(size)
            if tpl is None:
                continue
            th, tw = tpl.shape
            if th + 4 >= H or tw + 4 >= W:
                break
            # ★ 轮廓用**宽松**阈值：系统指针被放大后（150%/200% 缩放屏）
            #   边缘是抗锯齿的灰边，卡 `gray<110` 会整片漏掉 —— 实测
            #   48/64 两个尺寸就是这么漏掉的，指针没被擦掉、字还是被读错。
            dark = gray < 175
            # ★ 再给 1 像素容差：模板是按比例放大出来的，线条会变成 2px 粗，
            #   而系统渲染出来的指针是 1px 细线（实测 48/64 两档差在这）。
            #   允许"目标点附近 1 像素内有深色"就能对上；误判由下面
            #   "白芯必须是纯白"那条卡住。
            near = dark.copy()
            near[1:, :] |= dark[:-1, :]
            near[:-1, :] |= dark[1:, :]
            near[:, 1:] |= dark[:, :-1]
            near[:, :-1] |= dark[:, 1:]
            # 斜着的边要留出**斜对角**的容差：模板放大后斜边是 2px（两格斜着
            # 挨着），系统渲染出来是 1px —— 只给上下左右 4 邻域还是对不上
            # （实测 32/48 能认出来、64 认不出来，就差这一格斜的）
            near[1:, 1:] |= dark[:-1, :-1]
            near[1:, :-1] |= dark[:-1, 1:]
            near[:-1, 1:] |= dark[1:, :-1]
            near[:-1, :-1] |= dark[1:, 1:]
            dark = near
            ph, pw = H - th + 1, W - tw + 1
            ys, xs = np.nonzero(tpl)
            fy, fx = _spread(ys, xs, 24)              # 先用少量点粗筛
            acc = dark[:ph, :pw].copy()
            for dy, dx in zip(fy, fx):
                if not acc.any():
                    break
                acc &= dark[dy:dy + ph, dx:dx + pw]
            cy, cx = np.nonzero(core)
            oy, ox = np.nonzero(acc)
            for y, x in zip(oy, ox):
                # 复核一：整个轮廓基本都对上（允许抗锯齿差一两个点）
                hit_o = dark[y + ys, x + xs].mean()
                if hit_o < 0.85:
                    continue
                # 复核二：白芯必须是白的（指针的核心特征）
                if light[y + cy, x + cx].mean() < 0.90:
                    continue
                raw.append((size, int(x), int(y), th, tw))
        # ★ 复核三（关键）：**成团才算**。
        #   真指针会让连续好几个位置都对上（实测 5~8 个挤在一片，因为指针
        #   正好比模板大一点/小一点时，相邻位置也能匹配）；而文字里偶尔冒出来
        #   的假位置是**孤立的 1 个**（实测 10 张文字图：最多 1 个，多数 0 个）。
        #   这条是拿数据定出来的分界：真指针成团 ≥5，文字成团 ≤1，取 3 当门槛。
        for (sz, x, y, th, tw) in raw:
            near_n = sum(1 for (sz2, x2, y2, _a, _b) in raw
                         if abs(x - x2) <= 4 and abs(y - y2) <= 4)
            if near_n >= 3:
                boxes.append((y, x, th, tw))
        if not boxes:
            return im, []           # 没找到指针 → 后面按"没有任何行要丢"处理
        # 多个尺寸可能找到同一处，去重（留大的那个）
        boxes.sort(key=lambda b: -b[2] * b[3])
        keep = []
        for b in boxes:
            y, x, th, tw = b
            dup = False
            for (Y, X, TH, TW) in keep:
                if (abs(y - Y) < 6 and abs(x - X) < 6):
                    dup = True
                    break
            if not dup:
                keep.append(b)
        arr = np.asarray(im).copy()
        # 先擦掉指针，再找"文字行" —— 顺序不能反：指针自己也是深色像素，
        # 先找行的话它会把那一行的范围撑宽（x 一直伸到指针位置），
        # 于是"指针明明在文字右边、没压到字"也会被判成压住了（实测踩过）。
        for (y, x, th, tw) in keep:
            y0, x0 = max(0, y - 2), max(0, x - 2)
            y1, x1 = min(H, y + th + 2), min(W, x + tw + 2)
            ring = np.concatenate([
                arr[max(0, y0 - 3):y0, x0:x1].reshape(-1, 3),
                arr[y1:min(H, y1 + 3), x0:x1].reshape(-1, 3)])
            if len(ring) < 4:
                fill = np.array([255, 255, 255], np.uint8)
            else:                                   # 用周围底色涂，亮底暗底都自然
                fill = np.median(ring, axis=0).astype(np.uint8)
            arr[y0:y1, x0:x1] = fill
        out_img = Image.fromarray(arr, 'RGB')
        gray2 = np.asarray(out_img.convert('L'))
        bad_rows = []
        for (y, x, th, tw) in keep:
            y0, x0 = max(0, y - 2), max(0, x - 2)
            y1, x1 = min(H, y + th + 2), min(W, x + tw + 2)
            # 指针**压在这一行的字上**（横竖都碰上）→ 这一行整个作废
            for (by0, by1, bx0, bx1) in _line_bands(gray2):
                if by0 < y1 and y0 < by1 and bx0 < x1 and x0 < bx1:
                    bad_rows.append((by0, by1))
        return out_img, bad_rows
    except Exception as e:                         # noqa: BLE001
        # 出错就照原图识别（功能降级，不挡住认字）；错误留着给自检看
        global STRIP_ERR
        STRIP_ERR = repr(e)
        return image, []


def _prep(image, extra=1.0):
    """把图整成"Windows OCR 喜欢的样子"：RGB、PNG、边长 ≤ MAX_SIDE。

    `image` 可以是路径，也可以是 PIL 的 Image。返回 (临时文件路径, 是否要删)。
    `extra` 是额外倍率（同一条流水线会按不同倍率各跑一次，挑最好的，见
    `read_image`）。

    ★ 2026-10-15 补了"**小图先放大**"：Windows 的 OCR 对小字很差 ——
      同一段字（微软雅黑）实测：
        字号13 原尺寸 → 「层16 / 外堆速豆120 / 打开支支值角度50」（错得没法用）
        字号13 放大3倍 → 「层咼0.16 / 外墙速度120 / 打开支支阈值角度50」（基本对）
        字号24 原尺寸 → 全对
      用户说"图片识别不准"，多半就是截的小字。以前这里只会**缩小**大图，
      小图原样送进去，所以小字一直差。现在小于 TARGET_SIDE 的先放大（最多 3 倍），
      LANCZOS 重采样 —— 只是把已有的像素摊开，不引入新内容。
    """
    from PIL import Image
    tmp = None
    if isinstance(image, str):
        src = Image.open(image)
    else:
        src = image
    src = src.convert('RGB')
    w, h = src.size
    scale = min(extra, float(MAX_SIDE) / max(1, max(w, h)))
    if scale > 1.0 or scale < 1.0:
        src = src.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.LANCZOS)
    fd, tmp = tempfile.mkstemp(suffix='.png', prefix='ocr_')
    os.close(fd)
    src.save(tmp, 'PNG')
    return tmp, True


def read_image(image):
    """读图（路径或 PIL Image）→ (ok, 文字, 说明)。**不抛异常**。"""
    ok, why = available()
    if not ok:
        return False, '', why
    tmp = None
    out = None
    # ★ 识别前先把鼠标指针擦掉（用户 2026-10-16：「不想让他识别光标」）。
    #   指针会让 OCR 既认错字又吃掉数字，见 `strip_cursor` 里的实测表。
    #   擦之前**先自己看一眼**再决定要不要动：只在图上真找到指针时才复制图。
    global LAST_CURSOR_NOTE
    LAST_CURSOR_NOTE = ''
    BAD_ROWS = []
    try:
        from PIL import Image as _I2
        src = _I2.open(image) if isinstance(image, str) else image
        cleaned, bad_rows = strip_cursor(src)
        if bad_rows:
            image = cleaned
            LAST_CURSOR_NOTE = '这张图上有鼠标指针，我已先把它擦掉再认字。'
        BAD_ROWS = bad_rows
    except Exception:                                 # noqa: BLE001
        BAD_ROWS = []
    try:
        # ★ 多尺度各跑一次，挑"最像参数文本"的那份（用户 2026-10-15：
        #   「这么清晰的字，都识别不明白？」的截图里有 p1s → pls、
        #   层数 → 文 这类错）。Windows OCR 对**字号**很敏感：同一张图
        #   放大 2 倍常常多认对好几个词，所以两档都试，用命中语料库的多少打分。
        try:
            from PIL import Image as _I
            base = _I.open(image) if isinstance(image, str) else image
            bw_, bh_ = base.size
        except Exception:                                 # noqa: BLE001
            bw_, bh_ = 1000, 1000
        scales = [1.0]
        if max(bw_, bh_) * 2.0 <= MAX_SIDE:
            scales.append(2.0)
        elif max(bw_, bh_) < TARGET_SIDE:
            scales.append(min(3.0, float(TARGET_SIDE) / max(1, max(bw_, bh_))))
        best = None
        last_rc = 0
        dropped_lines = 0
        for sc in scales:
            tmp, _ = _prep(image, sc)
            fd, out = tempfile.mkstemp(suffix='.txt', prefix='ocr_')
            os.close(fd)
            fd2, rct = tempfile.mkstemp(suffix='.rct', prefix='ocr_')
            os.close(fd2)
            # creationflags 隐藏控制台窗口：挂件是 GUI 程序，弹黑框很难看
            flags = 0x08000000 if os.name == 'nt' else 0
            p = subprocess.run(
                ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                 '-File', PS1, tmp, out, rct],
                capture_output=True, timeout=TIMEOUT, creationflags=flags)
            text = ''
            try:
                with open(out, encoding='utf-8', errors='replace') as f:
                    text = f.read()
            except OSError:
                text = ''
            # 每行的位置（有了它才知道哪一行被鼠标指针压住了）
            rects = []
            try:
                with open(rct, encoding='utf-8', errors='replace') as f:
                    for ln in f:
                        ln = ln.strip()
                        if ln:
                            a, b, c, d = [int(v) for v in ln.split(',')]
                            rects.append((a, b, c, d))
            except Exception:                                 # noqa: BLE001
                rects = []
            for f_ in (tmp, out, rct):
                try:
                    os.remove(f_)
                except OSError:
                    pass
            tmp = out = None
            last_rc = p.returncode
            # 被指针压到的那些行，按这一档的放大倍数换算成同一坐标系后再丢
            if BAD_ROWS and rects:
                k = min(sc, float(MAX_SIDE) / max(1, max(bw_, bh_)))
                sc_rows = [(int(y0 * k), int(y1 * k)) for (y0, y1) in BAD_ROWS]
                text, n_drop = _drop_covered(text.split('\n'), rects, sc_rows)
                dropped_lines = max(dropped_lines, n_drop)
            cand = _clean(text)
            s = _score(cand)
            if best is None or s > best[0]:
                best = (s, cand)
            if sc != 1.0 and best[0] > 0:
                break                     # 放大这档已经能认出词了，够了
        tmp = out = None
        txt = best[1] if best else ''
        if dropped_lines:
            # 短一点：挂件气泡窄，太长会折成三行（实测截图里就是三行，很占地方）
            LAST_CURSOR_NOTE = ('鼠标指针压住了字，那一行我没读（怕读错数值）。'
                                '挪开鼠标重截一张就好。')
        if last_rc != 0:
            return False, txt, (txt or 'OCR 没跑起来')
        if not txt:
            # 如果是指针把整张图糊掉了（实测放大版指针会这样），要说清是哪种
            return False, '', (LAST_CURSOR_NOTE or '这张图里没认出文字')
        return True, txt, LAST_CURSOR_NOTE
    except subprocess.TimeoutExpired:
        return False, '', 'OCR 超时（图太大？）'
    except Exception as e:                       # noqa: BLE001
        return False, '', 'OCR 失败：%s' % str(e)[:80]
    finally:
        for f in (tmp, out):
            try:
                if f:
                    os.remove(f)
            except OSError:
                pass


def read_text(path):
    """读一张图 → (ok, 文字, 说明)。"""
    if not path or not os.path.isfile(path):
        return False, '', '找不到这个文件'
    return read_image(path)


def clipboard_image():
    """从剪贴板取一张图（截图后直接 Ctrl+V 用）→ PIL Image 或 None。"""
    try:
        from PIL import ImageGrab
        data = ImageGrab.grabclipboard()
    except Exception:                            # noqa: BLE001
        return None
    if data is None:
        return None
    if isinstance(data, list):                   # 复制的是"文件"，取第一张图
        for p in data:
            if str(p).lower().endswith(('.png', '.jpg', '.jpeg', '.bmp',
                                        '.webp', '.tif', '.tiff')):
                try:
                    from PIL import Image
                    return Image.open(p)
                except Exception:                # noqa: BLE001
                    return None
        return None
    return data                                  # 已经是 Image


if __name__ == '__main__':
    if len(sys.argv) > 1:
        _ok, _t, _w = read_text(sys.argv[1])
        sys.stdout.reconfigure(encoding='utf-8')
        print('ok=%s why=%s\n%s' % (_ok, _w, _t))
