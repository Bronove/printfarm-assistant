# -*- coding: utf-8 -*-
"""Standalone STEP/STP to binary STL converter.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 2 of the License, or (at your option) any later
version.

Gmsh is a separate GPL program/library invoked by this process. Keeping this
converter in a standalone executable isolates its GPL dependencies from the
PrintFarm Assistant desktop process.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from pathlib import Path


def _find_gmsh_dll() -> Path:
    configured = os.environ.get("GMSH_DLL", "").strip()
    program_dir = Path(sys.executable).resolve().parent
    candidates = [
        Path(configured) if configured else None,
        Path(__file__).resolve().parent / "gmsh-4.15.dll",
        program_dir / "gmsh-4.15.dll",
        Path(sys.prefix) / "Lib" / "gmsh-4.15.dll",
        Path(sys.prefix) / "bin" / "gmsh-4.15.dll",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise FileNotFoundError("gmsh-4.15.dll was not found")


class _GmshApi:
    def __init__(self) -> None:
        dll = ctypes.WinDLL(str(_find_gmsh_dll()))
        self._error = ctypes.c_int
        self.initialize = dll.gmshInitialize
        self.initialize.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.initialize.restype = None
        self.finalize = dll.gmshFinalize
        self.finalize.argtypes = [ctypes.POINTER(ctypes.c_int)]
        self.finalize.restype = None
        self.set_number = dll.gmshOptionSetNumber
        self.set_number.argtypes = [
            ctypes.c_char_p,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_int),
        ]
        self.set_number.restype = None
        self.open = dll.gmshOpen
        self.open.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
        self.open.restype = None
        self.occ_synchronize = dll.gmshModelOccSynchronize
        self.occ_synchronize.argtypes = [ctypes.POINTER(ctypes.c_int)]
        self.occ_synchronize.restype = None
        self.generate_mesh = dll.gmshModelMeshGenerate
        self.generate_mesh.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        self.generate_mesh.restype = None
        self.write = dll.gmshWrite
        self.write.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
        self.write.restype = None
        self.get_last_error = dll.gmshLoggerGetLastError
        self.get_last_error.argtypes = [
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_int),
        ]
        self.get_last_error.restype = None

    def check(self, code: int) -> None:
        if code == 0:
            return
        message = ctypes.c_char_p()
        api_code = ctypes.c_int()
        self.get_last_error(ctypes.byref(message), ctypes.byref(api_code))
        detail = ""
        if api_code.value == 0 and message.value:
            detail = message.value.decode("utf-8", errors="replace")
        raise RuntimeError(detail or f"Gmsh API error {code}")


def convert(src: str, dst: str, mesh_size: float) -> None:
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"STEP file not found: {src}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)

    gmsh = _GmshApi()
    code = ctypes.c_int()
    argv = ctypes.POINTER(ctypes.c_char_p)()
    gmsh.initialize(0, argv, 0, 0, ctypes.byref(code))
    gmsh.check(code.value)
    try:
        gmsh.set_number(b"General.Terminal", 0.0, ctypes.byref(code))
        gmsh.check(code.value)
        gmsh.set_number(b"Mesh.Binary", 1.0, ctypes.byref(code))
        gmsh.check(code.value)
        gmsh.set_number(
            b"Mesh.MeshSizeMax", float(mesh_size), ctypes.byref(code)
        )
        gmsh.check(code.value)
        gmsh.open(src.encode("utf-8"), ctypes.byref(code))
        gmsh.check(code.value)
        gmsh.occ_synchronize(ctypes.byref(code))
        gmsh.check(code.value)
        gmsh.generate_mesh(2, ctypes.byref(code))
        gmsh.check(code.value)
        gmsh.write(dst.encode("utf-8"), ctypes.byref(code))
        gmsh.check(code.value)
    finally:
        gmsh.finalize(ctypes.byref(code))

    if not os.path.isfile(dst) or os.path.getsize(dst) <= 0:
        raise RuntimeError("Gmsh did not create an STL file")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert STEP/STP to binary STL with Gmsh."
    )
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--mesh-size", type=float, default=2.0)
    args = parser.parse_args()
    try:
        convert(args.source, args.destination, args.mesh_size)
    except Exception as exc:  # noqa: BLE001
        print(f"STEP conversion failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
