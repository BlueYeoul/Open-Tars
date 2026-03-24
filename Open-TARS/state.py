"""AgentState and Todo dataclasses."""

from dataclasses import dataclass, field


@dataclass
class Todo:
    id: int
    description: str
    status: str = "pending"   # pending / delegated / done / failed / skipped
    attempts: int = 0
    parent_id: int = 0


@dataclass
class AgentState:
    task: str
    todos: list[Todo] = field(default_factory=list)
    memory: dict[str, str] = field(default_factory=dict)
    _next_id: int = 1

    def add_todo(self, desc: str, parent_id: int = 0) -> Todo:
        t = Todo(id=self._next_id, description=desc, parent_id=parent_id)
        self._next_id += 1
        if parent_id > 0:
            parent_idx = next((i for i, x in enumerate(self.todos) if x.id == parent_id), -1)
            if parent_idx >= 0:
                insert_at = parent_idx + 1
                while insert_at < len(self.todos) and self.todos[insert_at].parent_id == parent_id:
                    insert_at += 1
                self.todos.insert(insert_at, t)
            else:
                self.todos.append(t)
        else:
            self.todos.append(t)
        return t

    def update_delegated_tasks(self):
        for t in self.todos:
            if t.status == "delegated":
                children = [c for c in self.todos if c.parent_id == t.id]
                if children:
                    if all(c.status == "done" for c in children):
                        t.status = "done"
                        print(f"    ✨ [Delegation Complete] Parent Goal [{t.id}] automatically marked as done.")
                    elif any(c.status == "failed" for c in children):
                        t.status = "failed"
                        print(f"    ❌ [Delegation Failed] Parent Goal [{t.id}] failed because a child failed.")

    def next_pending(self) -> "Todo | None":
        self.update_delegated_tasks()
        return next((t for t in self.todos if t.status == "pending"), None)

    def set_memory(self, key: str, value: str):
        self.memory[key] = value
        print(f"    💾 Memory[{key}] = {value[:80]}{'...' if len(value) > 80 else ''}")

    def print_status(self):
        print("─" * 60)
        print("TODOs:")
        for t in self.todos:
            icon = {"pending": "[ ]", "delegated": "[⧖]", "done": "[✓]", "failed": "[✗]", "skipped": "[-]"}[t.status]
            indent = "    " if t.parent_id > 0 else "  "
            print(f"{indent}{icon} {t.id}. {t.description}")
        if self.memory:
            print(f"\nMemory ({len(self.memory)} items):")
            for k, v in list(self.memory.items())[-5:]:
                print(f"  💾 {k}: {v[:80]}")
        print("─" * 60)
