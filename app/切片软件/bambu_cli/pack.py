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
                   reserved=None, center=False):
    """紧凑模式：Bottom-Left 装箱 + 允许 90° 旋转。

    rects: [(w, h)] 为模型本体尺寸（不含间距）。返回
    [{ 'items': [(index, x, y, rot)], 'fill': float, 'oversize': bool }]
    rot=1 表示该件在盘面上转了 90°（宽高对调）。
    reserved: 每盘固定占用的矩形 [(x, y, w, h)]，例如擦料塔安全区。
    center: 最终交付布局设为 True，把该盘全部模型作为整体居中；
            置 False 时保留 Bottom-Left 坐标，供容量估算使用。
    """
    if isinstance(plate, (tuple, list)):
        plate_w, plate_h = float(plate[0]), float(plate[1])
    else:
        plate_w = plate_h = float(plate)
    eff = [(w + gap, h + gap) for w, h in rects]
    order = sorted(range(len(rects)), key=lambda i: -(eff[i][0] * eff[i][1]))
    plates = []
    # 固定区（禁入区/擦料塔）也把 gap 扩进去。否则物件可以从固定区
    # 右侧或上侧“贴着”放，虽然不重叠，却会丢掉要求的净距。
    fixed = [
        (
            float(rect[0]) - float(gap),
            float(rect[1]) - float(gap),
            float(rect[2]) + 2.0 * float(gap),
            float(rect[3]) + 2.0 * float(gap),
        )
        for rect in (reserved or [])
    ]

    def new_plate():
        return {
            'items': [], '_blf': list(fixed),
            '_fixed': list(fixed), 'fill': 0.0,
        }

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
            pl.pop('_fixed', None)
            continue
        if center and pl['items']:
            actual = []
            for index, x, y, rotation in pl['items']:
                width, depth = rects[index]
                if rotation:
                    width, depth = depth, width
                actual.append((x, y, x + width, y + depth))
            used_width = (
                max(row[2] for row in actual)
                - min(row[0] for row in actual)
            )
            used_depth = (
                max(row[3] for row in actual)
                - min(row[1] for row in actual)
            )
            shift_x = (
                (plate_w - used_width) / 2.0
                - min(row[0] for row in actual)
            )
            shift_y = (
                (plate_h - used_depth) / 2.0
                - min(row[1] for row in actual)
            )
            if abs(shift_x) > 1e-9 or abs(shift_y) > 1e-9:
                moved = []
                for index, x, y, rotation in pl['items']:
                    width, depth = rects[index]
                    if rotation:
                        width, depth = depth, width
                    moved.append((
                        x + shift_x, y + shift_y,
                        width + gap, depth + gap,
                    ))
                fixed = pl.get('_fixed') or []
                if not any(
                        overlaps(fixed, x, y, width, depth)
                        for x, y, width, depth in moved):
                    pl['items'] = [
                        (index, x + shift_x, y + shift_y, rotation)
                        for index, x, y, rotation in pl['items']
                    ]
        pl.pop('_fixed', None)
        used = sum((rects[i][0] + gap) * (rects[i][1] + gap)
                   for i, _, _, _ in pl['items'])
        pl['fill'] = used / (plate_w * plate_h)
        pl['items'].sort(key=lambda it: (it[1], it[2]))
    return plates


