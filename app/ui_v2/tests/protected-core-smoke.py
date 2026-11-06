# -*- coding: utf-8 -*-
"""Offline protocol and integrity smoke test for the protected core."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = "printfarm-multicolor/1"
VERSION = "1.0.0"


def command_for(core: Path) -> list[str]:
    if core.suffix.lower() == ".py":
        return [sys.executable, str(core)]
    return [str(core)]


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(("  OK   " if condition else "  FAIL ") + label
          + (": " + detail if detail and not condition else ""))
    return bool(condition)


def main() -> int:
    configured = os.environ.get("PRINTFARM_PROTECTED_CORE", "").strip()
    candidates = [
        Path(configured) if configured else None,
        ROOT / "protected_core.exe",
        ROOT / "protected_core.py",
    ]
    core = next(
        (path for path in candidates if path and path.is_file()),
        None,
    )
    if core is None:
        print("找不到 protected_core.exe 或 protected_core.py")
        return 1
    command = command_for(core)
    passed = []

    version_result = run([*command, "version"])
    version_payload = {}
    if version_result.returncode == 0:
        for line in version_result.stdout.splitlines():
            if line.startswith("CORE|version|"):
                version_payload = json.loads(line.split("|", 2)[2])
                break
    passed.append(check(
        "受保护组件版本协议",
        version_result.returncode == 0
        and version_payload.get("protocol") == PROTOCOL
        and version_payload.get("version") == VERSION,
        repr((
            version_result.returncode,
            version_result.stdout,
            version_result.stderr,
        )),
    ))

    with tempfile.TemporaryDirectory(prefix="printfarm_core_protocol_") as work:
        request = Path(work) / "validate.json"
        request.write_text(
            json.dumps({
                "protocol": PROTOCOL,
                "core_version": VERSION,
                "payload": {
                    "validation_required": False,
                    "validation_plates": [],
                    "file": "probe.3mf",
                },
            }),
            encoding="utf-8",
        )
        validate_result = run([*command, "validate", str(request)])
        validate_payload = {}
        for line in validate_result.stdout.splitlines():
            if line.startswith("PLAN|validate_done|"):
                validate_payload = json.loads(line.split("|", 2)[2])
                break
        passed.append(check(
            "受保护组件检修协议",
            validate_result.returncode == 0
            and validate_payload.get("core_protocol") == PROTOCOL
            and validate_payload.get("core_version") == VERSION,
            repr((
                validate_result.returncode,
                validate_result.stdout,
                validate_result.stderr,
            )),
        ))

        invalid = Path(work) / "invalid.json"
        invalid.write_text(
            json.dumps({
                "protocol": "printfarm-multicolor/0",
                "payload": {},
            }),
            encoding="utf-8",
        )
        invalid_result = run([*command, "validate", str(invalid)])
        passed.append(check(
            "旧协议被拒绝",
            invalid_result.returncode != 0
            and "PLAN|error|" in invalid_result.stdout,
            repr((invalid_result.stdout, invalid_result.stderr)),
        ))

    if all(passed):
        print("受保护组件冒烟测试：全部通过")
        return 0
    print("受保护组件冒烟测试：失败")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
