"""Docked side panel (Windows): the mobile dashboard in a slim Microsoft Edge app window on the screen edge.

Docked mode registers the window as an "app bar" (like the taskbar), so the screen edge is reserved and
maximized windows don't cover it. A small watcher process stays alive while the panel is open and releases
the reserved space when you close it.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path

from workpulse.agent import control
from workpulse.config import Config

log = logging.getLogger("workpulse.panel")
TITLE = "WorkPulse"  # the mobile page's <title>; Edge app windows use it as the window title
ABM_NEW, ABM_REMOVE, ABM_QUERYPOS, ABM_SETPOS = 0, 1, 2, 3
ABE_LEFT, ABE_RIGHT = 0, 2
SPI_GETWORKAREA = 0x0030
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0010, 0x0040
HWND_TOP, HWND_TOPMOST = 0, -1
WM_CLOSE = 0x0010
SW_RESTORE = 9


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uCallbackMessage", wintypes.UINT),
                ("uEdge", wintypes.UINT), ("rc", RECT), ("lParam", wintypes.LPARAM)]


def panel_rect(work: tuple[int, int, int, int], width: int, side: str) -> tuple[int, int, int, int]:
    """(left, top, right, bottom) of a panel `width` px wide on the `side` of the work area. Pure; tested."""
    left, top, right, bottom = work
    width = max(1, min(width, right - left))
    return (right - width, top, right, bottom) if side == "right" else (left, top, left + width, bottom)


def find_edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return None


def _state_file(cfg: Config) -> Path:
    return cfg.data_dir / "panel.json"


# ---- Win32 helpers ------------------------------------------------------------------------------

def _win():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32")
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
    shell32.SHAppBarMessage.restype = ctypes.c_size_t
    return user32, shell32


def _dpi_aware() -> int:
    """Make coordinates physical pixels and return the display scale in DPI (96 = 100%)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
    try:
        return int(ctypes.windll.user32.GetDpiForSystem())
    except (AttributeError, OSError):
        return 96


def _app_windows(user32) -> set[int]:
    found: set[int] = set()
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == TITLE:
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value.startswith("Chrome_WidgetWin"):
                found.add(int(hwnd))
        return True

    user32.EnumWindows(proc(cb), 0)
    return found


def _wait_for_dashboard(cfg: Config, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{cfg.server.url}/api/ping", timeout=2):
                return True
        except OSError:
            if not control.running_pid(cfg, "server"):
                control.start_background(cfg, "server")
            time.sleep(1)
    return False


def _work_area(user32) -> tuple[int, int, int, int]:
    work = RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
    return work.left, work.top, work.right, work.bottom


def _dock(shell32, abd: APPBARDATA, rect: tuple[int, int, int, int], width: int, side: str) -> tuple[int, int, int, int]:
    """Register as an app bar on the screen edge (reserving it) and return the rectangle the shell gave us."""
    shell32.SHAppBarMessage(ABM_NEW, ctypes.byref(abd))
    abd.rc = RECT(*rect)
    shell32.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(abd))
    if side == "right":  # keep our width after the shell adjusts the edge
        abd.rc.left = abd.rc.right - width
    else:
        abd.rc.right = abd.rc.left + width
    shell32.SHAppBarMessage(ABM_SETPOS, ctypes.byref(abd))
    return abd.rc.left, abd.rc.top, abd.rc.right, abd.rc.bottom


# ---- open / close -------------------------------------------------------------------------------

def focus_or_close_existing(cfg: Config, close: bool = False) -> bool:
    """If a panel is open: bring it forward (or close it). Returns True if one was open."""
    if sys.platform != "win32":
        return False
    try:
        hwnd = json.loads(_state_file(cfg).read_text(encoding="utf-8"))["hwnd"]
    except (FileNotFoundError, ValueError, KeyError):
        return False
    user32, _ = _win()
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if close:
        user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)  # the watcher notices and releases the reserved edge
    else:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
    return True


def run_watcher(cfg: Config) -> None:
    """Open the panel window, dock it, and keep it docked until it's closed (runs as `workpulse panel --watch`)."""
    if sys.platform != "win32":
        raise SystemExit("The docked panel is Windows-only. On other systems open http://127.0.0.1:8787/m/ in a narrow window.")
    if (pid := control.running_pid(cfg, "panel")) and pid != os.getpid():
        focus_or_close_existing(cfg)
        return
    control.write_pid(cfg, "panel")
    st = cfg.startup
    user32, shell32 = _win()
    dpi = _dpi_aware()
    abd = None
    try:
        edge = find_edge()
        if not edge:
            raise RuntimeError("Microsoft Edge not found (the panel uses Edge's app window).")
        if not _wait_for_dashboard(cfg):
            raise RuntimeError("the dashboard didn't start; see .\\workpulse logs server")
        width = int(st.panel_width * dpi / 96)
        left, top, right, bottom = panel_rect(_work_area(user32), width, st.panel_side)

        before = _app_windows(user32)
        subprocess.Popen([edge, f"--app={cfg.server.url}/m/#view=home", f"--window-size={st.panel_width},{max(400, int((bottom - top) * 96 / dpi))}"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        hwnd = None
        deadline = time.time() + 30
        while time.time() < deadline and not hwnd:
            new = _app_windows(user32) - before
            hwnd = next(iter(new), None)
            time.sleep(0.3)
        if not hwnd:
            raise RuntimeError("the panel window didn't appear")
        _state_file(cfg).write_text(json.dumps({"hwnd": hwnd}), encoding="utf-8")

        abd = APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA), hWnd=hwnd,
                         uCallbackMessage=user32.RegisterWindowMessageW("WorkPulsePanelAppBar"),
                         uEdge=ABE_RIGHT if st.panel_side == "right" else ABE_LEFT)
        target = (left, top, right, bottom)
        docked = False
        if st.panel_dock:
            target, docked = _dock(shell32, abd, target, width, st.panel_side), True
        insert_after = HWND_TOPMOST if st.panel_dock else HWND_TOP
        log.info("panel open: %dx%d at (%d,%d), %s, dpi %d", target[2] - target[0], target[3] - target[1], target[0], target[1],
                 "docked" if st.panel_dock else "floating", dpi)
        opened = time.time()
        while user32.IsWindow(hwnd):
            settling = time.time() - opened < 8  # Edge sizes its window as the page loads; hold our position meanwhile
            if st.panel_dock and user32.IsIconic(hwnd):
                if docked:  # minimized: give the screen edge back until it's restored
                    shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(abd))
                    docked = False
            else:
                if st.panel_dock and not docked:
                    target, docked = _dock(shell32, abd, panel_rect(_work_area(user32), width, st.panel_side), width, st.panel_side), True
                    settling = True
                rc = RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rc))
                if settling or (st.panel_dock and (rc.left, rc.top, rc.right, rc.bottom) != target):
                    l, t, r, b = target
                    user32.SetWindowPos(hwnd, insert_after, l, t, r - l, b - t, SWP_NOACTIVATE | SWP_SHOWWINDOW)
            time.sleep(0.5 if settling else 1.5)
        log.info("panel closed")
        if not docked:
            abd = None  # nothing reserved to give back
    finally:
        if abd is not None:
            shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(abd))  # give the screen edge back
        _state_file(cfg).unlink(missing_ok=True)
        control.clear_pid(cfg, "panel")
