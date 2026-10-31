#!/usr/bin/env python3
"""End-to-end Bambu Studio CLI slicing（单模型 + 批量 + 支撑感知摆盘）。

单模型：
    python slice_bambu.py <model.stl> [--out out.gcode.3mf] [...]

批量（--batch <文件夹>）：
    python slice_bambu.py --batch <folder> --out-dir <dir> [--pack 1] [...]
    - 递归扫描 .stl/.3mf/.stp/.step，逐个切片
    - 自动重试链：关闭定向 / 调整 STEP 网格
    - 每个模型都用 Bambu 自带自动朝向（主体零件和明确关闭时除外）
    - --pack 1 开启支撑感知摆盘：--tight 1 时按模型本体占地紧凑装箱，
      支撑之间可重叠、只保证不压本体；整盘校验不过自动回退单模型一板
    - 结束后输出 切片报告.txt

默认配方（打印农场）：P1S 0.4 / 纹理钢板 / PLA / 0.2mm / 15% 网格 /
树状支撑（仅打印板）/ 自动定向。--process-override 覆盖默认。
"""

import argparse
import copy
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zipfile

for _stream in (sys.stdout, sys.stderr):
    try:
        # 父界面通过管道读这些阶段标记。管道默认是整块缓冲，若不强制逐行
        # flush，MODEL ANALYSIS / RUN / OUTPUT 等消息会等进程结束才一起出现，
        # 用户看到的进度就会从 0% 直接跳到 100%。
        _stream.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_stl  # noqa: E402
import clean_stl  # noqa: E402
import flatten_presets  # noqa: E402
import footprint  # noqa: E402
import merge_stl  # noqa: E402
import merge_3mf  # noqa: E402
import min_support  # noqa: E402
import pack  # noqa: E402
import param_diff  # noqa: E402
import repair_mesh  # noqa: E402
import seam_profile  # noqa: E402
import unpack_3mf  # noqa: E402


DEFAULT_PROCESS_OVERRIDES = (
    'layer_height=0.2;'
    'sparse_infill_density=15%;'
    'sparse_infill_pattern=grid;'
    'enable_support=1;'
    'support_type=tree(auto);'
    'support_on_build_plate_only=1'
)

MODEL_EXTS = ('.stl', '.3mf', '.stp', '.step')
FIGURINE_BODY_MIN_RATIO = 0.60
FIGURINE_MAX_BODIES = 2


def enforce_figurine_mode(args):
    """复杂手办只保留普通支撑和普通摆盘。

    “手办模式”是独立于隐藏 Z 缝的页面模式。此时“最少支撑”和“最省空间”
    都可能为了省料或省盘改变零件方向，牺牲外观精度，因此两者强制关闭。
    工作台模式可以把隐藏 Z 缝与两个效率选项同时开启。
    """
    if not getattr(args, 'figurine_mode', 0):
        return []
    disabled = []
    if getattr(args, 'min_support', 0):
        args.min_support = 0
        disabled.append('最少支撑')
    if getattr(args, 'tight', 0):
        args.tight = 0
        disabled.append('最省空间')
    return disabled


def _stock_process_name(args):
    """本次切片所基于的原始工艺预设名（用于参数改动对照）。"""
    name = getattr(args, 'process', None)
    if name:
        return name
    try:
        return read_user_presets().get('process') or ''
    except Exception:
        return ''


def emit_param_diff(out_path, args, log=print):
    """在切片产物旁生成“参数改动.txt / 参数改动.png”。"""
    try:
        param_diff.write_report(out_path, args.profiles_root,
                                _stock_process_name(args), log=log)
    except Exception as e:  # 不因附图失败影响切片
        print(f'参数改动对照生成失败（{e}）')


class SliceError(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def protected_project_info(model):
    """多色/多材料 3MF 标记为受保护工程。"""
    if not str(model or '').lower().endswith('.3mf'):
        return None
    try:
        info = unpack_3mf.project_filament_info(model)
    except Exception:                                 # noqa: BLE001
        return None
    return info if info.get('multicolor') else None


def ensure_project_operation_safe(model, args, multiple=False):
    """受保护工程不允许经过会拆 STL、重排或克隆的破坏性路径。"""
    info = protected_project_info(model)
    if not info:
        return None
    conflicts = []
    if multiple:
        conflicts.append('多文件摆盘')
    if getattr(args, 'pack', 0):
        conflicts.append('自动摆盘')
    if getattr(args, 'tight', 0):
        conflicts.append('最省空间')
    if getattr(args, 'min_support', 0):
        conflicts.append('最少支撑')
    if getattr(args, 'clone', 1) and int(args.clone) > 1:
        conflicts.append('克隆')
    if conflicts:
        raise SliceError(
            '检测到多色/多材料 3MF，已拒绝%s。'
            '这类工程会保持原颜色、材料和零件绑定，不能拆 STL 重排；'
            '请关闭这些选项后按原工程切片。'
            % '、'.join(conflicts))
    return info


def _source_stat(path):
    try:
        stat = os.stat(path)
        return stat.st_size, stat.st_mtime_ns
    except OSError:
        return None


def _step_converter_command(src, dst, mesh_size):
    """Gmsh 由独立 GPL 进程提供，主程序不链接 Gmsh。"""
    if getattr(sys, 'frozen', False):
        converter = os.path.join(
            os.path.dirname(os.path.abspath(sys.executable)),
            'step_converter.exe',
        )
        if not os.path.isfile(converter):
            raise SliceError('STEP 转换组件缺失，请重新安装打印农场助手')
        return [
            converter, os.path.abspath(src), os.path.abspath(dst),
            '--mesh-size', str(mesh_size),
        ]

    converter = os.path.abspath(os.path.join(
        os.path.dirname(__file__), '..', '..', 'ui_v2',
        'step_converter.py'))
    if not os.path.isfile(converter):
        raise SliceError('找不到 STEP 转换组件 step_converter.py')
    return [
        sys.executable, converter, os.path.abspath(src), os.path.abspath(dst),
        '--mesh-size', str(mesh_size),
    ]


def convert_step_to_stl(src, dst, mesh_size=2.0):
    """通过独立进程把 STEP/STP 转成二进制 STL。"""
    command = _step_converter_command(src, dst, mesh_size)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=180,
            creationflags=0x08000000 if os.name == 'nt' else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SliceError('STEP 转换组件启动失败：%s' % str(exc)[:160]) from exc
    if result.returncode != 0 or not os.path.isfile(dst):
        detail = (result.stderr or result.stdout or '').strip()[-500:]
        raise SliceError(
            'STEP 转换失败：%s'
            % (detail or '转换组件没有生成 STL 文件'))


def _needs_admin(exe):
    """这个 exe 一启动就要管理员权限吗（是的就会失败成 WinError 740）。

    两个来源都得看，少看一个就查不出原因：
      ① 右键→属性→兼容性 里的"以管理员身份运行此程序" —— 记录在
         HKCU/HKLM 的 AppCompatFlags\\Layers，值是 RUNASADMIN；
      ② exe 自己清单里的 <requestedExecutionLevel level="requireAdministrator">。

    真实事故（用户 2026-10-09 的日志）：
        OSError: [WinError 740] 请求的操作需要提升。
        slice_bambu.py:511 slice_one -> subprocess.run
    就是被启动的那个程序要提权。用户当时只看到一串英文 traceback，
    根本不知道是"找错程序了"还是"该去掉右键里的管理员勾"。
    """
    try:
        import winreg
    except ImportError:
        winreg = None
    if winreg:
        key = (r'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
               r'\AppCompatFlags\Layers')
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, key) as k:
                    try:
                        v, _ = winreg.QueryValueEx(k, os.path.abspath(exe))
                    except OSError:
                        continue
                    if 'RUNASADMIN' in str(v).upper():
                        return True
            except OSError:
                continue
    # 清单：exe 里就带着 requireAdministrator 这串字。
    # 只扫前 4MB + 后 2MB（清单在资源段，正常 exe 都落在这两段里），
    # 免得为了一个判断把几百 MB 的 exe 整个读进内存。
    try:
        size = os.path.getsize(exe)
        with open(exe, 'rb') as f:
            blob = f.read(4 * 1024 * 1024)
            if size > len(blob):
                f.seek(max(0, size - 2 * 1024 * 1024))
                blob += f.read(2 * 1024 * 1024)
    except OSError:
        return False
    return b'requireAdministrator' in blob


def _admin_hint(exe):
    """把 WinError 740 翻成"哪个程序、为什么、去哪儿点"。"""
    return (
        '要启动的切片程序要求管理员权限（Windows 错误 740），没法直接调用：\n'
        f'  {exe}\n\n'
        '两种可能：\n'
        '  ① 这不是 Bambu Studio 主程序 —— 同门的其它拓竹软件有些是要管理员'
        '的（比如"拓竹农场服务器"的监控程序）；\n'
        '  ② 这个程序被设过"以管理员身份运行"。\n\n'
        '解决：右键这个 exe → 属性 → 兼容性 → 取消勾选"以管理员身份运行此程序"'
        ' → 确定，然后重开拓竹助手。\n'
        '（拓竹助手自己不需要管理员权限，平时也别用"以管理员身份运行"开它。）'
    )


def run_cli(cmd, **kw):
    """跑 Bambu Studio 命令行，把系统错误翻成人话。

    以前这里是裸的 subprocess.run：被启动的程序要提权就抛 OSError，一路冒到
    窗口上变成英文 traceback（用户 2026-10-09 就是这么被卡住的）。
    """
    try:
        return subprocess.run(cmd, **kw)
    except OSError as e:
        code = getattr(e, 'winerror', None)
        text = str(e)
        if code == 740 or '需要提升' in text or 'requires elevation' in text.lower():
            raise SliceError(_admin_hint(cmd[0])) from e
        if code == 2 or '找不到指定的文件' in text:
            raise SliceError(
                f'找不到切片程序：{cmd[0]}\n'
                '请确认 Bambu Studio 还在原来的位置（没被卸载或搬走）。') from e
        raise SliceError(f'启动切片程序失败：{text[:160]}\n  {cmd[0]}') from e


def explain_cli_failure(stdout, stderr, rc=None):
    """把 Bambu CLI 的报错翻成一句人话（认不出来返回 ''）。

    Bambu 拒绝一组参数时**不说"哪个设置该改"**，只吐一行
        Param values in 3mf/config error:
        sparse_infill_pattern: grid doesn't work at 100% density
    而界面上只截最后 600 字，用户看到的是一长串命令里夹着这行英文
    （2026-10-15 真实反馈）。这里把它单独捞出来说清楚。

    有的版本更狠：**一个字都不吐**，只返回退出码 -18（4294967278）。
    那就按退出码给个方向（rc 传进来就能认）。
    """
    text = (stderr or '') + '\n' + (stdout or '')
    m = re.search(r'Param values in[^\n]*error:\s*(.+)', text)
    if m:
        return 'Bambu 不接受这组参数：' + m.group(1).strip()
    for line in text.splitlines():
        low = line.lower()
        if "doesn't work at" in low or 'invalid value' in low:
            return 'Bambu 不接受这组参数：' + line.strip()
    if rc is not None and (rc & 0xFFFFFFFF) == 0xFFFFFFEE:
        return ('Bambu 退出码 -18：它不接受这组参数'
                '（最常见的坑是 100% 填充配 grid 图案）')
    return ''


BAMBU_EXE_NAMES = ('bambu-studio.exe', 'bambustudio.exe')


def _is_bambu_studio_exe(path):
    """像不像"真正的 Bambu Studio 主程序"。

    以前只判断卸载表里 DisplayName 带不带 Bambu，于是**同门程序也能被当成
    切片器**。本机实测：`C:\\Program Files\\Bambu Farm Manager Server\\
    Bambu Farm Manager Server Monitor.exe` 的清单就是 requireAdministrator，
    一启动必定 WinError 740，而报错里完全看不出是谁。
    现在按"文件名白名单 + 排除词"卡一道，再由 _needs_admin 排掉要提权的。
    """
    if not path or not os.path.isfile(path):
        return False
    if os.path.basename(path).lower() not in BAMBU_EXE_NAMES:
        return False
    low = os.path.normcase(os.path.abspath(path))
    for bad in ('uninstall', 'farm manager', 'monitor'):
        if bad in low:
            return False
    return True


def find_bambu_exe(notes=None):
    """Bambu Studio 主程序的完整路径；找不到返回 None。

    notes（可选 list）：把"看到过但没选"的候选记进去，出错时能说清原因。
    """
    def note(msg):
        if notes is not None:
            notes.append(msg)

    # ---- macOS ----
    # Mac 上 Bambu 是个 .app，可执行文件在 Contents/MacOS 里、
    # 预设目录在 Contents/Resources/profiles/BBL（下面 find_profiles_root 会用）。
    if sys.platform == 'darwin':
        for p in ('/Applications/BambuStudio.app/Contents/MacOS/BambuStudio',
                  os.path.expanduser(
                      '~/Applications/BambuStudio.app/Contents/MacOS/BambuStudio')):
            if os.path.isfile(p):
                return p
        w = shutil.which('BambuStudio') or shutil.which('bambu-studio')
        if w:
            return w
    try:
        import winreg
    except ImportError:
        winreg = None
    if winreg:
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in (
                r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
            ):
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        i = 0
                        while True:
                            try:
                                name = winreg.EnumKey(k, i)
                                i += 1
                            except OSError:
                                break
                            try:
                                with winreg.OpenKey(k, name) as sk:
                                    dn = str(winreg.QueryValueEx(
                                        sk, 'DisplayName')[0])
                                    if 'bambu' not in dn.lower():
                                        continue
                                    icon = winreg.QueryValueEx(
                                        sk, 'DisplayIcon')[0]
                                    cand = str(icon).split(',')[0].strip('"')
                                    if not _is_bambu_studio_exe(cand):
                                        note('卸载表里的「%s」不是 Bambu Studio '
                                             '主程序，跳过：%s' % (dn, cand))
                                        continue
                                    if _needs_admin(cand):
                                        note('「%s」要管理员权限（740 的来头），'
                                             '跳过：%s' % (dn, cand))
                                        continue
                                    return cand
                            except OSError:
                                continue
                except OSError:
                    pass
    for p in (
        r'C:\Program Files\Bambu Studio\bambu-studio.exe',
        r'D:\Bambu Studio\bambu-studio.exe',
    ):
        if _is_bambu_studio_exe(p):
            if _needs_admin(p):
                note('%s 被设成"以管理员身份运行"，跳过' % p)
                continue
            return p
    return None


def read_user_presets():
    # Windows 在 %APPDATA%\BambuStudio\，macOS 在
    # ~/Library/Application Support/BambuStudio/ —— 两边都要认，
    # 不然 Mac 上读不到用户选的机型/工艺，会退回默认值然后报"预设不存在"。
    if sys.platform == 'darwin':
        conf = os.path.expanduser(
            '~/Library/Application Support/BambuStudio/BambuStudio.conf')
    else:
        conf = os.path.join(os.environ.get('APPDATA', ''), 'BambuStudio',
                            'BambuStudio.conf')
    presets = {}
    if os.path.isfile(conf):
        text = open(conf, encoding='utf-8', errors='replace').read()
        m = re.search(r'"presets"\s*:\s*\{(.*?)\n\s*\}', text, re.S)
        if m:
            for key in ('machine', 'process'):
                mm = re.search(r'"%s"\s*:\s*"([^"]+)"' % key, m.group(1))
                if mm:
                    presets[key] = mm.group(1)
            fm = re.search(r'"filaments"\s*:\s*\[\s*"([^"]+)"', m.group(1))
            if fm:
                presets['filament'] = fm.group(1)
    return presets


def machine_plate_size(machine, profiles_root=None):
    """从机器预设读取打印板尺寸，返回 (宽, 高)，如 H2S (340, 320)。"""
    root = profiles_root or find_profiles_root()

    def parse_area(area):
        pts = []
        if isinstance(area, (list, tuple)):
            for item in area:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    try:
                        pts.append((float(item[0]), float(item[1])))
                    except (TypeError, ValueError):
                        pass
                elif isinstance(item, str) and 'x' in item:
                    try:
                        pts.append(tuple(float(v) for v in item.split('x')[:2]))
                    except ValueError:
                        pass
        elif isinstance(area, str):
            for p in area.replace(',', ' ').split():
                if 'x' in p:
                    try:
                        pts.append(tuple(float(v) for v in p.split('x')[:2]))
                    except ValueError:
                        pass
        if pts:
            return max(p[0] for p in pts), max(p[1] for p in pts)
        return None

    # 某些预设（如 H2S 0.2 nozzle）只继承基础机型，需要沿 inherits 找
    seen = set()
    current = machine
    for _ in range(12):
        if not current or current in seen:
            break
        seen.add(current)
        path = os.path.join(root, 'machine', current + '.json')
        if not os.path.isfile(path):
            break
        try:
            with open(path, encoding='utf-8') as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            break
        area = cfg.get('printable_area') or cfg.get('bed_shape')
        dims = parse_area(area) if area else None
        if dims:
            return dims
        current = cfg.get('inherits')
    return None


