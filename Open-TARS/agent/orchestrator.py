"""Orchestrator — Maestro → Planner → Perceive → action loop (Observe → Tactician → Execute).

Communicates exclusively through the Bus.  No import of TUI, no shared state.

Output protocol:
    bus.emit("log",     line_str)
    bus.emit("status",  {partial_dict})
    bus.emit("mode",    "RUNNING" | "SPLASH" | "PAUSED")
    bus.emit("tokens",  cumulative_int)
    bus.emit("summary", {done, total, tokens, memory})

Input protocol:
    text = bus.request_input(prompt_str)   ← blocks until TUI/CLI provides it
    if text == Bus.ABORT_SENTINEL: abort
"""

import json
import re

from PIL import Image

from agent.bus import Bus
from action.executor import execute_action
from action.input_controller import get_focus, format_app_list
from llm.client import call_llm, load_prompt, get_token_usage
from vision.screen import ScreenInfo, take_screenshot
from vision.action_history import ActionHistory
from vision.frame_diff import diff_image_b64
from agent.state import AgentState, Todo
import tools
from action.toolboxes import CHECKPOINT_ERROR_SIGNALS, parse_response, resolve_actions, validate_plan

MAX_ACTION_RETRIES   = 3
MAX_ACTIONS_PER_GOAL = 12
MAX_SCROLL_RETRIES   = 5
MAX_TOTAL_GOALS      = 8     # Abort if goal list grows beyond this


