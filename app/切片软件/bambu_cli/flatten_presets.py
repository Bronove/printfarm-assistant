#!/usr/bin/env python3
"""Flatten Bambu Lab preset inheritance chains into full config files that the
Bambu Studio CLI actually honors, and lay them out next to their parent chain
files (the CLI resolves parents by name in the same directory).

Why this is needed: Bambu Studio's --load-settings accepts system preset JSON
files, but the CLI does NOT resolve the `inherits` chain, so a leaf preset such
as "0.20mm Standard @BBL X1C" slices with default settings. A full
config with every key explicit fixes that, provided:
  * the leaf's own `inherits` and `include` keys are kept,
  * the merge order is parents -> include files -> leaf (leaf wins),
  * the config sits in a directory containing its parent chain files.

Usage:
    python flatten_presets.py --out-dir <dir>
        [--profiles-root "D:\\Bambu Studio\\resources\\profiles\\BBL"]
        [--machine "Bambu Lab P1S 0.4 nozzle"]
        [--process "0.20mm Standard @BBL X1C"]
        [--filament "Bambu PLA Basic @BBL P1S 0.4 nozzle"]
"""

import argparse
import hashlib
import json
import os
import shutil


def load(profiles_root, typ, name):
    with open(
        os.path.join(profiles_root, typ, name + '.json'), encoding='utf-8'
    ) as f:
        return json.load(f)


def resolve_names(profiles_root, typ, name, seen=None):
    """Return [root, ..., parent, leaf] names, including include templates."""
    seen = seen or set()
    if name in seen:
        return []
    seen.add(name)
    d = load(profiles_root, typ, name)
    names = [name]
    for incname in (d.get('include') or []):
        names.append(incname)
    if d.get('inherits'):
        names = resolve_names(profiles_root, typ, d['inherits'], seen) + names
    return names


def flatten_preset(profiles_root, typ, name):
    leaf = load(profiles_root, typ, name)
    chain_names = resolve_names(profiles_root, typ, name)
    parents = chain_names[: chain_names.index(name)]
    merged = {}
    for pname in parents:
        d = load(profiles_root, typ, pname)
        for k, v in d.items():
            if k != 'inherits':
                merged[k] = v
    for incname in (leaf.get('include') or []):
        for k, v in load(profiles_root, typ, incname).items():
            if k != 'inherits':
                merged[k] = v
    for k, v in leaf.items():
        if k != 'inherits':
            merged[k] = v
    # ★ 别硬取 leaf['inherits']：**用户自建的预设没有父预设**，没有这个键，
    #   以前直接 KeyError: 'inherits' → 整个切片崩掉（真实用户反馈的启动失败）。
    #   没有父预设就是"完整配置"，这时候把 inherits 去掉反而是对的。
    if leaf.get('inherits'):
        merged['inherits'] = leaf['inherits']
    else:
        merged.pop('inherits', None)
    if leaf.get('include'):
        merged['include'] = leaf['include']
    return merged


def apply_overrides(cfg, overrides):
    """Apply 'key=value;key=value' overrides to a flattened config.

    Values are stored as strings, matching Bambu preset JSON conventions
    (e.g. layer_height=0.2, sparse_infill_density=50%, enable_support=1).
    """
    if not overrides:
        return cfg
    for item in overrides.split(';'):
        item = item.strip()
        if not item:
            continue
        if '=' not in item:
            raise ValueError(
                f'bad override {item!r}: expected key=value (separate with ;)'
            )
        k, v = item.split('=', 1)
        cfg[k.strip()] = v.strip()
    return cfg


LAYER_ORDER = ('process', 'filament', 'machine')


def route_overrides(cfgs, overrides):
    """把 key=value 按"这个键原本属于哪一层"落位。

    不用维护中英对照表：扁平化之后每层的配置里都含自己的全部键，
    所以 `k in cfgs[layer]` 就是精确的路由判断。
    认不出来的键（用户自己造的）默认给 process。
    返回 {层: 生效的键列表}。
    """
    landed = {t: [] for t in LAYER_ORDER}
    if not overrides:
        return landed
    for item in overrides.split(';'):
        item = item.strip()
        if not item:
            continue
        if '=' not in item:
            raise ValueError(
                f'bad override {item!r}: expected key=value (separate with ;)'
            )
        k, v = (x.strip() for x in item.split('=', 1))
        for layer in LAYER_ORDER:
            if k in cfgs[layer]:
                cfgs[layer][k] = v
                landed[layer].append(k)
                break
        else:
            cfgs['process'][k] = v
            landed['process'].append(k)
    return landed


