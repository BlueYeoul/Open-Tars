"""Action history — mouse trail visualization + text-based long-term memory.

Tracks every action with mouse coordinates + text metadata only.
NO images stored — trail is drawn on the current frame at render time.

Generates:
  1. Trail image: current screenshot with mouse path as colored lines + numbered dots
  2. Text summary: compact text log of all past actions for LLM context
"""

from __future__ import annotations

import io
import base64
from dataclasses import dataclass

from PIL import Image, ImageDraw


# ── Trail colors: cycle through these for successive actions ──
_TRAIL_COLORS = [
    (0, 200, 255),    # cyan
    (255, 100, 0),    # orange
    (0, 255, 100),    # green
    (255, 50, 150),   # pink
    (200, 200, 0),    # yellow
    (150, 100, 255),  # purple
]

# How many recent entries to visualize in the trail image
_MAX_TRAIL_ENTRIES = 8

# Max text entries kept for LLM context
_MAX_TEXT_ENTRIES = 12


@dataclass
class ActionEntry:
    """One recorded action — coordinates + text only, no images."""
    step: int
    action_label: str        # e.g. "click search bar", "type 공주대학교"
    mouse_x: int | None      # image-space coords (on 1280-wide capture)
    mouse_y: int | None
    state_text: str = ""     # tactician's <state> summary


class ActionHistory:
    """Accumulates action entries and produces visual/text summaries."""

    def __init__(self):
        self._entries: list[ActionEntry] = []
        self._step = 0

    def record(self, action_label: str,
               mouse_x: int | None = None, mouse_y: int | None = None,
               state_text: str = ""):
        """Record one action. Coordinates only — no image stored."""
        self._step += 1
        self._entries.append(ActionEntry(
            step=self._step,
            action_label=action_label,
            mouse_x=mouse_x,
            mouse_y=mouse_y,
            state_text=state_text,
        ))

    def clear(self):
        self._entries.clear()
        self._step = 0

    # ── Text summary ──────────────────────────────────────────────

    def text_summary(self, last_n: int = _MAX_TEXT_ENTRIES) -> str:
        """Compact text log of recent actions for LLM context."""
        if not self._entries:
            return ""
        recent = self._entries[-last_n:]
        lines = ["Action History:"]
        for e in recent:
            pos = f" @({e.mouse_x},{e.mouse_y})" if e.mouse_x is not None else ""
            st = f" [{e.state_text[:60]}]" if e.state_text else ""
            lines.append(f"  #{e.step}: {e.action_label}{pos}{st}")
        return "\n".join(lines)

    # ── Trail image ───────────────────────────────────────────────

    def trail_image_b64(self, current_img: Image.Image) -> str | None:
        """Draw mouse trail on a degraded copy of the CURRENT screenshot.

        The current_img is used once to render the trail, then discarded.
        Returns base64 data URI, or None if no mouse positions recorded.
        """
        recent = [e for e in self._entries[-_MAX_TRAIL_ENTRIES:]
                  if e.mouse_x is not None and e.mouse_y is not None]
        if not recent:
            return None

        # Shrink current frame for trail overlay (saves tokens)
        thumb_w, thumb_h = 320, int(320 * current_img.height / current_img.width)
        bg = current_img.resize((thumb_w, thumb_h), Image.LANCZOS).convert("RGB")
        draw = ImageDraw.Draw(bg)

        # Scale factor: full image → thumbnail
        sx = thumb_w / current_img.width
        sy = thumb_h / current_img.height

        # Collect scaled points
        points = []
        for e in recent:
            tx = int(e.mouse_x * sx)
            ty = int(e.mouse_y * sy)
            points.append((tx, ty, e.step, e.action_label))

        # Draw trail lines connecting successive mouse positions
        for i in range(1, len(points)):
            color = _TRAIL_COLORS[(i - 1) % len(_TRAIL_COLORS)]
            x0, y0 = points[i - 1][0], points[i - 1][1]
            x1, y1 = points[i][0], points[i][1]
            draw.line([(x0, y0), (x1, y1)], fill=color, width=2)

        # Draw numbered circles at each position
        for i, (tx, ty, step, _label) in enumerate(points):
            color = _TRAIL_COLORS[i % len(_TRAIL_COLORS)]
            r = 6
            draw.ellipse([tx - r, ty - r, tx + r, ty + r],
                         fill=color, outline=(255, 255, 255), width=1)
            draw.text((tx + r + 2, ty - 6), str(step),
                      fill=(255, 255, 255))

        # Encode to base64 — use once, bg goes out of scope after return
        buf = io.BytesIO()
        bg.save(buf, "JPEG", quality=55)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"

    @property
    def count(self) -> int:
        return len(self._entries)
