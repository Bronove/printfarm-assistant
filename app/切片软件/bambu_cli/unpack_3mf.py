# -*- coding: utf-8 -*-
"""把多零件 .3mf 里的每个 mesh 对象拆成独立二进制 STL。

用途：拓竹助手收到“一个文件里有多个模型”的 .3mf 时，在内部先拆开，
再让每个零件独立自动选底面 / 紧凑摆盘，避免 Bambu 导出 STL 时只保留
第一个零件而丢件。
"""

import os
import json
import re
import struct
import zipfile
import io
import xml.etree.ElementTree as ET

import numpy as np

_NS = '{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}'
_PNS = '{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}'
_NON_PRINTABLE = {
    'modifier_part', 'negative_part', 'support_blocker',
    'support_enforcer', 'parameter_modifier',
}
_OBJECT_BLOCK_RE = re.compile(
    rb'<(?:[A-Za-z_][\w.-]*:)?object\b[^>]*>(.*?)'
    rb'</(?:[A-Za-z_][\w.-]*:)?object\s*>',
    re.DOTALL | re.IGNORECASE,
)
_MESH_TAG_RE = re.compile(
    rb'<(?:[A-Za-z_][\w.-]*:)?mesh\b', re.IGNORECASE)
_COLOR_ANALYSIS_CACHE = {}


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _find_objects_with_mesh(data):
    """返回 [(model_path, object_id, vertices, triangles)]。
    vertices/triangles 为原始字符串行列表，稍后统一解析。"""
    out = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return out
    for model in root.iter():
        if _local(model.tag) != 'object':
            continue
        mesh = None
        for child in model:
            if _local(child.tag) == 'mesh':
                mesh = child
                break
        if mesh is None:
            continue
        oid = model.get('id')
        verts, tris = [], []
        for child in mesh:
            tag = _local(child.tag)
            if tag == 'vertices':
                for v in child:
                    if _local(v.tag) == 'vertex':
                        verts.append((float(v.get('x', 0)),
                                      float(v.get('y', 0)),
                                      float(v.get('z', 0))))
            elif tag == 'triangles':
                for t in child:
                    if _local(t.tag) == 'triangle':
                        tris.append((int(t.get('v1', 0)),
                                     int(t.get('v2', 0)),
                                     int(t.get('v3', 0))))
        if verts and tris:
            out.append((oid, verts, tris))
    return out


def _model_files(z):
    names = []
    for n in z.namelist():
        low = n.lower()
        if not low.endswith('.model'):
            continue
        if '_rels/' in low or low.endswith('.model.rels'):
            continue
        names.append(n)
    # 主模型（内容最多的）放最后优先？直接全部收集即可
    return names


def _paint_leaf_states(encoded):
    """解码 Bambu 的 paint_color 子树，返回所有叶子颜色状态。

    每个十六进制数字按从右到左、低位先读的顺序组成位流。低 2 位是
    分裂边数；0 表示叶子，否则递归读取 2~4 个子三角形。叶子低 2 位
    为 0 时，高 2 位是状态；状态 3 及以上使用连续 0xF 扩展编码。
    """
    text = str(encoded or '').strip().upper()
    if not text or any(ch not in '0123456789ABCDEF' for ch in text):
        return []
    bits = []
    for ch in reversed(text):
        value = int(ch, 16)
        bits.extend(bool(value & (1 << bit)) for bit in range(4))
    cursor = 0

    def next_nibble():
        nonlocal cursor
        if cursor + 4 > len(bits):
            raise ValueError('paint_color 数据提前结束')
        value = 0
        for bit in range(4):
            value |= int(bits[cursor + bit]) << bit
        cursor += 4
        return value

    def read_item():
        code = next_nibble()
        split_sides = code & 0b11
        if split_sides:
            return split_sides + 1, None
        if (code & 0b1100) == 0b1100:
            next_code = next_nibble()
            repeats = 0
            while next_code == 0b1111:
                repeats += 1
                next_code = next_nibble()
            state = next_code + 15 * repeats + 3
        else:
            state = code >> 2
        return 0, state

    def walk():
        children, state = read_item()
        if not children:
            if state is not None:
                yield state
            return
        for _ in range(children):
            yield from walk()

    try:
        return list(walk())
    except ValueError:
        return []


def _model_roots(z):
    """读取所有 .model 文件里的对象索引，供颜色分析递归组件使用。"""
    roots = {}
    for name in _model_files(z):
        try:
            root = ET.fromstring(z.read(name))
        except ET.ParseError:
            continue
        key = _model_path(name)
        for obj in root.iter():
            if _local(obj.tag) == 'object' and obj.get('id') is not None:
                roots[(key, str(obj.get('id')))] = obj
    return roots


