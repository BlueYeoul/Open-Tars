"""Execute individual atomic actions."""

import time

from PIL import Image

import input_controller as inp
from grounding import find_element
from screen import ScreenInfo


def execute_action(action: dict, screen: ScreenInfo, img: Image.Image | None) -> tuple[bool, str]:
    t = action["type"]

    if t == "applescript":
        code = action["code"]
        print(f"      🍎 {code[:120]}")
        ok, out = inp.applescript(code)
        return ok, out if not ok else "applescript OK"

    if t in ("click", "doubleclick"):
        target = action["target"]
        print(f"      🖱️  Finding: {target}")
        result = find_element(target, img)
        if result[0] is None:
            return False, f"not found: {target} — {result[1]}"
        ix, iy = result
        lx, ly = screen.to_logical(ix, iy)
        print(f"      🖱️  {'Double-c' if t == 'doubleclick' else 'C'}lick → ({lx},{ly})")
        fn = inp.double_click if t == "doubleclick" else inp.click
        return fn(lx, ly)

    if t == "type":
        text = action["text"]
        print(f"      ⌨️  Type: {text}")
        return inp.type_text(text)

    if t == "hotkey":
        keys = action["keys"]
        print(f"      ⌨️  Hotkey: {keys}")
        return inp.hotkey(keys)

    if t == "scroll":
        d = action["direction"]
        print(f"      📜 Scroll {d}")
        return inp.scroll(d)

    if t == "wait":
        secs = action.get("seconds", 2)
        print(f"      ⏳ Wait {secs}s")
        time.sleep(secs)
        return True, f"waited {secs}s"

    if t == "move":
        dx, dy = action.get("dx", 0), action.get("dy", 0)
        print(f"      🖱️  Move ({dx:+d},{dy:+d})")
        return inp.move_relative(dx, dy)

    return False, f"unknown action: {t}"
