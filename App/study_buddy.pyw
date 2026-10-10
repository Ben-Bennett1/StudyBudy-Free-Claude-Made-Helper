"""Study Buddy: a screen-aware study partner for Windows.

Press its shortcut anywhere (Ctrl+Alt+Space, or the first free one in HOTKEYS)
or click the floating bubble to open it. It can see your screen, read your
school files and search the web, and it saves anything it makes in
Documents\\Study Buddy.

It thinks with the Claude Code you're already signed in to, so there's no API
key to set up and nothing to install beyond Python.
"""

import base64
import collections
import ctypes
import ctypes.wintypes as wt
import datetime
import filecmp
import json
import math
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import traceback
import uuid
import webbrowser
import winreg
import xml.etree.ElementTree as ET
import zipfile
import zlib
from urllib.parse import urlparse

import tkinter as tk
from tkinter import filedialog
from tkinter import font as tkfont

APP_NAME = "Study Buddy"
MODEL = None  # e.g. "sonnet" for quicker answers; None uses your Claude Code default
PORT = 47653  # a second launch uses this to bring up the copy that's already running
MAX_IMAGE_SIDE = 1568  # Claude scales anything bigger down anyway
APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "study_buddy_settings.json")
LOG_PATH = os.path.join(APP_DIR, "study_buddy_errors.log")

PERSONA = """\
You are Study Buddy, a friendly study partner that lives on a student's Windows PC. \
You and the student work through school assignments together.

How to help
- First make sure you understand the assignment: what it asks for, the format, and any rules or rubric. If something important is unclear, ask one short question.
- Break big tasks into small steps and work through them with the student one at a time.
- Problems (math, science, coding and so on): explain the method and why each step works. For a set of similar questions, work through one together, then let the student try the next and check their answer.
- Writing: help brainstorm, outline, find good sources and give specific feedback on drafts. Keep the student's own ideas and voice; suggest wording rather than rewriting whole pieces.
- Studying: quiz them, make flashcards and study guides, and try a different explanation when one doesn't land.
- Double-check facts and math. Say when you're unsure, and say where information came from when you look it up.
- If an assignment says AI tools aren't allowed, mention it kindly.

What you can see and do
- The student may send a screenshot of their screen. A red circle in a screenshot marks where their mouse pointer was, which is usually what they're asking about. Look at screenshots and attachments closely before answering.
- You can read files in these folders: {readable}. You can also search the web.
- You can create and edit files only in your workspace folder: {workspace}. Save things you make there (notes, outlines, study guides, practice quizzes) with clear file names, and tell the student the name; the chat shows a link they can click to open it. Use .txt for plain notes and drafts, and a single self-contained .html file for anything interactive or nicely formatted, like flashcards or a practice quiz. Don't change files anywhere else; if the student wants changes to one of their files, save an updated copy in the workspace.
- You can't click, type in other apps or control the computer.

How to write
- Replies appear in a small chat window, so keep them short and easy to scan: a few sentences or a short list. Offer to go deeper instead of writing long answers.
- Use plain text. **Bold** for a key term and simple "-" bullets are fine; avoid tables, headings and emoji. Write math in plain text, like x^2 + 3x = 10, sqrt(2) or (a + b)/c.
- Today is {today}.
"""

WELCOME_TIPS = [
    "Press {hotkey} from anywhere and I'll look at your screen.",
    "Snip part of your screen with Win+Shift+S, then press Ctrl+V here.",
    "Click Attach to share a PDF, Word or PowerPoint file, or a photo of your homework.",
    "Anything I make for you is saved in Documents\\Study Buddy.",
]

NO_CLAUDE = ("I couldn't find Claude Code on this PC, and I need it to think. "
             "Install it from claude.com/claude-code, sign in, then restart me.")

LIGHT = dict(bg="#f5f4f0", surface="#ffffff", border="#e3e1db", text="#1f1e1d",
             muted="#6d6a64", accent="#c96442", accent_hover="#b5573a", on_accent="#ffffff",
             button="#e8e6e0", button_hover="#dcd9d2", error="#b42318", link="#1a5fb4",
             code_bg="#f0eee9")
DARK = dict(bg="#1f1e1d", surface="#262624", border="#3a3936", text="#ecebe7",
            muted="#a19e98", accent="#d97757", accent_hover="#e28a6d", on_accent="#ffffff",
            button="#33322f", button_hover="#3e3d39", error="#f97a6b", link="#8ab4f8",
            code_bg="#30302d")

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp"}
TEXT_TYPES = {".txt", ".md", ".csv", ".tsv", ".json", ".html", ".htm", ".xml", ".rtf",
              ".tex", ".py", ".java", ".js", ".ts", ".c", ".cpp", ".h", ".cs", ".css",
              ".sql", ".r", ".m", ".ipynb"}
UNREADABLE_TYPES = {".doc", ".xls", ".xlsx", ".ppt", ".pages", ".numbers", ".key"}

# Variables a parent Claude Code session sets. The helper should start fresh without them.
SESSION_VARS = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_",
                "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_MESSAGING_", "CLAUDE_CODE_BRIDGE_",
                "CLAUDE_CODE_WORKER_", "CLAUDE_CODE_ENVIRONMENT_KIND")

# ------------------------------------------------------------------ Windows --

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32")
ole32 = ctypes.WinDLL("ole32")
dwmapi = ctypes.WinDLL("dwmapi")

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x4000
VK_SPACE, VK_LWIN, VK_H, VK_B = 0x20, 0x5B, 0x48, 0x42
KEYEVENTF_KEYUP = 0x0002
WM_HOTKEY = 0x0312
SRCCOPY, CAPTUREBLT = 0x00CC0020, 0x40000000
HALFTONE, PS_SOLID, NULL_BRUSH = 4, 0, 5
BI_RGB, BI_BITFIELDS, BI_ALPHABITFIELDS = 0, 3, 6
DIB_RGB_COLORS = 0
CF_DIB, CF_UNICODETEXT = 8, 13
MONITOR_DEFAULTTONULL, MONITOR_DEFAULTTONEAREST = 0, 2
DWMWA_USE_IMMERSIVE_DARK_MODE = 20

# Tried in order; the first one no other app has taken becomes the shortcut.
HOTKEYS = [("Ctrl+Alt+Space", MOD_CONTROL | MOD_ALT, VK_SPACE),
           ("Alt+Shift+Space", MOD_ALT | MOD_SHIFT, VK_SPACE),
           ("Ctrl+Alt+B", MOD_CONTROL | MOD_ALT, VK_B)]

KNOWN_FOLDERS = {"Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
                 "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
                 "Downloads": "374DE290-123F-4565-9164-39C4925E467B"}


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


