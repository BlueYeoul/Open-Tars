#!/usr/bin/env python3
"""Open-TARS v3.0 — full-screen CLI.

Pipeline:
    stdout → BusWriter → Bus.events → TUI (render thread)
    TUI input loop → Bus.provide_input() → Orchestrator (worker thread)

The TUI and Orchestrator never reference each other directly.
"""

import argparse
import signal
import sys
import threading
import time

from agent.bus import Bus, BusWriter
from llm.client import set_token_callback


def _build_banner_plain() -> str:
    CYAN = "\033[36m"; BOLD = "\033[1m"; DIM = "\033[2m"; R = "\033[0m"
    return (
        f"{CYAN}{BOLD}"
        "   ██████   ███████  ███████  ███   ██          ███████  ███████  ███████  ███████\n"
        "   ██  ██   ██   ██  ██       ████  ██             █     ██   ██  ██   ██  ██\n"
        "   ██  ██   ███████  █████    ██ ██ ██  ██████     █     ███████  ███████  ███████\n"
        "   ██  ██   ██       ██       ██  ████             █     ██   ██  ██  ██        ██\n"
        "   ██████   ██       ███████  ██   ███             █     ██   ██  ██   ██  ███████\n"
        f"{DIM}"
        "   ░░░░░░   ░░       ░░░░░░░  ░░   ░░░             ░     ░░   ░░  ░░   ░░  ░░░░░░░"
        f"{R}"
    )


def main():
    parser = argparse.ArgumentParser(description="Open-TARS v3.0")
    parser.add_argument("task", nargs="*")
    parser.add_argument("-D", "--display", type=int, default=1)
    parser.add_argument("--max-iters", type=int, default=50)
    parser.add_argument("--no-tui", action="store_true",
                        help="Plain scrolling output (no full-screen TUI)")
    args = parser.parse_args()

    if args.no_tui:
        _run_plain(args)
        return

    _run_tui(args)


# ── Full-screen TUI mode ──────────────────────────────────────

def _run_tui(args):
    from tui import TUI
    from agent.orchestrator import Orchestrator

    bus  = Bus()
    tui  = TUI(bus)

    # ① Redirect stdout → bus BEFORE creating orchestrator
    #   (so any import-time prints also go through the bus)
    real_stdout = sys.stdout
    sys.stdout  = BusWriter(bus, real_stdout)

    # ② Token counter → bus
    set_token_callback(lambda total: bus.emit("tokens", total))

    orch = Orchestrator(display=args.display, max_iters=args.max_iters, bus=bus)

    # ③ Start TUI (enters alternate screen, hides cursor, starts threads)
    tui.start()

    # ④ Worker thread: REPL loop — blocks on bus.request_input() when idle
    initial_task = " ".join(args.task) if args.task else None
    worker = threading.Thread(
        target=_worker,
        args=(orch, bus, tui, initial_task),
        daemon=True,
        name="orchestrator",
    )
    worker.start()

    try:
        # ⑤ Main thread: raw-input loop (must own signal handlers)
        tui.run_input_loop()
    except KeyboardInterrupt:
        bus.abort()
    finally:
        tui.stop()
        sys.stdout = real_stdout

        # Print final token count to restored terminal
        from llm.client import get_token_usage
        u = get_token_usage()
        if u["total"]:
            CYAN = "\033[36m"; DIM = "\033[2m"; R = "\033[0m"
            print(f"\n{DIM}Tokens used: {CYAN}{u['total']:,}{R}{DIM} total "
                  f"({u['prompt']:,} prompt + {u['completion']:,} completion){R}\n")


def _worker(orch, bus: Bus, tui, initial_task: str | None):
    """Orchestrator REPL — runs entirely in a background thread."""
    from agent.bus import Bus as _Bus

    if initial_task:
        orch.run(initial_task)

    while tui._running:
        bus.emit("mode", "SPLASH")
        raw = bus.request_input("TARS> ")

        if not raw or not tui._running:
            continue

        if raw == _Bus.ABORT_SENTINEL:
            tui._running = False
            return

        cmd = raw.strip()

        if cmd.lower() in ("/quit", "/exit", "/q"):
            tui._running = False
            return

        if cmd.lower() == "/help":
            bus.emit("log", "─" * 50)
            bus.emit("log", "  Commands:")
            bus.emit("log", "    <task>            Execute a task")
            bus.emit("log", "    /add <goal>       Append a goal")
            bus.emit("log", "    /add @N <goal>    Insert goal after #N")
            bus.emit("log", "    /status           Show plan and memory")
            bus.emit("log", "    /memory           Show stored memory")
            bus.emit("log", "    /help             This help")
            bus.emit("log", "    /quit             Exit")
            bus.emit("log", "─" * 50)
            continue

        if cmd.lower() == "/status":
            if orch.state:
                orch.state.print_status()   # goes via stdout → bus → TUI
            else:
                bus.emit("log", "  No active session.")
            continue

        if cmd.lower() == "/memory":
            if orch.state and orch.state.memory:
                for k, v in orch.state.memory.items():
                    bus.emit("log", f"  {k}: {v[:200]}")
            else:
                bus.emit("log", "  Memory is empty.")
            continue

        if cmd.lower().startswith("/add "):
            goal_desc = cmd[5:].strip()
            if goal_desc and orch.state:
                todo = orch.state.add_todo(goal_desc)
                bus.emit("log", f"  Added #{todo.id}: {goal_desc}")
                orch.state.print_status()
                ans = bus.request_input("  Resume execution? [Y/n] ")
                if ans.strip().lower() in ("", "y", "yes"):
                    orch.resume()
            elif not orch.state:
                bus.emit("log", "  No active session — enter a task first.")
            continue

        # ── Run task ──
        try:
            orch.run(cmd)
        except Exception as e:
            bus.emit("log", f"\n❌ Error: {e}")


# ── Plain mode (no TUI) ───────────────────────────────────────

def _run_plain(args):
    from agent.orchestrator import Orchestrator

    CYAN = "\033[36m"; BOLD = "\033[1m"; DIM = "\033[2m"; R = "\033[0m"
    print(_build_banner_plain())
    print(f"  {DIM}v3.0  —  --no-tui mode{R}\n")

    orch = Orchestrator(display=args.display, max_iters=args.max_iters)

    _last_sigint = [0.0]

    def _sigint_handler(sig, frame):
        now = time.monotonic()
        if now - _last_sigint[0] < 2.0:
            print(f"\n{DIM}  Force quit.{R}")
            sys.exit(0)
        _last_sigint[0] = now
        orch._aborted = True
        print(f"\n{DIM}  ⚠️  Ctrl+C — again within 2s to force quit.{R}")

    signal.signal(signal.SIGINT, _sigint_handler)

    def _run(task: str):
        orch.run(task)

    if args.task:
        _run(" ".join(args.task))

    while True:
        try:
            raw = input(f"\n{CYAN}{BOLD}TARS>{R} ").strip()
        except EOFError:
            print(f"\n{DIM}Goodbye.{R}")
            break

        if not raw:
            continue
        if raw.lower() in ("/quit", "/exit"):
            break
        _run(raw)

    from llm.client import get_token_usage
    u = get_token_usage()
    if u["total"]:
        print(f"\n{DIM}Tokens: {u['total']:,} total{R}")


if __name__ == "__main__":
    main()
