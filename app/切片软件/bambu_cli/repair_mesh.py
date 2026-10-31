# -*- coding: utf-8 -*-
"""破面 / 非流形面自动修复（trimesh，思路同拓竹 GUI 的一键修复）。

检测：水密性、非流形边、破洞（边界边）、退化面。
修复：法线、缠绕方向、翻转、补洞、去退化面。
"""

import os

import numpy as np
import trimesh
import trimesh.repair


def inspect_mesh(mesh):
    edges = np.sort(mesh.edges.reshape(-1, 2), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return {
        'triangles': int(len(mesh.faces)),
        'watertight': bool(mesh.is_watertight),
        'nonmanifold_edges': int((counts > 2).sum()),
        'boundary_edges': int((counts == 1).sum()),
        'degenerate_faces': int((mesh.area_faces < 1e-9).sum()),
    }


def inspect_stl(path):
    """读取 STL 并返回与 `inspect_mesh` 相同的拓扑检查结果。"""
    mesh = trimesh.load(path, force='mesh', process=True)
    return inspect_mesh(mesh)


def repair_mesh(path, out_path, max_bytes=None):
    """检测并修复 STL 破面。返回 (repaired: bool, report: dict)。

    默认不再按文件大小跳过。大体积手办同样可能是非流形网格，之前
    20 MB 的静默跳过会让破面模型直接进入切片，Bambu 只给一个不阻塞
    流程的警告。
    """
    report = {}
    if max_bytes is not None and os.path.getsize(path) > max_bytes:
        report['skipped'] = 'file too large'
        return False, report
    # process=True：先合并重复顶点、规整法线，再检测/修复
    mesh = trimesh.load(path, force='mesh', process=True)
    before = inspect_mesh(mesh)
    report['before'] = before
    has_problem = (not before['watertight']
                   or before['nonmanifold_edges'] > 0
                   or before['degenerate_faces'] > 0)
    if not has_problem:
        return False, report
    # 修复
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fix_winding(mesh)
    trimesh.repair.fix_inversion(mesh)
    try:
        trimesh.repair.fill_holes(mesh)
    except Exception:
        pass
    mask = mesh.area_faces > 1e-9
    if not mask.all():
        mesh.update_faces(mask)
    mesh.remove_unreferenced_vertices()
    after = inspect_mesh(mesh)
    report['after'] = after
    if after['nonmanifold_edges'] > 0:
        report['remaining_nonmanifold_edges'] = (
            after['nonmanifold_edges'])
    if after['triangles'] <= 0:
        return False, report
    improved = (
        (after['watertight'] and not before['watertight'])
        or after['boundary_edges'] < before['boundary_edges']
        or after['nonmanifold_edges'] < before['nonmanifold_edges']
        or after['degenerate_faces'] < before['degenerate_faces']
        or after['triangles'] != before['triangles'])
    if not improved:
        return False, report
    mesh.export(out_path, file_type='stl')
    report['repaired'] = True
    return True, report
