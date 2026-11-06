# -*- coding: utf-8 -*-
"""把多个“单盘切片 3mf”合并成一个多盘 3mf（Bambu Studio 格式）。

每个源文件必须恰好一盘（盘内可以有多个对象）。输出是**已切片的多盘 3mf**：
保留每盘的 gcode、缩略图、plate 映射；3D model 保持空壳，不再把对象塞进
build —— 这是 Bambu 自己导出的多盘 gcode.3mf 的做法，否则对象会全挤到盘 1。

这不是简单拼 ZIP：Bambu 靠 `Metadata/model_settings.config` 的 `<plate>`
和 `slice_info.config` 的 `<plate>` 认盘；少任何一个，多盘都会挤回盘 1。
"""

import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile

PLATE_FILES = (
    'Metadata/plate_{n}.gcode',
    'Metadata/plate_{n}.gcode.md5',
    'Metadata/plate_{n}.json',
    'Metadata/plate_{n}.png',
    'Metadata/plate_{n}_small.png',
    'Metadata/plate_no_light_{n}.png',
    'Metadata/top_{n}.png',
    'Metadata/pick_{n}.png',
)

PLATE_FILE_RE = re.compile(
    r'^(Metadata/)(plate_|plate_no_light_|top_|pick_)(\d+)'
    r'(\.(?:gcode|gcode\.md5|json|png))$'
)


def _uuid():
    return str(uuid.uuid4())


def _parse_objects(model_xml):
    """返回 [(obj_id, comp_id, path, comp_transform, item_transform)]。"""
    objs = []
    for m in re.finditer(
            r'<object id="(\d+)"[^>]*type="model">(.*?)</object>',
            model_xml, re.S):
        obj_id = int(m.group(1))
        body = m.group(2)
        cm = re.search(
            r'<component p:path="([^"]+)" objectid="(\d+)"[^>]*'
            r'transform="([^"]+)"', body)
        if not cm:
            continue
        objs.append((obj_id, int(cm.group(2)), cm.group(1),
                     cm.group(3)))
    build = []
    for m in re.finditer(
            r'<item objectid="(\d+)"[^>]*transform="([^"]+)"',
            model_xml):
        build.append((int(m.group(1)), m.group(2)))
    item_tr = {oid: tr for oid, tr in build}
    return [(oid, cid, path, ctr, item_tr.get(oid, ctr))
            for oid, cid, path, ctr in objs]


def _one_block(xml, tag):
    m = re.search(r'<%s\b.*?</%s>' % (tag, tag), xml, re.S)
    return m.group(0) if m else ''


def _remap_plate_paths(block, source_n, output_n):
    """把源盘号的文件引用换成合并后的第 N 盘。"""
    def sub(m):
        if int(m.group(2)) != int(source_n):
            return m.group(0)
        return '%s%d%s' % (m.group(1), output_n, m.group(3))
    return re.sub(
        r'(Metadata/(?:plate_no_light_|plate_|top_|pick_))(\d+)'
        r'(\.(?:png|gcode))',
        sub, block)


def _plate_block(xml, source_n, key):
    """返回指定盘号的 <plate> 块；缺失时退回第一块。"""
    blocks = re.findall(r'<plate\b.*?</plate>', xml, re.S)
    for block in blocks:
        if re.search(
                r'<metadata key="%s" value="%d"\s*/>'
                % (re.escape(key), int(source_n)),
                block):
            return block
    return blocks[0] if blocks else ''


def _replace_meta(block, key, fn):
    """替换 `<metadata key="key" value="X"/>` 的 X。"""
    return re.sub(
        r'(<metadata key="%s" value=")([^"]+)(")' % re.escape(key),
        lambda m: m.group(1) + str(fn(m.group(2))) + m.group(3), block)


