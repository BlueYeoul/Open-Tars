"""Screen info, screenshot capture, and image utilities."""

import base64
import io
import json
import re
import subprocess

from PIL import Image


class ScreenInfo:
    def __init__(self, display: int):
        self.display = display
        self.img_w = 0
        self.img_h = 0
        self.logical_w = 0
        self.logical_h = 0
        self.offset_x = 0
        self.offset_y = 0
        self._detect_display()

    def _detect_display(self):
        try:
            r = subprocess.run(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                capture_output=True, text=True,
            )
            data = json.loads(r.stdout)
            idx = 0
            for gpu in data.get("SPDisplaysDataType", []):
                for d in gpu.get("spdisplays_ndrvs", []):
                    idx += 1
                    res = d.get("_spdisplays_resolution", "")
                    m = re.match(r"(\d+)\s*x\s*(\d+)", res)
                    if m:
                        w, h = int(m.group(1)), int(m.group(2))
                        if idx == self.display:
                            self.logical_w = w
                            self.logical_h = h
                        elif idx < self.display:
                            self.offset_x += w
        except Exception:
            pass
        print(f"📺 Display {self.display}: {self.logical_w}x{self.logical_h} offset=({self.offset_x},{self.offset_y})")

    def to_logical(self, img_x: int, img_y: int) -> tuple[int, int]:
        if self.img_w == 0 or self.logical_w == 0:
            return img_x, img_y
        sx = self.logical_w / self.img_w
        sy = self.logical_h / self.img_h
        return (self.offset_x + int(img_x * sx), self.offset_y + int(img_y * sy))


def pil_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode()


_screenshot_counter = 0


def take_screenshot(screen: ScreenInfo) -> tuple[str, Image.Image]:
    global _screenshot_counter
    _screenshot_counter += 1
    path = f"/tmp/otars_{_screenshot_counter:03d}.png"
    subprocess.run(["screencapture", "-x", f"-D{screen.display}", path], capture_output=True)
    img = Image.open(path)
    max_w = 1280
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
    img = img.convert("RGB")
    screen.img_w = img.width
    screen.img_h = img.height
    preview = f"/tmp/otars_{_screenshot_counter:03d}.jpg"
    img.save(preview, "JPEG", quality=70)
    kb = len(open(preview, "rb").read()) // 1024
    print(f"    📸 {img.width}x{img.height} {kb}KB → {preview}")
    return f"data:image/jpeg;base64,{pil_to_b64(img)}", img
