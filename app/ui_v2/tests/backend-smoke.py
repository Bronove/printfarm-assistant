# -*- coding: utf-8 -*-
"""V2 后端复用测试：解析和命令构造必须继续使用原版规则。"""

import os
import json
import hashlib
import shutil
import sys
import tempfile
import time
import atexit
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import service


HAS_BAMBU_PROFILES = bool(service.CORE.app._profiles_root())


SETTINGS = {
    "printer": "Bambu Lab H2S",
    "material": "PLA",
    "bedType": "Textured PEI Plate",
    "layerHeight": "0.16",
    "infill": "15",
    "pattern": "grid",
    "supportMode": "tree_plate",
    "autoArrange": True,
    "orientation": True,
    "tightPacking": False,
    "minSupport": False,
    "clone": "1",
    "outputMode": "gcode",
    "maxColors": "4",
    "multicolorStrategy": "zero_flush",
    "targetHours": "4",
    "hideSeam": True,
    "topIroning": True,
}


def check(label, condition, detail=""):
    print(("  OK   " if condition else "  FAIL ") + label
          + (": " + detail if detail and not condition else ""))
    return bool(condition)


def _generated_probe_stl():
    work = tempfile.mkdtemp(prefix="printfarm_public_fixture_")
    atexit.register(shutil.rmtree, work, True)
    path = os.path.join(work, "probe.stl")
    facets = []
    vertices = (
        (0.0, 0.0, 0.0), (20.0, 0.0, 0.0), (0.0, 20.0, 0.0),
        (20.0, 20.0, 0.0), (0.0, 0.0, 10.0), (20.0, 0.0, 10.0),
        (0.0, 20.0, 10.0), (20.0, 20.0, 10.0),
    )
    triangles = (
        (0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6),
        (0, 1, 4), (1, 5, 4), (2, 6, 3), (3, 6, 7),
        (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5),
    )
    for a, b, c in triangles:
        facets.append(
            "  facet normal 0 0 0\n"
            "    outer loop\n"
            f"      vertex {vertices[a][0]} {vertices[a][1]} {vertices[a][2]}\n"
            f"      vertex {vertices[b][0]} {vertices[b][1]} {vertices[b][2]}\n"
            f"      vertex {vertices[c][0]} {vertices[c][1]} {vertices[c][2]}\n"
            "    endloop\n"
            "  endfacet\n"
        )
    with open(path, "w", encoding="ascii", newline="\n") as handle:
        handle.write("solid printfarm_probe\n")
        handle.writelines(facets)
        handle.write("endsolid printfarm_probe\n")
    return path


def _generated_multicolor_3mf():
    work = tempfile.mkdtemp(prefix="printfarm_multicolor_fixture_")
    atexit.register(shutil.rmtree, work, True)
    path = os.path.join(work, "multicolor_probe.3mf")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/'
                'package/2006/content-types">'
                '<Default Extension="model" ContentType="application/'
                'vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                '<Default Extension="config" ContentType="text/plain"/>'
                "</Types>"
            ),
        )
        archive.writestr(
            "Metadata/project_settings.config",
            "machine=Bambu Lab P2S 0.4 nozzle\n",
        )
    return path


