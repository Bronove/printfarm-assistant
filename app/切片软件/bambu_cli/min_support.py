# -*- coding: utf-8 -*-
"""Placeholder for the separately distributed minimum-support optimizer.

The public source tree can build the basic slicing workspace without this
feature. The official installer supplies the optimized component separately.
"""


def _unavailable(*_args, **_kwargs):
    raise RuntimeError("当前源码不含最少支撑优化组件")


load_mesh = _unavailable
place = _unavailable
candidates = _unavailable
estimate_support = _unavailable
stability = _unavailable
optimize = _unavailable