def _object_color_usage(roots, path, oid, default_slots, color_count, stack):
    key = (_model_path(path), str(oid))
    if key in stack or key not in roots:
        return {
            'triangle_count': 0,
            'painted_triangles': 0,
            'leaf_states': {},
            'effective_counts': {},
        }
    stack = set(stack)
    stack.add(key)
    obj = roots[key]
    result = {
        'triangle_count': 0,
        'painted_triangles': 0,
        'leaf_states': {},
        'effective_counts': {},
    }
    mesh = None
    components = None
    for child in obj:
        tag = _local(child.tag)
        if tag == 'mesh':
            mesh = child
        elif tag == 'components':
            components = child

    if mesh is not None:
        triangles = []
        for child in mesh:
            tag = _local(child.tag)
            if tag == 'triangles':
                triangles.extend(
                    t for t in child if _local(t.tag) == 'triangle'
                )
        if triangles:
            result['triangle_count'] += len(triangles)
            default_slots = tuple(default_slots or (1,))
            for triangle in triangles:
                paint = triangle.get('paint_color')
                states = _paint_leaf_states(paint) if paint else []
                if states:
                    result['painted_triangles'] += 1
                    counts = {}
                    for state in states:
                        counts[state] = counts.get(state, 0) + 1
                    for state, count in counts.items():
                        result['leaf_states'][str(state)] = (
                            result['leaf_states'].get(str(state), 0) + count)
                    state = max(counts.items(), key=lambda row: row[1])[0]
                    slots = default_slots if state == 0 else (state,)
                    if state > color_count and color_count > 0:
                        slots = default_slots
                    for slot in slots:
                        result['effective_counts'][str(slot)] = (
                            result['effective_counts'].get(str(slot), 0) + 1)
                else:
                    for slot in default_slots:
                        result['effective_counts'][str(slot)] = (
                            result['effective_counts'].get(str(slot), 0) + 1)

    if components is not None:
        for component in components:
            if _local(component.tag) != 'component':
                continue
            child_path = (
                component.get(_PNS + 'path')
                or component.get('path')
                or path
            )
            child_id = component.get('objectid')
            child = _object_color_usage(
                roots, child_path, child_id, default_slots, color_count, stack)
            result['triangle_count'] += child['triangle_count']
            result['painted_triangles'] += child['painted_triangles']
            for state, value in child['leaf_states'].items():
                result['leaf_states'][state] = (
                    result['leaf_states'].get(state, 0) + value)
            for slot, value in child['effective_counts'].items():
                result['effective_counts'][slot] = (
                    result['effective_counts'].get(slot, 0) + value)
    return result


def _project_color_analysis(path):
    """读取所有对象的几何颜色类别，不修改或重绑工程物料。"""
    info = {
        'face_paint': False,
        'painted_triangles': 0,
        'classes': [],
        'objects': {},
    }
    try:
        with zipfile.ZipFile(path) as z:
            project = {}
            if 'Metadata/project_settings.config' in z.namelist():
                project = json.loads(z.read(
                    'Metadata/project_settings.config').decode(
                        'utf-8', 'replace'))
            colors = (
                project.get('filament_colour')
                or project.get('filament_colors')
                or project.get('filament_multi_colour')
                or []
            )
            if isinstance(colors, str):
                colors = [colors]
            color_count = max(1, len(colors))
            defaults = {}
            if 'Metadata/model_settings.config' in z.namelist():
                config = ET.fromstring(
                    z.read('Metadata/model_settings.config'))
                for obj in config:
                    if _local(obj.tag) != 'object' or not obj.get('id'):
                        continue
                    slots = set()
                    for node in obj.iter():
                        if (_local(node.tag) == 'metadata'
                                and node.get('key') == 'extruder'):
                            try:
                                slot = int(node.get('value'))
                            except (TypeError, ValueError):
                                continue
                            if slot > 0:
                                slots.add(slot)
                    defaults[str(obj.get('id'))] = tuple(sorted(slots or (1,)))
            roots = _model_roots(z)
            main_path = '3D/3dmodel.model'
            if not roots:
                return info
            if not defaults:
                for key in roots:
                    defaults.setdefault(key[1], (1,))
            all_slots = set()
            for object_id, default_slots in defaults.items():
                usage = _object_color_usage(
                    roots, main_path, object_id, default_slots,
                    color_count, set())
                effective = [
                    int(slot) for slot, count
                    in usage['effective_counts'].items()
                    if count > 0
                ]
                visual = list(effective)
                if usage['painted_triangles']:
                    effective.extend(int(slot) for slot in default_slots)
                effective.sort()
                effective = sorted(set(effective))
                visual = sorted(set(visual)) or list(default_slots)
                dominant = None
                if usage['effective_counts']:
                    dominant = int(max(
                        usage['effective_counts'].items(),
                        key=lambda row: row[1])[0])
                usage['effective_slots'] = effective or list(default_slots)
                usage['visual_slots'] = visual
                usage['dominant_slot'] = dominant or (
                    effective[0] if effective else default_slots[0])
                usage['painted'] = bool(usage['painted_triangles'])
                info['objects'][str(object_id)] = usage
                info['painted_triangles'] += usage['painted_triangles']
                all_slots.update(visual)
            info['face_paint'] = info['painted_triangles'] > 0
            info['classes'] = sorted(all_slots)
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile):
        return info
    return info


def project_color_analysis(path):
    """带文件时间戳缓存的颜色类别分析，避免 UI 重复解析大模型。"""
    try:
        stat = os.stat(path)
    except OSError:
        return _project_color_analysis(path)
    key = (os.path.normcase(os.path.abspath(path)),
           int(stat.st_mtime_ns), int(stat.st_size))
    cached = _COLOR_ANALYSIS_CACHE.get(key)
    if cached is not None:
        return cached
    result = _project_color_analysis(path)
    if len(_COLOR_ANALYSIS_CACHE) > 16:
        _COLOR_ANALYSIS_CACHE.clear()
    _COLOR_ANALYSIS_CACHE[key] = result
    return result


