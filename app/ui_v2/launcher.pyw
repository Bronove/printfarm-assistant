# -*- coding: utf-8 -*-
"""打印农场助手桌面启动器。"""

import ctypes
import faulthandler
import os
import sys
import threading
import time
import tempfile
import traceback
import urllib.request

ROOT = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False)
                                      else __file__))
BUNDLE = getattr(sys, "_MEIPASS", ROOT)
if BUNDLE not in sys.path:
    sys.path.insert(0, BUNDLE)


def _read_version():
    for directory in (ROOT, BUNDLE):
        try:
            with open(os.path.join(directory, "version.txt"),
                      encoding="utf-8-sig") as handle:
                value = handle.read().strip()
            if value:
                return value
        except OSError:
            pass
    return "1.6.0-beta.1"


VERSION = _read_version()

STARTUP_LOG = os.path.join(tempfile.gettempdir(), "tuozhu_v2_startup.log")
try:
    _faulthandler_stream = open(STARTUP_LOG, "a", encoding="utf-8")
    faulthandler.dump_traceback_later(
        25, repeat=False, file=_faulthandler_stream
    )
except OSError:
    _faulthandler_stream = None


def _startup(message):
    try:
        with open(STARTUP_LOG, "a", encoding="utf-8") as handle:
            handle.write("%s %s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), message
            ))
    except OSError:
        pass


_startup("launcher start")
try:
    import server  # noqa: E402
except Exception:
    _startup("server import failed\n" + traceback.format_exc())
    raise
_startup("server imported")
if _faulthandler_stream is not None:
    faulthandler.cancel_dump_traceback_later()

if "--choose-output" in sys.argv:
    import native_dialog
    native_dialog.main()
    raise SystemExit(0)
if "--slice-job" in sys.argv:
    server.CORE.module.run_slice_job()
    raise SystemExit(0)


def _app_id():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "PrintFarm.Assistant"
        )
    except Exception:
        pass


def _activate_existing_instance():
    """Return True when another desktop instance already owns the app."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    global _single_instance_handle
    _single_instance_handle = kernel32.CreateMutexW(
        None, False, "Local\\PrintFarmAssistant.Singleton"
    )
    if not _single_instance_handle:
        return False
    if ctypes.get_last_error() != 183:
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    window = user32.FindWindowW(None, "打印农场助手 " + VERSION)
    if window:
        user32.ShowWindow(window, 9)
        user32.SetForegroundWindow(window)
    return True


def _wait_ready(timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:4180/api/health", timeout=1
            ) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def main():
    _startup("main enter")
    _app_id()
    if _activate_existing_instance():
        _startup("existing instance activated")
        return
    if not _wait_ready(0.3):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 4180), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        _startup("http server started")
    else:
        httpd = None
    if not _wait_ready():
        raise RuntimeError("本地服务启动超时")
    _startup("http ready")

    try:
        import webview
        _startup("webview imported")
        icon = os.path.join(BUNDLE, "icon.ico")
        webview.create_window(
            "打印农场助手 " + VERSION,
            "http://127.0.0.1:4180/",
            width=1240,
            height=820,
            min_size=(780, 660),
            background_color="#F3F6F4",
        )
        webview.start(debug=False, gui="edgechromium", icon=icon)
        _startup("webview stopped")
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _startup("fatal\n" + traceback.format_exc())
        raise
