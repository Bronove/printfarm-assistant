# -*- coding: utf-8 -*-
"""Generated public headless subset of the legacy desktop core.

This file is assembled from reviewed legacy methods. Product features
outside the public workbench are intentionally not included.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter, defaultdict
from types import SimpleNamespace

import materials
import voice_norm

FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
CLI_DIR = os.path.join(BUNDLE_DIR, "bambu_cli")
DATA_DIR = os.environ.get("PRINTFARM_DATA_DIR") or APP_DIR
PY_EXE = sys.executable
VERSION = "1.5.0-beta.2"
APP_NAME = "打印农场助手 1.5.0-beta.2"


FROZEN = bool(getattr(sys, 'frozen', False))

if FROZEN:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, '_MEIPASS', APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR

if FROZEN:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, '_MEIPASS', APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR

CLI_DIR = os.path.join(BUNDLE_DIR, 'bambu_cli')

DATA_DIR = os.environ.get('PRINTFARM_DATA_DIR') or APP_DIR

CONFIG_PATH = os.path.join(DATA_DIR, 'config.json')

if not os.path.isfile(PY_EXE):
    PY_EXE = sys.executable

RECIPE = {
    'layer_height': '0.2',
    'infill': '15',
    'pattern': 'grid',
    'support': 'tree_plate',
    'orient': True,
    'arrange': True,
    'min_support': False,
}

TOOLBOX_TOOLS = (
    ('hide_z_seam', '隐藏 Z 缝',
     '按外壁长短自动选 5–15 mm 斜拼'),
    ('top_ironing', '顶面熨烫',
     '顶层再走一遍，表面更平但更慢'),
)

def _cn_num(s):
    """中文数字转阿拉伯：零点二→0.2、二十三→23、百分之五十→50。

    实现搬到了共享模块 voice_norm（挂件也要用同一份），这里只是别名。
    """
    return voice_norm.cn_num(s)

class SliceApp:

    def _save_config(self):
        self.cfg['output_dir'] = self.out_dir
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _figurine_mode_on(self):
        return False

    def _filament_edit_locked(self, models=None):
        """多色/多材料 3MF 禁止在助手里换色或换材料类别。"""
        paths = list(models if models is not None else getattr(self, 'models', []))
        if not paths:
            return False
        cache = getattr(self, '_filament_lock_cache', None)
        if cache is None:
            cache = self._filament_lock_cache = {}
        for path in paths:
            if not str(path).lower().endswith('.3mf'):
                continue
            try:
                stat = os.stat(path)
                key = (os.path.abspath(path), stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
            if key in cache:
                locked = cache[key]
            else:
                try:
                    if CLI_DIR not in sys.path:
                        sys.path.insert(0, CLI_DIR)
                    import unpack_3mf
                    locked = bool(
                        unpack_3mf.project_filament_info(path).get('multicolor'))
                except Exception:                         # noqa: BLE001
                    locked = False
                cache[key] = locked
            if locked:
                return True
        return False

    def _effective_tight(self):
        if self._figurine_mode_on():
            return False
        ov = getattr(self, 'overrides', None) or {}
        if 'tight' in ov:
            tight = bool(ov['tight'])
        else:
            tight = bool(getattr(self, 'var_tight', None)
                         and self.var_tight.get())
        return bool(tight)

    def _effective_min_support(self):
        if self._figurine_mode_on():
            return False
        ov = getattr(self, 'overrides', None) or {}
        if 'min_support' in ov:
            return bool(ov['min_support'])
        return bool(getattr(self, 'var_min_support', None)
                    and self.var_min_support.get())

    def _param_parts(self, ov=None):
        if ov is None:
            try:
                ov = self.parse_requirements(self.var_folder.get())
            except Exception:
                ov = {}
        m = ov.get('machine') or (self._machine_display_name(
            self.cfg.get('machine') or 'Bambu Lab P1S 0.4 nozzle') or 'P1S')
        layer = ov.get('layer_height', '0.2')
        infill = ov.get('infill', '15')
        pat = {}
        for _k, _v in self.PATTERN_CN.items():
            pat.setdefault(_v, _k)
        pattern = pat.get(ov.get('pattern', 'grid'), '网格')
        if pattern:
            pattern = pattern.replace('3d蜂窝', '3D蜂窝')
        sup = {'tree_plate': '树状支撑', 'tree_all': '树状支撑',
               'normal_plate': '普通支撑', 'normal_all': '普通支撑',
               'none': '无支撑'}
        support = sup.get(ov.get('support', 'tree_plate'), '树状支撑')
        if ov.get('support') in ('tree_all', 'normal_all'):
            support += '（整机）'
        elif ov.get('support', 'tree_plate') != 'none':
            support += '（仅打印板）'
        bed = '纹理钢板'
        if 'Cool' in str(self.cfg.get('bed', '')):
            bed = '冷却板'
        elif 'High' in str(self.cfg.get('bed', '')):
            bed = '高温板'
        fil = 'PLA'
        _fam = ov.get('_mat_family')
        if _fam and _fam in self.MATERIAL_INFO:
            fil = self.MATERIAL_INFO[_fam][0]
            if ov.get('_mat_fuzzy'):
                fil += '？'
        else:
            _fname = str(ov.get('filament') or
                         self.cfg.get('filament') or '')
            for _k in ('PLA-CF', 'PETG-CF', 'ABS-GF', 'TPU', 'PETG',
                       'PLA', 'ABS'):
                if _k in _fname.upper():
                    fil = _k
                    break
        parts = [f'{m}', bed, fil, f'{layer}mm', f'{infill}% {pattern}',
                 support]
        pack = ov.get('pack')
        if pack is None:
            pack = bool(getattr(self, 'var_pack', None)
                        and self.var_pack.get())
        tight = ov.get('tight')
        if tight is None:
            tight = bool(getattr(self, 'var_tight', None)
                         and self.var_tight.get())
        if self._figurine_mode_on():
            tight = False
        if ov.get('clone'):
            parts.append(f'打{ov["clone"]}个')
            parts.append('关闭自动定向' if ov.get('orient') is False
                         else '自动选底面')
        if pack and tight:
            parts.append('最省空间')
        elif pack:
            parts.append('摆盘')
        elif tight:
            # 只开紧凑、没开摆盘：这时它做的是"把一个文件里的多零件拆开重排"，
            # 说"最省空间"会和上一行的"不摆盘"打架，所以这里说明白它干了什么
            parts.append('紧凑（拆件重排）')
        else:
            parts.append('不摆盘')
        min_on = (ov.get('min_support') if 'min_support' in ov
                  else getattr(self, '_effective_min_support',
                               lambda: False)())
        if self._figurine_mode_on():
            min_on = False
        if min_on:
            parts.append('最少支撑')
        parts += self._extra_display(ov)
        parts += self._toolbox_labels()
        # 直通项直接显示成键=值，让用户核对自己写了什么
        parts += list(ov.get('_raw') or [])
        if ov.get('_personal'):
            parts.append('含个人习惯')
        return parts

    def _current_params_parts(self, ov=None):
        """返回翻译后的参数条目列表（胶囊用）。失败时返回空列表。"""
        try:
            return self._param_parts(ov)
        except Exception:
            return []

    def _toolbox_active_keys(self):
        return [k for k, _title, _desc in TOOLBOX_TOOLS
                if self._toolbox_vars[k].get()]

    def _toolbox_labels(self):
        names = {k: title for k, title, _desc in TOOLBOX_TOOLS}
        return [names[k] for k in self._toolbox_active_keys()]

    def _toolbox_override_pairs(self):
        """把勾选项翻译成 Bambu 参数；返回 key=value 字符串列表。"""
        active = set(self._toolbox_active_keys())
        out = []
        if 'hide_z_seam' in active:
            out += [
                'seam_position=nearest',
                'seam_gap=15%',
                'seam_slope_conditional=1',
                'scarf_angle_threshold=155',
                'seam_slope_entire_loop=0',
                'seam_slope_steps=10',
                'seam_slope_inner_walls=1',
                'override_filament_scarf_seam_setting=1',
                'seam_slope_type=external',
                'seam_slope_start_height=10%',
                'seam_slope_gap=0%',
                'seam_slope_min_length=10',
                'filament_scarf_seam_type=external',
                'filament_scarf_height=10%',
                'filament_scarf_gap=0%',
                'filament_scarf_length=10',
            ]
        if 'top_ironing' in active:
            out += [
                'ironing_type=topmost',
                'ironing_speed=30',
                'ironing_flow=10%',
            ]
        return out

    PATTERN_CN = {
        '3d蜂窝': '3dhoneycomb', '三维蜂窝': '3dhoneycomb',
        '网格': 'grid', '直线': 'lines', '螺旋': 'gyroid',
        '蜂窝': 'honeycomb', '立方': 'cubic', '闪电': 'lightning',
        '三角': 'triangles',
    }

    SUPPORT_CN = {
        '无支撑': 'none', '普通支撑': 'normal_plate', '正常支撑': 'normal_plate',
        '树状支撑': 'tree_plate', '树支撑': 'tree_plate', '树形支撑': 'tree_plate',
    }

    BED_CN = {
        '纹理': 'Textured PEI Plate', '冷却': 'Cool Plate',
        '高温': 'High Temp Plate', '工程': 'Engineering Plate',
    }

    EXTRA_CN = {
        'wall_loops': '墙层数',
        'inner_wall_speed': '内墙速度',
        'outer_wall_speed': '外墙速度',
        'sparse_infill_speed': '填充速度',
        'internal_solid_infill_speed': '实心速度',
        'top_surface_speed': '顶面速度',
        'initial_layer_speed': '首层速度',
        'ironing_type': '熨烫',
        'ironing_speed': '熨烫速度',
        'brim_type': '裙边类型',
        'brim_width': '裙边宽',
        'skirt_loops': '裙边圈数',
        'raft_layers': '底座层数',
        'top_shell_layers': '顶层数',
        'bottom_shell_layers': '底层数',
        'seam_position': '接缝',
        'print_sequence': '打印顺序',
        'brim_object_gap': '裙边间距',
        'ironing_flow': '熨烫流量',
    }

    MATERIAL_INFO = materials.MATERIAL_INFO

    @staticmethod
    def _norm_voice(text):
        """语音输入归一化：同音纠正、口语简化、中文数字转阿拉伯、
        去语气词/废话、合并重复，输出尽量干净的参数描述。"""
        return voice_norm.normalize(text)

    def _parse_extra(self, text, raw=''):
        """高级参数：新手把别人给的参数建议整段粘贴即可识别。
        覆盖：墙层数、内/外墙速度、熨烫、裙边(类型/宽度/圈数)、
        顶/底层数、接缝、打印顺序、底座、各类速度；也支持 key=value。
        """
        ov = {}
        wt = text or ''

        def grab(pat, key, unit=1):
            nonlocal wt
            m = re.search(pat, wt, re.I)
            if not m:
                return
            ov[key] = m.group(unit)
            wt = (wt[:m.start()] + ' ' * (m.end() - m.start())
                  + wt[m.end():])

        # 数值型参数（按顺序提取，避免数字被重复使用）
        grab(r'(?:skirt|裙边)\s*(?:的)?\s*(?:层数|圈数|层|圈|loops?)'
             r'\s*[:：=为]?\s*(\d+)', 'skirt_loops')
        grab(r'(?:墙|壁|wall|walls)\s*(?:的)?\s*(?:层|圈|loops?|数量|数)'
             r'\s*[:：=为]?\s*(\d+)', 'wall_loops')
        grab(r'(?:墙|壁|wall|walls)\s*(\d+)\s*(?:层|圈|loops?)',
             'wall_loops')
        grab(r'(\d+)\s*(?:层|圈|loops?)\s*(?:墙|壁)', 'wall_loops')
        grab(r'(?:内墙|内壁|inner\s*wall)\s*(?:速度|speed)?\s*[:：=为]?\s*'
             r'(\d+)(?!\s*(?:层|圈|mm|毫米))', 'inner_wall_speed')
        grab(r'(?:外墙|外壁|outer\s*wall)\s*(?:速度|speed)?\s*[:：=为]?\s*'
             r'(\d+)(?!\s*(?:层|圈|mm|毫米))', 'outer_wall_speed')
        grab(r'(?:填充|sparse\s*infill)\s*(?:的)?\s*速度\s*[:：=为]?\s*'
             r'(\d+)', 'sparse_infill_speed')
        grab(r'(?:实心|internal\s*solid(?:\s*infill)?)\s*(?:的)?\s*速度'
             r'\s*[:：=为]?\s*(\d+)', 'internal_solid_infill_speed')
        grab(r'(?:顶面|top\s*surface)\s*(?:的)?\s*速度\s*[:：=为]?\s*'
             r'(\d+)', 'top_surface_speed')
        grab(r'(?:首层|initial\s*layer)\s*(?:的)?\s*速度\s*[:：=为]?\s*'
             r'(\d+)', 'initial_layer_speed')
        grab(r'(?:熨烫|ironing)\s*(?:的)?\s*速度\s*[:：=为]?\s*(\d+)',
             'ironing_speed')
        grab(r'(?:顶层|顶部|top\s*(?:shell|layer)s?)\s*(?:的)?\s*'
             r'(?:层|shells?|layers?)?\s*[:：=为]?\s*(\d+)',
             'top_shell_layers')
        grab(r'(?:底层|底部|bottom\s*(?:shell|layer)s?)\s*(?:的)?\s*'
             r'(?:层|shells?|layers?)?\s*[:：=为]?\s*(\d+)',
             'bottom_shell_layers')
        grab(r'(?:brim|裙边|防翘边)\s*(?:的)?\s*(?:宽度|宽度|width)?'
             r'\s*[:：=为]?\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?', 'brim_width')
        grab(r'(?:底座|raft)\s*(?:层数|层|layers?)?\s*[:：=为]?\s*(\d+)',
             'raft_layers')
        grab(r'(?:brim|裙边|防翘边)\s*(?:间距|gap)\s*[:：=为]?\s*'
             r'(\d+(?:\.\d+)?)', 'brim_object_gap')
        grab(r'(?:熨烫|ironing)\s*(?:流量|flow)\s*[:：=为]?\s*'
             r'(\d+(?:\.\d+)?)', 'ironing_flow')

        # 裙边类型：无
        if (re.search(r'(?:brim|裙边|防翘边)\s*(?:类型|type)?\s*[:：=为]?\s*'
                      r'(?:无|none|off|no|0)\b', wt, re.I)
                or re.search(r'(?:不要|不用|关闭|去掉)\s*'
                             r'(?:brim|裙边|防翘边)', wt, re.I)):
            ov['brim_type'] = 'no_brim'
        # 熨烫：先关，再全部，最后开/默认开（只提到熨烫就算开）
        if (re.search(r'(?:不要|不用|不需要|去掉|去除|关闭)\s*(?:熨烫|ironing)',
                      wt, re.I)
                or re.search(r'(?:熨烫|ironing)\s*(?:关|no|off|0|无)\b',
                             wt, re.I)):
            ov['ironing_type'] = 'no ironing'
        elif re.search(r'(?:熨烫|ironing)\s*(?:类型|type)?\s*[:：=为]?\s*'
                       r'(?:全部|所有|all)\b', wt, re.I):
            ov['ironing_type'] = 'all top'
        elif (re.search(r'(?:熨烫|ironing)\s*'
                        r'(?:开|yes|on|顶面|top|topmost)\b', wt, re.I)
              or re.search(r'熨烫|ironing', wt, re.I)):
            ov['ironing_type'] = 'topmost'
        # 接缝位置
        sm = re.search(r'(?:接缝|seam)\s*(?:位置|position)?\s*[:：=为]?\s*'
                       r'([\u4e00-\u9fff a-z]+)', wt, re.I)
        if sm:
            sv = sm.group(1).strip().lower()
            for cn, val in (('对齐', 'aligned'), ('最近', 'nearest'),
                            ('随机', 'random'), ('背面', 'back')):
                if cn in sv:
                    ov['seam_position'] = val
                    break
        # 打印顺序
        if (re.search(r'(?:按|以)?\s*(?:物体|对象|零件|object)\s*'
                      r'(?:为序|优先|顺序|打印)', wt, re.I)
                or 'by object' in wt.lower()):
            ov['print_sequence'] = 'by object'
        elif re.search(r'(?:逐层|按层|by\s*layer)', wt, re.I):
            ov['print_sequence'] = 'by layer'
        # 直接 key=value（专家原样粘贴）
        for m in re.finditer(
                r'([a-z_][a-z0-9_]{1,40})\s*=\s*([^;\s,，。][^;,，。]{0,50})',
                raw or '', re.I):
            k = m.group(1).lower()
            v = m.group(2).strip()
            if k in self.EXTRA_CN:
                ov[k] = v
        return ov

    def parse_requirements(self, text):
        """把自然语言参数需求解析成覆盖项；返回 {} 表示全部用默认。"""
        raw = (text or '').strip()
        t = self._norm_voice(raw) if (raw and raw != self._ph) else ''
        if not t:
            return self._apply_personal({}, '')
        ov = {}
        # 直通语法：任意 Bambu 参数键都能写 key=value，三层通吃
        # （layer_height / nozzle_temperature / printer_structure …）。
        # 键名是下划线英文，不会和下面的中文规则撞；先摘出来再从文本删掉。
        # 注意：必须从**原文** raw 里摘，不能从归一化后的 t——
        # _norm_voice 会把 "=" 抹掉（nozzle_temperature=225 → 两段）
        _pairs = re.findall(
            r'([a-z][a-z0-9_]{2,})\s*=\s*([^;；,，、\s]+)', raw)
        if _pairs:
            ov['_raw'] = [f'{k}={v}' for k, v in _pairs]
            for _k, _v in _pairs:          # 从中文解析文本里清掉这对
                t = re.sub(r'\b' + re.escape(_k) + r'\b\s*\S*', ' ', t)
        m = re.search(r'层高\s*(?:调到|调成|调低到|调高到|降到|降成|'
                      r'升到|升成|改成|改为|设为|设成|设置成|调整到|'
                      r'弄成|搞成|用|是|为)?\s*(\d+(?:\.\d+)?)', t)
        if not m:
            m = re.search(r'(\d+(?:\.\d+)?)\s*层高', t)
        if m:
            ov['layer_height'] = m.group(1)
        m = re.search(r'(\d{1,3})\s*%', t)
        if m:
            v = int(m.group(1))
            if 0 <= v <= 100:
                ov['infill'] = str(v)
        elif re.search(r'填充', t):
            # 允许多一个"密度/率"：语音归一化会把"填充50%"改写成
            # "填充密度50"（共享模块 voice_norm 的规则），这里要认
            m = re.search(r'填充(?:密度|率)?\s*(\d{1,3})', t)
            if m:
                ov['infill'] = str(int(m.group(1)))
        for cn, key in self.PATTERN_CN.items():
            if cn in t:
                ov['pattern'] = key
                break
        for cn, key in self.SUPPORT_CN.items():
            if cn in t:
                ov['support'] = key
                break
        if '支撑' in t and 'support' not in ov:
            ov['support'] = 'tree_plate'
        if ov.get('support') and ('整机' in t or '全部' in t or '全模型' in t):
            ov['support'] = 'tree_all' if ov['support'] == 'tree_plate' \
                else 'normal_all'
        for cn, key in self.BED_CN.items():
            if cn in t:
                ov['bed'] = key
                break
        if ('不' in t or '关' in t) and '定向' in t:
            ov['orient'] = False
        # 克隆：一个零件打多份
        m = re.search(r'(?:打|复制|要|切|切出)\s*(\d{1,3})\s*个', t)
        if not m:
            m = re.search(r'克隆\s*(\d{1,3})\s*个?', t)
        if not m:
            m = re.search(r'x\s*(\d{1,3})\s*个?', t)
        if m:
            n = int(m.group(1))
            if 2 <= n <= 100:
                ov['clone'] = n
        # 打印机型号：h2s / x1c / a1 mini / p1s 等
        norm = re.sub(r'\s+', '', t.lower())
        for d in sorted(getattr(self, 'machine_display', []),
                        key=len, reverse=True):
            key = re.sub(r'\s+', '', d.lower())
            if re.search(r'(?<![a-z])' + re.escape(key)
                         + r'(?![a-z0-9])', norm):
                ov['machine'] = d
                break
        if 'machine' not in ov:
            for k, v in (('h2s', 'H2S'), ('p1s', 'P1S'),
                         ('x1c', 'X1 Carbon'), ('a1m', 'A1 mini'),
                         ('h2dp', 'H2D Pro'), ('p1p', 'P1P'),
                         ('p2s', 'P2S'), ('x2d', 'X2D'), ('x1e', 'X1E')):
                if re.search(r'(?<![a-z])' + re.escape(k)
                             + r'(?![a-z0-9])', norm):
                    ov['machine'] = v
                    break
        # 耗材/材料：材料PETG、用ABS、换TPU、尼龙、碳纤维等
        mat = self._parse_material(t, ov.get('machine'))
        if mat:
            if self._filament_edit_locked():
                ov['_filament_locked'] = True
            else:
                ov['filament'] = mat[0]
                ov['_mat_family'] = mat[1]
                if mat[2]:
                    ov['_mat_fuzzy'] = True
        # 最省空间：提到“紧凑/紧致/极限/最省空间/密排”就开，明确说不就关
        tl = t.lower()
        if re.search(r'不\s*紧凑|不\s*紧致|不要紧凑|普通拼盘|普通摆盘|宽松|保守', t):
            ov['tight'] = False
        elif re.search(r'紧凑|紧致|极限|最省空间|省空间|密排|塞盘|tight', tl):
            ov['tight'] = True
        # 摆盘：提到“多个模型放一盘/一起打印”等就开，明确说不就关
        if re.search(r'不拼盘|不摆盘|分开打印|单独打印|一文件一盘|各打各|'
                     r'独立打印|不\s*一起打|分开打|分开切|不要拼|'
                     r'别拼|单独打|单独切|各打各的|不一起|不同盘|'
                     r'别放一起', t):
            ov['pack'] = False
        elif re.search(r'拼盘|摆盘|一盘|同一个盘|一个盘|同盘|一板|合盘|'
                       r'拼一板|一起打印|多模型一盘|同一块板|一块板|'
                       r'打印到同|放到同|放一起|拼在一起|拼一起|'
                       r'一个盘里|放一盘|一起打|放到一起|放一块|'
                       r'拼一块|共一盘|同一个盘里|同板|同一板|一起', t):
            ov['pack'] = True
        # 最少支撑：固定方向下少调参数是一回事，这里指的是自动换方向
        if re.search(r'不\s*省支撑|不要省支撑|正常支撑|普通支撑|'
                     r'不用省支撑|别省支撑|不\s*最少支撑|'
                     r'不要最少支撑|不用最少支撑', t):
            ov['min_support'] = False
        elif re.search(r'省支撑|支撑最少|最少支撑|支撑最省|'
                       r'少用.{0,3}支撑|少支撑|支撑瘦身', t):
            ov['min_support'] = True
        ov.update(self._parse_extra(t, raw))
        if self._filament_edit_locked():
            blocked = []
            for key in list(ov):
                if key == 'filament' or str(key).startswith('filament_'):
                    blocked.append(key)
                    ov.pop(key, None)
            kept_raw = []
            for item in (ov.get('_raw') or []):
                key = str(item).split('=', 1)[0].strip().lower()
                if key == 'filament' or key.startswith('filament_'):
                    blocked.append(key)
                else:
                    kept_raw.append(item)
            if '_raw' in ov:
                ov['_raw'] = kept_raw
            ov.pop('_mat_family', None)
            ov.pop('_mat_fuzzy', None)
            if blocked:
                ov['_filament_locked'] = True
        ov = self._apply_personal(ov, t)
        return ov

    def _user_rules_path(self):
        profile = str(self.cfg.get('profile') or 'default')
        return os.path.join(DATA_DIR, f'user_rules_{profile}.json')

    def _user_rules(self):
        if getattr(self, '_user_rules_cache', None) is None:
            try:
                with open(self._user_rules_path(), encoding='utf-8') as f:
                    self._user_rules_cache = json.load(f)
            except (OSError, ValueError):
                self._user_rules_cache = {}
            base = {'samples': [], 'phrase_rules': [], 'defaults': {}}
            base.update(self._user_rules_cache)
            self._user_rules_cache = base
        return self._user_rules_cache

    def _save_user_rules(self):
        try:
            with open(self._user_rules_path(), 'w', encoding='utf-8') as f:
                json.dump(self._user_rules_cache, f, ensure_ascii=False,
                          indent=1)
        except OSError:
            pass

    def _apply_personal(self, ov, norm):
        """把个人短语规则 / 习惯默认补进解析结果（只补缺，显式输入优先）。"""
        rules = self._user_rules()
        personal = set()
        for r in rules.get('phrase_rules', []):
            if (r.get('enabled', True) and r.get('norm')
                    and r['norm'] in norm):
                for k, v in r.get('overrides', {}).items():
                    if k not in ov:
                        ov[k] = v
                        personal.add(k)
        for k, v in rules.get('defaults', {}).items():
            if k not in ov:
                ov[k] = v
                personal.add(k)
        if personal:
            ov['_personal'] = sorted(personal)
        return ov

    def _learning_stats(self):
        r = self._user_rules()
        d = r.get('defaults', {})
        ds = ' · '.join(f'{k}={v}' for k, v in d.items()) or '无'
        return (f'{len(r.get("phrase_rules", []))} 条短语规则 / '
                f'{len(r.get("samples", []))} 条认可样本 · 习惯默认：{ds}')

    def _set_rule_enabled(self, norm, enabled):
        for r in self._user_rules().get('phrase_rules', []):
            if r.get('norm') == norm:
                r['enabled'] = bool(enabled)
        self._save_user_rules()

    def _remove_rule(self, norm):
        rules = self._user_rules()
        rules['phrase_rules'] = [r for r in rules.get('phrase_rules', [])
                                 if r.get('norm') != norm]
        self._save_user_rules()

    def _remove_default(self, key):
        self._user_rules().get('defaults', {}).pop(key, None)
        self._save_user_rules()

    @staticmethod
    def _ord_num(s):
        """第几个：'3'→3、'三'→3、'二'→2；识别不了返回 None。"""
        s = (s or '').strip()
        if not s:
            return None
        if s.isdigit():
            return int(s)
        try:
            v = _cn_num(s)
        except Exception:
            return None
        return v if isinstance(v, int) and v > 0 else None

    def _parse_per_file(self, models, text):
        """一句话给多个文件分配不同参数。

        支持两种引用：文件名（如“i6完成版001用PETG”）和序号
        （第1个/模型2/三号…）。每个引用后面的内容归它所有，
        引用之前的内容是全局默认（其他文件也用）。
        返回 (全局覆盖, {文件序号: 覆盖})。
        """
        raw = (text or '').strip()
        if not raw or raw == self._ph:
            return {}, {}
        t = self._norm_voice(raw)
        if not t:
            return {}, {}
        # 文件名引用（长名优先，去掉扩展名）
        name_refs = []
        for i, m in enumerate(models):
            base = os.path.splitext(os.path.basename(m))[0]
            if base:
                name_refs.append((i, base))
        name_refs.sort(key=lambda x: -len(x[1]))
        tl = t.lower()
        refs = []          # (起始, 结束, 文件序号)
        used = set()
        for i, base in name_refs:
            if i in used:
                continue
            idx = tl.find(base.lower())
            if idx >= 0:
                refs.append((idx, idx + len(base), i))
                used.add(i)
        # 序号引用：第N个/模型N/文件N/N号
        ord_pat = re.compile(
            r'第\s*([一二两三四五六七八九十\d]+)\s*(?:个|号|份)?\s*'
            r'(?:模型|文件)?|'
            r'(?:模型|文件)\s*([一二两三四五六七八九十\d]+)|'
            r'([一二两三四五六七八九十\d]+)\s*号(?:\s*(?:模型|文件)?)')
        for m in ord_pat.finditer(t):
            ntxt = m.group(1) or m.group(2) or m.group(3) or ''
            n = self._ord_num(ntxt)
            if n is None:
                continue
            idx = n - 1
            if 0 <= idx < len(models) and idx not in used:
                refs.append((m.start(), m.end(), idx))
                used.add(idx)
        if not refs:
            return self.parse_requirements(text), {}
        refs.sort(key=lambda x: x[0])
        base_ov = self.parse_requirements(t[:refs[0][0]])
        per_file = {}
        for k, (s, e, fi) in enumerate(refs):
            seg_end = refs[k + 1][0] if k + 1 < len(refs) else len(t)
            seg = t[e:seg_end]
            per_file[fi] = self.parse_requirements(seg) if seg.strip() else {}
        return base_ov, per_file

    def _overrides_str(self, ov):
        r = dict(RECIPE)
        r.update({k: v for k, v in ov.items() if k in r})
        file_based = bool(
            ov.get('_preserve_project') or self._preserve_3mf_project()
        )
        support_type, plate_only = {
            'tree_plate': ('tree(auto)', 1),
            'tree_all': ('tree(auto)', 0),
            'normal_plate': ('normal(auto)', 1),
            'normal_all': ('normal(auto)', 0),
            'none': (None, None),
        }[r['support']]
        overrides = []
        if not file_based or 'layer_height' in ov:
            overrides.append(f'layer_height={r["layer_height"]}')
        if not file_based or 'infill' in ov:
            overrides.append(f'sparse_infill_density={r["infill"]}%')
        if not file_based or 'pattern' in ov:
            overrides.append(f'sparse_infill_pattern={r["pattern"]}')
        if not file_based or 'support' in ov:
            if support_type:
                overrides += [
                    'enable_support=1',
                    f'support_type={support_type}',
                    f'support_on_build_plate_only={plate_only}',
                ]
            else:
                overrides += ['enable_support=0']
        for k in ('wall_loops', 'inner_wall_speed', 'outer_wall_speed',
                  'sparse_infill_speed', 'internal_solid_infill_speed',
                  'top_surface_speed', 'initial_layer_speed', 'ironing_type',
                  'ironing_speed', 'ironing_flow', 'brim_type', 'brim_width',
                  'brim_object_gap', 'skirt_loops', 'raft_layers',
                  'top_shell_layers', 'bottom_shell_layers', 'seam_position',
                  'print_sequence'):
            if k in ov:
                overrides.append(f'{k}={ov[k]}')
        # 直通项放最后：同名时用户手写的值覆盖上面的推导值
        overrides += list(ov.get('_raw') or [])
        # 工具箱是用户刚刚显式勾选的，放在最后确保真正进入这次切片。
        overrides += self._toolbox_override_pairs()
        return ';'.join(overrides)

    @staticmethod
    def _extra_display(ov):
        out = []
        for k in ('wall_loops', 'inner_wall_speed', 'outer_wall_speed',
                  'top_shell_layers', 'bottom_shell_layers', 'brim_width',
                  'brim_type', 'skirt_loops', 'raft_layers', 'ironing_type',
                  'seam_position', 'print_sequence'):
            if k not in ov:
                continue
            v = ov[k]
            vm = SliceApp.EXTRA_VAL_CN.get(k, {})
            vs = vm.get(v, str(v))
            if k == 'brim_type' and v == 'auto_brim':
                continue
            out.append(f"{SliceApp.EXTRA_CN.get(k, k)}{vs}")
        return out

    def _build_cmd(self, model, out, ov, layout_only=False):
        r = dict(RECIPE)
        r.update({k: v for k, v in ov.items() if k in r})
        bed = ov.get('bed') or self.cfg.get('bed', 'Textured PEI Plate')
        if FROZEN:
            # 打包后没有外部 python：以“内部切片”模式重跑自己
            cmd = [sys.executable, '--slice-job', model, '--out', out]
        else:
            cmd = [PY_EXE, os.path.join(CLI_DIR, 'slice_bambu.py'), model,
                   '--out', out]
        if layout_only:
            cmd += ['--layout-only', '1']
        cmd += ['--process-override', self._overrides_str(ov), '--bed-type', bed]
        if (hasattr(self, 'var_tool_hide_z')
                and self.var_tool_hide_z.get()):
            cmd += ['--adaptive-scarf', '1']
        if self._figurine_mode_on():
            cmd += ['--figurine-mode', '1']
        preserve_project = bool(
            (ov.get('_preserve_project') or self._preserve_3mf_project())
            and str(model).lower().endswith('.3mf')
        )
        if preserve_project:
            # 用户已经在 3MF 里排好朝向/位置时，默认只沿用，不再选底面。
            # 手办的绒毛外表面一旦被翻到支撑侧，拆支撑会直接毁表面。
            cmd += ['--preserve-project', '1', '--arrange', '0', '--orient', '0']
            cmd += ['--part-face-orient',
                    '0' if (not r['orient'] or ov.get('orient') is False)
                    else '1']
        for flag, key in (('--machine', 'machine'), ('--process', 'process'),
                          ('--filament', 'filament')):
            if key == 'filament' and self._filament_edit_locked([model]):
                continue
            v = str(self.cfg.get(key, '')).strip()
            if key == 'filament' and ov.get('filament'):
                v = ov['filament']
            if v:
                cmd += [flag, v]
        if not r['orient'] or ov.get('orient') is False:
            cmd += ['--orient', '0']
        if not preserve_project:
            cmd += ['--arrange', '1' if r['arrange'] else '0']
        if (self._effective_min_support()
                and r.get('support') != 'none'):
            cmd += ['--min-support', '2']
        if ov.get('clone', 1) > 1:
            cmd += ['--clone', str(ov['clone'])]
            cmd += ['--tight', '1' if self._effective_tight() else '0']
        return cmd

    def _build_batch_cmd(self, folder, out_dir, pack_on, layout_only=False,
                         layout_out=None):
        head = ([sys.executable, '--slice-job'] if FROZEN
                else [PY_EXE, os.path.join(CLI_DIR, 'slice_bambu.py')])
        cmd = head + ['--batch', folder, '--out-dir', out_dir,
                      '--pack',
                      '0' if layout_only else ('1' if pack_on else '0'),
                      '--tight',
                      '0' if layout_only else
                      ('1' if self._effective_tight() else '0'),
                      '--min-support',
                      ('0' if layout_only else
                       '2' if (self._effective_min_support()
                               and (self.overrides.get('support')
                                    or RECIPE['support']) != 'none')
                       else '0'),
                      '--process-override', self._overrides_str(self.overrides),
                      '--bed-type',
                      self.cfg.get('bed', 'Textured PEI Plate')]
        if layout_only:
            cmd += ['--layout-only', '1']
            if layout_out:
                cmd += ['--out', layout_out]
        if (hasattr(self, 'var_tool_hide_z')
                and self.var_tool_hide_z.get()):
            cmd += ['--adaptive-scarf', '1']
        if self._figurine_mode_on():
            cmd += ['--figurine-mode', '1']
        face_on = bool(RECIPE['orient']
                       and self.overrides.get('orient') is not False)
        figurine_3mf = (
            self._figurine_mode_on()
            and len(getattr(self, 'models', [])) == 1
            and str(self.models[0]).lower().endswith('.3mf'))
        if self._preserve_3mf_project() or figurine_3mf:
            # orient=0 只用于整盘保留；拆成零件后交给 Bambu 逐件自动朝向。
            cmd += ['--preserve-project', '1', '--orient', '0',
                    '--part-face-orient',
                    '1' if face_on else '0']
        elif not face_on:
            cmd += ['--orient', '0', '--part-face-orient', '0']
        for flag, key in (('--machine', 'machine'), ('--process', 'process'),
                          ('--filament', 'filament')):
            if key == 'filament' and self._filament_edit_locked():
                continue
            v = str(self.cfg.get(key, '')).strip()
            if key == 'filament' and self.overrides.get('filament'):
                v = self.overrides['filament']
            if v:
                cmd += [flag, v]
        return cmd

    def _preserve_3mf_project(self):
        """单个 3MF 且用户没显式改打印参数时，沿用文件内嵌项目参数。"""
        if (len(getattr(self, 'models', [])) != 1
                or not str(self.models[0]).lower().endswith('.3mf')):
            return False
        if self.overrides.get('_preserve_project'):
            return True
        if self._filament_edit_locked():
            # 多色/多材料工程的配色和耗材绑定必须整项目沿用，不能因为
            # 其它参数变化退回拆 STL 的普通路径。
            return True
        explicit = {
            'layer_height', 'infill', 'pattern', 'support', 'filament',
            'wall_loops', 'inner_wall_speed', 'outer_wall_speed',
            'sparse_infill_speed', 'internal_solid_infill_speed',
            'top_surface_speed', 'initial_layer_speed', 'ironing_type',
            'ironing_speed', 'ironing_flow', 'brim_type', 'brim_width',
            'brim_object_gap', 'skirt_loops', 'raft_layers',
            'top_shell_layers', 'bottom_shell_layers', 'seam_position',
            'print_sequence',
        }
        if any(k in self.overrides for k in explicit):
            return False
        for raw in (self.overrides.get('_raw') or []):
            key = str(raw).split('=', 1)[0].strip()
            if key in explicit:
                return False
        return True

    def _profiles_root(self):
        cached = getattr(self, '_profiles_root_cache', None)
        if cached and os.path.isdir(os.path.join(cached, 'machine')):
            return cached
        # 用和切片 CLI 完全相同的发现逻辑：环境变量 → 运行中的 Bambu
        # → 常见盘符。以前这里只写死 D:\ 和 C:\Program Files，装在
        # 用户目录/E 盘/F 盘时就会静默退回只有一个 P1S。
        try:
            if CLI_DIR not in sys.path:
                sys.path.insert(0, CLI_DIR)
            import slice_bambu
            p = slice_bambu.find_profiles_root()
            if p and os.path.isdir(os.path.join(p, 'machine')):
                self._profiles_root_cache = p
                return p
        except Exception:
            pass
        for exe in (r'D:\Bambu Studio\bambu-studio.exe',
                    r'C:\Program Files\Bambu Studio\bambu-studio.exe',
                    r'C:\Program Files (x86)\Bambu Studio\bambu-studio.exe',
                    os.path.join(os.environ.get('LOCALAPPDATA', ''),
                                 'Programs', 'Bambu Studio',
                                 'bambu-studio.exe')):
            if os.path.isfile(exe):
                p = os.path.join(os.path.dirname(exe), 'resources',
                                 'profiles', 'BBL')
                if os.path.isdir(p):
                    self._profiles_root_cache = p
                    return p
        return ''

    def _load_machines(self):
        """返回机型类型（去喷嘴版本），如 ['Bambu Lab A1', 'Bambu Lab P1S']。"""
        d = os.path.join(self._profiles_root(), 'machine')
        types = []
        seen = set()
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if not f.endswith('.json'):
                    continue
                b = f[:-5]
                if 'template' in b or b.startswith('fdm_'):
                    continue
                t = re.sub(r'\s+0\.[0-9]\s*nozzle$', '', b)
                if t not in seen:
                    seen.add(t)
                    types.append(t)
        cur = self.cfg.get('machine')
        if cur:
            t = re.sub(r'\s+0\.[0-9]\s*nozzle$', '', cur)
            if t not in seen:
                types.insert(0, t)
        if not types:
            types = ['Bambu Lab P1S']
        return types

    def _machine_display_name(self, machine):
        if not machine:
            return None
        return re.sub(r'\s+0\.[0-9]\s*nozzle$', '',
                      machine.replace('Bambu Lab ', ''))

    def _resolve_machine(self, display):
        t = 'Bambu Lab ' + display
        d = os.path.join(self._profiles_root(), 'machine')
        for cand in (t + ' 0.4 nozzle', t):
            if os.path.isfile(os.path.join(d, cand + '.json')):
                return cand
        return t

    def _machine_code(self, machine):
        base = machine.replace('Bambu Lab ', '').lower().replace(' ', '')
        base = re.sub(r'0\.[0-9]nozzle$', '', base)
        return {
            'a1': 'A1', 'a1mini': 'A1M', 'a2l': 'A2L',
            'h2c': 'H2C', 'h2d': 'H2D', 'h2dpro': 'H2DP',
            'h2s': 'H2S', 'p1p': 'P1P', 'p1s': 'X1C',
            'p2s': 'P2S', 'x1': 'X1C', 'x1carbon': 'X1C',
            'x1e': 'X1C', 'x2d': 'X2D',
        }.get(base)

    def _parse_material(self, text, machine=None):
        """识别耗材，返回 (预设名, 材料族, 是否模糊) 或 None。

        **认材料这一步交给共享模块 materials.identify()**（挂件用的是同一个
        函数，两边判断才会一致）；这里只负责把材料族翻成具体的耗材预设名。
        """
        got = materials.identify(text)
        if not got:
            return None
        fam, fuzzy = got['family'], got['fuzzy']

        root = os.path.join(self._profiles_root(), 'filament')
        if not os.path.isdir(root):
            return None
        names = [f[:-5] for f in os.listdir(root)
                 if f.endswith('.json') and ' @' in f
                 and not f.startswith(('fdm_', 'support_'))
                 and 'support' not in f.lower()]
        if not names:
            return None

        target = machine or self.cfg.get('machine', '')
        toks = set()
        disp = re.sub(r'\s+0\.[0-9]\s*nozzle$', '',
                      str(target).replace('Bambu Lab ', '').strip())
        if disp:
            toks.add(disp.lower())
        code = self._machine_code(target)
        if code:
            toks.add(code.lower())
        if not toks:
            toks.add('p1s')

        PLA_VARIANTS = ('silk', 'marble', 'glow', 'wood', 'metal',
                        'matte', 'translucent', 'galaxy', 'sparkle',
                        'aero', 'dynamic', 'lite', 'pure', 'tough',
                        'high speed')

        def fam_ok(n):
            ln = n.lower()
            if fam == 'pla':
                return bool(re.search(r'\bpla(?: |@)', ln)) \
                    and '-cf' not in ln and '-gf' not in ln \
                    and not any(v in ln for v in PLA_VARIANTS)
            if fam == 'pla-cf':
                return 'pla-cf' in ln
            if fam == 'petg':
                return bool(re.search(r'\bpetg(?: |@)', ln)) \
                    and '-cf' not in ln and 'translucent' not in ln
            if fam == 'petg-cf':
                return 'petg-cf' in ln
            if fam == 'abs':
                return bool(re.search(r'\babs(?: |@)', ln)) \
                    and '-gf' not in ln
            if fam == 'abs-gf':
                return 'abs-gf' in ln
            if fam == 'tpu':
                return bool(re.search(r'\btpu(?: |@)', ln)) \
                    and 'for ams' not in ln
            if fam.startswith('pla-'):
                return fam[4:] in ln and 'pla' in ln
            return False

        cands = [n for n in names if fam_ok(n)]
        if not cands:
            return None

        def machine_score(n):
            for tok in toks:
                if re.search(r'@BBL\s+' + re.escape(tok) + r'(?:\s|$)',
                             n, re.I):
                    return 1
            return 0

        nz = None
        mz = re.search(r'\s(0\.[0-9])\s*nozzle', str(target))
        if mz:
            nz = ' ' + mz.group(1) + ' nozzle'

        def rank(n):
            v = 0
            if re.search(r'\b95a\b', n, re.I):
                v = 3
            elif re.search(r'\b90a\b', n, re.I):
                v = 2
            elif re.search(r'\b85a\b', n, re.I):
                v = 1
            elif re.search(r'\bbasic\b', n, re.I):
                v = 2
            return (machine_score(n),
                    1 if n.startswith('Bambu ') else 0,
                    1 if (nz and nz in n) else 0,
                    v, -len(n))

        cands.sort(key=rank, reverse=True)
        if not machine_score(cands[0]):
            return None  # 该机型没有对应耗材预设，不擅自换机型
        return cands[0], fam, fuzzy

def run_slice_job():
    args = [item for item in sys.argv[1:] if item != "--slice-job"]
    sys.argv = ["slice_bambu.py"] + args
    if CLI_DIR not in sys.path:
        sys.path.insert(0, CLI_DIR)
    import slice_bambu
    slice_bambu.main()
