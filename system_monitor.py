"""
系统监控 — psutil CPU/内存 + win32gui BGM 抓取
"""
import os
import psutil


def get_system_status():
    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    return {
        "cpu": cpu,
        "memory": mem.percent,
        "memory_total_gb": mem.total // (1024**3),
        "memory_used_gb": mem.used // (1024**3),
    }


def get_bgm_title():
    """扫描 CloudMusic / QQMusic 窗口标题"""
    try:
        import win32gui
        import win32process

        titles = []

        def _enum(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                proc_name = psutil.Process(pid).name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return
            if proc_name not in ("cloudmusic.exe", "qqmusic.exe"):
                return
            title = win32gui.GetWindowText(hwnd)
            if title and " - " in title:
                titles.append(title)

        win32gui.EnumWindows(_enum, None)
        return titles[0] if titles else ""
    except ImportError:
        return ""
    except Exception:
        return ""
