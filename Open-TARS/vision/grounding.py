"""UI element grounding (Coarse → Refine), click verification (X-mark), and grid correction."""

import re
import string

from PIL import Image, ImageDraw, ImageFont

from llm.client import call_llm, load_prompt
from vision.screen import ScreenInfo, pil_to_b64

# If coarse box is smaller than this fraction of image, skip refine
TIGHT_RATIO = 0.07

# X-mark drawing parameters
X_ARM   = 18   # pixels from center
X_WIDTH = 4    # line thickness
X_COLOR = (255, 0, 0)  # bright red

# Grid correction parameters
GRID_ROWS   = 4
GRID_COLS   = 4
GRID_COLOR  = (255, 255, 0)     # yellow grid lines
GRID_LABEL_COLOR = (255, 255, 0)  # yellow text

# Radial search: center → 8 neighbors → outer ring
# Each ring = (dx_multiplier, dy_multiplier) offsets from center
_RING_0 = [(0, 0)]                                                         # center
_RING_1 = [(0, -1), (1, -1), (1, 0), (1, 1),                              # N NE E SE
           (0, 1), (-1, 1), (-1, 0), (-1, -1)]                            # S SW W NW
_SEARCH_RINGS = [_RING_0, _RING_1]
_RING_PAD  = 100   # crop half-size per ring patch
_RING_STEP = 140   # distance between ring centers (< 2*PAD → overlap for coverage)


def _parse_box(text: str) -> tuple[int, int, int, int] | None:
    """Extract (x1, y1, x2, y2) from <box .../> in LLM response."""
    m = re.search(
        r'<box\s+x1=["\']?(\d+)["\']?\s+y1=["\']?(\d+)["\']?'
        r'\s+x2=["\']?(\d+)["\']?\s+y2=["\']?(\d+)', text)
    if not m:
        m = re.search(r'<box>\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*</box>', text)
    if m:
        return tuple(int(x) for x in m.groups())
    return None


def _denorm(val: int, max_val: int) -> int:
    return int((max(0, min(val, 1000)) / 1000.0) * max_val)


def _draw_x(img: Image.Image, cx: int, cy: int) -> Image.Image:
    """Draw a bright red X mark at (cx, cy) on a copy of the image."""
    marked = img.copy()
    draw = ImageDraw.Draw(marked)
    draw.line([(cx - X_ARM, cy - X_ARM), (cx + X_ARM, cy + X_ARM)],
              fill=X_COLOR, width=X_WIDTH)
    draw.line([(cx - X_ARM, cy + X_ARM), (cx + X_ARM, cy - X_ARM)],
              fill=X_COLOR, width=X_WIDTH)
    return marked


def _crop_around(img: Image.Image, cx: int, cy: int, pad: int) -> Image.Image:
    """Crop a region around (cx, cy) with given padding."""
    w, h = img.size
    left   = max(0, cx - pad)
    top    = max(0, cy - pad)
    right  = min(w, cx + pad)
    bottom = min(h, cy + pad)
    return img.crop((left, top, right, bottom))


def verify_click(target: str, img: Image.Image, cx: int, cy: int,
                 hover_info: str = "") -> tuple[bool, str]:
    """Draw X at (cx,cy) on the full image, ask LLM to confirm.

    Returns (ok, reason).  Called by executor AFTER grounding finds coords.
    """
    print(f"      🔎 Verify: ({cx},{cy}) on {img.width}×{img.height}px")

    marked = _draw_x(img, cx, cy)
    b64 = f"data:image/jpeg;base64,{pil_to_b64(marked)}"

    ans = call_llm(
        "You are a precise UI element verifier.",
        load_prompt("verify", target=target, hover_info=hover_info),
        image=b64,
    )

    verdict = ans.strip().upper()
    if verdict.startswith("YES"):
        print(f"      ✅ Verify: confirmed")
        return True, ""
    else:
        reason = ans.strip()
        print(f"      ❌ Verify: {reason}")
        return False, reason


