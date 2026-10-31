#!/usr/bin/env python3
"""Choose a scarf length from measured print-layer outer-wall loops.

Bambu exposes one scarf length per process/filament, not one length per
perimeter. We therefore sample several horizontal cross-sections of the
oriented model and use a robust upper-middle perimeter (P75) to pick a band.
"""

import math
import os


# Outer-loop perimeter in mm -> scarf length in mm.
# Small fingers/hair tips land in 5-6 mm; broad smooth surfaces land in 12-15.
SCARF_BANDS = (
    (45.0, 5.0),
    (75.0, 6.0),
    (120.0, 8.0),
    (180.0, 10.0),
    (260.0, 12.0),
    (float('inf'), 15.0),
)

_SAMPLE_LEVELS = (0.10, 0.20, 0.30, 0.40, 0.50,
                  0.60, 0.70, 0.80, 0.90)


def choose_scarf_length(loop_perimeter_mm):
    """Map a representative outer-loop perimeter to a scarf length."""
    try:
        perimeter = max(0.0, float(loop_perimeter_mm))
    except (TypeError, ValueError):
        return 10.0
    for upper, scarf in SCARF_BANDS:
        if perimeter <= upper:
            return float(scarf)
    return 15.0


def _percentile(values, q):
    """Linear-interpolated percentile without adding another dependency."""
    vals = sorted(float(v) for v in values)
    if not vals:
        return 0.0
    pos = (len(vals) - 1) * max(0.0, min(1.0, q))
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def _line_length(line):
    total = 0.0
    last = None
    for point in line:
        cur = (float(point[0]), float(point[1]), float(point[2]))
        if last is not None:
            total += math.dist(last, cur)
        last = cur
    return total


def _fallback_loop(mesh):
    """Estimate one horizontal perimeter from the XY bounding rectangle."""
    bounds = getattr(mesh, 'bounds', None)
    if bounds is None:
        return 0.0
    dx = max(0.0, float(bounds[1][0]) - float(bounds[0][0]))
    dy = max(0.0, float(bounds[1][1]) - float(bounds[0][1]))
    return 2.0 * (dx + dy)


def inspect_model(path):
    """Measure outer-wall loops after the model has been oriented for print.

    Returns a dict with the selected scarf length and the measurements used.
    The caller must treat ``ok=False`` as "keep the normal 10 mm fallback".
    """
    result = {
        'ok': False,
        'scarf_length_mm': 10.0,
        'loop_p50_mm': None,
        'loop_p75_mm': None,
        'loop_p90_mm': None,
        'sample_count': 0,
        'method': 'fallback',
        'band': '默认 10 mm',
    }
    if not path or not os.path.isfile(path):
        result['error'] = 'model not found'
        return result

    try:
        import numpy as np
        import trimesh

        mesh = trimesh.load(path, force='mesh', process=False)
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) < 4:
            result['error'] = 'no printable mesh'
            return result

        bounds = mesh.bounds
        z0, z1 = float(bounds[0][2]), float(bounds[1][2])
        if z1 - z0 < 0.2:
            result['error'] = 'model has no layer height'
            return result

        loops = []
        cx, cy = float(mesh.centroid[0]), float(mesh.centroid[1])
        normal = np.array((0.0, 0.0, 1.0))
        for level in _SAMPLE_LEVELS:
            z = z0 + (z1 - z0) * level
            section = mesh.section(
                plane_origin=(cx, cy, z), plane_normal=normal)
            if section is None:
                continue
            for line in section.discrete:
                length = _line_length(line)
                # Ignore numerical crumbs; keep real wall loops only.
                if 4.0 <= length <= 20000.0:
                    loops.append(length)

        if len(loops) < 3:
            fallback = _fallback_loop(mesh)
            if fallback >= 4.0:
                loops = [fallback] * 3
                method = 'bbox'
            else:
                result['error'] = 'no usable outer-wall loop'
                return result
        else:
            method = 'cross-section'

        p50 = _percentile(loops, 0.50)
        p75 = _percentile(loops, 0.75)
        p90 = _percentile(loops, 0.90)
        chosen = choose_scarf_length(p75)
        result.update({
            'ok': True,
            'scarf_length_mm': chosen,
            'loop_p50_mm': round(p50, 2),
            'loop_p75_mm': round(p75, 2),
            'loop_p90_mm': round(p90, 2),
            'sample_count': len(loops),
            'method': method,
            'band': '%.0f mm' % chosen,
        })
        return result
    except Exception as exc:  # noqa: BLE001
        result['error'] = str(exc)[:180]
        return result