def resolve_plate(args):
    """自动解析打印板尺寸与缩放上限（--plate-size/--max-size <=0 时）。"""
    if getattr(args, 'plate_w', 0) and getattr(args, 'plate_h', 0):
        return
    if args.plate_size > 0:
        args.plate_w = args.plate_h = args.plate_size
    else:
        machine = (args.machine or read_user_presets().get('machine')
                   or 'Bambu Lab P1S 0.4 nozzle')
        dims = machine_plate_size(machine, args.profiles_root)
        args.plate_w, args.plate_h = dims or (256.0, 256.0)
        args.plate_size = max(args.plate_w, args.plate_h)
        if args.max_size <= 0:
            args.max_size = max(230.0, args.plate_size - 40.0)


def preset_exists(profiles_root, typ, name):
    return os.path.isfile(os.path.join(profiles_root, typ, name + '.json'))


def _preset_names(profiles_root, typ):
    """返回本机 Bambu Studio 实际安装的预设名。"""
    try:
        return sorted(
            name[:-5] for name in os.listdir(os.path.join(profiles_root, typ))
            if name.lower().endswith('.json')
            and not name.lower().endswith('_full.json')
        )
    except OSError:
        return []


def _machine_token(name):
    text = str(name or '').strip()
    match = re.match(r'Bambu Lab (.+?)(?:\s+\d+(?:\.\d+)?\s+nozzle)?$',
                     text, re.I)
    return match.group(1).strip() if match else text


def _process_family(machine):
    token = _machine_token(machine).upper()
    if token in ('P1P', 'P1S', 'X1', 'X1C', 'X1E'):
        return 'X1C'
    if token == 'A1 MINI':
        return 'A1M'
    return token


def _pick_compatible_process(names, requested, machine):
    family = _process_family(machine)
    suffix = '@BBL ' + family
    family_rows = [
        name for name in names
        if suffix.lower() in name.lower()
    ]
    if not family_rows:
        return None
    nozzle = ''
    match = re.search(r'(\d+(?:\.\d+)?)\s+nozzle', str(machine), re.I)
    if match:
        nozzle = match.group(1)
    quality = ''
    match = re.match(r'\d+(?:\.\d+)?mm\s+(.+?)\s+@', str(requested or ''), re.I)
    if match:
        quality = match.group(1).strip()

    def score(name):
        low = name.lower()
        return (
            100 if suffix.lower() in low else 0,
            60 if quality and quality.lower() in low else 0,
            35 if nozzle and (nozzle + ' nozzle') in low else 0,
            20 if 'standard' in low else 0,
            10 if '0.20mm' in low else 0,
            -len(name),
        )

    return max(family_rows, key=score)


def _pick_compatible_filament(names, requested, machine):
    token = _machine_token(machine)
    suffix = '@BBL ' + token
    same_machine = [
        name for name in names if suffix.lower() in name.lower()
    ]
    pool = same_machine or list(names)
    wanted = str(requested or '').split('@', 1)[0].strip().lower()
    if wanted:
        exact = [name for name in pool
                 if name.lower().startswith(wanted)]
        if exact:
            return exact[0]
        words = wanted.split()
        if len(words) >= 2:
            material = ' '.join(words[:2])
            related = [name for name in pool
                       if name.lower().startswith(material)]
            if related:
                return related[0]
    return pool[0] if pool else None


def _preset_compatible(profiles_root, typ, name, machine):
    """预设存在还不够，还必须声明兼容当前机型。"""
    try:
        cfg = flatten_presets.flatten_preset(profiles_root, typ, name)
    except (OSError, ValueError):
        return False
    compatible = cfg.get('compatible_printers')
    if isinstance(compatible, str):
        compatible = [compatible]
    return not compatible or machine in compatible


def resolve_compatible_presets(args):
    """修正旧配置里已经不存在的预设，并返回可写进诊断的说明。"""
    user = read_user_presets()
    machine = args.machine or user.get(
        'machine', 'Bambu Lab P1S 0.4 nozzle')
    process = args.process or user.get(
        'process', '0.20mm Standard @BBL X1C')
    filament = args.filament or user.get(
        'filament', 'Bambu PLA Basic @BBL P1S 0.4 nozzle')
    notes = []

    machines = _preset_names(args.profiles_root, 'machine')
    if not preset_exists(args.profiles_root, 'machine', machine):
        same_model = [
            name for name in machines
            if not re.search(r'template', name, re.I)
            and _machine_token(name).upper()
            == _machine_token(machine).upper()
        ]
        nozzle = re.search(
            r'(\d+(?:\.\d+)?)\s+nozzle', str(machine), re.I)
        fallback = None
        if same_model:
            if nozzle:
                fallback = next(
                    (name for name in same_model
                     if (nozzle.group(1) + ' nozzle').lower()
                     in name.lower()),
                    None,
                )
            fallback = fallback or same_model[0]
        if not fallback:
            raise SliceError(
                '[PROFILE-01] 当前 Bambu Studio 没有机型预设「%s」。'
                '请升级 Bambu Studio，或在助手右上角重新选择本机机型。'
                % machine)
        notes.append('机型预设 %s → %s' % (machine, fallback))
        machine = fallback

    processes = _preset_names(args.profiles_root, 'process')
    if (not preset_exists(args.profiles_root, 'process', process)
            or not _preset_compatible(
                args.profiles_root, 'process', process, machine)):
        fallback = _pick_compatible_process(processes, process, machine)
        if not fallback:
            raise SliceError(
                '[PROFILE-02] 当前 Bambu Studio 缺少 %s 的工艺预设。'
                '请升级 Bambu Studio 后重新选择工艺。' % machine)
        notes.append('工艺预设 %s → %s' % (process, fallback))
        process = fallback

    filaments = _preset_names(args.profiles_root, 'filament')
    if (not preset_exists(args.profiles_root, 'filament', filament)
            or not _preset_compatible(
                args.profiles_root, 'filament', filament, machine)):
        fallback = _pick_compatible_filament(
            filaments, filament, machine)
        if not fallback:
            raise SliceError(
                '[PROFILE-03] 当前 Bambu Studio 缺少 %s 可用的耗材预设。'
                '请先在 Bambu Studio 中安装一个 PLA 基础预设。' % machine)
        notes.append('耗材预设 %s → %s' % (filament, fallback))
        filament = fallback

    args.machine = machine
    args.process = process
    args.filament = filament
    return notes


def _writable_output_dir(args):
    if getattr(args, 'out', ''):
        candidate = os.path.dirname(os.path.abspath(args.out))
    elif getattr(args, 'out_dir', ''):
        candidate = os.path.abspath(args.out_dir)
    else:
        candidate = os.path.join(
            os.path.expanduser('~'), 'Desktop', '切片文件')
    try:
        os.makedirs(candidate, exist_ok=True)
        fd, probe = tempfile.mkstemp(
            prefix='.tuozhu_write_', suffix='.tmp', dir=candidate)
        os.close(fd)
        os.remove(probe)
    except OSError as exc:
        raise SliceError(
            '[OUTPUT-01] 输出目录不可写：%s\n%s'
            % (candidate, str(exc)[:180])) from exc
    return candidate


def _write_preflight_report(out_dir, lines):
    path = os.path.join(out_dir, '切片诊断.txt')
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(time.strftime('[%Y-%m-%d %H:%M:%S]\n'))
            handle.write('\n'.join(str(line) for line in lines) + '\n')
    except Exception:
        return ''
    return path


def _append_diagnostic(args, stage, message):
    """把运行阶段失败追加到同一次预检报告，形成一条完整排查链。"""
    try:
        out_dir = _writable_output_dir(args)
        path = os.path.join(out_dir, '切片诊断.txt')
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write('\n[%s] %s\n%s\n' % (
                time.strftime('%Y-%m-%d %H:%M:%S'), stage, message))
        return path
    except Exception:
        return ''


def _inspect_model_for_preflight(path):
    if not os.path.isfile(path):
        raise SliceError('[FILE-01] 找不到文件：%s' % path)
    low = path.lower()
    if not low.endswith(MODEL_EXTS):
        raise SliceError('[FILE-02] 不支持的文件格式：%s'
                         % os.path.basename(path))
    if not low.endswith('.3mf'):
        return '%s · 文件正常' % os.path.basename(path)
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if '[Content_Types].xml' not in names:
                raise SliceError(
                    '[FILE-03] 3MF 缺少 [Content_Types].xml，包结构不完整。')
            if '3D/3dmodel.model' not in names:
                raise SliceError(
                    '[FILE-04] 3MF 缺少 3D/3dmodel.model，无法读取模型。')
            if any(name.lower().endswith('.gcode') for name in names):
                raise SliceError(
                    '[FILE-05] 这是已经切好的 .gcode.3mf，'
                    '请改选原始模型或可编辑 .3mf。')
    except zipfile.BadZipFile as exc:
        raise SliceError(
            '[FILE-06] 3MF 压缩包损坏或不完整，请在 Bambu Studio 中重新另存。'
        ) from exc
    meshes = unpack_3mf.count_meshes(path)
    parts = unpack_3mf.count_build_items(path)
    plates = unpack_3mf.count_plates(path)
    if meshes <= 0:
        raise SliceError(
            '[FILE-07] 3MF 里没有找到可打印网格，可能只有参考图或空盘。')
    return ('%s · %d 盘 / %d 对象 / %d 网格'
            % (os.path.basename(path), plates, parts, meshes))


def preflight_command(args):
    """在启动 Bambu 前一次性检查最常见失败原因。"""
    lines = []
    try:
        exe = args.exe or find_bambu_exe(lines)
        if not exe:
            raise SliceError(
                '[BAMBU-01] 没找到 Bambu Studio 主程序。'
                '请安装后重新打开助手。')
        if _needs_admin(exe):
            raise SliceError(
                '[BAMBU-02] 找到的 Bambu Studio 被设为必须管理员运行。'
                '请取消它的“以管理员身份运行”后重试。')
        args.exe = exe
        lines.append('Bambu Studio：' + exe)

        preset_notes = resolve_compatible_presets(args)
        lines.append('机型：' + args.machine)
        lines.append('工艺：' + args.process)
        lines.append('耗材：' + args.filament)
        lines.extend('预设调整：' + note for note in preset_notes)

        out_dir = _writable_output_dir(args)
        lines.append('输出目录：' + out_dir + '（可写）')

        if getattr(args, 'batch', ''):
            models = scan_models(args.batch, args.max_depth)
        elif getattr(args, 'model', ''):
            models = [os.path.abspath(args.model)]
        else:
            models = []
        if not models:
            raise SliceError('[FILE-08] 没有找到可处理的模型文件。')
        for path in models:
            lines.append('文件：' + _inspect_model_for_preflight(path))
        lines.append('预检结果：通过')
        report = _write_preflight_report(out_dir, lines)
        print('BATCH|log|预检通过：%d 个文件；%s'
              % (len(models), '、'.join(
                  os.path.basename(path) for path in models[:3])
                 + ('…' if len(models) > 3 else '')))
        for note in preset_notes:
            print('BATCH|log|预设自动兼容：' + note)
        return {'ok': True, 'out_dir': out_dir, 'models': models,
                'report': report, 'lines': lines}
    except Exception as exc:
        lines.append('预检结果：失败')
        lines.append(str(exc))
        try:
            out_dir = _writable_output_dir(args)
        except Exception:
            out_dir = os.path.dirname(os.path.abspath(
                getattr(args, 'out', '') or '.')) or os.getcwd()
        report = _write_preflight_report(out_dir, lines)
        if report:
            lines.append('诊断：' + report)
        raise SliceError(
            '%s\n诊断文件：%s' % (exc, report or '(无法写入)')) from exc


def _duration_seconds(text):
    """`35m 03s` / `1h 2m` → 秒；解析不了返回 None。"""
    if not text:
        return None
    # 头部一行常写成 `35m 3s; total estimated time: 41m 18s` ——
    # 只要第一段“模型打印时间”，不能把后面总时间也加进去。
    m = re.match(r'\s*(\d+(?:\.\d+)?\s*[hms]'
                 r'(?:\s*\d+(?:\.\d+)?\s*[hms])*)', str(text))
    if not m:
        return None
    total = 0.0
    for num, unit in re.findall(r'(\d+(?:\.\d+)?)\s*([hms])', m.group(1)):
        total += float(num) * {'h': 3600.0, 'm': 60.0, 's': 1.0}[unit]
    return int(round(total)) if total > 0 else None


def _time_text(sec):
    if not sec:
        return '-'
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return ('%dh%02dm' % (h, m)) if h else ('%dm%02ds' % (m, s))


def verify_3mf(path, plate=1):
    """校验 3mf 含 G-code 并返回解析摘要；plate=0 校验并汇总全部盘。"""
    def one_plate(z, names, plate_no):
        gname = f'Metadata/plate_{plate_no}.gcode'
        md5 = f'Metadata/plate_{plate_no}.gcode.md5'
        if gname not in names:
            raise RuntimeError(f'exported 3mf missing {gname}')
        if md5 not in names:
            raise RuntimeError(f'exported 3mf missing {md5}')
        text = z.read(gname).decode('utf-8', errors='replace')
        head = {}
        for key in (
            'layer_height',
            'sparse_infill_density',
            'wall_loops',
            'printer_model',
            'printable_area',
            'filament_density',
            'print_settings_id',
            'curr_bed_type',
            'total layer number',
            'model printing time',
            'total filament weight [g]',
        ):
            # Bambu 2.07 头部是 `; key : value`（冒号），老版本有用等号的。
            m = re.search(r'^; %s\s*[:=]\s*(.+)$' % re.escape(key),
                          text, re.M)
            head[key] = m.group(1).strip() if m else None
        pj = f'Metadata/plate_{plate_no}.json'
        if pj in names:
            try:
                head['bed_type'] = json.loads(z.read(pj)).get('bed_type')
            except (ValueError, OSError):
                head['bed_type'] = None
        support_used = None
        si = 'Metadata/slice_info.config'
        if si in names:
            try:
                info = z.read(si).decode('utf-8', errors='replace')
                m = re.search(r'key="support_used"\s+value="([^"]+)"', info)
                if m:
                    support_used = (m.group(1).strip().lower() == 'true')
            except (KeyError, OSError):
                support_used = None
        try:
            weight_g = float(head.get('total filament weight [g]') or 0)
        except (TypeError, ValueError):
            weight_g = None
        raw_time = head.get('model printing time')
        if raw_time:
            raw_time = raw_time.split(';', 1)[0].strip()
        return {
            'entries': len(names),
            'gcode_bytes': len(text),
            'printing_time': raw_time,
            'print_time_s': _duration_seconds(raw_time),
            'layers': head.get('total layer number'),
            'filament_weight_g': weight_g,
            'weight_g': weight_g,
            'support_used': support_used,
            'layer_height': head.get('layer_height'),
            'printer_model': head.get('printer_model'),
            'printable_area': head.get('printable_area'),
            'sparse_infill_density': head.get('sparse_infill_density'),
            'wall_loops': head.get('wall_loops'),
            'filament_density': head.get('filament_density'),
            'print_settings_id': head.get('print_settings_id'),
            'bed_type': head.get('bed_type'),
            'curr_bed_type': head.get('curr_bed_type'),
        }

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if plate != 0:
            return one_plate(z, names, plate)
        found = []
        for name in names:
            m = re.match(r'^Metadata/plate_(\d+)\.gcode$', name)
            if m:
                found.append(int(m.group(1)))
        found = sorted(found)
        if not found:
            raise RuntimeError('exported 3mf contains no plate G-code')
        plates = [one_plate(z, names, n) for n in found]
        merged = dict(plates[0])
        merged['plates'] = len(plates)
        merged['gcode_bytes'] = sum(p['gcode_bytes'] for p in plates)
        times = [p.get('print_time_s') for p in plates]
        if all(t is not None for t in times):
            total_s = sum(times)
            merged['print_time_s'] = total_s
            merged['printing_time'] = _time_text(total_s)
        weights = [p.get('weight_g') for p in plates]
        if all(w is not None for w in weights):
            merged['weight_g'] = sum(weights)
            merged['filament_weight_g'] = sum(weights)
        supports = [p.get('support_used') for p in plates]
        merged['support_used'] = (
            any(s is True for s in supports)
            if any(s is not None for s in supports) else None)
        return merged


def preserved_3mf_slice_args(args, plate_count):
    """原布局 3MF：多盘时让 Bambu 一次处理全部盘。"""
    selected = copy.copy(args)
    if int(plate_count or 1) > 1:
        selected.slice_plate = 0
    return selected


