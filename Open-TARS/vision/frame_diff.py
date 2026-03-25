"""Frame differencing — detects visual changes between two screenshots.

Used by Observer/Verify roles to understand what changed after an action:
  - Button visually pressed / highlighted
  - New popup or dialog appeared
  - Search field became focused (cursor blinking)
  - Content scrolled
  - Mouse cursor moved
"""

from __future__ import annotations

import io
import base64

from PIL import Image, ImageDraw, ImageFilter, ImageChops


# Minimum change area (fraction of image) to consider meaningful
_MIN_CHANGE_RATIO = 0.002  # 0.2% of image

# Threshold for pixel difference (0-255)
_DIFF_THRESHOLD = 30

# Color for highlighting changed regions
_HIGHLIGHT_COLOR = (0, 255, 0, 100)  # semi-transparent green
_BORDER_COLOR = (0, 255, 0)          # solid green border


def compute_diff(prev: Image.Image, curr: Image.Image
                 ) -> tuple[Image.Image | None, str]:
    """Compare two screenshots and produce a diff visualization + text description.

    Returns:
        (diff_image, description)
        diff_image: current frame with green rectangles around changed regions,
                    or None if no meaningful change.
        description: text summary like "3 regions changed: top-right (popup), center-left (button)"
    """
    if prev.size != curr.size:
        # Resize prev to match curr
        prev = prev.resize(curr.size, Image.LANCZOS)

    w, h = curr.size

    # Convert to grayscale for comparison
    g_prev = prev.convert("L")
    g_curr = curr.convert("L")

    # Absolute pixel difference
    diff = ImageChops.difference(g_prev, g_curr)

    # Threshold: pixels that changed significantly
    diff_binary = diff.point(lambda p: 255 if p > _DIFF_THRESHOLD else 0)

    # Blur slightly to merge nearby changed pixels into regions
    diff_blurred = diff_binary.filter(ImageFilter.BoxBlur(8))
    diff_mask = diff_blurred.point(lambda p: 255 if p > 50 else 0)

    # Find bounding boxes of changed regions
    regions = _find_regions(diff_mask)

    # Filter out tiny regions
    total_pixels = w * h
    regions = [r for r in regions
               if (r[2] - r[0]) * (r[3] - r[1]) > total_pixels * _MIN_CHANGE_RATIO]

    if not regions:
        return None, "no_change"

    # Merge overlapping regions
    regions = _merge_regions(regions, margin=20)

    # Create visualization: current frame with green rectangles
    vis = curr.copy().convert("RGB")
    draw = ImageDraw.Draw(vis)
    for x1, y1, x2, y2 in regions:
        draw.rectangle([x1, y1, x2, y2], outline=_BORDER_COLOR, width=2)

    # Generate text description
    desc_parts = []
    for x1, y1, x2, y2 in regions:
        loc = _region_location(x1, y1, x2, y2, w, h)
        area_pct = ((x2 - x1) * (y2 - y1)) / total_pixels * 100
        desc_parts.append(f"{loc} ({area_pct:.1f}%)")

    total_change = sum((r[2] - r[0]) * (r[3] - r[1]) for r in regions) / total_pixels * 100
    description = (f"{len(regions)} changed region{'s' if len(regions) > 1 else ''} "
                   f"({total_change:.1f}% total): {', '.join(desc_parts)}")

    return vis, description


def diff_image_b64(prev: Image.Image, curr: Image.Image) -> tuple[str | None, str]:
    """Convenience: returns (base64_data_uri | None, description)."""
    vis, desc = compute_diff(prev, curr)
    if vis is None:
        return None, desc
    buf = io.BytesIO()
    # Degrade slightly to save tokens
    vis_small = vis.copy()
    max_w = 800
    if vis_small.width > max_w:
        ratio = max_w / vis_small.width
        vis_small = vis_small.resize((max_w, int(vis_small.height * ratio)), Image.LANCZOS)
    vis_small.save(buf, "JPEG", quality=60)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/jpeg;base64,{b64}", desc


# ── Internal helpers ─────────────────────────────────────────────

def _find_regions(mask: Image.Image) -> list[tuple[int, int, int, int]]:
    """Simple connected-component bounding boxes via scanline flood fill on binary mask."""
    pixels = mask.load()
    w, h = mask.size
    visited = set()
    regions = []

    for y in range(0, h, 4):  # sample every 4 pixels for speed
        for x in range(0, w, 4):
            if (x, y) in visited or pixels[x, y] == 0:
                continue
            # BFS to find extent of this region
            min_x, min_y, max_x, max_y = x, y, x, y
            stack = [(x, y)]
            while stack:
                cx, cy = stack.pop()
                if (cx, cy) in visited:
                    continue
                if cx < 0 or cx >= w or cy < 0 or cy >= h:
                    continue
                if pixels[cx, cy] == 0:
                    continue
                visited.add((cx, cy))
                min_x = min(min_x, cx)
                min_y = min(min_y, cy)
                max_x = max(max_x, cx)
                max_y = max(max_y, cy)
                # 4-connected neighbors (step 4 for speed)
                for nx, ny in [(cx + 4, cy), (cx - 4, cy), (cx, cy + 4), (cx, cy - 4)]:
                    if (nx, ny) not in visited:
                        stack.append((nx, ny))
            regions.append((min_x, min_y, max_x, max_y))

    return regions


def _merge_regions(regions: list[tuple[int, int, int, int]],
                   margin: int = 20) -> list[tuple[int, int, int, int]]:
    """Merge overlapping or nearby regions."""
    if not regions:
        return []

    # Expand each region by margin, then merge overlaps
    expanded = [(x1 - margin, y1 - margin, x2 + margin, y2 + margin)
                for x1, y1, x2, y2 in regions]

    merged = [expanded[0]]
    for r in expanded[1:]:
        found = False
        for i, m in enumerate(merged):
            if _overlaps(r, m):
                merged[i] = (min(r[0], m[0]), min(r[1], m[1]),
                             max(r[2], m[2]), max(r[3], m[3]))
                found = True
                break
        if not found:
            merged.append(r)

    # Shrink back by margin (but clamp to 0)
    result = [(max(0, x1 + margin), max(0, y1 + margin),
               x2 - margin, y2 - margin)
              for x1, y1, x2, y2 in merged]
    return result


def _overlaps(a: tuple, b: tuple) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _region_location(x1: int, y1: int, x2: int, y2: int,
                     w: int, h: int) -> str:
    """Describe region position in human terms."""
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2

    v = "top" if cy < h * 0.33 else ("bottom" if cy > h * 0.67 else "center")
    hz = "left" if cx < w * 0.33 else ("right" if cx > w * 0.67 else "center")

    if v == "center" and hz == "center":
        return "center"
    if v == "center":
        return hz
    if hz == "center":
        return v
    return f"{v}-{hz}"
