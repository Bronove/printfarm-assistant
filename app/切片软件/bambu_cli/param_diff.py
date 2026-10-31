# -*- coding: utf-8 -*-
"""对比切片文件里的实际参数与预设默认值，生成“参数改动对照”。

切片文件（.gcode.3mf）里的 Metadata/project_settings.config 保存了本次
切片的全部生效参数；本模块把它和所选工艺预设的默认值比较，输出：
  <名字>_参数改动.txt   —— 文字对照表
  <名字>_参数改动.png   —— 改动高亮卡片（模仿 Bambu 的橙色修改标记）
"""

import json
import os
import sys
import zipfile

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flatten_presets  # noqa: E402

# key -> (中文名, Bambu 页签, 值显示)
PARAM_INFO = {
    'layer_height': ('层高', '质量'),
    'initial_layer_print_height': ('首层层高', '质量'),
    'line_width': ('线宽', '质量'),
    'outer_wall_line_width': ('外墙线宽', '质量'),
    'inner_wall_line_width': ('内墙线宽', '质量'),
    'top_surface_line_width': ('顶面线宽', '质量'),
    'initial_layer_line_width': ('首层线宽', '质量'),
    'seam_position': ('接缝位置', '质量'),
    'ironing_type': ('熨烫类型', '质量'),
    'ironing_flow': ('熨烫流量', '质量'),
    'wall_generator': ('墙生成器', '质量'),
    'wall_loops': ('墙层数', '强度'),
    'sparse_infill_density': ('填充密度', '强度'),
    'sparse_infill_pattern': ('填充图案', '强度'),
    'internal_solid_infill_pattern': ('内部实心填充', '强度'),
    'sparse_infill_line_width': ('填充线宽', '强度'),
    'top_shell_layers': ('顶部壳层数', '强度'),
    'bottom_shell_layers': ('底部壳层数', '强度'),
    'infill_direction': ('填充方向', '强度'),
    'enable_support': ('开启支撑', '支撑'),
    'support_type': ('支撑类型', '支撑'),
    'support_style': ('支撑样式', '支撑'),
    'support_threshold_angle': ('支撑阈值角度', '支撑'),
    'support_on_build_plate_only': ('支撑仅打印板', '支撑'),
    'brim_type': ('裙边类型', '其他'),
    'brim_width': ('裙边宽度', '其他'),
    'skirt_loops': ('裙边圈数', '其他'),
    'raft_layers': ('底板层数', '其他'),
    'print_sequence': ('打印顺序', '其他'),
    'enable_prime_tower': ('擦料塔', '其他'),
    'outer_wall_speed': ('外墙速度', '速度'),
    'inner_wall_speed': ('内墙速度', '速度'),
    'sparse_infill_speed': ('填充速度', '速度'),
    'initial_layer_speed': ('首层速度', '速度'),
    'travel_speed': ('移动速度', '速度'),
}

VALUE_CN = {
    'sparse_infill_pattern': {
        'grid': '网格', 'honeycomb': '蜂窝', '3dhoneycomb': '3D蜂窝',
        'gyroid': '螺旋', 'line': '直线', 'concentric': '同心',
        'triangles': '三角形', 'cubic': '立方体', 'adaptivecubic': '自适应立方',
        'crosszag': '交叉之字', 'zig-zag': '之字形', 'lightning': '闪电',
    },
    'internal_solid_infill_pattern': {
        'monotonic': '单调', 'monotonicline': '单调线', 'rectilinear': '直线',
        'alignedrectilinear': '对齐直线', 'grid': '网格',
    },
    'support_type': {'tree(auto)': '树状', 'normal(auto)': '普通'},
    'support_style': {'default': '默认', 'tree_slim': '细树',
                      'tree_hybrid': '混合树', 'tree_strong': '粗树',
                      'snug': '贴合', 'organic': '有机'},
    'ironing_type': {'no ironing': '关闭', 'top': '仅顶面', 'topmost': '仅最顶面',
                     'solid': '全部实心'},
    'seam_position': {'aligned': '对齐', 'nearest': '最近', 'back': '背面',
                      'random': '随机'},
    'brim_type': {'auto_brim': '自动', 'outer_only': '仅外侧',
                  'inner_only': '仅内侧', 'outer_and_inner': '内外侧',
                  'no_brim': '关闭'},
    'print_sequence': {'by layer': '逐层', 'by object': '逐件'},
    'wall_generator': {'classic': '经典', 'arachne': 'Arachne'},
    'line_width': {}, 'wall_loops': {},
}


def _fmt_value(key, value):
    if isinstance(value, (list, tuple)):
        return ', '.join(str(v) for v in value)
    text = str(value)
    mapping = VALUE_CN.get(key)
    if mapping:
        low = text.strip().lower()
        if low in mapping:
            return mapping[low]
    if key in ('enable_support', 'support_on_build_plate_only',
               'enable_prime_tower'):
        return '开' if text in ('1', 'true', 'True') else '关'
    return text