def _polygon_bbox(poly):
    xs = [float(point[0]) for point in poly]
    ys = [float(point[1]) for point in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _rotate_polygon(poly, width, depth, rotation):
    """把已归一化的凸多边形绕 Z 转 90°，并重新贴到 (0, 0)。"""
    if not rotation:
        return [(float(x), float(y)) for x, y in poly]
    # (x, y) -> (depth - y, x)，旋转后包围盒为 depth × width。
    return [(depth - float(y), float(x)) for x, y in poly]


def _segment_distance(a, b, c, d):
    """两条二维线段的最短距离。"""
    def point_segment(p, q, r):
        qx, qy = q
        rx, ry = r[0] - qx, r[1] - qy
        denom = rx * rx + ry * ry
        if denom <= 1e-18:
            return ((p[0] - qx) ** 2 + (p[1] - qy) ** 2) ** 0.5
        t = ((p[0] - qx) * rx + (p[1] - qy) * ry) / denom
        t = max(0.0, min(1.0, t))
        x, y = qx + t * rx, qy + t * ry
        return ((p[0] - x) ** 2 + (p[1] - y) ** 2) ** 0.5

    def orient(p, q, r):
        return ((q[0] - p[0]) * (r[1] - p[1])
                - (q[1] - p[1]) * (r[0] - p[0]))

    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    if ((o1 == 0.0 or o2 == 0.0 or o1 * o2 < 0.0)
            and (o3 == 0.0 or o4 == 0.0 or o3 * o4 < 0.0)):
        return 0.0
    return min(
        point_segment(a, c, d), point_segment(b, c, d),
        point_segment(c, a, b), point_segment(d, a, b),
    )


def _point_in_convex(point, polygon):
    sign = 0
    for index in range(len(polygon)):
        a = polygon[index]
        b = polygon[(index + 1) % len(polygon)]
        cross = ((b[0] - a[0]) * (point[1] - a[1])
                 - (b[1] - a[1]) * (point[0] - a[0]))
        if abs(cross) <= 1e-9:
            continue
        current = 1 if cross > 0 else -1
        if sign and current != sign:
            return False
        sign = current
    return True


def _clear_of(first, second, gap):
    """凸多边形之间至少留 gap；快速排除相距很远的包围盒。"""
    ax0, ay0, ax1, ay1 = _polygon_bbox(first)
    bx0, by0, bx1, by1 = _polygon_bbox(second)
    if (ax1 + gap <= bx0 or bx1 + gap <= ax0
            or ay1 + gap <= by0 or by1 + gap <= ay0):
        return True

    # 凸多边形分离轴检测。只要存在一条投影轴的间隙达到 gap，
    # 两者实际二维距离一定不小于 gap。相比逐边穷举，复杂度从
    # O(n²) 降到 O(n)，适合同一盘几十个真实凸包。
    for polygon in (first, second):
        for index in range(len(polygon)):
            a = polygon[index]
            b = polygon[(index + 1) % len(polygon)]
            axis = (-(b[1] - a[1]), b[0] - a[0])
            length = (axis[0] ** 2 + axis[1] ** 2) ** 0.5
            if length <= 1e-12:
                continue
            axis = (axis[0] / length, axis[1] / length)
            first_projection = [
                point[0] * axis[0] + point[1] * axis[1]
                for point in first
            ]
            second_projection = [
                point[0] * axis[0] + point[1] * axis[1]
                for point in second
            ]
            separation = max(
                min(second_projection) - max(first_projection),
                min(first_projection) - max(second_projection),
            )
            if separation >= gap - 1e-7:
                return True
    return False


def pack_polygons_blf(polygons, plate=256.0, gap=4.0, rotate=True,
                      reserved=None):
    """按真实俯视凸包紧排，允许不同零件轮廓互相咬合。

    polygons 必须是已归一化到 (0, 0) 的凸多边形。
    reserved 仍接受矩形 (x, y, w, h)，用于擦料塔和机器禁入区。
    """
    if isinstance(plate, (tuple, list)):
        plate_w, plate_h = float(plate[0]), float(plate[1])
    else:
        plate_w = plate_h = float(plate)
    normalized = []
    for poly in polygons:
        points = [(float(x), float(y)) for x, y in poly]
        if len(points) < 3:
            raise ValueError('俯视轮廓至少需要三个点')
        normalized.append(points)
    gap = max(0.0, float(gap))
    fixed = []
    for x, y, width, depth in reserved or []:
        fixed.append([
            (float(x), float(y)),
            (float(x) + float(width), float(y)),
            (float(x) + float(width), float(y) + float(depth)),
            (float(x), float(y) + float(depth)),
        ])
    order = sorted(
        range(len(normalized)),
        key=lambda index: -(
            (_polygon_bbox(normalized[index])[2]
             - _polygon_bbox(normalized[index])[0])
            * (_polygon_bbox(normalized[index])[3]
               - _polygon_bbox(normalized[index])[1])
        ),
    )
    plates = []

    def new_plate():
        return {'items': [], '_placed': list(fixed), 'fill': 0.0}

    def fit(poly, placed):
        width = _polygon_bbox(poly)[2]
        depth = _polygon_bbox(poly)[3]
        if width > plate_w + 1e-7 or depth > plate_h + 1e-7:
            return None
        candidates = {(0.0, 0.0)}
        bboxes = [_polygon_bbox(item) for item in placed]
        if bboxes:
            min_x = min(row[0] for row in bboxes)
            max_x = max(row[2] for row in bboxes)
            min_y = min(row[1] for row in bboxes)
            max_y = max(row[3] for row in bboxes)
            for bx0, by0, bx1, by1 in bboxes:
                for x in (bx1, bx1 + gap, bx0 - width,
                          bx0 - width - gap):
                    candidates.add((x, by0))
                    candidates.add((x, by1 + gap))
                    candidates.add((x, min_y))
                    candidates.add((x, max_y + gap))
                for y in (by1, by1 + gap, by0 - depth,
                          by0 - depth - gap):
                    candidates.add((bx0, y))
                    candidates.add((bx1 + gap, y))
                    candidates.add((min_x, y))
                    candidates.add((max_x + gap, y))
        best = None
        for x, y in candidates:
            if x < -1e-7 or y < -1e-7:
                continue
            if x + width > plate_w + 1e-7 or y + depth > plate_h + 1e-7:
                continue
            moved = [(px + x, py + y) for px, py in poly]
            if not all(_clear_of(moved, other, gap)
                       for other in placed):
                continue
            score = (round(y, 5), round(x, 5), y + depth, x + width)
            if best is None or score < best[0]:
                best = (score, x, y, moved)
        return best

    for index in order:
        base = normalized[index]
        bx0, by0, bx1, by1 = _polygon_bbox(base)
        base_width, base_depth = bx1 - bx0, by1 - by0
        options = [(0, _rotate_polygon(base, base_width, base_depth, 0),
                    base_width, base_depth)]
        if rotate and abs(base_width - base_depth) > 1e-7:
            options.append(
                (1, _rotate_polygon(base, base_width, base_depth, 1),
                 base_depth, base_width))
        selected = None
        for plate_info in plates:
            if plate_info.get('oversize'):
                continue
            for rotation, poly, width, depth in options:
                fitted = fit(poly, plate_info['_placed'])
                if fitted is None:
                    continue
                score, x, y, moved = fitted
                value = (score, rotation)
                if selected is None or value < selected[0]:
                    selected = (value, plate_info, rotation, x, y, moved,
                                width, depth)
            if selected is not None:
                break
        if selected is None:
            plate_info = new_plate()
            plates.append(plate_info)
            for rotation, poly, width, depth in options:
                fitted = fit(poly, plate_info['_placed'])
                if fitted is None:
                    continue
                score, x, y, moved = fitted
                value = (score, rotation)
                if selected is None or value < selected[0]:
                    selected = (value, plate_info, rotation, x, y, moved,
                                width, depth)
            if selected is None:
                plate_info['oversize'] = True
                plate_info['items'] = [(index, 0.0, 0.0, 0)]
                continue
        _value, plate_info, rotation, x, y, moved, width, depth = selected
        plate_info['items'].append((index, x, y, rotation))
        plate_info['_placed'].append(moved)

    for plate_info in plates:
        plate_info.pop('_placed', None)
        if plate_info.get('oversize'):
            continue
        model_area = sum(
            abs(sum(
                normalized[index][i][0]
                * normalized[index][(i + 1) % len(normalized[index])][1]
                - normalized[index][(i + 1) % len(normalized[index])][0]
                * normalized[index][i][1]
                for i in range(len(normalized[index]))
            )) / 2.0
            for index, _x, _y, _rotation in plate_info['items']
        )
        plate_info['fill'] = model_area / (plate_w * plate_h)
        plate_info['items'].sort(key=lambda item: (item[2], item[1]))
    return plates
