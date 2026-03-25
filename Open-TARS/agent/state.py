"""AgentState and Todo dataclasses."""

from dataclasses import dataclass, field

# ── ANSI helpers ──
DIM    = "\033[2m"
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"


@dataclass
class Todo:
    id: int
    description: str
    status: str = "pending"   # pending / done / failed / skipped
    attempts: int = 0


@dataclass
class AgentState:
    task: str
    todos: list[Todo] = field(default_factory=list)
    memory: dict[str, str] = field(default_factory=dict)
    _next_id: int = 1

    def add_todo(self, desc: str) -> Todo:
        """Append a new goal at the end of the list."""
        t = Todo(id=self._next_id, description=desc)
        self._next_id += 1
        self.todos.append(t)
        return t

    def insert_todo(self, desc: str, after_id: int) -> Todo | None:
        """Insert a new goal right after the todo with the given id.

        Returns the new Todo, or None if after_id was not found.
        """
        for idx, t in enumerate(self.todos):
            if t.id == after_id:
                new = Todo(id=self._next_id, description=desc)
                self._next_id += 1
                self.todos.insert(idx + 1, new)
                return new
        return None

    def next_pending(self) -> "Todo | None":
        return next((t for t in self.todos if t.status == "pending"), None)

    def set_memory(self, key: str, value: str):
        self.memory[key] = value
        print(f"    💾 Memory[{key}] = {value[:80]}{'...' if len(value) > 80 else ''}")

    def print_status(self):
        print(f"{DIM}{'─'*60}{RESET}")
        print(f"  {BOLD}TODOs:{RESET}")
        icons = {
            "pending": f"  {DIM}[ ]{RESET}",
            "done":    f"  {GREEN}[✓]{RESET}",
            "failed":  f"  {RED}[✗]{RESET}",
            "skipped": f"  {YELLOW}[-]{RESET}",
        }
        for t in self.todos:
            icon = icons.get(t.status, "  [?]")
            marker = f" {CYAN}◀ next{RESET}" if t.status == "pending" and t == self.next_pending() else ""
            print(f"  {icon} {t.id}. {t.description}{marker}")
        if self.memory:
            print(f"\n  {BOLD}Memory{RESET} ({len(self.memory)} items):")
            for k, v in list(self.memory.items())[-5:]:
                print(f"    💾 {k}: {v[:80]}")
        print(f"{DIM}{'─'*60}{RESET}")
