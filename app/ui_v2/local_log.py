# -*- coding: utf-8 -*-
"""拓竹助手本地日志。"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _data_root():
    configured = os.environ.get("PRINTFARM_DATA_DIR")
    if configured:
        return Path(configured).resolve()
    if getattr(sys, "frozen", False):
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home()))
            / "PrintFarmAssistant"
        )
    return Path(__file__).resolve().parent


LOG_DIR = _data_root() / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "拓竹助手.log"

_logger = logging.getLogger("tuozhu.local")
_logger.setLevel(logging.INFO)
_logger.propagate = False
if not _logger.handlers:
    handler = RotatingFileHandler(
        LOG_PATH,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _logger.addHandler(handler)

_lock = threading.Lock()


def log_event(category, message, data=None, level="INFO"):
    payload = ""
    if data is not None:
        try:
            payload = " | " + json.dumps(
                data, ensure_ascii=False, default=str, separators=(",", ":")
            )
        except Exception:
            payload = " | " + repr(data)
    line = "[%s] %s%s" % (category, message, payload)
    with _lock:
        getattr(_logger, str(level).lower(), _logger.info)(line)


def log_exception(category, message):
    with _lock:
        _logger.exception("[%s] %s", category, message)


def tail(lines=200):
    limit = max(1, min(int(lines), 500))
    if not LOG_PATH.is_file():
        return ""
    try:
        content = LOG_PATH.read_text(encoding="utf-8", errors="replace")
        return "\n".join(content.splitlines()[-limit:])
    except OSError:
        return ""
