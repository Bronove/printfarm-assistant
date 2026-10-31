# -*- coding: utf-8 -*-
"""V2 后端复用测试：解析和命令构造必须继续使用原版规则。"""

import os
import shutil
import sys
import tempfile
import atexit

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

    multicolor_model = os.path.abspath(os.path.join(
        ROOT, "..", "test_files", "labubu_only_input", "毒液拉布布_可编辑.3mf"
    ))
    if os.path.isfile(multicolor_model):
        public_blocked = False
        try:
            service.CORE.build_command(
                mode="multicolor",
                models=[multicolor_model],
                settings=SETTINGS,
                command_text="零串色",
                output_dir=os.path.join(ROOT, "test-output"),
            )
        except ValueError as exc:
            public_blocked = "公开版" in str(exc)
        passed.append(check(
            "公开版后端拒绝多色模式",
            service.PUBLIC_EDITION and public_blocked,
        ))

        # 保留私版底层命令测试；公开版运行时必须先拒绝这些模式。
        service.PUBLIC_EDITION = False
        multi = service.CORE.build_command(
            mode="multicolor",
            models=[multicolor_model],
            settings=SETTINGS,
            command_text="零串色",
            output_dir=os.path.join(ROOT, "test-output"),
        )
        command = " ".join(multi["command"])
        passed.append(check("多色模式使用原版排盘入口",
                            "--multicolor-plan" in command
                            and "--strategy zero_flush" in command,
                            command))
        passed.append(check(
            "多色模式传递支撑和切片参数",
            "support_type=tree(auto)" in command
            and "support_on_build_plate_only=1" in command
            and "layer_height=0.16" in command
            and "sparse_infill_density=15%" in command,
            command,
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
        passed.append(check(
            "多色模式可真正关闭支撑",
            "enable_support=0" in " ".join(no_support["command"]),
            " ".join(no_support["command"]),
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
        passed.append(check(
            "多色仅摆盘不额外生成打印包",
            "--emit-printable" not in editable["command"],
            repr(editable["command"]),
        ))
        task = service.TaskState(id="protocol-test")
        service.TASKS._handle_line(task, "PLAN|progress|0.900000")
        service.TASKS._handle_line(task, "PLAN|status|Bambu 已整理第 1 盘")
        passed.append(check("多色 PLAN 进度协议已接入",
                            abs(task.progress - 0.9) < 0.001
                            and "第 1 盘" in task.message,
                            repr((task.progress, task.message))))

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
            passed.append(check(
                "多文件多色没有丢文件",
                len(commands) == 2
                and all((first if index == 0 else second) in " ".join(command)
                        for index, command in enumerate(commands)),
                repr(commands),
            ))
            passed.append(check(
                "多文件多色使用独立输出目录",
                len(set(multi_files.get("planDirs") or [])) == 2,
                repr(multi_files.get("planDirs")),
            ))

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

    import server
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

        import json
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

    if all(passed):
        print("V2 后端复用测试：全部通过")
        return 0
    print("V2 后端复用测试：失败")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
