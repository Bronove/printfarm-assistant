# -*- coding: utf-8 -*-
"""把多个二进制 STL 按摆位平移后合并成一个二进制 STL（保留原法线）。"""

import struct


def _triangle_count(path):
    with open(path, 'rb') as f:
        f.seek(80)
        return struct.unpack('<I', f.read(4))[0]


def merge_stls(items, out_path):
    """items: [(stl_path, dx, dy, dz)]。法线置零（由 Bambu 自行计算）。
    逐三角形流式写出，避免大模型占满内存。"""
    total = sum(_triangle_count(p) for p, _, _, _ in items)
    with open(out_path, 'wb') as f:
        f.write(b'merged by bamboo-slice'.ljust(80, b'\x00'))
        f.write(struct.pack('<I', total))
        for path, dx, dy, dz in items:
            with open(path, 'rb') as sf:
                data = sf.read()
            n = struct.unpack_from('<I', data, 80)[0]
            for i in range(n):
                base = 84 + i * 50
                f.write(data[base:base + 12])  # 原法线
                for k in range(3):
                    x, y, z = struct.unpack_from('<3f', data, base + 12 + k * 12)
                    f.write(struct.pack('<3f', x + dx, y + dy, z + dz))
                f.write(b'\x00\x00')
    return out_path
