"""Execute individual atomic actions."""

import time

from PIL import Image

import action.input_controller as inp
from vision.grounding import find_element, verify_click, grid_correct
from vision.screen import ScreenInfo


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
        result = find_element(target, img, screen)
        if result[0] is None:
            return False, f"not found: {target} — {result[1]}"
        ix, iy, hover_info = result

        # Verify: draw X on crop, ask LLM if it's on the right element
        ok, reason = verify_click(target, img, ix, iy, hover_info)
        if not ok:
            # Grid correction fallback: crop around failed point, ask LLM to pick grid cell
            print(f"      🔲 Attempting grid correction for: {target}")
            gx, gy, grid_reason = grid_correct(target, img, ix, iy)
            if gx is not None:
                # Re-verify the corrected position
                ok2, reason2 = verify_click(target, img, gx, gy, "")
                if ok2:
                    ix, iy = gx, gy
                    print(f"      ✅ Grid correction succeeded: ({ix},{iy})")
                else:
                    return False, f"grid correction failed verify: {reason2}"
            else:
                return False, f"not found: {target} — {reason} (grid: {grid_reason})"

        lx, ly = screen.to_logical(ix, iy)
        print(f"      🖱️  {'Double-c' if t == 'doubleclick' else 'C'}lick → ({lx},{ly})")
        # Store grounded coords for action history (image-space)
        action["_grounded_x"] = ix
        action["_grounded_y"] = iy
        fn = inp.double_click if t == "doubleclick" else inp.click
        return fn(lx, ly)

    if t == "type":
        text = action["text"]
        print(f"      ⌨️  Type: {text}")
        return inp.type_text(text)

    if t == "hotkey":
        keys = action["keys"]
        # Focus guard for window-control hotkeys
        _window_hotkeys = {"cmd w", "cmd q", "cmd m", "cmd h", "cmd `"}
        norm = " ".join(sorted(k.strip().lower() for k in keys.replace("+", " ").split()))
        if norm in _window_hotkeys:
            focused = inp.get_focus()
            print(f"      🔍 Focus check before {keys}: '{focused}'")
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