def custom_process_name(overrides):
    """Build a distinct preset name from key overrides.

    Bambu Studio's GUI shows the preset NAME from the 3mf, so an overridden
    config must not keep the stock preset name (e.g. "0.12mm High Quality")
    or the GUI will display the stock preset's nominal values instead of the
    values actually used for slicing. Keys are deduplicated so the name shows
    the effective (last) value for each key.
    """
    kv = {}
    for item in (overrides or '').split(';'):
        item = item.strip()
        if not item or '=' not in item:
            continue
        k, v = (x.strip() for x in item.split('=', 1))
        kv[k] = v
    parts = []
    for k, v in kv.items():
        if k == 'layer_height':
            parts.append(v + 'mm')
        elif k == 'sparse_infill_density':
            parts.append(v + ' infill')
        elif k == 'sparse_infill_pattern' and v not in ('gyroid', 'auto'):
            parts.append(v)
        elif k in ('support_type', 'support_style') and v not in ('0', 'none', 'normal(auto)'):
            parts.append('tree support' if 'tree' in v.lower() else v)
        elif k == 'support_on_build_plate_only' and v == '1':
            parts.append('plate-only')
    return 'Codex ' + ' '.join(parts) if parts else 'Codex custom'


# ---- Bambu 对"100% 填充 + 图案"的组合限制 ---------------------------------
# 实测 2026-10-15（Bambu Studio 02.07.01 / P2S 预设，逐个图案跑 CLI）：
#   密度 100% 时只有这三种图案能被接受：concentric / alignedrectilinear / zig-zag
#   grid / gyroid / honeycomb / cubic / line / triangles / crosshatch / octet /
#   adaptivecubic / 3dhoneycomb / lightning / supportcubic 一律被拒，报
#       Param values in 3mf/config error:
#       sparse_infill_pattern: grid doesn't work at 100% density
#   而且**连 --orient 那一步都过不去**，用户看到的是"整个切片失败"。
#   99% 及以下没有任何限制（顺带：monotonic / monotonicline 这个名字
#   在这个版本里根本不认，无论多少密度都失败）。
SOLID_OK_PATTERNS = ('concentric', 'alignedrectilinear', 'zig-zag')
# 100% 时换成哪个：对齐直线 = 最接近 grid 的"实心直线"，
# 强度/表面都稳，也是大家平时 100% 填充用的那个
SOLID_FALLBACK = 'alignedrectilinear'


def fix_solid_infill(cfg):
    """把"100% 填充 + 不兼容图案"改成能跑的组合；返回说明（没改就 None）。

    为什么放在这里：不管是用户说"填充100%"、我们的默认覆盖项，还是他自己
    在 Bambu 里挑的预设带进来的 100%，最后都会落到这份**扁平化后的配置**上。
    在这一处兜住，单模型 / 批量 / 克隆三条路都不会再踩。
    """
    dens = str(cfg.get('sparse_infill_density', '')).strip().rstrip('%')
    try:
        full = float(dens) >= 100
    except ValueError:
        return None
    if not full:
        return None
    pat = str(cfg.get('sparse_infill_pattern', '')).strip()
    if pat in SOLID_OK_PATTERNS:
        return None
    cfg['sparse_infill_pattern'] = SOLID_FALLBACK
    return ('填充 100%%：Bambu 不接受图案「%s」，已自动换成「%s」'
            % (pat or '(跟随预设)', SOLID_FALLBACK))


def fix_filament_indices(cfg):
    """把预设里的耗材占位编号 0 改成 CLI 接受的 1。

    Bambu 公共工艺预设会把 wall_filament / solid_infill_filament 等写成 0。
    图形界面会把它解释成“默认耗材”，但 CLI 校验按 1 开始计数，直接报：
        ... : 0 not in range [1, 2147483647]
    本程序每次只加载一种耗材，所以所有非正编号都统一落到 1。
    """
    changed = []
    for key, value in list(cfg.items()):
        if not key.endswith('_filament'):
            continue
        try:
            index = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if index <= 0:
            cfg[key] = '1'
            changed.append(key)
    return changed