def find_profiles_root():
    """找 Bambu Studio 的预设目录（resources/profiles/BBL）。

    为什么要有这个函数：以前这个路径**写死在参数默认值里**（开发机的
    `D:\\Bambu Studio\\...`），用户装到 `C:\\Program Files\\Bambu Studio`
    就 `FileNotFoundError` 直接崩 —— 这是真实用户反馈的启动失败。

    查找顺序：环境变量给的常见安装位置 → 从**正在运行的 bambu-studio.exe**
    反推 → 常见盘符兜底。都找不到返回 ''（由调用方给人话提示，不抛栈）。
    """
    cands = []
    # ---- macOS：预设就在 .app 包里 ----
    if sys.platform == 'darwin':
        cands += ['/Applications/BambuStudio.app/Contents/Resources',
                  os.path.expanduser(
                      '~/Applications/BambuStudio.app/Contents/Resources')]
        for base in cands[-2:]:
            if os.path.isdir(os.path.join(base, 'profiles', 'BBL')):
                return os.path.join(base, 'profiles', 'BBL')
    for env in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        base = os.environ.get(env)
        if not base:
            continue
        cands.append(os.path.join(base, 'Bambu Studio'))
        if env == 'LOCALAPPDATA':
            cands.append(os.path.join(base, 'Programs', 'Bambu Studio'))
    # 从正在运行的 Bambu 进程反推安装目录（最可靠）
    try:
        import ctypes
        import ctypes.wintypes as _wt
        u32 = ctypes.windll.user32
        found = []

        def _cb(h, _l):
            n = u32.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 2)
                u32.GetWindowTextW(h, b, n + 2)
                if 'BambuStudio' in (b.value or ''):
                    found.append(h)
            return True
        u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, _wt.HWND,
                                           ctypes.c_void_p)(_cb), None)
        for h in found[:1]:
            pid = ctypes.c_uint32()
            u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            k32 = ctypes.windll.kernel32
            ph = k32.OpenProcess(0x1000, False, pid.value)
            if ph:
                buf = ctypes.create_unicode_buffer(1024)
                size = ctypes.c_uint32(1024)
                if k32.QueryFullProcessImageNameW(ph, 0, buf,
                                                  ctypes.byref(size)):
                    cands.append(os.path.dirname(buf.value))
                k32.CloseHandle(ph)
    except Exception:
        pass
    for drive in ('D:', 'E:', 'C:', 'F:'):
        cands.append(drive + '\\Bambu Studio')
    for base in cands:
        if not base:
            continue
        p = os.path.join(base, 'resources', 'profiles', 'BBL')
        if os.path.isdir(p):
            return p
    return ''


def footprint_of_3mf(path, plate=1):
    """从 3mf 里的 G-code 提取含支撑真实占用矩形。"""
    try:
        with zipfile.ZipFile(path) as z:
            gname = f'Metadata/plate_{plate}.gcode'
            if gname not in z.namelist():
                return None
            text = z.read(gname).decode('utf-8', errors='replace')
    except (OSError, zipfile.BadZipFile):
        return None
    return footprint.extrude_bbox(text)


def unique_out(out_dir, name):
    base, _ = os.path.splitext(name)
    p = os.path.join(out_dir, base + '.gcode.3mf')
    i = 2
    while os.path.exists(p):
        p = os.path.join(out_dir, f'{base}_{i}.gcode.3mf')
        i += 1
    return p


def orient_stl(exe, paths, args, model_in, workdir):
    """让 Bambu 自动定向并导出 STL；失败时抛 SliceError。

    抽成独立函数是给“最少支撑”当候选用的：它需要一个 Bambu 自己的
    定向结果，但不应该再跑一遍完整切片。
    """
    # Bambu 会把导出写到 cwd/stl；先清掉上一次的，避免这次失败却
    # 拿到旧文件（最少支撑会在候选阶段和回退阶段各调一次）。
    stl_dir = os.path.join(workdir, 'stl')
    shutil.rmtree(stl_dir, ignore_errors=True)
    orient_cmd = [
        exe,
        '--load-settings', paths['machine'] + ';' + paths['process'],
        '--load-filaments', paths['filament'],
        '--curr-bed-type', args.bed_type,
        '--orient', '1',
        '--export-stl', model_in,
    ]
    print('ORIENT RUN:', ' '.join(orient_cmd))
    r1 = run_cli(orient_cmd, capture_output=True, text=True, cwd=workdir)
    print('orient exit code:', r1.returncode)
    if r1.stdout:
        print('stdout:', r1.stdout[-1000:])
    if r1.stderr:
        print('stderr:', r1.stderr[-1000:])
    exports = ([f for f in os.listdir(stl_dir)
                if f.lower().endswith('.stl')]
               if os.path.isdir(stl_dir) else [])
    if not exports:
        why = explain_cli_failure(r1.stdout, r1.stderr, r1.returncode)
        if why:
            raise SliceError(why + '（在"自动定向"这一步就被拒了）')
        raise SliceError('auto-orient failed: Bambu exported no STL')
    return os.path.join(stl_dir, exports[0])


def _min_support_probe(stl, support_on, args):
    """给最少支撑裁判用：同一个 STL 切两刀，只改 enable_support。"""
    a = copy.copy(args)
    a.min_support = 0
    a.adaptive_scarf = 0
    a.orient = 0
    a.arrange = 0
    a.clone = 1
    a.batch = '__min_support_probe__'
    extra = 'enable_support=1' if support_on else 'enable_support=0'
    a.process_override = args.process_override or ''
    a.tail_override = extra
    pdir = tempfile.mkdtemp(prefix='min_support_probe_')
    out = os.path.join(pdir, 'probe.gcode.3mf')
    try:
        r = slice_one(stl, a, out=out)
        return {'ok': True, 'summary': r.get('summary') or {}}
    except SliceError as e:
        return {'ok': False, 'error': str(e)}
    finally:
        shutil.rmtree(pdir, ignore_errors=True)


def inspect_3mf_printable_parts(path):
    """逐个检查 3MF 原始网格，返回 (reports, problems)。

    Bambu 对“低于打印床”和部分破面只提示、不阻止切片。静默放行会让
    错误一路进入 G-code，所以多零件 3MF 在调用切片器前先逐个检查。
    """
    reports = unpack_3mf.inspect_meshes(path)
    problems = [row for row in reports
                if row['nonmanifold_edges'] > 0]
    return reports, problems


def slice_one(model, args, out=None, keep_oriented_dir=None,
              orient=None, arrange=None, mesh_size=None):
    """单模型完整流水线。返回 dict；硬失败抛 SliceError。

    keep_oriented_dir: 若给出，把自动定向后的 STL 复制过去供摆盘使用。
    """
    notes = []
    exe = args.exe or find_bambu_exe(notes)
    if not exe:
        msg = 'Bambu Studio 未安装或找不到'
        if notes:
            msg += '\n排查记录：\n  ' + '\n  '.join(notes[-4:])
        raise SliceError(msg)
    # 找到了但要提权 —— 提前说清楚，别等 subprocess 抛出 WinError 740
    if _needs_admin(exe):
        raise SliceError(_admin_hint(exe))
    if not os.path.isfile(model):
        raise SliceError(f'model not found: {model}')
    source_path = os.path.abspath(model)
    source_state = _source_stat(source_path)
    source_is_3mf = str(model).lower().endswith('.3mf')
    color_info = (
        unpack_3mf.project_filament_info(model) if source_is_3mf
        else {'multicolor': False})
    multicolor_project = bool(color_info.get('multicolor'))

    user = read_user_presets()
    machine = args.machine or user.get('machine', 'Bambu Lab P1S 0.4 nozzle')
    process = args.process or user.get('process', '0.20mm Standard @BBL X1C')
    filament = args.filament or user.get(
        'filament', 'Bambu PLA Basic @BBL P1S 0.4 nozzle')
    for typ, name in (('machine', machine), ('process', process),
                      ('filament', filament)):
        if not preset_exists(args.profiles_root, typ, name):
            print(f'preset {name!r} not found in profiles ({typ}); '
                  'falling back to default')
            if typ == 'machine':
                machine = 'Bambu Lab P1S 0.4 nozzle'
            elif typ == 'process':
                process = '0.20mm Standard @BBL X1C'
            else:
                filament = 'Bambu PLA Basic @BBL P1S 0.4 nozzle'
    resolve_plate(args)
    overrides = DEFAULT_PROCESS_OVERRIDES
    if args.process_override:
        overrides = overrides + ';' + args.process_override
    if getattr(args, 'project_overrides', ''):
        overrides = overrides + ';' + args.project_overrides
    if getattr(args, 'tail_override', ''):
        overrides = overrides + ';' + args.tail_override
    o_orient = args.orient if orient is None else orient
    o_arrange = args.arrange if arrange is None else arrange
    if source_is_3mf and getattr(args, 'preserve_project', 0):
        o_orient = 0
    if multicolor_project:
        # 多色/多材料工程只能整项目切；任何自动朝向/摆盘都可能经过 STL
        # 临时文件并丢掉 object→part 的颜色绑定。
        o_orient = 0
        o_arrange = 0

    workdir = tempfile.mkdtemp(prefix='bambu_slice_')
    actions = []
    try:
        assembly_mode = False
        if (model.lower().endswith('.3mf') and not multicolor_project
                and unpack_3mf.needs_assembly_export(model)):
            try:
                aparts = unpack_3mf.export_printable_build_items(
                    model, os.path.join(workdir, 'assembly'),
                    prefix='assembly')
                if aparts:
                    model = aparts[0]
                    assembly_mode = True
                    actions.append('3MF装配体（排除修改器）')
                    o_orient = 0
                    o_arrange = 0
                    print('ASSEMBLY:', model)
            except Exception as e:                         # noqa: BLE001
                print('assembly export skipped:', str(e)[:120])
        model_in = model
        multi_mesh_3mf = False
        if model.lower().endswith(('.stp', '.step')):
            print('converting STEP to STL via gmsh...')
            model_in = os.path.join(workdir, 'model_cad.stl')
            convert_step_to_stl(model, model_in,
                                mesh_size=args.mesh_size
                                if mesh_size is None else mesh_size)
            actions.append('step->stl')
            print('converted:', model_in)
        if model_in.lower().endswith('.stl'):
            # 破面/非流形自动修复（同拓竹 GUI 一键修复思路）
            repair_input = model_in
            try:
                repaired_path = os.path.join(workdir, 'model_repaired.stl')
                repaired, rep = repair_mesh.repair_mesh(model_in,
                                                        repaired_path)
                if repaired:
                    model_in = repaired_path
                    actions.append('破面修复')
                    print('REPAIR: 检测到破面，已修复')
                    print(json.dumps(rep, ensure_ascii=False))
                else:
                    print('REPAIR: 模型完好'
                          + ('（跳过：文件过大）'
                             if rep.get('skipped') else ''))
            except Exception as e:
                print(f'REPAIR: 修复跳过（{e}）')
            check = repair_mesh.inspect_stl(model_in)
            if check['nonmanifold_edges'] > 0:
                # 本地修复没有完全消除时不能提前拦死。Bambu 导入网格时
                # 自带模型修复；只有它最终切片失败才由下面统一报错。
                print('REPAIR: 本地修复后仍有 %d 条非流形边，'
                      '交由 Bambu 自动修复'
                      % check['nonmanifold_edges'])
                model_in = repair_input
                actions.append('Bambu自动修复')
        if model_in.lower().endswith('.3mf'):
            mesh_n = unpack_3mf.count_parts_for_pack(model_in)
            if mesh_n > 1:
                reports, problems = inspect_3mf_printable_parts(model_in)
                if not reports:
                    raise SliceError(
                        '多零件 3MF 无法读取网格，已停止切片。'
                        '请在 Bambu 中确认模型能正常打开后重试。')
                if problems:
                    detail = '、'.join(
                        '%s（%d 条）' % (
                            row['name'], row['nonmanifold_edges'])
                        for row in problems[:5])
                    # 这段检查只用于告知用户即将触发自动修复，不能代替
                    # Bambu 的导入修复。实测 object_22 的 2 条边由 Bambu
                    # 原样导入可正常切片；此前提前 raise 反而误拦了正常盘。
                    print('REPAIR: 检测到非流形边：%s；交由 Bambu 自动修复'
                          % detail)
                    actions.append('Bambu自动修复')
                multi_mesh_3mf = True
                actions.append(f'多零件3mf（{mesh_n}件）整盘切片')
                print(f'input .3mf contains {mesh_n} parts: slicing as-is '
                      'without auto-orient export (avoids losing parts)')
            else:
                print('input is .3mf: Bambu Studio loads the geometry '
                      'directly; skipping STL analysis/clean')
        else:
            info = analyze_stl.analyze(model_in, args.plate_size)
            print('MODEL ANALYSIS')
            print(json.dumps(info, ensure_ascii=False, indent=2))
            if (not info['fits_plate'] or not info['finite']
                    or info['nan_triangles'] > 0):
                print('cleaning model (preserve size unless allowed)...')
                src = model_in
                model_in = os.path.join(workdir, 'model_clean.stl')
                try:
                    clean_stl.clean_and_fit(
                        src, model_in, max_size=args.max_size,
                        plate_size=args.plate_size,
                        allow_scale=bool(getattr(args, 'allow_scale', 0)))
                except ValueError as e:
                    raise SliceError(str(e)) from e
                actions.append('clean/scale'
                               if getattr(args, 'allow_scale', 0)
                               else 'clean/fit')
                print('cleaned:', model_in)

        preset_root = os.path.join(workdir, 'presetroot')
        paths = flatten_presets.prepare_preset_root(
            args.profiles_root, preset_root, machine, process, filament,
            process_overrides=overrides)
        print('PRESETS')
        for typ, p in paths.items():
            print(f'  {typ}: {p}')
        if multicolor_project:
            print('BATCH|log|多色工程：保留原耗材槽位和颜色绑定，'
                  '整项目直接交给 Bambu 切片')

        # 手办模式：主体保持设计者朝向；只有已经穿床/倾斜的非主体部件
        # 交给 Bambu 自己的“自动朝向”。回写后仍是原盘、原名、其它坐标不动。
        face_setting = getattr(args, 'part_face_orient', None)
        if face_setting is None:
            face_setting = int(getattr(args, 'orient', 1) != 0)
        if (multi_mesh_3mf and not multicolor_project
                and getattr(args, 'figurine_mode', 0)
                and face_setting and model_in.lower().endswith('.3mf')):
            try:
                model_in, _orient_actions = (
                    auto_orient_figurine_parts_in_place(
                        exe, paths, args, model_in, workdir))
                actions.extend(_orient_actions)
            except Exception as e:                         # noqa: BLE001
                raise SliceError(
                    '部件自动朝向失败：%s' % str(e)[:180]) from e

        out = out or os.path.join(
            os.path.expanduser('~'), 'Desktop', '切片文件',
            os.path.splitext(os.path.basename(model))[0] + '.gcode.3mf')
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        if os.path.normcase(os.path.abspath(out)) == os.path.normcase(
                os.path.abspath(model)):
            raise SliceError('输出路径不能覆盖源文件')
        if os.path.exists(out):
            os.remove(out)

        model_to_slice = model_in
        oriented_stl = None
        min_support_info = None

        # 日常朝向完全交给 Bambu Studio。主体零件由批量分类显式设为
        # orient=0，因此不会进入下面的 Bambu 自动朝向分支。
        daily_plane_info = None

        # ★ 最少支撑：先选方向，再走原来的最终切片。
        #   探针切片会把 min_support 置 0，所以不会递归回来。
        if getattr(args, 'min_support', 0) and multi_mesh_3mf:
            print('BATCH|log|最少支撑跳过：多零件 3mf 需要保持整盘，'
                  '先按原方向切')
        if (getattr(args, 'min_support', 0) and not multi_mesh_3mf
                and 'enable_support=0' in overrides):
            print('BATCH|log|最少支撑跳过：当前设置为无支撑')
        if (getattr(args, 'min_support', 0) and not multi_mesh_3mf
                and 'enable_support=0' not in overrides):
            try:
                import min_support as MS

                def _orient():
                    return orient_stl(exe, paths, args, model_in, workdir)

                def _probe(stl, support_on):
                    return _min_support_probe(stl, support_on, args)

                ms = MS.optimize(
                    model_in, args, _probe, orient_fn=_orient,
                    keep_dir=workdir,
                    batch=bool(getattr(args, 'batch', None)),
                    emit=lambda s: print('BATCH|log|' + s))
                if ms.get('ok'):
                    model_to_slice = ms['best_stl']
                    oriented_stl = model_to_slice
                    min_support_info = ms
                    actions.append('最少支撑：%s' % ms['best']['name'])
                    o_orient = 0          # 方向已定，别再让 Bambu 转一次
                    o_arrange = 0         # 也别让摆盘把方向转回去
                    if keep_oriented_dir:
                        os.makedirs(keep_oriented_dir, exist_ok=True)
                        dst = os.path.join(
                            keep_oriented_dir,
                            '%s_min_support.stl'
                            % os.path.splitext(os.path.basename(model))[0])
                        shutil.copyfile(model_to_slice, dst)
                        oriented_stl = dst
                else:
                    print('BATCH|log|最少支撑跳过：%s'
                          % (ms.get('error') or '没有可用方向'))
            except Exception as e:                         # noqa: BLE001
                print('BATCH|log|最少支撑失败，回退自动定向：%s'
                      % str(e)[:160])

        if o_orient and not multi_mesh_3mf:
            try:
                model_to_slice = orient_stl(exe, paths, args, model_in,
                                            workdir)
            except SliceError as e:
                print('WHY:', str(e))
                raise
            oriented_stl = model_to_slice
            actions.append('Bambu自动朝向')
            print('ORIENTED MODEL:', model_to_slice)
            if keep_oriented_dir:
                os.makedirs(keep_oriented_dir, exist_ok=True)
                dst = os.path.join(keep_oriented_dir,
                                   os.path.basename(model_to_slice))
                shutil.copyfile(model_to_slice, dst)
                oriented_stl = dst

        # 明确关闭自动定向（--orient 0）时，摆盘仍然需要原始 STL 作为
        # “oriented”输入；否则 pack_results 会把所有零件判成没有朝向，
        # 摆盘候选变成 0/6，最后只能回退成每个模型单独一盘。
        if not o_orient and not multi_mesh_3mf and not min_support_info:
            oriented_stl = model_in
            if keep_oriented_dir:
                os.makedirs(keep_oriented_dir, exist_ok=True)
                dst = os.path.join(
                    keep_oriented_dir,
                    os.path.basename(model_in))
                shutil.copyfile(model_in, dst)
                oriented_stl = dst

        scarf_profile = None
        if (getattr(args, 'adaptive_scarf', 0)
                and 'seam_slope_conditional=1' in overrides):
            scarf_profile = seam_profile.inspect_model(model_to_slice)
            if scarf_profile.get('ok'):
                scarf_len = scarf_profile['scarf_length_mm']
                overrides += (
                    ';seam_slope_min_length=%.0f'
                    ';filament_scarf_length=%.0f'
                    % (scarf_len, scarf_len))
                # The first preset tree was needed for orientation/min-support
                # probes. Rebuild it with the measured length for the final cut.
                final_preset_root = os.path.join(
                    workdir, 'presetroot_adaptive')
                paths = flatten_presets.prepare_preset_root(
                    args.profiles_root, final_preset_root, machine, process,
                    filament, process_overrides=overrides)
                print(
                    'BATCH|log|隐藏 Z 缝：外壁参考 %.1f mm，'
                    '采用 %.0f mm 斜拼'
                    % (scarf_profile['loop_p75_mm'], scarf_len))
            else:
                print(
                    'BATCH|log|隐藏 Z 缝：外壁测量失败，'
                    '沿用默认 10 mm（%s）'
                    % scarf_profile.get('error', '未知原因'))

        # run_slice 里认出来的"Bambu 拒了这组参数"原因，给最后的报错用
        last_why = []

        def run_slice(mesh, arrange):
            c = [exe, '--slice', str(args.slice_plate)]
            if not multicolor_project:
                c += [
                    '--load-settings',
                    paths['machine'] + ';' + paths['process'],
                    '--load-filaments', paths['filament'],
                    '--curr-bed-type', args.bed_type,
                ]
            c += ['--export-3mf', out]
            if arrange:
                c += ['--arrange', str(arrange)]
            if getattr(args, 'no_check', 0):
                # Bambu 自己的调试开关："不要运行任何有效性检查，如 gcode 路径
                # 冲突检查"（语言包原文）。紧凑摆盘允许支撑互相重叠，正是它要
                # 判冲突的地方 —— 打开这个才能真正按我们的规矩摆。
                c += ['--no-check']
            c.append(mesh)
            print('RUN:', ' '.join(c))
            rr = run_cli(c, capture_output=True, text=True)
            print('exit code:', rr.returncode)
            if rr.stdout:
                print('stdout:', rr.stdout[-2000:])
            if rr.stderr:
                print('stderr:', rr.stderr[-2000:])
            if rr.returncode != 0:
                _why = explain_cli_failure(rr.stdout, rr.stderr, rr.returncode)
                if _why:
                    print('WHY:', _why)
                    last_why.append(_why)
            return rr.returncode

        rcode = run_slice(model_to_slice, o_arrange)
        if (not os.path.isfile(out) and daily_plane_info
                and daily_plane_info.get('ok')):
            current = daily_plane_info.get('selected') or {}
            attempted = {current.get('rank')}
            for option in (daily_plane_info.get('options') or [])[1:]:
                if option.get('rank') in attempted:
                    continue
                attempted.add(option.get('rank'))
                print('BATCH|log|日常摆放：第%s大平面切片失败，换下一平面重试'
                      % current.get('rank', '一'))
                if os.path.exists(out):
                    os.remove(out)
                model_to_slice = option.get('path') or model_to_slice
                oriented_stl = model_to_slice
                current = option
                daily_plane_info['selected'] = option
                actions.append('日常大平面回退')
                rcode = run_slice(model_to_slice, o_arrange)
                if os.path.isfile(out):
                    print('BATCH|log|日常摆放：改用第%s大平面'
                          % option.get('rank', '二'))
                    break
        if not os.path.isfile(out) and o_orient:
            # Bambu 自动定向导出的网格对个别几何无法切片（-100/-64），
            # 自动回退成原方向切片，不阻塞打印
            print('auto-orient slice failed; retrying without orientation...')
            actions.append('定向失败→原方向')
            if os.path.exists(out):
                os.remove(out)
            rcode = run_slice(model_in, args.arrange)
            if os.path.isfile(out):
                # 定向失败但原方向能切：也给摆盘一个可用的 STL，
                # 别把零件从摆盘里丢掉。
                oriented_stl = model_in
        elif not os.path.isfile(out) and min_support_info:
            # 个别几何对 `--arrange 0` 不买账；退回自动摆放（只影响盘面
            # 平移/90° 旋转，不会把支撑最优的朝向翻掉）。
            print('min-support slice failed with arrange=0; retry arrange=2')
            actions.append('最少支撑：摆盘重试')
            if os.path.exists(out):
                os.remove(out)
            rcode = run_slice(model_to_slice, 2)
        if not os.path.isfile(out):
            msg = f'slice failed (exit {rcode}); no output file'
            if last_why:
                msg = last_why[-1] + '；' + msg
            raise SliceError(msg, rcode)

        summary = verify_3mf(out, args.slice_plate)
        if multicolor_project:
            try:
                unpack_3mf.verify_color_bindings(source_path, out)
                actions.append('保留原颜色与耗材绑定')
            except ValueError as exc:
                raise SliceError(
                    '切片产物没有保留多色/多材料绑定：%s' % exc) from exc
        if source_state is not None and _source_stat(source_path) != source_state:
            raise SliceError('处理过程中源 3MF 被修改，已停止并使用原文件')
        print('OUTPUT VERIFIED')
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print('OUTPUT:', out)
        if not getattr(args, 'batch', None) and getattr(args, 'clone', 1) <= 1:
            emit_param_diff(out, args)
        return {'out': out, 'summary': summary, 'oriented_stl': oriented_stl,
                'actions': actions, 'min_support': min_support_info,
                'scarf_profile': scarf_profile,
                'protected_project': bool(multicolor_project)}
    finally:
        if not args.keep_temp:
            shutil.rmtree(workdir, ignore_errors=True)


