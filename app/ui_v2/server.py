# -*- coding: utf-8 -*-
"""打印农场助手的本机 OCR 与切片桥。

只监听 127.0.0.1，接收浏览器发来的图片 data URL，调用现有 ocr.py，
返回 Windows OCR 识别出的文字。切片任务仍由原 Python 程序执行。
"""

import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_DIR = (
    os.path.join(ROOT, "切片软件")
    if getattr(sys, "frozen", False)
    else os.path.join(os.path.dirname(ROOT), "切片软件")
)
STATIC_ROOT = os.path.join(ROOT, "dist")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import ocr  # noqa: E402
from service import CORE, PUBLIC_EDITION, TASKS, UPLOAD_ROOT  # noqa: E402
from local_log import LOG_DIR, log_event, log_exception, tail  # noqa: E402


WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

MODEL_SUFFIXES = (".stl", ".3mf", ".step", ".stp")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024


def _cleanup_upload_sessions(root=None):
    """Drop temporary model copies from previous app sessions."""
    root = Path(root or UPLOAD_ROOT)
    if not root.is_dir():
        return 0
    removed = 0
    for child in root.iterdir():
        if (
            not child.is_dir()
            or len(child.name) != 32
            or any(ch not in "0123456789abcdef" for ch in child.name)
        ):
            continue
        try:
            shutil.rmtree(child)
            removed += 1
        except OSError:
            log_exception(
                "导入",
                "清理旧上传会话失败：%s" % child.name,
            )
    return removed


def _is_local_origin(value):
    """Allow the bundled UI and local Vite preview, nothing else."""
    try:
        parsed = urlparse(str(value or ""))
    except ValueError:
        return False
    return (
        parsed.scheme in ("http", "https")
        and parsed.hostname in ("127.0.0.1", "localhost")
    )


def _is_local_host(value):
    """Reject DNS-rebinding requests that reach the loopback listener."""
    try:
        parsed = urlparse("//" + str(value or ""))
    except ValueError:
        return False
    return parsed.hostname in ("127.0.0.1", "localhost")


def _thumbnail_data_uri(path: Path):
    """提取 Bambu 3MF 自带的盘面缩略图，避免前端重复渲染模型。"""
    if path.suffix.lower() != ".3mf":
        return ""
    preferred = (
        "Metadata/plate_1_small.png",
        "Metadata/plate_1.png",
        "Metadata/plate_no_light_1.png",
        "Metadata/top_1.png",
        "Metadata/thumbnail.png",
    )
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            candidates = list(preferred)
            candidates.extend(sorted(
                name for name in names
                if "thumbnail" in name.lower()
                and name.lower().endswith((".png", ".jpg", ".jpeg"))
            ))
            for name in candidates:
                if name not in names:
                    continue
                data = archive.read(name)
                if not data or len(data) > 2 * 1024 * 1024:
                    continue
                suffix = Path(name).suffix.lower()
                mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
                return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    except (OSError, zipfile.BadZipFile, KeyError):
        pass
    return ""


def _project_parameter_summary(path: Path):
    """Read the process parameters embedded in a Bambu 3MF project."""
    if path.suffix.lower() != ".3mf":
        return {"hasEmbeddedSettings": False}
    try:
        with zipfile.ZipFile(path) as archive:
            if "Metadata/project_settings.config" not in archive.namelist():
                return {"hasEmbeddedSettings": False}
            config = json.loads(
                archive.read("Metadata/project_settings.config").decode(
                    "utf-8", "replace"
                )
            )
    except (OSError, ValueError, zipfile.BadZipFile):
        return {"hasEmbeddedSettings": False}

    def first(key):
        value = config.get(key)
        if isinstance(value, list):
            return value[0] if value else None
        return value

    def text(key):
        value = first(key)
        return "" if value is None else str(value).strip()

    layer_height = text("layer_height")
    infill = text("sparse_infill_density")
    if infill and not infill.endswith("%"):
        infill += "%"
    support = text("enable_support").lower() in ("1", "true", "yes")
    plate_only = text("support_on_build_plate_only").lower() in (
        "1", "true", "yes"
    )
    result = {
        "hasEmbeddedSettings": True,
        "layerHeight": layer_height,
        "infill": infill,
        "pattern": text("sparse_infill_pattern"),
        "supportEnabled": support,
        "supportType": text("support_type"),
        "supportPlateOnly": plate_only,
        "material": text("filament_type"),
    }
    return {
        key: value
        for key, value in result.items()
        if value not in ("", None)
    }


