"""Windows implementation using plain Win32 calls via ctypes (no pywin32, no keyboard/mouse hooks).

GetLastInputInfo only returns a timestamp of the last input event — it cannot see keys or text.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

import psutil

from workpulse.agent.platforms.base import Platform

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL
kernel32.GetTickCount.restype = wintypes.DWORD
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenInputDesktop.restype = wintypes.HANDLE
user32.CloseDesktop.argtypes = [wintypes.HANDLE]

DESKTOP_SWITCHDESKTOP = 0x0100
# Apps that host other apps' windows; the title is a better "app name" for these.
HOST_PROCESSES = {"applicationframehost.exe"}


class WindowsPlatform(Platform):
    name = "windows"

    def idle_seconds(self) -> float:
        info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        # Both are 32-bit millisecond tick counts; mask handles the 49.7-day wraparound.
        return ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0

    def active_window(self) -> tuple[str | None, str | None]:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None, None
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value or None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            proc = psutil.Process(pid.value).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            proc = None
        if proc and proc.lower() in HOST_PROCESSES and title:
            proc = title.split(" - ")[-1]
        return proc, title

    def is_locked(self) -> bool:
        # When the workstation is locked the input desktop is the secure "Winlogon" desktop,
        # which a normal process cannot open.
        app, _ = self.active_window()
        if app and app.lower() == "lockapp.exe":
            return True
        h = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not h:
            return True
        user32.CloseDesktop(h)
        return False