def face_color_signature(path):
    """返回可比较的几何颜色签名，用于确认输出没有丢掉面漆。"""
    analysis = project_color_analysis(path)
    return {
        str(object_id): (
            int(usage.get('painted_triangles') or 0),
            tuple(usage.get('effective_slots') or ()),
            tuple(sorted(
                (str(state), int(count))
                for state, count in (
                    usage.get('leaf_states') or {}).items()
            )),
        )
        for object_id, usage in (analysis.get('objects') or {}).items()
    }


def _triangle_normal(a, b, c):
    ux, uy, uz = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    vx, vy, vz = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    nx, ny, nz = (uy * vz - uz * vy, uz * vx - ux * vz,
                  ux * vy - uy * vx)
    length = (nx * nx + ny * ny + nz * nz) ** 0.5
    if length < 1e-12:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def split_meshes(path, out_dir, prefix=None):
    """拆出一个 .3mf 里所有带 mesh 的对象，返回生成的 .stl 路径列表。"""
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    if not prefix:
        prefix = base
    results = []
    seq = 0
    with zipfile.ZipFile(path) as z:
        for model_name in _model_files(z):
            data = z.read(model_name).decode('utf-8', 'ignore')
            for oid, verts, tris in _find_objects_with_mesh(data):
                seq += 1
                dst = os.path.join(out_dir, f'{prefix}_{seq:02d}.stl')
                with open(dst, 'wb') as f:
                    f.write(b'unpacked from 3mf'.ljust(80, b'\x00'))
                    f.write(struct.pack('<I', len(tris)))
                    for v1, v2, v3 in tris:
                        a = verts[v1]
                        b = verts[v2]
                        c = verts[v3]
                        n = _triangle_normal(a, b, c)
                        f.write(struct.pack('<3f', *n))
                        for p in (a, b, c):
                            f.write(struct.pack('<3f', *p))
                        f.write(struct.pack('<H', 0))
                results.append(dst)
    return results


def count_meshes(path):
    """返回 .3mf 里带 mesh 的对象数量（不含只做装配的容器）。"""
    try:
        with zipfile.ZipFile(path) as z:
            total = 0
            for model_name in _model_files(z):
                raw = z.read(model_name)
                if b'<mesh' not in raw.lower():
                    continue
                # Counting objects must not parse hundreds of thousands of
                # vertices/triangles on the UI thread. Scan bounded object
                # blocks; fall back to the full XML parser for unusual files.
                found = sum(
                    1 for match in _OBJECT_BLOCK_RE.finditer(raw)
                    if _MESH_TAG_RE.search(match.group(1)))
                if found:
                    total += found
                else:
                    data = raw.decode('utf-8', 'ignore')
                    total += len(_find_objects_with_mesh(data))
            return total
    except (OSError, zipfile.BadZipFile):
        return 0


def count_build_items(path):
    """返回 3MF build 里的实例数；没有 build 时退回唯一 mesh 数。

    同一个 mesh 可以镜像/平移成多个 build item（例如一对石狮子）。
    count_meshes 会把它们算成 1 个，报告里的“几件”就不对。
    """
    try:
        with zipfile.ZipFile(path) as z:
            data = z.read('3D/3dmodel.model').decode('utf-8', 'ignore')
        root = ET.fromstring(data)
        for el in root.iter():
            if _local(el.tag) != 'build':
                continue
            items = [c for c in el if _local(c.tag) == 'item']
            if items:
                return len(items)
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        pass
    return count_meshes(path)


def count_plates(path):
    """返回 model_settings.config 里的盘数；没有配置时按 1 盘处理。"""
    try:
        with zipfile.ZipFile(path) as z:
            if 'Metadata/model_settings.config' not in z.namelist():
                return 1
            data = z.read('Metadata/model_settings.config').decode(
                'utf-8', 'ignore')
        root = ET.fromstring(data)
        n = sum(1 for el in root.iter() if _local(el.tag) == 'plate')
        return max(1, n)
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        return 1


def needs_build_item_split(path):
    """单盘文件里同一 mesh 被镜像/重复成多个实例时，必须按 build item 拆。

    多盘文件仍沿用原来的“按唯一 mesh 拆”，否则同一零件在不同盘上的
    重复实例会被误算成多个不同零件。
    """
    return (count_plates(path) <= 1
            and count_build_items(path) > count_meshes(path))


def needs_assembly_export(path):
    """单个 build item 内含多个 component 的装配体（常见于手办）。"""
    return (count_plates(path) <= 1
            and count_build_items(path) == 1
            and count_meshes(path) > 1)


def count_parts_for_pack(path):
    """自动摆盘实际要处理的零件数。"""
    if needs_assembly_export(path):
        return 1
    return (count_build_items(path)
            if needs_build_item_split(path) else count_meshes(path))


