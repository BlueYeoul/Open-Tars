"""cginput wrapper — maps each input action to a named function."""

import re
import subprocess
import time
from pathlib import Path

_CGINPUT = str(Path(__file__).parent / "cginput")

_MOD_MAP = {
    "command": "cmd", "cmd": "cmd",
    "shift": "shift",
    "option": "opt", "alt": "opt",
    "control": "ctrl", "ctrl": "ctrl",
}

# ── Blocked AppleScript patterns ──
_AS_BLOCKED = [
    (lambda c: "messages" in c and any(k in c for k in ("http", "www", "arxiv")),
     "BLOCKED: Tried to use Messages app for a web URL. Use Safari."),
    (lambda c: "open location" in c or "set url" in c,
     "BLOCKED: Do NOT use AppleScript for URLs. Use hotkey+type instead."),
    (lambda c: "do javascript" in c,
     "BLOCKED: do JavaScript is forbidden"),
]


def click(x: int, y: int) -> tuple[bool, str]:
    r = subprocess.run([_CGINPUT, "click", str(x), str(y)], capture_output=True)
    time.sleep(0.5)
    return r.returncode == 0, f"clicked ({x},{y})" if r.returncode == 0 else r.stderr.decode()


def double_click(x: int, y: int) -> tuple[bool, str]:
    r = subprocess.run([_CGINPUT, "double_click", str(x), str(y)], capture_output=True)
    time.sleep(0.5)
    return r.returncode == 0, f"double_clicked ({x},{y})" if r.returncode == 0 else r.stderr.decode()


def type_text(text: str) -> tuple[bool, str]:
    r = subprocess.run([_CGINPUT, "type", text], capture_output=True)
    time.sleep(0.5)
    return r.returncode == 0, f"typed '{text}'" if r.returncode == 0 else r.stderr.decode()


def hotkey(keys: str) -> tuple[bool, str]:
    parts = [p.strip().lower() for p in re.split(r"[\s+]+", keys) if p.strip()]
    args = [_MOD_MAP.get(p, p) for p in parts]
    r = subprocess.run([_CGINPUT, "hotkey"] + args, capture_output=True)
    time.sleep(0.5)
    return r.returncode == 0, f"hotkey '{keys}'" if r.returncode == 0 else r.stderr.decode()


def scroll(direction: str) -> tuple[bool, str]:
    r = subprocess.run([_CGINPUT, "scroll", direction], capture_output=True)
    time.sleep(1)
    return r.returncode == 0, f"scrolled {direction}" if r.returncode == 0 else r.stderr.decode()


def move_relative(dx: int, dy: int) -> tuple[bool, str]:
    """Move mouse cursor by (dx, dy) relative to current position (logical global coords)."""
    try:
        from Quartz.CoreGraphics import (
            CGEventCreate, CGEventGetLocation,
            CGEventCreateMouseEvent, CGEventPost,
            kCGEventMouseMoved, kCGHIDEventTap, kCGMouseButtonLeft,
        )
        ref = CGEventCreate(None)
        pos = CGEventGetLocation(ref)
        nx = int(pos.x) + dx
        ny = int(pos.y) + dy
        evt = CGEventCreateMouseEvent(None, kCGEventMouseMoved, (nx, ny), kCGMouseButtonLeft)
        CGEventPost(kCGHIDEventTap, evt)
        time.sleep(0.2)
        return True, f"moved ({dx:+d},{dy:+d}) → ({nx},{ny})"
    except Exception as e:
        return False, f"move failed: {e}"


def applescript(code: str) -> tuple[bool, str]:
    c = code.strip()
    for check, msg in _AS_BLOCKED:
        if check(c.lower()):
            return False, msg
    if re.match(r"^open\s+(\w+)$", c, re.IGNORECASE):
        app = re.match(r"^open\s+(\w+)$", c, re.IGNORECASE).group(1)
        c = f'tell application "{app.title()}" to activate'
    r = subprocess.run(["osascript", "-e", c], capture_output=True, text=True)
    time.sleep(1.5)
    return (r.returncode == 0), (r.stdout.strip() or r.stderr.strip() or "applescript OK")
