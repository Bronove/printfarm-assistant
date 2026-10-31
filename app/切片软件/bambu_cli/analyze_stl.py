#!/usr/bin/env python3
"""Analyze a binary STL: triangle count, NaN/garbage detection, bounding box,
edge-length distribution, and build-plate fit check.

Usage:
    python analyze_stl.py <model.stl> [--plate-size 256]

Exits 0 on success. Prints a JSON-ish summary plus human-readable lines.
"""

import argparse
import json
import re
import struct

import numpy as np


def parse_vertices(path):
    """Structured parse of an ASCII or binary STL.

    Binary STL is read per triangle (skip the normal and attribute bytes).
    ASCII STL is accepted as well: Bambu Studio can slice it, so rejecting it
    during preflight would make valid user files look like corrupt models.
    """
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) < 84:
        raise ValueError('file too small to be a binary STL')

    if data.lstrip().lower().startswith(b'solid'):
        vertex_rows = re.findall(
            rb'^\s*vertex\s+'
            rb'([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)',
            data,
            re.MULTILINE,
        )
        if vertex_rows and len(vertex_rows) % 3 == 0:
            try:
                values = [
                    float(value)
                    for row in vertex_rows
                    for value in row
                ]
            except ValueError as exc:
                raise ValueError('invalid numeric value in ASCII STL') from exc
            verts = np.asarray(values, dtype=np.float32).reshape(-1, 3, 3)
            return len(verts), verts

    n = struct.unpack_from('<I', data, 80)[0]
    if len(data) != 84 + n * 50:
        raise ValueError(
            f'not a valid binary STL: size mismatch (header count={n}, '
            f'file={len(data)} bytes)'
        )
    verts = np.empty((n, 3, 3), dtype=np.float32)
    for i in range(n):
        base = 84 + i * 50 + 12
        for k in range(3):
            verts[i, k] = np.frombuffer(
                data, dtype='<f4', count=3, offset=base + k * 12
            )
    return n, verts


def analyze(path, plate_size=256.0):
    n, verts = parse_vertices(path)
    v0, v1, v2 = verts[:, 0], verts[:, 1], verts[:, 2]
    e = np.maximum(
        np.maximum(
            np.linalg.norm(v1 - v0, axis=1),
            np.linalg.norm(v2 - v0, axis=1),
        ),
        np.linalg.norm(v2 - v1, axis=1),
    )
    V = verts.reshape(-1, 3)
    mn = V.min(axis=0)
    mx = V.max(axis=0)
    size = mx - mn
    p50, p95, p99 = np.percentile(e, [50, 95, 99])
    nan_tris = int(np.isnan(verts).any(axis=(1, 2)).sum())
    # Garbage spike heuristic: NaN triangles plus triangles with a very long
    # edge relative to the mesh resolution (SolidWorks exports often contain
    # spike triangles reaching +/-3.4e38 or +/-(1e4..1e6)).
    spike_thr = max(50.0, 5.0 * float(p50))
    spike_tris = int((e > spike_thr).sum())
    fits = bool((size <= plate_size).all())
    return {
        'triangles': n,
        'finite': bool(np.isfinite(V).all()),
        'nan_triangles': nan_tris,
        'spike_triangles_estimate': spike_tris,
        'min': [float(x) for x in mn],
        'max': [float(x) for x in mx],
        'size_mm': [round(float(x), 3) for x in size],
        'max_edge_p50_p95_p99_mm': [round(float(x), 3) for x in (p50, p95, p99)],
        'fits_plate': fits,
        'plate_size_mm': plate_size,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('model')
    ap.add_argument('--plate-size', type=float, default=256.0)
    args = ap.parse_args()
    result = analyze(args.model, args.plate_size)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('triangles:', result['triangles'])
    print('all finite:', result['finite'])
    print('NaN triangles:', result['nan_triangles'])
    print('spike triangles (estimate):', result['spike_triangles_estimate'])
    print('bbox min:', result['min'])
    print('bbox max:', result['max'])
    print('size (mm):', result['size_mm'])
    print('max edge p50/p95/p99 (mm):', result['max_edge_p50_p95_p99_mm'])
    print('fits plate:', result['fits_plate'])


if __name__ == '__main__':
    main()