def project_overrides(path, figurine=False):
    """读取 3MF 内嵌项目参数，生成可追加到的 process override。

    默认配方（15% grid）适合机械件，但手办项目常用 lightning/低密度
    内嵌设置；不保留它会把 200g 的模型切成 900g。
    """
    try:
        with zipfile.ZipFile(path) as z:
            if 'Metadata/project_settings.config' not in z.namelist():
                return ''
            cfg = json.loads(z.read(
                'Metadata/project_settings.config').decode(
                    'utf-8', 'replace'))
    except (OSError, ValueError, zipfile.BadZipFile):
        return ''

    def first(key, default=None):
        v = cfg.get(key, default)
        if isinstance(v, list):
            return v[0] if v else default
        return v

    out = []
    density = first('sparse_infill_density')
    pattern = first('sparse_infill_pattern')
    layer = first('layer_height')
    if density not in (None, ''):
        d = str(density).strip()
        out.append('sparse_infill_density=' + (d if d.endswith('%') else d + '%'))
    if pattern not in (None, ''):
        out.append('sparse_infill_pattern=' + str(pattern).strip())
    if layer not in (None, ''):
        out.append('layer_height=' + str(layer).strip())
    if figurine:
        out += [
            'enable_support=1',
            'support_type=tree(auto)',
            'support_on_build_plate_only=1',
            'support_critical_regions_only=1',
            'support_threshold_angle=55',
            'support_remove_small_overhang=1',
            'tree_support_branch_distance=5',
            'tree_support_branch_diameter=2',
            'support_interface_top_layers=2',
        ]
    return ';'.join(out)


def project_filament_info(path):
    """读取 3MF 的耗材槽位和零件颜色绑定。

    多色手办一旦拆 STL 或只加载一个耗材预设，颜色绑定会丢失；
    调用方据此改用 Bambu 的整项目直切。
    """
    info = {
        'colors': [],
        'types': [],
        'used_extruders': [],
        'filament_maps': [],
        'color_classes': [],
        'painted_triangles': 0,
        'face_paint': False,
        'multicolor': False,
        'single_filament': False,
    }
    try:
        with zipfile.ZipFile(path) as z:
            if 'Metadata/project_settings.config' in z.namelist():
                cfg = json.loads(z.read(
                    'Metadata/project_settings.config').decode(
                        'utf-8', 'replace'))
                colors = (cfg.get('filament_colors')
                          or cfg.get('filament_colour')
                          or cfg.get('filament_multi_colour')
                          or [])
                types = cfg.get('filament_type') or []
                if isinstance(colors, str):
                    colors = [colors]
                if isinstance(types, str):
                    types = [types]
                info['colors'] = [str(v) for v in colors if str(v).strip()]
                info['types'] = [str(v) for v in types if str(v).strip()]
            if 'Metadata/model_settings.config' in z.namelist():
                root = ET.fromstring(z.read(
                    'Metadata/model_settings.config'))
                used = set()
                for obj in root.iter():
                    if _local(obj.tag) not in ('object', 'part'):
                        continue
                    for meta in obj:
                        if (_local(meta.tag) == 'metadata'
                                and meta.get('key') == 'extruder'):
                            try:
                                slot = int(meta.get('value'))
                                if slot > 0:
                                    used.add(slot)
                            except (TypeError, ValueError):
                                pass
                    for meta in obj.iter():
                        if (_local(meta.tag) == 'metadata'
                                and meta.get('key') == 'filament_maps'):
                            info['filament_maps'] = [
                                int(v) for v in
                                str(meta.get('value') or '').split()
                                if v.lstrip('-').isdigit()]
                info['used_extruders'] = sorted(used)
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile):
        return info
    color_analysis = project_color_analysis(path)
    info['face_paint'] = bool(color_analysis.get('face_paint'))
    info['painted_triangles'] = int(
        color_analysis.get('painted_triangles') or 0)
    info['color_classes'] = list(color_analysis.get('classes') or [])
    used = sorted(set(info['used_extruders']) | set(info['color_classes']))
    info['used_extruders'] = used
    used_colors = {
        str(info['colors'][slot - 1]).strip().upper()
        for slot in used
        if 0 < slot <= len(info['colors'])
    }
    used_types = {
        str(info['types'][slot - 1]).strip().upper()
        for slot in used
        if 0 < slot <= len(info['types'])
    }
    info['used_colors'] = sorted(used_colors)
    info['used_types'] = sorted(used_types)
    info['single_filament'] = bool(
        len(used) <= 1
        and len(used_colors) <= 1
        and len(used_types) <= 1
        and len(info['color_classes']) <= 1
        and (
            bool(used)
            or (len(info['colors']) <= 1 and len(info['types']) <= 1)
        ))
    # Bambu 的颜色数组常带未使用槽位；只有实际物料的绑定才决定是否受保护。
    info['multicolor'] = not info['single_filament']
    return info