def find_element(target: str, img: Image.Image,
                 screen: ScreenInfo | None = None
                 ) -> tuple[int | None, int | None | str, str]:
    """Locate a UI element: Coarse → Refine.

    Returns ``(x, y, hover_info)`` on success, or
    ``(None, reason, "")`` on failure.

    Verification (X-mark) is NOT done here — call ``verify_click`` separately.
    """
    w, h = img.size

    # ── Pass 1: Coarse ────────────────────────────────────────────
    b64 = f"data:image/jpeg;base64,{pil_to_b64(img)}"
    ans = call_llm(
        "You are a precise UI element locator.",
        load_prompt("grounding", width=w, height=h, target=target),
        image=b64,
    )

    # Not-found → bail immediately
    if "<not_found" in ans:
        reason_m = re.search(r'<not_found\s+reason=["\'](.+?)["\']?\s*/?>', ans, re.DOTALL)
        if not reason_m:
            reason_m = re.search(r'<not_found[^>]*reason=(.+?)/?>', ans, re.DOTALL)
        reason = reason_m.group(1).strip('"\'') if reason_m else "not visible on screen"
        print(f"      🔍 Not found: {target}")
        print(f"         💬 {reason}")
        return None, reason, ""

    box = _parse_box(ans)
    if not box:
        print(f"      ❌ Grounding failed (no box): {target}")
        return None, "grounding returned no coordinates", ""

    rx1, ry1, rx2, ry2 = box
    x1 = _denorm(rx1, w); y1 = _denorm(ry1, h)
    x2 = _denorm(rx2, w); y2 = _denorm(ry2, h)
    if x1 > x2: x1, x2 = x2, x1
    if y1 > y2: y1, y2 = y2, y1
    print(f"      🎯 Coarse: [{rx1},{ry1},{rx2},{ry2}] → px [{x1},{y1},{x2},{y2}]")

    box_w, box_h = x2 - x1, y2 - y1

    # ── Pass 2: Refine (skip if coarse is already tight) ──────────
    if box_w < w * TIGHT_RATIO and box_h < h * TIGHT_RATIO:
        fx, fy = (x1 + x2) // 2, (y1 + y2) // 2
        print(f"      🎯 Coarse tight — skip refine: ({fx},{fy})")
    else:
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

        m2 = _parse_box(ans2)
        if m2:
            rrx1, rry1, rrx2, rry2 = m2
            fx = left + (_denorm(rrx1, cw) + _denorm(rrx2, cw)) // 2
            fy = top  + (_denorm(rry1, ch) + _denorm(rry2, ch)) // 2
            print(f"      🎯 Refined: ({fx},{fy})")
        else:
            fx, fy = (x1 + x2) // 2, (y1 + y2) // 2
            print(f"      🎯 Refine miss — coarse center: ({fx},{fy})")

    # ── Hover check (if screen available) ─────────────────────────
    hover_info = ""
    if screen:
        try:
            from action.input_controller import move_to, get_hover
            lx, ly = screen.to_logical(fx, fy)
            move_to(lx, ly)
            hover = get_hover()
            if hover["clickable"]:
                parts = ["Cursor at target → CLICKABLE"]
                if hover["role"]:  parts.append(f"role={hover['role']}")
                if hover["title"]: parts.append(f'title="{hover["title"]}"')
                hover_info = "Hover: " + " | ".join(parts)
            else:
                hover_info = "Hover: Cursor at target → not clickable"
            print(f"      📡 {hover_info}")
        except Exception:
            pass  # hover is best-effort

    return fx, fy, hover_info


# ── Grid correction ──────────────────────────────────────────────

def _grid_label(row: int, col: int) -> str:
    """Generate grid label like A1, B3, C2..."""
    return f"{string.ascii_uppercase[row]}{col + 1}"


def _draw_grid(img: Image.Image) -> Image.Image:
    """Overlay a labeled grid on an image. Returns annotated copy."""
    grid = img.copy().convert("RGB")
    draw = ImageDraw.Draw(grid)
    w, h = grid.size
    cell_w = w / GRID_COLS
    cell_h = h / GRID_ROWS

    # Draw grid lines
    for i in range(1, GRID_COLS):
        x = int(i * cell_w)
        draw.line([(x, 0), (x, h)], fill=GRID_COLOR, width=1)
    for i in range(1, GRID_ROWS):
        y = int(i * cell_h)
        draw.line([(0, y), (w, y)], fill=GRID_COLOR, width=1)

    # Draw border
    draw.rectangle([0, 0, w - 1, h - 1], outline=GRID_COLOR, width=2)

    # Label each cell
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            label = _grid_label(r, c)
            cx = int((c + 0.5) * cell_w)
            cy = int((r + 0.5) * cell_h)
            # Draw label with background for visibility
            draw.text((cx - 8, cy - 6), label, fill=GRID_LABEL_COLOR)

    return grid