def _sig(fn, restype, *argtypes):
    fn.restype, fn.argtypes = restype, argtypes


_int = ctypes.c_int
_sig(user32.GetCursorPos, wt.BOOL, ctypes.POINTER(wt.POINT))
_sig(user32.MonitorFromPoint, wt.HMONITOR, wt.POINT, wt.DWORD)
_sig(user32.GetMonitorInfoW, wt.BOOL, wt.HMONITOR, ctypes.POINTER(MONITORINFO))
_sig(user32.GetDC, wt.HDC, wt.HWND)
_sig(user32.ReleaseDC, _int, wt.HWND, wt.HDC)
_sig(user32.RegisterHotKey, wt.BOOL, wt.HWND, _int, wt.UINT, wt.UINT)
_sig(user32.GetMessageW, wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
_sig(user32.SetForegroundWindow, wt.BOOL, wt.HWND)
_sig(user32.GetForegroundWindow, wt.HWND)
_sig(user32.BringWindowToTop, wt.BOOL, wt.HWND)
_sig(user32.AllowSetForegroundWindow, wt.BOOL, wt.DWORD)
_sig(user32.GetWindowThreadProcessId, wt.DWORD, wt.HWND, ctypes.POINTER(wt.DWORD))
_sig(user32.AttachThreadInput, wt.BOOL, wt.DWORD, wt.DWORD, wt.BOOL)
_sig(kernel32.GetCurrentThreadId, wt.DWORD)
_sig(user32.OpenClipboard, wt.BOOL, wt.HWND)
_sig(user32.CloseClipboard, wt.BOOL)
_sig(user32.IsClipboardFormatAvailable, wt.BOOL, wt.UINT)
_sig(user32.GetClipboardData, wt.HANDLE, wt.UINT)
_sig(user32.keybd_event, None, wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t)
_sig(gdi32.CreateCompatibleDC, wt.HDC, wt.HDC)
_sig(gdi32.CreateCompatibleBitmap, wt.HBITMAP, wt.HDC, _int, _int)
_sig(gdi32.SelectObject, wt.HGDIOBJ, wt.HDC, wt.HGDIOBJ)
_sig(gdi32.DeleteObject, wt.BOOL, wt.HGDIOBJ)
_sig(gdi32.DeleteDC, wt.BOOL, wt.HDC)
_sig(gdi32.SetStretchBltMode, _int, wt.HDC, _int)
_sig(gdi32.SetBrushOrgEx, wt.BOOL, wt.HDC, _int, _int, ctypes.c_void_p)
_sig(gdi32.StretchBlt, wt.BOOL, wt.HDC, _int, _int, _int, _int,
     wt.HDC, _int, _int, _int, _int, wt.DWORD)
_sig(gdi32.StretchDIBits, _int, wt.HDC, _int, _int, _int, _int, _int, _int, _int, _int,
     ctypes.c_void_p, ctypes.c_void_p, wt.UINT, wt.DWORD)
_sig(gdi32.GetDIBits, _int, wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT,
     ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wt.UINT)
_sig(gdi32.CreatePen, wt.HPEN, _int, _int, wt.COLORREF)
_sig(gdi32.GetStockObject, wt.HGDIOBJ, _int)
_sig(gdi32.Ellipse, wt.BOOL, wt.HDC, _int, _int, _int, _int)
_sig(kernel32.GlobalLock, ctypes.c_void_p, wt.HGLOBAL)
_sig(kernel32.GlobalUnlock, wt.BOOL, wt.HGLOBAL)
_sig(kernel32.GlobalSize, ctypes.c_size_t, wt.HGLOBAL)
_sig(shell32.SHGetKnownFolderPath, ctypes.c_long, ctypes.POINTER(GUID), wt.DWORD,
     wt.HANDLE, ctypes.POINTER(ctypes.c_wchar_p))
_sig(ole32.CoTaskMemFree, None, ctypes.c_void_p)
_sig(dwmapi.DwmSetWindowAttribute, ctypes.c_long, wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD)


def use_real_pixels():
    """Opt out of Windows' DPI scaling so screenshots and window positions line up."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def cursor_pos():
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def monitor_rects(x, y):
    """The (whole monitor, usable work area) rectangles of the monitor nearest (x, y)."""
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromPoint(wt.POINT(x, y), MONITOR_DEFAULTTONEAREST),
                           ctypes.byref(info))
    return info.rcMonitor, info.rcWork


def on_a_monitor(x, y):
    return bool(user32.MonitorFromPoint(wt.POINT(x, y), MONITOR_DEFAULTTONULL))


def _fit(w, h):
    s = min(1.0, MAX_IMAGE_SIDE / max(w, h))
    return max(1, round(w * s)), max(1, round(h * s))


def _png(w, h, bgra):
    rgb = bytearray(w * h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    row = w * 3
    raw = b"".join(b"\0" + rgb[i:i + row] for i in range(0, len(rgb), row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _draw_to_png(w, h, draw):
    """Let draw(memory_dc, screen_dc) paint a w x h bitmap, then return it as PNG bytes."""
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        gdi32.SetStretchBltMode(mem, HALFTONE)
        gdi32.SetBrushOrgEx(mem, 0, 0, None)
        draw(mem, screen)
        gdi32.SelectObject(mem, old)  # GetDIBits wants the bitmap deselected
        old = None
        info = BITMAPINFO()
        hdr = info.bmiHeader
        hdr.biSize, hdr.biWidth, hdr.biHeight = ctypes.sizeof(BITMAPINFOHEADER), w, -h  # top-down
        hdr.biPlanes, hdr.biBitCount, hdr.biCompression = 1, 32, BI_RGB
        pixels = ctypes.create_string_buffer(w * h * 4)
        if gdi32.GetDIBits(mem, bmp, 0, h, pixels, ctypes.byref(info), DIB_RGB_COLORS) != h:
            raise OSError("Windows wouldn't hand over the image")
    finally:
        if old:
            gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)
    return _png(w, h, pixels.raw)


def capture_screen(mark_cursor=False):
    """PNG of the monitor under the mouse, optionally with a red ring around the pointer."""
    cx, cy = cursor_pos()
    mon, _ = monitor_rects(cx, cy)
    w, h = mon.right - mon.left, mon.bottom - mon.top
    dw, dh = _fit(w, h)

    def draw(mem, screen):
        gdi32.StretchBlt(mem, 0, 0, dw, dh, screen, mon.left, mon.top, w, h, SRCCOPY | CAPTUREBLT)
        if mark_cursor:
            x, y = round((cx - mon.left) * dw / w), round((cy - mon.top) * dh / h)
            r = max(14, dw // 60)
            pen = gdi32.CreatePen(PS_SOLID, 4, 0x003030FF)
            old_pen = gdi32.SelectObject(mem, pen)
            old_brush = gdi32.SelectObject(mem, gdi32.GetStockObject(NULL_BRUSH))
            gdi32.Ellipse(mem, x - r, y - r, x + r, y + r)
            gdi32.SelectObject(mem, old_brush)
            gdi32.SelectObject(mem, old_pen)
            gdi32.DeleteObject(pen)

    return _draw_to_png(dw, dh, draw), dw, dh


def clipboard_image():
    """PNG of the picture on the clipboard (say, from Win+Shift+S), or None."""
    if not user32.IsClipboardFormatAvailable(CF_DIB) or not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_DIB)
        ptr = kernel32.GlobalLock(handle) if handle else None
        if not ptr:
            return None
        try:
            data = ctypes.string_at(ptr, kernel32.GlobalSize(handle))
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    return dib_to_png(data)


def dib_to_png(data):
    """PNG of a Windows device-independent bitmap (the clipboard's picture format), or None."""
    if len(data) < ctypes.sizeof(BITMAPINFOHEADER):
        return None
    hdr = BITMAPINFOHEADER.from_buffer_copy(data)
    w, h = hdr.biWidth, abs(hdr.biHeight)
    if w <= 0 or h <= 0:
        return None
    offset = hdr.biSize  # the pixels start after the header, any color masks and any palette
    if hdr.biSize == 40 and hdr.biCompression == BI_BITFIELDS:
        offset += 12
    elif hdr.biSize == 40 and hdr.biCompression == BI_ALPHABITFIELDS:
        offset += 16
    offset += 4 * (hdr.biClrUsed or (1 << hdr.biBitCount if hdr.biBitCount <= 8 else 0))
    info = ctypes.create_string_buffer(data[:offset], offset)
    bits = ctypes.create_string_buffer(data[offset:], max(1, len(data) - offset))
    dw, dh = _fit(w, h)

    def draw(mem, screen):
        gdi32.StretchDIBits(mem, 0, 0, dw, dh, 0, 0, w, h, bits, info, DIB_RGB_COLORS, SRCCOPY)

    return _draw_to_png(dw, dh, draw), dw, dh


def bring_to_front(hwnd):
    """Give our window the keyboard. Windows stops apps from grabbing focus, so if the
    plain request is refused, briefly share input with the window that has it."""
    if user32.SetForegroundWindow(hwnd) and user32.GetForegroundWindow() == hwnd:
        return
    other = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    mine = kernel32.GetCurrentThreadId()
    if other and other != mine and user32.AttachThreadInput(mine, other, True):
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            user32.AttachThreadInput(mine, other, False)


def press_win_h():
    """Open Windows voice typing, which types whatever you say into the focused box."""
    for key, flags in ((VK_LWIN, 0), (VK_H, 0), (VK_H, KEYEVENTF_KEYUP), (VK_LWIN, KEYEVENTF_KEYUP)):
        user32.keybd_event(key, 0, flags, 0)


def use_dark_title_bar(hwnd, dark):
    value = ctypes.c_int(1 if dark else 0)
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value),
                                 ctypes.sizeof(value))


