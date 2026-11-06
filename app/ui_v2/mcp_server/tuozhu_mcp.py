#!/usr/bin/env python3
"""PrintFarm Assistant MCP server.

The server intentionally exposes a small, typed surface over stdio. It never
provides arbitrary shell execution or unrestricted filesystem access.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SERVER_NAME = "tuozhu-assistant"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"
API_BASE = os.environ.get(
    "TUOZHU_MCP_API_BASE", "http://127.0.0.1:4180"
).rstrip("/")
MODEL_EXTENSIONS = {".stl", ".3mf", ".step", ".stp"}
MAX_MODELS = 200
MAX_MODEL_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024

DEFAULT_SETTINGS: dict[str, Any] = {
    "printer": "Bambu Lab H2S",
    "material": "PLA",
    "bedType": "Textured PEI Plate",
    "layerHeight": "0.16",
    "infill": "15",
    "pattern": "grid",
    "supportMode": "tree_plate",
    "autoArrange": False,
    "orientation": False,
    "tightPacking": False,
    "minSupport": False,
    "clone": "1",
    "outputMode": "gcode",
    "maxColors": "4",
    "hideSeam": False,
    "topIroning": False,
}


class ToolError(RuntimeError):
    """A safe error that can be returned to an MCP client."""


def log(message: str) -> None:
    print(f"[tuozhu-mcp] {message}", file=sys.stderr, flush=True)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _assistant_candidates() -> list[Path]:
    candidates: list[Path] = []
    for key in ("TUOZHU_ASSISTANT_EXE", "PRINTFARM_ASSISTANT_EXE"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            candidates.append(Path(value))

    current = Path(sys.executable if getattr(sys, "frozen", False) else __file__)
    for parent in current.resolve().parents:
        candidates.extend((
            parent / "PrintFarmAssistant.exe",
            parent / "拓竹助手V2.exe",
            parent / "拓竹助手.exe",
        ))

    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    candidates.extend((
        local / "Programs" / "PrintFarmAssistant" / "PrintFarmAssistant.exe",
        local / "Programs" / "拓竹助手V2" / "拓竹助手V2.exe",
        local / "Programs" / "拓竹助手" / "拓竹助手.exe",
        home / "AppData" / "Local" / "Programs" / "PrintFarmAssistant"
        / "PrintFarmAssistant.exe",
    ))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        resolved = str(candidate.resolve())
        if resolved not in seen and candidate.is_file():
            seen.add(resolved)
            unique.append(candidate.resolve())
    return unique


def find_assistant() -> Path:
    candidates = _assistant_candidates()
    if not candidates:
        raise ToolError(
            "没有找到打印农场助手。请先安装，或设置 TUOZHU_ASSISTANT_EXE。"
        )
    return candidates[0]


def _data_candidates(assistant: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    env = str(os.environ.get("TUOZHU_HOME") or "").strip()
    if env:
        paths.extend((Path(env), Path(env) / "切片软件"))
    if assistant is not None:
        paths.extend((assistant.parent, assistant.parent / "_internal"))
    source_root = Path(__file__).resolve().parents[2]
    paths.append(source_root / "切片软件")
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    paths.extend((
        local / "Programs" / "PrintFarmAssistant" / "_internal",
        local / "Programs" / "拓竹助手V2" / "_internal",
        local / "Programs" / "拓竹助手" / "_internal",
    ))
    return paths


def find_data_dir() -> Path:
    assistant = None
    try:
        assistant = find_assistant()
    except ToolError:
        pass
    for path in _data_candidates(assistant):
        if (path / "bambu_wiki_paths.json").is_file():
            return path
    raise ToolError("没有找到 Bambu 参数百科数据。")


def _read_version(assistant: Path) -> str:
    for path in (
        assistant.parent / "version.txt",
        assistant.parent / "_internal" / "version.txt",
    ):
        try:
            return path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            continue
    return str(assistant.stat().st_size)


def _api_request(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> Any:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(
        API_BASE + path, data=body, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            result = json.loads(raw.decode("utf-8"))
            status = int(getattr(response, "status", 200))
            if not 200 <= status < 300 or result.get("ok") is False:
                raise ToolError(str(result.get("error") or "本机服务返回失败"))
            return result
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw).get("error")
        except (ValueError, AttributeError):
            detail = raw[:240]
        raise ToolError(str(detail or f"本机服务返回 HTTP {exc.code}")) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolError(
            "打印农场助手的本机服务没有启动。先调用 assistant_status "
            "并将 start_if_needed 设为 true。"
        ) from exc


def _health() -> dict[str, Any]:
    return _api_request("/api/health", timeout=3)


def _start_assistant() -> Path:
    assistant = find_assistant()
    flags = 0x08000000 if os.name == "nt" else 0
    subprocess.Popen(
        [str(assistant)],
        cwd=str(assistant.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            _health()
            return assistant
        except ToolError:
            time.sleep(0.35)
    raise ToolError("启动打印农场助手后，本机服务仍未在 25 秒内就绪。")


def _ensure_running(start_if_needed: bool = True) -> Path | None:
    try:
        _health()
        return None
    except ToolError:
        if not start_if_needed:
            raise
        return _start_assistant()


def _allowed_roots() -> list[Path]:
    configured = str(os.environ.get("TUOZHU_MCP_ALLOWED_ROOTS") or "").strip()
    candidates = (
        [Path(item.strip()) for item in configured.split(";") if item.strip()]
        if configured
        else [
            Path.home() / "Desktop",
            Path.home() / "Downloads",
            Path.home() / "Documents",
        ]
    )
    roots: list[Path] = []
    for candidate in candidates:
        try:
            roots.append(candidate.expanduser().resolve(strict=True))
        except OSError:
            continue
    if not roots:
        raise ToolError("没有可用的模型目录。请设置 TUOZHU_MCP_ALLOWED_ROOTS。")
    return roots


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_path(path_value: str) -> Path:
    try:
        path = Path(path_value).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ToolError(f"路径不存在：{path_value}") from exc
    roots = _allowed_roots()
    if not any(_within(path, root) for root in roots):
        allowed = "；".join(str(root) for root in roots)
        raise ToolError(f"路径不在允许目录内：{path}。允许目录：{allowed}")
    return path


def _collect_models(paths: list[str], recursive: bool = False) -> list[Path]:
    if not paths:
        raise ToolError("paths 不能为空。")
    models: list[Path] = []
    roots = _allowed_roots()
    for value in paths:
        path = _validate_path(str(value))
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            for child in iterator:
                if len(models) >= MAX_MODELS:
                    raise ToolError(f"模型数量超过限制：{MAX_MODELS}")
                if child.is_file() and child.suffix.lower() in MODEL_EXTENSIONS:
                    resolved = child.resolve(strict=True)
                    if not any(_within(resolved, root) for root in roots):
                        raise ToolError(f"目录中的链接指向允许范围外：{resolved}")
                    models.append(resolved)
        elif path.suffix.lower() in MODEL_EXTENSIONS:
            models.append(path)
        else:
            raise ToolError(f"不支持的模型文件：{path.name}")
    unique = list(dict.fromkeys(models))
    if not unique:
        raise ToolError("没有找到 STL、3MF、STEP 或 STP 模型。")
    if len(unique) > MAX_MODELS:
        raise ToolError(f"模型数量超过限制：{MAX_MODELS}")
    total = 0
    for path in unique:
        size = path.stat().st_size
        if size > MAX_MODEL_BYTES:
            raise ToolError(f"单个模型超过 1 GB：{path.name}")
        total += size
    if total > MAX_TOTAL_BYTES:
        raise ToolError("模型总大小超过 4 GB。")
    return unique


def _validate_output_dir(path_value: str | None) -> Path:
    if path_value:
        path = Path(path_value).expanduser().resolve()
        roots = _allowed_roots()
        if not any(_within(path, root) for root in roots):
            allowed = "；".join(str(root) for root in roots)
            raise ToolError(f"输出目录不在允许范围：{path}。允许目录：{allowed}")
    else:
        path = Path.home() / "Documents" / "PrintFarmAssistantOutput"
        path.mkdir(parents=True, exist_ok=True)
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ToolError(f"输出路径不是目录：{path}")
    return path


def _text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def _number_text(value: Any, default: str, minimum: float, maximum: float) -> str:
    text = _text(value, default)
    try:
        number = float(text)
    except ValueError as exc:
        raise ToolError(f"参数必须是数字：{text}") from exc
    if number < minimum or number > maximum:
        raise ToolError(f"参数超出范围：{number}")
    return text


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ToolError("布尔参数必须是 true 或 false。")


def _normalise_settings(raw: Any, config: dict[str, Any]) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ToolError("settings 必须是对象。")
    printer = _text(raw.get("printer"), config.get("machine") or DEFAULT_SETTINGS["printer"])
    printer = printer.removesuffix(" 0.4 nozzle").strip()
    pattern = _text(raw.get("pattern"), DEFAULT_SETTINGS["pattern"]).lower()
    if pattern not in {"grid", "lines", "gyroid", "honeycomb", "cubic"}:
        raise ToolError("pattern 必须是 grid/lines/gyroid/honeycomb/cubic。")
    support = _text(raw.get("supportMode"), DEFAULT_SETTINGS["supportMode"])
    if support not in {"off", "tree_plate", "tree_all", "normal_plate", "normal_all"}:
        raise ToolError("supportMode 不受支持。")
    output_mode = _text(raw.get("outputMode"), DEFAULT_SETTINGS["outputMode"])
    if output_mode not in {"gcode", "3mf"}:
        raise ToolError("outputMode 必须是 gcode 或 3mf。")
    settings = {
        "printer": printer,
        "material": _text(raw.get("material"), DEFAULT_SETTINGS["material"]),
        "bedType": _text(raw.get("bedType"), config.get("bed") or DEFAULT_SETTINGS["bedType"]),
        "layerHeight": _number_text(raw.get("layerHeight"), "0.16", 0.04, 1),
        "infill": _number_text(raw.get("infill"), "15", 0, 100),
        "pattern": pattern,
        "supportMode": support,
        "autoArrange": _bool(raw.get("autoArrange"), False),
        "orientation": _bool(raw.get("orientation"), False),
        "tightPacking": _bool(raw.get("tightPacking"), False),
        "minSupport": _bool(raw.get("minSupport"), False),
        "clone": _number_text(raw.get("clone"), "1", 1, 100),
        "outputMode": output_mode,
        "maxColors": "4",
        "hideSeam": _bool(raw.get("hideSeam"), False),
        "topIroning": _bool(raw.get("topIroning"), False),
    }
    policy = raw.get("parameterPolicy")
    if policy is not None:
        if not isinstance(policy, dict):
            raise ToolError("parameterPolicy 必须是对象。")
        mode = _text(policy.get("mode"), "habit")
        if mode not in {"file", "habit", "custom"}:
            raise ToolError("parameterPolicy.mode 必须是 file/habit/custom。")
        overrides_raw = policy.get("overrides") or {}
        if not isinstance(overrides_raw, dict):
            raise ToolError("parameterPolicy.overrides 必须是对象。")
        settings["parameterPolicy"] = {
            "mode": mode,
            "overrides": {
                key: bool(overrides_raw.get(key, False))
                for key in ("layerHeight", "infill", "pattern", "support")
            },
        }
    return settings


def assistant_status(start_if_needed: bool = False) -> dict[str, Any]:
    try:
        health = _health()
        state = _api_request("/api/state", timeout=5)
        config = _api_request("/api/config", timeout=5)
        return {
            "running": True,
            "health": health,
            "task": state.get("task"),
            "config": {
                "machine": config.get("machine"),
                "bed": config.get("bed"),
                "outputDir": config.get("outputDir"),
                "machines": config.get("machines", []),
                "materials": config.get("materials", []),
            },
        }
    except ToolError:
        if not start_if_needed:
            return {"running": False, "assistant": str(find_assistant())}
        assistant = _start_assistant()
        return {
            "running": True,
            "assistant": str(assistant),
            "health": _health(),
        }


def lookup_parameters(names: list[str]) -> list[dict[str, Any]]:
    if not names:
        raise ToolError("names 不能为空。")
    if len(names) > 10:
        raise ToolError("一次最多查询 10 个参数。")
    data = find_data_dir()
    with (data / "bambu_wiki_catalog.json").open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    tabs_path = data / "bambu_wiki_tabs.json"
    tabs = {}
    if tabs_path.is_file():
        with tabs_path.open(encoding="utf-8") as handle:
            tabs = json.load(handle)
    flat: dict[str, dict[str, Any]] = {}
    for layer, values in catalog.items():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            if isinstance(value, dict):
                flat[str(key)] = {"key": key, "layer": layer, **value}
    results = []
    for queried in names:
        needle = str(queried).strip()
        matches = []
        for key, item in flat.items():
            label = str(item.get("cn") or "")
            if (
                key.lower() == needle.lower()
                or label == needle
                or (needle and needle.lower() in key.lower())
                or (needle and needle in label)
            ):
                tab = tabs.get(key) or {}
                parts = [
                    tab.get("page_cn") or tab.get("page"),
                    tab.get("group_cn") or tab.get("group"),
                    tab.get("row_cn") or tab.get("row"),
                ]
                path = " → ".join(str(part) for part in parts if part)
                matches.append({
                    "query": queried,
                    "key": key,
                    "name": label or key,
                    "layer": item.get("layer"),
                    "path": path,
                    "default": item.get("default"),
                })
        results.append({
            "query": queried,
            "matches": matches[:8],
            "found": bool(matches),
        })
    return results


def slice_files(
    paths: list[str],
    *,
    output_dir: str | None,
    mode: str | None,
    recursive: bool,
    settings: Any,
    command_text: str,
) -> dict[str, Any]:
    _ensure_running(True)
    models = _collect_models(paths, recursive)
    output = _validate_output_dir(output_dir)
    config = _api_request("/api/config", timeout=5)
    selected_mode = mode or ("batch" if len(models) > 1 else "workbench")
    if selected_mode not in {"workbench", "batch"}:
        raise ToolError("mode 必须是 workbench 或 batch。")
    payload = {
        "mode": selected_mode,
        "models": [str(path) for path in models],
        "settings": _normalise_settings(settings, config),
        "command": str(command_text or ""),
        "outputDir": str(output),
    }
    result = _api_request("/api/slice", method="POST", payload=payload, timeout=30)
    return {
        "taskId": result.get("taskId"),
        "mode": selected_mode,
        "models": [str(path) for path in models],
        "outputDir": str(output),
        "state": result.get("task"),
    }


def job_status() -> dict[str, Any]:
    return _api_request("/api/state", timeout=5)


def cancel_job() -> dict[str, Any]:
    return _api_request(
        "/api/cancel", method="POST", payload={}, timeout=10
    )


def open_output() -> dict[str, Any]:
    state = _api_request("/api/state", timeout=5)
    task = state.get("task") or {}
    folder = str(task.get("outputDir") or "")
    if not folder:
        config = _api_request("/api/config", timeout=5)
        folder = str(config.get("outputDir") or "")
    if not folder:
        raise ToolError("没有可打开的输出目录。")
    path = Path(folder).expanduser().resolve()
    if not path.is_dir():
        raise ToolError(f"输出目录不存在：{path}")
    return _api_request(
        "/api/open-output",
        method="POST",
        payload={"path": str(path)},
        timeout=10,
    )


def _tool(name: str, description: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            **schema,
        },
    }


TOOLS = [
    _tool(
        "assistant_status",
        "Check the local PrintFarm Assistant service and current task. "
        "Set start_if_needed=true to launch the installed desktop app.",
        {
            "properties": {
                "start_if_needed": {"type": "boolean", "default": False},
            },
        },
    ),
    _tool(
        "find_assistant",
        "Find the installed PrintFarm Assistant executable without launching it.",
        {"properties": {}},
    ),
    _tool(
        "lookup_parameter",
        "Look up real Bambu Studio parameter names and paths from the local "
        "parameter database. Never invent UI paths.",
        {
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 10,
                },
            },
            "required": ["names"],
        },
    ),
    _tool(
        "slice_files",
        "Start a local slicing job for STL/3MF/STEP files or directories. "
        "Returns a task ID immediately; use job_status to poll. "
        "Paths must be under the MCP allowed roots.",
        {
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 50,
                },
                "output_dir": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["workbench", "batch"],
                },
                "recursive": {"type": "boolean", "default": False},
                "settings": {
                    "type": "object",
                    "description": "Optional partial PrintFarm settings object.",
                },
                "command_text": {
                    "type": "string",
                    "description": "Optional natural-language parameter command.",
                },
            },
            "required": ["paths"],
        },
    ),
    _tool(
        "job_status",
        "Read the current local slicing task, progress, logs, and output path.",
        {"properties": {}},
    ),
    _tool(
        "cancel_job",
        "Cancel the current local slicing task.",
        {"properties": {}},
    ),
    _tool(
        "open_output",
        "Open the current task output directory in Windows Explorer.",
        {"properties": {}},
    ),
]


TOOL_HANDLERS = {
    "assistant_status": lambda args: assistant_status(
        _bool(args.get("start_if_needed"), False)
    ),
    "find_assistant": lambda _args: {
        "assistant": str(find_assistant()),
        "version": _read_version(find_assistant()),
    },
    "lookup_parameter": lambda args: lookup_parameters(
        list(args.get("names") or [])
    ),
    "slice_files": lambda args: slice_files(
        list(args.get("paths") or []),
        output_dir=args.get("output_dir"),
        mode=args.get("mode"),
        recursive=_bool(args.get("recursive"), False),
        settings=args.get("settings"),
        command_text=_text(args.get("command_text")),
    ),
    "job_status": lambda _args: job_status(),
    "cancel_job": lambda _args: cancel_job(),
    "open_output": lambda _args: open_output(),
}


def _tool_result(data: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": _json_text(data)}],
        "structuredContent": data if isinstance(data, dict) else {"result": data},
        "isError": is_error,
    }


def _response(message_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(
    message_id: Any, code: int, message: str, data: Any = None
) -> dict[str, Any]:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": message_id, "error": error}


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    message_id = message.get("id")
    params = message.get("params") or {}
    if "id" not in message:
        return None
    if method == "initialize":
        requested = str(params.get("protocolVersion") or PROTOCOL_VERSION)
        return _response(message_id, {
            "protocolVersion": requested,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Use only the exposed PrintFarm Assistant tools. Slicing is local. "
                "Never ask for arbitrary shell commands, credentials, or paths "
                "outside configured model roots."
            ),
        })
    if method == "ping":
        return _response(message_id, {})
    if method == "tools/list":
        return _response(message_id, {"tools": TOOLS})
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return _error(message_id, -32602, f"Unknown tool: {name}")
        try:
            data = handler(arguments)
            return _response(message_id, _tool_result(data))
        except ToolError as exc:
            return _response(message_id, _tool_result(
                {"error": str(exc)}, is_error=True
            ))
        except Exception as exc:  # noqa: BLE001
            log(f"tool {name} failed: {exc!r}")
            return _response(message_id, _tool_result(
                {"error": f"Internal tool error: {exc}"}, is_error=True
            ))
    return _error(message_id, -32601, f"Method not found: {method}")


def serve_stdio() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    try:
        assistant = str(find_assistant())
    except ToolError:
        assistant = "not installed"
    log(f"ready; assistant={assistant}")
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            response = _error(None, -32700, "Parse error", str(exc))
        else:
            response = handle_request(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


def print_client_config() -> None:
    assistant = find_assistant()
    executable = Path(sys.executable if getattr(sys, "frozen", False) else __file__)
    command = executable if executable.suffix.lower() == ".exe" else Path(sys.executable)
    args = [] if command == executable else [str(executable)]
    print(_json_text({
        "mcpServers": {
            SERVER_NAME: {
                "command": str(command),
                "args": args + ["--stdio"],
                "env": {
                    "TUOZHU_ASSISTANT_EXE": str(assistant),
                },
            }
        }
    }))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdio", action="store_true", help="run MCP over stdio")
    parser.add_argument("--print-config", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    if args.version:
        print(SERVER_VERSION)
        return 0
    if args.print_config:
        print_client_config()
        return 0
    if args.doctor:
        try:
            status = assistant_status(False)
            print(_json_text({
                "server": SERVER_NAME,
                "version": SERVER_VERSION,
                "assistant": status,
                "dataDir": str(find_data_dir()),
                "allowedRoots": [str(path) for path in _allowed_roots()],
            }))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(_json_text({"ok": False, "error": str(exc)}))
            return 1
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
