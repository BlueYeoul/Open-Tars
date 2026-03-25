"""Response parser, natural-language toolbox resolver, and plan validator."""

import re
import tools

CHECKPOINT_ERROR_SIGNALS = [
    "404", "403", "page not found", "access denied", "connection refused",
    "error loading", "failed to load", "site can't be reached", "unable to connect",
]


# ── Natural-language toolbox resolver ──
# Maps free-form descriptions to structured tool/action dicts.

def _auto_save_key(description: str) -> str:
    """Generate a memory key from a description."""
    words = re.findall(r'\w+', description.lower())
    key_words = [w for w in words if w not in {"the", "a", "an", "and", "or", "from", "on", "to", "of", "in", "for"}]
    return "_".join(key_words[:3]) or "data"


def resolve_toolbox(name: str) -> dict:
    """Resolve a natural language toolbox description to a structured action dict.

    If the name matches a known tool directly, returns it as-is.
    Otherwise, pattern-matches the description to infer tool + params.
    """
    # Already a known tool name — pass through
    if tools.exists(name):
        return {"type": "toolbox", "name": name}

    nl = name.lower().strip()

    # ── URL present → OPEN_URL ──
    url_match = re.search(r'https?://\S+', name)
    if url_match:
        return {"type": "toolbox", "name": "OPEN_URL", "url": url_match.group().rstrip(".,)")}

    # ── Search / Google / Find ──
    search_prefixes = r'^(?:search(?:\s+(?:google|for|on google))?|google(?:\s+for)?|find|look up|lookup)\s+'
    if re.match(search_prefixes, nl):
        query = re.sub(search_prefixes, '', name, flags=re.IGNORECASE).strip('" ')
        return {"type": "toolbox", "name": "SEARCH", "query": query}

    # ── Navigate / Go to / Open (no URL → search) ──
    nav_match = re.match(r'^(?:navigate to|go to|open|visit)\s+(.+)$', nl)
    if nav_match:
        target = nav_match.group(1).strip()
        if target.startswith("http"):
            return {"type": "toolbox", "name": "OPEN_URL", "url": target}
        return {"type": "toolbox", "name": "SEARCH", "query": target}

    # ── Read / Extract / Get / Scrape ──
    read_match = re.match(r'^(?:read|extract|get|scrape|collect)\s+(.+)$', nl)
    if read_match:
        rest = read_match.group(1).strip()
        save_match = re.search(r'\s+(?:and\s+)?save(?:\s+(?:as|to))?\s+(\w+)', rest, re.IGNORECASE)
        if save_match:
            save_to = save_match.group(1)
            target = rest[:save_match.start()].strip()
        else:
            target = rest
            save_to = _auto_save_key(target)
        return {"type": "toolbox", "name": "READ_PAGE", "target": target, "save_to": save_to}

    # ── Click / Press / Tap / Select ──
    click_match = re.match(r'^(?:click(?:\s+on)?|press|tap|select)\s+(?:the\s+)?(.+)$', nl)
    if click_match:
        target = click_match.group(1).strip()
        return {"type": "click", "target": target}

    # ── Double-click ──
    dbl_match = re.match(r'^(?:double.?click(?:\s+on)?)\s+(?:the\s+)?(.+)$', nl)
    if dbl_match:
        return {"type": "doubleclick", "target": dbl_match.group(1).strip()}

    # ── Scroll ──
    if "scroll" in nl:
        direction = "up" if "up" in nl else "down"
        amount_match = re.search(r'(\d+)', nl)
        amount = int(amount_match.group(1)) if amount_match else 3
        return {"type": "scroll", "direction": direction, "amount": amount}

    # ── Type / Enter ──
    type_match = re.match(r'^(?:type|enter|input)\s+(.+)$', nl)
    if type_match:
        return {"type": "type", "text": type_match.group(1).strip('" ')}

    # ── Wait ──
    if "wait" in nl:
        secs_match = re.search(r'(\d+)', nl)
        return {"type": "wait", "seconds": int(secs_match.group(1)) if secs_match else 2}

    # ── Fallback: treat as a search ──
    print(f"    ⚠️ Resolver fallback: treating '{name[:60]}' as SEARCH query")
    return {"type": "toolbox", "name": "SEARCH", "query": name}