def windows_dark_mode():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def known_folder(name):
    guid = GUID.from_buffer_copy(uuid.UUID(KNOWN_FOLDERS[name]).bytes_le)
    out = ctypes.c_wchar_p()
    try:
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0 and out.value:
            return out.value
    finally:
        if out:
            ole32.CoTaskMemFree(ctypes.cast(out, ctypes.c_void_p))
    return os.path.join(os.path.expanduser("~"), name)


def hotkey_loop(events, chosen):
    """Claim the first free shortcut, report its name through chosen, then wait for presses."""
    label = next((name for name, mods, key in HOTKEYS
                  if user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, key)), None)
    chosen.put(label)
    if not label:
        return
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            # This thread got the key press, so it may pass focus rights to the UI thread.
            user32.AllowSetForegroundWindow(os.getpid())
            events.put(("hotkey",))


def claim_single_instance(events):
    """False if Study Buddy is already running (it gets asked to show itself instead)."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1) as conn:
            conn.sendall(b"show")
            if conn.recv(32) == b"study-buddy":
                return False
    except OSError:
        pass
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        server.bind(("127.0.0.1", PORT))
        server.listen(2)
    except OSError:
        return True  # something else has the port; run without the single-copy check

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(1)
                    request = conn.recv(16)
                    if request in (b"show", b"quit"):
                        conn.sendall(b"study-buddy")
                        events.put((request.decode(),))
                except OSError:
                    pass

    threading.Thread(target=serve, daemon=True).start()
    return True


# ------------------------------------------------------------ Claude Code --

class Places:
    def __init__(self):
        self.documents = known_folder("Documents")
        self.desktop = known_folder("Desktop")
        self.downloads = known_folder("Downloads")
        self.workspace = os.path.join(self.documents, APP_NAME)
        self.attachments = os.path.join(self.workspace, "Attached files")
        self.readable = []
        old_downloads = os.path.join(os.path.expanduser("~"), "Downloads")  # OneDrive can move Downloads
        for folder in (self.documents, self.desktop, self.downloads, old_downloads):
            if os.path.isdir(folder) and not any(
                    os.path.normcase(folder) == os.path.normcase(f) or is_inside(folder, f)
                    for f in self.readable):
                self.readable.append(folder)


def find_claude():
    found = shutil.which("claude")
    if found:
        return found
    guess = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    return guess if os.path.exists(guess) else None


def child_env():
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(SESSION_VARS)}


def rule_path(path):
    """A folder written the way Claude Code permission rules expect."""
    home, path = os.path.expanduser("~"), os.path.normpath(path)
    if os.path.normcase(path).startswith(os.path.normcase(home) + os.sep):
        return "~/" + os.path.relpath(path, home).replace("\\", "/")
    drive, rest = os.path.splitdrive(path)
    return "//" + drive.rstrip(":").lower() + rest.replace("\\", "/")


def today_text():
    d = datetime.date.today()
    return f"{d:%A}, {d:%B} {d.day}, {d.year}"


def claude_command(claude, places, resume=None):
    """The Claude Code command for the helper: it can read schoolwork folders, search the
    web and write only inside the workspace; it has no shell, so it can't run programs."""
    persona = PERSONA.format(workspace=places.workspace, readable=", ".join(places.readable),
                             today=today_text())
    allow = ["WebSearch", "WebFetch"] + [f"Read({rule_path(p)}/**)" for p in places.readable]
    cmd = [claude, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
           "--verbose", "--include-partial-messages",
           "--tools", "Read,Write,Edit,Glob,Grep,WebSearch,WebFetch",
           "--permission-mode", "acceptEdits", "--permission-prompts", "none",
           "--settings", json.dumps({"permissions": {"allow": allow}}),
           "--strict-mcp-config", "--system-prompt", persona]
    if MODEL:
        cmd += ["--model", MODEL]
    if resume:
        cmd += ["--resume", resume]
    return cmd


