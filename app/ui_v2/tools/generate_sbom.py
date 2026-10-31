# -*- coding: utf-8 -*-
"""Generate a small SPDX JSON inventory for a packaged desktop build."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _metadata_fields(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return fields
    for line in lines:
        if not line.strip():
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields.setdefault(key.strip().lower(), value.strip())
    return fields


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _spdx_id(name: str, version: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9.-]+", "-", f"{name}-{version}").strip("-")
    return "SPDXRef-Package-" + (clean or "unknown")


def generate(app_dir: Path, output: Path, product_version: str) -> None:
    internal = app_dir / "_internal"
    packages = []
    seen = set()
    for metadata in sorted(internal.glob("*.dist-info/METADATA")):
        fields = _metadata_fields(metadata)
        name = fields.get("name", "")
        version = fields.get("version", "")
        if not name or not version or (name, version) in seen:
            continue
        seen.add((name, version))
        packages.append({
            "SPDXID": _spdx_id(name, version),
            "name": name,
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": fields.get("license", "NOASSERTION"),
            "licenseDeclared": fields.get("license", "NOASSERTION"),
            "copyrightText": "NOASSERTION",
        })

    fixed = [
        ("CPython", "3.12.7", "PSF-2.0"),
        ("PyInstaller", "6.21.0", "GPL-2.0-or-later WITH Bootloader-exception"),
        ("Gmsh", "4.15.2", "GPL-2.0-or-later"),
        ("MiSans", "1.5", "MiSans-Font-License"),
        ("Microsoft Edge WebView2 Runtime", "system", "Microsoft-Software-License"),
    ]
    for name, version, license_name in fixed:
        key = (name, version)
        if key in seen:
            continue
        seen.add(key)
        packages.append({
            "SPDXID": _spdx_id(name, version),
            "name": name,
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": license_name,
            "licenseDeclared": license_name,
            "copyrightText": "NOASSERTION",
        })

    app_exe = app_dir / "PrintFarmAssistant.exe"
    converter_exe = app_dir / "step_converter.exe"
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"PrintFarmAssistant-{product_version}",
        "documentNamespace": (
            "https://github.com/Bronove/tuozhu-assistant/sbom/"
            + product_version
        ),
        "creationInfo": {
            "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "creators": ["Tool: printfarm-generate-sbom"],
        },
        "packages": packages,
        "files": [
            {
                "SPDXID": "SPDXRef-File-PrintFarmAssistant",
                "fileName": app_exe.name,
                "checksums": [{
                    "algorithm": "SHA256",
                    "checksumValue": _sha256(app_exe),
                }],
            },
            {
                "SPDXID": "SPDXRef-File-StepConverter",
                "fileName": converter_exe.name,
                "checksums": [{
                    "algorithm": "SHA256",
                    "checksumValue": _sha256(converter_exe),
                }],
            },
        ],
        "relationships": [{
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": package["SPDXID"],
        } for package in packages],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    generate(args.app_dir.resolve(), args.output.resolve(), args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
