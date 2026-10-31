# -*- coding: utf-8 -*-
"""独立选择目录，避免在 HTTP 服务线程里直接创建 Tk 控件。"""

import json
import os
import sys
import tkinter as tk
from tkinter import filedialog


def write_result(result_path, selected_path):
    """用 UTF-8 JSON 回传中文路径，不依赖子进程控制台编码。"""
    if not result_path:
        return
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump({"path": selected_path or ""}, handle, ensure_ascii=False)


def main():
    args = [arg for arg in sys.argv[1:] if arg != "--choose-output"]
    result_path = args[0] if args else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".choose-output.json"
    )
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askdirectory(title="选择切片输出目录", mustexist=True)
    root.destroy()
    write_result(result_path, path)


if __name__ == "__main__":
    main()
