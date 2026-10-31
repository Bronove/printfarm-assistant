#!/usr/bin/env python3
"""Clean a broken/oversized STL so Bambu Studio CLI can slice it.

Removes garbage spike triangles (NaN / huge coordinates / very long edges),
keeps the largest connected component, centers it on the plate (Z snapped to
0), and optionally scales it to fit. Writes a validated binary STL.

Usage:
    python clean_stl.py <input.stl> <output.stl> [--max-size 230]
                        [--plate-size 256] [--radius-max 600] [--edge-max 500]
                        [--allow-scale]

Exits 0 and prints stats only if the written file passes a structured
read-back (finite, within plate bounds).
"""

import argparse
import json
import os
import struct

import numpy as np


def _largest_component(Tk, quant=1.0):
    ntri = Tk.shape[0]
    V = Tk.reshape(-1, 3)
    q = np.round(V / quant).astype(np.int64)
    uv = np.ascontiguousarray(q).view(
        np.dtype([('x', 'i8'), ('y', 'i8'), ('z', 'i8')])
    ).reshape(-1)
    _, inv = np.unique(uv, return_inverse=True)
    parent = np.arange(ntri, dtype=np.int32)
    rank = np.zeros(ntri, dtype=np.int8)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    corners = np.arange(ntri * 3) // 3
    order = np.argsort(inv, kind='stable')
    tbv = corners[order]
    invs = inv[order]
    ch = np.empty(len(invs), dtype=bool)
    ch[0] = True
    np.not_equal(invs[1:], invs[:-1], out=ch[1:])
    st = np.nonzero(ch)[0]
    en = np.append(st[1:], len(invs))
    for s, e0 in zip(st, en):
        grp = tbv[s:e0]
        if len(grp) > 1:
            b = grp[0]
            for t in grp[1:]:
                union(b, t)
    for i in range(ntri):
        find(i)
    up, counts = np.unique(parent, return_counts=True)
    top = up[int(np.argmax(counts))]
    return Tk[parent == top].copy(), int(counts.max())


def clean_and_fit(
    src,
    dst,
    max_size=230.0,
    plate_size=256.0,
    radius_max=600.0,
    edge_max=500.0,
    allow_scale=False,
):
    """Return stats dict. Raises on invalid output."""
    # Structured parse: vertices per triangle, skipping the 3-float normal and
    # the 2-byte attribute. A flat float read mixes normals/attributes into the
    # vertex data and produces garbage meshes.
    with open(src, 'rb') as f:
        data = f.read()
    n = struct.unpack_from('<I', data, 80)[0]
    if len(data) != 84 + n * 50:
        raise ValueError('not a valid binary STL: size mismatch')
    verts = np.empty((n, 3, 3), dtype=np.float32)
    for i in range(n):
        base = 84 + i * 50 + 12
        for k in range(3):
            verts[i, k] = np.frombuffer(
                data, dtype='<f4', count=3, offset=base + k * 12
            )
    T = verts.reshape(-1, 9)

    ok = np.isfinite(T).all(axis=1)
    v0 = T[:, 0:3]
    v1 = T[:, 3:6]
    v2 = T[:, 6:9]
    e = np.maximum(
        np.maximum(
            np.linalg.norm(v1 - v0, axis=1),
            np.linalg.norm(v2 - v0, axis=1),
        ),
        np.linalg.norm(v2 - v1, axis=1),
    )
    keep = ok & (np.abs(T) <= radius_max).all(axis=1) & (e <= edge_max)
    Tmain, comp_size = _largest_component(T[keep])

    mn = Tmain.reshape(-1, 3).min(axis=0)
    mx = Tmain.reshape(-1, 3).max(axis=0)
    size = mx - mn
    # 默认绝不改模型尺寸。只有调用方明确允许时才缩小到 max_size。
    # 旧版无提示地缩放，用户拿到的 3MF 已经不是原模型，属于数据事故。
    if allow_scale:
        scale = min(1.0, max_size / float(size.max()))
    else:
        scale = 1.0
        if float(size.max()) > float(plate_size) + 0.001:
            raise ValueError(
                '模型尺寸 %.2f×%.2f×%.2f mm 超过打印板 %.2f mm；'
                '程序不会自动缩放，请换更大机型或手动调整模型。'
                % (size[0], size[1], size[2], plate_size))
    Tsc = (Tmain.astype(np.float64) * scale).astype(np.float32)
    smn = Tsc.reshape(-1, 3).min(axis=0)
    smx = Tsc.reshape(-1, 3).max(axis=0)
    tx = plate_size / 2.0 - (smn[0] + smx[0]) / 2.0
    ty = plate_size / 2.0 - (smn[1] + smx[1]) / 2.0
    tz = 0.0 - smn[2]
    trans = np.array([tx, ty, tz] * 3, dtype=np.float32)
    Tsc = Tsc + trans

    v0 = Tsc[:, 0:3].copy()
    v1 = Tsc[:, 3:6].copy()
    v2 = Tsc[:, 6:9].copy()
    normals = np.cross(v1 - v0, v2 - v0)
    ln = np.linalg.norm(normals, axis=1)
    ln[ln == 0] = 1
    normals /= ln[:, None]

    out_n = Tsc.shape[0]
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    header = b'cleaned by bambu-studio-slice' + b'\x00' * (80 - 29)
    assert len(header) == 80
    with open(dst, 'wb') as f:
        f.write(header)
        f.write(struct.pack('<I', out_n))
        for i in range(out_n):
            f.write(struct.pack('<3f', *normals[i]))
            for k in range(3):
                f.write(struct.pack('<3f', *Tsc[i, k * 3:k * 3 + 3]))
            f.write(struct.pack('<H', 0))

    # Structured read-back verification (skip normals/attrs).
    with open(dst, 'rb') as f:
        data2 = f.read()
    n2 = struct.unpack_from('<I', data2, 80)[0]
    assert n2 == out_n and len(data2) == 84 + n2 * 50
    V2 = np.empty((n2, 3, 3), dtype=np.float32)
    for i in range(n2):
        base = 84 + i * 50 + 12
        for k in range(3):
            V2[i, k] = np.frombuffer(data2, dtype='<f4', count=3, offset=base + k * 12)
    V2f = V2.reshape(-1, 3)
    assert bool(np.isfinite(V2f).all()), 'cleaned STL contains non-finite values'
    fmin = V2f.min(axis=0)
    fmax = V2f.max(axis=0)
    assert bool((fmin >= -0.001).all()) and bool((fmax <= plate_size + 0.001).all()), (
        'cleaned STL outside plate bounds'
    )

    return {
        'input_triangles': int(n),
        'output_triangles': int(out_n),
        'main_component_triangles': int(comp_size),
        'scale': float(scale),
        'original_size_mm': [round(float(x), 3) for x in size],
        'final_min': [round(float(x), 3) for x in fmin],
        'final_max': [round(float(x), 3) for x in fmax],
        'final_size_mm': [round(float(x), 3) for x in (fmax - fmin)],
        'output': dst,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--max-size', type=float, default=230.0)
    ap.add_argument('--plate-size', type=float, default=256.0)
    ap.add_argument('--radius-max', type=float, default=600.0)
    ap.add_argument('--edge-max', type=float, default=500.0)
    ap.add_argument('--allow-scale', action='store_true')
    args = ap.parse_args()
    stats = clean_and_fit(
        args.input,
        args.output,
        max_size=args.max_size,
        plate_size=args.plate_size,
        radius_max=args.radius_max,
        edge_max=args.edge_max,
        allow_scale=args.allow_scale,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