def pump_stdout(proc, err_thread, events):
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("{"):
            try:
                events.put(("agent", proc, json.loads(line)))
            except ValueError:
                pass
    proc.wait()
    err_thread.join(2)
    events.put(("exit", proc))


def pump_stderr(proc):
    for line in proc.stderr:
        proc.err_tail.append(line.rstrip())


def kill_tree(proc):
    if proc and proc.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)


def friendly_error(text):
    text = text.strip()
    low = text.lower()
    if any(k in low for k in ("not logged in", "/login", "log in", "authenticat", "oauth", "401")):
        return ("Claude Code needs you to sign in. Open a terminal, type claude, sign in, "
                "then try again.")
    return "Something went wrong: " + (" ".join(text.splitlines()[-3:])[:400] or "Claude Code stopped.")


class Attachment:
    def __init__(self, kind, label, **extra):
        self.kind, self.label = kind, label  # kind is "image", "text" or "file"
        self.data = self.media = self.note = self.thumb = self.text = self.path = None
        self.__dict__.update(extra)


def build_content(text, attachments):
    blocks, notes = [], []
    for a in attachments:
        if a.kind == "image":
            blocks.append({"type": "image", "source": {
                "type": "base64", "media_type": a.media,
                "data": base64.b64encode(a.data).decode("ascii")}})
            notes.append(f"({a.note})")
        elif a.kind == "text":
            notes.append(f"[Attached file: {a.label}]\n{a.text}\n[End of {a.label}]")
        else:
            notes.append(f"[Attached file: {a.label}. It's saved at {a.path}; open it with the Read tool.]")
    notes.append(text or "Can you help me with this?")
    blocks.append({"type": "text", "text": "\n\n".join(notes)})
    return blocks


def describe_tool(name, args):
    file = os.path.basename(str(args.get("file_path") or "")) or "a file"
    if name == "Read":
        return f"Reading {file}"
    if name == "Write":
        return f"Writing {file}"
    if name == "Edit":
        return f"Editing {file}"
    if name == "Glob":
        return "Looking through your files"
    if name == "Grep":
        return f"Searching your files for “{args.get('pattern', '')}”"
    if name == "WebSearch":
        return f"Searching the web for “{args.get('query', '')}”"
    if name == "WebFetch":
        return f"Reading {urlparse(str(args.get('url', ''))).netloc or 'a web page'}"
    return f"Using {name}"


# ------------------------------------------------------------------ files --

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for para in root.iter(W_NS + "p"):
        parts = []
        for el in para.iter():
            if el.tag == W_NS + "t" and el.text:
                parts.append(el.text)
            elif el.tag == W_NS + "tab":
                parts.append("\t")
            elif el.tag in (W_NS + "br", W_NS + "cr"):
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines)


def pptx_text(path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        names.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        slides = []
        for number, name in enumerate(names, 1):
            root = ET.fromstring(z.read(name))
            paras = ["".join(t.text or "" for t in p.iter(A_NS + "t")) for p in root.iter(A_NS + "p")]
            slides.append(f"--- Slide {number} ---\n" + "\n".join(p for p in paras if p.strip()))
    return "\n\n".join(slides)


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def clip(text, limit=60000):
    return text if len(text) <= limit else text[:limit] + "\n[...the rest was cut off because the file is long]"


def is_inside(path, folder):
    path, folder = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return path.startswith(folder + os.sep)


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


# --------------------------------------------------------------- markdown --

INLINE = re.compile(r"(\*\*[^*\n]+?\*\*|__[^_\n]+?__|`[^`\n]+`|https?://[^\s<>\"')\]]+)")


def md_segments(text):
    """Turn the bits of markdown Claude tends to use into (text, tags) runs."""
    out, in_code = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append((line + "\n", ("code",)))
            continue
        heading = re.match(r"\s{0,3}#{1,6}\s+(.*)", line)
        if heading:
            out.append((heading.group(1).replace("**", "") + "\n", ("head",)))
            continue
        if re.fullmatch(r"\s*([-*_])(\s*\1){2,}\s*", line):
            continue  # a horizontal rule
        tags = ()
        bullet = re.match(r"\s*[-*+•]\s+(.*)", line)
        if bullet:
            line, tags = "• " + bullet.group(1), ("bullet",)
        elif re.match(r"\s*\d+[.)]\s", line):
            line, tags = line.strip(), ("bullet",)
        for part in INLINE.split(line):
            if not part:
                continue
            if len(part) > 4 and part[:2] in ("**", "__") and part[-2:] == part[:2]:
                out.append((part[2:-2], tags + ("bold",)))
            elif len(part) > 2 and part[0] == part[-1] == "`":
                out.append((part[1:-1], tags + ("code",)))
            elif part.startswith(("http://", "https://")):
                url = part.rstrip(".,;:!?")
                out.append((url, tags + ("url",)))
                if len(url) < len(part):
                    out.append((part[len(url):], tags))
            else:
                out.append((part, tags))
        out.append(("\n", tags))
    return out


def plain_text(md):
    return "".join(seg for seg, _ in md_segments(md)).strip()


# --------------------------------------------------------------------- UI --

class Turn:
    """What's happened so far in the answer being streamed in."""

    def __init__(self):
        self.tools, self.files, self.answer = set(), [], []
        self.buf, self.in_text, self.wrote_text, self.tool_since_text = "", False, False, False


class Bubble:
    """The little floating button. Click to open Study Buddy, drag to move it."""

    def __init__(self, app):
        self.app = app
        self.size = s = app.px(46)
        key = "#ff00fe"  # painted transparent, which makes the window round
        self.win = tk.Toplevel(app.root)
        self.win.title(f"{APP_NAME} bubble")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=key)
        self.win.attributes("-transparentcolor", key)
        self.canvas = tk.Canvas(self.win, width=s, height=s, bg=key, highlightthickness=0,
                                cursor="hand2")
        self.canvas.pack()
        accent = app.c["accent"]
        self.canvas.create_oval(1, 1, s - 1, s - 1, fill=accent, outline=accent)
        self.canvas.create_text(s / 2, s / 2, text="✎", fill="#ffffff", font=app.f_icon)
        dot = app.px(13)
        self.dot = self.canvas.create_oval(s - dot, 1, s - 1, dot, fill="#e5484d",
                                           outline="#ffffff", state="hidden")
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Button-3>", self.menu)
        x, y = app.cfg.get("bubble_x"), app.cfg.get("bubble_y")
        if x is None or y is None or not on_a_monitor(x + s // 2, y + s // 2):
            _, work = monitor_rects(0, 0)
            x, y = work.right - s - app.px(14), work.top + int((work.bottom - work.top) * 0.55)
        self.move_to(x, y)
        self.start = None
        if not app.cfg.get("show_bubble", True):
            self.win.withdraw()

    def visible(self):
        return self.win.state() == "normal"

    def toggle(self):
        if self.visible():
            self.win.withdraw()
        else:
            self.win.deiconify()
            self.win.lift()
        self.app.cfg["show_bubble"] = self.visible()
        save_config(self.app.cfg)

    def set_dot(self, on):
        self.canvas.itemconfigure(self.dot, state="normal" if on else "hidden")

    def move_to(self, x, y):
        # Tk only reports a window's position once it's drawn, so keep track of it here.
        self.x, self.y = x, y
        self.win.geometry(f"+{x}+{y}")

    def press(self, e):
        self.start = (e.x_root, e.y_root, self.x, self.y, False)

    def drag(self, e):
        if not self.start:
            return
        x0, y0, wx, wy, moved = self.start
        dx, dy = e.x_root - x0, e.y_root - y0
        if moved or abs(dx) + abs(dy) > 4:
            self.start = (x0, y0, wx, wy, True)
            self.move_to(wx + dx, wy + dy)

    def release(self, e):
        if not self.start:
            return
        moved, self.start = self.start[4], None
        if moved:
            self.app.cfg["bubble_x"], self.app.cfg["bubble_y"] = self.x, self.y
            save_config(self.app.cfg)
        else:
            self.app.on_bubble_click()

    def menu(self, e):
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label=f"Open {APP_NAME}", command=self.app.show_panel)
        m.add_command(label="Hide this bubble", command=self.toggle)
        m.add_separator()
        m.add_command(label=f"Quit {APP_NAME}", command=self.app.quit)
        m.tk_popup(e.x_root, e.y_root)


