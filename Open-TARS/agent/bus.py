"""Event bus — decouples the orchestrator from the TUI (or any other consumer).

Architecture:
    Orchestrator ──► events Queue ──► TUI / Logger / any consumer
    TUI / CLI    ──► _input Queue ──► Orchestrator (blocks on request_input)

The orchestrator has zero knowledge of the TUI.  It only calls:
    bus.emit("log",    "some message")
    bus.emit("status", {"phase": "tactician", "goal_id": 2, ...})
    bus.emit("mode",   "RUNNING")
    bus.emit("tokens", 12345)
    bus.request_input("▸ ")          ← blocks until consumer calls provide_input()

The TUI (or headless logger) calls:
    bus.provide_input("some text")   ← unblocks orchestrator
    bus.abort()                      ← unblocks + signals abort

stdout is also redirected through BusWriter so all existing print() calls
automatically become "log" events — no changes needed in the orchestrator.
"""

import queue
import sys
import threading
from dataclasses import dataclass, field
from typing import Any


# ── Event types emitted by orchestrator ──────────────────────
#   log     data: str               — one line of log output
#   status  data: dict              — partial status update
#   mode    data: str               — SPLASH | RUNNING | PAUSED
#   tokens  data: int               — cumulative token count
#   prompt  data: str               — prompt text (input requested)
#   summary data: dict              — final summary on completion

@dataclass
class Event:
    type: str
    data: Any = None


class Bus:
    """Single-bus, in-process event pipeline."""

    ABORT_SENTINEL = "\x00__ABORT__"

    def __init__(self):
        # Orchestrator → consumers (unbounded; log bursts shouldn't block)
        self.events: queue.Queue[Event] = queue.Queue()

        # Consumer → orchestrator (capacity 1 keeps backpressure simple)
        self._input_q: queue.Queue[str] = queue.Queue(maxsize=1)

        # True while orchestrator is blocked inside request_input()
        self._waiting = threading.Event()

        # Set when abort() is called — polled by orchestrator during execution
        self._abort_event = threading.Event()

    # ── Orchestrator-side API ──────────────────────────────────

    def emit(self, type: str, data: Any = None) -> None:
        """Non-blocking; safe to call from any thread."""
        self.events.put_nowait(Event(type, data))

    def request_input(self, prompt: str = "▸ ") -> str:
        """Block until the consumer calls provide_input() or abort().

        Returns the typed string, or ABORT_SENTINEL if aborted.
        """
        self.emit("prompt", prompt)
        self._waiting.set()
        try:
            return self._input_q.get()   # blocks here
        finally:
            self._waiting.clear()

    # ── Consumer-side API ─────────────────────────────────────

    def provide_input(self, text: str) -> None:
        """Deliver user input to a waiting request_input() call.

        Silently dropped if nobody is waiting.
        """
        if self._waiting.is_set():
            try:
                self._input_q.put_nowait(text)
            except queue.Full:
                pass   # already have one pending answer

    def abort(self) -> None:
        """Cancel any pending request_input() call and signal abort."""
        self._abort_event.set()
        self.provide_input(self.ABORT_SENTINEL)
        self.emit("abort", None)

    def reset_abort(self) -> None:
        """Clear abort flag — call before starting a new task."""
        self._abort_event.clear()

    @property
    def abort_requested(self) -> bool:
        """True if abort() was called. Polled by orchestrator during execution."""
        return self._abort_event.is_set()

    @property
    def is_waiting_for_input(self) -> bool:
        return self._waiting.is_set()


# ── stdout redirect ───────────────────────────────────────────

class BusWriter:
    """Drop-in sys.stdout replacement: converts all print() calls to bus events.

    Install once in __main__ before starting the orchestrator:
        sys.stdout = BusWriter(bus)

    The real stdout is saved for the TUI renderer to write frames to.
    """

    def __init__(self, bus: Bus, real_stdout=None):
        self._bus = bus
        self._real = real_stdout or sys.__stdout__
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        with self._lock:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                self._bus.emit("log", line)
        return len(text)

    def flush(self) -> None:
        with self._lock:
            if self._buf:
                self._bus.emit("log", self._buf)
                self._buf = ""

    # Keep enough of the file interface so Python internals don't complain
    def fileno(self) -> int:
        return self._real.fileno()

    def isatty(self) -> bool:
        return False

    @property
    def real(self):
        return self._real