def _with_pattern(overrides, pat):
    """把覆盖项串里的 sparse_infill_pattern 换成 pat（没有就补上）。"""
    kv = [p for p in str(overrides or '').split(';') if p.strip()]
    out = []
    seen = False
    for p in kv:
        if p.split('=')[0].strip() == 'sparse_infill_pattern':
            out.append('sparse_infill_pattern=%s' % pat)
            seen = True
        else:
            out.append(p)
    if not seen:
        out.append('sparse_infill_pattern=%s' % pat)
    return ';'.join(out)


def prepare_preset_root(
    profiles_root, out_root, machine, process, filament, process_overrides=None
):
    """Copy the full preset chain into out_root and write flattened configs.

    Returns dict with machine/process/filament paths to pass to
    --load-settings / --load-filaments.
    """
    os.makedirs(out_root, exist_ok=True)
    paths = {}
    # 先把三层的扁平化配置都算出来，再统一路由覆盖项——
    # 覆盖项要能改 filament / machine 的参数，不能只认 process
    fulls = {}
    for typ, name in (
        ('machine', machine),
        ('process', process),
        ('filament', filament),
    ):
        fulls[typ] = flatten_preset(profiles_root, typ, name)
    landed = route_overrides(fulls, process_overrides)
    filament_fixes = fix_filament_indices(fulls['process'])
    if filament_fixes:
        print('INFO: 耗材占位编号 0 → 1：' + '、'.join(filament_fixes))
    # 100% 填充 + grid/gyroid 这类组合会被 Bambu 直接拒（见 fix_solid_infill 注释），
    # 先修配置再写文件 —— 顺便把"覆盖项字符串"也改掉，否则下面拼出来的
    # 工艺名（会写进 3mf 元数据）还写着 grid，跟实际用的图案对不上。
    _note = fix_solid_infill(fulls['process'])
    if _note:
        print('INFO:', _note)
        if process_overrides:
            process_overrides = _with_pattern(process_overrides, SOLID_FALLBACK)
    if process_overrides:
        print('OVERRIDES:', ' '.join(
            '%s:%d' % (t, len(landed[t])) for t in LAYER_ORDER
            if landed[t]))
    for typ, name in (
        ('machine', machine),
        ('process', process),
        ('filament', filament),
    ):
        sub = os.path.join(out_root, typ)
        os.makedirs(sub, exist_ok=True)
        for pname in resolve_names(profiles_root, typ, name):
            shutil.copy2(
                os.path.join(profiles_root, typ, pname + '.json'),
                os.path.join(sub, pname + '.json'),
            )
        full = fulls[typ]
        if typ == 'process' and process_overrides:
            full['name'] = custom_process_name(process_overrides)
            full['setting_id'] = 'codex_' + hashlib.md5(
                process_overrides.encode('utf-8')
            ).hexdigest()[:8]
        fname = name + '_full.json'
        with open(os.path.join(sub, fname), 'w', encoding='utf-8') as f:
            json.dump(full, f, ensure_ascii=False)
        paths[typ] = os.path.join(sub, fname)
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', required=True)
    ap.add_argument(
        '--profiles-root',
        required=True,
    )
    ap.add_argument('--machine', default='Bambu Lab P1S 0.4 nozzle')
    ap.add_argument('--process', default='0.20mm Standard @BBL X1C')
    ap.add_argument('--filament', default='Bambu PLA Basic @BBL P1S 0.4 nozzle')
    ap.add_argument(
        '--process-override',
        help='process overrides as key=value;key=value '
        '(e.g. layer_height=0.2;sparse_infill_density=50%;enable_support=1)',
    )
    args = ap.parse_args()
    paths = prepare_preset_root(
        args.profiles_root,
        args.out_dir,
        args.machine,
        args.process,
        args.filament,
        process_overrides=args.process_override,
    )
    for typ, path in paths.items():
        cfg = json.load(open(path, encoding='utf-8'))
        print(typ, '->', path)
        if typ == 'process':
            print(
                '  layer_height=%s infill=%s walls=%s'
                % (cfg.get('layer_height'), cfg.get('sparse_infill_density'), cfg.get('wall_loops'))
            )
        elif typ == 'machine':
            print(
                '  printer=%s printable_area=%s'
                % (cfg.get('printer_model'), cfg.get('printable_area'))
            )
        else:
            print(
                '  type=%s density=%s temp=%s'
                % (cfg.get('filament_type'), cfg.get('filament_density'), cfg.get('nozzle_temperature'))
            )


if __name__ == '__main__':
    main()
