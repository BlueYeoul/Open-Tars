#!/usr/bin/env python3
"""Open-TARS v3.0 — entry point."""

import argparse

from orchestrator import Orchestrator

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Open-TARS v3.0")
    parser.add_argument("task", nargs="*")
    parser.add_argument("-D", "--display", type=int, default=1)
    parser.add_argument("--max-iters", type=int, default=50)
    args = parser.parse_args()

    task = " ".join(args.task) if args.task else "Search Apple stock and read the price"
    Orchestrator(display=args.display, max_iters=args.max_iters).run(task)