def _probe_grid(target: str, img: Image.Image,
                center_x: int, center_y: int, pad: int,
                direction: str = "center"
                ) -> tuple[int | None, int | None, str]:
    """Probe one grid patch: crop → grid overlay → LLM picks cell.

    Returns (x, y, reason) in full-image coordinates, or (None, None, reason).
    """
    w, h = img.size
    left   = max(0, center_x - pad)
    top    = max(0, center_y - pad)
    right  = min(w, center_x + pad)
    bottom = min(h, center_y + pad)

    # Skip if crop is too small (near edge)
    if right - left < 40 or bottom - top < 40:
        return None, None, "patch too small (near edge)"

    crop = img.crop((left, top, right, bottom))
    grid_img = _draw_grid(crop)
    b64 = f"data:image/jpeg;base64,{pil_to_b64(grid_img)}"

    cw, ch = crop.size
    cell_w = cw / GRID_COLS
    cell_h = ch / GRID_ROWS

    cell_map = [_grid_label(r, c) for r in range(GRID_ROWS) for c in range(GRID_COLS)]

    prompt = (
        f"A click on \"{target}\" missed. This image shows a {direction} patch "
        f"divided into a {GRID_ROWS}×{GRID_COLS} grid.\n\n"
        f"Grid cells: {', '.join(cell_map)}\n"
        f"Rows A-{string.ascii_uppercase[GRID_ROWS-1]} (top→bottom), "
        f"Columns 1-{GRID_COLS} (left→right).\n\n"
        f"Which grid cell contains \"{target}\"?\n\n"
        f"Answer ONLY the cell ID (e.g. B3) or NOT_FOUND if not visible."
    )

    ans = call_llm(
        "You are a precise UI element locator. Pick the grid cell containing the target.",
        prompt, image=b64,
    )
    ans = ans.strip().upper()

    if "NOT_FOUND" in ans:
        return None, None, "not in this patch"

    m = re.match(r"([A-Z])(\d)", ans)
    if not m:
        return None, None, f"invalid response: {ans}"

    row = ord(m.group(1)) - ord('A')
    col = int(m.group(2)) - 1
    if row < 0 or row >= GRID_ROWS or col < 0 or col >= GRID_COLS:
        return None, None, f"out of range: {ans}"

    cx = left + int((col + 0.5) * cell_w)
    cy = top + int((row + 0.5) * cell_h)
    return cx, cy, f"grid {direction} → {m.group(0)}"


# Direction names for logging
_DIR_NAMES = {
    (0, 0): "center",
    (0, -1): "N", (1, -1): "NE", (1, 0): "E", (1, 1): "SE",
    (0, 1): "S", (-1, 1): "SW", (-1, 0): "W", (-1, -1): "NW",
}


def grid_correct(target: str, img: Image.Image, failed_x: int, failed_y: int
                 ) -> tuple[int | None, int | None, str]:
    """Radial grid correction: search center → 8 neighbors, expanding outward.

    Pattern (like compass rose):
        Ring 0:  center (X)
        Ring 1:  N, NE, E, SE, S, SW, W, NW

    Each patch is a _RING_PAD×2 crop with 4×4 grid overlay.
    Stops at the first patch where LLM finds the target.

    Returns (corrected_x, corrected_y, reason) in full-image coordinates,
    or (None, None, reason) if all patches exhausted.
    """
    print(f"      🔲 Radial grid search from ({failed_x},{failed_y})...")

    for ring_idx, ring in enumerate(_SEARCH_RINGS):
        for dx, dy in ring:
            dir_name = _DIR_NAMES.get((dx, dy), f"r{ring_idx}")
            cx = failed_x + dx * _RING_STEP
            cy = failed_y + dy * _RING_STEP

            print(f"      🔲 Ring {ring_idx} [{dir_name}] → probe ({cx},{cy})")
            gx, gy, reason = _probe_grid(target, img, cx, cy, _RING_PAD, dir_name)

            if gx is not None:
                print(f"      🔲 ✅ Found at ({gx},{gy}) via {reason}")
                return gx, gy, reason

            print(f"      🔲 ─ {dir_name}: {reason}")

    return None, None, "exhausted all radial patches"