def resolve_actions(actions: list[dict]) -> list[dict]:
    """Resolve all toolbox natural-language names to structured tool calls.

    Priority:
      1. Toolbox has inline actions  → name is just a label, execute inline as-is
      2. Name matches a known tool   → use registry (keep existing params)
      3. Name is natural language    → resolve to tool + params via NL patterns
    """
    resolved = []
    for action in actions:
        if action.get("type") == "toolbox":
            tb_name = action.get("name", "")
            inline = action.get("actions")

            if inline:
                # Inline actions are the implementation — name is only a label
                resolved.append(action)
            elif tools.exists(tb_name):
                resolved.append(action)
            else:
                extra = {k: v for k, v in action.items() if k not in ("type", "name", "actions")}
                r = resolve_toolbox(tb_name)
                r.update(extra)
                print(f"    🔀 Resolved: '{tb_name[:60]}' → {r}")
                resolved.append(r)
        else:
            resolved.append(action)
    return resolved


# ── Response parser ──

def _parse_atomic(text: str) -> list[dict]:
    """Parse only atomic action tags (no toolbox). Used for inline toolbox bodies."""
    items = []
    for m in re.finditer(r"<as>(.*?)</as>", text, re.DOTALL):
        items.append((m.start(), {"type": "applescript", "code": m.group(1).strip()}))
    for m in re.finditer(r'<click\s+target="(.*?)"\s*/>', text):
        items.append((m.start(), {"type": "click", "target": m.group(1)}))
    for m in re.finditer(r'<doubleclick\s+target="(.*?)"\s*/>', text):
        items.append((m.start(), {"type": "doubleclick", "target": m.group(1)}))
    for m in re.finditer(r'<type\s+text="(.*?)"\s*/>', text):
        items.append((m.start(), {"type": "type", "text": m.group(1)}))
    for m in re.finditer(r'<hotkey\s+keys="(.*?)"\s*/>', text):
        items.append((m.start(), {"type": "hotkey", "keys": m.group(1)}))
    for m in re.finditer(r'<scroll\s+direction="(\w+)"(?:\s+amount="(\d+)")?\s*/>', text):
        items.append((m.start(), {"type": "scroll", "direction": m.group(1),
                                  "amount": int(m.group(2)) if m.group(2) else 3}))
    for m in re.finditer(r'<wait\s+seconds="(\d+)"\s*/>', text):
        items.append((m.start(), {"type": "wait", "seconds": int(m.group(1))}))
    for m in re.finditer(r'<move\s+dx="([+-]?\d+)"\s+dy="([+-]?\d+)"\s*/>', text):
        items.append((m.start(), {"type": "move", "dx": int(m.group(1)), "dy": int(m.group(2))}))
    for m in re.finditer(r'<read\s+target="(.*?)"\s+save_to="(.*?)"\s*/>', text):
        items.append((m.start(), {"type": "read", "target": m.group(1), "save_to": m.group(2)}))
    for m in re.finditer(r'<memory\s+key="(.*?)">(.*?)</memory>', text, re.DOTALL):
        items.append((m.start(), {"type": "memory", "key": m.group(1), "value": m.group(2).strip()}))
    items.sort(key=lambda x: x[0])
    return [a for _, a in items]