class App:
    def __init__(self, root, events):
        self.root, self.events = root, events
        self.places = Places()
        os.makedirs(self.places.workspace, exist_ok=True)
        self.claude = find_claude()
        self.cfg = load_config()
        self.dark = windows_dark_mode()
        self.c = DARK if self.dark else LIGHT
        self.scale = root.winfo_fpixels("1i") / 96
        self.proc = None
        self.session_id = None
        self.busy = False
        self.turn = None
        self.attachments = []
        self.last_answer = ""
        self.link_count = 0
        self.titled = False
        root.report_callback_exception = self.report_crash
        chosen = queue.Queue()
        threading.Thread(target=hotkey_loop, args=(events, chosen), daemon=True).start()
        try:
            self.hotkey = chosen.get(timeout=3)  # None if every shortcut is taken
        except queue.Empty:
            self.hotkey = None
        self.make_fonts()
        self.build_panel()
        self.bubble = Bubble(self)
        self.welcome()
        if not self.claude:
            self.say_error(NO_CLAUDE)
        root.after(30, self.poll)
        self.show_panel()

    def px(self, n):
        return int(round(n * self.scale))

    def hwnd(self):
        return int(self.root.wm_frame(), 16)

    # ------------------------------------------------------------ layout --

    def make_fonts(self):
        def font(size, weight="normal", family="Segoe UI"):
            return tkfont.Font(root=self.root, family=family, size=size, weight=weight)

        self.f_body, self.f_bold = font(10), font(10, "bold")
        self.f_title, self.f_head = font(11, "bold"), font(11, "bold")
        self.f_small, self.f_code = font(9), font(10, family="Consolas")
        self.f_icon = font(15, family="Segoe UI Symbol")

    def button(self, parent, text, command, primary=False):
        b = tk.Label(parent, text=text, font=self.f_bold if primary else self.f_body,
                     padx=self.px(10), pady=self.px(4), cursor="hand2")
        self.paint_button(b, primary)
        b.bind("<Button-1>", lambda e: command())
        b.bind("<Enter>", lambda e: b.configure(bg=b.hover_bg))
        b.bind("<Leave>", lambda e: b.configure(bg=b.normal_bg))
        return b

    def paint_button(self, b, primary):
        c = self.c
        b.normal_bg = c["accent"] if primary else c["button"]
        b.hover_bg = c["accent_hover"] if primary else c["button_hover"]
        b.configure(bg=b.normal_bg, fg=c["on_accent"] if primary else c["text"])

    def build_panel(self):
        r, c, px = self.root, self.c, self.px
        r.title(APP_NAME)
        r.configure(bg=c["bg"])
        r.attributes("-topmost", True)
        r.attributes("-toolwindow", True)
        r.minsize(px(320), px(380))
        r.protocol("WM_DELETE_WINDOW", self.hide_panel)
        r.bind("<Escape>", lambda e: self.hide_panel())

        head = tk.Frame(r, bg=c["bg"])
        head.pack(side="top", fill="x", padx=px(12), pady=(px(10), px(8)))
        tk.Label(head, text=APP_NAME, font=self.f_title, bg=c["bg"], fg=c["text"]).pack(side="left")
        self.menu_btn = self.button(head, "⋯", self.show_menu)
        self.menu_btn.pack(side="right")
        self.button(head, "Folder", self.open_workspace).pack(side="right", padx=(0, px(6)))
        self.button(head, "New chat", self.new_chat).pack(side="right", padx=(0, px(6)))

        self.status = tk.Label(r, font=self.f_small, bg=c["bg"], fg=c["muted"], anchor="w")
        self.status.pack(side="bottom", fill="x", padx=px(12), pady=(0, px(8)))
        self.set_status()

        actions = tk.Frame(r, bg=c["bg"])
        actions.pack(side="bottom", fill="x", padx=px(12), pady=px(6))
        self.button(actions, "Look at screen", self.look_at_screen).pack(side="left")
        self.button(actions, "Attach", self.pick_files).pack(side="left", padx=(px(6), 0))
        self.button(actions, "Talk", self.dictate).pack(side="left", padx=(px(6), 0))
        self.send_btn = self.button(actions, "Send", self.send_or_stop, primary=True)
        self.send_btn.pack(side="right")

        self.box = tk.Frame(r, bg=c["surface"], highlightthickness=1,
                            highlightbackground=c["border"], highlightcolor=c["accent"])
        self.box.pack(side="bottom", fill="x", padx=px(12))
        self.input = tk.Text(self.box, height=3, wrap="word", font=self.f_body, bg=c["surface"],
                             fg=c["text"], insertbackground=c["text"], relief="flat",
                             padx=px(8), pady=px(6), undo=True, highlightthickness=0)
        self.input.pack(fill="x")
        self.placeholder = tk.Label(self.box, text="Ask about your assignment…",
                                    font=self.f_body, bg=c["surface"], fg=c["muted"])
        self.placeholder.bind("<Button-1>", lambda e: self.input.focus_set())
        self.input.bind("<<Modified>>", self.on_input_change)
        self.input.bind("<Return>", self.on_enter)
        self.input.bind("<Control-v>", self.on_paste)
        self.input.bind("<Control-V>", self.on_paste)
        self.on_input_change()

        self.chips = tk.Frame(r, bg=c["bg"])

        self.chat_frame = tk.Frame(r, bg=c["surface"], highlightthickness=1,
                                   highlightbackground=c["border"])
        self.chat_frame.pack(side="top", fill="both", expand=True, padx=px(12), pady=(0, px(4)))
        self.chat = tk.Text(self.chat_frame, wrap="word", font=self.f_body, bg=c["surface"],
                            fg=c["text"], relief="flat", padx=px(12), pady=px(10), cursor="arrow",
                            highlightthickness=0, spacing3=px(2), state="disabled",
                            selectbackground=c["accent"], selectforeground=c["on_accent"],
                            inactiveselectbackground=c["accent"])
        self.chat.pack(fill="both", expand=True)
        indent = px(4) + self.f_body.measure("• ")
        tag = self.chat.tag_configure
        tag("bot", foreground=c["text"])
        tag("you", foreground=c["text"])
        tag("who_you", font=self.f_bold, foreground=c["muted"], spacing1=px(10))
        tag("who_bot", font=self.f_bold, foreground=c["accent"], spacing1=px(10))
        tag("head", font=self.f_head, spacing1=px(6))
        tag("bold", font=self.f_bold)
        tag("bullet", lmargin1=px(4), lmargin2=indent)
        tag("code", font=self.f_code, background=c["code_bg"])
        tag("tool", font=self.f_small, foreground=c["muted"])
        tag("note", font=self.f_small, foreground=c["muted"])
        tag("error", foreground=c["error"])
        tag("link", foreground=c["link"], underline=True)
        menu = tk.Menu(r, tearoff=0)
        menu.add_command(label="Copy", command=lambda: self.chat.event_generate("<<Copy>>"))
        menu.add_command(label="Copy last answer", command=self.copy_last_answer)
        self.chat.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    def set_status(self, text=None):
        if text is None:
            text = (f"{self.hotkey} shows or hides me · Shift+Enter for a new line"
                    if self.hotkey else "Click the bubble to show or hide me")
        self.status.configure(text=text)

    def set_send_mode(self, stop):
        self.send_btn.configure(text="Stop" if stop else "Send")
        self.paint_button(self.send_btn, primary=not stop)

    # -------------------------------------------------------- chat output --

    def write(self, text, *tags):
        follow = self.chat.yview()[1] >= 0.999
        self.chat.configure(state="normal")
        self.chat.insert("end", text, tags)
        self.chat.configure(state="disabled")
        if follow:
            self.chat.see("end")

    def edit(self, change):
        self.chat.configure(state="normal")
        change()
        self.chat.configure(state="disabled")

    def line_break(self):
        last = self.chat.get("end-2c", "end-1c")
        if last and last != "\n":
            self.write("\n")

    def link(self, text, action, *tags):
        self.link_count += 1
        name = f"link{self.link_count}"
        self.chat.tag_bind(name, "<Button-1>", lambda e: action())
        self.chat.tag_bind(name, "<Enter>", lambda e: self.chat.configure(cursor="hand2"))
        self.chat.tag_bind(name, "<Leave>", lambda e: self.chat.configure(cursor="arrow"))
        self.write(text, "link", name, *tags)

    def file_link(self, path):
        self.write("Saved ", "note")
        self.link(os.path.basename(path), lambda: os.startfile(path), "note")
        self.write(" · ", "note")
        self.link("show in folder", lambda: subprocess.Popen(f'explorer /select,"{path}"'), "note")
        self.write("\n", "note")

    def say_error(self, text):
        self.line_break()
        self.write(text + "\n", "error")

    def welcome(self):
        self.write(APP_NAME + "\n", "who_bot")
        self.write("Hi! Let's work through your assignments together. Here's how to use me:\n", "bot")
        for tip in WELCOME_TIPS:
            if "{hotkey}" in tip and not self.hotkey:
                tip = "Click the floating bubble anytime and I'll look at your screen."
            self.write("• " + tip.format(hotkey=self.hotkey) + "\n", "bot", "bullet")

    def copy_last_answer(self):
        if self.last_answer:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_answer)

    # ------------------------------------------------------ show and hide --

    def panel_visible(self):
        return self.root.state() == "normal"

    def show_panel(self, near=None, keep_place=False):
        r = self.root
        if not keep_place:
            w = self.cfg.get("panel_w") or self.px(440)
            h = self.cfg.get("panel_h") or self.px(620)
            r.geometry("{}x{}+{}+{}".format(*self.panel_spot(w, h, near)))
        r.deiconify()
        r.lift()
        r.attributes("-topmost", True)
        r.update_idletasks()
        if not self.titled:
            self.titled = True
            use_dark_title_bar(self.hwnd(), self.dark)
        bring_to_front(self.hwnd())
        r.focus_force()
        self.input.focus_set()
        self.bubble.set_dot(False)
        self.ensure_agent()

    def panel_spot(self, w, h, near):
        """Size and place the panel: beside the mouse when the hotkey opened it, else by
        the bubble, and never bigger than the screen it's on."""
        gap, margin, title_bar = self.px(16), self.px(8), self.px(40)
        b = self.bubble
        if near is None and b.visible():
            bx, by = b.x, b.y
            _, work = monitor_rects(bx, by)
        else:
            ax, ay = near or cursor_pos()
            _, work = monitor_rects(ax, ay)
        w = min(w, work.right - work.left - 2 * margin)
        h = min(h, work.bottom - work.top - margin - title_bar)
        if near is None and b.visible():
            x = bx - w - gap if bx - w - gap >= work.left else bx + b.size + gap
            y = by + b.size // 2 - h // 2
        else:
            x = ax + gap if ax + gap + w <= work.right else ax - w - gap
            y = ay + gap
        x = max(work.left + margin, min(x, work.right - w - margin))
        y = max(work.top + margin, min(y, work.bottom - h - title_bar))
        return w, h, x, y

    def hide_panel(self):
        if self.panel_visible():
            self.cfg["panel_w"], self.cfg["panel_h"] = self.root.winfo_width(), self.root.winfo_height()
            save_config(self.cfg)
        self.root.withdraw()

    def on_hotkey(self):
        if self.panel_visible():
            self.hide_panel()
            return
        near = cursor_pos()
        self.grab_screen(mark_cursor=True)
        self.show_panel(near=near)

    def on_bubble_click(self):
        if self.panel_visible():
            self.hide_panel()
            return
        self.grab_screen()
        self.show_panel()

    def look_at_screen(self):
        bubble_was_up = self.bubble.visible()
        self.root.withdraw()
        if bubble_was_up:
            self.bubble.win.withdraw()

        def grab():
            self.grab_screen()
            if bubble_was_up:
                self.bubble.win.deiconify()
            self.show_panel(keep_place=True)

        self.root.after(350, grab)

    def show_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Hide the floating bubble" if self.bubble.visible()
                      else "Show the floating bubble", command=self.bubble.toggle)
        m.add_command(label=f"Open the {APP_NAME} folder", command=self.open_workspace)
        m.add_separator()
        m.add_command(label=f"Quit {APP_NAME}", command=self.quit)
        b = self.menu_btn
        m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def open_workspace(self):
        os.makedirs(self.places.workspace, exist_ok=True)
        os.startfile(self.places.workspace)

    def quit(self):
        kill_tree(self.proc)
        self.hide_panel()
        self.root.destroy()

    # -------------------------------------------------------- attachments --

    def grab_screen(self, mark_cursor=False):
        try:
            png, _, _ = capture_screen(mark_cursor)
        except Exception as e:  # a failed screenshot shouldn't stop the chat
            self.say_error(f"I couldn't take a screenshot ({e}).")
            return
        note = "This is a screenshot of my screen."
        if mark_cursor:
            note += " The red circle marks where my mouse pointer is."
        self.attachments = [a for a in self.attachments if a.label != "Screen"]
        self.add_attachment(Attachment("image", "Screen", data=png, media="image/png",
                                       note=note, thumb=png))

    def add_attachment(self, a):
        self.attachments.append(a)
        self.render_chips()

    def remove_attachment(self, a):
        self.attachments.remove(a)
        self.render_chips()

    def render_chips(self):
        c, px = self.c, self.px
        for child in self.chips.winfo_children():
            child.destroy()
        if not self.attachments:
            self.chips.pack_forget()
            return
        for a in self.attachments:
            chip = tk.Frame(self.chips, bg=c["button"])
            chip.pack(side="left", padx=(0, px(6)))
            if a.thumb:
                try:
                    image = tk.PhotoImage(data=base64.b64encode(a.thumb).decode("ascii"))
                    step = max(1, math.ceil(max(image.width() / px(64), image.height() / px(40))))
                    image = image.subsample(step, step)
                    pic = tk.Label(chip, image=image, bg=c["button"])
                    pic.image = image
                    pic.pack(side="left", padx=(px(4), 0), pady=px(4))
                except tk.TclError:
                    pass
            tk.Label(chip, text=a.label, font=self.f_small, bg=c["button"],
                     fg=c["text"]).pack(side="left", padx=(px(6), px(2)))
            x = tk.Label(chip, text="✕", font=self.f_small, bg=c["button"], fg=c["muted"],
                         cursor="hand2")
            x.pack(side="left", padx=(px(2), px(6)))
            x.bind("<Button-1>", lambda e, a=a: self.remove_attachment(a))
        self.chips.pack(side="bottom", fill="x", padx=px(12), pady=(px(6), 0), before=self.chat_frame)

    def pick_files(self):
        paths = filedialog.askopenfilenames(
            parent=self.root, title="Attach files",
            initialdir=self.cfg.get("last_dir") or self.places.documents,
            filetypes=[("Schoolwork", "*.pdf *.docx *.pptx *.txt *.md *.csv *.png *.jpg *.jpeg "
                                      "*.gif *.webp *.html *.py"), ("All files", "*.*")])
        for path in paths:
            self.attach_path(path)
        if paths:
            self.cfg["last_dir"] = os.path.dirname(paths[0])
            save_config(self.cfg)
        self.input.focus_set()

    def attach_path(self, path):
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        try:
            size = os.path.getsize(path)
            if ext in IMAGE_TYPES and size <= 3_500_000:
                with open(path, "rb") as f:
                    data = f.read()
                self.add_attachment(Attachment("image", name, data=data, media=IMAGE_TYPES[ext],
                                               note=f"Here's an image: {name}",
                                               thumb=data if ext in (".png", ".gif") else None))
            elif ext in (".docx", ".pptx"):
                text = docx_text(path) if ext == ".docx" else pptx_text(path)
                self.add_attachment(Attachment("text", name, text=clip(text)))
            elif ext in TEXT_TYPES and size <= 300_000:
                self.add_attachment(Attachment("text", name, text=clip(read_text(path))))
            elif ext in UNREADABLE_TYPES:
                self.say_error(f"I can't read {ext} files yet. Try saving {name} as a PDF "
                               "and attaching that.")
            else:
                self.add_attachment(Attachment("file", name, path=self.copy_in(path)))
        except Exception as e:  # a broken file shouldn't stop the chat
            self.say_error(f"I couldn't open {name}: {e}")

    def copy_in(self, path):
        """Copy a file into the workspace so the helper is allowed to open it."""
        if is_inside(path, self.places.workspace):
            return path
        os.makedirs(self.places.attachments, exist_ok=True)
        base, ext = os.path.splitext(os.path.basename(path))
        dest, n = os.path.join(self.places.attachments, base + ext), 2
        while os.path.exists(dest):
            if filecmp.cmp(path, dest, shallow=False):
                return dest
            dest, n = os.path.join(self.places.attachments, f"{base} ({n}){ext}"), n + 1
        shutil.copy2(path, dest)
        return dest

    # -------------------------------------------------------------- input --

    def on_input_change(self, _=None):
        self.input.edit_modified(False)
        if self.input.get("1.0", "end-1c"):
            self.placeholder.place_forget()
        else:
            self.placeholder.place(x=self.px(9), y=self.px(6))

    def on_enter(self, event):
        if event.state & 0x1:  # Shift+Enter makes a new line
            return None
        self.send()
        return "break"

    def on_paste(self, _):
        try:
            if user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None  # ordinary text paste
            image = clipboard_image()
        except Exception:  # fall back to Tk's own paste
            return None
        if not image:
            return None
        self.add_attachment(Attachment("image", "Pasted image", data=image[0], media="image/png",
                                       note="Here's an image I pasted.", thumb=image[0]))
        return "break"

    def dictate(self):
        self.root.focus_force()
        self.input.focus_set()
        self.root.after(150, press_win_h)

    # -------------------------------------------------------------- agent --

    def ensure_agent(self):
        if self.proc and self.proc.poll() is None:
            return True
        if not self.claude:
            return False
        try:
            proc = subprocess.Popen(
                claude_command(self.claude, self.places, self.session_id),
                cwd=self.places.workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW, env=child_env())
        except OSError as e:
            self.say_error(f"I couldn't start Claude Code: {e}")
            return False
        proc.err_tail = collections.deque(maxlen=40)
        err_thread = threading.Thread(target=pump_stderr, args=(proc,), daemon=True)
        err_thread.start()
        threading.Thread(target=pump_stdout, args=(proc, err_thread, self.events),
                         daemon=True).start()
        self.proc = proc
        return True

    def send_or_stop(self):
        if self.busy:
            self.stop()
        else:
            self.send()

    def send(self):
        if self.busy:
            return
        text = self.input.get("1.0", "end-1c").strip()
        attachments = self.attachments
        if not text and not attachments:
            return
        if not self.ensure_agent():
            if not self.claude:
                self.say_error(NO_CLAUDE)
            return
        self.attachments = []
        self.render_chips()
        self.input.delete("1.0", "end")
        self.line_break()
        self.write("You\n", "who_you")
        if attachments:
            self.write("  ".join(f"[{a.label}]" for a in attachments) + "\n", "note")
        if text:
            self.write(text + "\n", "you")
        self.turn, self.busy = Turn(), True
        self.set_send_mode(stop=True)
        self.write(APP_NAME + "\n", "who_bot")
        self.set_status("Thinking…")
        message = {"type": "user", "message": {"role": "user",
                                               "content": build_content(text, attachments)}}
        line = json.dumps(message) + "\n"
        proc = self.proc

        def feed():  # big screenshots can fill the pipe, so write off the UI thread
            try:
                proc.stdin.write(line)
                proc.stdin.flush()
            except (OSError, ValueError):
                pass  # the exit event explains what happened

        threading.Thread(target=feed, daemon=True).start()

    def stop(self):
        proc, self.proc = self.proc, None
        kill_tree(proc)
        self.finish_turn()
        self.write("(stopped)\n", "note")

    def new_chat(self):
        proc, self.proc = self.proc, None
        kill_tree(proc)
        self.finish_turn()
        self.session_id = None
        self.attachments = []
        self.render_chips()
        self.edit(lambda: self.chat.delete("1.0", "end"))
        self.write("New chat. What are we working on?\n", "note")
        self.input.focus_set()
        self.ensure_agent()

    def finish_turn(self):
        if self.turn and self.turn.in_text:
            self.end_text()
        self.turn, self.busy = None, False
        self.set_send_mode(stop=False)
        self.set_status()

    def poll(self):
        try:
            while True:
                kind, *args = self.events.get_nowait()
                if kind == "hotkey":
                    self.on_hotkey()
                elif kind == "show":
                    self.show_panel()
                elif kind == "quit":
                    self.quit()
                    return
                elif kind == "agent":
                    self.on_agent(*args)
                elif kind == "exit":
                    self.on_exit(*args)
        except queue.Empty:
            pass
        except Exception:
            self.report_crash(*sys.exc_info())
        self.root.after(30, self.poll)

    def on_agent(self, proc, ev):
        if proc is not self.proc:
            return
        if ev.get("session_id"):
            self.session_id = ev["session_id"]
        if ev.get("parent_tool_use_id") or not self.turn:
            return
        kind = ev.get("type")
        if kind == "stream_event":
            e = ev.get("event") or {}
            if e.get("type") == "content_block_start" and (e.get("content_block") or {}).get("type") == "text":
                self.start_text()
            elif e.get("type") == "content_block_delta" and (e.get("delta") or {}).get("type") == "text_delta":
                self.stream_text(e["delta"].get("text", ""))
            elif e.get("type") == "content_block_stop" and self.turn.in_text:
                self.end_text()
        elif kind == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "tool_use" and block.get("id") not in self.turn.tools:
                    self.turn.tools.add(block.get("id"))
                    self.on_tool(block.get("name", ""), block.get("input") or {})
        elif kind == "result":
            self.end_turn(ev)

    def start_text(self):
        t = self.turn
        if t.wrote_text or t.tool_since_text:
            self.line_break()
            if not t.tool_since_text:
                self.write("\n")
        self.chat.mark_set("block", "end-1c")
        self.chat.mark_gravity("block", "left")
        t.buf, t.in_text, t.tool_since_text = "", True, False
        self.set_status("Writing…")

    def stream_text(self, text):
        if not self.turn.in_text:
            self.start_text()
        self.turn.buf += text
        self.write(text, "bot")

    def end_text(self):
        """Swap the raw streamed text for a tidied-up version with bold, bullets and links."""
        t = self.turn
        t.in_text = False
        follow = self.chat.yview()[1] >= 0.999
        self.edit(lambda: self.chat.delete("block", "end-1c"))
        raw = t.buf.strip()
        if raw:
            for text, tags in md_segments(raw):
                if "url" in tags:
                    rest = tuple(x for x in tags if x != "url")
                    self.link(text, lambda u=text: webbrowser.open(u), "bot", *rest)
                else:
                    self.write(text, "bot", *tags)
            t.wrote_text = True
            t.answer.append(plain_text(raw))
        if follow:
            self.chat.see("end")

    def on_tool(self, name, args):
        if self.turn.in_text:
            self.end_text()
        label = describe_tool(name, args)
        self.line_break()
        self.write("› " + label + "\n", "tool")
        self.turn.tool_since_text = True
        self.set_status(label + "…")
        if name in ("Write", "Edit") and args.get("file_path"):
            self.turn.files.append(args["file_path"])

    def end_turn(self, ev):
        t = self.turn
        if t.in_text:
            self.end_text()
        if ev.get("is_error") or ev.get("subtype", "success") != "success":
            detail = ev.get("result") or "; ".join(map(str, ev.get("errors") or [])) or ""
            self.say_error(friendly_error(str(detail)))
        for path in dict.fromkeys(t.files):
            if os.path.isfile(path):
                self.file_link(path)
        if t.answer:
            self.last_answer = "\n\n".join(t.answer)
        self.finish_turn()
        if not self.panel_visible():
            self.bubble.set_dot(True)

    def on_exit(self, proc):
        if proc is not self.proc:
            return
        self.proc = None
        if self.busy:
            self.finish_turn()
            self.say_error(friendly_error("\n".join(proc.err_tail)))

    def report_crash(self, exc, value, tb):
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
                f.write("".join(traceback.format_exception(exc, value, tb)) + "\n")
            self.say_error(f"Something went wrong inside {APP_NAME} ({value}). "
                           f"Details are in {os.path.basename(LOG_PATH)}.")
        except Exception:
            pass


def main():
    use_real_pixels()
    events = queue.Queue()
    if not claim_single_instance(events):
        return
    root = tk.Tk()
    root.withdraw()
    App(root, events)
    root.mainloop()


if __name__ == "__main__":
    main()
