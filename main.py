# -*- coding: utf-8 -*-
"""main.py — 程序入口：启动 tkinter 主窗口。"""

import ctypes
import sys
import tkinter as tk

from ui import App


def enable_dpi_awareness():
    """在 Windows 上启用 DPI 感知，避免高分屏下界面模糊。"""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    app = App(root)
    # 拦截窗口关闭事件，处理未保存提示与线程池清理
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