def color_binding_signature(path):
    """返回颜色/材料数组与 object/part 的耗材绑定，用于输出前后校验。"""
    with zipfile.ZipFile(path) as archive:
        project = json.loads(
            archive.read('Metadata/project_settings.config').decode('utf-8'))
        config_root = ET.fromstring(
            archive.read('Metadata/model_settings.config'))
    colors = (
        project.get('filament_colour')
        or project.get('filament_colors')
        or project.get('filament_multi_colour')
        or []
    )
    types = project.get('filament_type') or []
    if isinstance(colors, str):
        colors = [colors]
    if isinstance(types, str):
        types = [types]
    bindings = {}
    for obj in config_root:
        if _local(obj.tag) != 'object' or not obj.get('id'):
            continue
        object_id = str(obj.get('id'))
        for node in obj:
            if (_local(node.tag) == 'metadata'
                    and node.get('key') == 'extruder'):
                bindings[(object_id, 'object')] = int(node.get('value'))
        for part in obj:
            if _local(part.tag) != 'part':
                continue
            part_id = str(part.get('id') or '')
            for node in part:
                if (_local(node.tag) == 'metadata'
                        and node.get('key') == 'extruder'):
                    bindings[(object_id, part_id)] = int(node.get('value'))
    return list(colors), list(types), bindings


def verify_color_bindings(source, output):
    """确认切片输出没有把多色/多材料工程压成单色。"""
    src_colors, src_types, src_bindings = color_binding_signature(source)
    out_colors, out_types, out_bindings = color_binding_signature(output)
    if src_colors and out_colors != src_colors:
        raise ValueError('输出丢失耗材颜色数组')
    if src_types and out_types != src_types:
        raise ValueError('输出丢失耗材材料数组')
    for key, value in out_bindings.items():
        if key in src_bindings and src_bindings[key] != value:
            raise ValueError(
                '输出改变了对象/部件耗材绑定：%s %s→%s'
                % (key, src_bindings[key], value))
    if project_color_analysis(source).get('face_paint'):
        if face_color_signature(source) != face_color_signature(output):
            raise ValueError('输出丢失或改变了模型面漆颜色')


def plate_layout(path):
    """返回每盘的盘名、耗材映射和对象成员，按 plater_id 排序。"""
    rows = []
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read('Metadata/model_settings.config'))
            object_names = {}
            for obj in root:
                if _local(obj.tag) != 'object':
                    continue
                oid = str(obj.get('id') or '')
                for meta in obj:
                    if (_local(meta.tag) == 'metadata'
                            and meta.get('key') == 'name'):
                        object_names[oid] = meta.get('value') or ''
                        break
            for plate in root:
                if _local(plate.tag) != 'plate':
                    continue
                md = {
                    m.get('key'): m.get('value')
                    for m in plate if _local(m.tag) == 'metadata'
                }
                members = []
                for inst in plate:
                    if _local(inst.tag) != 'model_instance':
                        continue
                    im = {
                        m.get('key'): m.get('value')
                        for m in inst if _local(m.tag) == 'metadata'
                    }
                    oid = str(im.get('object_id') or '')
                    members.append({
                        'object_id': oid,
                        'name': object_names.get(oid, ''),
                    })
                rows.append({
                    'plate': int(md.get('plater_id') or len(rows) + 1),
                    'name': md.get('plater_name') or '',
                    'filament_maps': md.get('filament_maps') or '',
                    'objects': members,
                })
    except (OSError, KeyError, ValueError, ET.ParseError,
            zipfile.BadZipFile):
        return []
    return sorted(rows, key=lambda row: row['plate'])


def _transform(text):
    """3MF 的 12 数变换（3x3 + 平移）→ 4x4 矩阵。

    3MF 规范使用行向量（point * matrix），内部统一存成列向量矩阵，
    所以左上 3x3 要转置；否则非对称旋转会被转到错误方向。
    """
    if not text:
        return np.eye(4, dtype=np.float64)
    a = [float(x) for x in str(text).replace(',', ' ').split()]
    if len(a) != 12:
        return np.eye(4, dtype=np.float64)
    m = np.eye(4, dtype=np.float64)
    m[:3, :3] = np.array(
        a[:9], dtype=np.float64).reshape(3, 3).T
    m[:3, 3] = a[9:12]
    return m


def _model_path(name):
    name = str(name or '3D/3dmodel.model').replace('\\', '/').lstrip('/')
    return name.lower()


def _register_xml_namespaces(data):
    """保留原 XML 的默认/Bambu/p 前缀，Bambu 对 3MF 前缀兼容性更稳。"""
    try:
        for _event, (prefix, uri) in ET.iterparse(
                io.BytesIO(data), events=('start-ns',)):
            ET.register_namespace(prefix or '', uri)
    except (ET.ParseError, ValueError):
        pass


def _mesh(V, F, M):
    if len(V) == 0 or len(F) == 0:
        return np.empty((0, 3), dtype=np.float64), np.empty((0, 3), dtype=np.int64)
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    V = V @ M[:3, :3].T + M[:3, 3]
    return V, F


