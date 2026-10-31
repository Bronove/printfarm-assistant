# -*- coding: utf-8 -*-
"""从 Bambu G-code 提取“含支撑的真实挤出占用矩形”。

树状支撑会超出模型包围盒向外生长，摆盘时若按模型尺寸算必然撞车。
这里扫描 G-code 里所有挤出指令（E 增加的 G1），得到该盘的真实占地。
"""

import re

_G = re.compile(r'^G[01]\s+(.*)$')
_COORD = re.compile(r'\b([XYZ])\s*(-?[\d.]+)')
_E = re.compile(r'\bE\s*(-?[\d.]+)')


def _extrude_bbox(gcode_text, min_layer):
    cur_x = cur_y = None
    prev_e = None
    x0 = y0 = x1 = y1 = None
    layer = 0
    for raw in gcode_text.splitlines():
        s = raw.strip()
        if s.startswith(';LAYER_CHANGE') or s.startswith('; layer '):
            layer += 1
            continue
        m = _G.match(s)
        if not m:
            continue
        if layer < min_layer:
            # 跳过起始校准挤出（prime line），它不属于模型/支撑
            em0 = _E.search(m.group(1))
            if em0 is not None:
                prev_e = float(em0.group(1))
            continue
        em = _E.search(m.group(1))
        if em is None:
            continue
        e = float(em.group(1))
        coords = {k: float(v) for k, v in _COORD.findall(m.group(1))}
        if 'X' in coords:
            cur_x = coords['X']
        if 'Y' in coords:
            cur_y = coords['Y']
        if prev_e is None:
            prev_e = e
            if cur_x is not None and cur_y is not None:
                x0 = x1 = cur_x
                y0 = y1 = cur_y
            continue
        if e > prev_e + 1e-6 and cur_x is not None and cur_y is not None:
            if x0 is None or cur_x < x0:
                x0 = cur_x
            if y0 is None or cur_y < y0:
                y0 = cur_y
            if x1 is None or cur_x > x1:
                x1 = cur_x
            if y1 is None or cur_y > y1:
                y1 = cur_y
        prev_e = e
    if x0 is None:
        return None
    return (x0, y0, x1, y1)


def extrude_bbox(gcode_text):
    """返回含模型+支撑的挤出矩形 (x0,y0,x1,y1)。

    优先统计第 1 层及以后的挤出（跳过开头 prime line）；若 G-code
    没有分层标记，则回退为统计全部挤出。
    """
    b = _extrude_bbox(gcode_text, 1)
    if b is not None:
        return b
    return _extrude_bbox(gcode_text, 0)