def scan_models(folder, max_depth=3):
    exts = MODEL_EXTS
    found = []
    base_depth = folder.rstrip('\\/').count(os.sep)
    for root, dirs, files in os.walk(folder):
        depth = root.count(os.sep) - base_depth
        if depth >= max_depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs
                   if not d.startswith('.') and not d.startswith('$')]
        for f in sorted(files):
            if f.startswith('.'):
                continue
            if f.lower().endswith(exts):
                p = os.path.join(root, f)
                if p not in found:
                    found.append(p)
    return sorted(found, key=lambda p: p.lower())


def split_parts_for_pack(path, out_dir, seq, prefer_build_items=False):
    """自动摆盘前把一个文件拆成 Bambu 拆分后的零件。

    返回 (零件路径列表, 报告用零件数)。STL/STEP 本身就是零件；
    多零件 3mf 用 unpack_3mf 拆成独立 STL，后续每个零件单独
    自动定向 / 最少支撑 / 量含支撑占地。
    """
    if not str(path).lower().endswith('.3mf'):
        return [path], 1
    if prefer_build_items:
        try:
            parts = unpack_3mf.export_printable_build_items(
                path, out_dir, prefix='f%02d' % seq)
            if parts:
                declared = unpack_3mf.count_build_items(path)
                print('BATCH|log|3MF 按顶层 build item 拆件：%d 个，'
                      '保留装配关系和原始名称' % len(parts))
                return parts, max(declared, len(parts))
        except Exception as e:                             # noqa: BLE001
            print('BATCH|log|3MF 顶层拆件失败（%s），回退网格拆件'
                  % str(e)[:120])
    n = unpack_3mf.count_parts_for_pack(path)
    need_items = unpack_3mf.needs_build_item_split(path)
    need_assembly = unpack_3mf.needs_assembly_export(path)
    base = os.path.splitext(os.path.basename(path))[0]
    safe = re.sub(r'[^\w.-]+', '_', base)[:40] or 'model'
    prefix = 'f%02d_%s' % (seq, safe)
    if n <= 1 and not need_assembly:
        return [path], max(1, n)
    if not need_items and not need_assembly:
        parts = unpack_3mf.split_meshes(path, out_dir, prefix=prefix)
        return (parts if parts else [path]), n
    # 单盘里的 build item 带缩放/镜像/装配位移，或一个 build item
    # 内含多个 component（手办）。用纯 Python 按装配树导出：
    # 应用变换、跳过 modifier/negative/support-blocker，
    # 不依赖 Bambu GUI，也不会把修改器当成实体打印。
    try:
        parts = unpack_3mf.export_printable_build_items(
            path, out_dir, prefix=prefix)
        if parts:
            print('BATCH|log|3MF 装配导出：%d 个可打印装配体，'
                  '保留缩放/镜像/位移' % len(parts))
            return parts, n
    except Exception as e:                                 # noqa: BLE001
        print('BATCH|log|3MF 装配导出失败（%s），保留原 3MF 整盘'
              % str(e)[:120])
    return [path], max(1, n)


def classify_figurine_parts(source, parts, enabled,
                            body_min_ratio=FIGURINE_BODY_MIN_RATIO):
    """Classify a split cosmetic/figurine 3MF by volume.

    The largest part is the primary body.  A second part at least
    ``body_min_ratio`` of that volume is the second body; all remaining parts
    are printable accessories.  The two-body cap is explicit and a warning is
    emitted if a third part also meets the body threshold.
    """
    if (not enabled or not str(source or '').lower().endswith('.3mf')
            or not parts):
        return None

    rows = []
    for path in parts:
        mesh = min_support.load_mesh(path)
        try:
            volume = abs(float(mesh.volume)) if mesh is not None else 0.0
        except (TypeError, ValueError):
            volume = 0.0
        if not math.isfinite(volume):
            volume = 0.0
        rows.append({'path': path, 'volume_mm3': volume, 'ratio': 0.0,
                     'role': 'part', 'body_rank': None})

    largest = max((r['volume_mm3'] for r in rows), default=0.0)
    if largest <= 0:
        return {
            'parts': rows, 'body_count': 0, 'warning':
            '体积计算失败，未启用手办主体保护',
        }

    body_count = 0
    excess_body_candidates = 0
    for row in sorted(rows, key=lambda r: r['volume_mm3'], reverse=True):
        row['ratio'] = row['volume_mm3'] / largest
        if row['ratio'] + 1e-9 >= float(body_min_ratio):
            if body_count < FIGURINE_MAX_BODIES:
                body_count += 1
                row['role'] = 'body'
                row['body_rank'] = body_count
            else:
                excess_body_candidates += 1

    warning = ''
    if excess_body_candidates:
        warning = (
            '有 %d 个体积达到主体阈值但超过 %d 个主体上限，'
            '这些零件按部件处理' %
            (excess_body_candidates, FIGURINE_MAX_BODIES))
    return {'parts': rows, 'body_count': body_count, 'warning': warning}


def body_pose_report(path):
    """Inspect a main body without changing its rotation."""
    mesh = min_support.load_mesh(path)
    if mesh is None:
        return {'ok': False, 'error': '主体网格读取失败'}
    import min_support as MS
    stability = MS.stability(mesh)
    support = MS.estimate_support(mesh)
    return {
        'ok': True,
        'contact_mm2': stability.get('contact_mm2'),
        'com_inside': stability.get('com_inside'),
        'stable': stability.get('stable'),
        'overhang_mm2': support.get('area_mm2'),
        'support_estimate_cm3': support.get('volume_cm3'),
    }


def prepare_split_part_args(args, source, part_path, figurine_role=None):
    """Return per-part slice args for a part extracted from a 3MF project.

    3MF build-item transforms are baked into the extracted STL.  Preserve them
    for a placement that already has a trusted base plane, but let the daily
    max-plane pass correct a genuinely tilted part (for example a shell that
    arrives 12.5 degrees off the bed).

    ``part_face_orient`` is distinct from ``orient`` because the GUI sets
    ``orient=0`` merely to preserve a whole 3MF project.  When it splits that
    3MF into parts, that inherited value must not disable per-part max-plane
    selection.  An explicit user request for no orientation sets this flag to 0.
    """
    if (not str(source or '').lower().endswith('.3mf')
            or str(part_path or '').lower().endswith('.3mf')):
        return args

    part_args = copy.copy(args)
    part_args.preserve_project = 0
    if figurine_role == 'body':
        # Cosmetic bodies already carry the designer's intended pose.  Keep
        # their rotation; packing may translate or rotate only in the XY plane.
        part_args.orient = 0
        part_args.daily_face_orient = 0
        part_args.min_support = 0
        part_args.arrange = 0
        return part_args

    face_setting = getattr(args, 'part_face_orient', None)
    if face_setting is None:
        # Direct CLI callers that explicitly disabled orientation keep it off.
        # The GUI supplies this flag explicitly when it splits a 3MF.
        face_setting = int(getattr(args, 'orient', 1) != 0)

    if face_setting:
        if getattr(args, 'orient', 1) == 2:
            part_args.orient = 2
            part_args.daily_face_orient = 0
        else:
            part_args.orient = 1
            part_args.daily_face_orient = 0
    else:
        part_args.orient = 0
        part_args.daily_face_orient = 0
    return part_args


def auto_orient_figurine_parts_in_place(exe, paths, args, source, workdir):
    """只把低于打印板的非主体部件交给 Bambu 自动朝向。

    已放平、主体以及其它零件都保持原坐标；Bambu 返回的单个部件朝向
    写回原 3MF 的对应 build item，因此盘号、名称和其它对象不变。
    """
    rows = unpack_3mf.inspect_build_items(source)
    if not rows:
        return source, []
    largest = max((r.get('volume_mm3') or 0.0 for r in rows),
                  default=0.0)
    bodies = set()
    if largest > 0:
        body_count = 0
        threshold = getattr(
            args, 'figurine_body_ratio', FIGURINE_BODY_MIN_RATIO)
        for row in sorted(
                rows, key=lambda r: r.get('volume_mm3') or 0.0,
                reverse=True):
            ratio = (row.get('volume_mm3') or 0.0) / largest
            if ratio + 1e-9 >= float(threshold):
                if body_count < FIGURINE_MAX_BODIES:
                    body_count += 1
                    bodies.add(row['index'])
    candidates = [r for r in rows if r['index'] not in bodies]
    if not candidates:
        return source, []

    current = source
    actions = []
    for seq, row in enumerate(candidates, 1):
        name = row.get('name') or '零件%d' % row['index']
        raw = os.path.join(
            workdir, 'figurine_part_%02d_before.stl' % seq)
        unpack_3mf.export_build_item_stl(current, raw, row['index'])
        orient_work = os.path.join(workdir, 'orient_part_%02d' % seq)
        os.makedirs(orient_work, exist_ok=True)
        oriented = orient_stl(
            exe, paths, args, raw, orient_work)
        dst = os.path.join(
            workdir, 'figurine_parts_oriented_%02d.3mf' % seq)
        rep = unpack_3mf.replace_build_item_geometry(
            current, dst, row['index'], oriented)
        current = dst
        actions.append('Bambu自动朝向：%s' % name)
        old_h = (row.get('max_z', 0.0) - row.get('min_z', 0.0))
        new_h = (rep.get('max_z', 0.0) - rep.get('min_z', 0.0))
        print('BATCH|log|部件自动朝向：%s（底面 %.2f → %.2f，'
              '高度 %.2f → %.2f mm）'
              % (name, row.get('min_z', 0.0), rep.get('min_z', 0.0),
                 old_h, new_h))
    return current, actions