def _safe_upload_target(session: Path, relative_path: str, fallback: str):
    """把浏览器给出的相对路径安全地落到本次上传目录。"""
    raw_parts = str(relative_path or fallback).replace("\\", "/").split("/")
    parts = []
    for raw in raw_parts:
        if raw in ("", "."):
            continue
        if raw == "..":
            raise ValueError("导入路径不能跳出上传目录")
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).rstrip(" .")
        if not clean:
            clean = "_"
        if clean.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
            clean = "_" + clean
        parts.append(clean)
    if not parts:
        raise ValueError("模型文件名无效")
    target = session.joinpath(*parts)
    session_root = session.resolve()
    resolved = target.resolve()
    if session_root not in resolved.parents:
        raise ValueError("导入路径不能跳出上传目录")
    if target.exists():
        suffix = target.suffix
        stem = target.name[:-len(suffix)] if suffix else target.name
        counter = 2
        while target.exists():
            target = target.with_name(f"{stem}_{counter}{suffix}")
            counter += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _upload_session(value):
    session_id = str(value or "").strip().lower()
    try:
        if uuid.UUID(session_id).hex != session_id:
            raise ValueError
    except (AttributeError, ValueError):
        raise ValueError("导入会话无效")
    session = UPLOAD_ROOT / session_id
    if not session.is_dir():
        raise ValueError("导入会话不存在")
    return session


