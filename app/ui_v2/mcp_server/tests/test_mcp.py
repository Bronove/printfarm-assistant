# -*- coding: utf-8 -*-
"""Fast, dependency-free tests for the local MCP server."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "tuozhu_mcp.py"
spec = importlib.util.spec_from_file_location("tuozhu_mcp", SERVER)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def test_protocol_handshake():
    env = os.environ.copy()
    env["TUOZHU_ASSISTANT_EXE"] = sys.executable
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ]
    process = subprocess.run(
        [sys.executable, str(SERVER), "--stdio"],
        input="\n".join(json.dumps(item) for item in messages) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=15,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    assert_true(process.returncode == 0, process.stderr)
    responses = [
        json.loads(line) for line in process.stdout.splitlines() if line.strip()
    ]
    assert_true(len(responses) == 3, repr(responses))
    assert_true(
        responses[0]["result"]["serverInfo"]["name"] == "tuozhu-assistant",
        repr(responses[0]),
    )
    tool_names = {item["name"] for item in responses[1]["result"]["tools"]}
    assert_true(
        {"assistant_status", "slice_files", "job_status", "lookup_parameter"}
        <= tool_names,
        repr(tool_names),
    )
    assert_true(responses[2]["result"] == {}, repr(responses[2]))


def test_parameter_lookup():
    result = module.lookup_parameters(["层高"])
    assert_true(result and result[0]["found"], repr(result))
    assert_true(
        result[0]["matches"][0]["key"] == "layer_height",
        repr(result),
    )


def test_path_allowlist():
    with tempfile.TemporaryDirectory(prefix="tuozhu-mcp-test-") as work:
        allowed = Path(work)
        model = allowed / "model.stl"
        model.write_text("solid test\nendsolid test\n", encoding="ascii")
        outside = Path(tempfile.gettempdir()) / "outside-model.stl"
        outside.write_text("solid test\nendsolid test\n", encoding="ascii")
        previous = os.environ.get("TUOZHU_MCP_ALLOWED_ROOTS")
        os.environ["TUOZHU_MCP_ALLOWED_ROOTS"] = str(allowed)
        try:
            selected = module._collect_models([str(allowed)], True)
            assert_true(selected == [model.resolve()], repr(selected))
            try:
                module._collect_models([str(outside)])
            except module.ToolError:
                pass
            else:
                raise AssertionError("outside path was accepted")
        finally:
            if previous is None:
                os.environ.pop("TUOZHU_MCP_ALLOWED_ROOTS", None)
            else:
                os.environ["TUOZHU_MCP_ALLOWED_ROOTS"] = previous
            outside.unlink(missing_ok=True)


def test_settings_validation():
    settings = module._normalise_settings(
        {
            "layerHeight": "0.2",
            "infill": 30,
            "pattern": "gyroid",
            "hideSeam": True,
            "parameterPolicy": {
                "mode": "file",
                "overrides": {},
            },
        },
        {"machine": "Bambu Lab H2S 0.4 nozzle"},
    )
    assert_true(settings["printer"] == "Bambu Lab H2S", repr(settings))
    assert_true(settings["layerHeight"] == "0.2", repr(settings))
    assert_true(settings["infill"] == "30", repr(settings))
    assert_true(settings["hideSeam"] is True, repr(settings))
    assert_true(settings["parameterPolicy"]["mode"] == "file", repr(settings))


def main():
    test_protocol_handshake()
    test_parameter_lookup()
    test_path_allowlist()
    test_settings_validation()
    print("MCP server tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
