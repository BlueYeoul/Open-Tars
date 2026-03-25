"""cginput wrapper — maps each input action to a named function."""

import re
import subprocess
import time
from pathlib import Path

_CGINPUT = str(Path(__file__).parent.parent / "cginput")

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

def get_focus() -> str:
    """Return the name of the app that currently has keyboard focus."""
    r = subprocess.run([_CGINPUT, "focus"], capture_output=True, text=True)
    if r.returncode == 0:
        return r.stdout.strip() or "unknown"
    return "unknown"


# ── Whitelist: apps the agent can activate and interact with ─
# display: name the user/agent sees
# activate: exact command — AppleScript name or hotkey
KNOWN_APPS = [
    {"display": "카카오톡",  "activate": 'tell application "카카오톡" to activate'},
    {"display": "Safari",    "activate": 'tell application "Safari" to activate'},
    {"display": "Chrome",    "activate": 'tell application "Google Chrome" to activate'},
    {"display": "Mail",      "activate": 'tell application "Mail" to activate'},
    {"display": "Gmail",     "activate": 'tell application "Gmail" to activate'},
    {"display": "Finder",    "activate": 'tell application "Finder" to activate'},
    {"display": "터미널",    "activate": 'tell application "Terminal" to activate'},
    {"display": "메모",      "activate": 'tell application "Notes" to activate'},
    {"display": "Spotlight", "activate": "hotkey cmd space"},
]


def get_known_apps() -> list[dict]:
    """Return the whitelist of apps the agent can use."""
    return KNOWN_APPS


def format_app_list() -> str:
    """One-line summary: just app names."""
    return "Apps: " + ", ".join(a["display"] for a in KNOWN_APPS)


def get_app_activate(name: str) -> str | None:
    """Look up activate command by display name (case-insensitive)."""
    lo = name.lower()
    for a in KNOWN_APPS:
        if a["display"].lower() == lo:
            return a["activate"]
    return None


def get_hover() -> dict:
    """Return accessibility info about the element under the mouse cursor.

    Returns dict with keys:
      - clickable: bool — whether the element is clickable
      - role: str — accessibility role (e.g. AXButton, AXLink, AXPopUpButton)
      - title: str — element title/label
      - description: str — accessibility description
      - raw: str — full raw output
    """
    r = subprocess.run([_CGINPUT, "hover"], capture_output=True, text=True)
    if r.returncode != 0:
        return {"clickable": False, "role": "", "title": "", "description": "", "raw": ""}

    raw = r.stdout.strip()
    lines = raw.splitlines()

    clickable = lines[0].strip().lower() == "clickable" if lines else False

    role = title = desc = ""
    for line in lines[1:]:
        line = line.strip()
        if line.startswith("→"):
            line = line[1:].strip()
        # parse "role: X | title: Y | desc: Z"
        for part in line.split("|"):
            part = part.strip()
            if part.startswith("role:"):
                role = part[5:].strip()
            elif part.startswith("title:"):
                title = part[6:].strip()
            elif part.startswith("desc:"):
                desc = part[5:].strip()

    return {"clickable": clickable, "role": role, "title": title, "description": desc, "raw": raw}


def move_to(x: int, y: int) -> tuple[bool, str]:
    """Move mouse cursor to absolute logical coordinates without clicking."""
    try:
        from Quartz.CoreGraphics import (
            CGEventCreateMouseEvent, CGEventPost,
            kCGEventMouseMoved, kCGHIDEventTap, kCGMouseButtonLeft,
        )
        evt = CGEventCreateMouseEvent(None, kCGEventMouseMoved, (x, y), kCGMouseButtonLeft)
        CGEventPost(kCGHIDEventTap, evt)
        time.sleep(0.2)
        return True, f"moved to ({x},{y})"
    except Exception as e:
        return False, f"move_to failed: {e}"


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
