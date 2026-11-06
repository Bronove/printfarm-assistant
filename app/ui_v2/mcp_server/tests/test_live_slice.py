# -*- coding: utf-8 -*-
"""Live integration test. Requires the local PrintFarm Assistant server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT.parent
SERVER = ROOT / "mcp_server" / "tuozhu_mcp.py"
MODEL = PROJECT / "test_files" / "v217_yaw_alignment" / "case1_m.3mf"


class Client:
    def __init__(self):
        env = os.environ.copy()
        env["TUOZHU_ASSISTANT_EXE"] = str(
            ROOT / "dist_v2" / "PrintFarmAssistant" / "PrintFarmAssistant.exe"
        )
        env["TUOZHU_MCP_ALLOWED_ROOTS"] = str(PROJECT)
        packaged = os.environ.get("TUOZHU_MCP_EXE")
        command = (
            [packaged, "--stdio"]
            if packaged
            else [sys.executable, str(SERVER), "--stdio"]
        )
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        self.next_id = 1

    def request(self, method, params=None):
        message_id = self.next_id
        self.next_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": method,
            "params": params or {},
        }
        self.process.stdin.write(
            json.dumps(message, ensure_ascii=False) + "\n"
        )
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(self.process.stderr.read())
        result = json.loads(line)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]

    def call(self, name, arguments=None):
        result = self.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        if result.get("isError"):
            raise RuntimeError(result["content"][0]["text"])
        return result.get("structuredContent") or {}

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        self.process.wait(timeout=5)
        if self.process.returncode != 0:
            raise RuntimeError(self.process.stderr.read())


def main():
    if not MODEL.is_file():
        raise SystemExit(f"Test model not found: {MODEL}")
    client = Client()
    try:
        initialized = client.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "live-test", "version": "1"},
            },
        )
        assert initialized["serverInfo"]["name"] == "tuozhu-assistant"
        tools = client.request("tools/list")["tools"]
        assert {tool["name"] for tool in tools} >= {
            "assistant_status",
            "lookup_parameter",
            "slice_files",
            "job_status",
        }
        status = client.call("assistant_status")
        assert status["running"] is True, status
        lookup_payload = client.call("lookup_parameter", {"names": ["层高"]})
        lookup = lookup_payload.get("result", lookup_payload)
        assert lookup[0]["found"] is True, lookup

        with tempfile.TemporaryDirectory(
            prefix="tuozhu_mcp_live_", dir=PROJECT
        ) as output:
            result = client.call(
                "slice_files",
                {
                    "paths": [str(MODEL)],
                    "output_dir": output,
                    "settings": {
                        "layerHeight": "0.16",
                        "infill": "35",
                        "pattern": "gyroid",
                        "hideSeam": True,
                        "parameterPolicy": {
                            "mode": "custom",
                            "overrides": {"layerHeight": True},
                        },
                    },
                },
            )
            assert result["taskId"], result
            deadline = time.time() + 180
            task = None
            while time.time() < deadline:
                state = client.call("job_status")
                task = state.get("task")
                if task and task.get("status") != "running":
                    break
                time.sleep(0.8)
            assert task and task["status"] == "done", task
            outputs = list(Path(output).glob("*.gcode.3mf"))
            assert outputs, "No sliced output"
            print(json.dumps({
                "taskId": result["taskId"],
                "output": str(outputs[0]),
                "size": outputs[0].stat().st_size,
            }, ensure_ascii=False))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