def parse_response(text: str) -> list[dict]:
    """Parse LLM response XML tags into an ordered list of action dicts.

    Supports:
      <toolbox name="natural language or TOOL_NAME">   (paired — atomic actions inside)
        <click target="..."/>
        <wait seconds="2"/>
      </toolbox>

      <toolbox name="TOOL_NAME" param="val"/>           (self-closing structured)
    """
    matches = []

    # Track spans occupied by paired toolbox blocks so we don't double-parse their contents
    paired_spans: list[tuple[int, int]] = []

    # ── Paired tags first: <toolbox name="...">...</toolbox> ──
    for m in re.finditer(r'<toolbox\s+name="([^"]+)"(?:[^>]*)(?<!/)>\s*(.*?)\s*</toolbox>', text, re.DOTALL):
        name = m.group(1)
        inner = m.group(2).strip()
        action: dict = {"type": "toolbox", "name": name}
        if inner:
            inner_actions = _parse_atomic(inner)
            if inner_actions:
                action["actions"] = inner_actions
        matches.append((m.start(), action))
        paired_spans.append((m.start(), m.end()))

    def _in_paired(pos: int) -> bool:
        return any(s <= pos < e for s, e in paired_spans)

    # ── Self-closing: <toolbox name="..." .../> (outside paired spans) ──
    for m in re.finditer(r'<toolbox\s+name="([^"]+)"([^>]*)/>', text):
        if _in_paired(m.start()):
            continue
        name = m.group(1)
        extra_attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(2)))
        matches.append((m.start(), {"type": "toolbox", "name": name, **extra_attrs}))

    # ── Atomic actions (outside paired toolbox spans) ──
    def add(pos, action):
        if not _in_paired(pos):
            matches.append((pos, action))

    for m in re.finditer(r"<as>(.*?)</as>", text, re.DOTALL):
        add(m.start(), {"type": "applescript", "code": m.group(1).strip()})
    for m in re.finditer(r'<click\s+target="(.*?)"\s*/>', text):
        add(m.start(), {"type": "click", "target": m.group(1)})
    for m in re.finditer(r'<doubleclick\s+target="(.*?)"\s*/>', text):
        add(m.start(), {"type": "doubleclick", "target": m.group(1)})
    for m in re.finditer(r'<type\s+text="(.*?)"\s*/>', text):
        add(m.start(), {"type": "type", "text": m.group(1)})
    for m in re.finditer(r'<hotkey\s+keys="(.*?)"\s*/>', text):
        add(m.start(), {"type": "hotkey", "keys": m.group(1)})
    for m in re.finditer(r'<scroll\s+direction="(\w+)"(?:\s+amount="(\d+)")?\s*/>', text):
        add(m.start(), {"type": "scroll", "direction": m.group(1),
                        "amount": int(m.group(2)) if m.group(2) else 3})
    for m in re.finditer(r'<wait\s+seconds="(\d+)"\s*/>', text):
        add(m.start(), {"type": "wait", "seconds": int(m.group(1))})
    for m in re.finditer(r'<read\s+target="(.*?)"\s+save_to="(.*?)"\s*/>', text):
        add(m.start(), {"type": "read", "target": m.group(1), "save_to": m.group(2)})
    for m in re.finditer(r'<memory\s+key="(.*?)">(.*?)</memory>', text, re.DOTALL):
        add(m.start(), {"type": "memory", "key": m.group(1), "value": m.group(2).strip()})
    for m in re.finditer(r'<done\s*/>', text):
        add(m.start(), {"type": "done"})

    matches.sort(key=lambda x: x[0])

    actions = []
    for _, action in matches:
        if not actions or action != actions[-1]:
            actions.append(action)

    if not actions:
        m = re.search(r'(tell\s+application\s+".*?".*)', text, re.DOTALL)
        if m:
            actions.append({"type": "applescript", "code": m.group(1).strip()})

    return actions


# ── Plan validator ──

def validate_plan(actions: list[dict]) -> tuple[bool, list[str]]:
    """Validate resolved actions for missing params and contradictions."""
    errors: list[str] = []

    if not actions:
        return False, ["Empty plan: no actions generated"]

    # <done/> alone is a valid plan — Tactician signaling goal completion
    if len(actions) == 1 and actions[0].get("type") == "done":
        return True, []

    ACTION_REQUIRED: dict[str, list[str]] = {
        "click": ["target"],
        "doubleclick": ["target"],
        "type": ["text"],
        "hotkey": ["keys"],
        "scroll": ["direction"],
        "wait": ["seconds"],
        "read": ["target", "save_to"],
        "applescript": ["code"],
        "memory": ["key", "value"],
    }

    has_navigation = False
    seen_done = False

    for i, action in enumerate(actions):
        atype = action.get("type", "")

        if seen_done:
            errors.append(f"[{i}] Action after <done/>: {atype}")
            continue
        if atype == "done":
            seen_done = True
            continue

        if atype == "toolbox":
            tb_name = action.get("name", "")
            inline = action.get("actions")
            if not tb_name:
                errors.append(f"[{i}] Toolbox missing name")
                continue
            if inline:
                # Inline actions are the implementation — name is a label, skip registry check
                continue
            if not tools.exists(tb_name):
                errors.append(f"[{i}] Unknown tool '{tb_name}' after resolution")
                continue
            for param in tools.required_params(tb_name):
                if not action.get(param):
                    errors.append(f"[{i}] {tb_name} missing '{param}'")
            if tb_name == "OPEN_URL":
                url = action.get("url", "")
                if url and not url.startswith(("http://", "https://")):
                    errors.append(f"[{i}] OPEN_URL invalid URL: '{url[:60]}'")
                has_navigation = True
            if tb_name == "SEARCH":
                has_navigation = True

        elif atype in ACTION_REQUIRED:
            for param in ACTION_REQUIRED[atype]:
                if param not in action:
                    errors.append(f"[{i}] '{atype}' missing '{param}'")

        if atype == "toolbox" and action.get("name") == "READ_PAGE" and not has_navigation:
            print(f"    ⚠️ READ_PAGE before navigation — assumes content already on screen")

        if i > 0 and actions[i] == actions[i - 1] and atype not in ("wait", "scroll"):
            errors.append(f"[{i}] Duplicate consecutive action")

    return len(errors) == 0, errors