def main():
    model = os.path.join(
        ROOT, "..", "test_files", "pure_probe", "_color_meshes", "slot_06.stl"
    )
    model = os.path.abspath(model)
    if not os.path.isfile(model):
        model = _generated_probe_stl()
    passed = []

    parsed = service.CORE.parse(
        "H2S，层高0.16，15%网格，树状支撑仅打印板，外墙速度35，wall_loops=4",
        [model],
    )
    ov = parsed["overrides"]
    passed.append(check("原版解析器识别层高", ov.get("layer_height") == "0.16", repr(ov)))
    passed.append(check("原版解析器识别树状支撑", ov.get("support") == "tree_plate", repr(ov)))
    passed.append(check("原版解析器识别高级参数", ov.get("outer_wall_speed") == "35", repr(ov)))
    passed.append(check(
        "原版解析器保留 key=value",
        "wall_loops=4" in (ov.get("_raw") or []),
        repr(ov),
    ))
    import analyze_stl
    ascii_analysis = analyze_stl.analyze(
        _generated_probe_stl(), plate_size=256
    )
    passed.append(check(
        "ASCII STL 可以通过切片预分析",
        ascii_analysis.get("triangles") == 12
        and ascii_analysis.get("finite") is True,
        repr(ascii_analysis),
    ))

    spec = service.CORE.build_command(
        mode="workbench",
        models=[model],
        settings=SETTINGS,
        command_text="H2S，层高0.16，15%网格，树状支撑仅打印板",
        output_dir=os.path.join(ROOT, "test-output"),
    )
    command = " ".join(spec["command"])
    passed.append(check("单文件命令调用原版 CLI", "slice_bambu.py" in command, command))
    passed.append(check("单文件命令包含完整支撑参数",
                        "support_type=tree(auto)" in command
                        and "support_on_build_plate_only=1" in command,
                        command))
    passed.append(check("妙妙工具箱进入真实参数",
                        "seam_position=nearest" in command
                        and "ironing_type=topmost" in command,
                        command))
    passed.append(check(
        "H2S 进入命令与摘要",
        (
            "--machine Bambu Lab H2S 0.4 nozzle" in command
            or "--machine Bambu Lab H2S" in command
            or "--machine H2S" in command
        )
        and spec["parts"][0] == "H2S",
        repr(spec["parts"]),
    ))
    passed.append(check(
        "单文件输出使用明确命名",
        os.path.basename(spec["output"])
        == os.path.splitext(os.path.basename(model))[0] + "_切片.gcode.3mf",
        spec["output"],
    ))
    passed.append(check(
        "自动排列使用真实生效参数",
        "--arrange 1" in command,
        command,
    ))

    batch = service.CORE.build_command(
        mode="batch",
        models=[model],
        settings=SETTINGS,
        command_text="层高0.16",
        output_dir=os.path.join(ROOT, "test-output"),
    )
    passed.append(check("批量模式使用原版 batch CLI",
                        "--batch" in batch["command"],
                        " ".join(batch["command"])))

    with tempfile.TemporaryDirectory(prefix="v2_farm_merge_") as work:
        second = os.path.join(work, "second.stl")
        shutil.copy2(model, second)
        combined_settings = dict(SETTINGS)
        combined_settings["printer"] = "Bambu Lab P1S"
        combined_settings["batchOutputMode"] = "combined"
        combined_settings["supportOverlap"] = False
        combined = service.CORE.build_command(
            mode="batch",
            models=[model, second],
            settings=combined_settings,
            command_text="",
            output_dir=os.path.join(work, "out"),
            batch_items=[
                {
                    "path": model,
                    "quantity": 3,
                    "parameterSource": "current",
                },
                {
                    "path": second,
                    "quantity": 2,
                    "parameterSource": "file",
                },
            ],
        )
        combined_command = " ".join(combined["command"])
        manifest_index = combined["command"].index(
            "--farm-merge-plan") + 1
        manifest_path = combined["command"][manifest_index]
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        passed.append(check(
            "批量工作台可进入多文件合并排盘",
            "--farm-merge-plan" in combined_command
            and manifest["files"][0]["quantity"] == 3
            and manifest["files"][1]["parameterSource"] == "current"
            and manifest.get("outputMode") == "editable",
            repr(combined),
        ))
        passed.append(check(
            "合并排盘使用当前选择的 P1S，而不是上次保存的机型",
            manifest["machine"] == "Bambu Lab P1S 0.4 nozzle",
            repr(manifest.get("machine")),
        ))
        passed.append(check(
            "合并排盘把当前设置参数带入清单",
            "layer_height=0.16" in manifest.get("processOverride", "")
            and "sparse_infill_density=15%" in manifest.get(
                "processOverride", ""),
            repr(manifest.get("processOverride")),
        ))
        if combined.get("tempDir"):
            shutil.rmtree(combined["tempDir"], ignore_errors=True)

    embedded_model = os.path.abspath(os.path.join(
        ROOT, "..", "test_files", "v217_yaw_alignment", "case1_m.3mf"
    ))
    if os.path.isfile(embedded_model):
        file_settings = dict(SETTINGS)
        file_settings["parameterPolicy"] = {
            "mode": "file",
            "overrides": {},
        }
        file_spec = service.CORE.build_command(
            mode="workbench",
            models=[embedded_model],
            settings=file_settings,
            command_text="",
            output_dir=os.path.join(ROOT, "test-output"),
        )
        file_command = " ".join(file_spec["command"])
        passed.append(check(
            "跟随文件时启用项目参数保留",
            "--preserve-project 1" in file_command
            and "layer_height=0.16" not in file_command
            and "sparse_infill_density=15%" not in file_command
            and "support_type=tree(auto)" not in file_command,
            file_command,
        ))
        passed.append(check(
            "隐藏 Z 缝不阻止保留文件参数",
            "seam_slope_conditional=1" in file_command,
            file_command,
        ))

        custom_settings = dict(SETTINGS)
        custom_settings["parameterPolicy"] = {
            "mode": "custom",
            "overrides": {
                "layerHeight": True,
                "infill": False,
                "pattern": False,
                "support": False,
            },
        }
        custom_spec = service.CORE.build_command(
            mode="workbench",
            models=[embedded_model],
            settings=custom_settings,
            command_text="",
            output_dir=os.path.join(ROOT, "test-output"),
        )
        custom_command = " ".join(custom_spec["command"])
        passed.append(check(
            "逐项选择只覆盖勾选项",
            "--preserve-project 1" in custom_command
            and "layer_height=0.16" in custom_command
            and "support_type=tree(auto)" not in custom_command,
            custom_command,
        ))

        from bambu_cli import unpack_3mf
        inherited = unpack_3mf.project_overrides(embedded_model)
        passed.append(check(
            "3MF 项目参数包含层高和支撑",
            "layer_height=0.2" in inherited
            and "enable_support=1" in inherited
            and "sparse_infill_pattern=grid" in inherited,
            inherited,
        ))

        with tempfile.TemporaryDirectory(prefix="v2_embedded_multi_") as work:
            first = os.path.join(work, "first.3mf")
            second = os.path.join(work, "second.3mf")
            shutil.copy2(embedded_model, first)
            shutil.copy2(embedded_model, second)
            multi_spec = service.CORE.build_command(
                mode="batch",
                models=[first, second],
                settings=file_settings,
                command_text="",
                output_dir=os.path.join(work, "out"),
            )
            multi_commands = multi_spec.get("commands") or []
            passed.append(check(
                "多个 3MF 分别保留自身参数",
                len(multi_commands) == 2
                and all(
                    "--preserve-project 1" in " ".join(command)
                    for command in multi_commands
                ),
                repr(multi_commands),
            ))

        stl_fallback = service.CORE.build_command(
            mode="workbench",
            models=[model],
            settings=file_settings,
            command_text="",
            output_dir=os.path.join(ROOT, "test-output"),
        )
        stl_fallback_command = " ".join(stl_fallback["command"])
        passed.append(check(
            "STL 没有内嵌参数时回退到当前习惯",
            "--preserve-project 1" not in stl_fallback_command
            and "layer_height=0.16" in stl_fallback_command
            and "sparse_infill_density=15%" in stl_fallback_command,
            stl_fallback_command,
        ))

    multicolor_model = os.path.abspath(os.path.join(
        ROOT, "..", "test_files", "labubu_only_input", "毒液拉布布_可编辑.3mf"
    ))
    if not os.path.isfile(multicolor_model):
        multicolor_model = _generated_multicolor_3mf()
    if os.path.isfile(multicolor_model):
        passed.append(check(
            "公开与研发版都开放多色模式",
            "multicolor" in service.PUBLIC_WORKSPACE_MODES,
        ))
        if service.PUBLIC_EDITION:
            figurine_blocked = False
            try:
                service.CORE.build_command(
                    mode="figurine",
                    models=[multicolor_model],
                    settings=SETTINGS,
                    command_text="",
                    output_dir=os.path.join(ROOT, "test-output"),
                )
            except ValueError as exc:
                figurine_blocked = "公开版" in str(exc)
            passed.append(check(
                "公开版仍拒绝手办模式",
                figurine_blocked,
            ))
        multi = service.CORE.build_command(
            mode="multicolor",
            models=[multicolor_model],
            settings=SETTINGS,
            command_text="零串色",
            output_dir=os.path.join(ROOT, "test-output"),
        )
        command = " ".join(multi["command"])
        request_path = multi["command"][-1]
        with open(request_path, encoding="utf-8") as handle:
            request = json.load(handle)
        passed.append(check(
            "多色模式使用受保护核心 JSON 协议",
            multi["command"][-2] == "plan"
            and request.get("protocol") == service.PROTECTED_CORE_PROTOCOL
            and request.get("strategy") == "zero_flush",
            command,
        ))
        passed.append(check(
            "多色模式传递支撑和切片参数",
            "support_type=tree(auto)" in request.get("process_overrides", "")
            and "support_on_build_plate_only=1"
            in request.get("process_overrides", "")
            and "layer_height=0.16"
            in request.get("process_overrides", "")
            and "sparse_infill_density=15%"
            in request.get("process_overrides", ""),
            repr(request),
        ))
        timed_settings = dict(SETTINGS)
        timed_settings["multicolorStrategy"] = "time_budget"
        timed_settings["targetHours"] = "3"
        timed = service.CORE.build_command(
            mode="multicolor",
            models=[multicolor_model],
            settings=timed_settings,
            command_text="按时长 3 小时",
            output_dir=os.path.join(ROOT, "test-output"),
        )
        with open(timed["command"][-1], encoding="utf-8") as handle:
            timed_request = json.load(handle)
        passed.append(check(
            "v2 按时长策略传递目标小时",
            timed_request.get("strategy") == "time_budget"
            and timed_request.get("target_hours") == 3
            and timed_request.get("emit_printable") is False,
            repr(timed_request),
        ))
        reference_settings = dict(SETTINGS)
        reference_settings["multicolorStrategy"] = "fewer_plates"
        reference = service.CORE.build_command(
            mode="multicolor",
            models=[multicolor_model],
            settings=reference_settings,
            command_text="满盘参考",
            output_dir=os.path.join(ROOT, "test-output"),
        )
        with open(reference["command"][-1], encoding="utf-8") as handle:
            reference_request = json.load(handle)
        passed.append(check(
            "v2 满盘参考不再写死零串色",
            reference_request.get("strategy") == "fewer_plates",
            repr(reference_request),
        ))
        no_support_settings = dict(SETTINGS)
        no_support_settings["supportMode"] = "off"
        no_support = service.CORE.build_command(
            mode="multicolor",
            models=[multicolor_model],
            settings=no_support_settings,
            command_text="不要支撑",
            output_dir=os.path.join(ROOT, "test-output"),
        )
        with open(no_support["command"][-1], encoding="utf-8") as handle:
            no_support_request = json.load(handle)
        passed.append(check(
            "多色模式可真正关闭支撑",
            "enable_support=0"
            in no_support_request.get("process_overrides", ""),
            repr(no_support_request),
        ))
        editable_settings = dict(SETTINGS)
        editable_settings["outputMode"] = "3mf"
        editable = service.CORE.build_command(
            mode="multicolor",
            models=[multicolor_model],
            settings=editable_settings,
            command_text="仅摆盘",
            output_dir=os.path.join(ROOT, "test-output"),
        )
        with open(editable["command"][-1], encoding="utf-8") as handle:
            editable_request = json.load(handle)
        passed.append(check(
            "多色仅摆盘不额外生成打印包",
            editable_request.get("emit_printable") is False,
            repr(editable_request),
        ))
        for spec in (
            multi, timed, reference, no_support, editable,
        ):
            if spec.get("tempDir"):
                shutil.rmtree(spec["tempDir"], ignore_errors=True)
        task = service.TaskState(id="protocol-test")
        service.TASKS._handle_line(task, "PLAN|progress|0.900000")
        service.TASKS._handle_line(task, "PLAN|status|Bambu 已整理第 1 盘")
        passed.append(check("多色 PLAN 进度协议已接入",
                            abs(task.progress - 0.9) < 0.001
                            and "第 1 盘" in task.message,
                            repr((task.progress, task.message))))

        original_validator = service.CORE.validate_multicolor_result
        try:
            service.CORE.validate_multicolor_result = (
                lambda payload, progress=None: {
                    **payload,
                    "slice_checked": True,
                    "support_verified": True,
                    "total_actual_hours": 1.25,
                }
            )
            done_payload = json.dumps({
                "file": "result.3mf",
                "validation_required": True,
                "plates": [{"name": "盘1"}],
            }, ensure_ascii=False)
            service.TASKS.start({
                "command": [
                    sys.executable,
                    "-c",
                    "print(%r)" % ("PLAN|done|" + done_payload),
                ],
                "cwd": ROOT,
                "outputDir": os.path.join(ROOT, "test-output"),
                "tempDir": "",
            })
            protocol_task = None
            for _ in range(50):
                protocol_task = service.TASKS.snapshot().get("task")
                if protocol_task and protocol_task.get("status") != "running":
                    break
                time.sleep(0.05)
            result = (protocol_task or {}).get("results") or []
            passed.append(check(
                "v2 在 PLAN 完成后执行真实检修回调",
                bool(result)
                and result[-1].get("slice_checked")
                and result[-1].get("support_verified"),
                repr(protocol_task),
            ))
        finally:
            service.CORE.validate_multicolor_result = original_validator

        with tempfile.TemporaryDirectory(prefix="v2_multicolor_files_") as work:
            first = os.path.join(work, "first.3mf")
            second = os.path.join(work, "second.3mf")
            shutil.copy2(multicolor_model, first)
            shutil.copy2(multicolor_model, second)
            multi_files = service.CORE.build_command(
                mode="multicolor",
                models=[first, second],
                settings=SETTINGS,
                command_text="零串色",
                output_dir=os.path.join(work, "out"),
            )
            commands = multi_files.get("commands") or []
            request_sources = []
            for command in commands:
                with open(command[-1], encoding="utf-8") as handle:
                    request_sources.append(json.load(handle).get("source"))
            passed.append(check(
                "多文件多色没有丢文件",
                len(commands) == 2
                and request_sources == [first, second],
                repr((commands, request_sources)),
            ))
            passed.append(check(
                "多文件多色使用独立输出目录",
                len(set(multi_files.get("planDirs") or [])) == 2,
                repr(multi_files.get("planDirs")),
            ))
            if multi_files.get("tempDir"):
                shutil.rmtree(multi_files["tempDir"], ignore_errors=True)

        with tempfile.TemporaryDirectory(prefix="v2_output_name_") as work:
            source = os.path.join(work, "紧凑摆盘测试1(1).3mf")
            shutil.copy2(multicolor_model, source)
            layout_settings = dict(SETTINGS)
            layout_settings["autoArrange"] = False
            layout_settings["outputMode"] = "3mf"
            named = service.CORE.build_command(
                mode="workbench",
                models=[source],
                settings=layout_settings,
                command_text="仅摆盘",
                output_dir=os.path.join(work, "out"),
            )
            passed.append(check(
                "输出名去掉下载重复标记",
                os.path.basename(named["output"]) == "紧凑摆盘测试1_摆盘.3mf",
                named["output"],
            ))

    with tempfile.TemporaryDirectory(prefix="v2_core_hash_") as work:
        core_path = os.path.join(work, "protected_core.exe")
        hash_path = os.path.join(
            work, service.PROTECTED_CORE_HASH_NAME
        )
        with open(core_path, "wb") as handle:
            handle.write(b"printfarm-core-fixture")
        with open(core_path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        with open(hash_path, "w", encoding="ascii") as handle:
            handle.write(digest + "  protected_core.exe\n")
        verified = (
            str(service._verify_protected_core(core_path))
            == os.path.abspath(core_path)
        )
        with open(core_path, "ab") as handle:
            handle.write(b"tampered")
        blocked = False
        try:
            service._verify_protected_core(core_path)
        except RuntimeError as exc:
            blocked = "校验失败" in str(exc)
        passed.append(check(
            "受保护组件正常校验且篡改后拒绝运行",
            verified and blocked,
            repr((verified, blocked)),
        ))

    service.PUBLIC_EDITION = True

    with tempfile.TemporaryDirectory(prefix="v2_per_file_") as work:
        first = os.path.join(work, "first.stl")
        second = os.path.join(work, "second.stl")
        shutil.copy2(model, first)
        shutil.copy2(model, second)
        per_settings = dict(SETTINGS)
        per_settings["autoArrange"] = False
        per_spec = service.CORE.build_command(
            mode="workbench",
            models=[first, second],
            settings=per_settings,
            command_text="层高0.16，first 用 PETG，second 用 PLA",
            output_dir=os.path.join(work, "out"),
        )
        passed.append(check("每文件独立参数生成独立任务",
                            len(per_spec.get("commands") or []) == 2,
                            repr(per_spec.get("commands"))))
        commands = per_spec.get("commands") or []
        first_command = " ".join(commands[0]) if len(commands) == 2 else ""
        second_command = " ".join(commands[1]) if len(commands) == 2 else ""
        isolated = (
            len(commands) == 2
            and first in first_command
            and second in second_command
            and second not in first_command
            and first not in second_command
        )
        if HAS_BAMBU_PROFILES:
            isolated = (
                isolated
                and "PETG" in first_command
                and "PLA Basic" in second_command
            )
        passed.append(check(
            "每文件参数没有串到另一个文件",
            isolated,
            repr(commands),
        ))

    with tempfile.TemporaryDirectory(prefix="v2_tight_single_") as work:
        tight_settings = dict(SETTINGS)
        tight_settings["autoArrange"] = False
        tight_settings["tightPacking"] = True
        tight = service.CORE.build_command(
            mode="workbench",
            models=[model],
            settings=tight_settings,
            command_text="最省空间",
            output_dir=os.path.join(work, "out"),
        )
        tight_command = " ".join(tight["command"])
        passed.append(check(
            "最省空间单文件进入紧凑装箱",
            "--batch" in tight_command
            and "--pack 1" in tight_command
            and "--tight 1" in tight_command,
            tight_command,
        ))
        if tight.get("tempDir"):
            shutil.rmtree(tight["tempDir"], ignore_errors=True)

    lines = service.CORE.parse("填充改直线", [model])
    passed.append(check(
        "直线填充可以被正确解析",
        lines["overrides"].get("pattern") == "lines",
        repr(lines["overrides"]),
    ))

    wiring_settings = dict(SETTINGS)
    wiring_settings.update({
        "autoArrange": False,
        "orientation": False,
        "minSupport": True,
        "clone": "2",
    })
    wiring = service.CORE.build_command(
        mode="workbench",
        models=[model],
        settings=wiring_settings,
        command_text="",
        output_dir=os.path.join(ROOT, "test-output"),
    )
    wiring_command = " ".join(wiring["command"])
    passed.append(check(
        "定向、支撑、克隆开关全部进入切片命令",
        "--orient 0" in wiring_command
        and "--arrange 0" in wiring_command
        and "--min-support 2" in wiring_command
        and "--clone 2" in wiring_command,
        wiring_command,
    ))
    fatal_task = service.TaskState(id="fatal-traceback-test")
    service.TASKS._handle_line(
        fatal_task, "Traceback (most recent call last):"
    )
    passed.append(check(
        "未处理异常会结束等待中的任务",
        fatal_task.fatal_traceback
        and "未处理异常" in fatal_task.message,
        repr((fatal_task.fatal_traceback, fatal_task.message)),
    ))

    with tempfile.TemporaryDirectory(prefix="v2_cwd_") as work:
        missing_cwd = os.path.join(work, "missing-directory")
        resolved_cwd = service._resolve_process_cwd(missing_cwd)
        resolved_ok = os.path.isdir(resolved_cwd)
        passed.append(check(
            "切片工作目录缺失时自动回退",
            resolved_ok,
            repr((missing_cwd, resolved_cwd)),
        ))

    cleanup_session = service.UPLOAD_ROOT / __import__("uuid").uuid4().hex
    cleanup_session.mkdir(parents=True)
    (cleanup_session / "old.stl").write_text("old", encoding="ascii")

    import server
    cleanup_removed = server._cleanup_upload_sessions()
    passed.append(check(
        "启动时清理上次遗留的上传会话",
        cleanup_removed >= 1 and not cleanup_session.exists(),
        repr((cleanup_removed, cleanup_session)),
    ))
    with tempfile.TemporaryDirectory(prefix="v2_upload_paths_") as work:
        session = __import__("pathlib").Path(work)
        first = server._safe_upload_target(
            session, "批次A/零件/同名.stl", "同名.stl"
        )
        second = server._safe_upload_target(
            session, "批次B/零件/同名.stl", "同名.stl"
        )
        passed.append(check(
            "批量同名文件保留子目录",
            first != second
            and first.parent.name == "零件"
            and second.parent.name == "零件"
            and first.parent != second.parent,
            repr((str(first), str(second))),
        ))
        rejected = False
        try:
            server._safe_upload_target(session, "../逃逸.stl", "逃逸.stl")
        except ValueError:
            rejected = True
        passed.append(check("批量导入拒绝目录逃逸", rejected))

        import zipfile
        preview_model = session / "preview.3mf"
        with zipfile.ZipFile(preview_model, "w") as archive:
            archive.writestr(
                "Metadata/plate_1_small.png",
                b"\x89PNG\r\n\x1a\npreview",
            )
        preview = server._thumbnail_data_uri(preview_model)
        passed.append(check(
            "3MF 自带缩略图可以提取",
            preview.startswith("data:image/png;base64,"),
            repr(preview[:40]),
        ))

        import native_dialog
        selection_file = session / "selection.json"
        expected_folder = os.path.join(
            tempfile.gettempdir(), "打印农场助手 输出"
        )
        native_dialog.write_result(selection_file, expected_folder)
        selection = json.loads(
            selection_file.read_text(encoding="utf-8")
        )
        passed.append(check(
            "目录选择结果保留中文路径",
            selection.get("path") == expected_folder,
            repr(selection),
        ))

        cleanup_dir = session / "cleanup-output"
        cleanup_dir.mkdir()
        for name in (
            ".layout_candidate_test.3mf",
            "切片诊断.txt",
            "切片报告.txt",
        ):
            (cleanup_dir / name).write_text("diagnostic", encoding="utf-8")
        keep_output = cleanup_dir / "紧凑摆盘测试1_摆盘.3mf"
        keep_output.write_bytes(b"model")
        keep_report = cleanup_dir / "多色排盘问题说明.md"
        keep_report.write_text("user report", encoding="utf-8")
        cleanup_task = service.TaskState(
            id="cleanup-test", output_dir=str(cleanup_dir)
        )
        service.TASKS._cleanup_task_artifacts(cleanup_task)
        passed.append(check(
            "输出目录只保留用户产物",
            keep_output.is_file()
            and keep_report.is_file()
            and not (cleanup_dir / ".layout_candidate_test.3mf").exists()
            and not (cleanup_dir / "切片诊断.txt").exists()
            and not (cleanup_dir / "切片报告.txt").exists(),
            repr(sorted(path.name for path in cleanup_dir.iterdir())),
        ))

    import http.client
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.parse import urlencode
    import server as bridge_server

    bridge = ThreadingHTTPServer(("127.0.0.1", 0), bridge_server.Handler)
    thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    thread.start()
    session_id = ""
    try:
        connection = http.client.HTTPConnection(
            "127.0.0.1", bridge.server_port, timeout=20)

        def post(path, body, content_type):
            connection.request(
                "POST", path, body=body,
                headers={"Content-Type": content_type},
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload

        status, started = post(
            "/api/import/start", b"{}", "application/json")
        session_id = started.get("sessionId", "")
        with open(_generated_probe_stl(), "rb") as handle:
            model_bytes = handle.read()
        query = urlencode({
            "session": session_id,
            "relativePath": "中文批次/测试模型.stl",
        })
        status_file, _ = post(
            "/api/import/file?" + query,
            model_bytes,
            "application/octet-stream",
        )
        status_finish, finished = post(
            "/api/import/finish?session=" + session_id,
            b"{}",
            "application/json",
        )
        jobs = finished.get("jobs") or []
        passed.append(check(
            "模型导入使用原始二进制流并保留中文相对路径",
            status == 200
            and status_file == 200
            and status_finish == 200
            and len(jobs) == 1
            and jobs[0].get("relativePath")
            == "中文批次/测试模型.stl"
            and jobs[0].get("size") == len(model_bytes),
            repr((status, status_file, status_finish, finished)),
        ))
        status_release, released = post(
            "/api/import/release",
            b"{}",
            "application/json",
        )
        passed.append(check(
            "清空队列对应的上传会话已删除",
            status_release == 200
            and released.get("removed", 0) >= 1
            and not (bridge_server.UPLOAD_ROOT / session_id).exists(),
            repr((status_release, released)),
        ))
    finally:
        bridge.shutdown()
        bridge.server_close()
        if session_id:
            shutil.rmtree(
                bridge_server.UPLOAD_ROOT / session_id,
                ignore_errors=True,
            )

    if all(passed):
        print("V2 后端复用测试：全部通过")
        return 0
    print("V2 后端复用测试：失败")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