def _rotate_for_min_footprint(src, dst):
    """若把零件立起来（绕 X/Y 转 90°）占地更小，就写一份立放 STL。

    返回 True 表示已写入立放版本。薄板类（如 125×125×8.5）会自动竖起，
    高度本来就大的零件保持原样。
    """
    try:
        with open(src, 'rb') as f:
            data = f.read()
        n = struct.unpack_from('<I', data, 80)[0]
        tris = []
        for i in range(n):
            base = 84 + i * 50 + 12
            t = []
            for k in range(3):
                t.append(struct.unpack_from('<3f', data, base + k * 12))
            tris.append(t)
    except (OSError, struct.error):
        return False

    def xform(mode, p):
        x, y, z = p
        if mode == 1:      # 绕 X 转 90°：把 Y 竖起来
            return (x, -z, y)
        if mode == 2:      # 绕 Y 转 90°：把 X 竖起来
            return (z, y, -x)
        return p

    def bbox(mode):
        mn = [float('inf')] * 3
        mx = [float('-inf')] * 3
        for t in tris:
            for p in t:
                q = xform(mode, p)
                for k in range(3):
                    mn[k] = min(mn[k], q[k])
                    mx[k] = max(mx[k], q[k])
        return tuple(mx[k] - mn[k] for k in range(3))

    dims = [bbox(0), bbox(1), bbox(2)]
    areas = [d[0] * d[1] for d in dims]
    best = min(range(3), key=lambda m: areas[m])
    if best == 0 or areas[best] >= areas[0] - 1.0:
        return False

    def normal(a, b, c):
        ux, uy, uz = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        vx, vy, vz = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        nx, ny, nz = (uy * vz - uz * vy, uz * vx - ux * vz,
                      ux * vy - uy * vx)
        length = (nx * nx + ny * ny + nz * nz) ** 0.5
        if length < 1e-12:
            return (0.0, 0.0, 1.0)
        return (nx / length, ny / length, nz / length)

    try:
        with open(dst, 'wb') as f:
            f.write(b'standing optimize'.ljust(80, b'\x00'))
            f.write(struct.pack('<I', n))
            for t in tris:
                q = [xform(best, p) for p in t]
                nn = normal(q[0], q[1], q[2])
                f.write(struct.pack('<3f', *nn))
                for p in q:
                    f.write(struct.pack('<3f', *p))
                f.write(struct.pack('<H', 0))
    except OSError:
        return False
    return True


def _rotate_stl_z90(src, dst):
    """绕 Z 转 90°（盘面旋转），用于紧凑摆盘的 90° 摆放。"""
    try:
        with open(src, 'rb') as f:
            data = f.read()
        n = struct.unpack_from('<I', data, 80)[0]
        tris = []
        for i in range(n):
            base = 84 + i * 50 + 12
            t = []
            for k in range(3):
                t.append(struct.unpack_from('<3f', data, base + k * 12))
            tris.append(t)
    except (OSError, struct.error):
        return False

    def xform(p):
        x, y, z = p
        return (-y, x, z)

    def normal(a, b, c):
        ux, uy, uz = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        vx, vy, vz = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        nx, ny, nz = (uy * vz - uz * vy, uz * vx - ux * vz,
                      ux * vy - uy * vx)
        length = (nx * nx + ny * ny + nz * nz) ** 0.5
        if length < 1e-12:
            return (0.0, 0.0, 1.0)
        return (nx / length, ny / length, nz / length)

    try:
        with open(dst, 'wb') as f:
            f.write(b'rotated z90'.ljust(80, b'\x00'))
            f.write(struct.pack('<I', n))
            for t in tris:
                q = [xform(p) for p in t]
                nn = normal(q[0], q[1], q[2])
                f.write(struct.pack('<3f', *nn))
                for p in q:
                    f.write(struct.pack('<3f', *p))
                f.write(struct.pack('<H', 0))
    except OSError:
        return False
    return True


def pack_results(results, args, out_dir, tmp, folder_name, allow_single=False,
                 tight=False):
    """摆盘 + 自适应间距重试。

    tight=True（紧致摆盘）：按模型本体占地装箱，支撑可互相重叠，
    只保证支撑不压别的本体；校验只查“不丢件 + 不出板”。
    否则按含支撑真实占地装箱（保守）。
    """
    out_plates = []
    try:
        indices = [i for i, r in enumerate(results)
                   if r.get('ok') and r.get('footprint') and r.get('oriented')]
        print(f'BATCH|log|摆盘候选：{len(indices)}/{len(results)}')
        if not indices:
            return []
        # 支撑占地已经在每个零件的切片 footprint 里，板边统一留 12mm
        # 就够；以前保守模式额外留 30mm，会白白少放零件。
        margin = 12.0
        pack_plate = (max(100.0, getattr(args, 'plate_w', 256.0) - margin),
                      max(100.0, getattr(args, 'plate_h', 256.0) - margin))

        def rect_of(i):
            if tight:
                info = analyze_stl.analyze(results[i]['oriented'],
                                           args.plate_size)
                w, h = info['size_mm'][0], info['size_mm'][1]
                # support_gap 是**上限**，不是固定值：每个零件到底外扩多少，
                # 看它自己那份切片里"含支撑的真实挤出范围"（footprint 就是
                # 扫它自己的 G-code 量出来的，各模型天然不同）。
                #   外扩 = (含支撑范围 - 本体尺寸) / 2
                #   实际留 = min(外扩, 上限)
                # 上限一步步放大（见 bambu_action 里的阶梯），哪一档能切就用哪档。
                cap = float(getattr(args, 'support_gap', 0.0) or 0.0)
                fp = results[i].get('footprint')
                if cap > 0 and fp:
                    gx = max(0.0, (fp[2] - fp[0] - w) / 2.0)
                    gy = max(0.0, (fp[3] - fp[1] - h) / 2.0)
                    return (w + 2 * min(gx, cap), h + 2 * min(gy, cap))
                # 上限 0 = 老规矩（支撑可互相重叠）—— 软件端保持这个
                return (w, h)
            fp = results[i]['footprint']
            return (fp[2] - fp[0], fp[3] - fp[1])

        def process_plate(items, gap, plate_no):
            """items: [(结果索引, x, y, rot=0)] → (verified, info)"""
            placed = []
            exp = [None, None, None, None]
            for item in items:
                idx, x, y = item[0], item[1], item[2]
                rot = item[3] if len(item) > 3 else 0
                r = results[idx]
                mesh = r['oriented']
                if rot:
                    rmesh = os.path.join(tmp, f'rot_{plate_no}_{idx}.stl')
                    if _rotate_stl_z90(mesh, rmesh):
                        mesh = rmesh
                info = analyze_stl.analyze(mesh, args.plate_size)
                mn = info['min']
                placed.append((mesh, x - mn[0], y - mn[1], -mn[2]))
                w, h = rect_of(idx)
                if rot:
                    w, h = h, w
                rect = (x, y, x + w, y + h)
                for k in range(4):
                    exp[k] = rect[k] if exp[k] is None else (
                        min(exp[k], rect[k]) if k < 2 else max(exp[k], rect[k]))
            merged = os.path.join(tmp, f'plate_{plate_no}.stl')
            merge_stl.merge_stls(placed, merged)
            plate_out = unique_out(out_dir, f'{folder_name}_盘{plate_no}')
            names = [results[i[0]]['name'] for i in items]
            print(f'BATCH|log|摆盘第{plate_no}盘（间距{gap:.0f}mm）：'
                  f'{len(items)} 个模型 → {plate_out}')
            print('BATCH|log|盘%d 模型：%s' % (plate_no, '、'.join(names)))
            verified = False
            plate_support_g = None
            plate_weight_on = None
            plate_weight_off = None
            plate_support_used = None
            try:
                def slice_merged_plate(plate_args, output_path):
                    """先保留助手算好的整盘坐标，失败再交给 Bambu 重排。

                    合并 STL 里的多个壳体已经由桌面端完成摆位。部分 Bambu
                    版本用 arrange=2 重新排列这种合并对象时会误报“盘内没有
                    完整物体”，而 arrange=0 可以直接按现有坐标切片。
                    """
                    for arrange_value in (0, 2):
                        try:
                            slice_one(
                                merged,
                                plate_args,
                                out=output_path,
                                orient=0,
                                arrange=arrange_value,
                            )
                            return
                        except SliceError:
                            try:
                                if os.path.isfile(output_path):
                                    os.remove(output_path)
                            except OSError:
                                pass
                            if arrange_value == 0:
                                print(
                                    'BATCH|log|盘%d 按原坐标切片失败，'
                                    '尝试 Bambu 自动排列重试' % plate_no
                                )
                                continue
                            raise

                # ★ 合并盘不能再跑“最少支撑”：方向已经在单件阶段定好了，
                #   对一整盘重新选方向会破坏摆位，而且会多花几倍时间。
                plate_args = copy.copy(args)
                plate_args.min_support = 0
                plate_args.pack = 0
                # ★ 不要在这里强制 enable_support=0。最少支撑只负责
                #   选方向，不是“关闭支撑”；合并盘仍按原支撑设置切，
                #   否则方向选完后有悬空面也不会生成支撑。
                slice_merged_plate(plate_args, plate_out)
                if getattr(args, 'min_support', 0):
                    try:
                        on_summary = verify_3mf(plate_out, args.slice_plate)
                        plate_weight_on = on_summary.get('weight_g')
                        plate_support_used = on_summary.get('support_used')
                        if on_summary.get('support_used'):
                            # 单件候选的“开/关支撑”差值有时会是 0
                            # （例如合盘后 Bambu 才按整盘悬空面补支撑）。
                            # 最终盘再切一次关支撑，报告以整盘真实差值为准。
                            off_args = copy.copy(plate_args)
                            po = (getattr(off_args, 'process_override', '') or '')
                            off_args.process_override = (
                                po.strip().strip(';') +
                                ';enable_support=0').strip(';')
                            off_out = os.path.join(
                                tmp, f'plate_{plate_no}_off.gcode.3mf')
                            try:
                                slice_merged_plate(off_args, off_out)
                                off_summary = verify_3mf(
                                    off_out, args.slice_plate)
                                plate_weight_off = off_summary.get('weight_g')
                                if plate_weight_on is not None and plate_weight_off is not None:
                                    plate_support_g = max(
                                        0.0, float(plate_weight_on) -
                                        float(plate_weight_off))
                                    print(
                                        'BATCH|log|盘%d 实际支撑：%.2f g'
                                        % (plate_no, plate_support_g))
                            finally:
                                try:
                                    os.remove(off_out)
                                except OSError:
                                    pass
                    except Exception as e:                     # noqa: BLE001
                        print('BATCH|log|盘%d 支撑称重失败（%s），'
                              '保留候选试切数值' % (plate_no, str(e)[:100]))
                fp2 = footprint_of_3mf(plate_out, args.slice_plate)
                if fp2 is not None:
                    exp_w = exp[2] - exp[0]
                    exp_h = exp[3] - exp[1]
                    print('BATCH|log|盘%d 校验：预期 %.1fx%.1f，'
                          '实际 %.1fx%.1f' % (plate_no, exp_w, exp_h,
                                              fp2[2] - fp2[0],
                                              fp2[3] - fp2[1]))
                    print('BATCH|log|盘%d 校验 bbox：实际 %s' % (
                        plate_no, [round(v, 1) for v in fp2]))
                    # Bambu 可能把合并盘旋转 90°，宽高对调；
                    # 用排序后的尺寸比较，旋转无关
                    act_w, act_h = fp2[2] - fp2[0], fp2[3] - fp2[1]
                    if tight:
                        # 支撑可超出本体，只查不丢件；
                        # 留 5mm 容差吸收合并盘旋转/圆整误差
                        size_ok = (
                            max(act_w, act_h) >= max(exp_w, exp_h) - gap - 5.0
                            and min(act_w, act_h)
                            >= min(exp_w, exp_h) - gap - 5.0)
                    else:
                        size_ok = (
                            max(act_w, act_h) <= max(exp_w, exp_h) + gap and
                            min(act_w, act_h) <= min(exp_w, exp_h) + gap and
                            max(act_w, act_h) >= max(exp_w, exp_h) - gap and
                            min(act_w, act_h) >= min(exp_w, exp_h) - gap)
                    inside_plate = (
                        fp2[0] >= -gap and fp2[1] >= -gap and
                        fp2[2] <= getattr(args, 'plate_w', 256.0) + gap and
                        fp2[3] <= getattr(args, 'plate_h', 256.0) + gap)
                    verified = size_ok and inside_plate
                    print('BATCH|log|盘%d 校验结果 size_ok=%s inside=%s'
                          % (plate_no, size_ok, inside_plate))
                if not verified:
                    try:
                        os.remove(plate_out)
                    except OSError:
                        pass
                    print('BATCH|log|盘%d 校验未通过，将加大间距重摆' % plate_no)
            except SliceError as e:
                try:
                    os.remove(plate_out)
                except OSError:
                    pass
                print(f'BATCH|log|盘{plate_no} 切片失败（{e}），回退单模型一板')
            if verified:
                emit_param_diff(plate_out, args)
            info = {'plate': plate_no, 'out': plate_out if verified else None,
                    'names': names, 'fill': None, 'verified': verified,
                    'support_g': plate_support_g,
                    'support_used': plate_support_used,
                    'weight_on_g': plate_weight_on,
                    'weight_off_g': plate_weight_off}
            return verified, info

        def reuse_single(idx, plate_no):
            """一盘只有一件时，直接复用前面已经切好的单件产物。

            大件（比如贴着打印板边界的模型）经常是一盘只能放一件。以前
            摆盘阶段会把这些单件重新合并成 STL 再切一遍，方向、参数都没变，
            只是白白多跑一次完整切片。这里把原来的单件 3mf 直接当成一盘，
            最后仍交给 merge_3mf 合成多盘文件；小件同盘摆盘不受影响。

            紧凑模式会为了省占地重新立放，最少支撑模式会改支撑参数，
            这两种情况仍走 process_plate 重切，避免复用错方向/参数。
            """
            r = results[idx]
            out = r.get('out')
            if not out or not os.path.isfile(out):
                return False, None
            try:
                verify_3mf(out, args.slice_plate)
            except Exception as e:                         # noqa: BLE001
                print(f'BATCH|log|盘{plate_no} 复用单片失败（{e}），改为重切')
                return False, None
            emit_param_diff(out, args)
            print('BATCH|log|盘%d 只有 1 个模型，复用已切单片：%s'
                  % (plate_no, r['name']))
            return True, {'plate': plate_no, 'out': out,
                          'names': [r['name']], 'fill': None,
                          'verified': True}

        remaining = list(indices)
        gap = min(args.gap, 6.0) if tight else args.gap
        plate_no = 0
        for _rnd in range(3):
            if not remaining:
                break
            rects = [rect_of(i) for i in remaining]
            # BLF（Bottom-Left）比货架法更紧凑，两种模式都用它；
            # 非紧凑模式的矩形已经含支撑，转 90° 不会改变支撑占用。
            plates = pack.pack_rects_blf(rects, plate=pack_plate,
                                         gap=gap, rotate=True)
            grouped = []
            for pl in plates:
                items = pl.get('items', [])
                if len(items) > 1 or (allow_single and len(items) == 1):
                    grouped.append([
                        (remaining[it[0]], it[1], it[2],
                         it[3] if len(it) > 3 else 0)
                        for it in items])
            if not grouped:
                break
            next_remaining = []
            any_fail = False
            for group in grouped:
                # 盘号只在“成功产出”时递增，失败重试不占号，
                # 保证最终文件连续：摆盘_盘1、摆盘_盘2 …
                if (len(group) == 1 and not tight
                        and not getattr(args, 'min_support', 0)):
                    reused, info = reuse_single(group[0][0], plate_no + 1)
                    if reused:
                        plate_no += 1
                        out_plates.append(info)
                        continue
                verified, info = process_plate(group, gap, plate_no + 1)
                if verified:
                    plate_no += 1
                    out_plates.append(info)
                else:
                    any_fail = True
                    next_remaining.extend(i for i, _, _, _ in group)
            remaining = next_remaining
            if not any_fail:
                break
            gap = min(gap * (1.4 if tight else 1.5),
                      22.0 if tight else 45.0)
            print(f'BATCH|log|增大间距到 {gap:.0f}mm 重试剩余模型')
        return out_plates
    except Exception as e:
        print(f'BATCH|log|摆盘异常（{e}），回退为单模型一板')
        return out_plates


