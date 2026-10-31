# -*- coding: utf-8 -*-
"""打印农场助手桌面端后端：复用原版解析器与切片 CLI，不维护第二套业务规则。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FROZEN = bool(getattr(sys, "frozen", False))
PUBLIC_EDITION = True
PUBLIC_WORKSPACE_MODES = frozenset(("workbench", "batch"))
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else ROOT.parent
BUNDLE_DIR = ROOT
DATA_DIR = BUNDLE_DIR if FROZEN else APP_DIR / "切片软件"
LEGACY_DIR = APP_DIR if FROZEN else DATA_DIR
CLI_DIR = DATA_DIR / "bambu_cli"
CONFIG_PATH = LEGACY_DIR / "config.json"
UPLOAD_ROOT = (
    Path(tempfile.gettempdir()) / "tuozhu_ui_v2_uploads"
    if FROZEN else ROOT / ".uploads"
)
USER_DATA_DIR = Path(
    os.environ.get("PRINTFARM_DATA_DIR")
    or Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    / "PrintFarmAssistant"
)
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PRINTFARM_DATA_DIR", str(USER_DATA_DIR))

from local_log import log_event, log_exception  # noqa: E402

for path in (LEGACY_DIR, CLI_DIR, ROOT.parent / "build_tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _resolve_process_cwd(requested: str | None) -> str:
    """Return an existing working directory for the frozen or source runtime."""
    candidate = Path(requested) if requested else LEGACY_DIR
    if candidate.is_dir():
        return str(candidate)
    fallback = (
        LEGACY_DIR if LEGACY_DIR.is_dir()
        else BUNDLE_DIR if BUNDLE_DIR.is_dir()
        else Path(tempfile.gettempdir())
    )
    log_event(
        "任务",
        "切片工作目录不可用，已回退",
        {"requested": str(candidate), "fallback": str(fallback)},
    )
    return str(fallback)


class _Value:
    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _load_legacy_module():
    import headless_core
    return headless_core


class LegacyCore:
    """无界面的原版 SliceApp 门面，只调用纯解析/命令构造方法。"""

    @staticmethod
    def _clean_output_stem(source):
        stem = os.path.splitext(os.path.basename(source))[0]
        stem = re.sub(r"\s*[\(（]\d+[\)）]\s*$", "", stem).strip()
        return stem or "模型"

    def _single_output_path(self, source, output_dir):
        stem = self._clean_output_stem(source)
        if self.app.output_mode == "3mf":
            filename = stem + "_摆盘.3mf"
        else:
            filename = stem + "_切片.gcode.3mf"
        return os.path.join(output_dir, filename)

    def __init__(self):
        self.module = _load_legacy_module()
        self.module.VERSION = "1.5.0-beta.1"
        self.module.APP_NAME = "打印农场助手 1.5.0-beta.1"
        self._migrate_legacy_state()
        self.SliceApp = self.module.SliceApp
        self.app = self.SliceApp.__new__(self.SliceApp)
        self.app.cfg = {}
        config_path = USER_DATA_DIR / "config.json"
        try:
            with open(config_path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                self.app.cfg.update(data)
        except (OSError, ValueError):
            pass
        self.app.cfg.setdefault("machine", "Bambu Lab P1S 0.4 nozzle")
        self.app.cfg.setdefault("process", "0.20mm Standard @BBL X1C")
        self.app.cfg.setdefault(
            "filament", "Bambu PLA Basic @BBL P1S 0.4 nozzle"
        )
        self.app.cfg.setdefault("bed", "Textured PEI Plate")
        self.app._ph = ""
        self.app.models = []
        self.app.overrides = {}
        self.app.ui_mode = "workbench"
        self.app.output_mode = "gcode"
        self.app._filament_lock_cache = {}
        self.app._user_rules_cache = None
        self.app.var_pack = _Value(False)
        self.app.var_tight = _Value(False)
        self.app.var_min_support = _Value(False)
        self.app.var_tool_hide_z = _Value(False)
        self.app.var_tool_top_ironing = _Value(False)
        self.app._toolbox_vars = {
            "hide_z_seam": self.app.var_tool_hide_z,
            "top_ironing": self.app.var_tool_top_ironing,
        }
        profile_candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Bambu Studio" / "resources" / "profiles" / "BBL",
            Path("D:/Bambu Studio/resources/profiles/BBL"),
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "BambuStudio" / "system" / "profiles" / "BBL",
        ]
        profile_root = next(
            (path for path in profile_candidates if path.is_dir()), None
        )
        if profile_root is not None:
            self.app._profiles_root_cache = str(profile_root)
            try:
                self.app.machine_display = self.app._load_machines()
            except Exception:
                self.app.machine_display = self._default_machines()
        else:
            self.app.machine_display = self._default_machines()

    def _migrate_legacy_state(self):
        if not FROZEN:
            return
        current = Path(self.module.APP_DIR)
        legacy = current.parent / "拓竹助手"
        sources = [current, legacy]
        local_apps = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"
        sources.extend(local_apps / name for name in (
            "拓竹助手1.0", "拓竹助手", "拓竹助手V2",
        ))
        if not USER_DATA_DIR.is_dir():
            USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        names = ["config.json"]
        for candidate in sources:
            try:
                names.extend(
                    item.name for item in candidate.glob("user_rules_*.json")
                )
            except OSError:
                pass
        for name in dict.fromkeys(names):
            target = USER_DATA_DIR / name
            if target.exists():
                continue
            for candidate in sources:
                source = candidate / name
                if source.is_file():
                    try:
                        shutil.copy2(source, target)
                    except OSError:
                        pass
                    break

    @staticmethod
    def _default_machines():
        return [
            "Bambu Lab A1", "Bambu Lab A1 mini", "Bambu Lab A2L",
            "Bambu Lab H2C", "Bambu Lab H2D", "Bambu Lab H2D Pro",
            "Bambu Lab H2S", "Bambu Lab P1P", "Bambu Lab P1S",
            "Bambu Lab P2S", "Bambu Lab X1", "Bambu Lab X1 Carbon",
            "Bambu Lab X1E", "Bambu Lab X2D",
        ]

    def parse(self, text: str, models: list[str] | None = None):
        self.app.models = list(models or [])
        overrides = self.app.parse_requirements(text)
        try:
            parts = self.app._current_params_parts(overrides)
        except Exception:
            parts = []
        result = {
            "overrides": overrides,
            "parts": parts,
        }
        log_event(
            "参数",
            "解析一句话参数",
            {"input": text, "models": models or [], "result": result},
        )
        return result

    def metadata(self):
        events = []
        usage_path = USER_DATA_DIR / "usage.json"
        try:
            with open(usage_path, encoding="utf-8") as handle:
                events = json.load(handle)
        except (OSError, ValueError):
            events = []
        event_counts = Counter(
            str(event.get("t") or "") for event in events
            if isinstance(event, dict)
        )
        rules = self.app._user_rules()
        return {
            "version": self.module.VERSION,
            "usage": {
                "total": len(events),
                "events": event_counts.most_common(12),
                "recent": events[-20:][::-1],
            },
            "learning": {
                "summary": self.app._learning_stats(),
                "phraseRules": rules.get("phrase_rules", []),
                "defaults": rules.get("defaults", {}),
                "samples": len(rules.get("samples", [])),
            },
        }

    def rule_action(self, action: str, norm: str = "", enabled=True):
        log_event(
            "习惯",
            "修改个人规则",
            {"action": action, "norm": norm, "enabled": enabled},
        )
        if action == "toggle":
            self.app._set_rule_enabled(norm, enabled)
        elif action == "remove":
            self.app._remove_rule(norm)
        elif action == "clear":
            self.app._user_rules_cache = {
                "samples": [], "phrase_rules": [], "defaults": {}
            }
            self.app._save_user_rules()
        elif action == "remove-default":
            self.app._remove_default(norm)
        else:
            raise ValueError("未知规则操作")
        return self.metadata()

    def plugins_metadata(self):
        import plugins as plugin_module
        found, problems = plugin_module.discover(
            str(DATA_DIR / "plugins")
        )
        result = {
            "plugins": [
                {
                    "id": item.id,
                    "name": item.name,
                    "version": item.version,
                    "description": item.desc,
                    "enabled": item.enabled and not item.error,
                    "error": item.error,
                }
                for item in found
            ],
            "problems": problems,
        }
        log_event("插件", "扫描插件", result)
        return result

    def run_plugin(self, text):
        import plugins as plugin_module
        registry = plugin_module.Registry(
            plugin_module.Host(log=lambda _message: None),
            str(DATA_DIR / "plugins"),
        )
        registry.load_all(ai_available=False)
        reply, plugin_name = registry.run(text)
        result = {
            "reply": reply or "",
            "plugin": plugin_name,
            **self.plugins_metadata(),
        }
        log_event(
            "插件",
            "运行插件",
            {"text": text, "plugin": plugin_name, "reply": reply},
        )
        return result

    def build_command(
        self,
        *,
        mode: str,
        models: list[str],
        settings: dict[str, Any],
        command_text: str,
        output_dir: str,
    ):
        log_event(
            "切片",
            "构造切片任务",
            {
                "mode": mode,
                "models": models,
                "settings": settings,
                "command": command_text,
                "output": output_dir,
            },
        )
        if not models:
            raise ValueError("没有待切片的模型")
        missing = [path for path in models if not os.path.isfile(path)]
        if missing:
            raise ValueError("找不到模型文件：%s" % missing[0])
        if not output_dir:
            raise ValueError("没有设置输出目录")
        if PUBLIC_EDITION and mode not in PUBLIC_WORKSPACE_MODES:
            raise ValueError("公开版仅提供切片工作台和批量切片")
        os.makedirs(output_dir, exist_ok=True)

        parsed = self.parse(command_text, models)
        base_overrides, per_file = self.app._parse_per_file(models, command_text)
        overrides = dict(base_overrides or parsed["overrides"])
        overrides.update(self._settings_overrides(settings))

        self.app.models = list(models)
        self.app.overrides = overrides
        self.app.ui_mode = mode if mode in ("workbench", "batch") else "workbench"
        self.app.output_mode = (
            "3mf" if settings.get("outputMode") == "3mf" else "gcode"
        )
        self.app.var_pack.set(bool(settings.get("autoArrange", True)))
        self.app.var_tight.set(bool(settings.get("tightPacking", False)))
        self.app.var_min_support.set(bool(settings.get("minSupport", False)))
        self.app.var_tool_hide_z.set(bool(settings.get("hideSeam", False)))
        self.app.var_tool_top_ironing.set(
            bool(settings.get("topIroning", False))
        )
        printer = str(settings.get("printer") or "").strip()
        if printer:
            display = printer.replace("Bambu Lab ", "")
            try:
                self.app.cfg["machine"] = self.app._resolve_machine(display)
            except Exception:
                self.app.cfg["machine"] = printer
        self.app.cfg["bed"] = settings.get(
            "bedType", self.app.cfg.get("bed", "Textured PEI Plate")
        )
        material = str(settings.get("material") or "").strip()
        if material:
            try:
                matched = self.app._parse_material(
                    material, self.app.cfg.get("machine")
                )
            except Exception:
                matched = None
            if matched:
                overrides["filament"] = matched[0]
                overrides["_mat_family"] = matched[1]
                if matched[2]:
                    overrides["_mat_fuzzy"] = True
        try:
            parts = self.app._current_params_parts(overrides)
        except Exception:
            parts = parsed["parts"]

        if per_file and not settings.get("autoArrange", True):
            commands = []
            outputs = []
            for index, source in enumerate(models):
                file_overrides = dict(overrides)
                file_overrides.update(per_file.get(index) or {})
                output = self._single_output_path(source, output_dir)
                commands.append(self.app._build_cmd(
                    source,
                    output,
                    file_overrides,
                    layout_only=self.app.output_mode == "3mf",
                ))
                outputs.append(output)
            return {
                "commands": commands,
                "cwd": str(LEGACY_DIR),
                "outputs": outputs,
                "outputDir": output_dir,
                "overrides": overrides,
                "perFile": per_file,
                "parts": parts,
            }

        if (
            mode == "workbench"
            and settings.get("tightPacking")
            and self.app.output_mode == "gcode"
            and len(models) == 1
            and int(settings.get("clone") or 1) <= 1
            and not self.app._filament_edit_locked([models[0]])
        ):
            parent = tempfile.mkdtemp(prefix="tuozhu_v2_tight_")
            staging = os.path.join(
                parent, self._clean_output_stem(models[0])
            )
            os.makedirs(staging, exist_ok=True)
            shutil.copy2(
                models[0],
                os.path.join(staging, os.path.basename(models[0])),
            )
            command = self.app._build_batch_cmd(
                staging,
                output_dir,
                True,
                layout_only=False,
            )
            return {
                "command": command,
                "cwd": str(LEGACY_DIR),
                "tempDir": parent,
                "outputDir": output_dir,
                "overrides": overrides,
                "parts": parts,
            }

        if mode == "batch" or len(models) > 1:
            staging = tempfile.mkdtemp(prefix="tuozhu_v2_batch_")
            for index, source in enumerate(models, 1):
                name = os.path.basename(source)
                target = os.path.join(staging, name)
                if os.path.exists(target):
                    target = os.path.join(staging, f"{index}_{name}")
                shutil.copy2(source, target)
            command = self.app._build_batch_cmd(
                staging,
                output_dir,
                bool(
                    settings.get("autoArrange", True)
                    or settings.get("tightPacking", False)
                ),
                layout_only=self.app.output_mode == "3mf",
            )
            return {
                "command": command,
                "cwd": str(LEGACY_DIR),
                "tempDir": staging,
                "outputDir": output_dir,
                "overrides": overrides,
                "parts": parts,
            }

        source = models[0]
        output = self._single_output_path(source, output_dir)
        command = self.app._build_cmd(
            source,
            output,
            overrides,
            layout_only=self.app.output_mode == "3mf",
        )
        return {
            "command": command,
            "cwd": str(LEGACY_DIR),
            "output": output,
            "outputDir": output_dir,
            "overrides": overrides,
            "parts": parts,
        }

    def _settings_overrides(self, settings):
        result = {}
        layer = str(settings.get("layerHeight") or "").strip()
        infill = str(settings.get("infill") or "").strip()
        if layer:
            result["layer_height"] = layer
        if infill:
            result["infill"] = infill
        if settings.get("pattern"):
            result["pattern"] = settings["pattern"]
        support = {
            "off": "none",
            "tree_plate": "tree_plate",
            "tree_all": "tree_all",
            "normal_plate": "normal_plate",
            "normal_all": "normal_all",
        }.get(settings.get("supportMode"), "tree_plate")
        result["support"] = support
        if settings.get("orientation") is False:
            result["orient"] = False
        if settings.get("autoArrange") is False:
            result["arrange"] = False
        if settings.get("tightPacking"):
            result["tight"] = True
        if settings.get("minSupport"):
            result["min_support"] = True
        clone = int(settings.get("clone") or 1)
        if clone > 1:
            result["clone"] = clone
        return result

    def persist_settings(self, output_dir, settings, mode):
        self.app.out_dir = output_dir
        self.app.cfg["output_dir"] = output_dir
        self.app.cfg["ui_mode"] = mode
        self.app.cfg["output_mode"] = (
            "3mf" if settings.get("outputMode") == "3mf" else "gcode"
        )
        self.app.cfg["bed"] = settings.get("bedType", "Textured PEI Plate")
        self.app.cfg["toolbox"] = {
            "hide_z_seam": bool(settings.get("hideSeam", False)),
            "top_ironing": bool(settings.get("topIroning", False)),
        }
        self.app._save_config()


@dataclass
class TaskState:
    id: str
    status: str = "running"
    progress: float = 0.0
    message: str = "正在启动切片"
    logs: list[str] = field(default_factory=list)
    output_dir: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    process: subprocess.Popen | None = None
    temp_dir: str = ""
    command_index: int = 0
    command_total: int = 0
    fatal_traceback: bool = False


class TaskManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.task: TaskState | None = None

    def snapshot(self):
        with self.lock:
            task = self.task
            if task is None:
                return {"busy": False, "task": None}
            return {
                "busy": task.status == "running",
                "task": {
                    "id": task.id,
                    "status": task.status,
                    "progress": task.progress,
                    "message": task.message,
                    "logs": task.logs[-160:],
                    "outputDir": task.output_dir,
                    "startedAt": task.started_at,
                    "finishedAt": task.finished_at,
                },
            }

    def start(self, spec):
        with self.lock:
            if self.task and self.task.status == "running":
                raise RuntimeError("已有切片任务正在运行")
            task = TaskState(
                id=uuid.uuid4().hex,
                output_dir=spec.get("outputDir", ""),
                temp_dir=spec.get("tempDir", ""),
            )
            self.task = task
        log_event(
            "任务",
            "启动任务",
            {
                "taskId": task.id,
                "outputDir": task.output_dir,
                "command": spec.get("commands") or spec.get("command"),
            },
        )
        threading.Thread(target=self._run, args=(task, spec), daemon=True).start()
        return task.id

    def _run(self, task, spec):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        flags = 0x08000000 if os.name == "nt" else 0
        try:
            commands = spec.get("commands") or [spec["command"]]
            with self.lock:
                task.command_total = len(commands)
            code = 0
            for command_index, command in enumerate(commands, 1):
                with self.lock:
                    task.command_index = command_index
                if len(commands) > 1:
                    with self.lock:
                        task.message = (
                            f"正在切片 {command_index}/{len(commands)}"
                        )
                process_cwd = _resolve_process_cwd(spec.get("cwd"))
                process = subprocess.Popen(
                    command,
                    cwd=process_cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=flags,
                    env=env,
                )
                with self.lock:
                    task.process = process
                assert process.stdout is not None
                for raw in process.stdout:
                    line = raw.rstrip()
                    if not line:
                        continue
                    self._handle_line(task, line)
                code = process.wait()
                log_event(
                    "进程",
                    "切片子进程结束",
                    {"pid": process.pid, "exitCode": code},
                )
                if code:
                    break
                if len(commands) > 1:
                    with self.lock:
                        task.progress = command_index / len(commands)
            with self.lock:
                task.finished_at = time.time()
                if task.status == "cancelled":
                    task.message = "已取消"
                elif code == 0:
                    task.status = "done"
                    task.progress = 1.0
                    task.message = "切片完成"
                else:
                    task.status = "error"
                    task.message = f"切片失败，退出码 {code}"
            log_event(
                "任务",
                "任务状态变化",
                {
                    "taskId": task.id,
                    "status": task.status,
                    "progress": task.progress,
                    "message": task.message,
                },
            )
        except Exception as exc:
            with self.lock:
                task.status = "error"
                task.message = str(exc)
                task.finished_at = time.time()
                task.logs.append(task.message)
            log_exception("任务", "切片任务异常：%s" % exc)
        finally:
            self._cleanup_task_artifacts(task)
            if task.temp_dir:
                shutil.rmtree(task.temp_dir, ignore_errors=True)

    def _handle_line(self, task, line):
        should_stop_fatal = False
        with self.lock:
            task.logs.append(line)
            if (
                not task.fatal_traceback
                and line.strip() == "Traceback (most recent call last):"
            ):
                task.fatal_traceback = True
                task.message = "切片遇到未处理异常，正在结束任务"
                should_stop_fatal = True
            elif line.startswith("BATCH|progress|"):
                value = line.split("|", 2)[2]
                match = re.match(r"(\d+)/(\d+)", value)
                if match:
                    done, total = int(match.group(1)), int(match.group(2))
                    task.progress = done / max(1, total)
                    task.message = f"正在切片 {done}/{total}"
                else:
                    task.message = value
            elif line.startswith("BATCH|status|"):
                task.message = line.split("|", 2)[2]
            elif line.startswith("BATCH|log|"):
                task.message = line.split("|", 2)[2][-120:]
            elif line.startswith("BATCH|done|"):
                task.message = "正在核对输出文件"
                task.progress = max(task.progress, 0.98)
            elif line.startswith("PLAN|progress|"):
                value = line.split("|", 2)[2]
                try:
                    local = min(1.0, max(0.0, float(value)))
                    if task.command_total > 1:
                        base = max(0, task.command_index - 1)
                        task.progress = min(
                            1.0,
                            (base + local) / task.command_total,
                        )
                    else:
                        task.progress = local
                except ValueError:
                    task.message = value
            elif line.startswith("PLAN|status|"):
                task.message = line.split("|", 2)[2]
        if should_stop_fatal:
            timer = threading.Timer(
                3.0, self._stop_after_fatal_traceback, args=(task,)
            )
            timer.daemon = True
            timer.start()
        log_event("切片输出", line, {"taskId": task.id})

    def _stop_after_fatal_traceback(self, task):
        with self.lock:
            if task.status != "running":
                return
            process = task.process
            task.status = "error"
            task.message = "切片失败，详见任务日志"
            task.finished_at = time.time()
        if process and process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    creationflags=0x08000000,
                    check=False,
                )
            else:
                process.terminate()

    def _cleanup_task_artifacts(self, task):
        """把技术诊断转入软件日志，输出目录只保留用户产物。"""
        output_dir = Path(task.output_dir)
        if not output_dir.is_dir():
            return
        diagnostic_names = {
            "切片诊断.txt",
            "切片报告.txt",
            "定位诊断.txt",
            "多色排盘错误日志.txt",
            "多色排盘崩溃详情.txt",
        }
        try:
            files = list(output_dir.rglob("*"))
        except OSError:
            return
        for path in files:
            if not path.is_file():
                continue
            if path.name in diagnostic_names:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                log_event(
                    "诊断",
                    "任务诊断：%s" % path.name,
                    {"taskId": task.id, "content": text[-64000:]},
                )
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            if (
                path.name.startswith(".layout_candidate_")
                and path.suffix.lower() == ".3mf"
            ):
                try:
                    path.unlink()
                except OSError:
                    pass

    def cancel(self):
        with self.lock:
            task = self.task
            if not task or task.status != "running" or not task.process:
                return False
            task.status = "cancelled"
            task.message = "正在停止"
            pid = task.process.pid
        log_event("任务", "请求取消", {"taskId": task.id, "pid": pid})
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                creationflags=0x08000000,
                check=False,
            )
        else:
            task.process.terminate()
        return True


CORE = LegacyCore()
TASKS = TaskManager()
log_event(
    "启动",
    "打印农场助手 1.5.0-beta.1 后端初始化完成",
    {
        "version": getattr(CORE.module, "VERSION", ""),
        "machines": CORE.app.machine_display,
        "frozen": FROZEN,
    },
)
