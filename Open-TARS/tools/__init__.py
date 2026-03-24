"""Tool registry — auto-discovers all tool scripts in this directory."""

import importlib
from pathlib import Path

_REGISTRY: dict[str, object] = {}


def _discover():
    tools_dir = Path(__file__).parent
    for f in sorted(tools_dir.glob("*.py")):
        if f.stem.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"tools.{f.stem}")
            if hasattr(mod, "NAME") and hasattr(mod, "run"):
                _REGISTRY[mod.NAME] = mod
        except Exception as e:
            print(f"    ⚠️ Failed to load tool {f.stem}: {e}")


_discover()


def get(name: str):
    return _REGISTRY.get(name)


def exists(name: str) -> bool:
    return name in _REGISTRY


def all_names() -> list[str]:
    return list(_REGISTRY.keys())


def run_tool(name: str, params: dict) -> list[dict]:
    tool = _REGISTRY.get(name)
    if not tool:
        raise ValueError(f"Unknown tool: {name}")
    return tool.run(params)


def required_params(name: str) -> list[str]:
    tool = _REGISTRY.get(name)
    return list(getattr(tool, "REQUIRED", [])) if tool else []


def load_tool_docs() -> str:
    """Load TOOL.md as LLM context — injected into tactician prompt."""
    docs = Path(__file__).parent / "TOOL.md"
    return docs.read_text() if docs.exists() else ""
