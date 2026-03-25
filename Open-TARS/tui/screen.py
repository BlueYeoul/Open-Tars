import json
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path
from agent.bus import Bus

_SWIFT_BIN = Path(__file__).parent.parent / "tars_tui"

class TUI:
    def __init__(self, bus: Bus):
        self._bus = bus
        self._proc = None
        self._running = False
        self._esc_buf = ""  # [NEW] 방향키(ESC 시퀀스) 조합 버퍼
        
        self._last_ctrl_c = 0.0
        self._state = {
            "mode": "SPLASH",
            "logs": [],
            "scroll_off": 0,
            "input_text": "",
            "input_prompt": "\033[36m\033[1mTARS>\033[0m ",
            "status": {
                "goal_id": 0, "goal_text": "", "total": 0,
                "done": 0, "failed": 0, "phase": "", "tokens": 0
            }
        }
        self._lock = threading.RLock()

    def start(self):
        if not _SWIFT_BIN.exists():
            print(f"Error: Swift binary not found at {_SWIFT_BIN}")
            sys.exit(1)

        self._running = True
        self._proc = subprocess.Popen(
            [str(_SWIFT_BIN)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1
        )
        threading.Thread(target=self._event_loop, daemon=True, name="tui-out").start()
        self._sync_state()

    def stop(self):
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1)
            except Exception: pass

    def _event_loop(self):
        while self._running:
            try:
                ev = self._bus.events.get(timeout=0.1)
                t = ev.type
                with self._lock:
                    if t == "log":
                        for line in (ev.data or "").split("\n"): self._state["logs"].append(line)
                    elif t == "status": self._state["status"].update(ev.data or {})
                    elif t == "mode": self._state["mode"] = ev.data or "SPLASH"
                    elif t == "tokens": self._state["status"]["tokens"] = ev.data or 0
                    elif t == "prompt":
                        self._state["input_prompt"] = f"\033[36m\033[1m{ev.data or '▸ '}\033[0m "
                        self._state["input_text"] = ""
                self._sync_state()
            except Exception: pass

    def _sync_state(self):
        if self._proc and self._proc.poll() is None:
            try:
                with self._lock: data = json.dumps(self._state)
                self._proc.stdin.write(data + "\n")
                self._proc.stdin.flush()
            except Exception: pass

    def run_input_loop(self):
        if not self._proc or not self._proc.stdout: return
        try:
            while self._running and self._proc.poll() is None:
                line = self._proc.stdout.readline()
                if not line: break
                try:
                    event = json.loads(line)
                    if event.get("type") == "key": self._handle_key(event.get("char", ""))
                except json.JSONDecodeError: pass
        except KeyboardInterrupt:
            self._bus.abort()
        finally:
            self.stop()

    def _handle_key(self, chars: str):
        if not chars: return

        for ch in chars:
            # [NEW] 방향키(ESC 시퀀스) 조립
            if self._esc_buf:
                self._esc_buf += ch
                # 시퀀스 종류 조건 (A-Z 등 문자나 ~로 끝남)
                if ch.isalpha() or ch == "~":
                    seq = self._esc_buf
                    self._esc_buf = ""
                    if seq == "\x1b[A": self._scroll(+1)
                    elif seq == "\x1b[B": self._scroll(-1)
                continue
                
            if ch == "\x1b":
                self._esc_buf = "\x1b"
                continue

            if ch == "\x03":  # Ctrl+C
                now = time.monotonic()
                if now - self._last_ctrl_c < 2.0:
                    # 2초 이내 두 번째 Ctrl+C → 즉시 강제 종료
                    self._running = False
                    self._bus.abort()
                    return
                self._last_ctrl_c = now
                self._bus.abort()
                with self._lock: mode = self._state["mode"]
                if mode not in ("SPLASH", "PAUSED"):
                    # Running — abort sent; TUI stays up until orchestrator stops
                    self._log_interrupt()
                    return
                self._running = False
                return
                
            if ch == "\x04":  # Ctrl+D
                self._bus.abort()
                self._running = False
                return

            with self._lock: mode = self._state["mode"]
            if mode not in ("SPLASH", "PAUSED"): continue

            if ch in ("\r", "\n"):
                with self._lock:
                    text = self._state["input_text"]
                    self._state["input_text"] = ""
                self._bus.provide_input(text)
                self._sync_state()
                continue
                
            if ch in ("\x7f", "\x08", "\b"): # Backspace
                with self._lock:
                    self._state["input_text"] = self._state["input_text"][:-1]
                self._sync_state()
                continue
                
            if ch == "\t": continue
            
            # 일반 영어, 특수문자 및 한글 처리
            if ord(ch) >= 32:
                with self._lock:
                    combined = self._state["input_text"] + ch
                    self._state["input_text"] = unicodedata.normalize('NFC', combined)
                self._sync_state()

    def _log_interrupt(self):
        """Inject a visible interrupt notice into the log without using bus emit
        (bus stdout may be redirected through BusWriter)."""
        with self._lock:
            self._state["logs"].append("  ⚠️  Ctrl+C — stopping after current action… (again to force quit)")
        self._sync_state()

    def _scroll(self, delta: int):
        with self._lock:
            max_scroll = max(0, len(self._state["logs"]) - 5)
            self._state["scroll_off"] = max(0, min(self._state["scroll_off"] + delta, max_scroll))
        self._sync_state()