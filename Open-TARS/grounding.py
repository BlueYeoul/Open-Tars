"""Two-pass UI element grounding via vision LLM."""

import re

from PIL import Image

from llm_client import call_llm, load_prompt
from screen import pil_to_b64


def find_element(target: str, img: Image.Image) -> tuple[int | None, int | None | str]:
    w, h = img.size

    def denorm(val, max_val):
        return int((max(0, min(int(val), 1000)) / 1000.0) * max_val)

    b64 = f"data:image/jpeg;base64,{pil_to_b64(img)}"
    ans = call_llm(
        "You are a precise UI element locator.",
        load_prompt("grounding", width=w, height=h, target=target),
        image=b64,
    )

    # Not-found check FIRST — if the model said not_found, trust it unconditionally
    if "<not_found" in ans:
        # Use a greedy match that stops at /> to handle quotes inside the reason value
        reason_m = re.search(r'<not_found\s+reason=["\'](.+?)["\']?\s*/?>', ans, re.DOTALL)
        if not reason_m:
            reason_m = re.search(r'<not_found[^>]*reason=(.+?)/?>', ans, re.DOTALL)
        reason = reason_m.group(1).strip('"\'') if reason_m else "not visible on screen"
        print(f"      🔍 Not found: {target}")
        print(f"         💬 {reason}")
        return None, reason

    m = re.search(r'<box\s+x1=["\']?(\d+)["\']?\s+y1=["\']?(\d+)["\']?\s+x2=["\']?(\d+)["\']?\s+y2=["\']?(\d+)', ans)
    if not m:
        m = re.search(r'<box>\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*</box>', ans)
    if not m:
        print(f"      ❌ Grounding failed (no box): {target}")
        return None, "grounding returned no coordinates"

    rx1, ry1, rx2, ry2 = [int(x) for x in m.groups()]
    x1, y1, x2, y2 = denorm(rx1, w), denorm(ry1, h), denorm(rx2, w), denorm(ry2, h)
    if x1 > x2: x1, x2 = x2, x1
    if y1 > y2: y1, y2 = y2, y1
    print(f"      🎯 Coarse: [{rx1},{ry1},{rx2},{ry2}] → px [{x1},{y1},{x2},{y2}]")

    # Refine on crop
    PAD = 60
    left, top = max(0, x1 - PAD), max(0, y1 - PAD)
    right, bottom = min(w, x2 + PAD), min(h, y2 + PAD)
    crop = img.crop((left, top, right, bottom))
    cw, ch = crop.size

    b64c = f"data:image/jpeg;base64,{pil_to_b64(crop)}"
    ans2 = call_llm(
        "You are a precise UI element locator.",
        load_prompt("refine", width=cw, height=ch, target=target),
        image=b64c,
    )

    m2 = re.search(r'<box\s+x1=["\']?(\d+)["\']?\s+y1=["\']?(\d+)["\']?\s+x2=["\']?(\d+)["\']?\s+y2=["\']?(\d+)', ans2)
    if not m2:
        m2 = re.search(r'<box>\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*</box>', ans2)
    if m2:
        rrx1, rry1, rrx2, rry2 = [int(x) for x in m2.groups()]
        fx = left + (denorm(rrx1, cw) + denorm(rrx2, cw)) // 2
        fy = top + (denorm(rry1, ch) + denorm(rry2, ch)) // 2
        print(f"      🎯 Refined: ({fx},{fy})")
        return fx, fy
    else:
        fx, fy = (x1 + x2) // 2, (y1 + y2) // 2
        print(f"      🎯 Center: ({fx},{fy})")
        return fx, fy