def _import_job(session: Path, target: Path):
    name = target.name
    material = "待识别"
    color = ""
    merge_parts = 1
    merge_issue = ""
    if target.suffix.lower() == ".3mf":
        if not zipfile.is_zipfile(target):
            raise ValueError(f"{name} 不是完整的 3MF 工程")
        try:
            import unpack_3mf
            info = unpack_3mf.project_filament_info(str(target))
            merge_parts = unpack_3mf.count_printable_parts(str(target))
            classes = info.get("color_classes") or []
            if len(classes) == 1:
                color = str(classes[0])
                material = "单色工程"
            elif classes:
                material = "%d 色工程" % len(classes)
            used_colors = info.get("used_colors") or []
            used_types = info.get("used_types") or []
            if len(used_colors) > 1 or len(used_types) > 1:
                merge_issue = "检测到多色或多材料，请改用多色排盘"
        except Exception:
            pass
    return {
        "path": str(target),
        "name": name,
        "relativePath": target.relative_to(session).as_posix(),
        "size": target.stat().st_size,
        "material": material,
        "color": color,
        "preview": _thumbnail_data_uri(target),
        "fileSettings": _project_parameter_summary(target),
        "mergeParts": merge_parts,
        "mergeIssue": merge_issue,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "TuozhuUI/0.1"

    def _send(self, status, payload):
        body = (
            b""
            if status == 204
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self.headers.get("Origin", "")
        if origin and _is_local_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Vary", "Origin")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _guard_request(self):
        """Block cross-site webpages and DNS rebinding from calling local APIs."""
        origin = self.headers.get("Origin", "")
        if origin and not _is_local_origin(origin):
            self._send(403, {"ok": False, "error": "local origin required"})
            return False
        site = self.headers.get("Sec-Fetch-Site", "")
        if site == "cross-site":
            self._send(403, {"ok": False, "error": "cross-site request blocked"})
            return False
        if not _is_local_host(self.headers.get("Host", "")):
            self._send(403, {"ok": False, "error": "local host required"})
            return False
        return True

    def do_OPTIONS(self):  # noqa: N802
        if not self._guard_request():
            return
        self._send(204, {})

    def do_GET(self):  # noqa: N802
        if not self._guard_request():
            return
        path = urlparse(self.path).path
        if path == "/api/health":
            available, reason = ocr.available()
            self._send(200, {"ok": available, "reason": reason})
            return
        if path == "/api/state":
            self._send(200, {"ok": True, **TASKS.snapshot()})
            return
        if path == "/api/config":
            self._send(
                200,
                {
                    "ok": True,
                    "machines": list(CORE.app.machine_display),
                    "materials": [
                        value[0]
                        for value in CORE.SliceApp.MATERIAL_INFO.values()
                    ],
                    "machine": CORE.app.cfg.get("machine", ""),
                    "process": CORE.app.cfg.get("process", ""),
                    "filament": CORE.app.cfg.get("filament", ""),
                    "bed": CORE.app.cfg.get("bed", "Textured PEI Plate"),
                    "outputDir": CORE.app.cfg.get(
                        "output_dir",
                        os.path.join(os.path.expanduser("~"), "Desktop", "切片文件"),
                    ),
                },
            )
            return
        if path == "/api/meta":
            self._send(200, {"ok": True, **CORE.metadata()})
            return
        if path == "/api/logs":
            self._send(
                200,
                {"ok": True, "path": str(LOG_DIR), "text": tail(300)},
            )
            return
        if path == "/api/open-logs":
            try:
                os.makedirs(LOG_DIR, exist_ok=True)
                os.startfile(str(LOG_DIR))  # noqa: S606
                self._send(200, {"ok": True, "path": str(LOG_DIR)})
            except OSError as exc:
                self._send(500, {"ok": False, "error": str(exc)[:160]})
            return
        if path.startswith("/api/"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        self._serve_static(path)

    def do_POST(self):  # noqa: N802
        if not self._guard_request():
            return
        parsed_request = urlparse(self.path)
        request_path = parsed_request.path
        request_query = parse_qs(parsed_request.query)
        if self.path == "/api/open-pet":
            if PUBLIC_EDITION:
                self._send(
                    403,
                    {"ok": False, "error": "公开版不提供悬浮助手"},
                )
                return
            script = os.path.join(APP_DIR, "pet.py")
            if not os.path.isfile(script):
                self._send(404, {"ok": False, "error": "找不到桌面挂件 pet.py"})
                return
            try:
                flags = 0x08000000 if os.name == "nt" else 0
                command = (
                    [sys.executable, "--pet"]
                    if getattr(sys, "frozen", False)
                    else [sys.executable, script]
                )
                subprocess.Popen(command, cwd=APP_DIR, creationflags=flags)
                log_event("助手", "启动桌面悬浮助手", {"command": command})
                self._send(200, {"ok": True, "mode": "desktop"})
            except OSError as exc:
                self._send(500, {"ok": False, "error": str(exc)[:160]})
            return
        if self.path == "/api/parse":
            try:
                payload = self._read_json(4 * 1024 * 1024)
                text = str(payload.get("text") or "")
                models = [
                    str(path) for path in payload.get("models", [])
                    if os.path.isfile(str(path))
                ]
                result = CORE.parse(text, models)
                self._send(200, {"ok": True, **result})
            except Exception as exc:  # noqa: BLE001
                log_exception("参数", "参数解析接口失败")
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if self.path == "/api/log":
            try:
                payload = self._read_json(1024 * 1024)
                log_event(
                    str(payload.get("category") or "界面"),
                    str(payload.get("message") or ""),
                    payload.get("data"),
                )
                self._send(200, {"ok": True})
            except Exception as exc:  # noqa: BLE001
                log_exception("日志", "写入前端日志失败")
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if request_path == "/api/import/start":
            try:
                session = UPLOAD_ROOT / uuid.uuid4().hex
                session.mkdir(parents=True, exist_ok=False)
                self._send(200, {"ok": True, "sessionId": session.name})
            except Exception as exc:  # noqa: BLE001
                log_exception("导入", "创建导入会话失败")
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if request_path == "/api/import/release":
            if TASKS.snapshot().get("busy"):
                self._send(
                    409,
                    {"ok": False, "error": "切片运行中不能清理上传文件"},
                )
                return
            try:
                removed = _cleanup_upload_sessions()
                self._send(200, {"ok": True, "removed": removed})
            except Exception as exc:  # noqa: BLE001
                log_exception("导入", "清理上传会话失败")
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if request_path == "/api/import/file":
            target = None
            try:
                session = _upload_session(
                    (request_query.get("session") or [""])[0])
                relative_path = (
                    request_query.get("relativePath") or [""])[0]
                name = Path(relative_path).name
                if not name.lower().endswith(MODEL_SUFFIXES):
                    raise ValueError("不是支持的模型文件")
                if name.lower().endswith(".gcode.3mf"):
                    raise ValueError("已经切片的 3MF 不能再次导入")
                target = _safe_upload_target(
                    session, relative_path, name or "model.stl")
                self._write_request_body(target)
                self._send(
                    200,
                    {
                        "ok": True,
                        "path": str(target),
                        "relativePath": target.relative_to(session).as_posix(),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                if target is not None:
                    try:
                        target.unlink()
                    except OSError:
                        pass
                log_exception("导入", "流式写入模型失败")
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if request_path == "/api/import/finish":
            try:
                session = _upload_session(
                    (request_query.get("session") or [""])[0])
                jobs = []
                issues = []
                for target in sorted(
                    (
                        path for path in session.rglob("*")
                        if path.is_file()
                        and path.suffix.lower() in MODEL_SUFFIXES
                    ),
                    key=lambda path: path.relative_to(session).as_posix(),
                ):
                    try:
                        jobs.append(_import_job(session, target))
                    except Exception as exc:  # noqa: BLE001
                        issues.append(str(exc))
                        try:
                            target.unlink()
                        except OSError:
                            pass
                self._send(
                    200 if jobs else 400,
                    {
                        "ok": bool(jobs),
                        "jobs": jobs,
                        "issues": issues,
                        "error": "；".join(issues),
                    },
                )
                log_event(
                    "导入",
                    "流式导入模型文件",
                    {"jobs": jobs, "issues": issues},
                )
            except Exception as exc:  # noqa: BLE001
                log_exception("导入", "完成模型导入失败")
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if self.path == "/api/import":
            try:
                payload = self._read_json(256 * 1024 * 1024)
                session = UPLOAD_ROOT / uuid.uuid4().hex
                session.mkdir(parents=True, exist_ok=True)
                jobs = []
                issues = []
                for item in payload.get("files", []):
                    name = Path(str(item.get("name") or "model.stl")).name
                    relative_path = str(
                        item.get("relativePath") or name
                    )
                    if not name.lower().endswith((".stl", ".3mf", ".step", ".stp")):
                        continue
                    if name.lower().endswith(".gcode.3mf"):
                        issues.append(f"{name} 已经切片，请导入原始 3MF")
                        continue
                    target = _safe_upload_target(
                        session, relative_path, name
                    )
                    raw = str(item.get("data") or "")
                    if "," in raw:
                        raw = raw.split(",", 1)[1]
                    target.write_bytes(base64.b64decode(raw))
                    if target.suffix.lower() == ".3mf" and not zipfile.is_zipfile(target):
                        issues.append(f"{name} 不是完整的 3MF 工程")
                        try:
                            target.unlink()
                        except OSError:
                            pass
                        continue
                    material = "待识别"
                    color = ""
                    merge_parts = 1
                    merge_issue = ""
                    if target.suffix.lower() == ".3mf":
                        try:
                            import unpack_3mf
                            info = unpack_3mf.project_filament_info(str(target))
                            merge_parts = unpack_3mf.count_printable_parts(
                                str(target))
                            classes = info.get("color_classes") or []
                            if len(classes) == 1:
                                color = str(classes[0])
                                material = "单色工程"
                            elif classes:
                                material = "%d 色工程" % len(classes)
                            used_colors = info.get("used_colors") or []
                            used_types = info.get("used_types") or []
                            if (len(used_colors) > 1
                                    or len(used_types) > 1):
                                merge_issue = (
                                    "检测到多色或多材料，请改用多色排盘")
                        except Exception:
                            pass
                    jobs.append(
                        {
                            "path": str(target),
                            "name": name,
                            "relativePath": target.relative_to(session).as_posix(),
                            "size": target.stat().st_size,
                            "material": material,
                            "color": color,
                            "preview": _thumbnail_data_uri(target),
                            "fileSettings": _project_parameter_summary(target),
                            "mergeParts": merge_parts,
                            "mergeIssue": merge_issue,
                        }
                    )
                self._send(
                    200 if jobs else 400,
                    {
                        "ok": bool(jobs),
                        "jobs": jobs,
                        "issues": issues,
                        "error": "；".join(issues),
                    },
                )
                log_event(
                    "导入",
                    "导入模型文件",
                    {"jobs": jobs, "issues": issues},
                )
            except Exception as exc:  # noqa: BLE001
                log_exception("导入", "模型导入失败")
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if self.path == "/api/slice":
            try:
                payload = self._read_json(4 * 1024 * 1024)
                spec = CORE.build_command(
                    mode=str(payload.get("mode") or "workbench"),
                    models=[os.path.abspath(str(path)) for path in payload.get("models", [])],
                    settings=payload.get("settings") or {},
                    command_text=str(payload.get("command") or ""),
                    output_dir=os.path.abspath(str(payload.get("outputDir") or "")),
                    batch_items=payload.get("batchItems") or [],
                )
                CORE.persist_settings(
                    os.path.abspath(str(payload.get("outputDir") or "")),
                    payload.get("settings") or {},
                    str(payload.get("mode") or "workbench"),
                )
                task_id = TASKS.start(spec)
                log_event(
                    "切片",
                    "切片接口已受理",
                    {"taskId": task_id, "mode": payload.get("mode")},
                )
                self._send(200, {"ok": True, "taskId": task_id, **TASKS.snapshot()})
            except Exception as exc:  # noqa: BLE001
                log_exception("切片", "启动切片接口失败")
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if self.path == "/api/cancel":
            self._send(200, {"ok": TASKS.cancel(), **TASKS.snapshot()})
            return
        if self.path == "/api/rules":
            try:
                payload = self._read_json(1024 * 1024)
                meta = CORE.rule_action(
                    str(payload.get("action") or ""),
                    str(payload.get("norm") or ""),
                    bool(payload.get("enabled", True)),
                )
                self._send(200, {"ok": True, **meta})
            except Exception as exc:  # noqa: BLE001
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if self.path == "/api/open-output":
            try:
                payload = self._read_json(1024 * 1024)
                folder = os.path.abspath(str(payload.get("path") or ""))
                if not os.path.isdir(folder):
                    raise ValueError("输出目录不存在")
                os.startfile(folder)  # noqa: S606
                log_event("输出", "打开输出目录", {"path": folder})
                self._send(200, {"ok": True})
            except Exception as exc:  # noqa: BLE001
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if self.path == "/api/choose-output":
            try:
                script = os.path.join(ROOT, "native_dialog.py")
                flags = 0x08000000 if os.name == "nt" else 0
                UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
                result_path = UPLOAD_ROOT / (
                    ".choose-output-%s.json" % uuid.uuid4().hex
                )
                command = (
                    [sys.executable, "--choose-output", str(result_path)]
                    if getattr(sys, "frozen", False)
                    else [sys.executable, script, str(result_path)]
                )
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=flags,
                    timeout=180,
                )
                folder = ""
                if result_path.is_file():
                    try:
                        payload = json.loads(
                            result_path.read_text(encoding="utf-8")
                        )
                        folder = str(payload.get("path") or "")
                    except (OSError, ValueError):
                        folder = ""
                if not folder:
                    folder = result.stdout.strip()
                log_event(
                    "输出",
                    "选择输出目录",
                    {"path": folder, "stderr": result.stderr[-300:]},
                )
                try:
                    result_path.unlink()
                except OSError:
                    pass
                self._send(
                    200 if folder else 400,
                    {"ok": bool(folder), "path": folder,
                     "error": "" if folder else (result.stderr or "未选择目录")[:240]},
                )
            except Exception as exc:  # noqa: BLE001
                self._send(400, {"ok": False, "error": str(exc)[:240]})
            return
        if self.path != "/api/ocr":
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16 * 1024 * 1024:
                self._send(413, {"ok": False, "error": "图片太大或请求为空"})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            image_data = str(payload.get("image") or "")
            if "," in image_data:
                image_data = image_data.split(",", 1)[1]
            raw = base64.b64decode(image_data, validate=True)
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            log_event(
                "OCR",
                "开始识别图片",
                {"bytes": len(raw), "size": image.size},
            )
            ok, text, note = ocr.read_image(image)
            log_event(
                "OCR",
                "图片识别完成",
                {"ok": ok, "text": text, "note": note},
            )
            self._send(
                200 if ok else 422,
                {
                    "ok": bool(ok),
                    "text": text if ok else "",
                    "note": note if ok else "",
                    "error": "" if ok else (note or "没认出文字"),
                },
            )
        except Exception as exc:  # noqa: BLE001
            log_exception("OCR", "图片识别失败")
            self._send(500, {"ok": False, "error": str(exc)[:160]})

    def log_message(self, _format, *_args):
        return

    def log_request(self, code="-", size="-"):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            log_event(
                "接口",
                "HTTP 请求",
                {
                    "method": getattr(self, "command", ""),
                    "path": path,
                    "status": code,
                    "bytes": size,
                },
            )

    def _read_json(self, limit):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > limit:
            raise ValueError("请求为空或文件太大")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _write_request_body(self, target: Path):
        remaining = int(self.headers.get("Content-Length", "0"))
        if remaining <= 0 or remaining > MAX_UPLOAD_BYTES:
            raise ValueError("模型文件为空或太大")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise OSError("模型上传连接提前中断")
                handle.write(chunk)
                remaining -= len(chunk)

    def _serve_static(self, request_path):
        rel = unquote(request_path).lstrip("/") or "index.html"
        target = os.path.abspath(os.path.join(STATIC_ROOT, rel))
        root = os.path.abspath(STATIC_ROOT)
        if not target.startswith(root + os.sep) and target != root:
            self._send(403, {"ok": False, "error": "forbidden"})
            return
        if not os.path.isfile(target):
            target = os.path.join(root, "index.html")
        if not os.path.isfile(target):
            self._send(404, {"ok": False, "error": "frontend not built"})
            return
        ext = os.path.splitext(target)[1].lower()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".ico": "image/x-icon",
            ".png": "image/png",
            ".woff2": "font/woff2",
        }.get(ext, "application/octet-stream")
        try:
            with open(target, "rb") as handle:
                body = handle.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        except OSError as exc:
            self._send(500, {"ok": False, "error": str(exc)[:160]})


if __name__ == "__main__":
    _cleanup_upload_sessions()
    available, reason = ocr.available()
    if not available:
        print("OCR 不可用：%s" % reason)
    server = ThreadingHTTPServer(("127.0.0.1", 4180), Handler)
    print("OCR bridge: http://127.0.0.1:4180")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