def _set_meta(block, key, value):
    """写入 metadata；源盘没有这个键时补一条，保留原有盘映射。"""
    updated = _replace_meta(block, key, lambda _: value)
    if updated != block:
        return updated
    metadata = '    <metadata key="%s" value="%s"/>\n' % (
        key, str(value))
    if '</plate>' in updated:
        return updated.replace('</plate>', metadata + '  </plate>', 1)
    return updated


def merge_3mf(sources, out_path, plate_names=None):
    """sources: 单盘切片 3mf 路径列表；输出一个多盘 3mf。

    plate_names 可选，按输出盘顺序写入用户可读的盘名。切片源里的盘名
    往往仍是 Bambu 排列时的旧候选名，不能直接带到最终文件。
    """
    if not sources:
        raise ValueError('没有源 3mf')
    if plate_names is not None and len(plate_names) != len(sources):
        raise ValueError('盘名数量与切片盘数量不一致')
    tmp = tempfile.mkdtemp(prefix='merge3mf_')
    try:
        obj_xml = []
        build_xml = []
        obj_rels = []
        ms_objects = []
        ms_plates = []
        si_plates = []
        plate_jsons = []
        cut_objs = []
        filament_seq = {}
        project_settings = None
        slice_header = ''
        model_head = ''
        obj_id = 0
        part_id = 0
        identify_id = 0
        plate_obj_id = 1000
        cut_id = 0

        for plate_n, src in enumerate(sources, 1):
            with zipfile.ZipFile(src) as z:
                names = set(z.namelist())
                model_xml = z.read('3D/3dmodel.model').decode('utf-8')
                if not model_head:
                    model_head = re.search(
                        r'(<model\b.*?<resources>)', model_xml, re.S).group(1)
                objs = _parse_objects(model_xml)

                ms_src = z.read('Metadata/model_settings.config').decode('utf-8')
                si_src = z.read('Metadata/slice_info.config').decode('utf-8')
                gcode_plates = sorted({
                    int(m.group(1))
                    for name in names
                    if (m := re.match(
                        r'Metadata/plate_(\d+)\.gcode$', name))
                })
                if not gcode_plates:
                    raise ValueError('%s: 缺少盘 G-code' % src)
                # Bambu 对候选工程第 2/3 盘切片时，导出的 gcode 文件名仍
                # 使用原始盘号。每个输入必须只含一张盘，按真实盘号取
                # 对应的 gcode、缩略图和盘映射，不能假定它一定叫 plate_1。
                if len(gcode_plates) != 1:
                    raise ValueError(
                        '%s: 预期单盘切片，实际含盘 %s'
                        % (src, ','.join(map(str, gcode_plates))))
                source_plate = gcode_plates[0]
                ms_plate = _plate_block(
                    ms_src, source_plate, 'plater_id')
                si_plate = _plate_block(
                    si_src, source_plate, 'index')
                if not ms_plate or not si_plate:
                    raise ValueError('%s: 缺少盘映射' % src)
                # 这是“已切片多盘”文件：盘内容由 plate_N.gcode 决定，
                # 3D 对象不再塞进 build（否则 Bambu 会把所有对象都摆到盘 1）。
                ms_plate = re.sub(r'<model_instance>.*?</model_instance>',
                                  '', ms_plate, flags=re.S)

                # 源 identify_id 可能在 model_settings 和 slice_info 两处出现；
                # 统一映射，保证两处仍然指向同一个对象实例。
                old_ids = re.findall(
                    r'<metadata key="identify_id" value="(\d+)"', ms_plate)
                old_ids += re.findall(
                    r'<object identify_id="(\d+)"', si_plate)
                id_map = {}
                for old in old_ids:
                    if old not in id_map:
                        identify_id += 1
                        id_map[old] = identify_id

                # model_settings 的盘映射：盘号 + 每盘自己的 gcode/缩略图
                block = _remap_plate_paths(
                    ms_plate, source_plate, plate_n)
                block = _replace_meta(block, 'plater_id', lambda _: plate_n)
                if plate_names is not None:
                    block = _set_meta(
                        block, 'plater_name', plate_names[plate_n - 1])
                ms_plates.append(block)

                # slice_info 的盘映射
                block = re.sub(
                    r'(<metadata key="index" value=")\d+(")',
                    lambda m: m.group(1) + str(plate_n) + m.group(2),
                    si_plate, 1)
                block = re.sub(
                    r'(<object identify_id=")(\d+)(")',
                    lambda m: m.group(1) + str(id_map.get(m.group(2),
                                                           m.group(2)))
                    + m.group(3), block)
                block = re.sub(
                    r'(<object identify_id="\d+" name=")[^"]*(")',
                    lambda mm: mm.group(1) + 'plate_%d.stl' % plate_n
                    + mm.group(2), block)
                si_plates.append(block)

                # 每盘的缩略图 / gcode / json 等文件：源盘 1 → 目标盘 N
                for pat in PLATE_FILES:
                    old = pat.format(n=source_plate)
                    if old not in names:
                        continue
                    new = pat.format(n=plate_n)
                    with open(os.path.join(
                            tmp, os.path.basename(new)), 'wb') as f:
                        f.write(z.read(old))

                # 这些是 Bambu 的可选预览/统计元数据。某些由 CLI 生成的
                # 单盘切片只带 gcode、md5、缩略图和盘映射，不带 plate JSON；
                # 它们不影响打印，不能因此拒绝整批已切好的盘。
                source_json = 'Metadata/plate_%d.json' % source_plate
                if source_json in names:
                    pj = json.loads(z.read(source_json))
                    for o in pj.get('bbox_objects', []):
                        plate_obj_id += 1
                        o['id'] = plate_obj_id
                        o['name'] = 'plate_%d.stl' % plate_n
                    plate_jsons.append((plate_n, pj))

                if 'Metadata/cut_information.xml' in names:
                    cut = z.read(
                        'Metadata/cut_information.xml').decode('utf-8')
                    for m in re.finditer(
                            r'<object id="(\d+)">(.*?)</object>',
                            cut, re.S):
                        cut_id += 1
                        cut_objs.append(
                            ' <object id="%d">%s</object>'
                            % (cut_id, m.group(2)))

                if 'Metadata/filament_sequence.json' in names:
                    fs = json.loads(
                        z.read('Metadata/filament_sequence.json'))
                    filament_seq['plate_%d' % plate_n] = fs.get(
                        'plate_%d' % source_plate, {})

                if project_settings is None:
                    project_settings = z.read(
                        'Metadata/project_settings.config')
                if not slice_header:
                    hm = re.search(r'(<config>.*?)(<plate>)', si_src, re.S)
                    slice_header = hm.group(1) if hm else '<config>\n'

        # 3dmodel.model：已切片的盘不需要 3D 对象；空 resources/build
        # 和 Bambu 自己的多盘 gcode.3mf 一致（盘内容看 plate_N.gcode）。
        model = model_head + '\n </resources>\n <build/>\n</model>\n'
        with open(os.path.join(tmp, 'model.model'), 'w',
                  encoding='utf-8') as f:
            f.write(model)

        rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/'
                'package/2006/relationships">\n</Relationships>\n')
        with open(os.path.join(tmp, '3dmodel.model.rels'), 'w',
                  encoding='utf-8') as f:
            f.write(rels)

        # model_settings：每盘 + assemble（没有 3D 对象）
        ms_xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
                  + '\n'.join(ms_plates) + '\n'
                  '  <assemble>\n  </assemble>\n</config>\n')
        with open(os.path.join(tmp, 'model_settings.config'), 'w',
                  encoding='utf-8') as f:
            f.write(ms_xml)

        # model_settings.rels：每盘一根 gcode 关系
        ms_rels = ['<?xml version="1.0" encoding="UTF-8"?>',
                   '<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships">']
        for n in range(1, len(sources) + 1):
            ms_rels.append(
                ' <Relationship Target="/Metadata/plate_%d.gcode" '
                'Id="rel-%d" Type="http://schemas.bambulab.com/package/'
                '2021/gcode"/>' % (n, n))
        ms_rels.append('</Relationships>')
        with open(os.path.join(tmp, 'model_settings.config.rels'), 'w',
                  encoding='utf-8') as f:
            f.write('\n'.join(ms_rels) + '\n')

        si_xml = slice_header + '\n'.join(si_plates) + '\n</config>\n'
        with open(os.path.join(tmp, 'slice_info.config'), 'w',
                  encoding='utf-8') as f:
            f.write(si_xml)

        for n, pj in plate_jsons:
            with open(os.path.join(tmp, 'plate_%d.json' % n), 'w',
                      encoding='utf-8') as f:
                json.dump(pj, f, ensure_ascii=False)
        with open(os.path.join(tmp, 'filament_sequence.json'), 'w',
                  encoding='utf-8') as f:
            json.dump(filament_seq, f, ensure_ascii=False)
        with open(os.path.join(tmp, 'cut_information.xml'), 'w',
                  encoding='utf-8') as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<objects>\n'
                    + '\n'.join(cut_objs) + '\n</objects>\n')

        with zipfile.ZipFile(sources[0]) as z:
            for n in ('[Content_Types].xml', '_rels/.rels'):
                with open(os.path.join(tmp, os.path.basename(n)), 'wb') as f:
                    f.write(z.read(n))

        with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(tmp):
                for fn in files:
                    full = os.path.join(root, fn)
                    if fn == 'model.model':
                        arc = '3D/3dmodel.model'
                    elif fn == '3dmodel.model.rels':
                        arc = '3D/_rels/3dmodel.model.rels'
                    elif fn.startswith('object_'):
                        arc = '3D/Objects/' + fn
                    elif fn == 'model_settings.config.rels':
                        arc = 'Metadata/_rels/model_settings.config.rels'
                    elif fn == '[Content_Types].xml':
                        arc = fn
                    elif fn == '.rels':
                        arc = '_rels/.rels'
                    elif (fn.startswith(('plate_', 'top_', 'pick_'))
                          or fn in ('filament_sequence.json',
                                    'cut_information.xml',
                                    'model_settings.config',
                                    'slice_info.config',
                                    'project_settings.config')):
                        arc = 'Metadata/' + fn
                    else:
                        arc = fn
                    z.write(full, arc)
        if project_settings is not None:
            with zipfile.ZipFile(out_path, 'a') as z:
                z.writestr('Metadata/project_settings.config',
                           project_settings)
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def split_plate_sources(source, out_dir):
    """把一个多盘 G-code 3MF拆成多个单盘 3MF。

    输出仍保留原始 3D model 和工程配置，只筛选指定盘号的 G-code、
    缩略图和 plate JSON，并把文件序号改成 1。这样后续可以继续交给
    ``merge_3mf`` 按新的 16 盘上限重新分组，而不复制任何 G-code。
    """
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        plate_numbers = sorted({
            int(match.group(1))
            for name in names
            if (match := re.match(
                r'Metadata/plate_(\d+)\.gcode$', name))
        })
        if not plate_numbers:
            raise ValueError('%s: 缺少盘 G-code' % source)
        if len(plate_numbers) == 1:
            return [(plate_numbers[0], source)]

        stem = re.sub(
            r'[^\w.-]+', '_',
            os.path.splitext(os.path.basename(source))[0])[:48] or 'plate'
        result = []
        for plate_number in plate_numbers:
            destination = os.path.join(
                out_dir, '%s_plate_%03d.gcode.3mf'
                % (stem, plate_number))
            with zipfile.ZipFile(
                    destination, 'w', zipfile.ZIP_DEFLATED) as output:
                for name in names:
                    match = PLATE_FILE_RE.match(name)
                    if match:
                        source_plate = int(match.group(3))
                        if source_plate != plate_number:
                            continue
                        name = (
                            match.group(1) + match.group(2)
                            + '1' + match.group(4)
                        )
                    output.writestr(name, archive.read(name))
            result.append((plate_number, destination))
        return result
