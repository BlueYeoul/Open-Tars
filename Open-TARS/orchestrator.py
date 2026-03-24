"""Orchestrator — Planner → Perceive (once) → action loop (Tactician → Execute)."""

import json
import re

from executor import execute_action
from llm_client import call_llm, load_prompt
from screen import ScreenInfo, take_screenshot
from state import AgentState, Todo
import tools
from toolboxes import CHECKPOINT_ERROR_SIGNALS, parse_response, resolve_actions, validate_plan

MAX_ACTION_RETRIES = 3   # retries per goal before giving up
MAX_ACTIONS_PER_GOAL = 12  # safety cap on total actions within one goal


class Orchestrator:
    def __init__(self, display: int = 1, max_iters: int = 50):
        self.screen = ScreenInfo(display)
        self.max_iters = max_iters
        self.state: AgentState | None = None
        self._iter = 0

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def run(self, task: str):
        print(f"\n{'='*60}\nTask: {task}\n{'='*60}")
        self.state = AgentState(task=task)
        self._iter = 0

        for g in self._plan(task):
            self.state.add_todo(g)
        self.state.print_status()

        while self._iter < self.max_iters:
            todo = self.state.next_pending()
            if not todo:
                print("\n✅ All tasks completed!")
                break
            self._run_goal(todo)
            self.state.print_status()

        self._summary()

    # ──────────────────────────────────────────────────────────────────
    # Planner
    # ──────────────────────────────────────────────────────────────────

    def _plan(self, task: str) -> list[str]:
        print("\n[Planner] Breaking down task...")
        raw = call_llm(load_prompt("planner"), task)
        goals = self._parse_json_array(raw)
        if goals:
            print(f"[Planner] {goals}")
            return goals
        print(f"[Planner] ⚠️ Parse failed, treating as single goal")
        return [task]

    # ──────────────────────────────────────────────────────────────────
    # Goal execution — action loop guided by daydream narrative
    # ──────────────────────────────────────────────────────────────────

    def _run_goal(self, todo: Todo):
        print(f"\n{'='*60}\n[Goal {todo.id}] {todo.description}\n{'='*60}")

        # ── Perceive: assess screen + narrate approach (single vision call) ──
        # Also checks if goal is already done — outputs <done/> if so.
        b64, _ = take_screenshot(self.screen)
        raw_perceive = call_llm(
            load_prompt("perceive", goal=todo.description,
                        memory_block=self._format_memory()),
            "Perceive and narrate.",
            image=b64,
        )
        if re.search(r"<done\s*/>", raw_perceive):
            todo.status = "done"
            print("    ✅ Already done (perceive)")
            return

        m = re.search(r"<after>(.*?)</after>", raw_perceive, re.DOTALL)
        next_hint = m.group(1).strip() if m else ""
        daydream = re.sub(r"<after>.*?</after>", "", raw_perceive, flags=re.DOTALL).strip()
        print(f"    💭 Perceive:\n{daydream[:400]}")
        if next_hint:
            print(f"    ➡️  First: {next_hint}")

        # ── Action loop ──
        past_actions: list[str] = []
        fail_streak = 0
        action_count = 0
        error_block = ""

        while action_count < MAX_ACTIONS_PER_GOAL and self._iter < self.max_iters:
            b64, _ = take_screenshot(self.screen)
            actions, state, next_hint = self._plan_action(
                b64, todo.description, daydream, past_actions, error_block, next_hint)

            if not actions:
                fail_streak += 1
                if fail_streak >= MAX_ACTION_RETRIES:
                    todo.status = "failed"
                    return
                continue

            # ── Done signal from Tactician ──
            if actions[0]["type"] == "done":
                todo.status = "done"
                print("    ✅ Goal done!")
                return

            aborted, fail_reason = self._execute_step(actions)
            self._iter += 1
            action_count += 1
            label = actions[0].get("name", actions[0].get("type", "?"))
            past_actions.append(f"[{state}] → {label}" if state else label)

            if aborted:
                error_block = f"⚠️ Action '{label}' FAILED: {fail_reason}"
                fail_streak += 1
                if fail_streak >= MAX_ACTION_RETRIES:
                    todo.status = "failed"
                    return
                # Reuse screenshot taken at top of next iteration (no extra vision call)
            else:
                fail_streak = 0
                error_block = ""

        todo.status = "failed"
        print(f"    ❌ Goal failed after {action_count} actions")

    # ──────────────────────────────────────────────────────────────────
    # Tactician: decide next action toward goal
    # ──────────────────────────────────────────────────────────────────

    def _plan_action(
        self,
        b64: str,
        goal: str,
        daydream: str,
        past_actions: list[str],
        error_block: str,
        next_hint: str = "",
    ) -> tuple[list[dict], str, str]:
        """Returns (actions, state, next_hint) where:
          - state: Tactician's situational assessment
          - next_hint: Tactician's weakly planned next step (for following iteration)
        """
        past_block = "\n".join(f"  - {a}" for a in past_actions[-6:]) or "  (nothing yet)"
        next_block = next_hint or "(not specified)"

        MAX_PLAN_RETRIES = 2
        local_error = error_block

        for attempt in range(MAX_PLAN_RETRIES + 1):
            raw = call_llm(
                load_prompt("tactician",
                            goal=goal,
                            daydream=daydream,
                            next_hint=next_block,
                            past_actions=past_block,
                            memory_block=self._format_memory(),
                            error_block=local_error,
                            tool_docs=tools.load_tool_docs()),
                "Generate the next action.",
                image=b64,
            )

            # Extract <state> assessment
            state = ""
            ms = re.search(r"<state>(.*?)</state>", raw, re.DOTALL)
            if ms:
                state = ms.group(1).strip()
                print(f"        🗺️  State: {state}")

            # Extract <next> weakly subplan hint
            new_next = ""
            mn = re.search(r"<after>(.*?)</after>", raw, re.DOTALL)
            if mn:
                new_next = mn.group(1).strip()
                print(f"        ➡️  Next: {new_next}")

            print(f"        📋 {raw[:160]}...")

            parsed = parse_response(raw)
            actions = resolve_actions([a for a in parsed if a["type"] != "todo"])
            print(f"        🔧 {[a['type'] + ('+' + a.get('name','') if a['type']=='toolbox' else '') for a in actions]}")

            is_valid, errors = validate_plan(actions)
            if is_valid:
                return actions, state, new_next

            err_str = "; ".join(errors)
            print(f"        ❌ Rejected ({attempt+1}): {err_str}")
            local_error = f"⚠️ REJECTED: {err_str}\nRejected: {raw[:200]}\nFix and regenerate."

        return [], "", ""

    # ──────────────────────────────────────────────────────────────────
    # Executor: run actions for one step
    # ──────────────────────────────────────────────────────────────────

    def _execute_step(self, actions: list[dict]) -> tuple[bool, str]:
        """Execute actions. Returns (aborted, reason) where aborted=True means failure."""
        for action in actions:
            atype = action["type"]

            if atype == "toolbox":
                tb_name = action["name"]
                inline = action.get("actions")
                tb_params = {k: v for k, v in action.items() if k not in ("type", "name", "actions")}

                if inline:
                    print(f"    📦 [{tb_name}] (inline: {len(inline)} actions)")
                    sub_list = inline
                elif tools.exists(tb_name):
                    print(f"    📦 [{tb_name}] {tb_params}")
                    sub_list = tools.run_tool(tb_name, tb_params)
                else:
                    print(f"    ⚠️ Unknown toolbox and no inline actions: {tb_name}")
                    continue

                for sub in sub_list:
                    if sub["type"] == "checkpoint":
                        b64_cp, _ = take_screenshot(self.screen)
                        cp_desc = call_llm(load_prompt("describer"), "Describe.", image=b64_cp)
                        print(f"    📍 [{tb_name}]: {cp_desc[:100]}")
                        if any(kw in cp_desc.lower() for kw in CHECKPOINT_ERROR_SIGNALS):
                            return True, f"checkpoint error: {cp_desc[:120]}"
                    elif sub["type"] == "read":
                        tgt, skey = sub["target"], sub["save_to"]
                        b64_r, _ = take_screenshot(self.screen)
                        extracted = call_llm(load_prompt("reader", target=tgt), "Extract.", image=b64_r)
                        self.state.set_memory(skey, extracted)
                        print(f"        👁️ {skey}: {extracted[:100]}")
                    else:
                        img = take_screenshot(self.screen)[1] if sub["type"] in ("click", "doubleclick") else None
                        ok, res = execute_action(sub, self.screen, img)
                        print(f"        → {'✅' if ok else '❌'} {res}")
                        if not ok:
                            return True, res

            elif atype == "read":
                tgt, skey = action["target"], action["save_to"]
                b64_r, _ = take_screenshot(self.screen)
                extracted = call_llm(load_prompt("reader", target=tgt), "Extract.", image=b64_r)
                self.state.set_memory(skey, extracted)
                print(f"    👁️ {skey}: {extracted[:100]}")

            elif atype == "memory":
                self.state.set_memory(action["key"], action["value"])

            else:
                img = take_screenshot(self.screen)[1] if atype in ("click", "doubleclick") else None
                ok, res = execute_action(action, self.screen, img)
                print(f"        → {'✅' if ok else '❌'} {res}")
                if not ok:
                    return True, res

        return False, ""

    def _expand_plan(self, instruction: str):
        """Ask Planner to generate prerequisite goals and append them to the queue."""
        print(f"\n[Planner] Expanding plan: {instruction[:100]}")
        new_goals = self._plan(instruction)
        for g in new_goals:
            self.state.add_todo(g)
        print(f"[Planner] Inserted {len(new_goals)} new goal(s)")
        self.state.print_status()

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────

    def _format_memory(self) -> str:
        if not self.state.memory:
            return ""
        lines = [f"  [{k}]: {v[:200]}" for k, v in list(self.state.memory.items())[-8:]]
        return "Memory:\n" + "\n".join(lines)

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
        done = sum(1 for t in self.state.todos if t.status == "done")
        total = len(self.state.todos)
        print(f"\n{'='*60}\nResult: {done}/{total} tasks completed")
        if self.state.memory:
            print(f"\n📋 Final Memory ({len(self.state.memory)} items):")
            for k, v in self.state.memory.items():
                print(f"  {k}: {v[:200]}")
        print(f"{'='*60}")