class Orchestrator:
    def __init__(self, display: int = 1, max_iters: int = 50, bus: Bus | None = None):
        self.screen    = ScreenInfo(display)
        self.max_iters = max_iters
        self.state: AgentState | None = None
        self._iter     = 0
        self._aborted  = False
        self._bus      = bus              # may be None (headless / test mode)
        self._history  = ActionHistory()  # mouse trail + text long-term memory
        self._prev_img: Image.Image | None = None  # previous frame for diff

    # ──────────────────────────────────────────────────────────────────
    # Bus helpers — all output funnels through here
    # ──────────────────────────────────────────────────────────────────

    def _log(self, text: str):
        """Emit a log line (or several).  Falls back to print() if no bus."""
        if self._bus:
            for line in text.split("\n"):
                self._bus.emit("log", line)
        else:
            print(text)

    def _status(self, **kw):
        if self._bus:
            self._bus.emit("status", kw)

    def _mode(self, mode: str):
        if self._bus:
            self._bus.emit("mode", mode)

    def _push_tokens(self):
        if self._bus:
            u = get_token_usage()
            self._bus.emit("tokens", u["total"])

    def _input(self, prompt: str) -> str:
        """Get user input.  Blocks until input is provided or abort."""
        if self._bus:
            self._mode("PAUSED")
            text = self._bus.request_input(prompt)
            self._mode("RUNNING")
            return text
        try:
            return input(prompt)
        except (EOFError, KeyboardInterrupt):
            return Bus.ABORT_SENTINEL

    def _sync_status(self):
        if not self.state:
            return
        done   = sum(1 for t in self.state.todos if t.status == "done")
        failed = sum(1 for t in self.state.todos if t.status == "failed")
        nxt    = self.state.next_pending()
        self._status(
            total    = len(self.state.todos),
            done     = done,
            failed   = failed,
            goal_id  = nxt.id if nxt else 0,
            goal_text= nxt.description if nxt else "",
        )

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def run(self, task: str):
        self._log(f"\n{'='*60}\nTask: {task}\n{'='*60}")
        self.state    = AgentState(task=task)
        self._iter    = 0
        self._aborted = False
        self._apps_str = format_app_list()
        self._history.clear()
        self._prev_img = None
        if self._bus:
            self._bus.reset_abort()

        # Initial screenshot — passed to Maestro + Planner so they know the current screen state
        init_b64, _ = take_screenshot(self.screen)

        # Maestro: initial strategic assessment
        strategy = self._maestro_initial(task, init_b64)

        for g in self._plan(task, strategy, init_b64):
            self.state.add_todo(g)
        self.state.print_status()
        self._sync_status()
        self._mode("RUNNING")
        self._execute_todos()
        self._summary()

    def resume(self):
        if not self.state:
            return
        self._aborted = False
        self._mode("RUNNING")
        self._execute_todos()
        self._summary()

    # ──────────────────────────────────────────────────────────────────
    # Core loop
    # ──────────────────────────────────────────────────────────────────

    def _execute_todos(self):
        while self._iter < self.max_iters:
            if self._aborted:
                self._log("  ⚠️  Aborted.")
                break

            todo = self.state.next_pending()
            if not todo:
                self._log("\n✅ All tasks completed!")
                break

            self._run_goal(todo)
            self.state.print_status()
            self._sync_status()

            # On failure: call Maestro for recovery
            if todo.status == "failed":
                recovered = self._maestro_recover(todo)
                if recovered:
                    self.state.print_status()
                    self._sync_status()

    # ──────────────────────────────────────────────────────────────────
    # Pause
    # ──────────────────────────────────────────────────────────────────

    def _pause_between_goals(self, last: Todo) -> bool:
        icon = "✓" if last.status == "done" else "✗"
        self._log(f"\n{'─'*60}")
        self._log(f"  [{icon}] Goal {last.id}: {last.description}")
        pending = [t for t in self.state.todos if t.status == "pending"]
        if pending:
            self._log(f"  Next → Goal {pending[0].id}: {pending[0].description}")
            self._log(f"  ({len(pending)} remaining)")
        self._log(f"{'─'*60}")

        while True:
            raw = self._input("▸ ").strip()

            # Abort sentinel from bus
            if raw == Bus.ABORT_SENTINEL or raw.lower() == "/quit":
                self._aborted = True
                return False

            if not raw:
                return True

            cmd = raw.lower()

            if cmd == "/abort":
                self._aborted = True
                return False

            elif cmd == "/skip":
                nxt = self.state.next_pending()
                if nxt:
                    nxt.status = "skipped"
                    self._log(f"  Skipped goal #{nxt.id}")
                    self.state.print_status()
                    self._sync_status()

            elif cmd == "/retry":
                failed = [t for t in self.state.todos if t.status == "failed"]
                if failed:
                    t = failed[-1]
                    t.status   = "pending"
                    t.attempts += 1
                    self._log(f"  Retrying #{t.id}: {t.description}")
                    self._sync_status()
                return True

            elif cmd.startswith("/add"):
                rest = raw[4:].strip()
                m    = re.match(r"@(\d+)\s+(.+)", rest)
                if m:
                    after_id  = int(m.group(1))
                    goal_desc = m.group(2).strip()
                    todo = self.state.insert_todo(goal_desc, after_id)
                    if todo:
                        self._log(f"  Inserted #{todo.id} after #{after_id}: {goal_desc}")
                    else:
                        todo = self.state.add_todo(goal_desc)
                        self._log(f"  Appended #{todo.id}: {goal_desc}")
                elif rest:
                    todo = self.state.add_todo(rest)
                    self._log(f"  Added #{todo.id}: {rest}")
                else:
                    self._log("  Usage: /add <goal>  or  /add @N <goal>")
                    continue
                self.state.print_status()
                self._sync_status()

            elif cmd.startswith("/task "):
                new_task = raw[6:].strip()
                if new_task:
                    for g in self._plan(new_task):
                        t = self.state.add_todo(g)
                        self._log(f"  + #{t.id}: {g}")
                    self.state.print_status()
                    self._sync_status()

            elif cmd == "/status":
                self.state.print_status()

            elif cmd == "/memory":
                if self.state.memory:
                    for k, v in self.state.memory.items():
                        self._log(f"  {k}: {v[:200]}")
                else:
                    self._log("  Memory is empty.")

            elif cmd == "/help":
                self._log("  Enter=continue  /add <goal>  /add @N <goal>")
                self._log("  /skip  /retry  /task <task>  /status  /memory  /abort")

            else:
                self._log("  Unknown command. /help for options, Enter to continue.")

    # ──────────────────────────────────────────────────────────────────
    # Maestro
    # ──────────────────────────────────────────────────────────────────

    def _maestro_initial(self, task: str, b64: str = None) -> str:
        """Strategic assessment before planning."""
        self._log("\n[Maestro] Strategic assessment...")
        self._status(phase="maestro")
        raw = call_llm(
            load_prompt("maestro", task=task, todos="(none yet)", context=""),
            "MODE A: Provide initial strategic assessment for this task.",
            image=b64)
        self._push_tokens()
        self._log(f"[Maestro] {raw[:300]}")
        return raw

    def _maestro_recover(self, failed_todo: Todo) -> bool:
        """Call Maestro to recover from a failed goal. Returns True if recovery was applied."""
        self._log(f"\n[Maestro] Recovery analysis for failed goal #{failed_todo.id}...")
        self._status(phase="maestro")

        # Format current TODOs
        todos_text = ""
        for t in self.state.todos:
            icon = {"done": "✓", "failed": "✗", "pending": " ", "skipped": "-"}.get(t.status, "?")
            todos_text += f"  [{icon}] {t.id}. {t.description} (status: {t.status})\n"

        context = f"FAILED GOAL: #{failed_todo.id} \"{failed_todo.description}\"\nAttempts: {failed_todo.attempts + 1}"

        raw = call_llm(
            load_prompt("maestro", task=self.state.task,
                        todos=todos_text, context=context),
            "MODE B: Analyze the failure and prescribe a recovery plan.")
        self._push_tokens()
        self._log(f"[Maestro] {raw[:400]}")

        # Parse response
        strategy_m = re.search(r"STRATEGY:\s*(RETRY|REVISE|SKIP|ABORT)", raw)
        if not strategy_m:
            self._log("[Maestro] ⚠️  Could not parse strategy — skipping recovery")
            return False

        strategy = strategy_m.group(1)

        if strategy == "RETRY":
            failed_todo.status = "pending"
            failed_todo.attempts += 1
            self._log(f"[Maestro] → RETRY goal #{failed_todo.id} (attempt {failed_todo.attempts + 1})")
            return True

        elif strategy == "REVISE":
            # Check total goal count — prevent runaway growth
            total = len(self.state.todos)
            if total >= MAX_TOTAL_GOALS:
                self._log(f"[Maestro] ⚠️  Already {total} goals (max {MAX_TOTAL_GOALS}) — refusing REVISE, aborting")
                self._aborted = True
                return False

            goals_m = re.search(r"REVISED_GOALS:\s*(\[.*?\])", raw, re.DOTALL)
            if goals_m:
                new_goals = self._parse_json_array(goals_m.group(1))
                if new_goals:
                    # Cap new goals so total doesn't exceed limit
                    room = MAX_TOTAL_GOALS - total
                    if len(new_goals) > room:
                        new_goals = new_goals[:room]
                        self._log(f"[Maestro] ⚠️  Trimmed to {room} new goals (limit {MAX_TOTAL_GOALS})")

                    self._log(f"[Maestro] → REVISE: replacing remaining goals with {len(new_goals)} new goals")
                    # Remove remaining pending goals
                    for t in self.state.todos:
                        if t.status == "pending":
                            t.status = "skipped"
                    # Add new goals
                    for g in new_goals:
                        t = self.state.add_todo(g)
                        self._log(f"  + #{t.id}: {g}")
                    return True
            self._log("[Maestro] ⚠️  REVISE but no valid goals — skipping")
            return False

        elif strategy == "SKIP":
            self._log(f"[Maestro] → SKIP goal #{failed_todo.id}")
            return True  # just continue to next pending

        elif strategy == "ABORT":
            self._log("[Maestro] → ABORT — task is unrecoverable")
            self._aborted = True
            return False

        return False

    # ──────────────────────────────────────────────────────────────────
    # Planner
    # ──────────────────────────────────────────────────────────────────

    def _plan(self, task: str, strategy: str = "", b64: str = None) -> list[str]:
        self._log("\n[Planner] Breaking task down...")
        self._status(phase="planner")
        prompt_text = task
        if strategy:
            prompt_text = f"{task}\n\n[Strategic guidance from Maestro]:\n{strategy}"
        raw   = call_llm(load_prompt("planner", app_list=self._apps_str), prompt_text, image=b64)
        self._push_tokens()
        goals = self._parse_json_array(raw)
        if goals:
            self._log(f"[Planner] Goals: {goals}")
            return goals
        self._log("[Planner] ⚠️  Parse failed — treating as single goal")
        return [task]

    # ──────────────────────────────────────────────────────────────────
    # Observer (lightweight screen analysis — replaces Consultant)
    # ──────────────────────────────────────────────────────────────────

    def _observe(self, b64: str, goal: str, curr_img: Image.Image | None = None,
                 diff_desc: str = "") -> str:
        """Fast 2-3 sentence screen observation, with optional diff context."""
        focused = get_focus()
        mem = self._format_memory()

        # Build diff context for observer
        diff_block = ""
        if diff_desc and diff_desc != "no_change":
            diff_block = f"\n**Screen changes since last action:** {diff_desc}"

        # Include action history text
        hist_block = self._history.text_summary()

        raw = call_llm(
            load_prompt("observe", goal=goal, focused_app=focused,
                        memory_block=mem, apps=self._apps_str,
                        diff_block=diff_block, history_block=hist_block),
            "Observe.", image=b64)
        self._push_tokens()
        self._log(f"    👁️ {raw[:250]}")
        return raw

    # ──────────────────────────────────────────────────────────────────
    # Goal execution
    # ──────────────────────────────────────────────────────────────────

    def _run_goal(self, todo: Todo):
        self._log(f"\n{'='*60}\n[Goal {todo.id}] {todo.description}\n{'='*60}")
        done = sum(1 for t in self.state.todos if t.status == "done")
        self._status(goal_id=todo.id, goal_text=todo.description, done=done)

        # ── Perceive ──
        self._status(phase="perceive")
        b64, _ = take_screenshot(self.screen)
        raw_p  = call_llm(
            load_prompt("perceive", goal=todo.description,
                        memory_block=self._format_memory()),
            "Perceive and narrate.", image=b64)
        self._push_tokens()

        if re.search(r"<done\s*/>", raw_p):
            todo.status = "done"
            self._log("    ✅ Already done (perceive)")
            return

        m        = re.search(r"<after>(.*?)</after>", raw_p, re.DOTALL)
        next_hint= m.group(1).strip() if m else ""
        daydream = re.sub(r"<after>.*?</after>", "", raw_p, flags=re.DOTALL).strip()
        self._log(f"    💭 Perceive:\n{daydream[:400]}")
        if next_hint:
            self._log(f"    ➡️  First: {next_hint}")

        # ── Action loop ──
        past_actions: list[str] = []
        fail_streak  = 0
        action_count = 0
        error_block  = ""

        while action_count < MAX_ACTIONS_PER_GOAL and self._iter < self.max_iters:
            if self._aborted or (self._bus and self._bus.abort_requested):
                self._aborted = True
                self._log("  ⚠️  Interrupted.")
                todo.status = "failed"
                return

            b64, curr_img = take_screenshot(self.screen)

            # Frame diff: compare with previous frame
            diff_desc = ""
            if self._prev_img is not None:
                _, diff_desc = diff_image_b64(self._prev_img, curr_img)
                if diff_desc != "no_change":
                    self._log(f"    🔄 Diff: {diff_desc[:120]}")

            # Observe (lightweight — replaces Consultant + Sensors)
            self._status(phase="observe")
            observation = self._observe(b64, todo.description, curr_img, diff_desc)

            # Check if observer detected goal completion
            if re.search(r"<done\s*/>", observation):
                todo.status = "done"
                self._log("    ✅ Goal done! (observer)")
                return

            # Tactician
            self._status(phase="tactician")
            actions, state, next_hint = self._plan_action(
                b64, todo.description, daydream, past_actions,
                error_block, next_hint, observation)

            if not actions:
                fail_streak += 1
                if fail_streak >= MAX_ACTION_RETRIES:
                    todo.status = "failed"
                    return
                continue

            if actions[0]["type"] == "done":
                todo.status = "done"
                self._log("    ✅ Goal done!")
                return

            # Record action to history BEFORE execution (no image stored)
            label = actions[0].get("name", actions[0].get("type", "?"))
            self._history.record(
                action_label=label,
                state_text=state,
            )

            # Execute — with scroll-loop support
            self._status(phase="execute")
            self._prev_img = curr_img  # store for next diff
            has_scroll = self._actions_contain_scroll(actions)
            aborted, fail_reason = self._execute_step(actions)
            self._iter   += 1
            action_count += 1
            past_actions.append(f"[{state}] → {label}" if state else label)

            # Update history entry with grounded coords (set by executor)
            gx, gy = self._extract_grounded_coords(actions)
            if gx is not None and self._history.count > 0:
                last = self._history._entries[-1]
                last.mouse_x = gx
                last.mouse_y = gy

            if aborted:
                error_block  = f"⚠️  Action '{label}' FAILED: {fail_reason}"
                fail_streak += 1
                if fail_streak >= MAX_ACTION_RETRIES:
                    todo.status = "failed"
                    return
            else:
                fail_streak = 0
                error_block = ""

            # Scroll-loop: if the step was a scroll and next_hint suggests
            # something to find, auto-scroll with observe checks
            if has_scroll and not aborted and next_hint:
                scroll_obs = self._scroll_loop(todo.description, next_hint)
                if scroll_obs:
                    # Feed the final observation into next tactician iteration
                    observation = scroll_obs

        todo.status = "failed"
        self._log(f"    ❌ Goal failed after {action_count} actions")

    # ──────────────────────────────────────────────────────────────────
    # Scroll loop — tight scroll+observe without full tactician cycle
    # ──────────────────────────────────────────────────────────────────

    def _actions_contain_scroll(self, actions: list[dict]) -> bool:
        """Check if any action in the list is or contains a scroll."""
        for a in actions:
            if a["type"] == "scroll":
                return True
            if a["type"] == "toolbox":
                for sub in a.get("actions", []):
                    if sub["type"] == "scroll":
                        return True
        return False

    def _scroll_loop(self, goal: str, target_hint: str) -> str:
        """Auto-scroll up to MAX_SCROLL_RETRIES times, checking with observer each time.

        Returns the final observation if scrolling was done, empty string otherwise.
        """
        from action.input_controller import scroll
        import time

        last_obs = ""
        for i in range(MAX_SCROLL_RETRIES):
            b64, _ = take_screenshot(self.screen)
            obs = self._observe(b64, goal)

            # If observer sees something related to the target hint, stop scrolling
            # Heuristic: check if key words from hint appear in observation
            hint_words = [w.lower() for w in target_hint.split() if len(w) > 2]
            obs_lower = obs.lower()
            matches = sum(1 for w in hint_words if w in obs_lower)

            if matches >= len(hint_words) * 0.4 or re.search(r"<done\s*/>", obs):
                self._log(f"    🔄 Scroll-loop: target found after {i} extra scrolls")
                return obs

            # Auto-scroll down
            self._log(f"    🔄 Scroll-loop: scroll {i+1}/{MAX_SCROLL_RETRIES}...")
            scroll("down")
            time.sleep(0.5)
            last_obs = obs

        self._log(f"    🔄 Scroll-loop: exhausted {MAX_SCROLL_RETRIES} scrolls")
        return last_obs

    # ──────────────────────────────────────────────────────────────────
    # Tactician
    # ──────────────────────────────────────────────────────────────────

    def _plan_action(self, b64, goal, daydream, past_actions, error_block,
                     next_hint="", observation=""):
        past_block  = "\n".join(f"  - {a}" for a in past_actions[-6:]) or "  (nothing yet)"
        next_block  = next_hint or "(not specified)"
        local_error = error_block

        for attempt in range(3):
            raw = call_llm(
                load_prompt("tactician",
                            goal=goal, daydream=daydream,
                            next_hint=next_block, past_actions=past_block,
                            memory_block=self._format_memory(),
                            error_block=local_error,
                            tool_docs=tools.load_tool_docs(),
                            app_list=self._apps_str,
                            observation=observation,
                            history_block=self._history.text_summary()),
                "Generate the next action.", image=b64)
            self._push_tokens()

            state = ""
            ms = re.search(r"<state>(.*?)</state>", raw, re.DOTALL)
            if ms:
                state = ms.group(1).strip()
                self._log(f"        🗺️  State: {state}")

            new_next = ""
            mn = re.search(r"<after>(.*?)</after>", raw, re.DOTALL)
            if mn:
                new_next = mn.group(1).strip()
                self._log(f"        ➡️  Next: {new_next}")

            self._log(f"        📋 {raw[:160]}...")

            parsed  = parse_response(raw)
            actions = resolve_actions([a for a in parsed if a["type"] != "todo"])
            self._log(f"        🔧 {[a['type'] + ('+' + a.get('name','') if a['type']=='toolbox' else '') for a in actions]}")

            ok, errors = validate_plan(actions)
            if ok:
                return actions, state, new_next

            err_str    = "; ".join(errors)
            self._log(f"        ❌ Rejected ({attempt+1}): {err_str}")
            local_error = f"⚠️  REJECTED: {err_str}\nFix and regenerate."

        return [], "", ""

    # ──────────────────────────────────────────────────────────────────
    # Executor
    # ──────────────────────────────────────────────────────────────────

    def _execute_step(self, actions: list[dict]) -> tuple[bool, str]:
        for action in actions:
            atype = action["type"]

            if atype == "toolbox":
                tb_name = action["name"]
                inline  = action.get("actions")
                tb_params = {k: v for k, v in action.items()
                             if k not in ("type", "name", "actions")}

                if inline:
                    self._log(f"    📦 [{tb_name}] (inline: {len(inline)} actions)")
                    sub_list = inline
                elif tools.exists(tb_name):
                    self._log(f"    📦 [{tb_name}] {tb_params}")
                    sub_list = tools.run_tool(tb_name, tb_params)
                else:
                    self._log(f"    ⚠️  Unknown toolbox: {tb_name}")
                    continue

                for sub in sub_list:
                    if sub["type"] == "checkpoint":
                        b64_cp, _ = take_screenshot(self.screen)
                        cp_desc   = call_llm(load_prompt("describer"), "Describe.", image=b64_cp)
                        self._push_tokens()
                        self._log(f"    📍 [{tb_name}]: {cp_desc[:100]}")
                        if any(kw in cp_desc.lower() for kw in CHECKPOINT_ERROR_SIGNALS):
                            return True, f"checkpoint: {cp_desc[:120]}"
                    elif sub["type"] == "read":
                        tgt, skey = sub["target"], sub["save_to"]
                        b64_r, _  = take_screenshot(self.screen)
                        val       = call_llm(load_prompt("reader", target=tgt), "Extract.", image=b64_r)
                        self._push_tokens()
                        self.state.set_memory(skey, val)
                        self._log(f"        👁️  {skey}: {val[:100]}")
                    else:
                        img = take_screenshot(self.screen)[1] if sub["type"] in ("click", "doubleclick") else None
                        ok, res = execute_action(sub, self.screen, img)
                        self._log(f"        → {'✅' if ok else '❌'} {res}")
                        if not ok:
                            return True, res

            elif atype == "read":
                tgt, skey = action["target"], action["save_to"]
                b64_r, _  = take_screenshot(self.screen)
                val       = call_llm(load_prompt("reader", target=tgt), "Extract.", image=b64_r)
                self._push_tokens()
                self.state.set_memory(skey, val)
                self._log(f"    👁️  {skey}: {val[:100]}")

            elif atype == "memory":
                self.state.set_memory(action["key"], action["value"])

            else:
                img = take_screenshot(self.screen)[1] if atype in ("click", "doubleclick") else None
                ok, res = execute_action(action, self.screen, img)
                self._log(f"        → {'✅' if ok else '❌'} {res}")
                if not ok:
                    return True, res

        return False, ""

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    def _format_memory(self) -> str:
        if not self.state or not self.state.memory:
            return ""
        lines = [f"  [{k}]: {v[:200]}" for k, v in list(self.state.memory.items())[-8:]]
        return "Memory:\n" + "\n".join(lines)

    @staticmethod
    def _extract_grounded_coords(actions: list[dict]) -> tuple[int | None, int | None]:
        """Extract grounded click coordinates set by executor after execution.

        Executor stores _grounded_x/_grounded_y on click actions post-grounding.
        """
        for a in actions:
            if a["type"] == "toolbox":
                for sub in a.get("actions", []):
                    gx = sub.get("_grounded_x")
                    gy = sub.get("_grounded_y")
                    if gx is not None:
                        return gx, gy
            gx = a.get("_grounded_x")
            gy = a.get("_grounded_y")
            if gx is not None:
                return gx, gy
        return None, None

    @staticmethod
    def _parse_json_array(text: str) -> list[str] | None:
        for m in reversed(list(re.finditer(r"\[.*?\]", text, re.DOTALL))):
            try:
                arr = json.loads(m.group())
                if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
                    return arr
            except json.JSONDecodeError:
                continue
        return None

    def _summary(self):
        u     = get_token_usage()
        done  = sum(1 for t in self.state.todos if t.status == "done")
        total = len(self.state.todos)

        self._log(f"\n{'='*60}")
        self._log(f"Result : {done}/{total} tasks completed")
        self._log(f"Tokens : {u['total']:,} total  "
                  f"({u['prompt']:,} prompt + {u['completion']:,} completion)")
        if self.state.memory:
            self._log(f"\n📋 Memory ({len(self.state.memory)} items):")
            for k, v in self.state.memory.items():
                self._log(f"  {k}: {v[:200]}")
        self._log(f"{'='*60}")

        if self._bus:
            self._bus.emit("summary", {
                "done": done, "total": total,
                "tokens": u["total"],
                "memory": self.state.memory,
            })
            self._mode("SPLASH")