def write_report(out_dir, results, plates):
    ok = sum(1 for r in results if r['ok'])
    file_parts = {}
    for r in results:
        src = r.get('source') or r['path']
        file_parts[src] = max(file_parts.get(src, 0), r.get('parts', 1))
    auto_parts = any(v > 1 for v in file_parts.values())
    plate_by_name = {}
    for pl in plates:
        if pl.get('verified') and pl.get('out'):
            for n in pl.get('names', []):
                plate_by_name.setdefault(n, pl['out'])
    lines = [
        '拓竹助手1.0 - 批量切片报告',
        '=' * 50,
        f'输出目录: {out_dir}',
        f'处理: {len(results)} 个{"零件" if auto_parts else ""}'
        f'（来自 {len(file_parts)} 个文件）   成功: {ok}   '
        f'失败: {len(results) - ok}',
        f'摆盘: {len(plates)} 盘',
        '-' * 50,
    ]
    multi = [(s, n) for s, n in file_parts.items() if n > 1]
    if multi:
        lines.append('多零件文件：')
        for s, n in multi:
            lines.append(f'  {os.path.basename(s)}：{n} 个零件')
        lines.append('-' * 50)
    for r in results:
        status = '成功' if r['ok'] else '失败'
        act = ('；'.join(r['actions'])) if r.get('actions') else '无'
        lines.append(f"[{status}] {r['name']}")
        if (r.get('source')
                and os.path.abspath(r['source']) != os.path.abspath(r['path'])):
            lines.append(f'  来源文件: {r["source"]}')
            lines.append(f'  零件: {os.path.basename(r["path"])}')
        else:
            lines.append(f'  源文件: {r["path"]}')
        if r['ok']:
            if r['name'] in plate_by_name:
                lines.append('  产物: 并入 '
                             f'{os.path.basename(plate_by_name[r["name"]])}')
            else:
                lines.append(f'  产物: {r["out"]}')
            lines.append(f'  自动处理: {act}')
            ms = r.get('min_support') or {}
            b = ms.get('best') or {}
            if b:
                lines.append(
                    '  候选方向: %s（单件试切，支撑 %s g；'
                    '总 %s g，%s）'
                    % (b.get('name') or '-',
                       b.get('support_g') if b.get('support_g') is not None
                       else '未测',
                       b.get('weight_on_g') if b.get('weight_on_g') is not None
                       else '-',
                       _time_text(b.get('print_time_s'))))
        else:
            lines.append(f'  原因: {r["error"]}')
            lines.append(f'  尝试过: {act or "无"}')
    if plates:
        lines.append('-' * 50)
        lines.append('摆盘结果：')
        grouped = {}
        for pl in plates:
            if pl.get('group'):
                grouped.setdefault(pl['group'], []).append(pl)
        if grouped:
            for g, gps in grouped.items():
                merged = next((pl.get('merged_out') for pl in gps
                               if pl.get('merged_out')), '')
                if merged:
                    lines.append(f'  {g}: 多盘文件 {merged}'
                                 f'（{len(gps)} 盘）')
        else:
            merged = next((pl.get('merged_out') for pl in plates
                           if pl.get('merged_out')), '')
            if merged:
                lines.append(f'  多盘文件: {merged}（共 {len(plates)} 盘）')
        for pl in plates:
            tag = '✓' if pl['verified'] else '✗ 已回退'
            fill = f"{pl['fill'] * 100:.0f}%" if pl.get('fill') else '-'
            label = (f"{pl['group']} 盘{pl['plate']}"
                     if pl.get('group') else f"盘{pl['plate']}")
            lines.append(f"  {label} [{tag}] 占用率 {fill}: "
                         f"{'、'.join(pl['names'])}")
            if pl.get('support_g') is not None:
                lines.append(f"    实际支撑: {pl['support_g']:.2f} g")
            if pl.get('out'):
                lines.append(f'    产物: {pl["out"]}')
    # 批量报告也收进 `_报告\`：输出目录根上只留 .3mf（用户 2026-10-16 要求）
    rdir = os.path.join(out_dir, '_报告')
    try:
        os.makedirs(rdir, exist_ok=True)
    except OSError:
        rdir = out_dir
    path = os.path.join(rdir, '切片报告.txt')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return path


def run_batch(args):
    resolve_plate(args)
    folder = os.path.abspath(args.batch)
    if not os.path.isdir(folder):
        raise SliceError(f'batch folder not found: {folder}')
    out_dir = os.path.abspath(args.out_dir or os.path.join(
        os.path.expanduser('~'), 'Desktop', '切片文件'))
    os.makedirs(out_dir, exist_ok=True)
    folder_name = os.path.basename(folder.rstrip('\\/')) or '批量'

    models = scan_models(folder, args.max_depth)
    print(f'BATCH|log|扫描到 {len(models)} 个模型')
    if not models:
        print('BATCH|done|' + json.dumps(
            {'ok': 0, 'fail': 0, 'total': 0, 'report': None, 'plates': 0},
            ensure_ascii=False))
        return
    protected = []
    for model in models:
        info = protected_project_info(model)
        if info:
            protected.append((model, info))
    if protected:
        names = '、'.join(os.path.basename(path) for path, _info in protected)
        print('BATCH|log|受保护的 3MF：%s（保留原颜色、材料、零件绑定）'
              % names)
        for model, _info in protected:
            ensure_project_operation_safe(
                model, args, multiple=(len(models) > 1))
    if (getattr(args, 'preserve_project', 0)
            and len(models) == 1 and models[0].lower().endswith('.3mf')):
        try:
            po = unpack_3mf.project_overrides(
                models[0],
                figurine=unpack_3mf.needs_assembly_export(models[0]))
            if po:
                args.project_overrides = po
                print('BATCH|log|保留 3MF 内嵌项目参数（填充/层高/支撑）')
        except Exception as e:                             # noqa: BLE001
            print('BATCH|log|读取 3MF 项目参数失败（%s），用默认参数'
                  % str(e)[:100])

    # 单个多零件 3MF 往往已经是用户摆好的整盘（例如“一对单盘”）。
    # 默认切法必须原样切这一盘：一旦先拆 raw mesh 再重摆，就会丢
    # build item 的 3.26 倍缩放/镜像/位移，模型尺寸会变。
    src_color_info = (
        unpack_3mf.project_filament_info(models[0])
        if len(models) == 1 and models[0].lower().endswith('.3mf')
        else {'multicolor': False})
    src_is_multicolor = bool(src_color_info.get('multicolor'))
    if (len(models) == 1 and models[0].lower().endswith('.3mf')
            and not args.pack and not args.tight
            and not getattr(args, 'min_support', 0)
            and (not getattr(args, 'figurine_mode', 0)
                 or unpack_3mf.count_plates(models[0]) > 1
                 or src_is_multicolor)
            and (getattr(args, 'clone', 1) or 1) <= 1):
        src = models[0]
        if unpack_3mf.count_meshes(src) > 1:
            base = os.path.splitext(os.path.basename(src))[0]
            out = unique_out(out_dir, base)
            src_plates = unpack_3mf.count_plates(src)
            source_plate_layout = unpack_3mf.plate_layout(src)
            print('BATCH|log|单个多零件 3MF：保留原布局和原始尺寸，'
                  '切片全部 %d 盘' % src_plates)
            assembly_tmp = None
            slice_src = src
            extra_actions = []
            if (not src_is_multicolor
                    and unpack_3mf.needs_assembly_export(src)):
                assembly_tmp = tempfile.mkdtemp(prefix='assembly_')
                try:
                    parts = unpack_3mf.export_printable_build_items(
                        src, assembly_tmp, prefix='assembly')
                    if parts:
                        slice_src = parts[0]
                        extra_actions.append('3MF装配体（排除修改器）')
                        print('BATCH|log|3MF 单装配体：按可打印零件合并，'
                              '排除 modifier/negative')
                except Exception as e:                     # noqa: BLE001
                    print('BATCH|log|3MF 装配体导出失败（%s），尝试原文件'
                          % str(e)[:100])
            try:
                # Bambu CLI 的 0 = 所有盘。只切 1 会丢掉其它盘，
                # 却又因为输入是“原布局”而看起来像成功。
                slice_args = preserved_3mf_slice_args(args, src_plates)
                res = slice_one(slice_src, slice_args, out=out,
                                orient=0, arrange=0)
            finally:
                if assembly_tmp:
                    shutil.rmtree(assembly_tmp, ignore_errors=True)
            if any(row.get('name') for row in source_plate_layout):
                output_plate_layout = unpack_3mf.plate_layout(out)
                src_sig = [
                    (row['plate'], row['name'],
                     sorted(o.get('name') or '' for o in row['objects']))
                    for row in source_plate_layout
                ]
                out_sig = [
                    (row['plate'], row['name'],
                     sorted(o.get('name') or '' for o in row['objects']))
                    for row in output_plate_layout
                ]
                if src_sig != out_sig:
                    raise SliceError(
                        '盘名或分盘内容发生变化，已拒绝输出。'
                        '源盘：%s；输出盘：%s'
                        % ([(p, n) for p, n, _o in src_sig],
                           [(p, n) for p, n, _o in out_sig]))
                print('BATCH|log|盘名与每盘内容核对通过：%d 盘'
                      % len(src_sig))
            emit_param_diff(out, args)
            summary = res.get('summary') or {}
            result = {
                'path': src, 'name': base, 'out': out, 'ok': True,
                'error': None,
                'actions': extra_actions + (res.get('actions') or []),
                'footprint': footprint_of_3mf(out, args.slice_plate),
                'source': src, 'part': 1,
                'parts': unpack_3mf.count_meshes(src),
                'oriented': res.get('oriented_stl'),
                'summary': summary, 'min_support': None,
            }
            plate_rows = [{
                'plate': n, 'out': out, 'names': [base], 'fill': None,
                'verified': True,
                'support_used': summary.get('support_used'),
                'support_g': None,
                'weight_on_g': (summary.get('weight_g')
                                if src_plates == 1 else None),
                'weight_off_g': None,
            } for n in range(1, src_plates + 1)]
            report = write_report(out_dir, [result], plate_rows)
            print('BATCH|done|' + json.dumps({
                'ok': 1, 'fail': 0, 'total': result['parts'],
                'files': 1, 'parts': result['parts'],
                'report': report, 'plates': src_plates,
                'verified_plates': src_plates,
                'pack_feature': '原布局', 'merged_out': out,
                'min_support_models': 0, 'min_support_g': 0,
            }, ensure_ascii=False))
            return

    if args.pack:
        feature = '最省空间' if args.tight else '自动摆盘'
        single_src = models[0] if len(models) == 1 else None
        pack_base = None
        if single_src:
            stem = os.path.splitext(os.path.basename(single_src))[0]
            pack_base = f'{stem}_{feature}'
        else:
            pack_base = f'{folder_name}_{feature}'
        # 摆盘每次重新切：先清掉上次同批次留在输出目录的旧摆盘文件，
        # 避免出现 盘1、盘2、盘1_2… 越积越多
        prefixes = [folder_name + '_盘']
        if pack_base:
            prefixes += [pack_base + '_盘', pack_base + '.']
        removed = []
        for old in os.listdir(out_dir):
            if (any(old.startswith(pr) for pr in prefixes)
                    and old.endswith('.gcode.3mf')
                    and os.path.isfile(os.path.join(out_dir, old))):
                try:
                    os.remove(os.path.join(out_dir, old))
                    removed.append(old)
                except OSError:
                    pass
        if removed:
            print('BATCH|log|已清理旧摆盘文件：' + '、'.join(removed))

    tmp = tempfile.mkdtemp(prefix='bambu_batch_')
    oriented_dir = os.path.join(tmp, 'oriented')
    results = []
    try:
        # ★ 自动摆盘按**零件**摆，不按文件摆：一个 3mf 里有几个 Bambu
        #   拆分后的零件，就拆成几个独立 STL，各自量支撑占地、各自装箱。
        items = []
        print('BATCH|log|逐文件检查零件（Bambu 拆分后的零件）…')
        for si, model in enumerate(models, 1):
            prefer_items = bool(getattr(args, 'figurine_mode', 0))
            parts, declared = split_parts_for_pack(
                model, os.path.join(tmp, 'parts'), si,
                prefer_build_items=prefer_items)
            base = os.path.splitext(os.path.basename(model))[0]
            actual = len(parts)
            part_names = (unpack_3mf.build_item_names(model)
                          if prefer_items and actual == declared else [])
            print('BATCH|log|%s：%d 个零件'
                  % (os.path.basename(model), declared))
            if actual != declared:
                print('BATCH|log|%s：实际拆出 %d 个，按实际数量摆'
                      % (os.path.basename(model), actual))
            for pi, part in enumerate(parts, 1):
                source_name = (part_names[pi - 1]
                               if pi <= len(part_names) else '')
                safe_source_name = unpack_3mf._safe_part_name(source_name)
                display_name = (source_name or
                                (base if actual == 1
                                 else '%s #%d' % (base, pi)))
                items.append({
                    'path': part, 'source': model, 'part': pi,
                    'parts': actual,
                    'source_name': source_name,
                    'figurine_role': None,
                    'volume_mm3': None, 'body_ratio': None,
                    'body_rank': None,
                    'name': display_name,
                    'out_name': (base if actual == 1 else
                                 '%s_%s' % (base, safe_source_name or
                                            'p%d' % pi)),
                })

        if getattr(args, 'figurine_mode', 0):
            by_source = {}
            for item in items:
                by_source.setdefault(item['source'], []).append(item)
            for source, group in by_source.items():
                cls = classify_figurine_parts(
                    source, [item['path'] for item in group],
                    True,
                    body_min_ratio=getattr(
                        args, 'figurine_body_ratio',
                        FIGURINE_BODY_MIN_RATIO))
                if not cls:
                    continue
                for item, row in zip(group, cls['parts']):
                    item['figurine_role'] = row['role']
                    item['volume_mm3'] = row['volume_mm3']
                    item['body_ratio'] = row['ratio']
                    item['body_rank'] = row['body_rank']
                role_text = '、'.join(
                    '%s #%d:%s %.1f mm³ (%.1f%%)'
                    % (os.path.basename(source), item['part'],
                       '主体' if item['figurine_role'] == 'body' else '部件',
                       item['volume_mm3'], item['body_ratio'] * 100)
                    for item in group)
                print('BATCH|log|手办模式按体积分类：%s' % role_text)
                print('BATCH|log|手办主体数：%d（上限 %d）'
                      % (cls['body_count'], FIGURINE_MAX_BODIES))
                if cls.get('warning'):
                    print('BATCH|log|警告：%s' % cls['warning'])

        total = len(items)
        for i, item in enumerate(items, 1):
            model = item['path']
            name = item['name']
            out = unique_out(out_dir, item['out_name'])
            extra = ('' if item['parts'] <= 1 else
                     '（%d 个零件中的第 %d 个）'
                     % (item['parts'], item['part']))
            print(f'BATCH|log|[{i}/{total}] {name}{extra}')
            actions = []
            ok, err, res = False, None, None
            body_pose = None
            try:
                part_args = prepare_split_part_args(
                    args, item.get('source'), model,
                    figurine_role=item.get('figurine_role'))
                if item.get('figurine_role') == 'body':
                    body_pose = body_pose_report(model)
                    print('BATCH|log|%s：主体保留原朝向；接触 %.1f mm²，'
                          '重心在内=%s，悬垂 %.1f mm²，预计支撑 %.2f cm³'
                          % (name,
                             float(body_pose.get('contact_mm2') or 0),
                             body_pose.get('com_inside'),
                             float(body_pose.get('overhang_mm2') or 0),
                             float(body_pose.get(
                                 'support_estimate_cm3') or 0)))
                    actions.append('手办主体：保留原朝向')
                    if body_pose.get('stable') is False:
                        actions.append('手办主体：稳定性警告')
                        print('BATCH|log|警告：%s 原始朝向不稳定，'
                              '按手办规则不改朝向，请人工检查' % name)
                res = slice_one(model, part_args, out=out,
                                keep_oriented_dir=oriented_dir)
                ok = True
                if res and res.get('actions'):
                    actions.extend(res['actions'])
            except SliceError as e:
                err, code = str(e), e.code
                if args.orient and code in (-50, -2):
                    try:
                        actions.append('重试：关闭自动定向')
                        res = slice_one(model, part_args, out=out,
                                        keep_oriented_dir=oriented_dir,
                                        orient=0)
                        ok = True
                    except SliceError as e2:
                        err = str(e2)
                if not ok and model.lower().endswith(('.stp', '.step')):
                    try:
                        actions.append('重试：调整 STEP 网格')
                        res = slice_one(model, part_args, out=out,
                                        keep_oriented_dir=oriented_dir,
                                        mesh_size=1.0)
                        ok = True
                    except SliceError as e3:
                        err = str(e3)
            fp = footprint_of_3mf(out, args.slice_plate) if ok else None
            # ★ 两者可同时开启：最少支撑先选方向，最省空间只负责更紧的
            #   装箱；这里不再二次立放，避免把最少支撑选好的方向推翻。
            if (ok and args.tight and not getattr(args, 'min_support', 0)
                    and (res or {}).get('oriented_stl')):
                # 紧凑摆盘：比较“平放/立放”占地，占地更小就立起来
                opt_dst = os.path.join(
                    oriented_dir, f'opt_{i:02d}_{name}.stl')
                try:
                    if _rotate_for_min_footprint(res['oriented_stl'],
                                                 opt_dst):
                        res['oriented_stl'] = opt_dst
                        actions.append('立放优化')
                        print(f'BATCH|log|{name}: 采用立放（占地更小）')
                except Exception as _e:
                    print(f'BATCH|log|{name}: 立放优化跳过（{_e}）')
            results.append({
                'path': model, 'name': name, 'out': out, 'ok': ok,
                'error': err, 'actions': actions, 'footprint': fp,
                'source': item['source'], 'part': item['part'],
                'parts': item['parts'],
                'figurine_role': item.get('figurine_role'),
                'volume_mm3': item.get('volume_mm3'),
                'body_ratio': item.get('body_ratio'),
                'body_rank': item.get('body_rank'),
                'body_pose': body_pose,
                'oriented': (res or {}).get('oriented_stl'),
                'summary': (res or {}).get('summary'),
                'min_support': (res or {}).get('min_support'),
            })
            if ok and not args.pack:
                emit_param_diff(out, args)
            print('BATCH|progress|%d/%d' % (i, total))

        plates = []
        if args.pack:
            plates = pack_results(results, args, out_dir, tmp, folder_name,
                                  allow_single=True,
                                  tight=bool(args.tight))
            verified = [p for p in plates if p.get('verified')]
            if verified:
                # 摆盘成功：只保留摆好的盘，删掉“每个模型一盘”的中间产物
                # 注意：大件单件复用时，盘本身就是原来的 r['out']，
                # 不能在这里先删掉，否则后面的多盘合并会拿不到源文件。
                keep = {os.path.abspath(p['out']) for p in verified
                        if p.get('out')}
                merged_names = {n for p in verified for n in p.get('names', [])}
                for r in results:
                    if (r.get('ok') and r['name'] in merged_names
                            and r.get('out')
                            and os.path.isfile(r['out'])
                            and os.path.abspath(r['out']) not in keep):
                        try:
                            os.remove(r['out'])
                        except OSError:
                            pass
            else:
                print('BATCH|log|摆盘未能合并出整盘（模型放不下或校验未通过），'
                      '已回退：每个模型单独一盘输出')
                for r in results:
                    if r.get('ok') and r.get('out'):
                        emit_param_diff(r['out'], args)
        else:
            # 不跨文件摆盘，但多零件文件仍要按零件处理：
            # 同一个源文件拆出的零件合成这个源自己的一个（可多盘）3mf。
            groups = {}
            for r in results:
                groups.setdefault(r.get('source') or r['path'], []).append(r)
            for source, group in groups.items():
                if len(group) <= 1:
                    continue
                base = os.path.splitext(os.path.basename(source))[0]
                gp = pack_results(group, args, out_dir, tmp, base,
                                  allow_single=True,
                                  tight=bool(args.tight))
                good = [p for p in gp
                        if p.get('verified') and p.get('out')
                        and os.path.isfile(p['out'])]
                if not good:
                    print('BATCH|log|%s：零件合盘未通过，保留逐零件产物'
                          % os.path.basename(source))
                    continue
                suffix = '_最省空间' if args.tight else ''
                final = os.path.join(out_dir, base + suffix + '.gcode.3mf')
                try:
                    if len(good) == 1:
                        os.replace(good[0]['out'], final)
                        good[0]['out'] = final
                    else:
                        merge_3mf.merge_3mf(
                            [p['out'] for p in good], final)
                        for idx in range(1, len(good) + 1):
                            verify_3mf(final, idx)
                        for p in good:
                            try:
                                os.remove(p['out'])
                            except OSError:
                                pass
                            p['out'] = final
                    for p in gp:
                        p['merged_out'] = final
                        p['group'] = base
                    plates.extend(gp)
                    # 零件自己的中间切片文件已被合盘文件替代
                    for r in group:
                        try:
                            if r.get('out') and os.path.isfile(r['out']):
                                os.remove(r['out'])
                        except OSError:
                            pass
                    print('BATCH|log|%s：%d 个零件 → %d 盘合成一个文件 %s'
                          % (os.path.basename(source), len(group), len(good),
                             os.path.basename(final)))
                except Exception as _e:                     # noqa: BLE001
                    print('BATCH|log|%s：零件合盘失败，保留逐零件产物（%s）'
                          % (os.path.basename(source), str(_e)[:120]))
        if not args.pack and not plates:
            # 不摆盘时 plates 一直是空的，报告会误写“0 盘”；给每个成功
            # 产物补一条报告用的盘记录，UI 才知道实际有 1 盘/几盘。
            for i, r in enumerate(
                    [x for x in results if x.get('ok')
                     and x.get('out') and os.path.isfile(x['out'])], 1):
                msb = ((r.get('min_support') or {}).get('best') or {})
                summary = r.get('summary') or {}
                plates.append({
                    'plate': i, 'out': r['out'], 'names': [r['name']],
                    'fill': None, 'verified': True,
                    'support_used': summary.get('support_used'),
                    'support_g': msb.get('support_g'),
                    'weight_on_g': summary.get('weight_g'),
                    'weight_off_g': msb.get('weight_off_g'),
                })
        merged_out = ''
        if args.pack and plates:
            good = [p for p in plates
                    if p.get('verified') and p.get('out')
                    and os.path.isfile(p['out'])]
            if good:
                # ★ 自动摆盘的产出是**一个 3mf 文件、里面多盘**，不是
                #   “盘1一个文件、盘2一个文件”。Bambu 的一个 3mf 本来就
                #   可以装多块盘，用户要的就是这个。
                final = os.path.join(out_dir, pack_base + '.gcode.3mf')
                try:
                    if len(good) == 1:
                        os.replace(good[0]['out'], final)
                        good[0]['out'] = final
                    else:
                        merge_3mf.merge_3mf(
                            [p['out'] for p in good], final)
                        # 逐盘校验，别把一个结构坏掉的多盘文件发出去
                        for idx in range(1, len(good) + 1):
                            verify_3mf(final, idx)
                        for p in good:
                            try:
                                os.remove(p['out'])
                            except OSError:
                                pass
                            p['out'] = final
                    for p in plates:
                        p['merged_out'] = final
                    merged_out = final
                    print('BATCH|log|%s：%d 盘已合成一个文件 %s'
                          % (feature, len(good), os.path.basename(final)))
                except Exception as _e:                     # noqa: BLE001
                    print('BATCH|log|多盘合并失败，保留分盘文件：%s'
                          % str(_e)[:160])
                    try:
                        if os.path.isfile(final):
                            os.remove(final)
                    except OSError:
                        pass
                    # 回退：至少保持旧的分盘命名，别丢产物
                    for idx, pl in enumerate(good, 1):
                        old = pl.get('out')
                        if old and os.path.isfile(old):
                            new = os.path.join(
                                out_dir,
                                '%s_盘%d.gcode.3mf' % (pack_base, idx))
                            try:
                                os.replace(old, new)
                                pl['out'] = new
                            except OSError:
                                pass
        report = write_report(out_dir, results, plates)
        ok_n = sum(1 for r in results if r['ok'])
        ms_rows = [r['min_support']['best'] for r in results
                   if r.get('min_support') and r['min_support'].get('best')]
        plate_ms = [p for p in plates
                    if p.get('support_used') is not None]
        if plate_ms and all(
                (not p.get('support_used'))
                or p.get('support_g') is not None for p in plate_ms):
            # 有合盘结果时，以整盘“开/关支撑”称重为准；单件候选值
            # 只用于选方向，不能直接拿来当最终报告。
            ms_g = sum(float(p.get('support_g') or 0)
                       for p in plate_ms if p.get('support_used'))
        else:
            ms_g = sum(float(b.get('support_g') or 0) for b in ms_rows)
        failed_rows = [
            '%s：%s' % (row.get('name') or row.get('path'), row.get('error'))
            for row in results if not row.get('ok')
        ]
        if failed_rows:
            diag = _append_diagnostic(
                args, '批量结果',
                '\n'.join(failed_rows[:30])
                + ('\n…其余 %d 项见切片报告' % (len(failed_rows) - 30)
                   if len(failed_rows) > 30 else ''))
            if diag:
                print('BATCH|log|诊断文件：' + diag)
        print('BATCH|done|' + json.dumps({
            'ok': ok_n, 'fail': total - ok_n, 'total': total,
            'files': len({r.get('source') or r['path'] for r in results}),
            'parts': total,
            'report': report, 'plates': len(plates),
            'verified_plates': sum(1 for p in plates if p['verified']),
            'pack_feature': feature if args.pack else '',
            'merged_out': merged_out,
            'min_support_models': len(ms_rows),
            'min_support_g': round(ms_g, 2),
        }, ensure_ascii=False))
    finally:
        if not args.keep_temp:
            shutil.rmtree(tmp, ignore_errors=True)