def _object_mesh(roots, path, oid, M, stack):
    key = (_model_path(path), str(oid))
    if key in stack:
        return (np.empty((0, 3), dtype=np.float64),
                np.empty((0, 3), dtype=np.int64))
    obj = roots.get(key)
    if obj is None:
        return (np.empty((0, 3), dtype=np.float64),
                np.empty((0, 3), dtype=np.int64))
    stack = set(stack)
    stack.add(key)
    V, F = [], []
    mesh_el = None
    components = None
    for child in obj:
        tag = _local(child.tag)
        if tag == 'mesh':
            mesh_el = child
        elif tag == 'components':
            components = child
    if mesh_el is not None:
        vv, ff = [], []
        for child in mesh_el:
            tag = _local(child.tag)
            if tag == 'vertices':
                for v in child:
                    if _local(v.tag) == 'vertex':
                        vv.append((float(v.get('x', 0)),
                                   float(v.get('y', 0)),
                                   float(v.get('z', 0))))
            elif tag == 'triangles':
                for t in child:
                    if _local(t.tag) == 'triangle':
                        ff.append((int(t.get('v1', 0)),
                                   int(t.get('v2', 0)),
                                   int(t.get('v3', 0))))
        return _mesh(vv, ff, M)
    if components is not None:
        base = 0
        for comp in components:
            if _local(comp.tag) != 'component':
                continue
            cpath = comp.get(_PNS + 'path') or comp.get('path') or path
            cid = comp.get('objectid')
            cm = M @ _transform(comp.get('transform'))
            cv, cf = _object_mesh(roots, cpath, cid, cm, stack)
            if len(cv):
                V.append(cv)
                F.append(cf + base)
                base += len(cv)
    if not V:
        return (np.empty((0, 3), dtype=np.float64),
                np.empty((0, 3), dtype=np.int64))
    return np.vstack(V), np.vstack(F)


def _printable_part_indices(z, oid):
    """从 model_settings 读出顶层对象的普通零件位置。"""
    try:
        data = z.read('Metadata/model_settings.config').decode(
            'utf-8', 'ignore')
        root = ET.fromstring(data)
        for obj in root.iter():
            if _local(obj.tag) != 'object' or obj.get('id') != str(oid):
                continue
            parts = [c for c in obj if _local(c.tag) == 'part']
            if not parts:
                return None
            keep = []
            for i, part in enumerate(parts):
                subtype = (part.get('subtype') or 'normal_part').lower()
                if subtype not in _NON_PRINTABLE:
                    keep.append(i)
            return keep or None
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        pass
    return None


def build_item_names(path):
    """返回 3MF build 中每个顶层对象的原始名称。"""
    try:
        with zipfile.ZipFile(path) as z:
            names_by_oid = {}
            if 'Metadata/model_settings.config' in z.namelist():
                root_cfg = ET.fromstring(
                    z.read('Metadata/model_settings.config'))
                for obj in root_cfg:
                    if _local(obj.tag) != 'object' or not obj.get('id'):
                        continue
                    for meta in obj:
                        if (_local(meta.tag) == 'metadata'
                                and meta.get('key') == 'name'):
                            names_by_oid[str(obj.get('id'))] = (
                                meta.get('value') or '')
                            break
            root = ET.fromstring(z.read('3D/3dmodel.model'))
            items = []
            for el in root.iter():
                if _local(el.tag) == 'build':
                    items = [c for c in el if _local(c.tag) == 'item']
                    break
            return [
                names_by_oid.get(str(item.get('objectid')), '')
                or 'object_%s' % item.get('objectid')
                for item in items
            ]
    except (OSError, ET.ParseError, zipfile.BadZipFile):
        return []