def _norm(value):
    if isinstance(value, (list, tuple)):
        return ','.join(str(v).strip() for v in value)
    if isinstance(value, float):
        return f'{value:g}'
    return str(value).strip()


def _font(size):
    for name in ('msyh.ttc', 'msyhbd.ttc', 'simhei.ttf'):
        p = os.path.join(r'C:\Windows\Fonts', name)
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def read_effective(gcode_3mf):
    with zipfile.ZipFile(gcode_3mf) as z:
        data = z.read('Metadata/project_settings.config').decode('utf-8')
    return json.loads(data)


def collect_changes(gcode_3mf, profiles_root, process_name):
    """返回 [(key, cn, baseline, actual, tab)]，只含被改动的参数。"""
    try:
        effective = read_effective(gcode_3mf)
    except (OSError, KeyError, ValueError):
        return []
    baseline = {}
    if process_name:
        try:
            baseline = flatten_presets.flatten_preset(
                profiles_root, 'process', process_name) or {}
        except Exception:
            baseline = {}
    changes = []
    for key, (cn, tab) in PARAM_INFO.items():
        if key not in effective:
            continue
        if key not in baseline:
            continue
        if _norm(effective[key]) != _norm(baseline[key]):
            changes.append((key, cn, _fmt_value(key, baseline[key]),
                            _fmt_value(key, effective[key]), tab))
    return changes


def write_report(gcode_3mf, profiles_root, process_name, log=print,
                 subdir='_报告'):
    """写 参数改动.txt / 参数改动.png，返回 (txt, png, changes)。

    ★ 2026-10-16（用户：「切片出来 4 个文件，太多了，不方便用户管理，
      只要一个切片好的 .3mf」）：这两个文件**不再和 .3mf 并排放在输出目录根上**，
      而是收进输出目录下的 `_报告\\` 子文件夹 —— 用户打开输出目录只看到 .3mf，
      附属文件还在（以前明确要过"参数改动要一眼可见"），只是不碍事了。
    """
    changes = collect_changes(gcode_3mf, profiles_root, process_name)
    base = os.path.splitext(gcode_3mf)[0]
    if base.lower().endswith('.gcode'):
        base = base[:-6]
    if subdir:
        out_dir = os.path.join(os.path.dirname(gcode_3mf), subdir)
        try:
            os.makedirs(out_dir, exist_ok=True)
            base = os.path.join(out_dir, os.path.basename(base))
        except OSError:
            pass                      # 建不出来就退回原地，别因此丢报告
    txt_path = base + '_参数改动.txt'
    png_path = base + '_参数改动.png'
    lines = [
        f'参数改动对照：{os.path.basename(gcode_3mf)}',
        f'基准预设：{process_name}',
        '=' * 56,
    ]
    if changes:
        for _, cn, old, new, tab in changes:
            lines.append(f'{cn}（{tab}）：{old} → {new}')
    else:
        lines.append('本次切片没有改动预设参数（全部为预设默认值）。')
    lines += ['', '在 Bambu Studio 中按括号里的页签查找对应项。']
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    # 渲染卡片
    title_font = _font(30)
    head_font = _font(20)
    row_font = _font(22)
    small_font = _font(17)
    n = max(1, len(changes))
    W = 880
    H = 190 + n * 46
    im = Image.new('RGB', (W, H), (250, 250, 249))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([18, 16, W - 18, H - 16], radius=16,
                        fill=(255, 255, 255), outline=(224, 228, 232), width=2)
    d.text((46, 34), '拓竹助手 · 参数改动对照', font=title_font,
           fill=(30, 38, 46))
    d.text((46, 76), f'基准：{process_name or "-"}   '
                     f'（橙字 = 与预设不同，右侧为 Bambu 页签）',
           font=small_font, fill=(120, 130, 138))
    y = 118
    d.text((46, y), '参数', font=head_font, fill=(120, 130, 138))
    d.text((260, y), '预设值', font=head_font, fill=(120, 130, 138))
    d.text((460, y), '实际值', font=head_font, fill=(120, 130, 138))
    d.text((690, y), '位置', font=head_font, fill=(120, 130, 138))
    y += 34
    if changes:
        for _, cn, old, new, tab in changes:
            d.text((46, y), cn, font=row_font, fill=(230, 126, 34))
            d.text((260, y), str(old), font=row_font, fill=(90, 98, 106))
            d.text((460, y), str(new), font=row_font, fill=(230, 126, 34))
            d.text((690, y), tab, font=row_font, fill=(90, 98, 106))
            y += 46
    else:
        d.text((46, y), '没有改动，全部使用预设默认值', font=row_font,
               fill=(90, 98, 106))
    im.save(png_path)
    if changes:
        log('参数改动：' + '；'.join(
            f'{cn} {old}→{new}（{tab}）' for _, cn, old, new, tab in changes))
    else:
        log('参数改动：无（全部为预设默认值）')
    return txt_path, png_path, changes