def _layout_output_path(args, models):
    if args.out:
        return os.path.abspath(args.out)
    out_dir = os.path.abspath(args.out_dir or os.path.join(
        os.path.expanduser('~'), 'Desktop', '切片文件'))
    if len(models) == 1:
        stem = os.path.splitext(os.path.basename(models[0]))[0]
    else:
        stem = (os.path.basename(os.path.dirname(models[0])) or '批量') \
            + '_摆盘'
    return os.path.join(out_dir, stem + '_摆盘.3mf')


def _repair_layout_metadata(path):
    """Bambu 导出列表型字段时会写入未转义引号，先修复 XML。"""
    with zipfile.ZipFile(path) as archive:
        if 'Metadata/model_settings.config' not in archive.namelist():
            return False
        names = archive.namelist()
        data = {
            name: archive.read(name) for name in names
        }
    text = data['Metadata/model_settings.config'].decode('utf-8')
    pattern = re.compile(
        r'(<metadata\b[^>]*\bvalue=")(.*)("\s*/>)')

    def repair_line(line):
        return pattern.sub(
            lambda match: (
                match.group(1)
                + match.group(2).replace('"', '&quot;')
                + match.group(3)
            ),
            line,
        )

    repaired = '\n'.join(
        repair_line(line) for line in text.split('\n'))
    if repaired == text:
        return False
    data['Metadata/model_settings.config'] = repaired.encode('utf-8')
    fd, temporary = tempfile.mkstemp(
        prefix='.layout_fixed_', suffix='.3mf',
        dir=os.path.dirname(path))
    os.close(fd)
    try:
        with zipfile.ZipFile(
                temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                archive.writestr(name, data[name])
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return True


def _check_layout_by_slicing(exe, model_path, plate_count, settings=None,
                             filament=None, bed_type=None):
    """把临时布局完整试切一遍，确认不会等到交付后才报错。"""
    print('BATCH|log|正在用切片引擎预检可编辑 3MF…', flush=True)
    with tempfile.TemporaryDirectory(prefix='layout_check_') as check_dir:
        expected_plates = int(plate_count or 1)

        def command_for(slice_option, proof, check_input):
            cmd = [
                exe,
                '--slice', str(slice_option),
                '--arrange', '0',
                '--orient', '0',
            ]
            if settings:
                cmd += [
                    '--load-settings', settings,
                    '--load-filaments', filament or '',
                    '--curr-bed-type', bed_type or 'Textured PEI Plate',
                ]
            return cmd + ['--export-3mf', proof, check_input]

        result = None
        for attempt in range(3):
            check_input = os.path.join(
                check_dir, 'layout_check_%d.3mf' % (attempt + 1))
            shutil.copy2(model_path, check_input)
            proof = os.path.join(
                check_dir,
                'verification_%d.gcode.3mf' % (attempt + 1))
            cmd = command_for(
                '0' if expected_plates > 1 else '1', proof, check_input)
            print('LAYOUT CHECK RUN:', ' '.join(cmd))
            result = run_cli(
                cmd, capture_output=True, text=True, timeout=1800)
            print(
                'LAYOUT CHECK EXIT: %s%s'
                % (result.returncode,
                   '（重试 %d/3）' % (attempt + 1)
                   if attempt else ''))
            if result.returncode == 0 and os.path.isfile(proof):
                break
            if attempt < 2:
                print('BATCH|log|切片预检遇到瞬时进程错误，自动重试…')
                time.sleep(3.0)
        if result.returncode != 0 or not os.path.isfile(proof):
            all_detail = (
                result.stderr or result.stdout or '')[-800:].strip()
            all_why = explain_cli_failure(
                result.stdout or '', result.stderr or '',
                result.returncode)
            print(
                'BATCH|log|全盘切片模式失败，改为逐盘真实切片校验…',
                flush=True)
            plate_details = []
            for plate_no in range(1, expected_plates + 1):
                plate_proof = ''
                plate_result = None
                for attempt in range(3):
                    plate_input = os.path.join(
                        check_dir,
                        'layout_plate_%02d_%d.3mf'
                        % (plate_no, attempt + 1))
                    shutil.copy2(model_path, plate_input)
                    plate_proof = os.path.join(
                        check_dir,
                        'verification_plate_%02d_%d.gcode.3mf'
                        % (plate_no, attempt + 1))
                    cmd = command_for(
                        str(plate_no), plate_proof, plate_input)
                    print(
                        'LAYOUT CHECK PLATE %d RUN: %s'
                        % (plate_no, ' '.join(cmd)),
                        flush=True)
                    plate_result = run_cli(
                        cmd, capture_output=True, text=True, timeout=1800)
                    print(
                        'LAYOUT CHECK PLATE %d EXIT: %s%s'
                        % (plate_no, plate_result.returncode,
                           '（重试 %d/3）' % (attempt + 1)
                           if attempt else ''),
                        flush=True)
                    if (plate_result.returncode == 0
                            and os.path.isfile(plate_proof)):
                        break
                    if attempt < 2:
                        print(
                            'BATCH|log|第 %d 盘切片预检遇到瞬时进程错误，'
                            '自动重试…' % plate_no,
                            flush=True)
                        time.sleep(1.5)
                if (plate_result.returncode != 0
                        or not os.path.isfile(plate_proof)):
                    plate_detail = (
                        plate_result.stderr or plate_result.stdout
                        or '')[-800:].strip()
                    plate_why = explain_cli_failure(
                        plate_result.stdout or '',
                        plate_result.stderr or '',
                        plate_result.returncode)
                    all_reason = (
                        all_why or all_detail
                        or 'Bambu 没有生成全盘校验切片（exit=%s）'
                        % result.returncode)
                    plate_reason = (
                        plate_why or plate_detail
                        or 'Bambu 没有生成第 %d 盘校验切片（exit=%s）'
                        % (plate_no, plate_result.returncode))
                    raise SliceError(
                        '可编辑 3MF 切片预检失败：全盘模式失败（%s）；'
                        '逐盘后备在盘 %d 也失败（%s）'
                        % (all_reason, plate_no, plate_reason),
                        plate_result.returncode or 1)
                try:
                    detail = verify_3mf(plate_proof, plate_no)
                except Exception as exc:               # noqa: BLE001
                    raise SliceError(
                        '可编辑 3MF 逐盘预检第 %d 盘结果无效：%s'
                        % (plate_no, exc)) from exc
                detail['plate'] = plate_no
                plate_details.append(detail)
            print(
                'LAYOUT CHECK VERIFIED: %d 盘（逐盘后备校验）'
                % expected_plates)
            return {
                'plates': expected_plates,
                'plate_details': plate_details,
                'slice_check_mode': 'plate_by_plate',
            }

        try:
            summary = verify_3mf(proof, 0)
        except Exception as exc:                       # noqa: BLE001
            raise SliceError(
                '可编辑 3MF 切片预检结果无效：%s' % exc) from exc
        actual_plates = int(summary.get('plates') or 0)
        if expected_plates != actual_plates:
            raise SliceError(
                '可编辑 3MF 切片预检盘数不一致：布局 %d 盘，切片 %d 盘'
                % (expected_plates, actual_plates))
        print('LAYOUT CHECK VERIFIED: %d 盘' % actual_plates)
        plate_details = []
        for plate_no in range(1, actual_plates + 1):
            detail = verify_3mf(proof, plate_no)
            detail['plate'] = plate_no
            plate_details.append(detail)
        summary['plate_details'] = plate_details
        summary['slice_check_mode'] = 'all_plates'
        return summary


def check_layout_by_slicing(exe, model_path, plate_count, settings=None,
                            filament=None, bed_type=None):
    """在全新助手子进程中调用 Bambu，隔离连续试切后的进程状态。"""
    with tempfile.TemporaryDirectory(prefix='layout_check_job_') as work:
        job_path = os.path.join(work, 'job.json')
        result_path = os.path.join(work, 'result.json')
        with open(job_path, 'w', encoding='utf-8') as handle:
            json.dump({
                'exe': exe,
                'model': model_path,
                'plates': int(plate_count),
                'settings': settings,
                'filament': filament,
                'bed_type': bed_type,
            }, handle, ensure_ascii=False)
        if getattr(sys, 'frozen', False):
            helper = sys.executable
        else:
            app_dir = os.path.dirname(
                os.path.dirname(os.path.abspath(__file__)))
            helper = os.path.join(app_dir, '切片软件.pyw')
        cmd = [
            sys.executable, helper,
            '--layout-check', job_path, result_path,
        ]
        result = run_cli(
            cmd, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=2100,
            creationflags=0x08000000)
        payload = {}
        if os.path.isfile(result_path):
            try:
                with open(result_path, encoding='utf-8') as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                payload = {}
        if not payload.get('ok'):
            detail = (
                payload.get('error')
                or (result.stderr or result.stdout or '')[-800:].strip()
                or '独立切片预检进程异常退出')
            raise SliceError(
                '可编辑 3MF 切片预检失败：%s' % detail,
                result.returncode or 1)
        return payload.get('summary') or {}


def run_layout_export(args):
    """只摆盘并导出可编辑 3MF，不生成 G-code。"""
    if args.batch:
        models = scan_models(args.batch, args.max_depth)
    elif args.model:
        models = [os.path.abspath(args.model)]
    else:
        raise SliceError('摆盘需要模型文件或文件夹')
    if not models:
        raise SliceError('没有找到可摆盘模型')
    protected = [
        (model, protected_project_info(model)) for model in models
        if protected_project_info(model)
    ]
    if protected and len(models) > 1:
        raise SliceError(
            '多色/多材料 3MF 不能和其它文件混合摆盘；'
            '请单独导出受保护工程。')
    out = _layout_output_path(args, models)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fd, candidate = tempfile.mkstemp(
        prefix='.layout_candidate_', suffix='.3mf',
        dir=os.path.dirname(out))
    os.close(fd)
    os.remove(candidate)
    source_states = {model: _source_stat(model) for model in models}
    exe = args.exe or find_bambu_exe([])
    if not exe:
        raise SliceError('Bambu Studio 未安装或找不到')
    cmd = [exe, '--export-3mf', candidate]
    if protected:
        # 受保护工程保持原始朝向、布局、颜色和材料绑定。
        cmd += ['--arrange', '0', '--orient', '0']
    else:
        resolve_plate(args)
        profile_args = argparse.Namespace(
            profiles_root=args.profiles_root,
            machine=args.machine,
            process=args.process,
            filament=args.filament,
        )
        for note in resolve_compatible_presets(profile_args):
            print('LAYOUT PRESET:', note)
        machine = profile_args.machine
        process = profile_args.process
        filament = profile_args.filament
        with tempfile.TemporaryDirectory(prefix='layout_presets_') as work:
            paths = flatten_presets.prepare_preset_root(
                args.profiles_root, os.path.join(work, 'presetroot'),
                machine, process, filament)
            cmd += [
                '--load-settings',
                paths['machine'] + ';' + paths['process'],
                '--load-filaments', paths['filament'],
                '--curr-bed-type', args.bed_type,
                '--arrange', str(args.arrange),
                '--orient', str(args.orient),
            ]
            cmd += models
            print('LAYOUT RUN:', ' '.join(cmd))
            result = run_cli(cmd, capture_output=True, text=True)
            if result.returncode != 0 or not os.path.isfile(candidate):
                detail = (
                    result.stderr or result.stdout or '')[-500:].strip()
                try:
                    os.remove(candidate)
                except OSError:
                    pass
                raise SliceError(
                    '摆盘导出失败：%s' % (detail or '没有输出文件'),
                    result.returncode or 1)
            if _repair_layout_metadata(candidate):
                print('BATCH|log|已修复导出 3MF 的元数据转义')
            layout_plates = unpack_3mf.count_plates(candidate)
            try:
                check_layout_by_slicing(
                    exe, candidate, layout_plates,
                    settings=paths['machine'] + ';' + paths['process'],
                    filament=paths['filament'],
                    bed_type=args.bed_type)
            except Exception:
                try:
                    os.remove(candidate)
                except OSError:
                    pass
                raise
    if protected:
        cmd += models
        print('LAYOUT RUN:', ' '.join(cmd))
        result = run_cli(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not os.path.isfile(candidate):
            detail = (result.stderr or result.stdout or '')[-500:].strip()
            try:
                os.remove(candidate)
            except OSError:
                pass
            raise SliceError(
                '摆盘导出失败：%s' % (detail or '没有输出文件'),
                result.returncode or 1)
        if _repair_layout_metadata(candidate):
            print('BATCH|log|已修复导出 3MF 的元数据转义')
        layout_plates = unpack_3mf.count_plates(candidate)
        try:
            check_layout_by_slicing(
                exe, candidate, layout_plates,
                bed_type=args.bed_type)
        except Exception:
            try:
                os.remove(candidate)
            except OSError:
                pass
            raise
    print('LAYOUT EXIT:', result.returncode)
    if result.returncode != 0 or not os.path.isfile(candidate):
        detail = (result.stderr or result.stdout or '')[-500:].strip()
        try:
            os.remove(candidate)
        except OSError:
            pass
        raise SliceError('摆盘导出失败：%s' % (detail or '没有输出文件'),
                         result.returncode or 1)
    with zipfile.ZipFile(candidate) as archive:
        names = archive.namelist()
    if any(name.lower().endswith('.gcode') for name in names):
        try:
            os.remove(candidate)
        except OSError:
            pass
        raise SliceError('摆盘输出错误：通用 3MF 里包含 G-code')
    for model, state in source_states.items():
        if state is not None and _source_stat(model) != state:
            try:
                os.remove(candidate)
            except OSError:
                pass
            raise SliceError('摆盘过程中源文件被修改：%s'
                             % os.path.basename(model))
    if protected:
        try:
            unpack_3mf.verify_color_bindings(
                protected[0][0], candidate)
        except Exception:
            try:
                os.remove(candidate)
            except OSError:
                pass
            raise
    plates = unpack_3mf.count_plates(candidate)
    os.replace(candidate, out)
    print('LAYOUT VERIFIED')
    print('OUTPUT:', out)
    print('BATCH|done|' + json.dumps({
        'ok': len(models), 'fail': 0, 'total': len(models),
        'files': len(models), 'parts': len(models),
        'report': None, 'plates': plates,
        'verified_plates': plates, 'pack_feature': '摆盘',
        'merged_out': out, 'min_support_models': 0,
        'min_support_g': 0, 'layout_only': True,
        'slice_checked': True,
    }, ensure_ascii=False))
    return out


def run_clone(model, args, count):
    """一个模型打 count 份：先拆零件，每个零件克隆 N 份，支撑感知装箱。"""
    resolve_plate(args)
    ensure_project_operation_safe(model, args)
    tmp = tempfile.mkdtemp(prefix='bambu_clone_')
    try:
        oriented_dir = os.path.join(tmp, 'oriented')
        prefer_items = bool(getattr(args, 'figurine_mode', 0))
        parts, declared = split_parts_for_pack(
            model, os.path.join(tmp, 'parts'), 1,
            prefer_build_items=prefer_items)
        if not parts:
            raise SliceError('模型拆零件后为空，克隆失败')
        print('BATCH|log|%s：%d 个零件（克隆 %d 份）'
              % (os.path.basename(model), len(parts), count))
        if declared != len(parts):
            print('BATCH|log|%s：预期 %d 个零件，实际拆出 %d 个'
                  % (os.path.basename(model), declared, len(parts)))
        part_names = (unpack_3mf.build_item_names(model)
                      if prefer_items and declared == len(parts) else [])
        base = os.path.splitext(os.path.basename(model))[0]
        out_dir = (os.path.dirname(os.path.abspath(args.out)) if args.out
                   else os.path.join(os.path.expanduser('~'), 'Desktop',
                                     '切片文件'))
        classification = classify_figurine_parts(
            model, parts, bool(getattr(args, 'figurine_mode', 0)),
            body_min_ratio=getattr(
                args, 'figurine_body_ratio', FIGURINE_BODY_MIN_RATIO))
        role_rows = (classification or {}).get('parts') or [
            {'role': None, 'volume_mm3': None, 'ratio': None,
             'body_rank': None} for _ in parts]
        if classification:
            print('BATCH|log|手办主体数：%d（上限 %d）'
                  % (classification['body_count'], FIGURINE_MAX_BODIES))
            if classification.get('warning'):
                print('BATCH|log|警告：%s' % classification['warning'])
        results = []
        for pi, part in enumerate(parts, 1):
            single = os.path.join(tmp, 'part_%d.gcode.3mf' % pi)
            role_row = role_rows[pi - 1]
            role = role_row.get('role')
            part_args = prepare_split_part_args(
                args, model, part, figurine_role=role)
            actions = ['手办主体：保留原朝向'] if role == 'body' else []
            body_pose = body_pose_report(part) if role == 'body' else None
            if body_pose and body_pose.get('stable') is False:
                actions.append('手办主体：稳定性警告')
            res = slice_one(part, part_args, out=single,
                            keep_oriented_dir=oriented_dir)
            fp = footprint_of_3mf(single, args.slice_plate)
            oriented = res.get('oriented_stl')
            if not fp or not oriented:
                raise SliceError('无法测量零件占地，克隆失败')
            actions.extend(res.get('actions') or [])
            # 两者同时开启时，最少支撑负责方向，最省空间负责紧凑装箱。
            if (role != 'body'
                    and args.tight and not getattr(args, 'min_support', 0)
                    and oriented):
                opt_dst = os.path.join(oriented_dir, 'opt_part_%d.stl' % pi)
                try:
                    if _rotate_for_min_footprint(oriented, opt_dst):
                        oriented = opt_dst
                        actions.append('立放优化')
                except Exception:
                    pass
            for ci in range(count):
                source_name = (part_names[pi - 1]
                               if pi <= len(part_names) else '')
                name = (f'{source_name or base} #{ci + 1}'
                        if source_name or len(parts) > 1
                        else f'{base} #{ci + 1}')
                results.append({
                    'ok': True, 'footprint': fp, 'oriented': oriented,
                    'name': name, 'path': part, 'out': single,
                    'error': None, 'actions': actions + ['clone'],
                    'summary': res.get('summary'),
                    'source': model, 'part': pi, 'parts': len(parts),
                    'source_name': source_name,
                    'figurine_role': role,
                    'volume_mm3': role_row.get('volume_mm3'),
                    'body_ratio': role_row.get('ratio'),
                    'body_rank': role_row.get('body_rank'),
                    'body_pose': body_pose})
        plates = pack_results(results, args, out_dir, tmp, base,
                              allow_single=True, tight=bool(args.tight))
        if not plates:
            if args.tight:
                raise SliceError('克隆摆盘未通过校验（已自动选底面摆放）：'
                                 '请减少数量后再试')
            raise SliceError(
                '克隆摆盘未通过校验：已按自动选底面方向摆放，'
                f'放不下 {count} 个；请减少数量后再试')
        final = args.out or os.path.join(out_dir, f'{base}_x{count}.gcode.3mf')
        good = [p for p in plates
                if p.get('verified') and p.get('out')
                and os.path.isfile(p['out'])]
        if not good:
            raise SliceError('克隆摆盘没有通过校验的盘')
        if len(good) == 1:
            if os.path.abspath(good[0]['out']) != os.path.abspath(final):
                shutil.copyfile(good[0]['out'], final)
        else:
            merge_3mf.merge_3mf([p['out'] for p in good], final)
            for idx in range(1, len(good) + 1):
                verify_3mf(final, idx)
            for p in good:
                try:
                    if os.path.abspath(p['out']) != os.path.abspath(final):
                        os.remove(p['out'])
                except OSError:
                    pass
            print('CLONE MERGED: %d plates -> %s' % (len(good), final))
        print('OUTPUT VERIFIED')
        print('OUTPUT:', final)
        print('CLONE PLATES:', len(plates))
        return final
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument('model', nargs='?')
    ap.add_argument('--out')
    ap.add_argument('--out-dir')
    ap.add_argument('--batch', help='批量切片：输入文件夹路径')
    ap.add_argument('--pack', type=int, default=0,
                    help='1 = 支撑感知摆盘（多模型一盘）')
    ap.add_argument('--tight', type=int, default=0,
                    help='1 = 紧致摆盘：按模型本体占地装箱，支撑可互相重叠，'
                         '只保证不压本体；模型仍先自动选底面。'
                         '0 = 保守：按含支撑占地装箱（默认）')
    ap.add_argument('--gap', type=float, default=15.0, help='摆盘安全边距 mm')
    ap.add_argument('--max-depth', type=int, default=3, help='递归扫描深度')
    ap.add_argument('--mesh-size', type=float, default=2.0,
                    help='STEP 网格尺寸上限')
    ap.add_argument('--exe')
    # ★ 这里原来写死的是开发机的 D:\Bambu Studio —— 用户装到
    #   C:\Program Files 就 FileNotFoundError 直接崩（真实反馈）。
    #   现在留空，运行时自动找。
    ap.add_argument('--profiles-root', default='')
    ap.add_argument('--machine')
    ap.add_argument('--process')
    ap.add_argument('--filament')
    ap.add_argument('--bed-type', default='Textured PEI Plate')
    ap.add_argument('--max-size', type=float, default=0.0,
                    help='允许缩放时的目标上限（0 = 按打印板自动）；'
                         '默认不缩放')
    ap.add_argument('--allow-scale', type=int, default=0,
                    help='1 = 模型超界时允许自动缩小；默认 0，绝不改尺寸')
    ap.add_argument('--plate-size', type=float, default=0.0,
                    help='打印板尺寸（0 = 按所选机型自动，如 P1S=256, '
                         'H2S=340x320）')
    ap.add_argument('--slice-plate', type=int, default=1)
    ap.add_argument('--process-override')
    ap.add_argument('--adaptive-scarf', type=int, default=0,
                    help='1 = 按打印摆放下的外壁长度选择 5/6/8/10/12/15 mm '
                         '斜拼长度；需配合隐藏 Z 缝参数')
    ap.add_argument('--figurine-mode', type=int, default=0,
                    help='1 = 左侧“手办模式”：主体保留原朝向，'
                         '并关闭最少支撑/最省空间')
    ap.add_argument('--daily-face-orient', type=int, default=0,
                    help='兼容旧参数；已停用，不再执行自定义最大平面判断')
    ap.add_argument('--preserve-project', type=int, default=0,
                    help='1 = 单个 3MF 有内嵌项目参数时优先沿用其填充/层高')
    ap.add_argument('--part-face-orient', type=int, choices=(0, 1),
                    default=None,
                    help='3MF 拆件后是否让 Bambu 逐件自动朝向；'
                         '0 = 保留拆件时的原始朝向')
    ap.add_argument('--figurine-body-ratio', type=float, default=0.60,
                    help='手办模式下，第二主体相对最大主体的最小体积比例 '
                         '(默认 0.60)')
    ap.add_argument('--orient', type=int, default=1,
                    help='0 = 不定向；1 = 使用 Bambu 自带自动朝向；'
                         '2 = Bambu 自动定向')
    ap.add_argument('--min-support', type=int, default=0, choices=(0, 2),
                    help='最少支撑：0=关闭；2=精准（前几个方向真实切片称重）。'
                         '快速模式（只估方向）留到下一期。')
    ap.add_argument('--arrange', type=int, default=2)
    ap.add_argument('--clone', type=int, default=1,
                    help='一个模型打印多份（克隆 + 支撑感知自动摆盘）')
    ap.add_argument('--keep-temp', action='store_true')
    ap.add_argument('--layout-only', type=int, default=0,
                    help='1 = 只摆盘并导出通用 .3mf，不执行切片')
    ap.add_argument('--no-check', type=int, default=0,
                    help='1 = 让 Bambu 跳过 gcode 走线冲突检查'
                         '（紧凑摆盘允许支撑互相重叠时要用）')
    ap.add_argument('--support-gap', type=float, default=0.0,
                    help='紧凑摆盘时给"支撑"留的余量（每边 mm）。'
                         '0 = 支撑可互相重叠（软件端默认，极限紧凑）；'
                         '3 = 支撑之间也留距离，能过 Bambu 2.07 的走线冲突检查')
    return ap


def main():
    args = build_parser().parse_args()
    disabled = enforce_figurine_mode(args)
    if disabled:
        print('BATCH|log|复杂手办模式：已自动关闭%s，'
              '保持普通支撑和原始朝向' % '、'.join(disabled))
    # 预设目录没显式给（用户机器上肯定没给）→ 自动找。找不到就说人话，
    # 不要甩 FileNotFoundError 的堆栈（真实用户就是这么崩的）。
    if not args.profiles_root:
        args.profiles_root = find_profiles_root()
    if not args.profiles_root:
        print('ERROR: 没找到 Bambu Studio 的预设目录（resources/profiles/BBL）。')
        print('       请确认已安装 Bambu Studio；装了还是在别的盘，')
        print('       就在软件端里手动指定：--profiles-root "X:\\...\\resources\\profiles\\BBL"')
        sys.exit(3)
    print('BATCH|status|正在检查文件和运行环境', flush=True)
    try:
        preflight_command(args)
    except SliceError as exc:
        print('BATCH|log|批量失败：预检未通过：%s' % exc)
        sys.exit(exc.code or 1)
    if getattr(args, 'layout_only', 0):
        try:
            run_layout_export(args)
        except SliceError as e:
            _append_diagnostic(args, '布局输出', str(e))
            print('ERROR:', e)
            sys.exit(e.code or 1)
        return
    if args.batch:
        try:
            run_batch(args)
        except SliceError as e:
            _append_diagnostic(args, '批量处理', str(e))
            print(f'BATCH|log|批量失败：{e}')
            sys.exit(1)
        return
    if not args.model:
        sys.exit('model required (或使用 --batch <文件夹>)')
    if (args.preserve_project
            and str(args.model).lower().endswith('.3mf')):
        po = unpack_3mf.project_overrides(
            args.model,
            figurine=unpack_3mf.needs_assembly_export(args.model))
        if po:
            args.project_overrides = po
    try:
        if args.clone and args.clone > 1:
            run_clone(os.path.abspath(args.model), args, args.clone)
            return
        slice_one(os.path.abspath(args.model), args, out=args.out)
    except SliceError as e:
        _append_diagnostic(args, '切片', str(e))
        print('ERROR:', e)
        sys.exit(e.code or 1)


if __name__ == '__main__':
    main()