def inspect_meshes(path):
    """检查 3MF 内每个实体网格的拓扑，不做导出或变换。

    装配体可能由多个彼此接触的实体组成；把装配体先合再检查，接触面
    会被误判成非流形边。这里按原始网格逐个检查，更接近 Bambu 对每个
    可打印对象给出的告警。
    """
    names = {}
    try:
        with zipfile.ZipFile(path) as z:
            if 'Metadata/model_settings.config' in z.namelist():
                cfg = ET.fromstring(
                    z.read('Metadata/model_settings.config'))
                for obj in cfg.iter():
                    if _local(obj.tag) != 'object' or not obj.get('id'):
                        continue
                    for meta in obj:
                        if (_local(meta.tag) == 'metadata'
                                and meta.get('key') == 'name'):
                            names[str(obj.get('id'))] = (
                                meta.get('value') or '')
                            break
    except (OSError, ET.ParseError, zipfile.BadZipFile):
        pass

    reports = []
    try:
        with zipfile.ZipFile(path) as z:
            for model_name in _model_files(z):
                data = z.read(model_name)
                for oid, vertices, triangles in _find_objects_with_mesh(data):
                    v = np.asarray(vertices, dtype=np.float64)
                    f = np.asarray(triangles, dtype=np.int64)
                    edge_pairs = np.sort(
                        f[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1)
                    _, edge_counts = np.unique(
                        edge_pairs, axis=0, return_counts=True)
                    tri = v[f] if len(f) else np.empty((0, 3, 3))
                    if len(tri):
                        areas = 0.5 * np.linalg.norm(
                            np.cross(tri[:, 1] - tri[:, 0],
                                     tri[:, 2] - tri[:, 0]), axis=1)
                    else:
                        areas = np.empty(0, dtype=np.float64)
                    reports.append({
                        'id': str(oid),
                        'name': names.get(str(oid), 'object_%s' % oid),
                        'model': model_name,
                        'triangles': int(len(f)),
                        'nonmanifold_edges': int(
                            (edge_counts > 2).sum()),
                        'boundary_edges': int(
                            (edge_counts == 1).sum()),
                        'degenerate_faces': int((areas <= 1e-12).sum()),
                    })
    except (OSError, zipfile.BadZipFile):
        pass
    return reports


def _safe_part_name(text):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', str(text or ''))
    text = text.strip(' ._')[:80]
    if text.lower().endswith('.stl'):
        text = text[:-4]
    return text


def export_printable_build_items(path, out_dir, prefix=None):
    """按 build item 导出**可打印装配体** STL。

    会应用 component/build 变换，并跳过 model_settings 里标记为
    modifier/negative/support-blocker 的零件。用于手办这类“一个 build
    item 里含很多子零件”的 3MF，避免把修改器当成实体打印。
    """
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(path) as z:
        roots = {}
        for name in z.namelist():
            low = name.lower()
            if not low.endswith('.model'):
                continue
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            for obj in root.iter():
                if _local(obj.tag) == 'object' and obj.get('id'):
                    roots[(_model_path(name), str(obj.get('id')))] = obj
        main = '3D/3dmodel.model'
        root = ET.fromstring(z.read(main))
        items = []
        for el in root.iter():
            if _local(el.tag) == 'build':
                items = [c for c in el if _local(c.tag) == 'item']
        if not items:
            return []
        if not prefix:
            prefix = os.path.splitext(os.path.basename(path))[0]
        names = build_item_names(path)
        out = []
        for idx, item in enumerate(items, 1):
            oid = item.get('objectid')
            M = _transform(item.get('transform'))
            obj = roots.get((_model_path(main), str(oid)))
            if obj is None:
                continue
            vv, ff = [], []
            base = 0
            components = None
            mesh_el = None
            for child in obj:
                if _local(child.tag) == 'components':
                    components = child
                elif _local(child.tag) == 'mesh':
                    mesh_el = child
            if mesh_el is not None:
                V, F = _object_mesh(roots, main, oid, M, set())
                vv.append(V); ff.append(F)
            elif components is not None:
                keep = _printable_part_indices(z, oid)
                comps = [c for c in components
                         if _local(c.tag) == 'component']
                for ci, comp in enumerate(comps):
                    if keep is not None and ci not in keep:
                        continue
                    cpath = comp.get(_PNS + 'path') or comp.get('path') or main
                    cid = comp.get('objectid')
                    cm = M @ _transform(comp.get('transform'))
                    V, F = _object_mesh(roots, cpath, cid, cm, set())
                    if len(V):
                        vv.append(V); ff.append(F + base); base += len(V)
            if not vv:
                continue
            V = np.vstack(vv)
            F = np.vstack(ff)
            part_name = names[idx - 1] if idx <= len(names) else ''
            safe_name = _safe_part_name(part_name)
            stem = f'{prefix}_{idx:02d}'
            if safe_name:
                stem += '_' + safe_name
            dst = os.path.join(out_dir, stem + '.stl')
            tri = V[F]
            n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            ln = np.linalg.norm(n, axis=1)
            ln[ln == 0] = 1.0
            n = n / ln[:, None]
            with open(dst, 'wb') as f:
                f.write(b'assembled by tuozhu-helper'.ljust(80, b'\x00'))
                f.write(struct.pack('<I', len(tri)))
                for i in range(len(tri)):
                    f.write(struct.pack('<3f', *n[i]))
                    for k in range(3):
                        f.write(struct.pack('<3f', *tri[i, k]))
                    f.write(struct.pack('<H', 0))
            out.append(dst)
        return out


def _load_roots_and_items(z):
    """读取对象、主模型 build item、实际 zip 路径和 XML 根节点。"""
    roots = {}
    entries = {}
    root_map = {}
    for name in z.namelist():
        low = name.lower()
        if (not low.endswith('.model') or '_rels/' in low
                or low.endswith('.model.rels')):
            continue
        try:
            root = ET.fromstring(z.read(name))
        except ET.ParseError:
            continue
        key = _model_path(name)
        entries[key] = name
        root_map[key] = root
        for obj in root.iter():
            if _local(obj.tag) == 'object' and obj.get('id'):
                roots[(key, str(obj.get('id')))] = obj
    main_key = _model_path('3D/3dmodel.model')
    main_root = root_map.get(main_key)
    if main_root is None:
        raise ValueError('3MF 缺少 3D/3dmodel.model')
    items = []
    for el in main_root.iter():
        if _local(el.tag) == 'build':
            items = [c for c in el if _local(c.tag) == 'item']
            break
    return roots, items, entries, root_map


def _write_binary_stl(path, vertices, faces):
    tri = np.asarray(vertices, dtype=np.float64)[
        np.asarray(faces, dtype=np.int64)]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    lengths[lengths == 0] = 1.0
    normals = normals / lengths[:, None]
    with open(path, 'wb') as f:
        f.write(b'exported by tuozhu-helper'.ljust(80, b'\x00'))
        f.write(struct.pack('<I', len(tri)))
        for i in range(len(tri)):
            f.write(struct.pack('<3f', *normals[i]))
            for k in range(3):
                f.write(struct.pack('<3f', *tri[i, k]))
            f.write(struct.pack('<H', 0))


def inspect_build_items(path):
    """返回每个顶层 build item 的世界坐标包围盒、体积和最低 Z。"""
    rows = []
    try:
        import trimesh
        with zipfile.ZipFile(path) as z:
            roots, items, _entries, _root_map = _load_roots_and_items(z)
            names = build_item_names(path)
            for index, item in enumerate(items, 1):
                if str(item.get('printable') or '1') == '0':
                    continue
                M = _transform(item.get('transform'))
                V, F = _object_mesh(
                    roots, '3D/3dmodel.model', str(item.get('objectid')),
                    M, set())
                if not len(V):
                    continue
                mn = V.min(axis=0)
                mx = V.max(axis=0)
                mesh = trimesh.Trimesh(
                    vertices=V, faces=F, process=False)
                try:
                    volume = abs(float(mesh.volume))
                except (TypeError, ValueError):
                    volume = 0.0
                try:
                    area = abs(float(mesh.area))
                except (TypeError, ValueError):
                    area = 0.0
                rows.append({
                    'index': index,
                    'name': names[index - 1] if index <= len(names)
                    else 'object_%s' % item.get('objectid'),
                    'object_id': str(item.get('objectid')),
                    'volume_mm3': volume,
                    'area_mm2': area,
                    'min': [float(v) for v in mn],
                    'max': [float(v) for v in mx],
                    'min_z': float(mn[2]),
                    'max_z': float(mx[2]),
                })
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return []
    return rows


def export_build_item_stl(path, out_stl, item_index):
    """把一个顶层 build item 按世界坐标导出成单个 STL（1-based）。"""
    with zipfile.ZipFile(path) as z:
        roots, items, _entries, _root_map = _load_roots_and_items(z)
        if item_index < 1 or item_index > len(items):
            raise ValueError('build item 序号越界：%s' % item_index)
        item = items[item_index - 1]
        M = _transform(item.get('transform'))
        V, F = _object_mesh(
            roots, '3D/3dmodel.model', str(item.get('objectid')), M, set())
        if not len(V) or not len(F):
            raise ValueError('build item %d 没有可导出的网格' % item_index)
    _write_binary_stl(out_stl, V, F)
    return out_stl


def replace_build_item_geometry(path, out_path, item_index, replacement_stl):
    """把一个 build item 的 Bambu 自动朝向写成纯变换，保留原始网格。

    只修改主模型里的 transform 字符串，不重写几十万顶点。XY 中心沿用
    原位置，底面贴到 Z=0；名称、盘号、网格文件和其它对象都不动。
    """
    import trimesh
    with zipfile.ZipFile(path) as z:
        roots, items, _entries, root_map = _load_roots_and_items(z)
        if item_index < 1 or item_index > len(items):
            raise ValueError('build item 序号越界：%s' % item_index)
        item = items[item_index - 1]
        main_key = _model_path('3D/3dmodel.model')
        outer_oid = str(item.get('objectid'))
        outer = roots.get((main_key, outer_oid))
        if outer is None:
            raise ValueError('找不到 build item 外层对象 %s' % outer_oid)
        old_M = _transform(item.get('transform'))
        old_V, old_F = _object_mesh(
            roots, main_key, outer_oid, old_M, set())
        rep = trimesh.load(replacement_stl, force='mesh', process=False)
        new_V = np.asarray(rep.vertices, dtype=np.float64)
        new_F = np.asarray(rep.faces, dtype=np.int64)
        if not len(new_V) or not len(new_F):
            raise ValueError('自动朝向结果为空')
        A = old_V[old_F].reshape(-1, 3)
        B = new_V[new_F].reshape(-1, 3)
        if A.shape != B.shape:
            raise ValueError('自动朝向前后三角面顺序不一致，无法安全回写')
        ca, cb = A.mean(axis=0), B.mean(axis=0)
        H = (A - ca).T @ (B - cb)
        U, _S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1] *= -1
            R = Vt.T @ U.T
        predicted = (R @ A.T).T + (cb - R @ ca)
        rms = float(np.sqrt(np.mean(np.sum(
            (predicted - B) ** 2, axis=1))))
        if not np.isfinite(rms) or rms > 0.05:
            raise ValueError('自动朝向变换误差过大：%.4f mm' % rms)

        rotated = (R @ old_V.T).T
        old_min, old_max = old_V.min(axis=0), old_V.max(axis=0)
        new_min, new_max = rotated.min(axis=0), rotated.max(axis=0)
        shift = np.array([
            (old_min[0] + old_max[0] - new_min[0] - new_max[0]) / 2.0,
            (old_min[1] + old_max[1] - new_min[1] - new_max[1]) / 2.0,
            -new_min[2],
        ])
        new_R = R @ old_M[:3, :3]
        new_t = R @ old_M[:3, 3] + shift
        row_rotation = new_R.T
        transform = ' '.join('%.9g' % v for v in (
            list(row_rotation[0]) + list(row_rotation[1])
            + list(row_rotation[2]) + list(new_t)))
        item.set('transform', transform)

        _register_xml_namespaces(z.read('3D/3dmodel.model'))
        replaced = {
            main_key: ET.tostring(
                root_map[main_key], encoding='utf-8', xml_declaration=True),
        }
        os.makedirs(
            os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as dst:
            for info in z.infolist():
                key = _model_path(info.filename)
                data = replaced.get(key)
                if data is None:
                    data = z.read(info.filename)
                dst.writestr(info, data)
    final_V = rotated + shift
    return {
        'item': item_index,
        'rms_mm': rms,
        'min_z': float(final_V[:, 2].min()),
        'max_z': float(final_V[:, 2].max()),
    }
