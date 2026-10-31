# -*- coding: utf-8 -*-
"""支撑感知矩形装箱：把“含支撑真实占用矩形”摆进打印板。

矩形之间互不重叠并保留安全边距，因此任何模型的支撑都不可能
碰到相邻模型。shelf 算法：按面积降序，逐个放进第一个能容纳的
货架行，放不下则新开一行，行放不下则新开一板。
"""


def pack_rects(rects, plate=256.0, gap=3.0):
    """rects: [(w, h)]（已含支撑占用）。返回每板信息列表：
    [{ 'items': [(index, x, y)], 'fill': float, 'oversize': bool }]
    plate 可以是数字（正方形板）或 (w, h)（矩形板）。
    """
    if isinstance(plate, (tuple, list)):
        plate_w, plate_h = float(plate[0]), float(plate[1])
    else:
        plate_w = plate_h = float(plate)
    eff = [(w + gap, h + gap) for w, h in rects]
    order = sorted(range(len(rects)), key=lambda i: -(eff[i][0] * eff[i][1]))
    plates = []

    for i in order:
        w, h = eff[i]
        if w > plate_w or h > plate_h:
            plates.append({'items': [(i, 0.0, 0.0)], 'fill': 0.0,
                           'oversize': True})
            continue
        placed = False
        for pl in plates:
            if pl.get('oversize'):
                continue
            pos = _place(pl, w, h, plate_w, plate_h)
            if pos is not None:
                pl['items'].append((i, pos[0], pos[1]))
                placed = True
                break
        if not placed:
            pl = {'shelves': [[0.0, 0.0, 0.0]], 'items': [], 'fill': 0.0}
            plates.append(pl)
            pos = _place(pl, w, h, plate_w, plate_h)
            pl['items'].append((i, pos[0], pos[1]))

    for pl in plates:
        if pl.get('oversize'):
            continue
        used = sum(
            (rects[i][0] + gap) * (rects[i][1] + gap)
            for i, _, _ in pl['items']
        )
        pl['fill'] = used / (plate_w * plate_h)
        pl['items'].sort(key=lambda it: (it[1], it[2]))
        pl.pop('shelves', None)
    return plates


def _place(pl, w, h, plate_w, plate_h):
    """找第一个能容纳的货架行；返回 (x, y) 或 None。"""
    best = None
    for s in pl['shelves']:
        y, used, sh = s
        if used + w <= plate_w and y + h <= plate_h:
            if best is None or y < best[0]:
                best = (y, s)
    if best:
        y, s = best
        x = s[1]
        s[1] = x + w
        if s[2] < h:
            s[2] = h
        return x, y
    # 新开一行
    y = max(s[0] + s[2] for s in pl['shelves'])
    if y + h > plate_h:
        return None
    pl['shelves'].append([y, w, h])
    return 0.0, y


def pack_rects_blf(rects, plate=256.0, gap=3.0, rotate=True,
                   reserved=None):
    """紧凑模式：Bottom-Left 装箱 + 允许 90° 旋转。

    rects: [(w, h)] 为模型本体尺寸（不含间距）。返回
    [{ 'items': [(index, x, y, rot)], 'fill': float, 'oversize': bool }]
    rot=1 表示该件在盘面上转了 90°（宽高对调）。
    reserved: 每盘固定占用的矩形 [(x, y, w, h)]，例如擦料塔安全区。
    """
    if isinstance(plate, (tuple, list)):
        plate_w, plate_h = float(plate[0]), float(plate[1])
    else:
        plate_w = plate_h = float(plate)
    eff = [(w + gap, h + gap) for w, h in rects]
    order = sorted(range(len(rects)), key=lambda i: -(eff[i][0] * eff[i][1]))
    plates = []
    fixed = [tuple(float(v) for v in rect) for rect in (reserved or [])]

    def new_plate():
        return {'items': [], '_blf': list(fixed), 'fill': 0.0}

    def overlaps(placed, x, y, w, h):
        for px, py, pw, ph in placed:
            if (x < px + pw and x + w > px and y < py + ph
                    and y + h > py):
                return True
        return False

    def find_best(placed, opts):
        ys = sorted({0.0} | {py + ph for px, py, pw, ph in placed})
        xs = sorted({0.0} | {px + pw for px, py, pw, ph in placed})
        best = None
        for y in ys:
            if y > plate_h:
                break
            for x in xs:
                if x > plate_w:
                    break
                for w, h, rot in opts:
                    if x + w > plate_w + 1e-6 or y + h > plate_h + 1e-6:
                        continue
                    if not overlaps(placed, x, y, w, h):
                        score = (y, x, rot)
                        if best is None or score < best[0]:
                            best = (score, x, y, w, h, rot)
                        break
            if best:
                break
        return best

    for i in order:
        w0, h0 = rects[i]
        if w0 > plate_w or h0 > plate_h:
            plates.append({'items': [(i, 0.0, 0.0, 0)],
                           'fill': 0.0, 'oversize': True})
            continue
        opts = [(w0 + gap, h0 + gap, 0)]
        if rotate and abs(w0 - h0) > 1e-9:
            opts.append((h0 + gap, w0 + gap, 1))
        placed_pos = None
        target_plate = None
        for pl in plates:
            if pl.get('oversize'):
                continue
            placed = pl.get('_blf', [])
            best = find_best(placed, opts)
            if best:
                (_, x, y, w, h, rot) = best
                placed_pos = (i, x, y, rot)
                target_plate = pl
                pl['_blf'].append((x, y, w, h))
                pl['items'].append(placed_pos)
                break
        if placed_pos is None:
            pl = new_plate()
            plates.append(pl)
            placed = pl['_blf']
            best = find_best(placed, opts)
            if best:
                (_, x, y, w, h, rot) = best
                placed_pos = (i, x, y, rot)
                pl['_blf'].append((x, y, w, h))
                pl['items'].append(placed_pos)
            else:
                pl['oversize'] = True
                pl['items'] = [(i, 0.0, 0.0, 0)]

    for pl in plates:
        pl.pop('_blf', None)
        if pl.get('oversize'):
            continue
        used = sum((rects[i][0] + gap) * (rects[i][1] + gap)
                   for i, _, _, _ in pl['items'])
        pl['fill'] = used / (plate_w * plate_h)
        pl['items'].sort(key=lambda it: (it[1], it[2]))
    return plates
